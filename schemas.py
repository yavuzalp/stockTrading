"""
models/schemas.py — Pydantic v2 schemas for FastAPI request/response bodies
and WebSocket event payloads.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from models.database import TradeSide, TradeMode, OrderStatus, AgentStatus


# ── WebSocket Event ────────────────────────────────────────────────────────────
class WSEvent(BaseModel):
    """Generic envelope pushed over the WebSocket connection."""
    event: str                   # e.g. "agent_log", "order", "portfolio", "cycle"
    payload: dict[str, Any]
    ts: datetime = Field(default_factory=datetime.utcnow)


# ── Agent ──────────────────────────────────────────────────────────────────────
class AgentLogOut(BaseModel):
    id: int
    cycle_id: int
    agent_id: str
    agent_name: str
    message: str
    level: str
    metadata_json: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Signal ─────────────────────────────────────────────────────────────────────
class SignalOut(BaseModel):
    id: int
    cycle_id: int
    symbol: str
    source_agent: str
    direction: TradeSide
    conviction: float
    reasoning: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Order ──────────────────────────────────────────────────────────────────────
class OrderOut(BaseModel):
    id: int
    cycle_id: int
    symbol: str
    side: TradeSide
    qty: float
    limit_price: float | None
    stop_price: float | None
    take_profit_price: float | None
    paper_status: OrderStatus
    live_status: OrderStatus
    paper_fill_price: float | None
    live_fill_price: float | None
    pm_conviction: float
    pm_reasoning: str
    risk_approved: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Portfolio ──────────────────────────────────────────────────────────────────
class PortfolioOut(BaseModel):
    id: int
    cycle_id: int
    mode: TradeMode
    equity: float
    cash: float
    day_pnl: float
    total_pnl: float
    positions_json: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


class PortfolioSummary(BaseModel):
    paper: PortfolioOut | None = None
    live: PortfolioOut | None = None


# ── Cycle ──────────────────────────────────────────────────────────────────────
class CycleOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    candidates_count: int
    signals_generated: int
    orders_placed: int
    status: str

    class Config:
        from_attributes = True


# ── Dashboard Summary (REST) ───────────────────────────────────────────────────
class DashboardSummary(BaseModel):
    current_cycle: CycleOut | None
    paper_portfolio: PortfolioOut | None
    live_portfolio: PortfolioOut | None
    recent_orders: list[OrderOut]
    recent_logs: list[AgentLogOut]
    agent_statuses: dict[str, AgentStatus]
