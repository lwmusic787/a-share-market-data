# A-share market data

Automatic public-market-data collection via GitHub Actions. Scheduled at **16:40 Beijing time on weekdays** (08:40 UTC). GitHub scheduled runs can be delayed or skipped.

Data: daily OHLCV for four indices and five watchlist stocks (backfilled from 2024 for stocks), plus a full-market daily quote snapshot. Files are under `data/`, with `data/status.json` recording successes, errors, and Beijing run time.

**Important:** This is not a paid real-time feed, does not yet store 250+ historical bars for every listed stock, and does not guarantee data completeness. Public endpoints may fail or change. Inspect Actions logs and status.json; never assume a scheduled run succeeded. Market snapshot values are not necessarily official exchange closing data. The index API may expose different column conventions; verify dates and units before analysis.

To start: GitHub → Actions → A-share market data update → Run workflow. Ensure Actions is enabled and workflow write permission is allowed. Initial execution has not been verified.
