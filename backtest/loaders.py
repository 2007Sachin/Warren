"""Candle loaders for backtests. Daily via DuckDB; 15m from the Parquet store."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from data.coverage import MANIFEST
from data.query import load

ROOT = Path(__file__).resolve().parents[1]
STORE_15M = ROOT / "data" / "store" / "candles_15m"

EQUITIES = ["RELIANCE-EQ", "HDFCBANK-EQ", "INFY-EQ", "TCS-EQ", "SBIN-EQ"]
ORB_SYMBOLS = ["RELIANCE-EQ", "HDFCBANK-EQ", "SBIN-EQ"]
NIFTY = "Nifty 50"


def daily_close(symbol: str, exchange: str = "NSE") -> pd.Series:
    df = load(symbol, exchange)
    ts = pd.to_datetime(df["timestamp"])
    s = pd.Series(df["close"].to_numpy(), index=ts, name=symbol)
    s.index = s.index.normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def close_frame(symbols: list[str]) -> pd.DataFrame:
    return pd.concat([daily_close(s) for s in symbols], axis=1).sort_index()


def load_15m(symbol: str, exchange: str = "NSE") -> pd.DataFrame:
    path = STORE_15M / exchange / f"{symbol}.parquet"
    df = duckdb.execute(
        "SELECT * FROM read_parquet(?) ORDER BY timestamp",
        [str(path)],
    ).df()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date
    df["clock"] = df["timestamp"].dt.time
    return df


def coverage_ok(interval: str = "15m") -> pd.DataFrame:
    m = pd.read_parquet(MANIFEST)
    m = m[m["interval"] == interval].copy()
    m["date"] = pd.to_datetime(m["date"]).dt.date
    return m
