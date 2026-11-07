"""
Exceptions raised by the ingestion pipeline.

Every expected, per-ticker failure is a subclass of IngestionError, so a batch
run can catch IngestionError, record the failure and move on to the next ticker,
while genuine bugs (TypeError, KeyError, ...) still propagate and stop the run.
"""


class IngestionError(Exception):
    """Base class for expected per-ticker ingestion failures. Never raised directly."""

    def __init__(self, symbol: str, message: str) -> None:
        self.symbol = symbol
        super().__init__(f"{symbol}: {message}")


class UnknownTickerError(IngestionError):
    """Raised when a symbol isn't in our universe, before any network call is made."""

    def __init__(self, symbol: str) -> None:
        super().__init__(symbol, "not in the research universe")


class NoDataError(IngestionError):
    """Raised when a symbol in the universe gets nothing back from yfinance.

    Typical causes: the stock was delisted, the network failed, or Yahoo rate-limited us.
    """

    def __init__(self, symbol: str, reason: str = "yfinance returned no data") -> None:
        super().__init__(symbol, reason)


class DataQualityError(IngestionError):
    """Raised when too many of a ticker's rows fail validation, so the whole ticker is rejected."""

    def __init__(self, symbol: str, failed: int, total: int) -> None:
        self.failed = failed
        self.total = total
        super().__init__(symbol, f"{failed}/{total} rows failed validation")
