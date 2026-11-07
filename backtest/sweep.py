"""LIQUIDITY-SWEEP-FADE on 15-minute bars. Pre-registered; no post-TEST edits.

Conservative ambiguities:
- High >= level (or low <= level) is a touch even when the bar is not a fade.
- ZigZag pivots are usable only after the confirmation bar.
- Same-bar stop vs target: stop wins.
- No entry on the 15:00 bar. Gap through stop or target at the next open: skip.
- Nifty 50 is modelled as MIS like cash names.
- Coverage-false days are dropped before ZigZag / PDH construction.
"""
from __future__ import annotations

from datetime import date, time
from math import floor

import pandas as pd

from backtest.costs import order_cost
from backtest.harmonic import confirmed_zigzag
from backtest.loaders import coverage_ok, equity_universe, load_15m
from backtest.metrics import summarize

CAPITAL = 100_000.0
ZIGZAG = 0.02
SWEEP_PAD = 0.0005
STOP_PAD = 0.001
RR = 1.5
TOUCH_GAP = 10
TIME_BARS = 8
RISK_FRAC = 0.0075
MAX_PER_DAY = 3
HARD_EXIT = time(15, 0)


def sweep_universe() -> list[str]:
    names = equity_universe()
    if "Nifty 50" not in names:
        names = ["Nifty 50"] + names
    return names


def _filter(symbol: str, allowed: set) -> pd.DataFrame:
    df = load_15m(symbol)
    keep = [(symbol, d) in allowed for d in df["date"]]
    return df.loc[keep].reset_index(drop=True)


def _session_hl(df: pd.DataFrame) -> dict:
    out = {}
    for day, g in df.groupby("date", sort=True):
        out[day] = (float(g["high"].max()), float(g["low"].min()))
    return out


def simulate(start: date, end: date, capital: float = CAPITAL, compound: bool = True) -> dict:
    ok = coverage_ok("15m")
    allowed = {(row.symbol, row.date) for row in ok.itertuples(index=False) if bool(row.backtest_ok)}
    frames = {}
    for sym in sweep_universe():
        try:
            df = _filter(sym, allowed)
        except Exception:
            continue
        if df.empty:
            continue
        frames[sym] = df

    state = {}
    events = []
    for sym, df in frames.items():
        pivots = confirmed_zigzag(df, ZIGZAG)
        by_conf: dict[int, list] = {}
        for p in pivots:
            by_conf.setdefault(p["confirmed_index"], []).append(p)
        days = sorted(df["date"].unique())
        prev_day = {days[i]: days[i - 1] for i in range(1, len(days))}
        state[sym] = {
            "df": df,
            "by_conf": by_conf,
            "prev_day": prev_day,
            "hl": _session_hl(df),
            "levels": [],
            "pending": None,
            "pos": None,
            "day_trades": 0,
            "day": None,
        }
        for i, rec in enumerate(df.itertuples(index=False)):
            events.append((rec.timestamp, i, sym))
    events.sort()

    equity = capital
    trades: list[dict] = []
    daily: dict = {}

    def flatten(sym, i, price, reason):
        nonlocal equity
        pos = state[sym]["pos"]
        if pos is None:
            return
        df = state[sym]["df"]
        take = pos["qty"]
        side = pos["side"]
        exit_side = "SELL" if side == "LONG" else "BUY"
        entry = pos["entry"]
        gross = (price - entry) * take if side == "LONG" else (entry - price) * take
        cost = pos["entry_cost"] + order_cost(exit_side, "MIS", take, price)["total"]
        net = gross - cost
        equity += net
        trades.append({
            "date": df.loc[i, "date"],
            "timestamp": df.loc[i, "timestamp"],
            "symbol": sym,
            "level_type": pos["level_type"],
            "side": side,
            "qty": take,
            "entry": entry,
            "exit": price,
            "gross_pnl": gross,
            "cost": cost,
            "net_pnl": net,
            "reason": reason,
        })
        state[sym]["pos"] = None

    last_day = None
    for ts, i, sym in events:
        st = state[sym]
        df = st["df"]
        rec = df.iloc[i]
        day = rec["date"]
        if last_day is not None and day != last_day:
            daily[pd.Timestamp(last_day)] = equity
        last_day = day
        in_window = start <= day <= end
        clock = rec["clock"]
        hi, lo, op, cl = map(float, (rec["high"], rec["low"], rec["open"], rec["close"]))

        if st["day"] != day:
            st["day"] = day
            st["day_trades"] = 0
            prev = st["prev_day"].get(day)
            if prev is not None:
                pdh, pdl = st["hl"][prev]
                st["levels"].append({"kind": "H", "price": pdh, "type": "PDH", "last_touch": None, "from_i": i})
                st["levels"].append({"kind": "L", "price": pdl, "type": "PDL", "last_touch": None, "from_i": i})

        pos = st["pos"]
        if pos is not None and in_window:
            side = pos["side"]
            stop, tgt = pos["stop"], pos["target"]
            hit_stop = (side == "LONG" and lo <= stop) or (side == "SHORT" and hi >= stop)
            hit_tgt = (side == "LONG" and hi >= tgt) or (side == "SHORT" and lo <= tgt)
            if hit_stop:
                fill = min(op, stop) if side == "LONG" else max(op, stop)
                flatten(sym, i, fill, "stop")
            elif hit_tgt:
                flatten(sym, i, tgt, "target")
            elif clock == HARD_EXIT:
                flatten(sym, i, cl, "hard_exit")
            else:
                pos["bars"] += 1
                if pos["bars"] >= TIME_BARS:
                    flatten(sym, i, cl, "time_stop")

        if st["pos"] is not None:
            st["pending"] = None

        pending = st["pending"]
        if st["pos"] is None and pending is not None and in_window:
            st["pending"] = None
            if clock != HARD_EXIT and st["day_trades"] < MAX_PER_DAY:
                side = pending["side"]
                stop = pending["stop"]
                dist = abs(op - stop)
                gap_stop = dist <= 0 or (side == "LONG" and op <= stop) or (side == "SHORT" and op >= stop)
                tgt = op + RR * (op - stop) if side == "LONG" else op - RR * (stop - op)
                gap_tgt = (side == "LONG" and op >= tgt) or (side == "SHORT" and op <= tgt)
                if not gap_stop and not gap_tgt:
                    base = equity if compound else capital
                    qty = floor((base * RISK_FRAC) / dist)
                    if qty >= 1:
                        entry_side = "BUY" if side == "LONG" else "SELL"
                        ec = order_cost(entry_side, "MIS", qty, op)
                        st["pos"] = {
                            "side": side,
                            "qty": float(qty),
                            "entry": op,
                            "entry_cost": ec["total"],
                            "stop": stop,
                            "target": tgt,
                            "bars": 0,
                            "level_type": pending["level_type"],
                        }
                        st["day_trades"] += 1

        if st["pos"] is None:
            chosen = None
            for lvl in st["levels"]:
                if i < lvl["from_i"] or lvl["price"] <= 0:
                    continue
                last = lvl["last_touch"]
                first = last is None or (i - last) >= TOUCH_GAP
                px = lvl["price"]
                if lvl["kind"] == "H":
                    touched = hi >= px
                    swept = first and hi >= px * (1 + SWEEP_PAD) and cl < px
                    side = "SHORT"
                    extreme = hi
                else:
                    touched = lo <= px
                    swept = first and lo <= px * (1 - SWEEP_PAD) and cl > px
                    side = "LONG"
                    extreme = lo
                if touched:
                    lvl["last_touch"] = i
                if swept and chosen is None:
                    stop = extreme * (1 + STOP_PAD) if side == "SHORT" else extreme * (1 - STOP_PAD)
                    chosen = {"side": side, "stop": stop, "level_type": lvl["type"]}
            st["pending"] = chosen

        if i in st["by_conf"]:
            for p in st["by_conf"][i]:
                st["levels"].append({
                    "kind": p["kind"],
                    "price": p["price"],
                    "type": "swing",
                    "last_touch": None,
                    "from_i": i + 1,
                })

    if last_day is not None:
        daily[pd.Timestamp(last_day)] = equity
    for sym, st in state.items():
        if st["pos"] is not None:
            df = st["df"]
            flatten(sym, len(df) - 1, float(df.iloc[-1]["close"]), "window_end")

    tdf = pd.DataFrame(trades)
    if tdf.empty:
        tdf = pd.DataFrame(columns=["date", "timestamp", "symbol", "level_type", "side", "qty", "entry", "exit", "gross_pnl", "cost", "net_pnl", "reason"])
    eq = pd.Series(daily).sort_index()
    if eq.empty:
        eq = pd.Series({pd.Timestamp(start): capital})
    return {
        "equity": eq,
        "trades": tdf,
        "round_trips": tdf,
        "metrics": summarize(eq, tdf if len(tdf) else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])),
        "n_symbols": len(frames),
    }
