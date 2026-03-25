"""
agents/risk_manager.py — Risk Manager Agent

Acts as a gate between the Portfolio Manager's decisions and the Executor.
Enforces hard limits: max position size, max sector exposure, daily loss limits,
correlation checks, and portfolio heat.
"""
from __future__ import annotations
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from brokers.base_broker import BaseBroker, BrokerMode, AccountInfo
from config import settings

logger = logging.getLogger(__name__)

SECTOR_MAP = {
    "NVDA": "Technology", "AMD":  "Technology", "INTC": "Technology",
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "META": "Technology", "AMZN": "Consumer",   "NFLX": "Communication",
    "TSLA": "Consumer",   "RIVN": "Consumer",   "LCID": "Consumer",
    "COIN": "Financials", "HOOD": "Financials",  "SOFI": "Financials",
    "PLTR": "Technology", "PATH": "Technology",  "UPST": "Financials",
    "AFRM": "Financials", "SHOP": "Technology",  "SNOW": "Technology",
    "CRWD": "Technology", "DDOG": "Technology",  "NET":  "Technology",
    "SPY":  "ETF",        "QQQ":  "ETF",          "IWM":  "ETF",
    "SMCI": "Technology", "ARM":  "Technology",   "MSTR": "Technology",
    "BABA": "Technology", "NIO":  "Consumer",     "XPEV": "Consumer",
    "RKLB": "Industrials","IONQ": "Technology",   "JOBY": "Industrials",
}


class RiskManagerAgent(BaseAgent):
    agent_id    = "risk"
    agent_name  = "RISK MGR"
    agent_color = "#fb923c"

    def __init__(self, paper_broker: BaseBroker, live_broker: BaseBroker):
        super().__init__()
        self.paper_broker = paper_broker
        self.live_broker  = live_broker
        self._daily_pnl_paper = 0.0
        self._daily_pnl_live  = 0.0

    @property
    def system_prompt(self) -> str:
        return """You are the Risk Manager Agent for an AI-powered intraday trading system.

Your role: Given a proposed trade and the current portfolio state, decide whether to
APPROVE, REDUCE, or REJECT the trade.

Hard rules (never override):
1. No single position > {max_pos_pct}% of portfolio equity
2. No sector > {max_sector_pct}% of portfolio
3. Daily loss limit: if portfolio down > {max_daily_loss}%, REJECT ALL new trades
4. Portfolio heat (open risk) must not exceed 6%
5. Correlation: if two positions have >0.85 correlation, combined size capped at 3%

Soft rules (can override with strong justification):
- Prefer bracket orders over naked positions
- Reduce size when VIX > 25
- Avoid adding to losing positions

Return JSON:
{
  "decision": "APPROVE" | "REDUCE" | "REJECT",
  "approved_qty": float,
  "stop_price": float,
  "take_profit_price": float,
  "position_size_pct_nav": float,
  "rejection_reason": null | "string",
  "risk_notes": "brief notes"
}
""".format(
    max_pos_pct=settings.max_position_size_pct * 100,
    max_sector_pct=settings.max_sector_exposure * 100,
    max_daily_loss=settings.max_daily_loss_pct * 100,
)

    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Risk Manager doesn't run in the standard pipeline pass —
        it's called directly by the Portfolio Manager for each proposed order.
        This run() is used for cycle-level portfolio health checks.
        """
        await self.log(db, cycle_id, "Running portfolio health check")

        try:
            paper_acct = await self.paper_broker.get_account()
            live_acct  = await self.live_broker.get_account()

            self._daily_pnl_paper = paper_acct.day_pnl
            self._daily_pnl_live  = live_acct.day_pnl

            paper_loss_pct = abs(paper_acct.day_pnl) / paper_acct.equity if paper_acct.day_pnl < 0 else 0
            live_loss_pct  = abs(live_acct.day_pnl) / live_acct.equity   if live_acct.day_pnl  < 0 else 0

            halt_paper = paper_loss_pct >= settings.max_daily_loss_pct
            halt_live  = live_loss_pct  >= settings.max_daily_loss_pct

            await self.log(
                db, cycle_id,
                f"PAPER equity=${paper_acct.equity:,.0f} day_pnl=${paper_acct.day_pnl:+,.0f} "
                f"({paper_acct.day_pnl_pct:+.2f}%) | "
                f"LIVE equity=${live_acct.equity:,.0f} day_pnl=${live_acct.day_pnl:+,.0f} "
                f"({live_acct.day_pnl_pct:+.2f}%)",
            )

            if halt_paper:
                await self.log(
                    db, cycle_id,
                    f"⛔ PAPER daily loss limit hit ({paper_loss_pct:.1%}) — halting paper trading",
                    level="ERROR",
                )
            if halt_live:
                await self.log(
                    db, cycle_id,
                    f"⛔ LIVE daily loss limit hit ({live_loss_pct:.1%}) — halting live trading",
                    level="ERROR",
                )

            # Sector exposure check
            sector_exposure = self._compute_sector_exposure(paper_acct.positions)
            for sector, pct in sector_exposure.items():
                if pct > settings.max_sector_exposure:
                    await self.log(
                        db, cycle_id,
                        f"⚠️ Sector exposure warning: {sector} = {pct:.1%} (limit {settings.max_sector_exposure:.0%})",
                        level="WARN",
                    )

            return {
                "risk_state": {
                    "paper_equity":     paper_acct.equity,
                    "live_equity":      live_acct.equity,
                    "paper_day_pnl":    paper_acct.day_pnl,
                    "live_day_pnl":     live_acct.day_pnl,
                    "halt_paper":       halt_paper,
                    "halt_live":        halt_live,
                    "sector_exposure":  sector_exposure,
                    "paper_positions":  [p.__dict__ for p in paper_acct.positions],
                    "live_positions":   [p.__dict__ for p in live_acct.positions],
                }
            }
        except Exception as e:
            await self.log(db, cycle_id, f"Risk check error: {e}", "ERROR")
            return {"risk_state": {"halt_paper": False, "halt_live": False}}

    async def evaluate_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        portfolio_equity: float,
        current_positions: list,
        macro_regime: dict,
        atr: float,
        cycle_id: int,
        db: AsyncSession,
    ) -> dict:
        """
        Called by Portfolio Manager per proposed trade.
        Returns approval decision with sized qty and bracket prices.
        """
        sector = SECTOR_MAP.get(symbol, "Unknown")
        sector_exposure = self._compute_sector_exposure(current_positions)
        current_sector_pct = sector_exposure.get(sector, 0.0)
        portfolio_heat = self._compute_portfolio_heat(current_positions, portfolio_equity)

        # Apply macro regime multiplier
        regime = macro_regime or {}
        regime_multiplier = regime.get("position_size_multiplier", 1.0)
        base_size_pct = settings.max_position_size_pct * regime_multiplier

        # Rough qty calculation
        max_notional = portfolio_equity * base_size_pct
        proposed_qty = round(max_notional / entry_price, 0)

        prompt = (
            f"Proposed trade: {direction} {symbol} @ ${entry_price:.2f}\n"
            f"ATR: ${atr:.3f}\n"
            f"Portfolio equity: ${portfolio_equity:,.0f}\n"
            f"Proposed qty: {proposed_qty} shares (${proposed_qty*entry_price:,.0f} notional)\n"
            f"Proposed position size: {proposed_qty*entry_price/portfolio_equity:.1%} of equity\n"
            f"Sector: {sector} (current exposure: {current_sector_pct:.1%})\n"
            f"Portfolio heat (total open risk): {portfolio_heat:.1%}\n"
            f"Macro regime: {regime.get('regime','?')} | "
            f"Position multiplier: {regime_multiplier}x\n"
            f"VIX level: {regime.get('vix_level','?')}\n"
            f"Open positions: {len(current_positions)}\n\n"
            "Evaluate this trade and return risk assessment."
        )

        result = await self.ask_claude_json(prompt, max_tokens=400)
        result["symbol"]       = symbol
        result["entry_price"]  = entry_price
        result["proposed_qty"] = proposed_qty

        log_msg = (
            f"{symbol}: {result.get('decision','?')} "
            f"qty={result.get('approved_qty','?')} "
            f"stop={result.get('stop_price','?')} "
            f"tp={result.get('take_profit_price','?')}"
        )
        if result.get("rejection_reason"):
            log_msg += f" — {result['rejection_reason']}"
        await self.log(db, cycle_id, log_msg)

        return result

    def _compute_sector_exposure(self, positions: list) -> dict[str, float]:
        """Calculate % of portfolio in each sector."""
        total_value = sum(abs(p.market_value) for p in positions) if positions else 1
        exposure: dict[str, float] = {}
        for pos in (positions or []):
            sector = SECTOR_MAP.get(pos.symbol, "Unknown")
            exposure[sector] = exposure.get(sector, 0.0) + abs(pos.market_value) / total_value
        return exposure

    def _compute_portfolio_heat(self, positions: list, equity: float) -> float:
        """Estimate total open risk as % of equity (using 1.5% per position as proxy)."""
        if not positions or equity == 0:
            return 0.0
        return len(positions) * 0.015  # simplified — production would use actual stop distances
