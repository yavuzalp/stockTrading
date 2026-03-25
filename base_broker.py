"""
brokers/base_broker.py — Abstract broker interface.

To add a new broker (IBKR, TDA, Coinbase, etc.) create a new file
in this directory and subclass BaseBroker, implementing all abstract methods.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class BrokerMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass
class Position:
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    side: str  # "long" | "short"


@dataclass
class AccountInfo:
    mode: BrokerMode
    equity: float
    cash: float
    buying_power: float
    day_pnl: float
    day_pnl_pct: float
    positions: list[Position] = field(default_factory=list)


@dataclass
class OrderResult:
    broker_order_id: str
    symbol: str
    side: str
    qty: float
    status: str
    filled_avg_price: Optional[float] = None
    message: str = ""


@dataclass
class Bar:
    """OHLCV bar."""
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: Optional[float] = None


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int


class BaseBroker(ABC):
    """
    Abstract trading broker interface.
    Every concrete broker must implement all methods below.
    """

    def __init__(self, mode: BrokerMode):
        self.mode = mode

    # ── Account ────────────────────────────────────────────────────────────────
    @abstractmethod
    async def get_account(self) -> AccountInfo:
        """Return current account equity, cash, buying power, P&L."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all open positions."""
        ...

    # ── Market Data ───────────────────────────────────────────────────────────
    @abstractmethod
    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "5Min",
        limit: int = 50,
    ) -> list[Bar]:
        """
        Fetch OHLCV bars.
        timeframe examples: "1Min", "5Min", "15Min", "1H", "1D"
        """
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Fetch latest quote (bid/ask/last)."""
        ...

    @abstractmethod
    async def get_snapshot(self, symbols: list[str]) -> dict[str, dict]:
        """
        Fetch a market snapshot (quote + daily bar) for multiple symbols at once.
        Returns dict keyed by symbol.
        """
        ...

    # ── Orders ─────────────────────────────────────────────────────────────────
    @abstractmethod
    async def submit_market_order(
        self,
        symbol: str,
        side: str,           # "buy" | "sell"
        qty: float,
        time_in_force: str = "day",
    ) -> OrderResult:
        ...

    @abstractmethod
    async def submit_limit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        limit_price: float,
        time_in_force: str = "day",
    ) -> OrderResult:
        ...

    @abstractmethod
    async def submit_bracket_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        limit_price: float,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str = "day",
    ) -> OrderResult:
        """
        Bracket order: entry + attached TP/SL legs.
        Not all brokers support this natively; subclass may simulate it.
        """
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool:
        ...

    @abstractmethod
    async def get_order_status(self, broker_order_id: str) -> OrderResult:
        ...

    # ── Universe ───────────────────────────────────────────────────────────────
    @abstractmethod
    async def get_tradeable_assets(self) -> list[str]:
        """Return list of symbols that can be traded on this broker."""
        ...

    @abstractmethod
    async def is_market_open(self) -> bool:
        """Return True if the market is currently open."""
        ...
