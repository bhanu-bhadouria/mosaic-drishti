"""
Annual and quarterly financial statements from yfinance.

fetch_financials() only downloads and reshapes; validate_financials() only
nulls impossible values and drops impossible periods; store_financials() only
converts types and writes. Each function has one job.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from config.settings import settings
from data.ingestion.convert import to_decimal
from data.ingestion.exceptions import NoDataError
from data.schemas.models import FinancialData
from data.universe import require_known_ticker

logger = logging.getLogger(__name__)

# yfinance row label -> our column name. eps_basic and eps_diluted are working
# columns: both are needed for the consistency check, only diluted is stored as eps.
INCOME_LABELS = {
    "Total Revenue": "revenue",
    "Net Income": "net_income",
    "Basic EPS": "eps_basic",
    "Diluted EPS": "eps_diluted",
    "EBIT": "ebit",
}
BALANCE_LABELS = {
    "Total Debt": "total_debt",
    "Stockholders Equity": "stockholders_equity",
    "Total Assets": "total_assets",
    "Current Liabilities": "current_liabilities",
}
VALUE_COLUMNS = [*INCOME_LABELS.values(), *BALANCE_LABELS.values()]

# Diluted EPS can't meaningfully exceed basic (1% allows rounding), and dilution
# beyond 10% is implausible for these companies. Outside that band, the two
# figures are on different share bases (e.g. a bonus issue restated in only one).
EPS_DILUTED_MAX_RATIO = 1.01
EPS_DILUTED_MIN_RATIO = 0.90

MARKET_TZ = ZoneInfo(settings.MARKET_TIMEZONE)

# Raw values written by store_financials(). The ratio columns are left alone:
# they're derived, and recalculated from these whenever these change.
STORED_COLUMNS = [
    "revenue",
    "net_income",
    "eps",
    "ebit",
    "total_debt",
    "stockholders_equity",
    "total_assets",
    "current_liabilities",
]


def _reshape(statement: pd.DataFrame, labels: dict[str, str]) -> pd.DataFrame:
    """Labels-as-rows, dates-as-columns -> one row per period date, our column names.

    Unlike fetch_prices(), where a missing column means yfinance changed for every
    ticker and must stop the run, a missing label here is a fact about one company
    (banks report no EBIT), so reindex turns it into NaN instead of a KeyError.
    """
    return statement.reindex(list(labels)).T.rename(columns=labels)


def _combine(
    income: pd.DataFrame, balance: pd.DataFrame, period_type: str
) -> pd.DataFrame:
    """Outer-join one income statement with its balance sheet on period date."""
    # Outer, not inner: the two statements don't cover the same periods
    df = _reshape(income, INCOME_LABELS).join(
        _reshape(balance, BALANCE_LABELS), how="outer"
    )
    df = df.rename_axis("period_date").reset_index()
    df.insert(0, "period_type", period_type)
    return df


def fetch_financials(symbol: str) -> pd.DataFrame:
    """Download annual and quarterly statements for one symbol, one row per period.

    Returns columns: period_type ("annual" | "quarterly"), period_date, then
    VALUE_COLUMNS as float64. Labels a company doesn't report are NaN.
    Raises UnknownTickerError (before any network call) or NoDataError.
    """
    require_known_ticker(symbol)
    t = yf.Ticker(symbol)  # each statement property below is a separate HTTP request

    df = pd.concat(
        [
            _combine(t.financials, t.balance_sheet, "annual"),
            _combine(t.quarterly_financials, t.quarterly_balance_sheet, "quarterly"),
        ],
        ignore_index=True,
    )
    # Periods with no values at all, e.g. TCS's empty 2022 balance sheet
    df = df.dropna(subset=VALUE_COLUMNS, how="all")
    if df.empty:
        raise NoDataError(symbol, "no financial statements")

    # astype, not to_numeric(errors="coerce"): unexpected text should fail loudly, not become NaN
    df[VALUE_COLUMNS] = df[VALUE_COLUMNS].astype("float64")
    df["period_date"] = pd.to_datetime(df["period_date"]).dt.date
    df = df.sort_values(["period_type", "period_date"], ignore_index=True)

    logger.info("Fetched %d financial periods for %s", len(df), symbol)
    return df[["period_type", "period_date", *VALUE_COLUMNS]]


def validate_financials(
    symbol: str, df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Null impossible fields, drop impossible periods; return (valid, rejections).

    Rejects what's impossible, not what's unusual: losses, negative equity and
    big year-on-year jumps (mergers) are real and pass through untouched.
    Fields are nulled rather than rows dropped, because one bad EPS shouldn't
    cost a period its good revenue. There's no reject-ratio threshold: with 4
    annual periods, one bad year is already 25%, which says nothing statistically.

    valid has a single eps column (diluted) in place of eps_basic/eps_diluted.
    rejections has one row per (period, rule) with the raw values that were nulled.
    """
    basic, diluted = df["eps_basic"], df["eps_diluted"]
    # Every mask is computed on the original data before anything is nulled; otherwise
    # nulling total_assets first would make equity_exceeds_assets compare against NaN.
    # Each rule: (rows that break it, fields to null). basic > 0 because for losses
    # both EPS figures are negative, the inequalities flip, and diluted equals basic anyway.
    field_rules = {
        "eps_mismatch": (
            (basic > 0)
            & (
                (diluted > basic * EPS_DILUTED_MAX_RATIO)
                | (diluted < basic * EPS_DILUTED_MIN_RATIO)
            ),
            ["eps_basic", "eps_diluted"],
        ),
        "negative_revenue": (df["revenue"] < 0, ["revenue"]),
        "non_positive_assets": (df["total_assets"] <= 0, ["total_assets"]),
        "negative_debt": (df["total_debt"] < 0, ["total_debt"]),
        "equity_exceeds_assets": (
            df["stockholders_equity"] > df["total_assets"],
            ["stockholders_equity", "total_assets"],
        ),
    }
    # The one row-level rule: a period that hasn't ended yet can't have been reported
    future_period = df["period_date"] > datetime.now(MARKET_TZ).date()
    row_rules = {"future_period": (future_period, VALUE_COLUMNS)}

    rejections = []
    for rule, (mask, fields) in {**field_rules, **row_rules}.items():
        for idx in df.index[mask]:
            raw = {f: float(df.at[idx, f]) for f in fields if pd.notna(df.at[idx, f])}
            rejections.append(
                {
                    "period_type": df.at[idx, "period_type"],
                    "period_date": df.at[idx, "period_date"],
                    "rule": rule,
                    "raw_values": raw,
                }
            )
            logger.warning(
                "%s %s %s rejected (%s): %s",
                symbol,
                df.at[idx, "period_type"],
                df.at[idx, "period_date"],
                rule,
                raw,
            )

    valid = df.copy()
    for mask, fields in field_rules.values():
        valid.loc[mask, fields] = np.nan
    valid = valid[~future_period]

    valid.insert(valid.columns.get_loc("eps_basic"), "eps", valid["eps_diluted"])
    valid = valid.drop(columns=["eps_basic", "eps_diluted"]).reset_index(drop=True)
    rejections = pd.DataFrame(
        rejections, columns=["period_type", "period_date", "rule", "raw_values"]
    )
    return valid, rejections


def store_financials(session: Session, stock_id: int, df: pd.DataFrame) -> int:
    """Upsert validated financial periods for one stock and return how many were written.

    Takes the valid frame from validate_financials(). Does not commit.
    """
    records = [
        {
            "stock_id": stock_id,
            "period_type": row["period_type"],
            "period_date": row["period_date"],
            **{col: to_decimal(row[col]) for col in STORED_COLUMNS},
        }
        for row in df.to_dict("records")
    ]
    if not records:  # an empty list runs one parameterless INSERT, not zero inserts
        return 0

    stmt = insert(FinancialData)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_financial_stock_period",
        # Plain excluded, no coalesce (unlike upsert_stock): there, None means "the fetch
        # failed, keep what we had"; here it means "checked and absent or proven wrong",
        # so it must overwrite a stored bad value, and restated figures replace old ones.
        set_={col: stmt.excluded[col] for col in STORED_COLUMNS},
    )
    session.execute(stmt, records)
    return len(records)
