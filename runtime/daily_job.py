"""Paper daily loop. Replay mode uses stored candles only — no live orders."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from math import floor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.laya_advisor import regime_vote, size_multiplier, triage_vote
from backtest.donchian import SMA_DAYS, _ohlc, pooled_equities
from backtest.donchian_v2 import donchian_low, in_regime, ranked_breakouts
from backtest.loaders import NIFTY, daily_close
from paper.broker import PaperBroker
from paper.ledger import (
    daily_pnl,
    equity_start,
    orders as load_orders,
    peak_equity,
    positions as load_positions,
    set_position,
    upsert_daily_pnl,
    upsert_order,
)
from risk.kill_switch import can_trade, check_daily_loss, load as ks_load
from runtime.features import atr_series, nifty_state, signal_features
from runtime.telegram_bot import send, summary_text

CAPITAL = 100_000.0
RISK_FRAC = 0.0075
HEAT_CAP = 0.04
MAX_POS = 6
DAILY_LOSS = 0.02
LIMIT_PAD = 0.01
STRATEGY = "donchian-v2"


def _tag(symbol: str, signal_date: date, side: str) -> str:
    return f"{STRATEGY}:{symbol}:{signal_date}:{side}"


def _calendar(start: date, end: date) -> list:
    nifty = daily_close(NIFTY).dropna()
    return [d for d in nifty.index if pd.Timestamp(start) <= d <= pd.Timestamp(end)]


def _opens(bars, day) -> dict[str, float]:
    out = {}
    for sym, px in bars.items():
        if day in px.index:
            out[sym] = float(px.loc[day, "open"])
    return out


def _closes(bars, day) -> dict[str, float]:
    out = {}
    for sym, px in bars.items():
        if day in px.index:
            out[sym] = float(px.loc[day, "close"])
    return out


def coverage_ok_daily(bars, day, min_frac: float = 0.8) -> bool:
    n = len(bars)
    have = sum(1 for px in bars.values() if day in px.index)
    return n > 0 and (have / n) >= min_frac


def restore_broker() -> PaperBroker:
    broker = PaperBroker()
    existing = load_orders()
    if existing.empty:
        return broker
    from datetime import date as date_cls
    from paper.broker import PaperOrder

    def _as_date(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        text = str(v).strip()
        if text in {"", "nan", "None", "NaT"}:
            return None
        return date_cls.fromisoformat(text[:10])

    for rec in existing.itertuples(index=False):
        sd = _as_date(getattr(rec, "signal_date", None))
        fd = _as_date(getattr(rec, "fill_date", None))
        order = PaperOrder(
            client_tag=str(rec.client_tag),
            symbol=str(rec.symbol),
            side=str(rec.side),
            qty=int(rec.qty),
            limit_price=float(rec.limit_price),
            status=str(rec.status),
            signal_date=sd,
            fill_date=fd,
            fill_price=None if pd.isna(getattr(rec, "fill_price", None)) else float(rec.fill_price),
        )
        broker.orders[order.client_tag] = order
    return broker


def restore_pos() -> dict[str, dict]:
    frame = load_positions()
    pos = {}
    if frame.empty:
        return pos
    for rec in frame.itertuples(index=False):
        if int(rec.qty) <= 0:
            continue
        pos[str(rec.symbol)] = {
            "qty": int(rec.qty),
            "avg": float(rec.avg_price),
            "stop": None if pd.isna(rec.stop_price) else float(rec.stop_price),
            "tag": rec.client_tag,
        }
    return pos


def _qty(equity: float, atr: float, entry: float) -> int:
    if atr is None or atr <= 0 or entry <= 0:
        return 0
    stop_dist = 2.0 * atr
    if stop_dist <= 0:
        return 0
    return floor((equity * RISK_FRAC) / stop_dist)


def run_range(start: date, end: date, *, replay: bool, dry_run: bool) -> dict:
    if not replay:
        from data.pipeline import run as refresh
        refresh()
        try:
            import data.coverage as coverage
            coverage.build()
        except Exception as exc:
            send(f"coverage failed: {exc}", dry_run=True)

    names = pooled_equities()
    bars = _ohlc(names)
    sma = {sym: bars[sym]["close"].rolling(SMA_DAYS, min_periods=SMA_DAYS).mean() for sym in names}
    atrs = {sym: atr_series(bars[sym]) for sym in names}
    nifty = daily_close(NIFTY).dropna()
    warm = [d for d in nifty.index if d < pd.Timestamp(start)]
    cal = _calendar(start, end)
    broker = restore_broker()
    pos = restore_pos()
    last_exit_i: dict[str, int] = {}
    off_streak = {sym: 0 for sym in names}
    loc_all = {d: i for i, d in enumerate(list(nifty.index))}
    new_orders = 0
    new_pnl = 0

    for day in warm:
        for sym in names:
            if day not in bars[sym].index:
                continue
            if in_regime(bars[sym], sma[sym], day):
                off_streak[sym] = 0
            else:
                off_streak[sym] += 1

    for day in cal:
        session = day.date() if hasattr(day, "date") else day
        opens = _opens(bars, day)
        resolved = broker.resolve_open(session, opens)
        n_fills = 0
        n_exp = 0
        realized = 0.0
        fill_lines = []
        for order in resolved:
            upsert_order(order.as_dict())
            if order.status == "FILLED":
                n_fills += 1
                cost = float((order.costs_breakdown or {}).get("total") or 0)
                if order.side == "BUY":
                    pos[order.symbol] = {
                        "qty": order.qty,
                        "avg": order.fill_price,
                        "stop": order.stop_price,
                        "tag": order.client_tag,
                    }
                    set_position({
                        "symbol": order.symbol, "qty": order.qty, "avg_price": order.fill_price,
                        "stop_price": order.stop_price, "opened_at": session, "client_tag": order.client_tag,
                    })
                    fill_lines.append(f"FILL BUY {order.symbol} {order.qty}@{order.fill_price:.2f}")
                else:
                    held = pos.pop(order.symbol, None)
                    if held:
                        realized += (order.fill_price - held["avg"]) * order.qty - cost
                        last_exit_i[order.symbol] = loc_all.get(day, 0)
                    set_position({"symbol": order.symbol, "qty": 0, "avg_price": 0, "stop_price": None, "opened_at": None, "client_tag": None})
                    fill_lines.append(f"FILL SELL {order.symbol} {order.qty}@{order.fill_price:.2f}")
            else:
                n_exp += 1

        closes = _closes(bars, day)
        mtm = 0.0
        for sym, rec in pos.items():
            px = closes.get(sym, rec["avg"])
            mtm += rec["qty"] * (px - rec["avg"])
        prev_eq = equity_start(CAPITAL)
        equity = prev_eq + realized + mtm
        peak = max(peak_equity(CAPITAL), equity)
        dd = equity / peak - 1.0 if peak else 0.0
        wrote_pnl = upsert_daily_pnl({
            "date": session, "realized": realized, "unrealized": mtm,
            "equity": equity, "drawdown": dd,
        })
        if wrote_pnl:
            new_pnl += 1
            check_daily_loss(equity - prev_eq, prev_eq * DAILY_LOSS)

        i = loc_all.get(day, 0)
        for sym in names:
            if day not in bars[sym].index:
                continue
            if in_regime(bars[sym], sma[sym], day):
                off_streak[sym] = 0
            else:
                off_streak[sym] += 1

        pending_sell = {}
        for sym, rec in list(pos.items()):
            px = bars[sym]
            ll = donchian_low(px, day)
            if ll is not None and day in px.index and float(px.loc[day, "close"]) < ll:
                pending_sell[sym] = "donchian20"
            elif off_streak[sym] >= 5:
                pending_sell.setdefault(sym, "regime_off")

        skipped = not coverage_ok_daily(bars, day)
        n_signals = 0
        if skipped:
            send(f"SKIP incomplete daily coverage {session}", dry_run=dry_run)
        elif not can_trade():
            send(f"HALTED {ks_load().reason}", dry_run=dry_run)
        else:
            for sym, reason in pending_sell.items():
                rec = pos.get(sym)
                if not rec:
                    continue
                close = closes.get(sym)
                if close is None:
                    continue
                tag = _tag(sym, session, "SELL")
                before = broker.get_order_status(tag)
                order = broker.place_limit_order(
                    sym, "SELL", rec["qty"], close * (1 - LIMIT_PAD), tag,
                    signal_date=session,
                )
                created = upsert_order(order.as_dict())
                if created and before is None:
                    new_orders += 1

            cands = ranked_breakouts(names, bars, sma, day, pos, pending_sell, last_exit_i, i)
            n_signals = len(cands)
            regime = regime_vote(nifty_state(day))
            heat = RISK_FRAC * len(pos)
            for sym, score in cands:
                if not can_trade():
                    break
                if len(pos) + sum(1 for o in broker.pending() if o.side == "BUY") >= MAX_POS:
                    break
                if heat + RISK_FRAC > HEAT_CAP:
                    break
                px = bars[sym]
                close = float(px.loc[day, "close"])
                atr = float(atrs[sym].loc[day]) if day in atrs[sym].index and pd.notna(atrs[sym].loc[day]) else None
                tri = triage_vote(signal_features(px, day, atr))
                mult = size_multiplier(tri, regime)
                if mult <= 0:
                    continue
                qty = _qty(equity, atr or 0.0, close)
                qty = int(qty * mult)
                if qty < 1:
                    continue
                stop = close - 2.0 * (atr or 0.0)
                tag = _tag(sym, session, "BUY")
                before = broker.get_order_status(tag)
                order = broker.place_limit_order(
                    sym, "BUY", qty, close * (1 + LIMIT_PAD), tag,
                    signal_date=session, stop_price=stop,
                )
                created = upsert_order(order.as_dict())
                if created and before is None:
                    new_orders += 1
                heat += RISK_FRAC

        send(summary_text({
            "session": session,
            "equity": equity,
            "drawdown": dd,
            "n_signals": n_signals,
            "n_fills": n_fills,
            "n_expired": n_exp,
            "n_open": len(pos),
            "halted": not can_trade(),
            "fill_lines": fill_lines,
        }), dry_run=dry_run)

    return {"new_orders": new_orders, "new_pnl_rows": new_pnl, "days": len(cal)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--replay", default=None, help="YYYY-MM-DD:YYYY-MM-DD")
    p.add_argument("--live-fetch", action="store_true")
    p.add_argument("--send-telegram", action="store_true")
    args = p.parse_args()
    dry = not args.send_telegram
    if args.replay:
        a, b = args.replay.split(":")
        start = datetime.strptime(a, "%Y-%m-%d").date()
        end = datetime.strptime(b, "%Y-%m-%d").date()
        out = run_range(start, end, replay=True, dry_run=dry)
    else:
        today = date.today()
        out = run_range(today, today, replay=not args.live_fetch, dry_run=dry)
    print("JOB", out)


if __name__ == "__main__":
    main()
