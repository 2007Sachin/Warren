"""TSMOM-PAPER: long-only Moskowitz-Ooi-Pedersen 12-month time-series momentum.

Paper rules, frozen. Conservative ambiguities:
- Signal is the sign of 252-day *total* return (not excess; no cash rate).
- Only the 12-month leg (the paper's strongest univariate lookback).
- Inverse-vol weights among eligible names, then 15% cap; leftover is cash.
  If capped weights sum above 100%, scale down.
- σ is the sample std (ddof=1) of 60 daily close-to-close returns.
- Zero or undefined vol / missing 252-day history: not eligible.
- Sign zero is not a long (strictly > 0).
- Rebalance at the next session's open after month-end close.
- Whole shares, no leverage. Window-end flatten at last close.
"""
from __future__ import annotations

from datetime import date
from math import floor, sqrt

import numpy as np
import pandas as pd

from backtest.costs import order_cost
from backtest.donchian import pooled_equities
from backtest.loaders import NIFTY, daily_close
from backtest.metrics import TRADING_DAYS, summarize
from data.query import load

CAPITAL = 100_000.0
LOOKBACK = 252
VOL_WINDOW = 60
CAP_W = 0.15


def _closes(names: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close_cols = {}
    open_cols = {}
    for sym in names:
        df = load(sym).copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.normalize()
        df = df.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
        close_cols[sym] = df["close"]
        open_cols[sym] = df["open"]
    close = pd.concat(close_cols, axis=1).sort_index()
    opn = pd.concat(open_cols, axis=1).sort_index()
    return close, opn


def month_ends(calendar: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(1, index=calendar)
    return s.groupby(s.index.to_period("M")).apply(lambda x: x.index[-1]).values


def inverse_vol_weights(vols: pd.Series) -> pd.Series:
    """Normalize 1/σ among eligible names, cap 15%, leftover cash."""
    inv = 1.0 / vols
    raw = inv / inv.sum()
    w = raw.clip(upper=CAP_W)
    total = float(w.sum())
    if total > 1.0:
        w = w / total
    return w


def _fifo_trips(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])
    lots: dict[str, list] = {}
    rows = []
    for rec in orders.itertuples(index=False):
        lots.setdefault(rec.symbol, [])
        if rec.side == "BUY":
            lots[rec.symbol].append({"qty": rec.qty, "price": rec.price, "cost": rec.cost})
            continue
        remain = rec.qty
        sell_unit = rec.cost / rec.qty if rec.qty else 0.0
        while remain > 1e-9 and lots[rec.symbol]:
            lot = lots[rec.symbol][0]
            take = min(remain, lot["qty"])
            buy_cost = lot["cost"] * (take / lot["qty"])
            sell_cost = sell_unit * take
            gross = (rec.price - lot["price"]) * take
            cost = buy_cost + sell_cost
            rows.append({"gross_pnl": gross, "cost": cost, "net_pnl": gross - cost})
            lot["qty"] -= take
            lot["cost"] -= buy_cost
            remain -= take
            if lot["qty"] <= 1e-9:
                lots[rec.symbol].pop(0)
    if not rows:
        return pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])
    return pd.DataFrame(rows)


def simulate(start: date, end: date, capital: float = CAPITAL) -> dict:
    names = pooled_equities()
    close, opn = _closes(names)
    nifty = daily_close(NIFTY).dropna()
    calendar = nifty.index[(nifty.index >= pd.Timestamp(start)) & (nifty.index <= pd.Timestamp(end))]
    full_cal = nifty.index
    ret252 = close.pct_change(LOOKBACK)
    vol = close.pct_change().rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=1)

    month_end_list = []
    by_m: dict = {}
    for d in full_cal:
        by_m.setdefault(d.to_period("M"), []).append(d)
    for dates in by_m.values():
        month_end_list.append(dates[-1])
    month_end_list = [d for d in month_end_list if d in close.index]

    loc = {d: i for i, d in enumerate(full_cal)}
    rebalance_of = {}
    for me in month_end_list:
        i = loc.get(me)
        if i is None or i + 1 >= len(full_cal):
            continue
        rebalance_of[full_cal[i + 1]] = me

    weights_on_rebal: dict = {}
    for rebal, me in rebalance_of.items():
        if me not in ret252.index:
            continue
        elig = []
        vols = {}
        defined = False
        for sym in names:
            r = ret252.loc[me, sym] if sym in ret252.columns else np.nan
            v = vol.loc[me, sym] if sym in vol.columns else np.nan
            if pd.notna(r):
                defined = True
            if pd.notna(r) and r > 0 and pd.notna(v) and v > 0:
                elig.append(sym)
                vols[sym] = float(v)
        if not defined:
            continue
        if not elig:
            weights_on_rebal[rebal] = pd.Series(dtype=float)
            continue
        weights_on_rebal[rebal] = inverse_vol_weights(pd.Series(vols))

    cash = capital
    holdings: dict[str, float] = {}
    last_px: dict[str, float] = {}
    trades = []
    equity_pts = []
    turnovers = []
    prev_w = pd.Series(dtype=float)

    def mark(day) -> float:
        value = cash
        for sym, qty in holdings.items():
            if day in close.index and pd.notna(close.loc[day, sym]):
                last_px[sym] = float(close.loc[day, sym])
            value += qty * last_px.get(sym, 0.0)
        return value

    def sell(sym, qty, price, day, reason):
        nonlocal cash
        qty = min(qty, holdings.get(sym, 0.0))
        if qty <= 0:
            return
        cost = order_cost("SELL", "CNC", qty, price)
        cash += qty * price - cost["total"]
        holdings[sym] -= qty
        if holdings[sym] <= 1e-9:
            holdings.pop(sym, None)
        trades.append({
            "date": day.date() if hasattr(day, "date") else day,
            "symbol": sym, "side": "SELL", "qty": qty, "price": price,
            "cost": cost["total"], "reason": reason,
        })

    def buy(sym, qty, price, day, reason):
        nonlocal cash
        if qty <= 0:
            return
        cost = order_cost("BUY", "CNC", qty, price)
        need = qty * price + cost["total"]
        while qty >= 1:
            cost = order_cost("BUY", "CNC", qty, price)
            need = qty * price + cost["total"]
            if need <= cash:
                break
            qty -= 1
        if qty < 1:
            return
        cash -= need
        holdings[sym] = holdings.get(sym, 0.0) + float(qty)
        last_px[sym] = price
        trades.append({
            "date": day.date() if hasattr(day, "date") else day,
            "symbol": sym, "side": "BUY", "qty": float(qty), "price": price,
            "cost": cost["total"], "reason": reason,
        })

    for day in calendar:
        if day in weights_on_rebal:
            w = weights_on_rebal[day]
            equity = cash + sum(holdings.get(sym, 0.0) * last_px.get(sym, 0.0) for sym in holdings)
            aligned = prev_w.reindex(names).fillna(0.0)
            new_al = w.reindex(names).fillna(0.0)
            turnovers.append(0.5 * float((new_al - aligned).abs().sum()))
            prev_w = w
            # sells first
            for sym in list(holdings):
                price = float(opn.loc[day, sym]) if day in opn.index and pd.notna(opn.loc[day, sym]) else last_px.get(sym, 0.0)
                tw = float(w.get(sym, 0.0)) if len(w) else 0.0
                target_qty = floor((equity * tw) / price) if price > 0 else 0
                have = holdings[sym]
                if have > target_qty:
                    sell(sym, have - target_qty, price, day, "rebalance")
            for sym in names:
                if day not in opn.index or pd.isna(opn.loc[day, sym]):
                    continue
                price = float(opn.loc[day, sym])
                tw = float(w.get(sym, 0.0)) if len(w) else 0.0
                if tw <= 0:
                    continue
                target_qty = floor((equity * tw) / price) if price > 0 else 0
                have = holdings.get(sym, 0.0)
                if target_qty > have:
                    buy(sym, target_qty - have, price, day, "rebalance")

        if day in close.index:
            for sym in list(holdings):
                if pd.notna(close.loc[day, sym]):
                    last_px[sym] = float(close.loc[day, sym])
        equity_pts.append((day, mark(day)))

    if holdings and len(calendar):
        last = calendar[-1]
        for sym in list(holdings):
            price = last_px.get(sym, 0.0)
            if last in close.index and pd.notna(close.loc[last, sym]):
                price = float(close.loc[last, sym])
            sell(sym, holdings.get(sym, 0.0), price, last, "window_end")
        equity_pts[-1] = (last, cash)

    equity = pd.Series({d: v for d, v in equity_pts}, dtype=float).sort_index()
    orders = pd.DataFrame(trades)
    trips = _fifo_trips(orders)
    rets = equity.pct_change().dropna()
    ann_vol = float(rets.std(ddof=1) * sqrt(TRADING_DAYS)) if len(rets) > 1 else 0.0
    monthly_to = float(np.mean(turnovers)) if turnovers else 0.0
    return {
        "equity": equity,
        "trades": orders,
        "round_trips": trips,
        "metrics": summarize(equity, trips if len(trips) else pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])),
        "ann_vol": ann_vol,
        "monthly_turnover": monthly_to,
        "n_rebalances": len(turnovers),
        "n_symbols": len(names),
        "nifty": nifty.reindex(calendar).ffill(),
    }


def crisis_months(equity: pd.Series, nifty: pd.Series, n: int = 5) -> pd.DataFrame:
    """Nifty's worst n calendar months vs strategy, first-to-last close in month."""
    both = pd.DataFrame({"nifty": nifty, "strat": equity}).dropna()
    if both.empty:
        return pd.DataFrame(columns=["month", "nifty", "strategy"])
    rows = []
    for period, g in both.groupby(both.index.to_period("M")):
        if len(g) < 2:
            continue
        rows.append({
            "month": str(period),
            "nifty": float(g["nifty"].iloc[-1] / g["nifty"].iloc[0] - 1.0),
            "strategy": float(g["strat"].iloc[-1] / g["strat"].iloc[0] - 1.0),
        })
    tab = pd.DataFrame(rows)
    if tab.empty:
        return tab
    return tab.nsmallest(n, "nifty").reset_index(drop=True)
