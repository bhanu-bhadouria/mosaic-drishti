"""
Daily price ingestion from yfinance.

fetch_prices() only downloads and reshapes; validate_prices() only splits rows
into valid and rejected; store_prices() only converts types and writes. Each
function has one job.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from config.settings import settings
from data.ingestion.convert import to_decimal, to_int
from data.ingestion.exceptions import DataQualityError, NoDataError
from data.schemas.models import PriceHistory
from data.universe import require_known_ticker

logger = logging.getLogger(__name__)

# yfinance column -> PriceHistory column, in output order
PRICE_COLUMNS = {
    "Open": "open_price",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adjusted_close",
    "Volume": "volume",
}

PRICE_FIELDS = ["open_price", "high", "low", "close", "adjusted_close"]

# Yahoo reports values like high=3899.9999 against close=3900.0; don't reject those
PRICE_TOLERANCE = 0.01

# "Today" means today on the NSE, not on whatever machine this runs on (Azure is UTC)
MARKET_TZ = ZoneInfo(settings.MARKET_TIMEZONE)


def fetch_prices(symbol: str, period: str | None = None) -> pd.DataFrame:
    """Download daily OHLCV for one symbol, with columns named after PriceHistory.

    Returns columns: date, open_price, high, low, close, adjusted_close, volume.
    Raises UnknownTickerError (before any network call) or NoDataError, and
    RuntimeError if yfinance's columns change.
    """
    require_known_ticker(symbol)
    if period is None:
        period = f"{settings.MAX_HISTORY_YEARS}y"

    raw = yf.download(
        symbol,
        period=period,
        auto_adjust=False,
        multi_level_index=False,
        progress=False,
        actions=False,
    )
    if raw.empty:
        raise NoDataError(symbol)

    missing = [col for col in PRICE_COLUMNS if col not in raw.columns]
    if missing:
        # Systemic (yfinance changed its output), not a per-ticker problem, so it must stop the run
        raise RuntimeError(
            f"yfinance {yf.__version__} response for {symbol} is missing columns {missing}"
        )

    df = raw[list(PRICE_COLUMNS)].rename(columns=PRICE_COLUMNS)
    df.insert(0, "date", raw.index.date)
    logger.info("Fetched %d rows for %s", len(df), symbol)
    return df.reset_index(drop=True)


def validate_prices(symbol: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split fetched prices into (valid, rejected) rows.

    rejected has an extra reason column listing every rule the row broke.
    Raises DataQualityError if more than settings.MAX_REJECT_RATIO of rows are rejected.
    """
    prices = df[PRICE_FIELDS]
    highest_other = df[["open_price", "close", "low"]].max(axis=1)
    lowest_other = df[["open_price", "close"]].min(axis=1)

    # True = the row breaks the rule. NaN comparisons are False, which is why
    # missing_price is its own rule rather than relying on the others.
    rules = {
        "missing_price": prices.isna().any(axis=1),
        "non_positive_price": (prices <= 0).any(axis=1),
        "high_below_others": df["high"] < highest_other - PRICE_TOLERANCE,
        "low_above_others": df["low"] > lowest_other + PRICE_TOLERANCE,
        "negative_volume": df["volume"] < 0,
        "future_date": df["date"] > datetime.now(MARKET_TZ).date(),
        "duplicate_date": df["date"].duplicated(keep="first"),
    }
    is_rejected = pd.concat(rules, axis=1).any(axis=1)

    # Every broken rule per row, joined with "; " (loops over rules, not rows)
    reason = pd.Series("", index=df.index)
    for name, mask in rules.items():
        reason[mask] += name + "; "

    valid = df[~is_rejected].copy()
    rejected = df[is_rejected].copy()
    rejected["reason"] = reason[is_rejected].str.removesuffix("; ")

    for row in rejected.itertuples():
        logger.warning("%s %s rejected: %s", symbol, row.date, row.reason)

    failed, total = len(rejected), len(df)
    if total and failed / total > settings.MAX_REJECT_RATIO:
        raise DataQualityError(symbol, failed, total)

    return valid, rejected


def store_prices(session: Session, stock_id: int, df: pd.DataFrame) -> int:
    """Upsert validated price rows for one stock and return how many were written.

    Re-running is safe: an existing (stock_id, date) row is updated, because
    dividends change past adjusted_close values and an intraday run stores an
    incomplete day. Does not commit.
    """
    records = [
        {
            "stock_id": stock_id,
            "date": row.date,
            "open_price": to_decimal(row.open_price),
            "high": to_decimal(row.high),
            "low": to_decimal(row.low),
            "close": to_decimal(row.close),
            "adjusted_close": to_decimal(row.adjusted_close),
            "volume": to_int(row.volume),
        }
        for row in df.itertuples(index=False)
    ]
    if not records:  # an empty list runs one parameterless INSERT, not zero inserts
        return 0

    stmt = insert(PriceHistory)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_price_stock_date",
        set_={col: stmt.excluded[col] for col in [*PRICE_FIELDS, "volume"]},
    )
    # Rows passed separately, not via .values(records): SQLAlchemy batches them,
    # so we never hit Postgres's 65,535-placeholders-per-statement limit
    session.execute(stmt, records)
    return len(records)  # result.rowcount isn't reliable for batched execution
