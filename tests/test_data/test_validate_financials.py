"""validate_financials: reject what's impossible, not what's unusual."""

from datetime import date

import pandas as pd

from data.ingestion.financials_ingestion import validate_financials

FY23, FY24, FY25 = date(2023, 3, 31), date(2024, 3, 31), date(2025, 3, 31)


def test_hdfc_eps_pattern_is_nulled_and_rest_kept(make_financials):
    df = make_financials(
        (FY23, {"eps_basic": 44.51, "eps_diluted": 88.68}),
        (FY24, {"eps_basic": 88.66, "eps_diluted": 44.16}),
        (FY25, {"eps_basic": 45.01, "eps_diluted": 44.82}),
    )
    valid, rejections = validate_financials("HDFCBANK.NS", df)

    assert rejections["rule"].tolist() == ["eps_mismatch", "eps_mismatch"]
    assert rejections["period_date"].tolist() == [FY23, FY24]
    assert rejections.loc[0, "raw_values"] == {"eps_basic": 44.51, "eps_diluted": 88.68}

    assert valid["eps"].isna().tolist() == [True, True, False]
    assert valid.loc[2, "eps"] == 44.82  # stored eps is diluted
    assert valid["revenue"].tolist() == [1000.0] * 3  # good fields survive


def test_output_has_single_eps_column(make_financials):
    valid, _ = validate_financials("TCS.NS", make_financials((FY25, {})))
    assert "eps" in valid.columns
    assert not {"eps_basic", "eps_diluted"} & set(valid.columns)


def test_loss_year_is_not_an_eps_mismatch(make_financials):
    df = make_financials(
        (FY25, {"net_income": -100.0, "eps_basic": -10.0, "eps_diluted": -10.0})
    )
    valid, rejections = validate_financials("TCS.NS", df)
    assert rejections.empty
    assert valid.loc[0, "eps"] == -10.0


def test_unusual_but_real_values_pass(make_financials):
    # A loss, negative equity, and a 5x year-on-year jump (a merger) are all real
    df = make_financials(
        (
            FY24,
            {
                "net_income": -50.0,
                "eps_basic": -5.0,
                "eps_diluted": -5.0,
                "stockholders_equity": -20.0,
            },
        ),
        (FY25, {"revenue": 5000.0, "total_assets": 5000.0}),
    )
    _, rejections = validate_financials("TCS.NS", df)
    assert rejections.empty


def test_masks_are_computed_before_anything_is_nulled(make_financials):
    # Nulling total_assets for one rule must not hide the other rule
    df = make_financials((FY25, {"total_assets": -5.0, "stockholders_equity": 10.0}))
    valid, rejections = validate_financials("TCS.NS", df)
    assert set(rejections["rule"]) == {"non_positive_assets", "equity_exceeds_assets"}
    assert pd.isna(valid.loc[0, "total_assets"])
    assert pd.isna(valid.loc[0, "stockholders_equity"])


def test_future_period_is_dropped(make_financials):
    df = make_financials((FY25, {}), (date(2099, 3, 31), {}))
    valid, rejections = validate_financials("TCS.NS", df)
    assert valid["period_date"].tolist() == [FY25]
    assert rejections["rule"].tolist() == ["future_period"]
