"""
agents/technicals.py — Technical Analysis Agent

For each scanner candidate, fetches OHLCV bars and computes:
RSI, MACD, Bollinger Bands, VWAP, EMA(9/20/50/200), ATR.
Then asks Claude to interpret the signals and rate conviction.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

import numpy as np
import pandas as pd
import ta  # technical analysis library

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from brokers.base_broker import BaseBroker
from models.database import Signal, TradeSide

logger = logging.getLogger(__name__)


def _compute_indicators(bars: list) -> dict:
    """Compute a full set of TA indicators from a list of Bar objects."""
    if len(bars) < 20:
        return {}

    df = pd.DataFrame([{
        "open":   b.open,
        "high":   b.high,
        "low":    b.low,
        "close":  b.close,
        "volume": b.volume,
        "vwap":   b.vwap or b.close,
    } for b in bars])

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    # RSI
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]

    # MACD
    macd_ind  = ta.trend.MACD(close)
    macd_line = macd_ind.macd().iloc[-1]
    macd_sig  = macd_ind.macd_signal().iloc[-1]
    macd_hist = macd_ind.macd_diff().iloc[-1]

    # Bollinger Bands
    bb       = ta.volatility.BollingerBands(close, window=20)
    bb_upper = bb.bollinger_hband().iloc[-1]
    bb_lower = bb.bollinger_lband().iloc[-1]
    bb_mid   = bb.bollinger_mavg().iloc[-1]
    bb_pct   = bb.bollinger_pband().iloc[-1]       # position within bands 0-1
    bb_squeeze = (bb_upper - bb_lower) / bb_mid    # normalised width

    # EMAs
    ema9   = ta.trend.EMAIndicator(close, window=9).ema_indicator().iloc[-1]
    ema20  = ta.trend.EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50  = ta.trend.EMAIndicator(close, window=50).ema_indicator().iloc[-1] if len(df) >= 50 else None
    ema200 = ta.trend.EMAIndicator(close, window=200).ema_indicator().iloc[-1] if len(df) >= 200 else None

    # VWAP (intraday approximation using cumulative)
    cum_vol     = vol.cumsum()
    cum_vol_prc = (close * vol).cumsum()
    vwap_calc   = (cum_vol_prc / cum_vol.replace(0, np.nan)).iloc[-1]

    # ATR
    atr = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]

    # Relative volume (last bar vs avg)
    avg_vol = vol.mean()
    rvol    = vol.iloc[-1] / avg_vol if avg_vol else 1.0

    return {
        "current_price": float(close.iloc[-1]),
        "rsi": round(float(rsi), 2),
        "macd_line": round(float(macd_line), 4),
        "macd_signal": round(float(macd_sig), 4),
        "macd_hist": round(float(macd_hist), 4),
        "macd_bull_cross": float(macd_line) > float(macd_sig) and float(macd_hist) > 0,
        "bb_upper": round(float(bb_upper), 2),
        "bb_lower": round(float(bb_lower), 2),
        "bb_mid": round(float(bb_mid), 2),
        "bb_pct_b": round(float(bb_pct), 3),
        "bb_squeeze": round(float(bb_squeeze), 4),
        "ema9": round(float(ema9), 2),
        "ema20": round(float(ema20), 2),
        "ema50": round(float(ema50), 2) if ema50 else None,
        "ema200": round(float(ema200), 2) if ema200 else None,
        "vwap": round(float(vwap_calc), 2),
        "above_vwap": float(close.iloc[-1]) > float(vwap_calc),
        "atr": round(float(atr), 3),
        "rvol": round(float(rvol), 2),
    }


class TechnicalsAgent(BaseAgent):
    agent_id    = "tech"
    agent_name  = "TECHNICALS"
    agent_color = "#818cf8"

    def __init__(self, broker: BaseBroker):
        super().__init__()
        self.broker = broker

    @property
    def system_prompt(self) -> str:
        return """You are the Technical Analysis Agent for an AI-powered intraday trading system.

Given computed indicators for a stock, produce a structured trading signal.

Rules:
- RSI < 30 = oversold (bullish bias); RSI > 70 = overbought (bearish bias)
- MACD bull cross (line > signal AND hist > 0) = bullish momentum
- Price above VWAP = institutional buy bias; below = sell bias
- BB squeeze (width < 2%) followed by breakout = high-conviction entry
- EMA alignment (9 > 20 > 50) = strong uptrend; reverse = downtrend
- RVOL > 2 = unusual interest, amplifies other signals
- ATR used for stop sizing: stop = entry ± 1.5× ATR

Return JSON:
{
  "direction": "BUY" | "SELL" | "NEUTRAL",
  "conviction": 0.0-1.0,
  "stop_distance_atr_multiplier": 1.5,
  "take_profit_atr_multiplier": 3.0,
  "reasoning": "concise explanation max 2 sentences",
  "key_levels": { "support": float, "resistance": float }
}
"""

    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        candidates = context.get("candidates", [])
        if not candidates:
            await self.log(db, cycle_id, "No candidates received — skipping")
            return {"tech_signals": {}}

        top = [c["symbol"] for c in candidates[:8]]
        await self.log(db, cycle_id, f"Running TA on {len(top)} symbols: {', '.join(top)}")

        tech_signals: dict[str, dict] = {}
        saved_signals: list[Signal]   = []

        tasks = [self._analyse_symbol(sym, cycle_id, db) for sym in top]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for sym, res in zip(top, results):
            if isinstance(res, Exception):
                await self.log(db, cycle_id, f"{sym}: TA error — {res}", "WARN")
                continue
            if res:
                tech_signals[sym] = res
                if res.get("direction") in ("BUY", "SELL"):
                    sig = Signal(
                        cycle_id=cycle_id,
                        symbol=sym,
                        source_agent=self.agent_id,
                        direction=TradeSide(res["direction"]),
                        conviction=res["conviction"],
                        reasoning=res["reasoning"],
                        raw_data=res,
                    )
                    db.add(sig)
                    saved_signals.append(sig)
                    await self.log(
                        db, cycle_id,
                        f"{sym}: {res['direction']} conviction={res['conviction']:.0%} — {res['reasoning']}",
                    )

        await db.flush()
        await self.log(db, cycle_id, f"TA complete — {len(saved_signals)} directional signals generated")
        return {"tech_signals": tech_signals}

    async def _analyse_symbol(self, symbol: str, cycle_id: int, db: AsyncSession) -> dict | None:
        try:
            bars = await self.broker.get_bars(symbol, timeframe="5Min", limit=50)
            indicators = _compute_indicators(bars)
            if not indicators:
                return None

            prompt = (
                f"Symbol: {symbol}\nIndicators:\n"
                + "\n".join(f"  {k}: {v}" for k, v in indicators.items())
                + "\n\nGenerate trading signal."
            )
            result = await self.ask_claude_json(prompt, max_tokens=512)
            result["indicators"] = indicators
            result["symbol"]     = symbol
            return result
        except Exception as e:
            logger.warning("TA error for %s: %s", symbol, e)
            return None
