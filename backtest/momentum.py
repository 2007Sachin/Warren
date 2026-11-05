"""Daily long-only momentum, CNC, equal-weight top 2 of 5 NSE names."""
from __future__ import annotations

from datetime import date

import pandas as pd

from backtest.costs import order_cost
from backtest.loaders import EQUITIES, NIFTY, close_frame
from backtest.metrics import summarize

LOOKBACK = 90
SKIP = 5
REBALANCE = 21
TOP_HOLD = 2
TOP_KEEP = 3
CAPITAL = 100_000.0


def scores(closes: pd.DataFrame) -> pd.DataFrame:
    r90 = closes.pct_change(LOOKBACK)
    r5 = closes.pct_change(SKIP)
    return r90 - r5


def _rank_row(row: pd.Series) -> list[str]:
    return row.dropna().sort_values(ascending=False).index.tolist()


def simulate(closes: pd.DataFrame, start: date, end: date, capital: float = CAPITAL) -> dict:
    """Trade inside [start, end]. Ranking uses history before start."""
    px = closes.loc[: pd.Timestamp(end)].copy()
    sc = scores(px)
    idx = px.index
    loc = {d: i for i, d in enumerate(idx)}
    in_window = [d for d in idx if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    if len(in_window) < 2:
        empty = pd.Series(dtype=float)
        return {"equity": empty, "trades": pd.DataFrame(), "metrics": summarize(empty, pd.DataFrame())}

    cash = capital
    holdings: dict[str, float] = {}  # qty
    trades = []
    equity_pts = []
    last_rebalance_i = None

    def mark(day) -> float:
        value = cash
        for sym, qty in holdings.items():
            value += qty * float(px.loc[day, sym])
        return value

    def flatten(day, reason: str) -> None:
        nonlocal cash
        price_row = px.loc[day]
        for sym in list(holdings):
            qty = holdings.pop(sym)
            if qty <= 0:
                continue
            price = float(price_row[sym])
            cost = order_cost("SELL", "CNC", qty, price)
            cash += qty * price - cost["total"]
            trades.append({
                "date": day.date() if hasattr(day, "date") else day,
                "symbol": sym,
                "side": "SELL",
                "qty": qty,
                "price": price,
                "gross_pnl": 0.0,
                "cost": cost["total"],
                "net_pnl": -cost["total"],
                "reason": reason,
                "breakdown": cost,
            })

    def rebalance(day) -> None:
        nonlocal cash, last_rebalance_i
        row = sc.loc[day]
        ranked = _rank_row(row)
        if len(ranked) < TOP_HOLD:
            return
        keep = set(ranked[:TOP_KEEP])
        target = [s for s in ranked if s in holdings and s in keep]
        for s in ranked:
            if len(target) >= TOP_HOLD:
                break
            if s not in target:
                target.append(s)
        target = target[:TOP_HOLD]
        price_row = px.loc[day]
        # Sell names not in target.
        for sym in list(holdings):
            if sym not in target:
                qty = holdings.pop(sym)
                price = float(price_row[sym])
                cost = order_cost("SELL", "CNC", qty, price)
                cash += qty * price - cost["total"]
                trades.append({
                    "date": day.date() if hasattr(day, "date") else day,
                    "symbol": sym,
                    "side": "SELL",
                    "qty": qty,
                    "price": price,
                    "gross_pnl": 0.0,
                    "cost": cost["total"],
                    "net_pnl": -cost["total"],
                    "reason": "rebalance_exit",
                    "breakdown": cost,
                })
        equity = mark(day)
        n = len(target)
        if n == 0:
            last_rebalance_i = loc[day]
            return
        slice_value = equity / n
        # Resize remaining + buy new so each target is equal weight.
        for sym in target:
            price = float(price_row[sym])
            desired_qty = slice_value / price
            have = holdings.get(sym, 0.0)
            delta = desired_qty - have
            if abs(delta) * price < 1.0:
                holdings[sym] = desired_qty
                continue
            if delta > 0:
                qty = delta
                cost = order_cost("BUY", "CNC", qty, price)
                cash -= qty * price + cost["total"]
                holdings[sym] = have + qty
                trades.append({
                    "date": day.date() if hasattr(day, "date") else day,
                    "symbol": sym,
                    "side": "BUY",
                    "qty": qty,
                    "price": price,
                    "gross_pnl": 0.0,
                    "cost": cost["total"],
                    "net_pnl": -cost["total"],
                    "reason": "rebalance_entry",
                    "breakdown": cost,
                })
            else:
                qty = -delta
                cost = order_cost("SELL", "CNC", qty, price)
                cash += qty * price - cost["total"]
                holdings[sym] = have - qty
                if holdings[sym] <= 1e-9:
                    holdings.pop(sym, None)
                trades.append({
                    "date": day.date() if hasattr(day, "date") else day,
                    "symbol": sym,
                    "side": "SELL",
                    "qty": qty,
                    "price": price,
                    "gross_pnl": 0.0,
                    "cost": cost["total"],
                    "net_pnl": -cost["total"],
                    "reason": "rebalance_trim",
                    "breakdown": cost,
                })
        last_rebalance_i = loc[day]

    # First day we can rank (90 bars of history).
    for day in in_window:
        i = loc[day]
        hist = sc.loc[day].dropna()
        ready = len(hist) >= TOP_HOLD and i >= LOOKBACK
        if ready and (last_rebalance_i is None or (i - last_rebalance_i) >= REBALANCE):
            rebalance(day)
        equity_pts.append((day, mark(day)))

    if in_window:
        flatten(in_window[-1], "window_end")
        equity_pts[-1] = (in_window[-1], mark(in_window[-1]))

    equity = pd.Series({d: v for d, v in equity_pts}, dtype=float).sort_index()
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        tdf = pd.DataFrame(columns=["date", "symbol", "side", "qty", "price", "gross_pnl", "cost", "net_pnl", "reason"])
    paired = _pair_round_trips(tdf)
    return {"equity": equity, "trades": tdf, "round_trips": paired, "metrics": summarize(equity, paired)}


def _pair_round_trips(orders: pd.DataFrame) -> pd.DataFrame:
    """Match FIFO lots so win-rate / profit-factor / cost% use complete CNC cycles."""
    if orders.empty:
        return pd.DataFrame(columns=["gross_pnl", "cost", "net_pnl"])
    lots: dict[str, list] = {}
    rows = []
    for rec in orders.itertuples(index=False):
        sym = rec.symbol
        lots.setdefault(sym, [])
        if rec.side == "BUY":
            lots[sym].append({"qty": rec.qty, "price": rec.price, "cost": rec.cost})
        else:
            remain = rec.qty
            sell_cost_unit = rec.cost / rec.qty if rec.qty else 0.0
            while remain > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                take = min(remain, lot["qty"])
                buy_cost = lot["cost"] * (take / lot["qty"])
                sell_cost = sell_cost_unit * take
                gross = (rec.price - lot["price"]) * take
                cost = buy_cost + sell_cost
                rows.append({"gross_pnl": gross, "cost": cost, "net_pnl": gross - cost})
                lot["qty"] -= take
                lot["cost"] -= buy_cost
                remain -= take
                if lot["qty"] <= 1e-9:
                    lots[sym].pop(0)
            if remain > 1e-9:
                # leftover sell (should not happen); treat as cost-only
                rows.append({"gross_pnl": 0.0, "cost": sell_cost_unit * remain, "net_pnl": -sell_cost_unit * remain})
    if not rows:
        # no completed lots — count order costs as trades
        return pd.DataFrame({
            "gross_pnl": [0.0] * len(orders),
            "cost": orders["cost"].tolist(),
            "net_pnl": (-orders["cost"]).tolist(),
        })
    return pd.DataFrame(rows)


def run_windows(windows: dict[str, tuple[date, date]], capital: float = CAPITAL) -> dict:
    closes = close_frame(EQUITIES)
    out = {}
    for name, (start, end) in windows.items():
        out[name] = simulate(closes, start, end, capital)
    return out


def nifty_buy_hold(start: date, end: date, capital: float = CAPITAL) -> dict:
    px = close_frame([NIFTY])[NIFTY].dropna()
    window = px.loc[pd.Timestamp(start): pd.Timestamp(end)]
    if len(window) < 2:
        empty = pd.Series(dtype=float)
        return {"equity": empty, "trades": pd.DataFrame(), "metrics": summarize(empty, pd.DataFrame())}
    entry = float(window.iloc[0])
    qty = capital / entry
    buy = order_cost("BUY", "CNC", qty, entry)
    cash = capital - qty * entry - buy["total"]
    equity = (cash + qty * window).copy()
    exit_px = float(window.iloc[-1])
    sell = order_cost("SELL", "CNC", qty, exit_px)
    equity.iloc[-1] = cash + qty * exit_px - sell["total"]
    gross = (exit_px - entry) * qty
    cost = buy["total"] + sell["total"]
    trips = pd.DataFrame([{"gross_pnl": gross, "cost": cost, "net_pnl": gross - cost}])
    orders = pd.DataFrame([
        {"date": window.index[0].date(), "symbol": NIFTY, "side": "BUY", "qty": qty, "price": entry, "cost": buy["total"]},
        {"date": window.index[-1].date(), "symbol": NIFTY, "side": "SELL", "qty": qty, "price": exit_px, "cost": sell["total"]},
    ])
    return {"equity": equity, "trades": orders, "round_trips": trips, "metrics": summarize(equity, trips)}
