"""15-minute opening-range breakout, MIS, after coverage_ok filter.

Opening range is the 09:15 bar (first 15 minutes). First unambiguous break
of that high or low after 09:30 is the entry. Stop is the opposite side of
the range. Hard exit is the close of the 15:00 bar. One trade per symbol
per day, at most two positions at once. Risk 1% of equity per trade.
"""
from __future__ import annotations

from datetime import date, time
from math import floor

import pandas as pd

from backtest.costs import order_cost
from backtest.loaders import ORB_SYMBOLS, coverage_ok, load_15m
from backtest.metrics import summarize

CAPITAL = 100_000.0
RISK_FRAC = 0.01
MAX_CONCURRENT = 2
OR_CLOCK = time(9, 15)
ENTRY_FROM = time(9, 30)
HARD_EXIT = time(15, 0)


def _fill_break(side: str, bar, orh: float, orl: float) -> float | None:
    """Fill at the range edge, or at open if the bar gaps through. None if both sides break."""
    hi, lo, op = float(bar.high), float(bar.low), float(bar.open)
    up = hi > orh
    down = lo < orl
    if up and down:
        return None
    if side == "LONG" and up:
        return op if op > orh else orh
    if side == "SHORT" and down:
        return op if op < orl else orl
    return None


def simulate(start: date, end: date, capital: float = CAPITAL) -> dict:
    ok = coverage_ok("15m")
    ok = ok[ok["symbol"].isin(ORB_SYMBOLS)]
    allowed = {(row.symbol, row.date) for row in ok.itertuples(index=False) if bool(row.backtest_ok)}

    frames = {sym: load_15m(sym) for sym in ORB_SYMBOLS}
    for sym, df in frames.items():
        frames[sym] = df[(df["date"] >= start) & (df["date"] <= end)].copy()

    bars = []
    for sym, df in frames.items():
        for rec in df.itertuples(index=False):
            bars.append(rec)
    bars.sort(key=lambda r: (r.timestamp, r.symbol if hasattr(r, "symbol") else ""))

    # load_15m does not include symbol column — add it.
    tagged = []
    for sym, df in frames.items():
        part = df.copy()
        part["symbol"] = sym
        tagged.append(part)
    if not tagged:
        empty = pd.Series(dtype=float)
        return {"equity": empty, "trades": pd.DataFrame(), "metrics": summarize(empty, pd.DataFrame())}
    all_bars = pd.concat(tagged, ignore_index=True).sort_values(["timestamp", "symbol"])

    equity = capital
    open_pos: dict[str, dict] = {}
    traded_today: set[str] = set()
    ranges: dict[tuple, tuple[float, float]] = {}
    day_seen: date | None = None
    trades = []
    equity_pts = {}

    def close_pos(sym: str, price: float, when, reason: str) -> None:
        nonlocal equity
        pos = open_pos.pop(sym, None)
        if pos is None:
            return
        side = pos["side"]
        qty = pos["qty"]
        entry = pos["entry"]
        sell_side = "SELL" if side == "LONG" else "BUY"
        # Cover with the opposite order. Shorts buy to cover.
        if side == "LONG":
            exit_side = "SELL"
            gross = (price - entry) * qty
        else:
            exit_side = "BUY"
            gross = (entry - price) * qty
        entry_cost = pos["entry_cost"]
        exit_cost = order_cost(exit_side, "MIS", qty, price)
        cost = entry_cost["total"] + exit_cost["total"]
        net = gross - cost
        equity += net
        trades.append({
            "date": when.date() if hasattr(when, "date") else when,
            "symbol": sym,
            "side": side,
            "qty": qty,
            "entry": entry,
            "exit": price,
            "gross_pnl": gross,
            "cost": cost,
            "net_pnl": net,
            "reason": reason,
        })

    for rec in all_bars.itertuples(index=False):
        sym = rec.symbol
        day = rec.date
        clock = rec.clock
        ts = rec.timestamp

        if day_seen is not None and day != day_seen:
            # New session: leftover positions should already be flat; reset day flags.
            traded_today.clear()
            # mark previous session
        if day != day_seen:
            traded_today.clear()
            day_seen = day

        if (sym, day) not in allowed:
            continue

        if clock == OR_CLOCK:
            ranges[(sym, day)] = (float(rec.high), float(rec.low))
            continue

        rng = ranges.get((sym, day))
        if rng is None:
            continue
        orh, orl = rng
        width = orh - orl

        # Stops on open positions first.
        if sym in open_pos:
            pos = open_pos[sym]
            if pos["side"] == "LONG" and float(rec.low) <= pos["stop"]:
                fill = min(float(rec.open), pos["stop"])
                close_pos(sym, fill, ts, "stop")
            elif pos["side"] == "SHORT" and float(rec.high) >= pos["stop"]:
                fill = max(float(rec.open), pos["stop"])
                close_pos(sym, fill, ts, "stop")

        if clock == HARD_EXIT:
            if sym in open_pos:
                close_pos(sym, float(rec.close), ts, "hard_exit")
            continue

        if clock < ENTRY_FROM:
            continue
        if sym in open_pos or sym in traded_today:
            continue
        if len(open_pos) >= MAX_CONCURRENT:
            continue
        if width <= 0:
            continue

        up = float(rec.high) > orh
        down = float(rec.low) < orl
        if up and down:
            traded_today.add(sym)
            continue
        side = "LONG" if up else ("SHORT" if down else None)
        if side is None:
            continue
        fill = _fill_break(side, rec, orh, orl)
        if fill is None:
            continue
        stop = orl if side == "LONG" else orh
        risk_per_share = abs(fill - stop)
        if risk_per_share <= 0:
            continue
        # Same-bar stop: skip.
        if side == "LONG" and float(rec.low) <= stop:
            traded_today.add(sym)
            continue
        if side == "SHORT" and float(rec.high) >= stop:
            traded_today.add(sym)
            continue
        qty = floor((equity * RISK_FRAC) / risk_per_share)
        if qty < 1:
            continue
        entry_side = "BUY" if side == "LONG" else "SELL"
        entry_cost = order_cost(entry_side, "MIS", qty, fill)
        open_pos[sym] = {
            "side": side,
            "qty": qty,
            "entry": fill,
            "stop": stop,
            "entry_cost": entry_cost,
        }
        traded_today.add(sym)

        equity_pts[pd.Timestamp(day)] = equity

    # Daily marks: equity after each session (positions are flat overnight).
    if all_bars.empty:
        eq = pd.Series(dtype=float)
    else:
        days = sorted(set(all_bars["date"]))
        running = capital
        # rebuild from trades
        tdf_tmp = pd.DataFrame(trades)
        eq_map = {}
        if tdf_tmp.empty:
            for d in days:
                eq_map[pd.Timestamp(d)] = capital
        else:
            tdf_tmp["date"] = pd.to_datetime(tdf_tmp["date"])
            pnl_by_day = tdf_tmp.groupby(tdf_tmp["date"].dt.date)["net_pnl"].sum()
            for d in days:
                running += float(pnl_by_day.get(d, 0.0))
                eq_map[pd.Timestamp(d)] = running
        eq = pd.Series(eq_map).sort_index()

    tdf = pd.DataFrame(trades)
    if tdf.empty:
        tdf = pd.DataFrame(columns=["date", "symbol", "side", "qty", "entry", "exit", "gross_pnl", "cost", "net_pnl", "reason"])
    return {"equity": eq, "trades": tdf, "round_trips": tdf, "metrics": summarize(eq, tdf if not tdf.empty else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"]))}


def run_windows(windows: dict[str, tuple[date, date]], capital: float = CAPITAL) -> dict:
    return {name: simulate(start, end, capital) for name, (start, end) in windows.items()}
