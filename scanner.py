"""
agents/scanner.py — Scanner Agent

Scans a broad universe of stocks every cycle and narrows down to
high-probability intraday candidates using relative volume, price
momentum, float characteristics, and gap analysis.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from brokers.base_broker import BaseBroker

logger = logging.getLogger(__name__)

# Default watchlist — configurable via env/DB in production
DEFAULT_UNIVERSE = [
    "NVDA","TSLA","AAPL","META","MSFT","GOOGL","AMD","AMZN",
    "NFLX","COIN","SPY","QQQ","SMCI","PLTR","ARM","MSTR",
    "SOFI","HOOD","RIVN","LCID","JOBY","IONQ","RKLB","PATH",
    "UPST","AFRM","SHOP","SNOW","CRWD","S","DDOG","NET",
    "MELI","SE","BIDU","JD","PDD","BABA","NIO","XPEV",
]


class ScannerAgent(BaseAgent):
    agent_id    = "scanner"
    agent_name  = "SCANNER"
    agent_color = "#38bdf8"

    def __init__(self, broker: BaseBroker):
        super().__init__()
        self.broker = broker

    @property
    def system_prompt(self) -> str:
        return """You are the Scanner Agent for an AI-powered intraday trading system.

Your role: Given a snapshot of market data for multiple stocks, identify the TOP candidates
for intraday trades in the current 5-minute cycle.

Scoring criteria (weight each 0-10, compute weighted average):
- Relative Volume (RVOL): vol vs 20-day avg. >2x = score 10
- Price momentum: % change from open / prev close
- Gap quality: clean gap-up/down with volume confirmation
- Float dynamics: smaller float = higher score
- Sector leadership: is the stock leading its sector today?
- Liquidity: avg dollar volume must be >$5M/day
- ATR-adjusted range: is intraday range healthy for scalping?

Return JSON: { "candidates": [ { "symbol": str, "score": float (0-10), "reason": str } ] }
Limit to top 10 candidates, sorted by score descending.
"""

    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        await self.log(db, cycle_id, f"Scanning universe of {len(DEFAULT_UNIVERSE)} symbols...")

        # Fetch snapshots in batches of 20 (API rate limit friendly)
        snapshots: dict = {}
        batch_size = 20
        universe   = DEFAULT_UNIVERSE

        for i in range(0, len(universe), batch_size):
            batch = universe[i : i + batch_size]
            try:
                snap = await self.broker.get_snapshot(batch)
                snapshots.update(snap)
            except Exception as e:
                await self.log(db, cycle_id, f"Snapshot batch {i//batch_size+1} error: {e}", "WARN")

        if not snapshots:
            await self.log(db, cycle_id, "No snapshot data received — skipping cycle", "ERROR")
            return {"candidates": []}

        # Build summary for Claude
        lines = []
        for sym, s in snapshots.items():
            if not s.get("daily_close") or not s.get("prev_close"):
                continue
            change_pct = (s["daily_close"] / s["prev_close"] - 1) * 100 if s["prev_close"] else 0
            lines.append(
                f"{sym}: close={s['daily_close']:.2f} prev={s['prev_close']:.2f} "
                f"chg={change_pct:+.2f}% vol={int(s.get('daily_volume',0)):,} "
                f"vwap={s.get('daily_vwap','N/A')}"
            )

        prompt = (
            f"Market snapshot for cycle #{cycle_id}:\n"
            + "\n".join(lines)
            + "\n\nIdentify the top intraday trading candidates."
        )

        result = await self.ask_claude_json(prompt, max_tokens=800)
        candidates = result.get("candidates", [])

        await self.log(
            db, cycle_id,
            f"Scan complete — {len(candidates)} candidates identified from {len(snapshots)} symbols",
            metadata={"top_candidates": [c["symbol"] for c in candidates[:5]]},
        )

        for c in candidates[:3]:
            await self.log(
                db, cycle_id,
                f"#{candidates.index(c)+1} {c['symbol']} score={c['score']:.1f}/10 — {c['reason']}",
            )

        return {"candidates": candidates, "snapshots": snapshots}
