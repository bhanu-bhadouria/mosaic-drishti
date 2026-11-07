"""
ingest_all(): the full ingestion run for every ticker in the universe.

The building blocks live in their own modules; this file only orchestrates.
Each ticker runs in two phases: every network call first, with no database
connection held, then one transaction that commits whatever is written
together, or nothing.

Prices are required: a price failure fails the ticker. Financials are optional:
a financials failure still writes the stock and its prices ("partial").
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeVar, get_args

from yfinance.exceptions import YFRateLimitError

from config.settings import settings
from data.database import SessionLocal
from data.ingestion.exceptions import IngestionError
from data.ingestion.financials_ingestion import (
    fetch_financials,
    store_financials,
    validate_financials,
)
from data.ingestion.price_ingestion import fetch_prices, store_prices, validate_prices
from data.ingestion.ratios import update_ratios
from data.ingestion.stocks import fetch_stock_info, upsert_stock
from data.universe import get_all_tickers

logger = logging.getLogger(__name__)

T = TypeVar("T")

Status = Literal["ok", "partial", "failed"]


@dataclass
class TickerResult:
    """The outcome of ingesting one ticker, for the end-of-run summary.

    ok: everything written. partial: stock and prices written, financials failed
    (financials_error says why). failed: nothing written (error says why).
    """

    symbol: str
    status: Status
    prices_written: int = 0
    prices_rejected: int = 0
    financials_written: int = 0
    financial_rejections: int = 0
    error: str | None = None
    financials_error: str | None = None


def _with_retry(fn: Callable[..., T], *args) -> T:
    """Call fn(*args), retrying only on YFRateLimitError, with exponential backoff.

    Any other exception propagates at once. If the rate limit outlasts every
    retry, YFRateLimitError propagates too: it's systemic, so every remaining
    ticker would fail the same way, and the run should stop.
    """
    for attempt in range(settings.INGEST_MAX_RETRIES + 1):
        try:
            return fn(*args)
        except YFRateLimitError:
            if attempt == settings.INGEST_MAX_RETRIES:
                raise
            delay = settings.INGEST_RETRY_BASE_DELAY * 2**attempt
            logger.warning(
                "Rate limited in %s; retry %d/%d in %.0fs",
                fn.__name__,
                attempt + 1,
                settings.INGEST_MAX_RETRIES,
                delay,
            )
            time.sleep(delay)


def ingest_ticker(symbol: str) -> TickerResult:
    """Fetch, validate and store one ticker in a single transaction.

    Raises IngestionError if the stock info or prices fail (nothing is written).
    A financials IngestionError is recorded on the result instead: the stock and
    prices are still written, and the ratios recalculated from stored financials.
    """
    # Phase 1: network only. No session is open, so no connection is held while Yahoo is slow
    info = _with_retry(fetch_stock_info, symbol)
    prices, rejected_prices = validate_prices(symbol, _with_retry(fetch_prices, symbol))

    financials, fin_rejections, financials_error = None, [], None
    try:
        financials, fin_rejections = validate_financials(
            symbol, _with_retry(fetch_financials, symbol)
        )
    except IngestionError as e:
        financials_error = f"{type(e).__name__}: {e}"

    # Phase 2: one transaction. s.begin() commits when the block ends, rolls back if anything raises
    financials_written = 0
    with SessionLocal() as s, s.begin():
        stock_id = upsert_stock(s, symbol, info)
        prices_written = store_prices(s, stock_id, prices)
        if financials is not None:
            financials_written = store_financials(s, stock_id, financials)
        # Always: reads stored financials, so earlier runs' figures get today's prices
        update_ratios(s, stock_id)

    return TickerResult(
        symbol=symbol,
        status="partial" if financials_error else "ok",
        prices_written=prices_written,
        prices_rejected=len(rejected_prices),
        financials_written=financials_written,
        financial_rejections=len(fin_rejections),
        financials_error=financials_error,
    )


def ingest_all(symbols: list[str] | None = None) -> list[TickerResult]:
    """Ingest every symbol (default: the whole universe) and log a summary.

    Only IngestionError is caught: that ticker is recorded as failed and the run
    moves on. Anything else (a bug, the RuntimeError for changed yfinance columns,
    a rate limit that outlasts every retry) stops the run.
    """
    symbols = get_all_tickers() if symbols is None else symbols
    results = []
    for i, symbol in enumerate(symbols):
        if i:
            time.sleep(settings.INGEST_TICKER_PAUSE)
        try:
            result = ingest_ticker(symbol)
            logger.info(
                "%s %s: %d prices (%d rejected), %d financial periods (%d rejections)",
                symbol,
                result.status,
                result.prices_written,
                result.prices_rejected,
                result.financials_written,
                result.financial_rejections,
            )
            if result.financials_error:
                logger.warning(
                    "%s financials skipped: %s", symbol, result.financials_error
                )
        except IngestionError as e:
            result = TickerResult(
                symbol=symbol, status="failed", error=f"{type(e).__name__}: {e}"
            )
            logger.warning("%s failed: %s", symbol, result.error)
        results.append(result)

    counts = {
        status: sum(r.status == status for r in results) for status in get_args(Status)
    }
    logger.info(
        "%d tickers: %d ok, %d partial, %d failed",
        len(results),
        counts["ok"],
        counts["partial"],
        counts["failed"],
    )
    for r in results:
        if r.status != "ok":
            logger.info(
                "  %s %s: %s", r.symbol, r.status, r.error or r.financials_error
            )
    return results
