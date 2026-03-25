"""
agents/sentiment.py — Sentiment Agent

Fetches real-time news headlines via NewsAPI + RSS feeds,
scores sentiment per symbol, and feeds signals to the Portfolio Manager.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
import feedparser
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from models.database import Signal, TradeSide
from config import settings

logger = logging.getLogger(__name__)

RSS_FEEDS = {
    "market":  "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
    "tech":    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA,AMD,AAPL&region=US&lang=en-US",
    "seekingalpha": "https://seekingalpha.com/feed.xml",
    "marketwatch":  "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
}


class SentimentAgent(BaseAgent):
    agent_id    = "sentiment"
    agent_name  = "SENTIMENT"
    agent_color = "#fbbf24"

    @property
    def system_prompt(self) -> str:
        return """You are the Sentiment Analysis Agent for an AI-powered intraday trading system.

Given a list of recent news headlines and articles relevant to a stock or the broader market,
produce a structured sentiment signal for intraday trading purposes.

Focus on:
- Breaking news that could cause immediate price moves (earnings, M&A, FDA, legal, executive changes)
- Analyst upgrades/downgrades with specific price targets
- Macro events: Fed speeches, CPI/PPI/jobs data, earnings beats/misses
- Social momentum: unusual spike in mentions, viral narrative forming
- Distinguish between noise and signal — weight recency and credibility of source

Return JSON:
{
  "sentiment_score": -1.0 to +1.0,
  "direction": "BUY" | "SELL" | "NEUTRAL",
  "conviction": 0.0-1.0,
  "catalyst": "one-line description of the key driver",
  "risk_flag": true|false,
  "risk_note": "if risk_flag, explain what the risk is",
  "reasoning": "max 2 sentences"
}
"""

    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        candidates = context.get("candidates", [])
        symbols    = [c["symbol"] for c in candidates[:8]]

        if not symbols:
            await self.log(db, cycle_id, "No candidates — skipping sentiment scan")
            return {"sentiment_signals": {}}

        await self.log(db, cycle_id, f"Fetching news for {len(symbols)} symbols + macro feeds")

        # Fetch in parallel
        tasks = {sym: self._fetch_news_for_symbol(sym) for sym in symbols}
        tasks["_macro"] = self._fetch_rss_headlines()

        all_results = {}
        for sym, coro in tasks.items():
            try:
                all_results[sym] = await coro
            except Exception as e:
                logger.warning("News fetch error [%s]: %s", sym, e)
                all_results[sym] = []

        macro_headlines = all_results.pop("_macro", [])
        await self.log(db, cycle_id, f"Fetched {len(macro_headlines)} macro headlines")

        sentiment_signals: dict[str, dict] = {}

        for sym in symbols:
            headlines = all_results.get(sym, [])
            all_headlines = macro_headlines[:5] + headlines  # prepend top macro context
            if not all_headlines:
                continue

            try:
                result = await self._score_sentiment(sym, all_headlines)
                sentiment_signals[sym] = result

                if result.get("direction") in ("BUY", "SELL") and result.get("conviction", 0) >= 0.4:
                    sig = Signal(
                        cycle_id=cycle_id,
                        symbol=sym,
                        source_agent=self.agent_id,
                        direction=TradeSide(result["direction"]),
                        conviction=result["conviction"],
                        reasoning=result["reasoning"],
                        raw_data={
                            "sentiment_score": result.get("sentiment_score"),
                            "catalyst": result.get("catalyst"),
                            "risk_flag": result.get("risk_flag"),
                        },
                    )
                    db.add(sig)

                    flag = " ⚠️ RISK" if result.get("risk_flag") else ""
                    await self.log(
                        db, cycle_id,
                        f"{sym}: sentiment={result.get('sentiment_score',0):+.2f} "
                        f"{result['direction']} conviction={result['conviction']:.0%} "
                        f"— {result.get('catalyst','')}{flag}",
                    )
            except Exception as e:
                await self.log(db, cycle_id, f"{sym}: sentiment error — {e}", "WARN")

        await db.flush()
        await self.log(db, cycle_id, f"Sentiment scan complete — {len(sentiment_signals)} symbols scored")
        return {"sentiment_signals": sentiment_signals}

    async def _fetch_news_for_symbol(self, symbol: str) -> list[str]:
        """Fetch headlines from NewsAPI for a specific symbol."""
        if not settings.news_api_key:
            return []

        url = (
            "https://newsapi.org/v2/everything"
            f"?q={symbol}&sortBy=publishedAt&pageSize=10"
            f"&from={(datetime.utcnow()-timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%S')}"
            f"&apiKey={settings.news_api_key}"
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [
                            f"[{a.get('source',{}).get('name','')}] {a.get('title','')} — {a.get('description','')}"
                            for a in data.get("articles", [])[:8]
                        ]
        except Exception as e:
            logger.debug("NewsAPI error for %s: %s", symbol, e)
        return []

    async def _fetch_rss_headlines(self) -> list[str]:
        """Fetch macro RSS headlines."""
        headlines = []
        for name, url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:4]:
                    headlines.append(f"[{name}] {entry.get('title','')} — {entry.get('summary','')[:120]}")
            except Exception:
                pass
        return headlines[:20]

    async def _score_sentiment(self, symbol: str, headlines: list[str]) -> dict:
        prompt = (
            f"Symbol: {symbol}\n\nRecent headlines (newest first):\n"
            + "\n".join(f"- {h}" for h in headlines[:15])
            + "\n\nScore intraday sentiment signal."
        )
        return await self.ask_claude_json(prompt, max_tokens=512)
