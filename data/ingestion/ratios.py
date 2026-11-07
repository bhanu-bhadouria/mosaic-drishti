"""
Derived financial ratios, calculated from the raw values we store.

compute_ratios() is a pure function: DataFrames in, DataFrame out, no database
or network, so the finance logic can be tested with hand-made numbers.
update_ratios() is the thin database layer around it.

All ratios are stored as fractions (ROE 0.4823, not 48.23); the display layer
formats them as percentages. Never multiply by 100 here.
"""

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from data.ingestion.convert import to_decimal
from data.schemas.models import FinancialData, PriceHistory, Stock

# A period's implied share count (net income / EPS) must be within 10% of the
# most recent period's, or its EPS is on a different share basis (e.g. before a
# bonus issue) and its P/E would be off by that factor. A real share issue, such
# as a merger, also fails this; an unknown P/E is better than a wrong one.
SHARE_BASIS_TOLERANCE = 0.10

# Period ends often fall on a weekend or holiday: use the last close on or
# before the period end, at most this far back.
PRICE_WINDOW = pd.Timedelta(days=7)

RATIO_COLUMNS = ["debt_to_equity", "roe", "roce", "pe_ratio", "pb_ratio"]

# Sectors where D/E and ROCE are meaningless (a bank's debt is its raw material)
FINANCIAL_SECTORS = {"Financial Services"}


def compute_ratios(
    fin: pd.DataFrame, prices: pd.DataFrame, is_financial: bool | None
) -> pd.DataFrame:
    """Calculate the five ratios for annual financial periods.

    fin: annual rows with id, period_date, net_income, eps, ebit, total_debt,
    stockholders_equity, total_assets, current_liabilities.
    prices: date and close for the same stock.
    is_financial: None (sector unknown) is treated like True, so a bank whose
    sector lookup failed never gets a meaningless D/E or ROCE.

    Returns id plus RATIO_COLUMNS. A ratio is NULL wherever it would be
    meaningless; no division is ever done by zero or a negative denominator.
    """
    values = ["net_income", "eps", "ebit", "total_debt", "stockholders_equity"]
    values += ["total_assets", "current_liabilities"]
    # Values read from the database arrive as Decimal; ratios are calculated in float
    f = fin[["id", "period_date", *values]].copy()
    f[values] = f[values].astype("float64")
    f["period_date"] = pd.to_datetime(f["period_date"])

    # close, not adjusted_close: adjusted_close is back-adjusted for every dividend
    # paid since, so a 2023 adjusted price is lower than what the market actually
    # paid then, understating that year's P/E, and it keeps changing with each
    # new dividend. P/E compares a period's EPS with the price
    # the market paid at that time. Note Yahoo's close is still split/bonus-adjusted,
    # which is why the share-basis check below is needed.
    p = prices[["date", "close"]].dropna().copy()
    p["close"] = p["close"].astype("float64")
    p["date"] = pd.to_datetime(p["date"])

    df = pd.merge_asof(
        f.sort_values("period_date"),
        p.sort_values("date"),
        left_on="period_date",
        right_on="date",
        direction="backward",
        tolerance=PRICE_WINDOW,
    )

    # Masks first, all on the original values, before any ratio is calculated
    ni, eps, price = df["net_income"], df["eps"], df["close"]
    equity = df["stockholders_equity"]
    capital_employed = df["total_assets"] - df["current_liabilities"]
    sector_ok = is_financial is False  # unknown sector (None) is treated as financial

    equity_ok = equity > 0
    capital_ok = capital_employed > 0
    eps_ok = eps > 0

    # The share count each EPS was calculated on, compared with the most recent
    # usable period's (rows are sorted by date). If none is usable, latest is NaN
    # and every comparison is False, so no P/E is calculated.
    implied_shares = (ni / eps.where(eps_ok)).where(lambda s: s > 0)
    known_shares = implied_shares.dropna()
    latest_shares = known_shares.iloc[-1] if len(known_shares) else float("nan")
    basis_ok = (
        implied_shares - latest_shares
    ).abs() <= SHARE_BASIS_TOLERANCE * latest_shares

    # Every denominator is masked to NaN before dividing, so no ratio can be inf
    df["roe"] = ni / equity.where(equity_ok)
    df["debt_to_equity"] = df["total_debt"] / equity.where(equity_ok & sector_ok)
    df["roce"] = df["ebit"] / capital_employed.where(capital_ok & sector_ok)
    df["pe_ratio"] = price / eps.where(eps_ok & price.notna() & basis_ok)
    # P/B = price / book value per share = (price / EPS) * (net income / equity) = P/E * ROE.
    # Needs no share count, and inherits the share-basis check from P/E.
    # Limitation: P/B is therefore NULL for loss years (EPS <= 0), even though a
    # loss-making company with positive book value has a real P/B. Not a bug.
    df["pb_ratio"] = df["pe_ratio"] * df["roe"]

    return df[["id", *RATIO_COLUMNS]]


def update_ratios(session: Session, stock_id: int) -> int:
    """Recalculate and write the ratios for every annual period of one stock.

    Reads through the caller's session, so it sees financials and prices written
    earlier in the same, uncommitted transaction: raw values and their ratios
    commit together or not at all. Does not commit. Returns rows updated.
    """
    conn = session.connection()
    fin = pd.read_sql(
        select(FinancialData).where(
            FinancialData.stock_id == stock_id, FinancialData.period_type == "annual"
        ),
        conn,
    )
    if fin.empty:
        return 0
    prices = pd.read_sql(
        select(PriceHistory.date, PriceHistory.close).where(
            PriceHistory.stock_id == stock_id
        ),
        conn,
    )
    sector = session.scalar(select(Stock.sector).where(Stock.id == stock_id))
    is_financial = None if sector is None else sector in FINANCIAL_SECTORS

    ratios = compute_ratios(fin, prices, is_financial)
    # All five columns for every row, None included: if a re-ingestion nulled a bad
    # EPS, the P/E calculated from it must become NULL too, not survive stale.
    records = [
        {"id": row["id"], **{col: to_decimal(row[col]) for col in RATIO_COLUMNS}}
        for row in ratios.to_dict("records")
    ]
    # Bulk UPDATE by primary key: each dict's id says which row; no WHERE needed
    session.execute(update(FinancialData), records)
    return len(records)
