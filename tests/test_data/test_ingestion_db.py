"""Integration tests against the real Postgres test database (mosaic_drishti_test).

Each test runs in a transaction that's rolled back. The network is always mocked.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

import pandas as pd
import pytest
from sqlalchemy import func, select, text

from data.ingestion import pipeline
from data.ingestion.exceptions import NoDataError
from data.ingestion.financials_ingestion import store_financials
from data.ingestion.price_ingestion import store_prices
from data.ingestion.ratios import update_ratios
from data.ingestion.stocks import upsert_stock
from data.schemas.models import FinancialData, PriceHistory, Stock

pytestmark = pytest.mark.integration

TCS_INFO = {
    "name": "Tata Consultancy Services",
    "sector": "Technology",
    "industry": "IT",
    "exchange": "NSE",
}
FY26 = date(2026, 3, 31)


def _valid_financials(**overrides) -> pd.DataFrame:
    """One annual period in the shape validate_financials returns."""
    row = {
        "period_type": "annual",
        "period_date": FY26,
        "revenue": 1000.0,
        "net_income": 100.0,
        "eps": 10.0,
        "ebit": 150.0,
        "total_debt": 100.0,
        "stockholders_equity": 500.0,
        "total_assets": 1000.0,
        "current_liabilities": 200.0,
    }
    return pd.DataFrame([{**row, **overrides}])


def _stored(session, column, stock_id):
    return session.scalar(select(column).where(FinancialData.stock_id == stock_id))


def test_migrations_build_the_schema_from_scratch(db_session):
    head = db_session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    assert head == "8ec34c228497"
    columns = db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'financial_data'"
        )
    ).scalars()
    assert {
        "ebit",
        "total_debt",
        "stockholders_equity",
        "total_assets",
        "current_liabilities",
    } <= set(columns)


def test_store_prices_twice_is_idempotent_and_updates(db_session, make_prices):
    stock_id = upsert_stock(db_session, "TCS.NS", TCS_INFO)
    prices = make_prices(5)
    count = (
        select(func.count())
        .select_from(PriceHistory)
        .where(PriceHistory.stock_id == stock_id)
    )

    assert store_prices(db_session, stock_id, prices) == 5
    store_prices(
        db_session, stock_id, prices.assign(adjusted_close=99.0)
    )  # e.g. a new dividend

    assert db_session.scalar(count) == 5
    assert db_session.scalar(select(PriceHistory.adjusted_close).limit(1)) == Decimal(
        "99.0000"
    )


def test_upsert_stock_keeps_sector_when_info_failed(db_session):
    first_id = upsert_stock(db_session, "TCS.NS", TCS_INFO)
    second_id = upsert_stock(
        db_session, "TCS.NS", {**TCS_INFO, "sector": None, "industry": None}
    )

    assert first_id == second_id
    stock = db_session.execute(
        select(Stock.sector, Stock.industry).where(Stock.id == first_id)
    ).one()
    assert (stock.sector, stock.industry) == ("Technology", "IT")


def test_store_financials_none_overwrites_stored_eps(db_session):
    stock_id = upsert_stock(db_session, "TCS.NS", TCS_INFO)
    store_financials(db_session, stock_id, _valid_financials(eps=44.16))
    store_financials(
        db_session, stock_id, _valid_financials(eps=float("nan"))
    )  # proven wrong

    assert _stored(db_session, FinancialData.eps, stock_id) is None
    rows = (
        select(func.count())
        .select_from(FinancialData)
        .where(FinancialData.stock_id == stock_id)
    )
    assert db_session.scalar(rows) == 1


def test_update_ratios_writes_none_over_a_stale_pe(db_session):
    stock_id = upsert_stock(db_session, "TCS.NS", TCS_INFO)
    store_prices(
        db_session,
        stock_id,
        pd.DataFrame(
            [
                {
                    "date": FY26,
                    "open_price": 200.0,
                    "high": 200.0,
                    "low": 200.0,
                    "close": 200.0,
                    "adjusted_close": 200.0,
                    "volume": 1.0,
                }
            ]
        ),
    )
    store_financials(db_session, stock_id, _valid_financials())
    update_ratios(db_session, stock_id)
    assert _stored(db_session, FinancialData.pe_ratio, stock_id) == Decimal("20.0000")

    store_financials(db_session, stock_id, _valid_financials(eps=float("nan")))
    assert update_ratios(db_session, stock_id) == 1

    assert _stored(db_session, FinancialData.pe_ratio, stock_id) is None
    assert _stored(db_session, FinancialData.pb_ratio, stock_id) is None
    assert _stored(db_session, FinancialData.roe, stock_id) == Decimal(
        "0.2000"
    )  # doesn't use EPS


def test_ingest_ticker_is_partial_when_financials_fail(
    db_session, test_sessionmaker, make_prices
):
    with (
        mock.patch.object(pipeline, "SessionLocal", test_sessionmaker),
        mock.patch.object(pipeline, "fetch_stock_info", return_value=TCS_INFO),
        mock.patch.object(pipeline, "fetch_prices", return_value=make_prices(100)),
        mock.patch.object(
            pipeline,
            "fetch_financials",
            side_effect=NoDataError("TCS.NS", "no financial statements"),
        ),
    ):
        result = pipeline.ingest_ticker("TCS.NS")

    assert result.status == "partial"
    assert result.financials_error == "NoDataError: TCS.NS: no financial statements"
    assert (result.prices_written, result.financials_written) == (100, 0)
    assert db_session.scalar(select(func.count()).select_from(PriceHistory)) == 100
    assert db_session.scalar(select(func.count()).select_from(FinancialData)) == 0
