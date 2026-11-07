"""DONCHIAN-TREND-DAILY. Pre-registered; no post-TEST edits.

Conservative ambiguities:
- Universe is the 55 cash names (watchlist -EQ except NIFTYBEES).
- Donchian windows exclude today: close vs prior 55-day high / prior 20-day low.
- Breakout and stop fills are the next open (no same-bar execution).
- Existing names are not displaced when new breakouts appear.
- Size is 12.5% of post-exit equity, whole shares, no leverage; skip if
  cash cannot fund one share.
- Cooldown: no signal in the 5 sessions after an exit fill.
- Regime-off flatten after 5 consecutive Nifty-below-SMA closes, next open;
  Donchian-20 stops still fire while the regime is off.
"""
from __future__ import annotations

from datetime import date
from math import floor

import pandas as pd

from backtest.costs import order_cost
from backtest.loaders import NIFTY, daily_close, equity_universe
from backtest.metrics import summarize
from data.query import load

CAPITAL = 100_000.0
DONCHIAN_IN = 55
DONCHIAN_OUT = 20
SMA_DAYS = 200
MAX_POS = 8
WEIGHT = 0.125
COOLDOWN = 5
REGIME_OFF_DAYS = 5
SKIP = {"NIFTYBEES-EQ"}


def pooled_equities() -> list[str]:
    return [s for s in equity_universe() if s not in SKIP]


def _ohlc(symbols: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for sym in symbols:
        df = load(sym).copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.normalize()
        df = df.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
        out[sym] = df[["open", "high", "low", "close"]]
    return out


def simulate(start: date, end: date, capital: float = CAPITAL) -> dict:
    names = pooled_equities()
    bars = _ohlc(names)
    nifty = daily_close(NIFTY).dropna()
    sma = nifty.rolling(SMA_DAYS, min_periods=SMA_DAYS).mean()
    calendar = [d for d in nifty.index if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    if not calendar:
        empty = pd.Series(dtype=float)
        return {
            "equity": empty, "trades": pd.DataFrame(), "round_trips": pd.DataFrame(),
            "metrics": summarize(empty, pd.DataFrame()), "avg_hold_days": 0.0,
            "cash_frac": 1.0, "regime_off_frac": 0.0, "top5_share": 0.0, "n_symbols": len(names),
        }

    loc = {d: i for i, d in enumerate(calendar)}
    cash = capital
    pos: dict[str, dict] = {}
    last_exit_i: dict[str, int] = {}
    pending_buy: list[tuple[str, float]] = []
    pending_sell: set[str] = set()
    flatten_open = False
    off_streak = 0
    trades = []
    equity_pts = []
    cash_days = 0
    regime_off_days = 0

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

    def donchian_high(sym: str, day) -> float | None:
        px = bars[sym]
        if day not in px.index:
            return None
        i = px.index.get_loc(day)
        if i < DONCHIAN_IN:
            return None
        window = px["high"].iloc[i - DONCHIAN_IN : i]
        if len(window) < DONCHIAN_IN or window.isna().any():
            return None
        return float(window.max())

    def donchian_low(sym: str, day) -> float | None:
        px = bars[sym]
        if day not in px.index:
            return None
        i = px.index.get_loc(day)
        if i < DONCHIAN_OUT:
            return None
        window = px["low"].iloc[i - DONCHIAN_OUT : i]
        if len(window) < DONCHIAN_OUT or window.isna().any():
            return None
        return float(window.min())

    def ret55(sym: str, day) -> float:
        px = bars[sym]
        i = px.index.get_loc(day)
        if i < DONCHIAN_IN:
            return float("-inf")
        a = float(px["close"].iloc[i - DONCHIAN_IN])
        b = float(px["close"].iloc[i])
        if a <= 0:
            return float("-inf")
        return b / a - 1.0

    for day in calendar:
        i = loc[day]
        if flatten_open:
            for sym in list(pos):
                px = bars[sym]
                price = float(px.loc[day, "open"]) if day in px.index else pos[sym]["last"]
                sell(sym, day, price, "regime_off")
            pending_sell.clear()
            pending_buy = []
            flatten_open = False

        for sym in list(pending_sell):
            if sym in pos:
                px = bars[sym]
                price = float(px.loc[day, "open"]) if day in px.index else pos[sym]["last"]
                sell(sym, day, price, "donchian20")
            pending_sell.discard(sym)

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
        if not pos:
            cash_days += 1

        regime = bool(pd.notna(sma.loc[day]) and nifty.loc[day] > sma.loc[day])
        if not regime:
            off_streak += 1
            regime_off_days += 1
        else:
            off_streak = 0

        for sym in list(pos):
            ll = donchian_low(sym, day)
            px = bars[sym]
            if ll is None or day not in px.index:
                continue
            if float(px.loc[day, "close"]) < ll:
                pending_sell.add(sym)

        if off_streak >= REGIME_OFF_DAYS and pos:
            flatten_open = True
        elif regime:
            cands = []
            for sym in names:
                if sym in pos:
                    continue
                last_x = last_exit_i.get(sym)
                if last_x is not None and i - last_x < COOLDOWN + 1:
                    continue
                hh = donchian_high(sym, day)
                px = bars[sym]
                if hh is None or day not in px.index:
                    continue
                if float(px.loc[day, "close"]) > hh:
                    cands.append((sym, ret55(sym, day)))
            cands.sort(key=lambda x: x[1], reverse=True)
            pending_buy = cands

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
    return {
        "equity": equity,
        "trades": tdf,
        "round_trips": sells,
        "metrics": summarize(equity, sells if len(sells) else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])),
        "avg_hold_days": avg_hold,
        "cash_frac": cash_days / n_days,
        "regime_off_frac": regime_off_days / n_days,
        "top5_share": top5_share,
        "n_symbols": len(names),
        "n_days": n_days,
    }
