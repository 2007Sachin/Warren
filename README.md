# Warren — Mirror Trading Bot

Layered algorithmic trading system for Indian markets (NSE/BSE) on Angel One SmartAPI.

## Architecture
- **data/** — market data pipelines (jugaad-data, bhavcopy, yfinance, SmartAPI historical) → Parquet/DuckDB
- **research/** — notebooks, vectorbt sweeps
- **backtest/** — nautilus_trader event-driven validation
- **execution/** — Angel One auth, instrument master, order placement (LIMIT only — market/IOC prohibited for algos)
- **risk/** — position limits, daily loss cap, kill switch
- **ops/** — Telegram alerts, token refresh, health checks
- **supabase/** — operational database schema (orders, positions, P&L, audit)
- **vps/** — deployment scripts + cron for the Mumbai VPS (live trading)

## Data
SmartAPI historical candles are stored as tz-naive Asia/Kolkata wall-clock Parquet:

- `data/store/candles/{exchange}/{symbol}.parquet` — daily, from 2024-01-01
- `data/store/candles_15m/` and `data/store/candles_5m/` — intraday, from 2025-08-01
- `data/store/coverage_manifest.parquet` — one row per symbol, trading day, and interval (`python data/coverage.py`)

Known SmartAPI vendor gaps, confirmed against a one-day refetch (not a pipeline bug):

- Closing bars **15:15 and 15:20** are often absent on 5-minute equity history (the 15:25 bar is still present). Fifteen-minute history often drops the **15:15** bar on those same days. `backtest_ok` stays true for these closing-window gaps.
- **2025-10-21** is the Diwali Muhurat session (a handful of bars, not a full 25/75). `backtest_ok` is false that day, and also false when any bar that starts from 09:15 through 11:00 is missing.

## Quickstart
1. `pip install -r requirements.txt`
2. Copy `.env.example` → `.env`, fill Angel One credentials (or set env vars in Cursor Cloud)
3. `python tests/smoke_login.py` — verifies auth + fetches your profile
4. `python execution/instruments.py` — downloads & indexes the instrument master

## Hard rules (SEBI/Angel One, in force since 1 Apr 2026)
- Orders only from the registered static IP (Mumbai VPS) — login/data work from anywhere
- LIMIT orders only for algo flow; no market/IOC
- Stay under 10 orders/second to avoid exchange algo registration
- Daily token expiry: re-login every morning (~7:30 AM IST)
