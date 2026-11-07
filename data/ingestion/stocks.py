"""
The stocks master record, shared by price and financials ingestion.

fetch_stock_info() only talks to yfinance; upsert_stock() only writes. Callers
fetch first and only then open the transaction: never do network I/O while
holding a database connection. The caller also owns the commit, so a ticker's
stock row and its price rows commit together or not at all.
"""

import logging

import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from config.settings import settings
from data.schemas.models import Stock
from data.universe import require_known_ticker

logger = logging.getLogger(__name__)


def fetch_stock_info(symbol: str) -> dict:
    """Return name, sector, industry and exchange for a symbol in the universe.

    t.info is slow and unreliable, so a failure degrades to sector and industry
    set to None rather than failing the ticker. The exception is a rate limit:
    it's systemic, so it propagates for the caller to retry or stop the run.
    """
    universe_name = require_known_ticker(symbol)
    try:
        info = yf.Ticker(symbol).info
        if not info:
            raise ValueError("empty response")
    except YFRateLimitError:
        raise
    except Exception as e:  # any yfinance/network failure here only costs us metadata
        logger.warning(
            "%s: info lookup failed (%s); sector/industry unknown", symbol, e
        )
        info = {}

    return {
        # Always our own universe name, not longName: it's stable whether or not Yahoo answered
        "name": universe_name,
        "sector": info.get("sector") or None,
        "industry": info.get("industry") or None,
        "exchange": info.get("fullExchangeName") or settings.DEFAULT_MARKET,
    }


def upsert_stock(session: Session, symbol: str, info: dict) -> int:
    """Insert or update the stocks row from fetch_stock_info() output and return its id.

    Makes no network calls and does not commit.
    """
    stmt = insert(Stock).values(symbol=symbol, **info)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Stock.symbol],
        set_={
            "name": stmt.excluded.name,
            # A failed info lookup sends None; keep the stored value instead of erasing it
            "sector": func.coalesce(stmt.excluded.sector, Stock.sector),
            "industry": func.coalesce(stmt.excluded.industry, Stock.industry),
            "exchange": stmt.excluded.exchange,
            # onupdate=func.now() doesn't fire for ON CONFLICT DO UPDATE, so set it here
            "updated_at": func.now(),
        },
    ).returning(Stock.id)
    return session.execute(stmt).scalar_one()
