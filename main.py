"""
main.py — Application entry point.

Starts FastAPI, initialises DB, wires WebSocket broadcast into agents,
and starts the APScheduler trading cycle.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models.database import init_db
from api.routes import router, manager
from agents.base_agent import set_broadcast_fn
from orchestrator import orchestrator

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    logger.info("Initialising database...")
    await init_db()

    logger.info("Wiring WebSocket broadcast into agent base...")
    set_broadcast_fn(manager.broadcast)

    logger.info("Starting trading orchestrator (cycle every %ds)...", settings.cycle_interval_seconds)
    orchestrator.start()

    logger.info("✅ Trading system live — paper + live mode active")
    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    logger.info("Shutting down orchestrator...")
    orchestrator.stop()
    logger.info("Shutdown complete")


app = FastAPI(
    title="AI Trading Agents",
    description="Multi-agent intraday trading system with Alpaca integration",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )
