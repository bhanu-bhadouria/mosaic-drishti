"""convert: NaN never reaches the database as Decimal('NaN')."""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from data.ingestion.convert import to_decimal, to_int


@pytest.mark.parametrize(
    "missing", [None, float("nan"), np.nan, np.float64("nan"), pd.NA]
)
def test_missing_values_become_none(missing):
    assert to_decimal(missing) is None
    assert to_int(missing) is None


def test_decimal_keeps_the_printed_value_not_the_binary_expansion():
    assert to_decimal(np.float64(3899.949951171875)) == Decimal("3899.949951171875")
    # Decimal(0.1) would be 0.1000000000000000055...
    assert to_decimal(0.1) == Decimal("0.1")


def test_int_from_float_column():
    # One NaN in a column makes every volume a float
    value = to_int(np.float64(2382510.0))
    assert value == 2382510
    assert type(value) is int
