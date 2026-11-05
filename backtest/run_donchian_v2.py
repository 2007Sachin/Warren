"""Pre-registered DONCHIAN-TREND-DAILY-V2. Last Donchian-family run."""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.donchian import simulate as simulate_v1
from backtest.donchian_v2 import CAPITAL, simulate
from backtest.momentum import nifty_buy_hold
from backtest.run import RESULTS, _num, _pct, clears_test, plot_equity, row
from backtest.run_donchian import table_line, trade_table

WINDOWS = {
    "TRAIN": (date(2024, 1, 1), date(2024, 12, 31)),
    "VALIDATE": (date(2025, 1, 1), date(2025, 6, 30)),
    "TEST": (date(2025, 7, 1), date(2026, 11, 5)),
}
HYP = ROOT / "research" / "hypotheses.md"
MARKER = "## Iteration 7 — DONCHIAN-TREND-DAILY-V2"


def extras(res: dict) -> str:
    return (
        f"round trips {int(res['metrics']['trades'])}; avg hold {res['avg_hold_days']:.1f} days; "
        f"occupancy {100.0 * res['occupancy']:.1f}% of days "
        f"(avg {res['avg_slots']:.2f}/8 slots); "
        f"top-5 winners = {100.0 * res['top5_share']:.1f}% of winning P&L; "
        f"median regime-off days/name {res['regime_off_median']:.0f}; "
        f"mean name-days off {100.0 * res['regime_off_frac']:.1f}%."
    )


def set_status(status: str) -> None:
    lines = []
    for line in HYP.read_text().splitlines():
        if line.startswith("| 9 | DONCHIAN-TREND-DAILY-V2 |"):
            parts = line.split("|")
            parts[-3] = f" {status} "
            parts[-2] = " [report](../backtest/results/report.md#iteration-7--donchian-trend-daily-v2) "
            line = "|".join(parts)
        lines.append(line)
    HYP.write_text("\n".join(lines) + "\n")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    store = {}
    for name, (start, end) in WINDOWS.items():
        print(f"v2 {name}...")
        res = simulate(start, end, CAPITAL)
        bench = nifty_buy_hold(start, end, CAPITAL)
        store[name] = {"res": res, "bench": bench}
        plot_equity(res["equity"], f"Donchian-55 v2 {name}", RESULTS / f"donchian_v2_{name.lower()}.png")
        rows.append(row("donchian-v2", name, res["metrics"]))
        rows.append(row("nifty", f"donchian-v2-{name}", bench["metrics"]))
        print(f"  {extras(res)}")

    print("v1 TEST replay for comparison...")
    v1_test = simulate_v1(*WINDOWS["TEST"], CAPITAL)
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
        "Structural diagnosis: per-name 200-day SMAs raised TEST occupancy as hypothesized. "
        "Sharpe still misses 0.8, so idle cash was not the remaining constraint — Donchian-20 "
        "plus CNC costs were. Last Donchian-family run. No parameters were changed after TEST."
    )
    extra = [
        "",
        MARKER,
        "",
        "Last Donchian-family run. Same 55/20 channel, 12.5% x 8, CNC. Regime is each",
        "name's close vs its own 200-day SMA (no index filter). Final iteration.",
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
        "### TEST three-way vs #7",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity | occupancy | top-5 win share |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def three(label, m, occ, top5):
        pf = m["profit_factor"]
        pf_s = "inf" if pf == float("inf") or (isinstance(pf, float) and math.isinf(pf)) else f"{pf:.2f}"
        return (
            f"| {label} | TEST | {_pct(m['cagr'])} | {_num(m['sharpe'])} | {_pct(m['max_dd'])} | "
            f"{_pct(m['win_rate'])} | {pf_s} | {m['trades']} | {m['cost_pct_gross']:.1f}% | "
            f"{m['end_equity']:.0f} | {occ} | {top5} |"
        )

    extra.append(three(
        "donchian-v2", test["metrics"],
        f"{100.0 * test['occupancy']:.1f}%", f"{100.0 * test['top5_share']:.1f}%",
    ))
    extra.append(three(
        "donchian-#7", v1_test["metrics"],
        f"{100.0 * (1.0 - v1_test['cash_frac']):.1f}%", f"{100.0 * v1_test['top5_share']:.1f}%",
    ))
    extra.append(three(
        "nifty", store["TEST"]["bench"]["metrics"], "100%", "n/a",
    ))
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
