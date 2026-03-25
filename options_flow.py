"""
agents/options_flow.py — Options Flow Agent

Detects unusual options activity: large sweeps, dark pool prints,
high call/put imbalances, and gamma exposure. Uses Tradier or
manually scraped public data when available.
"""
from __future__ import annotations
import asyncio
import logging
import random
from typing import Any

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from models.database import Signal, TradeSide

logger = logging.getLogger(__name__)


class OptionsFlowAgent(BaseAgent):
    agent_id    = "options"
    agent_name  = "OPTIONS FLOW"
    agent_color = "#c084fc"

    @property
    def system_prompt(self) -> str:
        return """You are the Options Flow Analysis Agent for an AI-powered intraday trading system.

You detect and interpret unusual options activity to infer what large institutional
traders are positioning for. This is often the most reliable leading indicator.

Signal types to detect and weight:
1. SWEEP: Large orders split across multiple exchanges at ASK price — urgent, directional
2. BLOCK: Single large print, often a hedge — less directional
3. DARK POOL: Off-exchange large block — accumulation/distribution signal
4. CALL/PUT RATIO: Extreme skew vs 20-day average
5. IV SPIKE: Sudden implied volatility jump — anticipation of large move
6. GAMMA EXPOSURE: Near-term expiry OTM calls/puts — potential gamma squeeze

Scoring:
- Sweep at ask, large notional, short DTE, OTM → highest conviction BUY signal
- Large put block, IV spike, near expiry → SELL / protective signal
- Dark pool at ask = bullish; at bid = bearish

Return JSON:
{
  "direction": "BUY" | "SELL" | "NEUTRAL",
  "conviction": 0.0-1.0,
  "flow_type": "SWEEP" | "BLOCK" | "DARK_POOL" | "RATIO" | "GAMMA",
  "notional_size_usd": float,
  "dte": int,
  "moneyness": "ITM" | "ATM" | "OTM",
  "reasoning": "max 2 sentences",
  "squeeze_risk": true|false
}
"""

    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        candidates = context.get("candidates", [])
        symbols    = [c["symbol"] for c in candidates[:8]]

        if not symbols:
            await self.log(db, cycle_id, "No candidates — skipping options flow scan")
            return {"options_signals": {}}

        await self.log(db, cycle_id, f"Scanning options flow for {len(symbols)} symbols")

        options_signals: dict[str, dict] = {}

        for sym in symbols:
            try:
                flow_data = await self._get_options_flow(sym)
                if not flow_data:
                    continue

                result = await self._analyse_flow(sym, flow_data)
                options_signals[sym] = result

                if result.get("direction") in ("BUY", "SELL") and result.get("conviction", 0) >= 0.45:
                    sig = Signal(
                        cycle_id=cycle_id,
                        symbol=sym,
                        source_agent=self.agent_id,
                        direction=TradeSide(result["direction"]),
                        conviction=result["conviction"],
                        reasoning=result["reasoning"],
                        raw_data={k: v for k, v in result.items() if k != "reasoning"},
                    )
                    db.add(sig)

                    squeeze_flag = " 🔥 SQUEEZE RISK" if result.get("squeeze_risk") else ""
                    notional = result.get("notional_size_usd", 0)
                    await self.log(
                        db, cycle_id,
                        f"{sym}: {result.get('flow_type','?')} {result['direction']} "
                        f"${notional/1e6:.1f}M notional DTE={result.get('dte','?')} "
                        f"{result.get('moneyness','?')} conviction={result['conviction']:.0%}"
                        f"{squeeze_flag}",
                    )
            except Exception as e:
                await self.log(db, cycle_id, f"{sym}: options flow error — {e}", "WARN")

        await db.flush()
        await self.log(
            db, cycle_id,
            f"Options flow scan complete — {len(options_signals)} symbols with unusual activity",
        )
        return {"options_signals": options_signals}

    async def _get_options_flow(self, symbol: str) -> dict | None:
        """
        Fetch options flow data. In production this would connect to:
        - Tradier API (options chains + volume)
        - Unusual Whales API
        - Market Chameleon
        - Self-hosted options scanner

        For now we simulate realistic-looking data structures.
        In real deployment, replace this with actual API calls.
        """
        # TODO: Replace with real options flow API
        # Example Tradier endpoint:
        # GET https://api.tradier.com/v1/markets/options/chains?symbol={symbol}&expiration=...
        #
        # For now — generate realistic synthetic data for testing
        call_volume = random.randint(500, 50000)
        put_volume  = random.randint(500, 50000)
        cp_ratio    = call_volume / max(put_volume, 1)
        avg_cp_ratio = 1.1  # typical baseline

        flow_data = {
            "symbol": symbol,
            "call_volume": call_volume,
            "put_volume": put_volume,
            "call_put_ratio": round(cp_ratio, 2),
            "avg_call_put_ratio": avg_cp_ratio,
            "ratio_vs_avg": round(cp_ratio / avg_cp_ratio, 2),
            "largest_trade": {
                "type": random.choice(["CALL", "PUT"]),
                "side": random.choice(["BUY", "SELL"]),
                "execution": random.choice(["SWEEP", "BLOCK"]),
                "location": random.choice(["ASK", "BID", "MID"]),
                "contracts": random.randint(100, 5000),
                "strike_pct_otm": round(random.uniform(0, 0.05), 3),
                "dte": random.choice([1, 2, 5, 14, 30]),
                "notional_usd": random.randint(50000, 5_000_000),
                "iv": round(random.uniform(0.20, 1.50), 2),
            },
            "dark_pool_prints": random.randint(0, 5),
            "dark_pool_notional": random.randint(0, 10_000_000),
            "iv_rank": round(random.uniform(10, 90), 1),
            "gamma_exposure": round(random.uniform(-1e9, 1e9), 0),
        }
        return flow_data

    async def _analyse_flow(self, symbol: str, flow_data: dict) -> dict:
        prompt = (
            f"Symbol: {symbol}\nOptions flow data:\n"
            + "\n".join(f"  {k}: {v}" for k, v in flow_data.items())
            + "\n\nInterpret this options flow and generate a trading signal."
        )
        return await self.ask_claude_json(prompt, max_tokens=512)
