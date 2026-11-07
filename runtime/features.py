"""Feature builders for the advisor. No live orders."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.donchian import _ohlc, pooled_equities
from backtest.loaders import NIFTY, daily_close


def atr_series(px: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = px["high"], px["low"], px["close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def nifty_state(day) -> dict:
    s = daily_close(NIFTY).dropna()
    if day not in s.index:
        loc = s.index.searchsorted(pd.Timestamp(day), side="right") - 1
        if loc < 0:
            return {"ret_20d": None, "atr_pct": None, "breadth": None}
        day = s.index[loc]
    ret = None
    loc = s.index.get_loc(day)
    if loc >= 20:
        ret = float(s.iloc[loc] / s.iloc[loc - 20] - 1.0)
    names = pooled_equities()
    bars = _ohlc(names)
    up = 0
    tot = 0
    for sym, px in bars.items():
        if day not in px.index:
            continue
        i = px.index.get_loc(day)
        if i < 1:
            continue
        tot += 1
        if float(px["close"].iloc[i]) > float(px["close"].iloc[i - 1]):
            up += 1
    breadth = (up / tot) if tot else None
    return {"ret_20d": ret, "atr_pct": None, "breadth": breadth, "india_vix": None}


def signal_features(px: pd.DataFrame, day, atr: float | None) -> dict:
    if day not in px.index:
        return {}
    i = px.index.get_loc(day)
    close = float(px.loc[day, "close"])
    vol = float(px["volume"].iloc[i]) if "volume" in px.columns else None
    vol_ma = float(px["volume"].iloc[max(0, i - 20) : i].mean()) if vol is not None and i > 0 else None
    look = px["high"].iloc[max(0, i - 252) : i + 1]
    dist_52w = float(close / look.max() - 1.0) if len(look) else None
    strength = None
    if atr and atr > 0:
        strength = (close - float(px["low"].iloc[i])) / atr
    return {
        "breakout_atr": strength,
        "volume_ratio": (vol / vol_ma) if vol and vol_ma else None,
        "dist_52w": dist_52w,
    }
