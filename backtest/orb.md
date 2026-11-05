# Opening-range breakout

No backtest runner is scaffolded yet. These rules are the spec for the first ORB run.

- Session clock is naive Asia/Kolkata wall time, matching `data/store/candles_15m` and `data/store/candles_5m`.
- Hard exit is the close of the **15:00** bar. Do not hold for the 15:15 bar. On a 5-minute frame that close is 15:05. On a 15-minute frame the 15:00 bar closes at 15:15.
- Skip any symbol-day whose `backtest_ok` flag is false in `data/store/coverage_manifest.parquet`. That flag is false for Muhurat 2025-10-21 and for any day missing a bar that starts between 09:15 and 11:00. A missing 15:15 or 15:20 bar does not by itself skip the day.
