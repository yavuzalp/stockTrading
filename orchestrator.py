"""
orchestrator.py — Trading Cycle Orchestrator

Manages the 5-minute agent pipeline:
  Scanner → [Technicals, Sentiment, OptionsFlow, Macro] → RiskMgr → PM → Executor

Runs cycles on APScheduler. Maintains shared state and DB snapshots.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from agents.scanner         import ScannerAgent
from agents.technicals      import TechnicalsAgent
from agents.sentiment       import SentimentAgent
from agents.options_flow    import OptionsFlowAgent
from agents.macro           import MacroAgent
from agents.risk_manager    import RiskManagerAgent
from agents.portfolio_manager import PortfolioManagerAgent
from agents.executor        import ExecutorAgent

from brokers.alpaca_broker  import AlpacaBroker
from brokers.base_broker    import BrokerMode
from models.database        import (
    TradingCycle, Portfolio, AsyncSessionLocal, TradeMode
)
from config import settings

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    """
    Wires up all agents and brokers, schedules the 5-minute cycle,
    and manages graceful start/stop.
    """

    def __init__(self):
        # ── Brokers ────────────────────────────────────────────────────────────
        self.paper_broker = AlpacaBroker(BrokerMode.PAPER)
        self.live_broker  = AlpacaBroker(BrokerMode.LIVE)

        # ── Agents ────────────────────────────────────────────────────────────
        self.scanner    = ScannerAgent(self.paper_broker)         # paper for scanning
        self.technicals = TechnicalsAgent(self.paper_broker)
        self.sentiment  = SentimentAgent()
        self.options    = OptionsFlowAgent()
        self.macro      = MacroAgent()
        self.risk       = RiskManagerAgent(self.paper_broker, self.live_broker)
        self.pm         = PortfolioManagerAgent(self.risk)
        self.executor   = ExecutorAgent(self.paper_broker, self.live_broker)

        self._scheduler  = AsyncIOScheduler()
        self._running    = False
        self._cycle_lock = asyncio.Lock()
        self.current_cycle_id: int | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    def start(self):
        interval = settings.cycle_interval_seconds
        self._scheduler.add_job(
            self._safe_run_cycle,
            "interval",
            seconds=interval,
            id="trading_cycle",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info("Orchestrator started — cycle every %ds", interval)

    def stop(self):
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Orchestrator stopped")

    async def trigger_now(self):
        """Manually trigger a cycle (used by API endpoint)."""
        asyncio.create_task(self._safe_run_cycle())

    # ── Cycle ──────────────────────────────────────────────────────────────────
    async def _safe_run_cycle(self):
        if self._cycle_lock.locked():
            logger.warning("Previous cycle still running — skipping")
            return
        async with self._cycle_lock:
            await self._run_cycle()

    async def _run_cycle(self):
        async with AsyncSessionLocal() as db:
            # Create cycle record
            cycle = TradingCycle(started_at=datetime.utcnow(), status="RUNNING")
            db.add(cycle)
            await db.flush()
            self.current_cycle_id = cycle.id
            logger.info("=== CYCLE %d START ===", cycle.id)

            context: dict[str, Any] = {}

            try:
                # ── 1. Check market open ──────────────────────────────────────
                if not await self.paper_broker.is_market_open():
                    logger.info("Market is closed — skipping cycle %d", cycle.id)
                    cycle.status = "SKIPPED"
                    await db.commit()
                    return

                # ── 2. Scanner ────────────────────────────────────────────────
                scanner_out = await self.scanner.execute(cycle.id, context, db)
                context.update(scanner_out)
                cycle.candidates_count = len(context.get("candidates", []))

                # ── 3. Parallel analysis layer ────────────────────────────────
                tech_task      = self.technicals.execute(cycle.id, context, db)
                sentiment_task = self.sentiment.execute(cycle.id, context, db)
                options_task   = self.options.execute(cycle.id, context, db)
                macro_task     = self.macro.execute(cycle.id, context, db)
                risk_task      = self.risk.execute(cycle.id, context, db)

                results = await asyncio.gather(
                    tech_task, sentiment_task, options_task, macro_task, risk_task,
                    return_exceptions=True,
                )

                for r in results:
                    if isinstance(r, dict):
                        context.update(r)
                    elif isinstance(r, Exception):
                        logger.error("Agent error in parallel phase: %s", r)

                # Count signals
                tech_sigs = len([v for v in context.get("tech_signals", {}).values()
                                  if v.get("direction") in ("BUY","SELL")])
                sent_sigs = len([v for v in context.get("sentiment_signals", {}).values()
                                  if v.get("direction") in ("BUY","SELL")])
                cycle.signals_generated = tech_sigs + sent_sigs

                # ── 4. Portfolio Manager ──────────────────────────────────────
                pm_out = await self.pm.execute(cycle.id, context, db)
                context.update(pm_out)

                # ── 5. Executor ───────────────────────────────────────────────
                exec_out = await self.executor.execute(cycle.id, context, db)
                context.update(exec_out)
                cycle.orders_placed = len([r for r in exec_out.get("execution_results", [])
                                            if isinstance(r, dict) and r.get("success")])

                # ── 6. Save portfolio snapshots ───────────────────────────────
                await self._save_portfolio_snapshots(cycle.id, db)

                cycle.status      = "COMPLETE"
                cycle.finished_at = datetime.utcnow()
                await db.commit()

                logger.info(
                    "=== CYCLE %d COMPLETE | candidates=%d signals=%d orders=%d ===",
                    cycle.id, cycle.candidates_count, cycle.signals_generated, cycle.orders_placed,
                )

            except Exception as e:
                logger.exception("Cycle %d crashed: %s", cycle.id, e)
                cycle.status        = "ERROR"
                cycle.error_message = str(e)
                cycle.finished_at   = datetime.utcnow()
                await db.commit()

    async def _save_portfolio_snapshots(self, cycle_id: int, db: AsyncSession):
        """Persist portfolio equity snapshots after each cycle."""
        for mode, broker in [("PAPER", self.paper_broker), ("LIVE", self.live_broker)]:
            try:
                acct = await broker.get_account()
                snap = Portfolio(
                    cycle_id=cycle_id,
                    mode=TradeMode(mode),
                    equity=acct.equity,
                    cash=acct.cash,
                    day_pnl=acct.day_pnl,
                    positions_json=[
                        {
                            "symbol": p.symbol,
                            "qty": p.qty,
                            "market_value": p.market_value,
                            "unrealized_pnl": p.unrealized_pnl,
                        }
                        for p in acct.positions
                    ],
                )
                db.add(snap)
            except Exception as e:
                logger.warning("Portfolio snapshot error [%s]: %s", mode, e)


# Singleton
orchestrator = TradingOrchestrator()
