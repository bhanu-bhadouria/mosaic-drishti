"""resolve_symbol: forgiving input, never a guess, never an exception."""

import pytest

from agents.tools.schemas import ToolError
from agents.tools.symbols import SymbolMatch, resolve_symbol
from data.universe import ALIASES, NIFTY_50


@pytest.mark.parametrize(
    "query, symbol, matched_by",
    [
        ("TCS.NS", "TCS.NS", "symbol"),
        ("tcs.ns", "TCS.NS", "symbol"),
        (" TCS.NS ", "TCS.NS", "symbol"),
        ("tcs", "TCS.NS", "symbol"),
        ("HUL", "HINDUNILVR.NS", "alias"),
        ("l&t", "LT.NS", "alias"),
        ("tata consultancy", "TCS.NS", "name"),
        ("Sun Pharma", "SUNPHARMA.NS", "name"),
    ],
)
def test_matches(query, symbol, matched_by):
    result = resolve_symbol(query)
    assert isinstance(result, SymbolMatch)
    assert (result.symbol, result.matched_by) == (symbol, matched_by)
    assert result.name == NIFTY_50[symbol]
    assert result.as_of is None  # no stored data was read


def test_ambiguous_word_lists_every_candidate():
    result = resolve_symbol("bank")
    banks = {"HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS"}
    assert isinstance(result, ToolError)
    assert result.error == "ambiguous_symbol"
    assert {s.split(" ")[0] for s in result.suggestions} == banks
    assert "HDFCBANK.NS (HDFC Bank)" in result.suggestions  # names help the LLM ask


def test_misspelling_suggests_close_matches():
    result = resolve_symbol("TSC")
    assert isinstance(result, ToolError)
    assert result.error == "unknown_symbol"
    assert "TCS.NS (Tata Consultancy Services)" in result.suggestions


def test_nonsense_is_unknown_with_no_suggestions():
    result = resolve_symbol("zzzzqqq")
    assert (result.error, result.suggestions) == ("unknown_symbol", [])


@pytest.mark.parametrize("query", ["", "   ", None])
def test_empty_input_is_invalid(query):
    result = resolve_symbol(query)
    assert isinstance(result, ToolError)
    assert result.error == "invalid_input"


def test_aliases_only_point_into_the_universe():
    assert set(ALIASES.values()) <= set(NIFTY_50)
    assert all(alias == alias.upper() for alias in ALIASES)
