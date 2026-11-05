"""Pre-registered HARMONIC-XABCD-DAILY. Appends Iteration 6 to the report."""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.harmonic_daily import CAPITAL, PRIMARY_ZZ, SENS_ZZ, simulate
from backtest.momentum import nifty_buy_hold
from backtest.run import RESULTS, _num, _pct, clears_test, plot_equity, row

WINDOWS = {
    "TRAIN": (date(2024, 1, 1), date(2024, 12, 31)),
    "VALIDATE": (date(2025, 1, 1), date(2025, 6, 30)),
    "TEST": (date(2025, 7, 1), date(2026, 11, 5)),
}
MIN_TEST_TRADES = 20
HYP = ROOT / "research" / "hypotheses.md"
MARKER = "## Iteration 6 — HARMONIC-XABCD-DAILY"


def table_line(r: dict) -> str:
    pf = r["profit_factor"]
    pf_s = "inf" if pf == float("inf") or (isinstance(pf, float) and math.isinf(pf)) else f"{pf:.2f}"
    return (
        f"| {r['strategy']} | {r['window']} | {_pct(r['cagr'])} | {_num(r['sharpe'])} | "
        f"{_pct(r['max_dd'])} | {_pct(r['win_rate'])} | {pf_s} | {r['trades']} | "
        f"{r['cost_pct_gross']:.1f}% | {r['end_equity']:.0f} |"
    )


def pattern_table(trades) -> str:
    if trades.empty:
        return "_No trades._"
    lines = [
        "| pattern | trades | wins | losses | net P&L | profit factor |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, sub in trades.groupby("pattern"):
        wins = sub.loc[sub["net_pnl"] > 0, "net_pnl"].sum()
        loss = sub.loc[sub["net_pnl"] < 0, "net_pnl"].abs().sum()
        pf = wins / loss if loss > 0 else (math.inf if wins > 0 else 0.0)
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        lines.append(
            f"| {name} | {len(sub)} | {int((sub.net_pnl > 0).sum())} | {int((sub.net_pnl < 0).sum())} | "
            f"{sub.net_pnl.sum():.0f} | {pf_s} |"
        )
    return "\n".join(lines)


def trade_list(trades) -> str:
    if trades.empty:
        return "_None._"
    lines = [
        "| date | symbol | pattern | side | entry | exit | net | reason |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    show = trades.sort_values("date")
    extra = ""
    if len(show) > 80:
        extra = f"\n\n_{len(show) - 80} additional round trips omitted._"
        show = show.tail(80)
    for rec in show.itertuples(index=False):
        lines.append(
            f"| {rec.date} | {rec.symbol} | {rec.pattern} | {rec.side} | "
            f"{rec.entry:.2f} | {rec.exit:.2f} | {rec.net_pnl:.2f} | {rec.reason} |"
        )
    return "\n".join(lines) + extra


def set_status(status: str) -> None:
    lines = []
    for line in HYP.read_text().splitlines():
        if line.startswith("| 8 | HARMONIC-XABCD-DAILY |"):
            parts = line.split("|")
            parts[-3] = f" {status} "
            parts[-2] = " [report](../backtest/results/report.md#iteration-6--harmonic-xabcd-daily) "
            line = "|".join(parts)
        lines.append(line)
    HYP.write_text("\n".join(lines) + "\n")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    primary = {}
    rows = []
    for name, (start, end) in WINDOWS.items():
        print(f"5% {name}...")
        res = simulate(PRIMARY_ZZ, start, end, CAPITAL)
        bench = nifty_buy_hold(start, end, CAPITAL)
        primary[name] = {"res": res, "bench": bench}
        plot_equity(res["equity"], f"HARMONIC daily 5% {name}", RESULTS / f"harmonic_daily_{name.lower()}.png")
        rows.append(row("harmonic-d-5pct", name, res["metrics"]))
        rows.append(row("nifty", f"harmd-{name}", bench["metrics"]))
        print(f"  symbols={res['n_symbols']} trades={res['metrics']['trades']}")

    print("7% sensitivity...")
    sens_rows = []
    for name, (start, end) in WINDOWS.items():
        res = simulate(SENS_ZZ, start, end, CAPITAL)
        sens_rows.append(row("harmonic-d-7pct", name, res["metrics"]))
        print(f"  7% {name} trades={res['metrics']['trades']}")

    test = primary["TEST"]["res"]
    n_test = int(test["metrics"]["trades"])
    if n_test < MIN_TEST_TRADES:
        tag = "INSUFFICIENT SAMPLE"
        why = f"TEST produced {n_test} trades (need {MIN_TEST_TRADES}). Aggregate gate metrics are not used."
    else:
        ok, reasons = clears_test(test, primary["TEST"]["bench"])
        tag = "PASSED" if ok else "FAILED"
        why = "; ".join(reasons)

    combined = pd.concat(
        [primary[w]["res"]["trades"] for w in WINDOWS if not primary[w]["res"]["trades"].empty],
        ignore_index=True,
    ) if any(not primary[w]["res"]["trades"].empty for w in WINDOWS) else pd.DataFrame(columns=["pattern", "net_pnl"])

    diagnosis = (
        "Structural diagnosis: TEST sample clears 20 trades but Sharpe and PF fail because "
        "0.382/0.618 AD scale-outs sit inside CNC STT plus slippage. Group 2 sharks/cyphers "
        "lose; Bat is the only pooled winner. Bearish patterns skipped (no overnight short). "
        "Cost-versus-target-scale, not a missing Fibonacci. No parameters were changed after TEST."
    )
    extra = [
        "",
        MARKER,
        "",
        "Pre-registered daily XABCD (same Group 1/2 ratios as #4). ZigZag 5% on daily closes",
        "(7% sensitivity is not the TEST decision). Long-only CNC, 10% equity, max 10 names.",
        "Bearish patterns skipped. Universe: 55 cash equities.",
        "",
        "### Metrics (5% ZigZag)",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in rows]
    extra += [
        "",
        "### Pattern-type breakdown (5%, TRAIN+VALIDATE+TEST)",
        "",
        pattern_table(combined),
        "",
        "### 7% ZigZag sensitivity (not used for TEST)",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in sens_rows]
    extra += [
        "",
        f"### Verdict: {tag}",
        "",
        why,
        "",
        diagnosis,
        "",
        "TEST trades (5%):",
        "",
        trade_list(test["trades"]),
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
