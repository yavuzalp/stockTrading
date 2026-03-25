"""
agents/base_agent.py — Abstract base class for all trading agents.

Each agent:
  - Has its own Claude system prompt / persona
  - Logs every action to the DB + broadcasts over WebSocket
  - Exposes a single `run(cycle_id, context)` coroutine
"""
from __future__ import annotations
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Coroutine

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import AgentLog

logger = logging.getLogger(__name__)

# Global broadcast hook — set by main.py to the WebSocket manager
_broadcast: Callable[[dict], Coroutine] | None = None


def set_broadcast_fn(fn: Callable[[dict], Coroutine]):
    global _broadcast
    _broadcast = fn


async def _emit(event: str, payload: dict):
    if _broadcast:
        try:
            await _broadcast({"event": event, "payload": payload, "ts": datetime.utcnow().isoformat()})
        except Exception as e:
            logger.debug("Broadcast error: %s", e)


class BaseAgent(ABC):
    """
    Abstract base for all 8 trading agents.

    Subclasses must implement:
        agent_id    : str  — unique slug  e.g. "scanner"
        agent_name  : str  — display name e.g. "SCANNER"
        system_prompt: str — Claude system prompt defining the agent's role
        run(cycle_id, context, db) -> dict  — main logic
    """

    agent_id: str = "base"
    agent_name: str = "BASE"
    agent_color: str = "#94a3b8"

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._status = "IDLE"

    # ── Claude helper ──────────────────────────────────────────────────────────
    async def ask_claude(
        self,
        user_message: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """
        Send a message to Claude and return the text response.
        System prompt is defined by each agent subclass.
        """
        response = await self._client.messages.create(
            model="claude-opus-4-5",
            max_tokens=max_tokens,
            temperature=temperature,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    async def ask_claude_json(
        self,
        user_message: str,
        max_tokens: int = 1024,
    ) -> dict:
        """Ask Claude and parse the response as JSON."""
        raw = await self.ask_claude(
            user_message + "\n\nRespond ONLY with valid JSON, no markdown, no commentary.",
            max_tokens=max_tokens,
        )
        # Strip possible markdown fences
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(clean)

    # ── Logging ───────────────────────────────────────────────────────────────
    async def log(
        self,
        db: AsyncSession,
        cycle_id: int,
        message: str,
        level: str = "INFO",
        metadata: dict | None = None,
    ):
        """Persist log entry to DB and broadcast to WebSocket clients."""
        entry = AgentLog(
            cycle_id=cycle_id,
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            message=message,
            level=level,
            metadata_json=metadata,
        )
        db.add(entry)
        await db.flush()  # get the id

        payload = {
            "id": entry.id,
            "cycle_id": cycle_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_color": self.agent_color,
            "message": message,
            "level": level,
            "metadata": metadata,
            "ts": datetime.utcnow().isoformat(),
        }
        await _emit("agent_log", payload)
        logger.info("[%s] %s", self.agent_name, message)

    async def set_status(self, status: str):
        self._status = status
        await _emit("agent_status", {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "status": status,
            "ts": datetime.utcnow().isoformat(),
        })

    # ── Entry point ───────────────────────────────────────────────────────────
    async def execute(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Wrapper around run() that handles status + errors."""
        await self.set_status("RUNNING")
        try:
            result = await self.run(cycle_id, context, db)
            await self.set_status("IDLE")
            return result
        except Exception as e:
            await self.set_status("ERROR")
            await self.log(db, cycle_id, f"ERROR: {e}", level="ERROR")
            logger.exception("[%s] Unhandled error in cycle %d", self.agent_name, cycle_id)
            return {}

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        ...

    @abstractmethod
    async def run(
        self,
        cycle_id: int,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Execute the agent's logic for one cycle.
        Returns a dict that is merged into the shared cycle context
        and passed downstream to the next agent(s).
        """
        ...
