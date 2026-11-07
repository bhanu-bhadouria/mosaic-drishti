"""
Converters from pandas/numpy values to the Python types the database expects.

Shared by price and financials ingestion. Both are safe to call on unvalidated
data: NaN always becomes None, never a stored 'NaN'.
"""

from decimal import Decimal

import pandas as pd


def to_decimal(value) -> Decimal | None:
    """NaN/None -> None, otherwise an exact Decimal of the printed float.

    Checks NaN first because Postgres NUMERIC would happily store 'NaN'.
    str() first so 3899.949951171875 becomes Decimal("3899.949951171875"),
    not the float's full binary expansion; Postgres then rounds to the column's scale.
    """
    if value is None or pd.isna(value):
        return None
    return Decimal(str(value))


def to_int(value) -> int | None:
    """NaN/None -> None, otherwise int (one NaN turns a whole column into floats)."""
    if value is None or pd.isna(value):
        return None
    return int(value)
