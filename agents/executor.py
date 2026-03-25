"""
agents/executor.py — Executor Agent

Receives approved orders from the Portfolio Manager and routes them
to BOTH the paper and live Alpaca accounts simultaneously via bracket orders.
Tracks fills and reports execution quality.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from brokers.base_broker import BaseBroker
from models.database import Order, OrderStatus

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    agent_id    = "executor"
    agent_name  = "EXECUTOR"
    agent_color = "#2dd4bf"

    def __init__(self, paper_broker: BaseBroker, live_broker: BaseBroker):
        super().__init__()
        self.paper_broker = paper_broker
        self.live_broker  = live_broker

    @property
    def system_prompt(self) -> str:
        # Executor is deterministic — Claude is only used for execution quality reports
        return """You are the Trade Execution Quality Analyst.
Given execution details (submitted price vs fill price, slippage, timing),
assess execution quality and flag any issues. Return JSON:
{
  "execution_quality": "EXCELLENT" | "GOOD" | "FAIR" | "POOR",
  "slippage_assessment": str,
  "recommendations": str
}
"""

    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        approved_orders: list[dict] = context.get("approved_orders", [])
        risk_state = context.get("risk_state", {})

        if not approved_orders:
            await self.log(db, cycle_id, "No orders to execute this cycle")
            return {"execution_results": []}

        await self.log(
            db, cycle_id,
            f"Routing {len(approved_orders)} orders to PAPER + LIVE simultaneously",
        )

        # Execute all orders in parallel (paper and live side by side)
        tasks = [
            self._execute_order(order_data, risk_state, cycle_id, db)
            for order_data in approved_orders
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful = [r for r in results if isinstance(r, dict) and r.get("success")]
        failed     = [r for r in results if isinstance(r, Exception) or
                      (isinstance(r, dict) and not r.get("success"))]

        await self.log(
            db, cycle_id,
            f"Execution complete: {len(successful)} filled, {len(failed)} failed",
            metadata={"successful": len(successful), "failed": len(failed)},
        )
        return {"execution_results": results}

    async def _execute_order(
        self,
        order_data: dict,
        risk_state: dict,
        cycle_id: int,
        db: AsyncSession,
    ) -> dict:
        symbol     = order_data["symbol"]
        side       = order_data["side"].lower()
        qty        = order_data["qty"]
        limit_p    = order_data.get("limit_price")
        stop_p     = order_data.get("stop_price")
        tp_p       = order_data.get("take_profit_price")
        order_obj: Order = order_data.get("order_obj")

        results = {"symbol": symbol, "success": False, "paper": None, "live": None}

        # ── Paper execution ────────────────────────────────────────────────────
        if not risk_state.get("halt_paper"):
            try:
                if stop_p and tp_p and limit_p:
                    paper_result = await self.paper_broker.submit_bracket_order(
                        symbol, side, qty, limit_p, tp_p, stop_p
                    )
                elif limit_p:
                    paper_result = await self.paper_broker.submit_limit_order(
                        symbol, side, qty, limit_p
                    )
                else:
                    paper_result = await self.paper_broker.submit_market_order(
                        symbol, side, qty
                    )

                if order_obj:
                    order_obj.paper_order_id = paper_result.broker_order_id
                    order_obj.paper_status   = OrderStatus(paper_result.status.upper())
                    if paper_result.filled_avg_price:
                        order_obj.paper_fill_price = paper_result.filled_avg_price

                results["paper"] = paper_result.__dict__
                await self.log(
                    db, cycle_id,
                    f"PAPER {side.upper()} {qty}sh {symbol} @ ${limit_p:.2f} → "
                    f"order_id={paper_result.broker_order_id} status={paper_result.status}",
                )
            except Exception as e:
                await self.log(db, cycle_id, f"PAPER order failed for {symbol}: {e}", "ERROR")
                if order_obj:
                    order_obj.paper_status = OrderStatus.REJECTED

        # ── Live execution ─────────────────────────────────────────────────────
        if not risk_state.get("halt_live"):
            try:
                if stop_p and tp_p and limit_p:
                    live_result = await self.live_broker.submit_bracket_order(
                        symbol, side, qty, limit_p, tp_p, stop_p
                    )
                elif limit_p:
                    live_result = await self.live_broker.submit_limit_order(
                        symbol, side, qty, limit_p
                    )
                else:
                    live_result = await self.live_broker.submit_market_order(
                        symbol, side, qty
                    )

                if order_obj:
                    order_obj.live_order_id = live_result.broker_order_id
                    order_obj.live_status   = OrderStatus(live_result.status.upper())
                    if live_result.filled_avg_price:
                        order_obj.live_fill_price = live_result.filled_avg_price

                results["live"] = live_result.__dict__

                slippage = 0.0
                if limit_p and live_result.filled_avg_price:
                    slippage = abs(live_result.filled_avg_price - limit_p)

                await self.log(
                    db, cycle_id,
                    f"LIVE  {side.upper()} {qty}sh {symbol} @ ${limit_p:.2f} → "
                    f"order_id={live_result.broker_order_id} "
                    f"fill=${live_result.filled_avg_price or 'pending':.2f} "
                    f"slippage=${slippage:.3f}",
                )
            except Exception as e:
                await self.log(db, cycle_id, f"LIVE order failed for {symbol}: {e}", "ERROR")
                if order_obj:
                    order_obj.live_status = OrderStatus.REJECTED

        results["success"] = bool(results["paper"] or results["live"])
        return results
