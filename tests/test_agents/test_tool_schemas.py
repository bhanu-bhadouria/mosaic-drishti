"""Tool output models: no unexplained NULLs, no NaN, money in crore."""

import json
from decimal import Decimal

import numpy as np
import pytest
from pydantic import ValidationError

from agents.tools.schemas import Metric, ToolError, inr_to_crore


# ── Metric ────────────────────────────────────────────────────────────────────


def test_metric_with_value_only_is_ok():
    m = Metric(value=0.2, unit="fraction")
    assert (m.value, m.reason) == (0.2, None)


def test_metric_with_reason_only_is_ok():
    m = Metric(unit="times", reason="EPS is negative, so P/E is undefined")
    assert m.value is None


def test_metric_with_both_is_rejected():
    with pytest.raises(ValidationError, match="exactly one of value or reason"):
        Metric(value=0.2, unit="fraction", reason="also a reason")


def test_metric_with_neither_is_rejected():
    with pytest.raises(ValidationError, match="exactly one of value or reason"):
        Metric(unit="fraction")


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_metric_rejects_nan_and_inf(bad):
    # NaN would be an unexplained null in disguise
    with pytest.raises(ValidationError):
        Metric(value=bad, unit="fraction")


def test_metric_rejects_unknown_unit_and_extra_fields():
    with pytest.raises(ValidationError):
        Metric(value=1.0, unit="percent")
    with pytest.raises(ValidationError):
        Metric(value=1.0, unit="count", err_msg="typo'd field")


# ── inr_to_crore ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rupees",
    [2670210000000.0, Decimal("2670210000000.00"), np.float64(2670210000000.0)],
)
def test_inr_to_crore(rupees):
    assert inr_to_crore(rupees) == 267021.0


@pytest.mark.parametrize("missing", [None, float("nan"), np.nan, Decimal("NaN")])
def test_inr_to_crore_missing_is_none_not_nan(missing):
    assert inr_to_crore(missing) is None


# ── ToolError ─────────────────────────────────────────────────────────────────


def test_tool_error_dumps_to_json_with_expected_keys():
    err = ToolError(
        error="unknown_symbol",
        message="TSC.NS is not in the research universe",
        suggestions=["TCS.NS"],
    )
    payload = json.loads(json.dumps(err.model_dump(mode="json")))
    assert payload == {
        "error": "unknown_symbol",
        "message": "TSC.NS is not in the research universe",
        "suggestions": ["TCS.NS"],
    }


def test_tool_error_rejects_unknown_error_kind():
    with pytest.raises(ValidationError):
        ToolError(error="timeout", message="x")
