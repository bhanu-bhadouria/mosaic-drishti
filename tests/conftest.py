"""
Shared fixtures. All test data is built by hand with obvious numbers, never
recorded from the network, so a failing test is easy to read.

Integration fixtures use a separate database (mosaic_drishti_test), rebuilt
from the Alembic migrations once per run; each test runs in a transaction
that is rolled back.
"""

from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings

ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE = "mosaic_drishti_test"


@pytest.fixture(autouse=True)
def _block_curl_cffi():
    """Block yfinance's HTTP client in every test.

    pytest-socket's --disable-socket only patches Python's socket module, but
    yfinance talks to Yahoo through curl_cffi (a C library with its own sockets),
    so a real Yahoo call would slip through. yfinance also swallows many errors,
    so the attempt is recorded and the test failed afterwards, not just raised.
    """
    attempts = []

    def blocked(self, method, url, *args, **kwargs):
        attempts.append(f"{method} {url}")
        raise RuntimeError(f"network access in tests is blocked: {method} {url}")

    with mock.patch("curl_cffi.requests.Session.request", blocked):
        yield
    if attempts:
        pytest.fail(f"test tried to reach the network: {attempts}")


# ── Unit-test data ────────────────────────────────────────────────────────────


@pytest.fixture
def make_prices():
    """Factory: n clean daily price rows (open 100, high 105, low 95, close 101)."""

    # Default 100 rows, so one broken row (1%) stays under the 5% reject threshold
    def _make(n: int = 100) -> pd.DataFrame:
        start = date(2024, 1, 1)
        return pd.DataFrame(
            {
                "date": [start + timedelta(days=i) for i in range(n)],
                "open_price": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 101.0,
                "adjusted_close": 100.5,
                "volume": 1000.0,
            }
        )

    return _make


@pytest.fixture
def make_financials():
    """Factory: one financials row per (period_date, overrides) pair, all values sane."""

    def _make(*periods: tuple[date, dict]) -> pd.DataFrame:
        base = {
            "period_type": "annual",
            "revenue": 1000.0,
            "net_income": 100.0,
            "eps_basic": 10.0,
            "eps_diluted": 10.0,
            "ebit": 150.0,
            "total_debt": 100.0,
            "stockholders_equity": 500.0,
            "total_assets": 1000.0,
            "current_liabilities": 200.0,
        }
        return pd.DataFrame(
            [{**base, "period_date": d, **overrides} for d, overrides in periods]
        )

    return _make


@pytest.fixture
def ratio_inputs():
    """Factory for compute_ratios inputs: annual rows with an id, plus a price table."""

    def _fin(*rows: dict) -> pd.DataFrame:
        base = {
            "net_income": 100.0,
            "eps": 10.0,
            "ebit": 150.0,
            "total_debt": 100.0,
            "stockholders_equity": 500.0,
            "total_assets": 1000.0,
            "current_liabilities": 200.0,
        }
        return pd.DataFrame(
            [{**base, "id": i + 1, **row} for i, row in enumerate(rows)]
        )

    def _prices(*pairs: tuple[date, float]) -> pd.DataFrame:
        return pd.DataFrame(pairs, columns=["date", "close"])

    return _fin, _prices


@pytest.fixture
def statement():
    """Factory: a yfinance-shaped statement (labels as rows, period dates as columns)."""

    def _make(values: dict[str, list[float]], dates: list[str]) -> pd.DataFrame:
        return pd.DataFrame(values, index=pd.to_datetime(dates)).T

    return _make


# ── Integration database ──────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def test_engine():
    """Engine for a freshly migrated mosaic_drishti_test database.

    Dropped and rebuilt each run, which also proves the migrations can build
    the whole schema from nothing.
    """
    url = make_url(settings.DATABASE_URL).set(database=TEST_DATABASE)
    assert url.database.endswith("_test"), "refusing to touch a non-test database"

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
    admin.dispose()

    engine = create_engine(url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn  # env.py migrates this connection
        command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(test_engine):
    """A connection inside an outer transaction that is always rolled back."""
    with test_engine.connect() as conn:
        outer = conn.begin()
        yield conn
        outer.rollback()


@pytest.fixture
def db_session(db_connection):
    """A session whose commits become savepoints, so nothing outlives the test."""
    with Session(bind=db_connection, join_transaction_mode="create_savepoint") as s:
        yield s


@pytest.fixture
def test_sessionmaker(db_connection):
    """Stand-in for SessionLocal, bound to the rolled-back test connection."""
    return sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")
