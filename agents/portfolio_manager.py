"""
agents/portfolio_manager.py — Portfolio Manager Agent (The Decider)

Aggregates signals from Technicals, Sentiment, Options Flow, and Macro agents.
Has FINAL AUTHORITY on every trade. Calls Risk Manager for approval before
passing approved orders to the Executor.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from agents.risk_manager import RiskManagerAgent
from models.database import Order, TradeSide

logger = logging.getLogger(__name__)


class PortfolioManagerAgent(BaseAgent):
    agent_id    = "pm"
    agent_name  = "PORT. MANAGER"
    agent_color = "#fde047"

    def __init__(self, risk_manager: RiskManagerAgent):
        super().__init__()
        self.risk_manager = risk_manager

    @property
    def system_prompt(self) -> str:
        return """You are the Portfolio Manager — the FINAL DECISION MAKER for an AI intraday trading system.

You receive aggregated signals from 4 specialist agents:
1. TECHNICALS   — price action, indicators (most reliable for timing)
2. SENTIMENT    — news and social signals (best for catalyst-driven moves)
3. OPTIONS FLOW — smart money positioning (best leading indicator)
4. MACRO        — regime context (scales position sizing)

Your decision process:
1. Score each agent's signal for the symbol (direction + conviction)
2. Weight signals: Options Flow (35%) > Technicals (30%) > Sentiment (20%) > Macro (15%)
3. Aggregate weighted conviction. If > 0.55 in one direction → TRADE
4. Below 0.55 or conflicting signals → HOLD

Override rules (PM authority):
- You CAN override individual agents if you have strong cross-agent justification
- Options flow sweep at ASK, short DTE, OTM + TA bull cross = maximum override UP
- Conflicting signals with no clear edge → always HOLD (capital preservation)
- Never trade into a binary event (FOMC, earnings) without reducing size 50%

Return JSON for each symbol decision:
{
  "symbol": str,
  "action": "BUY" | "SELL" | "HOLD",
  "conviction": 0.0-1.0,
  "weighted_score": float,
  "signal_breakdown": {
    "technicals": {"direction": str, "conviction": float, "weight": 0.30},
    "sentiment":  {"direction": str, "conviction": float, "weight": 0.20},
    "options":    {"direction": str, "conviction": float, "weight": 0.35},
    "macro":      {"direction": str, "conviction": float, "weight": 0.15}
  },
  "override_applied": false,
  "override_reason": null,
  "reasoning": "max 2 sentences explaining the decision"
}
"""

    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        candidates      = context.get("candidates", [])
        tech_signals    = context.get("tech_signals", {})
        sentiment_signals = context.get("sentiment_signals", {})
        options_signals = context.get("options_signals", {})
        macro_regime    = context.get("macro_regime", {})
        risk_state      = context.get("risk_state", {})

        symbols = [c["symbol"] for c in candidates[:8]]
        if not symbols:
            await self.log(db, cycle_id, "No candidates to evaluate — cycle complete")
            return {"approved_orders": []}

        await self.log(
            db, cycle_id,
            f"Evaluating {len(symbols)} candidates | Regime: {macro_regime.get('regime','?')} "
            f"| Paper halt: {risk_state.get('halt_paper',False)} "
            f"| Live halt: {risk_state.get('halt_live',False)}",
        )

        if risk_state.get("halt_paper") and risk_state.get("halt_live"):
            await self.log(db, cycle_id, "⛔ Both modes halted — no trades this cycle", level="ERROR")
            return {"approved_orders": []}

        # Evaluate each symbol
        tasks = [
            self._evaluate_symbol(
                sym, tech_signals, sentiment_signals, options_signals, macro_regime, cycle_id, db
            )
            for sym in symbols
        ]
        decisions = await asyncio.gather(*tasks, return_exceptions=True)

        approved_orders: list[dict] = []

        for sym, decision in zip(symbols, decisions):
            if isinstance(decision, Exception):
                await self.log(db, cycle_id, f"{sym}: PM evaluation error — {decision}", "WARN")
                continue
            if not decision:
                continue

            action = decision.get("action", "HOLD")
            conviction = decision.get("conviction", 0.0)

            if action == "HOLD":
                await self.log(
                    db, cycle_id,
                    f"HOLD {sym} | conviction={conviction:.0%} | {decision.get('reasoning','')}",
                )
                continue

            await self.log(
                db, cycle_id,
                f"✅ DECISION: {action} {sym} | conviction={conviction:.0%} | "
                f"score={decision.get('weighted_score',0):.2f} | {decision.get('reasoning','')}",
            )

            # Get current price from snapshot
            snapshot = context.get("snapshots", {}).get(sym, {})
            entry_price = snapshot.get("latest_trade_price") or snapshot.get("daily_close")
            if not entry_price:
                await self.log(db, cycle_id, f"{sym}: no price data — skipping", "WARN")
                continue

            # ATR from technicals
            atr = tech_signals.get(sym, {}).get("indicators", {}).get("atr", entry_price * 0.01)

            # Risk Manager approval
            paper_equity = risk_state.get("paper_equity", 100000)
            paper_positions = risk_state.get("paper_positions", [])

            risk_decision = await self.risk_manager.evaluate_trade(
                symbol=sym,
                direction=action,
                entry_price=entry_price,
                portfolio_equity=paper_equity,
                current_positions=paper_positions,
                macro_regime=macro_regime,
                atr=atr,
                cycle_id=cycle_id,
                db=db,
            )

            if risk_decision.get("decision") == "REJECT":
                await self.log(
                    db, cycle_id,
                    f"⛔ REJECTED by Risk Manager: {sym} — {risk_decision.get('rejection_reason','')}",
                    level="WARN",
                )
                continue

            # Build order
            approved_qty   = risk_decision.get("approved_qty", 1)
            stop_price     = risk_decision.get("stop_price")
            tp_price       = risk_decision.get("take_profit_price")

            if approved_qty <= 0:
                continue

            order = Order(
                cycle_id=cycle_id,
                symbol=sym,
                side=TradeSide(action),
                qty=approved_qty,
                limit_price=round(entry_price * (1.001 if action == "BUY" else 0.999), 2),
                stop_price=stop_price,
                take_profit_price=tp_price,
                pm_conviction=conviction,
                pm_reasoning=decision.get("reasoning", ""),
                risk_approved=True,
            )
            db.add(order)
            approved_orders.append({
                "symbol": sym,
                "side":   action,
                "qty":    approved_qty,
                "limit_price": order.limit_price,
                "stop_price": stop_price,
                "take_profit_price": tp_price,
                "pm_conviction": conviction,
                "order_obj": order,
            })

        await db.flush()
        await self.log(
            db, cycle_id,
            f"PM cycle complete — {len(approved_orders)} orders approved for execution",
            metadata={"order_symbols": [o["symbol"] for o in approved_orders]},
        )
        return {"approved_orders": approved_orders}

    async def _evaluate_symbol(
        self,
        symbol: str,
        tech_signals: dict,
        sentiment_signals: dict,
        options_signals: dict,
        macro_regime: dict,
        cycle_id: int,
        db: AsyncSession,
    ) -> dict | None:
        tech      = tech_signals.get(symbol, {})
        sentiment = sentiment_signals.get(symbol, {})
        options   = options_signals.get(symbol, {})

        # Build aggregated signal prompt
        prompt = (
            f"Symbol: {symbol}\n\n"
            f"TECHNICALS signal:\n"
            f"  direction={tech.get('direction','NEUTRAL')} conviction={tech.get('conviction',0):.2f}\n"
            f"  reasoning={tech.get('reasoning','no data')}\n\n"
            f"SENTIMENT signal:\n"
            f"  direction={sentiment.get('direction','NEUTRAL')} conviction={sentiment.get('conviction',0):.2f}\n"
            f"  catalyst={sentiment.get('catalyst','none')}\n"
            f"  risk_flag={sentiment.get('risk_flag',False)}\n\n"
            f"OPTIONS FLOW signal:\n"
            f"  direction={options.get('direction','NEUTRAL')} conviction={options.get('conviction',0):.2f}\n"
            f"  flow_type={options.get('flow_type','?')} notional=${options.get('notional_size_usd',0)/1e6:.1f}M\n"
            f"  squeeze_risk={options.get('squeeze_risk',False)}\n\n"
            f"MACRO REGIME:\n"
            f"  regime={macro_regime.get('regime','NEUTRAL')}\n"
            f"  position_multiplier={macro_regime.get('position_size_multiplier',1.0)}\n"
            f"  event_risk={macro_regime.get('event_risk','LOW')}\n"
            f"  key_event={macro_regime.get('key_event_today','none')}\n\n"
            "Make the final trade decision."
        )

        return await self.ask_claude_json(prompt, max_tokens=700)
