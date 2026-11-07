"""_with_retry and ingest_all's error policy, with sleep and the network mocked."""

from unittest import mock

import pytest
from yfinance.exceptions import YFRateLimitError

from data.ingestion import pipeline
from data.ingestion.exceptions import NoDataError, UnknownTickerError
from data.ingestion.pipeline import TickerResult


@pytest.fixture
def sleeps():
    """Patch time.sleep in the pipeline; returns the list of requested delays."""
    delays = []
    with mock.patch.object(pipeline.time, "sleep", side_effect=delays.append):
        yield delays


def test_retry_recovers_after_two_rate_limits(sleeps):
    fn = mock.Mock(
        side_effect=[YFRateLimitError(), YFRateLimitError(), "data"], __name__="fn"
    )
    assert pipeline._with_retry(fn, "TCS.NS") == "data"
    assert sleeps == [2.0, 4.0]
    fn.assert_called_with("TCS.NS")


def test_retry_gives_up_after_three_retries(sleeps):
    fn = mock.Mock(side_effect=YFRateLimitError(), __name__="fn")
    with pytest.raises(YFRateLimitError):
        pipeline._with_retry(fn, "TCS.NS")
    assert sleeps == [2.0, 4.0, 8.0]
    assert fn.call_count == 4  # first try + 3 retries


def test_retry_never_retries_other_errors(sleeps):
    fn = mock.Mock(side_effect=TypeError("a bug"), __name__="fn")
    with pytest.raises(TypeError):
        pipeline._with_retry(fn, "TCS.NS")
    assert sleeps == []
    assert fn.call_count == 1


def test_ingest_all_records_ingestion_errors_and_moves_on(sleeps):
    outcomes = {
        "TCS.NS": TickerResult("TCS.NS", "ok", prices_written=10),
        "INFY.NS": TickerResult(
            "INFY.NS", "partial", financials_error="NoDataError: x"
        ),
        "FAKE.NS": UnknownTickerError("FAKE.NS"),
        "WIPRO.NS": NoDataError("WIPRO.NS"),
    }

    def fake_ingest(symbol):
        outcome = outcomes[symbol]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with mock.patch.object(pipeline, "ingest_ticker", side_effect=fake_ingest):
        results = pipeline.ingest_all(list(outcomes))

    assert [r.status for r in results] == ["ok", "partial", "failed", "failed"]
    assert (
        results[2].error == "UnknownTickerError: FAKE.NS: not in the research universe"
    )
    assert sleeps == [1.0, 1.0, 1.0]  # a pause between tickers, not before the first


@pytest.mark.parametrize(
    "systemic",
    [TypeError("a bug"), RuntimeError("columns changed"), YFRateLimitError()],
)
def test_ingest_all_stops_on_anything_else(sleeps, systemic):
    with mock.patch.object(pipeline, "ingest_ticker", side_effect=systemic) as ingest:
        with pytest.raises(type(systemic)):
            pipeline.ingest_all(["TCS.NS", "INFY.NS"])
    assert ingest.call_count == 1  # the second ticker never runs


def test_ingest_all_defaults_to_the_whole_universe(sleeps):
    with mock.patch.object(
        pipeline, "ingest_ticker", side_effect=lambda s: TickerResult(s, "ok")
    ):
        results = pipeline.ingest_all()
    assert len(results) == 20
