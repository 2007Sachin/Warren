"""HARMONIC-XABCD on 15-minute bars. Pre-registered rules; no post-TEST edits.

Conservative ambiguities (make the book look worse, not better):
- ZigZag uses high/low extremes; a pivot is usable only from the bar AFTER
  the confirmation bar.
- XB/XD match tolerance is ±0.05; if several names fit, keep the closest XD
  (ties keep the first listed name).
- Group 1 is AC = |C-X|/|A-X| < 1 (C has not exceeded A). Group 2 otherwise.
- Bad coverage days are dropped before the ZigZag (stitches sessions).
- Same-bar stop vs target: stop wins.
- Size is 20% of equity notional, whole shares, no leverage.
- Shorts are modelled as MIS (cash-market approximation).
- Brokerage follows backtest.costs (Rs 20 flat), not min(Rs 20, 0.03%).
"""
from __future__ import annotations

from datetime import date
from math import floor

import pandas as pd

from backtest.costs import order_cost
from backtest.loaders import coverage_ok, load_15m
from backtest.metrics import summarize

SYMBOLS = ["RELIANCE-EQ", "HDFCBANK-EQ", "INFY-EQ", "TCS-EQ", "SBIN-EQ"]
CAPITAL = 100_000.0
NOTIONAL_FRAC = 0.20
XB_TOL = 0.05
XD_TOL = 0.05
MAX_HOLD_BARS = 10
FIBS = (0.382, 0.5, 0.618, 0.786, 0.886, 1.0, 1.13, 1.272, 1.618, 2.0, 2.618, 3.618, 4.618)

GROUP1 = {
    0.382: (("Bat", 0.886), ("Alt Bat", 1.13), ("Butterfly", 1.272), ("Crab", 1.618)),
    0.500: (("Bat", 0.886), ("Alt Bat", 1.13), ("Butterfly", 1.272), ("Crab", 1.618)),
    0.618: (("Gartley", 0.786), ("Alt Gartley", 0.886), ("Butterfly", 1.272), ("Crab", 1.618)),
    0.786: (("Butterfly", 1.272), ("Crab", 1.618)),
    0.886: (("Crab", 1.618), ("Deep Crab", 2.61)),
}
SHARK_A = (("Shark", 0.886), ("Alt Shark", 1.13), ("EShark", 1.272), ("EEShark", 1.618))
SHARK_B = (("EShark", 1.272), ("EEShark", 1.618), ("DES", 2.618))


def confirmed_zigzag(df: pd.DataFrame, threshold: float) -> list[dict]:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)
    if n == 0:
        return []
    pivots: list[dict] = []
    ext_h, ext_h_i = high[0], 0
    ext_l, ext_l_i = low[0], 0
    direction = 0
    for i in range(1, n):
        if direction >= 0 and high[i] >= ext_h:
            ext_h, ext_h_i = high[i], i
        if direction <= 0 and low[i] <= ext_l:
            ext_l, ext_l_i = low[i], i
        confirm_high = ext_h > 0 and (ext_h - low[i]) / ext_h >= threshold
        confirm_low = ext_l > 0 and (high[i] - ext_l) / ext_l >= threshold
        if direction == 0:
            if confirm_high:
                pivots.append({"kind": "H", "index": ext_h_i, "price": float(ext_h), "confirmed_index": i})
                direction = -1
                ext_l, ext_l_i = low[i], i
            elif confirm_low:
                pivots.append({"kind": "L", "index": ext_l_i, "price": float(ext_l), "confirmed_index": i})
                direction = 1
                ext_h, ext_h_i = high[i], i
        elif direction == 1 and confirm_high:
            pivots.append({"kind": "H", "index": ext_h_i, "price": float(ext_h), "confirmed_index": i})
            direction = -1
            ext_l, ext_l_i = low[i], i
        elif direction == -1 and confirm_low:
            pivots.append({"kind": "L", "index": ext_l_i, "price": float(ext_l), "confirmed_index": i})
            direction = 1
            ext_h, ext_h_i = high[i], i
    return pivots


def _nearest_fib(ratio: float) -> float:
    return min(FIBS, key=lambda f: abs(f - ratio))


def classify(xb: float, xd: float, ac: float, xa_retr: float) -> str | None:
    """Return a pattern name or None. xa_retr is AB/XA, same as xb here."""
    if ac < 1:
        best = None
        best_err = 1e9
        for grid, names in GROUP1.items():
            if abs(xb - grid) > XB_TOL:
                continue
            for name, target in names:
                err = abs(xd - target)
                if err <= XD_TOL and err < best_err:
                    best, best_err = name, err
        return best
    # Group 2
    if 0.3 <= xb <= 0.7 and abs(xd - 0.786) <= XD_TOL:
        return "Cypher"
    best = None
    best_err = 1e9
    if 0.3 <= xb <= 0.7 and 0.98 <= xd <= 4.618:
        table = SHARK_A
    elif 0.7 < xb <= 0.98 and 0.98 <= xd <= 4.618:
        table = SHARK_B
    else:
        table = ()
    for name, target in table:
        err = abs(xd - target)
        if err <= XD_TOL and err < best_err:
            best, best_err = name, err
    # Shark 0.886 sits outside the 0.98–4.618 band; still allow if closest
    # and XB is in 0.3–0.7 with XD within 0.05 of 0.886 (listed subtype).
    if best is None and 0.3 <= xb <= 0.7 and abs(xd - 0.886) <= XD_TOL:
        best = "Shark"
    return best


def _ratios(x, a, b, c, d) -> dict:
    xa = abs(a - x)
    ab = abs(b - a)
    if xa <= 0 or ab <= 0:
        return {}
    xb = ab / xa
    xd = abs(a - d) / xa
    ac = abs(c - x) / xa
    bc_ab = abs(c - b) / ab
    return {"xa": xa, "xb": xb, "xd": xd, "ac": ac, "bc_ab": bc_ab}


def _prz_and_stops(x, a, b, c, d, xd_ratio: float, bullish: bool) -> dict:
    xa = a - x
    # (1) XA projected at the pattern XD value
    p1 = a - xd_ratio * xa  # bullish: down from A; bearish xa negative so up from A
    # (2) fib retracement of B->C, nearest fib to D
    bc = c - b
    if bc != 0:
        raw = (d - b) / bc
        p2 = b + _nearest_fib(raw) * bc
    else:
        p2 = d
    # (3) trend-based fib extension A->B->C, nearest fib to D
    ab = b - a
    if ab != 0:
        # D ~ C + f*(B-A) = C + f*ab
        raw_e = (d - c) / ab if ab != 0 else 0.0
        p3 = c + _nearest_fib(raw_e) * ab
    else:
        p3 = d
    levels = (p1, p2, p3)
    prz_lo, prz_hi = min(levels), max(levels)
    if prz_lo == prz_hi:
        pad = abs(xa) * 0.002
        prz_lo, prz_hi = prz_lo - pad, prz_hi + pad
    t1 = d + 0.382 * (a - d)
    t2 = d + 0.618 * (a - d)
    stop = x - 1.13 * abs(x - d) if bullish else x + 1.13 * abs(x - d)
    return {
        "prz_lo": float(min(prz_lo, prz_hi)),
        "prz_hi": float(max(prz_lo, prz_hi)),
        "t1": float(t1),
        "t2": float(t2),
        "stop": float(stop),
        "p1": float(p1),
        "xd_ratio": float(xd_ratio),
    }


def _pattern_from_pivots(pivots: list[dict]) -> dict | None:
    if len(pivots) < 5:
        return None
    last = pivots[-5:]
    kinds = [p["kind"] for p in last]
    if kinds not in (["L", "H", "L", "H", "L"], ["H", "L", "H", "L", "H"]):
        return None
    bullish = kinds[0] == "L"
    x, a, b, c, d = (p["price"] for p in last)
    rats = _ratios(x, a, b, c, d)
    if not rats:
        return None
    name = classify(rats["xb"], rats["xd"], rats["ac"], rats["xb"])
    if not name:
        return None
    geo = _prz_and_stops(x, a, b, c, d, rats["xd"], bullish)
    return {
        "name": name,
        "bullish": bullish,
        "x": x, "a": a, "b": b, "c": c, "d": d,
        "d_index": last[-1]["index"],
        "d_confirmed": last[-1]["confirmed_index"],
        **rats,
        **geo,
    }


def _filter_bars(symbol: str, allowed: set) -> pd.DataFrame:
    df = load_15m(symbol)
    mask = [(symbol, d) in allowed for d in df["date"]]
    out = df.loc[mask].reset_index(drop=True)
    return out


def _close_in_prz(close: float, lo: float, hi: float) -> bool:
    return lo <= close <= hi


def simulate(threshold: float, start: date, end: date, capital: float = CAPITAL) -> dict:
    ok = coverage_ok("15m")
    allowed = {(row.symbol, row.date) for row in ok.itertuples(index=False) if bool(row.backtest_ok)}
    frames = {}
    for sym in SYMBOLS:
        df = _filter_bars(sym, allowed)
        df.attrs["symbol"] = sym
        frames[sym] = df

    # Event merge: process all symbols in timestamp order with a shared book.
    events = []
    for sym, df in frames.items():
        pivots = confirmed_zigzag(df, threshold)
        events.append((sym, df, pivots))

    books = {sym: {"pending": None, "pos": None, "running": []} for sym in SYMBOLS}
    all_pivots_by_i = {sym: {} for sym in SYMBOLS}
    for sym, df, pivots in events:
        run = []
        for p in pivots:
            run.append(p)
            all_pivots_by_i[sym].setdefault(p["confirmed_index"], []).append(list(run))

    rows = []
    for sym, df, _ in events:
        for i, rec in enumerate(df.itertuples(index=False)):
            rows.append((rec.timestamp, i, sym))
    rows.sort()

    equity = capital
    trades: list[dict] = []
    daily: dict[pd.Timestamp, float] = {}

    def flatten(sym, i, price, reason, qty=None):
        nonlocal equity
        pos = books[sym]["pos"]
        if pos is None:
            return
        take = pos["qty"] if qty is None else min(qty, pos["qty"])
        if take <= 0:
            return
        df = frames[sym]
        side = pos["side"]
        exit_side = "SELL" if side == "LONG" else "BUY"
        entry = pos["entry"]
        gross = (price - entry) * take if side == "LONG" else (entry - price) * take
        entry_cost_part = pos["entry_cost"] * (take / pos["qty_init"])
        exit_cost = order_cost(exit_side, "MIS", take, price)
        cost = entry_cost_part + exit_cost["total"]
        net = gross - cost
        equity += net
        trades.append({
            "date": df.loc[i, "date"],
            "timestamp": df.loc[i, "timestamp"],
            "symbol": sym,
            "pattern": pos["pattern"],
            "side": side,
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
            books[sym]["pending"] = _pattern_from_pivots(all_pivots_by_i[sym][i][-1])

        pos = books[sym]["pos"]
        if pos is not None and in_window:
            side = pos["side"]
            stop = pos["stop"]
            hit_stop = (side == "LONG" and lo <= stop) or (side == "SHORT" and hi >= stop)
            if hit_stop:
                fill = min(op, stop) if side == "LONG" else max(op, stop)
                flatten(sym, i, fill, "stop")
            else:
                if pos is not None and books[sym]["pos"] is not None:
                    pos = books[sym]["pos"]
                    half = pos["qty_init"] / 2.0
                    if not pos["t1_done"]:
                        hit_t1 = (side == "LONG" and hi >= pos["t1"]) or (side == "SHORT" and lo <= pos["t1"])
                        if hit_t1:
                            flatten(sym, i, pos["t1"], "target_382", qty=min(half, pos["qty"]))
                            if books[sym]["pos"] is not None:
                                books[sym]["pos"]["t1_done"] = True
                    pos = books[sym]["pos"]
                    if pos is not None and not pos["t2_done"]:
                        hit_t2 = (side == "LONG" and hi >= pos["t2"]) or (side == "SHORT" and lo <= pos["t2"])
                        if hit_t2:
                            flatten(sym, i, pos["t2"], "target_618")
                    pos = books[sym]["pos"]
                    if pos is not None:
                        pos["bars"] += 1
                        if pos["bars"] >= MAX_HOLD_BARS:
                            flatten(sym, i, close, "time_stop")

        pos = books[sym]["pos"]
        pending = books[sym]["pending"]
        if pos is None and pending is not None and in_window and i > pending["d_confirmed"]:
            if _close_in_prz(close, pending["prz_lo"], pending["prz_hi"]):
                side = "LONG" if pending["bullish"] else "SHORT"
                qty = floor((equity * NOTIONAL_FRAC) / close)
                if qty >= 1:
                    entry_side = "BUY" if side == "LONG" else "SELL"
                    ec = order_cost(entry_side, "MIS", qty, close)
                    books[sym]["pos"] = {
                        "side": side,
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
        eq = pd.Series({pd.Timestamp(start): capital, pd.Timestamp(end): capital})
    elif eq.iloc[0] != capital:
        eq = pd.concat([pd.Series({eq.index[0] - pd.Timedelta(days=1): capital}), eq])
    return {"equity": eq, "trades": tdf, "round_trips": tdf, "metrics": summarize(eq, tdf if len(tdf) else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"]))}
