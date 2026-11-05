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
