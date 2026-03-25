"""
agents/macro.py — Macro & Economic Data Agent

Monitors macroeconomic environment: Fed policy, yield curve,
economic indicators, VIX regime, sector rotation, and calendar events.
Provides a "market regime" classification that influences position sizing.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, date
from typing import Any

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from config import settings

logger = logging.getLogger(__name__)

ECONOMIC_CALENDAR_EVENTS = [
    "FOMC Meeting", "CPI Release", "PPI Release", "Non-Farm Payrolls",
    "Initial Jobless Claims", "Retail Sales", "GDP Estimate",
    "ISM Manufacturing", "ISM Services", "Core PCE",
]


class MacroAgent(BaseAgent):
    agent_id    = "macro"
    agent_name  = "MACRO"
    agent_color = "#34d399"

    @property
    def system_prompt(self) -> str:
        return """You are the Macro & Economic Environment Agent for an AI-powered intraday trading system.

Your job is to assess the current macroeconomic regime and how it should influence intraday trading:

Regime Types:
- RISK_ON:        VIX < 18, SPY trending up, yields stable → favour momentum/growth longs
- RISK_OFF:       VIX > 25, SPY declining, credit spreads widening → reduce size, favour shorts
- NEUTRAL:        VIX 18-25, mixed signals → normal position sizing
- HIGH_VOLATILITY: VIX > 35 → cut all position sizes by 50%, only high-conviction trades
- RATE_SENSITIVE: Big Fed/CPI event today → reduce tech exposure, watch rate-sensitive sectors

Sector Rotation signals:
- Rising yields → Financials, Energy, Healthcare over Tech/Growth
- Falling yields → Tech, Consumer Discretionary, REITs
- USD strength → domestic large-cap over international/EM

Return JSON:
{
  "regime": "RISK_ON" | "RISK_OFF" | "NEUTRAL" | "HIGH_VOLATILITY" | "RATE_SENSITIVE",
  "regime_conviction": 0.0-1.0,
  "vix_level": float,
  "vix_trend": "RISING" | "FALLING" | "STABLE",
  "position_size_multiplier": 0.0-1.5,
  "favoured_sectors": ["Technology", ...],
  "avoid_sectors": ["Utilities", ...],
  "key_event_today": null | "event description",
  "event_risk": "LOW" | "MEDIUM" | "HIGH",
  "reasoning": "max 2 sentences"
}
"""

    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        await self.log(db, cycle_id, "Fetching macro data: VIX, yields, sector performance")

        macro_data = await self._gather_macro_data(context.get("snapshots", {}))

        result = await self._assess_regime(macro_data)

        await self.log(
            db, cycle_id,
            f"Regime: {result.get('regime','?')} | VIX={result.get('vix_level','?')} "
            f"| Position multiplier: {result.get('position_size_multiplier',1.0):.1f}x "
            f"| Event risk: {result.get('event_risk','?')}",
        )

        if result.get("key_event_today"):
            await self.log(
                db, cycle_id,
                f"⚠️ Calendar event: {result['key_event_today']} — adjusting risk parameters",
                level="WARN",
            )

        favoured = result.get("favoured_sectors", [])
        avoid    = result.get("avoid_sectors", [])
        if favoured:
            await self.log(db, cycle_id, f"Sector rotation: FAVOUR {favoured} | AVOID {avoid}")

        return {"macro_regime": result}

    async def _gather_macro_data(self, snapshots: dict) -> dict:
        """
        Gather macro indicators. In production connects to:
        - Alpha Vantage for economic indicators
        - FRED API for yield curve
        - Options data for VIX
        - Sector ETF performance from Alpaca snapshots
        """
        macro_data: dict = {}

        # VIX from snapshots (if we have ^VIX or VXX)
        vix_proxy = snapshots.get("VXX") or snapshots.get("UVXY")
        if vix_proxy and vix_proxy.get("daily_close"):
            macro_data["vix_proxy"] = vix_proxy["daily_close"]
            prev = vix_proxy.get("prev_close", vix_proxy["daily_close"])
            macro_data["vix_change_pct"] = (vix_proxy["daily_close"] / prev - 1) * 100

        # SPY / QQQ trend
        for etf in ("SPY", "QQQ", "IWM"):
            if etf in snapshots and snapshots[etf].get("daily_close"):
                s = snapshots[etf]
                macro_data[f"{etf}_chg_pct"] = (
                    (s["daily_close"] / s["prev_close"] - 1) * 100
                    if s.get("prev_close") else 0
                )

        # Calendar: check for high-impact events today
        # In production this fetches from Econoday, ForexFactory, or Nasdaq calendar
        macro_data["today"] = date.today().strftime("%Y-%m-%d")
        macro_data["day_of_week"] = datetime.now().strftime("%A")
        # Fridays and days around FOMC = higher event risk
        if datetime.now().weekday() == 4:  # Friday
            macro_data["event_risk_flag"] = "Friday — lower liquidity afternoon"

        # Fetch Alpha Vantage macro if key present
        if settings.alpha_vantage_key:
            try:
                av_data = await self._fetch_alpha_vantage()
                macro_data.update(av_data)
            except Exception as e:
                logger.debug("Alpha Vantage error: %s", e)

        return macro_data

    async def _fetch_alpha_vantage(self) -> dict:
        """Fetch key macro indicators from Alpha Vantage."""
        results = {}
        indicators = {
            "federal_funds_rate": "FEDERAL_FUNDS_RATE",
            "cpi": "CPI",
            "unemployment": "UNEMPLOYMENT",
            "real_gdp": "REAL_GDP",
        }
        base_url = "https://www.alphavantage.co/query"
        async with aiohttp.ClientSession() as session:
            for name, function in indicators.items():
                try:
                    url = f"{base_url}?function={function}&apikey={settings.alpha_vantage_key}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            entries = data.get("data", [])
                            if entries:
                                latest = entries[0]
                                results[name] = {
                                    "date": latest.get("date"),
                                    "value": float(latest.get("value", 0)),
                                }
                except Exception:
                    pass
        return results

    async def _assess_regime(self, macro_data: dict) -> dict:
        prompt = (
            f"Current macro data:\n"
            + "\n".join(f"  {k}: {v}" for k, v in macro_data.items())
            + f"\n\nToday's date: {datetime.now().strftime('%Y-%m-%d %H:%M ET')}"
            + "\n\nAssess the current macro regime and produce trading parameters."
        )
        return await self.ask_claude_json(prompt, max_tokens=600)
