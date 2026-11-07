"""
config/settings.py
------------------
Central configuration for Mosaic Drishti.
All environment variables are loaded here.
Every module imports from this file — never directly from .env

This is the single source of truth for all configuration.
If you need to add a new API key or setting, add it here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env from project root ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    """
    Central settings object.
    Typed attributes make it easy to catch configuration
    errors early rather than at runtime deep in an agent.
    """

    # ── Project ───────────────────────────────────────────────────────────────
    PROJECT_NAME: str = "Mosaic Drishti"
    VERSION: str = "0.1.0"
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # ── LLM ───────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    LLM_MODEL: str = "gpt-4.1-mini"
    LLM_MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.2  # Low temperature = more consistent reasoning

    # ── News ──────────────────────────────────────────────────────────────────
    NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # ── Vector Database ───────────────────────────────────────────────────────
    CHROMA_PERSIST_DIR: str = os.getenv(
        "CHROMA_PERSIST_DIR",
        str(BASE_DIR / "data" / "chroma_db")
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: Path = BASE_DIR / "logs"

    # ── Market Data ───────────────────────────────────────────────────────────
    DEFAULT_MARKET: str = "NSE"
    DEFAULT_CURRENCY: str = "INR"
    MARKET_TIMEZONE: str = "Asia/Kolkata"  # "Today" means today on the NSE, wherever we run
    DATA_CACHE_TTL: int = 3600        # Cache market data for 1 hour (seconds)
    MAX_HISTORY_YEARS: int = 5        # How far back we fetch historical data
    MAX_REJECT_RATIO: float = 0.05    # Reject a whole ticker if over 5% of its rows fail validation

    # ── Agent Behaviour ───────────────────────────────────────────────────────
    AGENT_MAX_RETRIES: int = 3        # Retry failed LLM calls up to 3 times
    AGENT_TIMEOUT_SECONDS: int = 60   # Fail agent if no response in 60s


# ── Single instance imported everywhere ───────────────────────────────────────
# Usage in any module:
#   from config.settings import settings
#   print(settings.OPENAI_API_KEY)
settings = Settings()

if not settings.DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it to .env (see .env.example).")