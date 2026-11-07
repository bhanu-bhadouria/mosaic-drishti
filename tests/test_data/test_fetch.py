"""The fetch functions, with yfinance mocked: no network in unit tests."""

from unittest import mock

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from data.ingestion import financials_ingestion, price_ingestion, stocks
from data.ingestion.exceptions import IngestionError, NoDataError, UnknownTickerError


def _history(columns=("Open", "High", "Low", "Close", "Adj Close", "Volume"), rows=2):
    index = pd.date_range("2024-01-01", periods=rows, tz="Asia/Kolkata")
    return pd.DataFrame(
        {c: [100.0 + i for i in range(rows)] for c in columns}, index=index
    )


@pytest.fixture
def ticker():
    """Patch yf.Ticker everywhere it's looked up; returns the mock class."""
    with (
        mock.patch.object(price_ingestion.yf, "Ticker") as cls,
        mock.patch.object(stocks.yf, "Ticker", cls),
        mock.patch.object(financials_ingestion.yf, "Ticker", cls),
    ):
        yield cls


# ── fetch_prices ──────────────────────────────────────────────────────────────


def test_unknown_ticker_raises_before_any_network_call(ticker):
    with pytest.raises(UnknownTickerError):
        price_ingestion.fetch_prices("FAKE.NS")
    ticker.assert_not_called()


def test_empty_result_raises_no_data(ticker):
    ticker.return_value.history.return_value = pd.DataFrame()
    with pytest.raises(NoDataError):
        price_ingestion.fetch_prices("TCS.NS")


def test_missing_column_is_systemic_not_an_ingestion_error(ticker):
    ticker.return_value.history.return_value = _history(
        columns=("Open", "High", "Low", "Close", "Volume")
    )
    with pytest.raises(RuntimeError, match="Adj Close") as exc:
        price_ingestion.fetch_prices("TCS.NS")
    assert not isinstance(exc.value, IngestionError)  # so ingest_all won't swallow it


def test_prices_are_reshaped_to_db_columns(ticker):
    ticker.return_value.history.return_value = _history().assign(
        **{"Capital Gains": 0.0}
    )
    df = price_ingestion.fetch_prices("TCS.NS")
    assert df.columns.tolist() == [
        "date",
        "open_price",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
    ]
    assert [d.isoformat() for d in df["date"]] == [
        "2024-01-01",
        "2024-01-02",
    ]  # Python dates


def test_period_defaults_to_settings_and_unadjusted_prices(ticker):
    ticker.return_value.history.return_value = _history()
    price_ingestion.fetch_prices("TCS.NS")
    ticker.return_value.history.assert_called_once_with(
        period="5y", auto_adjust=False, actions=False
    )


# ── fetch_stock_info ──────────────────────────────────────────────────────────


def _set_info(ticker, **kwargs):
    type(ticker.return_value).info = mock.PropertyMock(**kwargs)


def test_info_uses_universe_name_and_yahoo_sector(ticker):
    _set_info(
        ticker,
        return_value={
            "longName": "Yahoo's Long Name",
            "sector": "Technology",
            "industry": "IT",
        },
    )
    info = stocks.fetch_stock_info("TCS.NS")
    assert info == {
        "name": "Tata Consultancy Services",
        "sector": "Technology",
        "industry": "IT",
        "exchange": "NSE",
    }


def test_rate_limit_propagates_from_info(ticker):
    _set_info(ticker, side_effect=YFRateLimitError())
    with pytest.raises(YFRateLimitError):
        stocks.fetch_stock_info("TCS.NS")


@pytest.mark.parametrize(
    "failure", [{"side_effect": ConnectionError("down")}, {"return_value": {}}]
)
def test_other_info_failures_degrade(ticker, failure):
    _set_info(ticker, **failure)
    info = stocks.fetch_stock_info("TCS.NS")
    assert info == {
        "name": "Tata Consultancy Services",
        "sector": None,
        "industry": None,
        "exchange": "NSE",
    }


# ── fetch_financials ──────────────────────────────────────────────────────────


def _set_statements(ticker, statement, income, balance, q_income=None, q_balance=None):
    t = ticker.return_value
    t.financials, t.balance_sheet = income, balance
    t.quarterly_financials = q_income if q_income is not None else pd.DataFrame()
    t.quarterly_balance_sheet = q_balance if q_balance is not None else pd.DataFrame()


def test_missing_labels_become_nan_and_periods_outer_join(ticker, statement):
    # A bank: no EBIT or current liabilities. Balance sheet covers one more year.
    income = statement(
        {
            "Total Revenue": [10.0],
            "Net Income": [2.0],
            "Basic EPS": [1.0],
            "Diluted EPS": [1.0],
        },
        ["2025-03-31"],
    )
    balance = statement(
        {
            "Total Debt": [5.0, 4.0],
            "Stockholders Equity": [20.0, 18.0],
            "Total Assets": [100.0, 90.0],
        },
        ["2025-03-31", "2024-03-31"],
    )
    _set_statements(ticker, statement, income, balance)
    df = financials_ingestion.fetch_financials("HDFCBANK.NS")

    assert len(df) == 2  # the balance-sheet-only year survives (outer join)
    assert df["ebit"].isna().all() and df["current_liabilities"].isna().all()
    assert df["revenue"].isna().tolist() == [
        True,
        False,
    ]  # 2024 has no income statement
    assert (df[financials_ingestion.VALUE_COLUMNS].dtypes == "float64").all()


def test_all_nan_period_is_dropped(ticker, statement):
    income = statement(
        {"Total Revenue": [10.0, float("nan")]}, ["2025-03-31", "2022-03-31"]
    )
    _set_statements(ticker, statement, income, pd.DataFrame())
    df = financials_ingestion.fetch_financials("TCS.NS")
    assert [d.isoformat() for d in df["period_date"]] == ["2025-03-31"]


def test_no_statements_raises_no_data(ticker):
    _set_statements(ticker, None, pd.DataFrame(), pd.DataFrame())
    with pytest.raises(NoDataError, match="no financial statements"):
        financials_ingestion.fetch_financials("TCS.NS")


def test_unexpected_text_fails_loudly_instead_of_becoming_nan(ticker, statement):
    income = statement({"Total Revenue": ["not a number"]}, ["2025-03-31"])
    _set_statements(ticker, statement, income, pd.DataFrame())
    with pytest.raises(ValueError):
        financials_ingestion.fetch_financials("TCS.NS")
