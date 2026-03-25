"""
config.py — Centralised settings loaded from environment / .env file.
All other modules import `settings` from here.
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ── Alpaca ─────────────────────────────────────────────────────────────────
    alpaca_paper_api_key: str = Field("", env="ALPACA_PAPER_API_KEY")
    alpaca_paper_secret_key: str = Field("", env="ALPACA_PAPER_SECRET_KEY")
    alpaca_live_api_key: str = Field("", env="ALPACA_LIVE_API_KEY")
    alpaca_live_secret_key: str = Field("", env="ALPACA_LIVE_SECRET_KEY")

    # ── Anthropic ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = Field("", env="ANTHROPIC_API_KEY")

    # ── External APIs ──────────────────────────────────────────────────────────
    news_api_key: str = Field("", env="NEWS_API_KEY")
    alpha_vantage_key: str = Field("", env="ALPHA_VANTAGE_KEY")

    # ── Capital & Risk ─────────────────────────────────────────────────────────
    paper_capital: float = Field(100_000.0, env="PAPER_CAPITAL")
    live_capital: float = Field(10_000.0, env="LIVE_CAPITAL")
    max_position_size_pct: float = Field(0.05, env="MAX_POSITION_SIZE_PCT")
    max_daily_loss_pct: float = Field(0.03, env="MAX_DAILY_LOSS_PCT")
    max_sector_exposure: float = Field(0.35, env="MAX_SECTOR_EXPOSURE")
    cycle_interval_seconds: int = Field(300, env="CYCLE_INTERVAL_SECONDS")

    # ── Database ───────────────────────────────────────────────────────────────
    database_url: str = Field(
        "sqlite+aiosqlite:///./trading.db", env="DATABASE_URL"
    )

    # ── App ────────────────────────────────────────────────────────────────────
    log_level: str = Field("INFO", env="LOG_LEVEL")
    environment: str = Field("development", env="ENVIRONMENT")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
