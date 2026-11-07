"""compute_ratios: the finance logic, with numbers you can check by hand."""

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from data.ingestion.ratios import RATIO_COLUMNS, compute_ratios

FY25, FY26 = date(2025, 3, 31), date(2026, 3, 31)


def test_hand_made_row(ratio_inputs):
    fin, prices = ratio_inputs
    # net income 100, equity 500, EPS 10, price 200, debt 100, EBIT 150, capital 800
    r = compute_ratios(
        fin({"period_date": FY26}), prices((FY26, 200.0)), is_financial=False
    )
    assert r.loc[0, "roe"] == pytest.approx(0.20)
    assert r.loc[0, "pe_ratio"] == pytest.approx(20.0)
    assert r.loc[0, "pb_ratio"] == pytest.approx(4.0)
    assert r.loc[0, "debt_to_equity"] == pytest.approx(0.20)
    assert r.loc[0, "roce"] == pytest.approx(0.1875)


def test_decimal_inputs_from_the_database_work(ratio_inputs):
    fin, prices = ratio_inputs
    f = fin(
        {
            "period_date": FY26,
            "net_income": Decimal("100"),
            "stockholders_equity": Decimal("500"),
        }
    )
    r = compute_ratios(f, prices((FY26, Decimal("200.0000"))), is_financial=False)
    assert r.loc[0, "roe"] == pytest.approx(0.20)
    assert r.loc[0, "pe_ratio"] == pytest.approx(20.0)


def test_share_basis_mismatch_nulls_pe_and_pb(ratio_inputs):
    fin, prices = ratio_inputs
    # Older year: EPS 20 on the same net income -> half the implied shares
    f = fin({"period_date": FY25, "eps": 20.0}, {"period_date": FY26, "eps": 10.0})
    r = compute_ratios(f, prices((FY25, 200.0), (FY26, 200.0)), is_financial=False)
    assert r["pe_ratio"].isna().tolist() == [True, False]
    assert r["pb_ratio"].isna().tolist() == [True, False]
    assert r["roe"].notna().all()  # ROE doesn't use EPS


@pytest.mark.parametrize("is_financial", [True, None])
def test_financial_or_unknown_sector_skips_de_and_roce(ratio_inputs, is_financial):
    fin, prices = ratio_inputs
    r = compute_ratios(fin({"period_date": FY26}), prices((FY26, 200.0)), is_financial)
    assert r[["debt_to_equity", "roce"]].isna().all(axis=None)
    assert r.loc[0, "roe"] == pytest.approx(0.20)


@pytest.mark.parametrize("value", [0.0, -50.0])
@pytest.mark.parametrize(
    "column, nulled",
    [
        ("stockholders_equity", ["roe", "debt_to_equity", "pb_ratio"]),
        ("eps", ["pe_ratio", "pb_ratio"]),
        # Overridden below so capital employed = total assets - liabilities = value
        ("current_liabilities", ["roce"]),
    ],
)
def test_zero_or_negative_denominator_gives_null_never_inf(
    ratio_inputs, column, nulled, value
):
    fin, prices = ratio_inputs
    override = 1000.0 - value if column == "current_liabilities" else value
    r = compute_ratios(
        fin({"period_date": FY26, column: override}), prices((FY26, 200.0)), False
    )
    assert r[nulled].isna().all(axis=None)
    assert not np.isinf(r[RATIO_COLUMNS].to_numpy(dtype=float)).any()


def test_last_close_within_7_days_is_used(ratio_inputs):
    fin, prices = ratio_inputs
    period_end = date(2025, 3, 30)  # a Sunday
    r = compute_ratios(
        fin({"period_date": period_end}),
        prices((date(2025, 3, 23), 300.0), (date(2025, 3, 28), 200.0)),
        is_financial=False,
    )
    # Friday's close, not the older one
    assert r.loc[0, "pe_ratio"] == pytest.approx(20.0)


def test_no_price_within_7_days_gives_null_pe(ratio_inputs):
    fin, prices = ratio_inputs
    r = compute_ratios(
        fin({"period_date": FY26}), prices((date(2026, 3, 23), 200.0)), False
    )
    assert pd.isna(r.loc[0, "pe_ratio"])
    assert r.loc[0, "roe"] == pytest.approx(0.20)
