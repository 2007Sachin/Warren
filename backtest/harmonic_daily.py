"""HARMONIC-XABCD on daily bars. Same ratios as experiment #4; scale only.

Conservative ambiguities:
- ZigZag runs on daily closes (high=low=close), 5% primary / 7% sensitivity.
- Pivots usable only after the confirmation bar.
- Bearish patterns are skipped (CNC cannot short overnight).
- Same-bar stop vs target: stop wins.
- 10% equity, whole shares, max 10 names, no leverage.
- Brokerage is Rs 20 flat CNC from costs.py.
"""
from __future__ import annotations

from datetime import date
from math import floor

import pandas as pd

from backtest.costs import order_cost
from backtest.donchian import pooled_equities
from backtest.harmonic import _close_in_prz, _pattern_from_pivots, confirmed_zigzag
from backtest.metrics import summarize
from data.query import load

CAPITAL = 100_000.0
NOTIONAL_FRAC = 0.10
MAX_POS = 10
MAX_HOLD_BARS = 20
PRIMARY_ZZ = 0.05
SENS_ZZ = 0.07


def _daily(symbol: str) -> pd.DataFrame:
    df = load(symbol).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.normalize()
    df = df.drop_duplicates("timestamp", keep="last").sort_values("timestamp").reset_index(drop=True)
    df["date"] = df["timestamp"].dt.date
    return df


def _zz_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["high"] = out["close"]
    out["low"] = out["close"]
    return out


def _n_open(books: dict) -> int:
    return sum(1 for b in books.values() if b["pos"] is not None)


def simulate(threshold: float, start: date, end: date, capital: float = CAPITAL) -> dict:
    names = pooled_equities()
    frames = {}
    all_pivots_by_i = {}
    rows = []
    for sym in names:
        df = _daily(sym)
        frames[sym] = df
        pivots = confirmed_zigzag(_zz_frame(df), threshold)
        run = []
        by_i: dict[int, list] = {}
        for p in pivots:
            run.append(p)
            by_i.setdefault(p["confirmed_index"], []).append(list(run))
        all_pivots_by_i[sym] = by_i
        for i, rec in enumerate(df.itertuples(index=False)):
            rows.append((rec.timestamp, i, sym))
    rows.sort()
    books = {sym: {"pending": None, "pos": None} for sym in names}

    equity = capital
    trades: list[dict] = []
    daily: dict = {}

    def flatten(sym, i, price, reason, qty=None):
        nonlocal equity
        pos = books[sym]["pos"]
        if pos is None:
            return
        take = pos["qty"] if qty is None else min(qty, pos["qty"])
        if take <= 0:
            return
        df = frames[sym]
        entry = pos["entry"]
        gross = (price - entry) * take
        entry_cost_part = pos["entry_cost"] * (take / pos["qty_init"])
        exit_cost = order_cost("SELL", "CNC", take, price)
        cost = entry_cost_part + exit_cost["total"]
        net = gross - cost
        equity += net
        trades.append({
            "date": df.loc[i, "date"],
            "timestamp": df.loc[i, "timestamp"],
            "symbol": sym,
            "pattern": pos["pattern"],
            "side": "LONG",
            "qty": take,
            "entry": entry,
            "exit": price,
            "gross_pnl": gross,
            "cost": cost,
            "net_pnl": net,
            "reason": reason,
        })
        pos["qty"] -= take
        if pos["qty"] <= 1e-9:
            books[sym]["pos"] = None

    last_day = None
    for ts, i, sym in rows:
        df = frames[sym]
        rec = df.iloc[i]
        day = rec["date"]
        if last_day is not None and day != last_day:
            daily[pd.Timestamp(last_day)] = equity
        last_day = day
        in_window = start <= day <= end
        close = float(rec["close"])
        hi, lo = float(rec["high"]), float(rec["low"])
        op = float(rec["open"])

        if i in all_pivots_by_i[sym]:
            pat = _pattern_from_pivots(all_pivots_by_i[sym][i][-1])
            if pat is not None and pat["bullish"]:
                books[sym]["pending"] = pat
            elif pat is not None and not pat["bullish"]:
                books[sym]["pending"] = None

        pos = books[sym]["pos"]
        if pos is not None and in_window:
            stop = pos["stop"]
            if lo <= stop:
                flatten(sym, i, min(op, stop), "stop")
            else:
                pos = books[sym]["pos"]
                if pos is not None:
                    half = pos["qty_init"] / 2.0
                    if not pos["t1_done"] and hi >= pos["t1"]:
                        flatten(sym, i, pos["t1"], "target_382", qty=min(half, pos["qty"]))
                        if books[sym]["pos"] is not None:
                            books[sym]["pos"]["t1_done"] = True
                    pos = books[sym]["pos"]
                    if pos is not None and not pos["t2_done"] and hi >= pos["t2"]:
                        flatten(sym, i, pos["t2"], "target_618")
                    pos = books[sym]["pos"]
                    if pos is not None:
                        pos["bars"] += 1
                        if pos["bars"] >= MAX_HOLD_BARS:
                            flatten(sym, i, close, "time_stop")

        pos = books[sym]["pos"]
        pending = books[sym]["pending"]
        if (
            pos is None
            and pending is not None
            and pending["bullish"]
            and in_window
            and i > pending["d_confirmed"]
            and _n_open(books) < MAX_POS
            and _close_in_prz(close, pending["prz_lo"], pending["prz_hi"])
        ):
            qty = floor((equity * NOTIONAL_FRAC) / close)
            if qty >= 1:
                ec = order_cost("BUY", "CNC", qty, close)
                books[sym]["pos"] = {
                    "side": "LONG",
                    "qty": float(qty),
                    "qty_init": float(qty),
                    "entry": close,
                    "entry_cost": ec["total"],
                    "stop": pending["stop"],
                    "t1": pending["t1"],
                    "t2": pending["t2"],
                    "t1_done": False,
                    "t2_done": False,
                    "bars": 0,
                    "pattern": pending["name"],
                }
                books[sym]["pending"] = None

    if last_day is not None:
        daily[pd.Timestamp(last_day)] = equity
    for sym, book in books.items():
        if book["pos"] is not None:
            df = frames[sym]
            flatten(sym, len(df) - 1, float(df.iloc[-1]["close"]), "window_end")

    fills = pd.DataFrame(trades)
    if fills.empty:
        fills = pd.DataFrame(columns=["date", "timestamp", "symbol", "pattern", "side", "qty", "entry", "exit", "gross_pnl", "cost", "net_pnl", "reason"])
        tdf = fills.copy()
    else:
        tdf = (
            fills.groupby(["symbol", "pattern", "side", "entry"], as_index=False)
            .agg(
                date=("date", "first"),
                timestamp=("timestamp", "first"),
                qty=("qty", "sum"),
                exit=("exit", "last"),
                gross_pnl=("gross_pnl", "sum"),
                cost=("cost", "sum"),
                net_pnl=("net_pnl", "sum"),
                reason=("reason", lambda s: "+".join(str(x) for x in s)),
            )
        )
    eq = pd.Series(daily).sort_index()
    if eq.empty:
        eq = pd.Series({pd.Timestamp(start): capital})
    return {
        "equity": eq,
        "trades": tdf,
        "round_trips": tdf,
        "metrics": summarize(eq, tdf if len(tdf) else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])),
        "n_symbols": len(names),
        "fills": fills,
    }
