"""
models/database.py — SQLAlchemy ORM models + async engine setup.
"""
from __future__ import annotations
import enum
from datetime import datetime

from sqlalchemy import (
    String, Float, Integer, Boolean, DateTime,
    Enum as SAEnum, ForeignKey, Text, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import settings


# ── Engine / Session Factory ───────────────────────────────────────────────────
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Enums ──────────────────────────────────────────────────────────────────────
class TradeSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeMode(str, enum.Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"
    BOTH = "BOTH"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AgentStatus(str, enum.Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


# ── Base ───────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Models ─────────────────────────────────────────────────────────────────────
class AgentLog(Base):
    """One row per agent action/thought during a cycle."""
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(Integer, index=True)
    agent_id: Mapped[str] = mapped_column(String(64))
    agent_name: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Signal(Base):
    """Tradeable signals produced by analyst agents."""
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    source_agent: Mapped[str] = mapped_column(String(64))
    direction: Mapped[TradeSide] = mapped_column(SAEnum(TradeSide))
    conviction: Mapped[float] = mapped_column(Float)   # 0-1
    reasoning: Mapped[str] = mapped_column(Text)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # back-ref
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="signal")


class Order(Base):
    """An order approved by the Portfolio Manager and sent to the Executor."""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    cycle_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[TradeSide] = mapped_column(SAEnum(TradeSide))
    qty: Mapped[float] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Dual-mode: separate broker order IDs
    paper_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    live_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paper_status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), default=OrderStatus.PENDING)
    live_status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), default=OrderStatus.PENDING)

    paper_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    live_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    pm_conviction: Mapped[float] = mapped_column(Float, default=0.0)
    pm_reasoning: Mapped[str] = mapped_column(Text, default="")
    risk_approved: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal: Mapped["Signal | None"] = relationship("Signal", back_populates="orders")


class Portfolio(Base):
    """Snapshot of portfolio state saved each cycle (both modes)."""
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(Integer)
    mode: Mapped[TradeMode] = mapped_column(SAEnum(TradeMode))
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    day_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    positions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TradingCycle(Base):
    """Metadata about each 5-minute cycle."""
    __tablename__ = "trading_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    candidates_count: Mapped[int] = mapped_column(Integer, default=0)
    signals_generated: Mapped[int] = mapped_column(Integer, default=0)
    orders_placed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
