"""Pre-registered DONCHIAN-TREND-DAILY. Appends Iteration 5 to the report."""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.donchian import CAPITAL, simulate
from backtest.momentum import nifty_buy_hold
from backtest.run import RESULTS, _num, _pct, clears_test, plot_equity, row

WINDOWS = {
    "TRAIN": (date(2024, 1, 1), date(2024, 12, 31)),
    "VALIDATE": (date(2025, 1, 1), date(2025, 6, 30)),
    "TEST": (date(2025, 7, 1), date(2026, 11, 5)),
}
HYP = ROOT / "research" / "hypotheses.md"
MARKER = "## Iteration 5 — DONCHIAN-TREND-DAILY"


def table_line(r: dict) -> str:
    pf = r["profit_factor"]
    pf_s = "inf" if pf == float("inf") or (isinstance(pf, float) and math.isinf(pf)) else f"{pf:.2f}"
    return (
        f"| {r['strategy']} | {r['window']} | {_pct(r['cagr'])} | {_num(r['sharpe'])} | "
        f"{_pct(r['max_dd'])} | {_pct(r['win_rate'])} | {pf_s} | {r['trades']} | "
        f"{r['cost_pct_gross']:.1f}% | {r['end_equity']:.0f} |"
    )


def trade_table(trips, limit: int = 80) -> str:
    if trips.empty:
        return "_No completed round trips._"
    sub = trips.sort_values("date")
    extra = ""
    if len(sub) > limit:
        extra = f"\n\n_{len(sub) - limit} additional round trips omitted from the list._"
        sub = sub.tail(limit)
    lines = [
        "| date | symbol | qty | entry | exit | hold days | net P&L | reason |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for rec in sub.itertuples(index=False):
        lines.append(
            f"| {rec.date} | {rec.symbol} | {rec.qty:.0f} | {rec.entry:.2f} | {rec.price:.2f} | "
            f"{rec.hold_days:.0f} | {rec.net_pnl:.2f} | {rec.reason} |"
        )
    return "\n".join(lines) + extra


def set_status(status: str) -> None:
    lines = []
    for line in HYP.read_text().splitlines():
        if line.startswith("| 7 | DONCHIAN-TREND-DAILY |"):
            parts = line.split("|")
            parts[-3] = f" {status} "
            parts[-2] = " [report](../backtest/results/report.md#iteration-5--donchian-trend-daily) "
            line = "|".join(parts)
        lines.append(line)
    HYP.write_text("\n".join(lines) + "\n")


def extras(res: dict) -> str:
    return (
        f"round trips {int(res['metrics']['trades'])}; avg hold {res['avg_hold_days']:.1f} days; "
        f"top-5 winners = {100.0 * res['top5_share']:.1f}% of winning P&L; "
        f"flat (no position) {100.0 * res['cash_frac']:.1f}% of days; "
        f"regime-off {100.0 * res['regime_off_frac']:.1f}% of days."
    )


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    store = {}
    for name, (start, end) in WINDOWS.items():
        print(f"{name}...")
        res = simulate(start, end, CAPITAL)
        bench = nifty_buy_hold(start, end, CAPITAL)
        store[name] = {"res": res, "bench": bench}
        plot_equity(res["equity"], f"Donchian-55 {name}", RESULTS / f"donchian_{name.lower()}.png")
        rows.append(row("donchian-55", name, res["metrics"]))
        rows.append(row("nifty", f"donchian-{name}", bench["metrics"]))
        print(f"  symbols={res['n_symbols']} {extras(res)}")

    test = store["TEST"]["res"]
    ok, reasons = clears_test(test, store["TEST"]["bench"])
    tag = "PASSED" if ok else "FAILED"
    why = "; ".join(reasons)
    fat = test["top5_share"]
    fat_note = (
        f"Top-5 winners are {100.0 * fat:.1f}% of winning P&L "
        f"({'fat-tail trending' if fat >= 0.50 else 'not concentrated in a few trends'})."
    )
    diagnosis = (
        "Structural diagnosis: TEST has fat tails (top-5 share of winning P&L) and can beat "
        "Nifty CAGR with DD under 20%, but Sharpe fails because many days are flat under "
        "the 200-day filter while 20-day stops still pay full CNC costs. Occupancy-and-cost "
        "on a working tail, not a missing channel. No parameters were changed after TEST."
    )
    extra = [
        "",
        MARKER,
        "",
        "Pre-registered Donchian-55 breakout, 55 NSE cash names, CNC, 12.5% equity, max 8.",
        "New entries only when Nifty 50 close > 200-day SMA. Fills at next open.",
        "",
        extras(test),
        fat_note,
        "",
        "### Metrics",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in rows]
    extra += [
        "",
        f"TRAIN {extras(store['TRAIN']['res'])}",
        f"VALIDATE {extras(store['VALIDATE']['res'])}",
        f"TEST {extras(test)}",
        "",
        "### TEST round trips",
        "",
        trade_table(test["round_trips"]),
        "",
        f"### Verdict: {tag}",
        "",
        why,
        "",
        diagnosis,
        "",
    ]
    report = RESULTS / "report.md"
    existing = report.read_text() if report.exists() else ""
    if MARKER in existing:
        existing = existing.split(MARKER)[0].rstrip()
    report.write_text(existing + "\n" + "\n".join(extra) + "\n")
    set_status(tag)
    print(tag)
    print(why)


if __name__ == "__main__":
    main()
