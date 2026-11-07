"""NIFTY-MEANREVERT-DAILY (Connors RSI-2 class). Pre-registered; no post-TEST edits.

Conservative ambiguities:
- Regime uses Nifty 50 close vs its 200-day SMA (the validated index rule),
  not the ETF's own SMA.
- SMA and RSI require a full lookback; undefined values are not a signal.
- Wilder RSI seeds with the SMA of the first `period` changes.
- 10-day time stop counts the entry session as day 1 and exits that close.
- Close>5-SMA / RSI>70 / time-stop on the same bar beat a regime-off exit
  (exit at close, not next open).
- Whole shares, 95% of marked equity, no leverage.
"""
from __future__ import annotations

from datetime import date
from math import floor

import numpy as np
import pandas as pd

from backtest.costs import order_cost
from backtest.loaders import NIFTY, daily_close
from backtest.metrics import summarize
from data.query import load

SYMBOL = "NIFTYBEES-EQ"
CAPITAL = 100_000.0
SMA_REGIME = 200
SMA_EXIT = 5
RSI_N = 2
RSI_BUY = 10.0
RSI_SELL = 70.0
MAX_HOLD = 10
ALLOC = 0.95


def wilder_rsi(close: pd.Series, period: int = RSI_N) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = pd.Series(np.nan, index=close.index)
    avg_loss = pd.Series(np.nan, index=close.index)
    if len(close) <= period:
        return avg_gain
    avg_gain.iloc[period] = float(gain.iloc[1 : period + 1].mean())
    avg_loss.iloc[period] = float(loss.iloc[1 : period + 1].mean())
    for i in range(period + 1, len(close)):
        avg_gain.iloc[i] = (float(avg_gain.iloc[i - 1]) * (period - 1) + float(gain.iloc[i])) / period
        avg_loss.iloc[i] = (float(avg_loss.iloc[i - 1]) * (period - 1) + float(loss.iloc[i])) / period
    rsi = pd.Series(np.nan, index=close.index)
    for i in range(period, len(close)):
        g, l = float(avg_gain.iloc[i]), float(avg_loss.iloc[i])
        if l == 0 and g == 0:
            rsi.iloc[i] = 50.0
        elif l == 0:
            rsi.iloc[i] = 100.0
        else:
            rsi.iloc[i] = 100.0 - 100.0 / (1.0 + g / l)
    return rsi


def _bars() -> pd.DataFrame:
    etf = load(SYMBOL).copy()
    etf["timestamp"] = pd.to_datetime(etf["timestamp"]).dt.normalize()
    etf = etf.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    nifty = daily_close(NIFTY)
    df = etf.set_index("timestamp")[["open", "high", "low", "close"]].rename(
        columns={"open": "open", "close": "close"}
    )
    df["nifty"] = nifty.reindex(df.index)
    df = df.dropna(subset=["open", "close", "nifty"])
    df["sma200"] = df["nifty"].rolling(SMA_REGIME, min_periods=SMA_REGIME).mean()
    df["sma5"] = df["close"].rolling(SMA_EXIT, min_periods=SMA_EXIT).mean()
    df["rsi2"] = wilder_rsi(df["close"], RSI_N)
    df["regime"] = df["sma200"].notna() & (df["nifty"] > df["sma200"])
    return df


def simulate(start: date, end: date, capital: float = CAPITAL) -> dict:
    px = _bars()
    idx = list(px.index)
    in_window = [d for d in idx if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    cash = capital
    qty = 0.0
    entry_px = 0.0
    entry_cost = 0.0
    entry_i = None
    pending = False
    pending_regime_exit = False
    trades = []
    equity_pts = []
    invested_days = 0

    def mark(day) -> float:
        return cash + qty * float(px.loc[day, "close"])

    def buy_open(day):
        nonlocal cash, qty, entry_px, entry_cost, entry_i
        price = float(px.loc[day, "open"])
        take = floor((cash * ALLOC) / price)
        cost = None
        while take >= 1:
            cost = order_cost("BUY", "CNC", take, price)
            if take * price + cost["total"] <= cash:
                break
            take -= 1
        if take < 1 or cost is None:
            return
        need = take * price + cost["total"]
        cash -= need
        qty = float(take)
        entry_px = price
        entry_cost = cost["total"]
        entry_i = idx.index(day)
        trades.append({
            "date": day.date() if hasattr(day, "date") else day,
            "symbol": SYMBOL,
            "side": "BUY",
            "qty": qty,
            "price": price,
            "gross_pnl": 0.0,
            "cost": cost["total"],
            "net_pnl": -cost["total"],
            "reason": "rsi2_entry",
        })

    def sell(day, price: float, reason: str):
        nonlocal cash, qty, entry_px, entry_cost, entry_i
        if qty <= 0:
            return
        cost = order_cost("SELL", "CNC", qty, price)
        cash += qty * price - cost["total"]
        gross = (price - entry_px) * qty
        hold = (idx.index(day) - entry_i + 1) if entry_i is not None else 0
        trades.append({
            "date": day.date() if hasattr(day, "date") else day,
            "symbol": SYMBOL,
            "side": "SELL",
            "qty": qty,
            "price": price,
            "gross_pnl": gross,
            "cost": cost["total"] + entry_cost,
            "net_pnl": gross - cost["total"] - entry_cost,
            "reason": reason,
            "hold_days": hold,
            "entry": entry_px,
        })
        qty = 0.0
        entry_px = 0.0
        entry_cost = 0.0
        entry_i = None

    loc = {d: i for i, d in enumerate(idx)}
    for day in in_window:
        i = loc[day]
        rec = px.loc[day]
        if pending_regime_exit and qty > 0:
            sell(day, float(rec["open"]), "regime_off")
            pending_regime_exit = False
        if pending and qty <= 0:
            buy_open(day)
        pending = False

        if qty > 0:
            invested_days += 1
            hold = i - entry_i + 1
            sma5 = rec["sma5"]
            rsi = rec["rsi2"]
            close_exit = False
            reason = ""
            if pd.notna(sma5) and float(rec["close"]) > float(sma5):
                close_exit, reason = True, "sma5"
            elif pd.notna(rsi) and float(rsi) > RSI_SELL:
                close_exit, reason = True, "rsi70"
            elif hold >= MAX_HOLD:
                close_exit, reason = True, "time_stop"
            if close_exit:
                sell(day, float(rec["close"]), reason)
                pending_regime_exit = False
            elif not bool(rec["regime"]):
                pending_regime_exit = True
        else:
            pending_regime_exit = False
            rsi = rec["rsi2"]
            if bool(rec["regime"]) and pd.notna(rsi) and float(rsi) < RSI_BUY:
                pending = True

        equity_pts.append((day, mark(day)))

    if qty > 0 and in_window:
        last = in_window[-1]
        sell(last, float(px.loc[last, "close"]), "window_end")
        equity_pts[-1] = (last, mark(last))

    equity = pd.Series({d: v for d, v in equity_pts}, dtype=float).sort_index()
    tdf = pd.DataFrame(trades)
    sells = tdf[tdf["side"] == "SELL"].copy() if not tdf.empty else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl", "hold_days"])
    n_days = max(len(in_window), 1)
    avg_hold = float(sells["hold_days"].mean()) if len(sells) and "hold_days" in sells else 0.0
    return {
        "equity": equity,
        "trades": tdf,
        "round_trips": sells,
        "metrics": summarize(equity, sells if len(sells) else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])),
        "time_in_market": invested_days / n_days,
        "avg_hold_days": avg_hold,
        "n_days": n_days,
        "invested_days": invested_days,
    }
