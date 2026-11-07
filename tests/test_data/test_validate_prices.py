"""validate_prices: each rule fires with the right reason, and the 5% threshold."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from config.settings import settings
from data.ingestion.exceptions import DataQualityError
from data.ingestion.price_ingestion import MARKET_TZ, validate_prices


def test_clean_prices_pass(make_prices):
    df = make_prices()
    valid, rejected = validate_prices("TCS.NS", df)
    assert len(valid) == 100
    assert rejected.empty
    assert "reason" not in valid.columns


# Clean rows are open 100, high 105, low 95, close 101; each value breaks exactly one rule
@pytest.mark.parametrize(
    "column, value, reason",
    [
        ("close", np.nan, "missing_price"),
        ("adjusted_close", 0.0, "non_positive_price"),
        ("high", 99.0, "high_below_others"),
        ("low", 100.5, "low_above_others"),
        ("volume", -1.0, "negative_volume"),
        ("date", datetime.now(MARKET_TZ).date() + timedelta(days=5), "future_date"),
    ],
)
def test_each_rule_rejects_with_its_reason(make_prices, column, value, reason):
    df = make_prices()
    df.loc[3, column] = value
    valid, rejected = validate_prices("TCS.NS", df)
    assert rejected.index.tolist() == [3]
    assert rejected.loc[3, "reason"] == reason
    assert len(valid) == 99


def test_duplicate_date_keeps_the_first_copy(make_prices):
    df = make_prices()
    df.loc[5, "date"] = df.loc[4, "date"]
    valid, rejected = validate_prices("TCS.NS", df)
    assert rejected.index.tolist() == [5]
    assert rejected.loc[5, "reason"] == "duplicate_date"
    assert 4 in valid.index


def test_row_breaking_two_rules_lists_both(make_prices):
    df = make_prices()
    df.loc[2, ["close", "volume"]] = [np.nan, -1.0]
    _, rejected = validate_prices("TCS.NS", df)
    assert rejected.loc[2, "reason"] == "missing_price; negative_volume"


def test_missing_volume_is_allowed(make_prices):
    df = make_prices()
    df.loc[2, "volume"] = np.nan  # becomes NULL, not a rejection
    _, rejected = validate_prices("TCS.NS", df)
    assert rejected.empty


def test_float_noise_within_tolerance_passes(make_prices):
    df = make_prices()
    df.loc[1, ["open_price", "high", "low", "close"]] = [
        3890.0,
        3899.9999,
        3880.0,
        3900.0,
    ]
    _, rejected = validate_prices("TCS.NS", df)
    assert rejected.empty


def test_gap_beyond_tolerance_is_rejected(make_prices):
    df = make_prices()
    df.loc[1, ["open_price", "high", "low", "close"]] = [
        3890.0,
        3899.98,
        3880.0,
        3900.0,
    ]
    _, rejected = validate_prices("TCS.NS", df)
    assert rejected.loc[1, "reason"] == "high_below_others"


def test_reject_ratio_at_4_9_percent_passes(make_prices):
    df = make_prices(1000)
    df.loc[:48, "volume"] = -1.0  # 49 rows
    _, rejected = validate_prices("TCS.NS", df)
    assert len(rejected) == 49


def test_reject_ratio_of_exactly_5_percent_passes(make_prices):
    # The rule is "more than 5%": the boundary itself is allowed
    df = make_prices(1000)
    df.loc[:49, "volume"] = -1.0  # 50 rows
    _, rejected = validate_prices("TCS.NS", df)
    assert len(rejected) == 50


def test_reject_ratio_at_5_1_percent_raises_with_counts(make_prices):
    assert settings.MAX_REJECT_RATIO == 0.05
    df = make_prices(1000)
    df.loc[:50, "volume"] = -1.0  # 51 rows
    with pytest.raises(DataQualityError) as exc:
        validate_prices("INFY.NS", df)
    assert (exc.value.symbol, exc.value.failed, exc.value.total) == (
        "INFY.NS",
        51,
        1000,
    )
    assert str(exc.value) == "INFY.NS: 51/1000 rows failed validation"
