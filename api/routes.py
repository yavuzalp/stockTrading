"""
api/routes.py — FastAPI HTTP routes + WebSocket connection manager.
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import (
    AgentLog, Signal, Order, Portfolio, TradingCycle, get_db, TradeMode
)
from models.schemas import (
    AgentLogOut, SignalOut, OrderOut, PortfolioOut,
    CycleOut, DashboardSummary, PortfolioSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── WebSocket Connection Manager ───────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("WS client connected (%d total)", len(self._connections))

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self._connections = [c for c in self._connections if c != ws]
        logger.info("WS client disconnected (%d total)", len(self._connections))

    async def broadcast(self, payload: dict):
        """Broadcast a message to all connected WebSocket clients."""
        if not self._connections:
            return
        data = json.dumps(payload, default=str)
        dead = []
        async with self._lock:
            conns = list(self._connections)
        for ws in conns:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for d in dead:
            await self.disconnect(d)


manager = ConnectionManager()


# ── WebSocket endpoint ─────────────────────────────────────────────────────────
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


# ── REST Endpoints ─────────────────────────────────────────────────────────────
@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """Full dashboard summary: latest cycle, portfolios, orders, logs."""
    from orchestrator import orchestrator

    # Latest cycle
    cycle_row = (await db.execute(
        select(TradingCycle).order_by(desc(TradingCycle.id)).limit(1)
    )).scalar_one_or_none()

    # Latest portfolios
    paper_row = (await db.execute(
        select(Portfolio)
        .where(Portfolio.mode == TradeMode.PAPER)
        .order_by(desc(Portfolio.id)).limit(1)
    )).scalar_one_or_none()

    live_row = (await db.execute(
        select(Portfolio)
        .where(Portfolio.mode == TradeMode.LIVE)
        .order_by(desc(Portfolio.id)).limit(1)
    )).scalar_one_or_none()

    # Recent orders (last 20)
    orders = (await db.execute(
        select(Order).order_by(desc(Order.id)).limit(20)
    )).scalars().all()

    # Recent logs (last 50)
    logs = (await db.execute(
        select(AgentLog).order_by(desc(AgentLog.id)).limit(50)
    )).scalars().all()

    agent_statuses = {
        a.agent_id: a._status
        for a in [
            orchestrator.scanner, orchestrator.technicals,
            orchestrator.sentiment, orchestrator.options,
            orchestrator.macro, orchestrator.risk,
            orchestrator.pm, orchestrator.executor,
        ]
    }

    return DashboardSummary(
        current_cycle=CycleOut.model_validate(cycle_row) if cycle_row else None,
        paper_portfolio=PortfolioOut.model_validate(paper_row) if paper_row else None,
        live_portfolio=PortfolioOut.model_validate(live_row) if live_row else None,
        recent_orders=[OrderOut.model_validate(o) for o in orders],
        recent_logs=[AgentLogOut.model_validate(l) for l in reversed(logs)],
        agent_statuses=agent_statuses,
    )


@router.get("/cycles", response_model=list[CycleOut])
async def get_cycles(limit: int = 20, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(TradingCycle).order_by(desc(TradingCycle.id)).limit(limit)
    )).scalars().all()
    return [CycleOut.model_validate(r) for r in rows]


@router.get("/cycles/{cycle_id}/logs", response_model=list[AgentLogOut])
async def get_cycle_logs(cycle_id: int, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(AgentLog)
        .where(AgentLog.cycle_id == cycle_id)
        .order_by(AgentLog.id)
    )).scalars().all()
    return [AgentLogOut.model_validate(r) for r in rows]


@router.get("/cycles/{cycle_id}/signals", response_model=list[SignalOut])
async def get_cycle_signals(cycle_id: int, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Signal)
        .where(Signal.cycle_id == cycle_id)
        .order_by(Signal.id)
    )).scalars().all()
    return [SignalOut.model_validate(r) for r in rows]


@router.get("/orders", response_model=list[OrderOut])
async def get_orders(limit: int = 50, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Order).order_by(desc(Order.id)).limit(limit)
    )).scalars().all()
    return [OrderOut.model_validate(r) for r in rows]


@router.get("/portfolio", response_model=PortfolioSummary)
async def get_portfolio(db: AsyncSession = Depends(get_db)):
    paper = (await db.execute(
        select(Portfolio).where(Portfolio.mode == TradeMode.PAPER)
        .order_by(desc(Portfolio.id)).limit(1)
    )).scalar_one_or_none()
    live = (await db.execute(
        select(Portfolio).where(Portfolio.mode == TradeMode.LIVE)
        .order_by(desc(Portfolio.id)).limit(1)
    )).scalar_one_or_none()
    return PortfolioSummary(
        paper=PortfolioOut.model_validate(paper) if paper else None,
        live=PortfolioOut.model_validate(live)  if live  else None,
    )


@router.get("/portfolio/history")
async def get_portfolio_history(
    mode: str = "PAPER",
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Portfolio)
        .where(Portfolio.mode == TradeMode(mode.upper()))
        .order_by(Portfolio.id)
        .limit(limit)
    )).scalars().all()
    return [
        {"cycle_id": r.cycle_id, "equity": r.equity, "day_pnl": r.day_pnl, "ts": r.created_at}
        for r in rows
    ]


@router.post("/cycle/trigger")
async def trigger_cycle():
    """Manually fire a trading cycle."""
    from orchestrator import orchestrator
    await orchestrator.trigger_now()
    return {"message": "Cycle triggered", "ts": datetime.utcnow().isoformat()}


@router.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}
