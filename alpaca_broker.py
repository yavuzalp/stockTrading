"""
brokers/alpaca_broker.py — Alpaca Markets concrete broker implementation.

Supports both Paper and Live trading via alpaca-py SDK.
Paper trading uses a separate Alpaca paper endpoint automatically.
"""
from __future__ import annotations
import logging
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from brokers.base_broker import (
    BaseBroker, BrokerMode, AccountInfo, Position,
    OrderResult, Bar, Quote
)
from config import settings

logger = logging.getLogger(__name__)

# Map friendly timeframe strings → alpaca TimeFrame objects
_TF_MAP = {
    "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
    "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "30Min": TimeFrame(30, TimeFrameUnit.Minute),
    "1H":    TimeFrame(1,  TimeFrameUnit.Hour),
    "1D":    TimeFrame(1,  TimeFrameUnit.Day),
}


class AlpacaBroker(BaseBroker):
    """
    Alpaca Markets broker.

    Usage:
        paper_broker = AlpacaBroker(BrokerMode.PAPER)
        live_broker  = AlpacaBroker(BrokerMode.LIVE)
    """

    def __init__(self, mode: BrokerMode):
        super().__init__(mode)

        if mode == BrokerMode.PAPER:
            api_key = settings.alpaca_paper_api_key
            secret  = settings.alpaca_paper_secret_key
            paper   = True
        else:
            api_key = settings.alpaca_live_api_key
            secret  = settings.alpaca_live_secret_key
            paper   = False

        self._trading = TradingClient(api_key, secret, paper=paper)
        self._data    = StockHistoricalDataClient(api_key, secret)

    # ── Account ────────────────────────────────────────────────────────────────
    async def get_account(self) -> AccountInfo:
        acct = self._trading.get_account()
        positions = await self.get_positions()
        return AccountInfo(
            mode=self.mode,
            equity=float(acct.equity),
            cash=float(acct.cash),
            buying_power=float(acct.buying_power),
            day_pnl=float(acct.equity) - float(acct.last_equity),
            day_pnl_pct=(float(acct.equity) / float(acct.last_equity) - 1) * 100
                         if float(acct.last_equity) else 0.0,
            positions=positions,
        )

    async def get_positions(self) -> list[Position]:
        raw = self._trading.get_all_positions()
        out = []
        for p in raw:
            out.append(Position(
                symbol=p.symbol,
                qty=float(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pnl=float(p.unrealized_pl),
                unrealized_pnl_pct=float(p.unrealized_plpc) * 100,
                side=p.side.value,
            ))
        return out

    # ── Market Data ───────────────────────────────────────────────────────────
    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "5Min",
        limit: int = 50,
    ) -> list[Bar]:
        tf = _TF_MAP.get(timeframe, _TF_MAP["5Min"])
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, limit=limit)
        bars_dict = self._data.get_stock_bars(req)
        out: list[Bar] = []
        for b in bars_dict[symbol]:
            out.append(Bar(
                symbol=symbol,
                timestamp=str(b.timestamp),
                open=float(b.open),
                high=float(b.high),
                low=float(b.low),
                close=float(b.close),
                volume=float(b.volume),
                vwap=float(b.vwap) if b.vwap else None,
            ))
        return out

    async def get_quote(self, symbol: str) -> Quote:
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        q   = self._data.get_stock_latest_quote(req)[symbol]
        return Quote(
            symbol=symbol,
            bid=float(q.bid_price),
            ask=float(q.ask_price),
            last=(float(q.bid_price) + float(q.ask_price)) / 2,
            volume=int(q.bid_size + q.ask_size),
        )

    async def get_snapshot(self, symbols: list[str]) -> dict[str, dict]:
        req  = StockSnapshotRequest(symbol_or_symbols=symbols)
        snaps = self._data.get_stock_snapshot(req)
        result = {}
        for sym, snap in snaps.items():
            result[sym] = {
                "symbol": sym,
                "latest_trade_price": float(snap.latest_trade.price) if snap.latest_trade else None,
                "bid": float(snap.latest_quote.bid_price) if snap.latest_quote else None,
                "ask": float(snap.latest_quote.ask_price) if snap.latest_quote else None,
                "daily_open":  float(snap.daily_bar.open)   if snap.daily_bar else None,
                "daily_high":  float(snap.daily_bar.high)   if snap.daily_bar else None,
                "daily_low":   float(snap.daily_bar.low)    if snap.daily_bar else None,
                "daily_close": float(snap.daily_bar.close)  if snap.daily_bar else None,
                "daily_volume":float(snap.daily_bar.volume) if snap.daily_bar else None,
                "daily_vwap":  float(snap.daily_bar.vwap)   if snap.daily_bar else None,
                "prev_close":  float(snap.previous_daily_bar.close) if snap.previous_daily_bar else None,
            }
        return result

    # ── Orders ─────────────────────────────────────────────────────────────────
    def _side(self, side: str) -> OrderSide:
        return OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    def _tif(self, tif: str) -> TimeInForce:
        mapping = {
            "day": TimeInForce.DAY,
            "gtc": TimeInForce.GTC,
            "ioc": TimeInForce.IOC,
            "fok": TimeInForce.FOK,
        }
        return mapping.get(tif.lower(), TimeInForce.DAY)

    def _to_order_result(self, order) -> OrderResult:
        return OrderResult(
            broker_order_id=str(order.id),
            symbol=order.symbol,
            side=order.side.value,
            qty=float(order.qty) if order.qty else 0.0,
            status=order.status.value,
            filled_avg_price=float(order.filled_avg_price)
                             if order.filled_avg_price else None,
        )

    async def submit_market_order(
        self, symbol: str, side: str, qty: float, time_in_force: str = "day"
    ) -> OrderResult:
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=self._side(side),
            time_in_force=self._tif(time_in_force),
        )
        order = self._trading.submit_order(req)
        logger.info("[%s] Market %s %s x%s → %s", self.mode, side, symbol, qty, order.id)
        return self._to_order_result(order)

    async def submit_limit_order(
        self, symbol: str, side: str, qty: float,
        limit_price: float, time_in_force: str = "day"
    ) -> OrderResult:
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=self._side(side),
            limit_price=limit_price,
            time_in_force=self._tif(time_in_force),
        )
        order = self._trading.submit_order(req)
        logger.info("[%s] Limit %s %s x%s @%.2f → %s", self.mode, side, symbol, qty, limit_price, order.id)
        return self._to_order_result(order)

    async def submit_bracket_order(
        self, symbol: str, side: str, qty: float,
        limit_price: float, take_profit_price: float,
        stop_loss_price: float, time_in_force: str = "day"
    ) -> OrderResult:
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=self._side(side),
            limit_price=limit_price,
            time_in_force=self._tif(time_in_force),
            order_class="bracket",
            take_profit=TakeProfitRequest(limit_price=take_profit_price),
            stop_loss=StopLossRequest(stop_price=stop_loss_price),
        )
        order = self._trading.submit_order(req)
        logger.info(
            "[%s] Bracket %s %s x%s entry=%.2f tp=%.2f sl=%.2f → %s",
            self.mode, side, symbol, qty, limit_price,
            take_profit_price, stop_loss_price, order.id,
        )
        return self._to_order_result(order)

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            self._trading.cancel_order_by_id(broker_order_id)
            return True
        except Exception as e:
            logger.warning("Cancel failed %s: %s", broker_order_id, e)
            return False

    async def get_order_status(self, broker_order_id: str) -> OrderResult:
        order = self._trading.get_order_by_id(broker_order_id)
        return self._to_order_result(order)

    # ── Universe ───────────────────────────────────────────────────────────────
    async def get_tradeable_assets(self) -> list[str]:
        assets = self._trading.get_all_assets()
        return [a.symbol for a in assets if a.tradable and a.status.value == "active"]

    async def is_market_open(self) -> bool:
        clock = self._trading.get_clock()
        return clock.is_open
