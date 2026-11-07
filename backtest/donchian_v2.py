"""DONCHIAN-TREND-DAILY-V2. Same channel as #7; per-stock 200-day SMA.

This is the last Donchian-family run. No post-TEST edits.

Conservative ambiguities (same as #7 except regime):
- Donchian windows exclude today; fills at next open.
- Existing names are not displaced. Whole shares, no leverage.
- Cooldown: no signal in the 5 sessions after an exit fill.
- SMA undefined (need 200 closes) is out of regime.
- A name missing a bar does not extend its off-streak.
- Same-day Donchian-20 stop beats a regime-off exit.
"""
from __future__ import annotations

from datetime import date
from math import floor

import pandas as pd

from backtest.costs import order_cost
from backtest.donchian import (
    CAPITAL,
    COOLDOWN,
    DONCHIAN_IN,
    DONCHIAN_OUT,
    MAX_POS,
    REGIME_OFF_DAYS,
    SMA_DAYS,
    WEIGHT,
    _ohlc,
    pooled_equities,
)
from backtest.loaders import NIFTY, daily_close
from backtest.metrics import summarize


def donchian_high(px: pd.DataFrame, day) -> float | None:
    if day not in px.index:
        return None
    i = px.index.get_loc(day)
    if i < DONCHIAN_IN:
        return None
    window = px["high"].iloc[i - DONCHIAN_IN : i]
    if len(window) < DONCHIAN_IN or window.isna().any():
        return None
    return float(window.max())


def donchian_low(px: pd.DataFrame, day) -> float | None:
    if day not in px.index:
        return None
    i = px.index.get_loc(day)
    if i < DONCHIAN_OUT:
        return None
    window = px["low"].iloc[i - DONCHIAN_OUT : i]
    if len(window) < DONCHIAN_OUT or window.isna().any():
        return None
    return float(window.min())


def in_regime(px: pd.DataFrame, sma: pd.Series, day) -> bool:
    if day not in px.index:
        return False
    if day not in sma.index or pd.isna(sma.loc[day]):
        return False
    return float(px.loc[day, "close"]) > float(sma.loc[day])


def ret55(px: pd.DataFrame, day) -> float:
    i = px.index.get_loc(day)
    if i < DONCHIAN_IN:
        return float("-inf")
    a = float(px["close"].iloc[i - DONCHIAN_IN])
    b = float(px["close"].iloc[i])
    if a <= 0:
        return float("-inf")
    return b / a - 1.0


def ranked_breakouts(names, bars, sma, day, held, pending_sell, last_exit_i, i) -> list[tuple[str, float]]:
    """Donchian-55 close breakouts, ranked by 55-day return. Verbatim v2 rule."""
    cands = []
    for sym in names:
        if sym in held or sym in pending_sell:
            continue
        last_x = last_exit_i.get(sym)
        if last_x is not None and i - last_x < COOLDOWN + 1:
            continue
        px = bars[sym]
        if not in_regime(px, sma[sym], day):
            continue
        hh = donchian_high(px, day)
        if hh is None or day not in px.index:
            continue
        if float(px.loc[day, "close"]) > hh:
            cands.append((sym, ret55(px, day)))
    cands.sort(key=lambda x: x[1], reverse=True)
    return cands


def simulate(start: date, end: date, capital: float = CAPITAL) -> dict:
    names = pooled_equities()
    bars = _ohlc(names)
    sma = {
        sym: bars[sym]["close"].rolling(SMA_DAYS, min_periods=SMA_DAYS).mean()
        for sym in names
    }
    nifty = daily_close(NIFTY).dropna()
    calendar = [d for d in nifty.index if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    if not calendar:
        empty = pd.Series(dtype=float)
        return {
            "equity": empty, "trades": pd.DataFrame(), "round_trips": pd.DataFrame(),
            "metrics": summarize(empty, pd.DataFrame()), "avg_hold_days": 0.0,
            "cash_frac": 1.0, "occupancy": 0.0, "avg_slots": 0.0,
            "regime_off_frac": 0.0, "regime_off_median": 0.0, "top5_share": 0.0,
            "n_symbols": len(names), "n_days": 0,
            "signals": pd.DataFrame(),
        }

    loc = {d: i for i, d in enumerate(calendar)}
    cash = capital
    pos: dict[str, dict] = {}
    last_exit_i: dict[str, int] = {}
    pending_buy: list[tuple[str, float]] = []
    pending_sell: dict[str, str] = {}
    off_streak = {sym: 0 for sym in names}
    off_days = {sym: 0 for sym in names}
    trades = []
    signal_rows = []
    equity_pts = []
    cash_days = 0
    slot_sum = 0

    def equity_mark(day) -> float:
        value = cash
        for rec in pos.values():
            px = bars[rec["sym"]]
            if day in px.index:
                value += rec["qty"] * float(px.loc[day, "close"])
            else:
                value += rec["qty"] * rec["last"]
        return value

    def sell(sym: str, day, price: float, reason: str):
        nonlocal cash
        rec = pos.pop(sym, None)
        if rec is None:
            return
        qty = rec["qty"]
        cost = order_cost("SELL", "CNC", qty, price)
        cash += qty * price - cost["total"]
        gross = (price - rec["entry"]) * qty
        hold = loc[day] - rec["entry_i"] + 1
        trades.append({
            "date": day.date() if hasattr(day, "date") else day,
            "symbol": sym,
            "side": "SELL",
            "qty": qty,
            "price": price,
            "entry": rec["entry"],
            "gross_pnl": gross,
            "cost": rec["entry_cost"] + cost["total"],
            "net_pnl": gross - rec["entry_cost"] - cost["total"],
            "reason": reason,
            "hold_days": hold,
        })
        last_exit_i[sym] = loc[day]

    def buy(sym: str, day, price: float, marked: float):
        nonlocal cash
        if sym in pos or len(pos) >= MAX_POS:
            return
        take = floor((marked * WEIGHT) / price) if price > 0 else 0
        cost = None
        while take >= 1:
            cost = order_cost("BUY", "CNC", take, price)
            if take * price + cost["total"] <= cash:
                break
            take -= 1
        if take < 1 or cost is None:
            return
        cash -= take * price + cost["total"]
        pos[sym] = {
            "sym": sym, "qty": float(take), "entry": price,
            "entry_cost": cost["total"], "entry_i": loc[day], "last": price,
        }
        trades.append({
            "date": day.date() if hasattr(day, "date") else day,
            "symbol": sym,
            "side": "BUY",
            "qty": float(take),
            "price": price,
            "gross_pnl": 0.0,
            "cost": cost["total"],
            "net_pnl": -cost["total"],
            "reason": "donchian55",
        })

    for day in calendar:
        i = loc[day]
        for sym, reason in list(pending_sell.items()):
            if sym in pos:
                px = bars[sym]
                price = float(px.loc[day, "open"]) if day in px.index else pos[sym]["last"]
                sell(sym, day, price, reason)
            pending_sell.pop(sym, None)

        marked = cash + sum(rec["qty"] * rec["last"] for rec in pos.values())
        if pending_buy:
            slots = MAX_POS - len(pos)
            for sym, _rank in pending_buy:
                if slots <= 0:
                    break
                if sym in pos:
                    continue
                px = bars[sym]
                if day not in px.index:
                    continue
                buy(sym, day, float(px.loc[day, "open"]), marked)
                slots = MAX_POS - len(pos)
        pending_buy = []

        for rec in pos.values():
            px = bars[rec["sym"]]
            if day in px.index:
                rec["last"] = float(px.loc[day, "close"])

        eq = equity_mark(day)
        equity_pts.append((day, eq))
        slot_sum += len(pos)
        if not pos:
            cash_days += 1

        for sym in names:
            px = bars[sym]
            if day not in px.index:
                continue
            on = in_regime(bars[sym], sma[sym], day)
            if not on:
                off_streak[sym] += 1
                off_days[sym] += 1
            else:
                off_streak[sym] = 0

        for sym in list(pos):
            px = bars[sym]
            ll = donchian_low(px, day)
            if ll is not None and day in px.index and float(px.loc[day, "close"]) < ll:
                pending_sell[sym] = "donchian20"
            elif off_streak[sym] >= REGIME_OFF_DAYS:
                pending_sell.setdefault(sym, "regime_off")

        pending_buy = ranked_breakouts(names, bars, sma, day, pos, pending_sell, last_exit_i, i)
        for rnk, (sym, score) in enumerate(pending_buy):
            signal_rows.append({
                "signal_date": day.date() if hasattr(day, "date") else day,
                "symbol": sym,
                "rank": rnk,
                "ret55": score,
            })

    if pos and calendar:
        last = calendar[-1]
        for sym in list(pos):
            px = bars[sym]
            price = float(px.loc[last, "close"]) if last in px.index else pos[sym]["last"]
            sell(sym, last, price, "window_end")
        equity_pts[-1] = (last, cash)

    equity = pd.Series({d: v for d, v in equity_pts}, dtype=float).sort_index()
    tdf = pd.DataFrame(trades)
    sells = tdf[tdf["side"] == "SELL"].copy() if not tdf.empty else pd.DataFrame(
        columns=["gross_pnl", "cost", "net_pnl", "hold_days", "symbol", "date"]
    )
    wins = sells[sells["net_pnl"] > 0] if len(sells) else sells
    if len(wins):
        top = wins.nlargest(min(5, len(wins)), "net_pnl")["net_pnl"].sum()
        top5_share = float(top / wins["net_pnl"].sum())
    else:
        top5_share = 0.0
    n_days = max(len(calendar), 1)
    avg_hold = float(sells["hold_days"].mean()) if len(sells) else 0.0
    off_list = [off_days[s] for s in names]
    return {
        "equity": equity,
        "trades": tdf,
        "round_trips": sells,
        "metrics": summarize(equity, sells if len(sells) else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])),
        "avg_hold_days": avg_hold,
        "cash_frac": cash_days / n_days,
        "occupancy": 1.0 - cash_days / n_days,
        "avg_slots": slot_sum / n_days,
        "regime_off_frac": (sum(off_list) / (len(names) * n_days)) if names else 0.0,
        "regime_off_median": float(pd.Series(off_list).median()) if off_list else 0.0,
        "top5_share": top5_share,
        "n_symbols": len(names),
        "n_days": n_days,
        "signals": pd.DataFrame(signal_rows),
    }
