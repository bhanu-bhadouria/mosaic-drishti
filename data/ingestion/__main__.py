"""
Run ingestion from the command line:

    python -m data.ingestion                  # the whole universe
    python -m data.ingestion TCS.NS INFY.NS   # just these symbols

Exits 1 if any ticker failed and 0 otherwise, including when some are partial
(those still log a warning), so a scheduler can tell when a run needs attention.
Kept out of __init__.py so importing the package never triggers a run.
"""

import argparse
import sys

from config.logging_config import setup_logging
from data.ingestion.pipeline import ingest_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m data.ingestion",
        description="Ingest prices and financials from yfinance into Postgres.",
    )
    parser.add_argument(
        "symbols", nargs="*", help="symbols to ingest (default: the whole universe)"
    )
    args = parser.parse_args(argv)

    setup_logging()
    results = ingest_all(args.symbols or None)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
