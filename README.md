# Mosaic Drishti

AI-assisted equity research for NSE-listed stocks.

## Data ingestion

Ingestion pulls data for the research universe (20 Nifty 50 stocks, defined in
`data/universe.py`) from Yahoo Finance via yfinance, validates it, and stores it
in Postgres:

- **Stock master data:** name, sector, industry and exchange (`stocks`)
- **Daily prices:** 5 years of open, high, low, close, adjusted close and volume (`price_history`)
- **Financials:** annual and quarterly revenue, net income, EPS, EBIT, debt, equity,
  assets and current liabilities, plus derived ratios (ROE, D/E, ROCE, P/E, P/B) for
  annual periods (`financial_data`)

Every run is idempotent: re-running updates existing rows instead of duplicating them.

### Running it

Start Postgres and apply the migrations once:

```bash
docker compose up -d
poetry run alembic upgrade head
```

Then:

```bash
make ingest                              # the whole universe
make ingest SYMBOLS="TCS.NS INFY.NS"     # just these symbols
```

`make ingest` runs `python -m data.ingestion`. It finishes with a summary such as
`20 tickers: 19 ok, 1 partial, 0 failed`, and exits non-zero if any ticker failed,
so a scheduler can tell when a run needs attention.

### What the statuses mean

| Status | Meaning |
|---|---|
| `ok` | Stock, prices and financials all written. |
| `partial` | Stock and prices written; financials failed and were skipped (the reason is logged). Ratios are still recalculated from previously stored financials. Exit code stays 0. |
| `failed` | Nothing written for that ticker, e.g. an unknown symbol, no price data, or too many invalid price rows. Exit code 1. |

Each ticker is written in a single transaction, so a ticker is never half-written.
Systemic problems (a code bug, yfinance changing its output, or a rate limit that
outlasts the retries) stop the whole run instead of failing every ticker one by one.

### Known data issues

Yahoo's data has quirks (inconsistent EPS restatements, banks with no EBIT,
dividend-adjusted prices that change over time, and more). They're documented,
with how ingestion handles each one, in
[docs/data_known_issues.md](docs/data_known_issues.md).

### Tests

```bash
make test               # unit tests: fast, no network, no database
make test-integration   # integration tests against a separate mosaic_drishti_test database
```
