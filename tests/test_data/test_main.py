"""The command-line entry point: exit codes a scheduler can rely on."""

import importlib
from unittest import mock

import pytest

from data.ingestion.pipeline import TickerResult

cli = importlib.import_module("data.ingestion.__main__")


@pytest.fixture
def run():
    """Call main() with ingest_all and logging setup mocked; returns (exit code, ingest mock)."""

    def _run(statuses, argv=()):
        results = [TickerResult(f"S{i}.NS", s) for i, s in enumerate(statuses)]
        with (
            mock.patch.object(cli, "setup_logging"),
            mock.patch.object(cli, "ingest_all", return_value=results) as ingest,
        ):
            return cli.main(list(argv)), ingest

    return _run


@pytest.mark.parametrize(
    "statuses, code",
    [
        (["ok", "ok"], 0),
        (["ok", "partial"], 0),  # partial still writes prices: warn, don't page anyone
        (["ok", "failed"], 1),
        (["partial", "failed"], 1),
    ],
)
def test_exit_code_is_1_only_when_a_ticker_failed(run, statuses, code):
    assert run(statuses)[0] == code


def test_no_symbols_means_the_whole_universe(run):
    _, ingest = run(["ok"])
    ingest.assert_called_once_with(None)


def test_symbols_are_passed_through(run):
    _, ingest = run(["ok", "ok"], argv=["TCS.NS", "INFY.NS"])
    ingest.assert_called_once_with(["TCS.NS", "INFY.NS"])
