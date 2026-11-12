"""
resolve_symbol(): turn how people and LLMs name a company into a universe symbol.

Ingestion stays strict (an unknown symbol raises); this tool is forgiving about
input but never guesses: several matches come back as ambiguous_symbol so the
LLM can ask the user. A pure function: it reads only the universe and aliases,
never the database or the network, and it never raises.
"""

import difflib
from typing import Literal

from pydantic import Field

from agents.tools.schemas import ToolError, ToolResult
from data.universe import ALIASES, NIFTY_50

SUFFIX = ".NS"

# How close a misspelling must be to get suggested (difflib ratio, 0-1)
SUGGESTION_CUTOFF = 0.6
MAX_SUGGESTIONS = 5


class SymbolMatch(ToolResult):
    """The universe symbol a query refers to. Tell the user what was assumed."""

    symbol: str = Field(
        description='The exchange symbol to use with other tools, e.g. "TCS.NS".'
    )
    name: str = Field(description="The company's name.")
    matched_by: Literal["symbol", "alias", "name"] = Field(
        description="How the query was matched; e.g. alias means 'HUL' was taken as Hindustan Unilever."
    )


def _label(symbol: str) -> str:
    return f"{symbol} ({NIFTY_50[symbol]})"


def _match(symbol: str, matched_by: str) -> SymbolMatch:
    return SymbolMatch(
        as_of=None, symbol=symbol, name=NIFTY_50[symbol], matched_by=matched_by
    )


def resolve_symbol(query: str) -> SymbolMatch | ToolError:
    """Resolve a symbol, short form or part of a company name to one universe symbol."""
    if not isinstance(query, str) or not query.strip():
        return ToolError(
            error="invalid_input",
            message="Give a stock symbol or company name, e.g. TCS.NS or Tata Consultancy.",
        )
    q = query.strip().upper()

    # 1. An exact symbol, then 2. a symbol without its suffix
    for candidate in (q, q + SUFFIX):
        if candidate in NIFTY_50:
            return _match(candidate, "symbol")

    # 3. A common alias
    if q in ALIASES:
        return _match(ALIASES[q], "alias")

    # 4. Part of a company name: one match is an answer, several need the user to choose
    in_name = [s for s, name in NIFTY_50.items() if q.casefold() in name.casefold()]
    if len(in_name) == 1:
        return _match(in_name[0], "name")
    if in_name:
        return ToolError(
            error="ambiguous_symbol",
            message=f"'{query.strip()}' matches {len(in_name)} companies; ask which one is meant.",
            suggestions=[_label(s) for s in in_name],
        )

    # 5. Nothing matched: suggest close spellings of symbols, aliases and names
    spellings = {s.removesuffix(SUFFIX): s for s in NIFTY_50}
    spellings |= {s: s for s in NIFTY_50}
    spellings |= dict(ALIASES)
    spellings |= {name.upper(): s for s, name in NIFTY_50.items()}
    close = difflib.get_close_matches(
        q, spellings, n=MAX_SUGGESTIONS, cutoff=SUGGESTION_CUTOFF
    )
    suggestions = list(dict.fromkeys(_label(spellings[c]) for c in close))
    return ToolError(
        error="unknown_symbol",
        message=f"'{query.strip()}' isn't in the research universe; check the spelling.",
        suggestions=suggestions,
    )
