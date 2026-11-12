"""
Output models shared by every agent tool.

The LLM reads these field names and docstrings, so both are written for it:
descriptive names (revenue_crore, not rev) and one-line explanations.

Money leaves the tool layer in ₹ crore, not raw rupees: LLMs miscount zeros in
long numbers, and Indian analysts think in crore. The database keeps exact
rupees; the conversion is presentation only.
"""

import math
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RUPEES_PER_CRORE = 10_000_000

Unit = Literal["INR_crore", "INR_per_share", "fraction", "times", "count"]
"""INR_crore: money in ₹ crore. INR_per_share: e.g. EPS, price. fraction: 0.2 means 20%.
times: a multiple, e.g. P/E 20 means 20x. count: a plain number of things."""


def inr_to_crore(value: float | Decimal | None) -> float | None:
    """Rupees -> ₹ crore (1 crore = 10,000,000). None or NaN -> None, never NaN."""
    if value is None:
        return None
    rupees = float(value)
    if math.isnan(rupees):
        return None
    return rupees / RUPEES_PER_CRORE


class _Model(BaseModel):
    # A misspelled field is an error, not silently dropped
    model_config = ConfigDict(extra="forbid")


class Metric(_Model):
    """One number with its unit. If the number is unavailable, reason says why.

    Exactly one of value and reason is set, so a missing number always comes
    with an explanation.
    """

    value: float | None = Field(
        default=None, allow_inf_nan=False, description="The number, in the given unit."
    )
    unit: Unit = Field(description="How to read value, e.g. fraction 0.2 means 20%.")
    reason: str | None = Field(
        default=None,
        description="Why value is unavailable. Only set when value is null.",
    )

    @model_validator(mode="after")
    def _value_or_reason(self) -> Self:
        if (self.value is None) == (self.reason is None):
            raise ValueError("set exactly one of value or reason")
        return self


class Caveat(_Model):
    """A known data issue that affects this result. Mention it when using the numbers."""

    code: str = Field(description='Stable identifier, e.g. "hdfc_equity_unverified".')
    message: str = Field(
        description="What the issue is and how it affects the numbers."
    )


class ToolResult(_Model):
    """Base for every successful tool result.

    as_of says how fresh the data is (None if the result doesn't depend on stored
    data, e.g. resolving a symbol); caveats lists known issues to mention.
    """

    # Required but nullable: every tool must state it explicitly, even if it's None
    as_of: datetime | None = Field(
        description="When the underlying data was last updated; null if no stored data was used."
    )
    caveats: list[Caveat] = Field(
        default_factory=list, description="Known data issues affecting this result."
    )


class ToolError(_Model):
    """Returned instead of a result when a tool can't answer. Tools never raise to the LLM."""

    error: Literal["unknown_symbol", "ambiguous_symbol", "no_data", "invalid_input"] = (
        Field(description="What kind of failure this is.")
    )
    message: str = Field(description="What went wrong, in plain words.")
    suggestions: list[str] = Field(
        default_factory=list,
        description="What to try instead, e.g. valid symbols close to the one given.",
    )
