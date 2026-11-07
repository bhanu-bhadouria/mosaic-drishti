# Data known issues

Known quirks and gaps in the yfinance data, and how ingestion handles each one.
Agents and anyone reading the database should check here before trusting a number
that looks odd. Findings come from `notebooks/exploration/02_yfinance_exploration.ipynb`
(yfinance 1.3.0).

**Status:** *Handled* means the pipeline already copes with it. *Open* means it's
unexplained or unverified, so treat the affected values with care.

---

## Open

### HDFC Bank equity looks too high after the merger, so ROE looks too low

- **Evidence:** stored `stockholders_equity` rises 2.4× from FY2023 to FY2024, while
  net income rises 26%. ROE falls from 17.0% (FY2023) to about 9% (FY2024–FY2026).
  HDFC Bank's ROE has historically been in the mid-teens.
- **Two separate hypotheses, both unverified (test each against the annual report):**
  1. **The equity figure isn't what we think.** yfinance's "Stockholders Equity" for
     the merged group may include minority interests, or otherwise not match the
     bank's reported net worth.
  2. **Mid-year merger, year-end equity.** The July 2023 merger means FY2024 net
     income includes the merged business for only about 9 months, while year-end
     equity includes all of it. ROE on *average* equity (start + end ÷ 2) would be
     the fairer measure for that year. Note this can only explain FY2024: FY2025 and
     FY2026 are full post-merger years and are still about 9%, which points back to (1).
- **Impact:** HDFC's `roe` and `pb_ratio` (P/B = P/E × ROE) may be understated.
- **Next step:** compare stored equity and net income with the annual reports, and
  compute average-equity ROE for FY2024. Don't adjust the formulas to make it look right.

### TCS P/E drops from 26.9 (FY2025) to 17.3 (FY2026)

- **Evidence:** EPS barely changed (134.19 → 136.01), but the 31 March close fell
  from ₹3,606 to ₹2,359. The implied share count is unchanged (3.62 bn), so it isn't
  a share-basis problem.
- **Impact:** the ratio is calculated correctly from the stored price; the question
  is whether the price is right.
- **Next step:** confirm the price against a second source before an agent quotes it.

---

## Handled

### EPS restated on inconsistent share bases (HDFC Bank FY2023, FY2024)

- Basic and diluted EPS differ by about 2× in opposite directions in consecutive
  years (FY2023: 44.51 vs 88.68; FY2024: 88.66 vs 44.16), consistent with a 1:1
  bonus issue restated in some figures only.
- **Handling:** `validate_financials()` rule `eps_mismatch` nulls both EPS values for
  those periods; raw values are kept in its rejections. P/E and P/B are then NULL.

### Banks don't report EBIT or current liabilities

- `ebit` and `current_liabilities` are absent for HDFC Bank, in every period.
- **Handling:** `fetch_financials()` turns missing labels into NaN; the columns are
  nullable. D/E and ROCE are meaningless for lenders, so `compute_ratios()` skips
  them for `FINANCIAL_SECTORS`, and also when the sector is unknown.

### Quarterly statements are sparse and have gaps

- TCS's quarterly income statement skips 2025-09-30. HDFC's quarterly income
  statement has only 2 quarters; the balance sheet adds 2 more, so those rows have
  income fields NULL. Some periods are entirely empty (e.g. TCS balance sheet 2022-03-31).
- **Handling:** income and balance sheet are outer-joined on date; all-NaN periods
  are dropped. Ratios are calculated for annual periods only.

### "Total Debt" includes lease obligations

- TCS has essentially no borrowings, but its D/E is about 0.1: yfinance's
  "Total Debt" counts lease liabilities.
- **Handling:** none needed; read TCS-like D/E as lease exposure, not borrowing.

### Adjusted prices change after every dividend

- `adjusted_close` is back-adjusted by Yahoo, so past values change whenever a
  dividend is paid (e.g. TCS before the 2026-10-14 ex-date: about 0.5% lower).
- `close` is **not** dividend-adjusted but **is** split/bonus-adjusted.
- **Handling:** `store_prices()` upserts with `DO UPDATE`, so re-fetching refreshes
  history. P/E uses `close`, never `adjusted_close`.

### An intraday run stores an incomplete day

- During market hours (9:15–15:30 IST), yfinance returns today with close = the
  current price. It passes validation because it's internally consistent.
- **Handling:** the `DO UPDATE` upsert overwrites it with final values on the next run.

### P/E is NULL when the share count changed

- P/E is only calculated if a period's implied share count (net income ÷ EPS) is
  within 10% of the most recent period's. This catches stale-basis EPS, but a real
  share issue (such as a merger) also fails it.
- **Handling:** deliberate. An unknown P/E is better than one that's off by 2×.
  The precise fix would be storing split and bonus history from `t.splits`.

### P/B is NULL in loss-making years

- P/B is derived as P/E × ROE (no share count needed), so it's NULL whenever P/E
  is, including when EPS ≤ 0. A loss-making company with positive book value does
  have a real P/B; this method can't produce it.
- **Handling:** accepted limitation, documented in `ratios.py`.

### Unknown or delisted tickers don't raise

- yfinance logs "possibly delisted; no price data found" and returns an empty
  DataFrame.
- **Handling:** `fetch_prices()` raises `NoDataError` on an empty result; symbols
  outside the universe raise `UnknownTickerError` before any network call.

### `t.info` is slow and sometimes fails

- **Handling:** `fetch_stock_info()` degrades: sector and industry become `None`,
  and `upsert_stock()` keeps the stored values via `COALESCE`. The stock name always
  comes from our universe list, so it never changes with Yahoo's availability.

### Sequence ids skip ahead

- Postgres takes a sequence value for every row an upsert tries to insert, even
  when it ends as an update (e.g. HDFC Bank's stock id is 10, not 2).
- **Handling:** harmless at this scale. Never assume ids are consecutive.
