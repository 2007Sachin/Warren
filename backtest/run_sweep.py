"""Pre-registered LIQUIDITY-SWEEP-FADE. Appends Iteration 3 to the report."""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.momentum import nifty_buy_hold
from backtest.run import RESULTS, _num, _pct, clears_test, plot_equity, row
from backtest.sweep import CAPITAL, simulate

WINDOWS = {
    "VALIDATE": (date(2025, 8, 1), date(2026, 2, 28)),
    "TEST": (date(2026, 3, 1), date(2026, 11, 5)),
}
MIN_TEST_TRADES = 100
HYP = ROOT / "research" / "hypotheses.md"
MARKER = "## Iteration 3 — LIQUIDITY-SWEEP-FADE"


def table_line(r: dict) -> str:
    pf = r["profit_factor"]
    pf_s = "inf" if pf == float("inf") or (isinstance(pf, float) and math.isinf(pf)) else f"{pf:.2f}"
    return (
        f"| {r['strategy']} | {r['window']} | {_pct(r['cagr'])} | {_num(r['sharpe'])} | "
        f"{_pct(r['max_dd'])} | {_pct(r['win_rate'])} | {pf_s} | {r['trades']} | "
        f"{r['cost_pct_gross']:.1f}% | {r['end_equity']:.0f} |"
    )


def breakdown(trades: pd.DataFrame, col: str) -> str:
    if trades.empty:
        return "_No trades._"
    lines = [
        f"| {col} | trades | wins | net P&L | profit factor | cost % of gross |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, sub in trades.groupby(col):
        wins = sub.loc[sub["net_pnl"] > 0, "net_pnl"].sum()
        loss = sub.loc[sub["net_pnl"] < 0, "net_pnl"].abs().sum()
        pf = wins / loss if loss > 0 else (math.inf if wins > 0 else 0.0)
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        gross_abs = sub["gross_pnl"].abs().sum()
        cost_pct = 100.0 * sub["cost"].sum() / gross_abs if gross_abs else 0.0
        lines.append(
            f"| {key} | {len(sub)} | {int((sub.net_pnl > 0).sum())} | {sub.net_pnl.sum():.0f} | "
            f"{pf_s} | {cost_pct:.1f}% |"
        )
    return "\n".join(lines)


def set_status(status: str) -> None:
    lines = []
    for line in HYP.read_text().splitlines():
        if line.startswith("| 5 | LIQUIDITY-SWEEP-FADE |"):
            parts = line.split("|")
            parts[-3] = f" {status} "
            parts[-2] = " [report](../backtest/results/report.md#iteration-3--liquidity-sweep-fade) "
            line = "|".join(parts)
        lines.append(line)
    HYP.write_text("\n".join(lines) + "\n")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    store = {}
    for name, (start, end) in WINDOWS.items():
        print(f"compound {name}...")
        res = simulate(start, end, CAPITAL, compound=True)
        print(f"  symbols={res['n_symbols']} trades={res['metrics']['trades']}")
        print(f"flat {name}...")
        flat = simulate(start, end, CAPITAL, compound=False)
        bench = nifty_buy_hold(start, end, CAPITAL)
        store[name] = {"res": res, "flat": flat, "bench": bench}
        plot_equity(res["equity"], f"Sweep-fade compound {name}", RESULTS / f"sweep_{name.lower()}.png")
        rows.append(row("sweep-compound", name, res["metrics"]))
        rows.append(row("sweep-flat", name, flat["metrics"]))
        rows.append(row("nifty", f"sweep-{name}", bench["metrics"]))

    test = store["TEST"]["res"]
    n_test = int(test["metrics"]["trades"])
    if n_test < MIN_TEST_TRADES:
        tag = "INSUFFICIENT SAMPLE"
        why = f"TEST produced {n_test} trades (need {MIN_TEST_TRADES}). Aggregate gate metrics are not used."
    else:
        ok, reasons = clears_test(test, store["TEST"]["bench"])
        tag = "PASSED" if ok else "FAILED"
        why = "; ".join(reasons)

    diagnosis = (
        "Structural diagnosis: sizing 0.75% of equity against a 0.1% stop implies about 7.5× "
        "notional per name. Combined with Rs 20 brokerage, 0.05% slippage, and a 0.1% stop, "
        "each fade is cost-dominated. The compound book is wiped out. PDH, PDL, and swing "
        "levels all lose. That is a size-and-cost problem on a tight stop, not a missing "
        "level type. Nifty is a cash-market MIS approximation. No parameters were changed after TEST."
    )

    extra = [
        "",
        MARKER,
        "",
        "Pre-registered 15-minute liquidity-sweep fade. Universe: 55 equities + Nifty 50.",
        "Skip `backtest_ok=false`. Entry at next open. Risk 0.75% of equity (compounding) or of",
        "the initial Rs 1,00,000 (flat). MIS costs from `backtest/costs.py`.",
        "",
        "### Metrics",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in rows]
    extra += [
        "",
        "### TEST breakdown by level type",
        "",
        breakdown(test["trades"], "level_type"),
        "",
        "### TEST breakdown by direction",
        "",
        breakdown(test["trades"], "side"),
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
    print("wrote", report)


if __name__ == "__main__":
    main()
