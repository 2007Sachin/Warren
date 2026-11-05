"""Pre-registered NIFTY-MEANREVERT-DAILY. Appends Iteration 4 to the report."""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.meanrevert import CAPITAL, SYMBOL, simulate
from backtest.momentum import nifty_buy_hold
from backtest.run import RESULTS, _num, _pct, clears_test, plot_equity, row

WINDOWS = {
    "TRAIN": (date(2024, 1, 1), date(2024, 12, 31)),
    "VALIDATE": (date(2025, 1, 1), date(2025, 6, 30)),
    "TEST": (date(2025, 7, 1), date(2026, 11, 5)),
}
MIN_TEST_TRADES = 15
HYP = ROOT / "research" / "hypotheses.md"
MARKER = "## Iteration 4 — NIFTY-MEANREVERT-DAILY"


def table_line(r: dict) -> str:
    pf = r["profit_factor"]
    pf_s = "inf" if pf == float("inf") or (isinstance(pf, float) and math.isinf(pf)) else f"{pf:.2f}"
    return (
        f"| {r['strategy']} | {r['window']} | {_pct(r['cagr'])} | {_num(r['sharpe'])} | "
        f"{_pct(r['max_dd'])} | {_pct(r['win_rate'])} | {pf_s} | {r['trades']} | "
        f"{r['cost_pct_gross']:.1f}% | {r['end_equity']:.0f} |"
    )


def trade_table(trips) -> str:
    if trips.empty:
        return "_No completed round trips._"
    lines = [
        "| date | side | qty | entry | exit | hold days | net P&L | reason |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for rec in trips.itertuples(index=False):
        lines.append(
            f"| {rec.date} | {rec.side} | {rec.qty:.0f} | {rec.entry:.2f} | {rec.price:.2f} | "
            f"{getattr(rec, 'hold_days', 0):.0f} | {rec.net_pnl:.2f} | {rec.reason} |"
        )
    return "\n".join(lines)


def set_status(status: str) -> None:
    lines = []
    for line in HYP.read_text().splitlines():
        if line.startswith("| 6 | NIFTY-MEANREVERT-DAILY |"):
            parts = line.split("|")
            parts[-3] = f" {status} "
            parts[-2] = " [report](../backtest/results/report.md#iteration-4--nifty-meanrevert-daily) "
            line = "|".join(parts)
        lines.append(line)
    HYP.write_text("\n".join(lines) + "\n")


def extra_bits(res: dict) -> str:
    return (
        f"time-in-market {100.0 * res['time_in_market']:.1f}% "
        f"({res['invested_days']}/{res['n_days']} days); "
        f"avg hold {res['avg_hold_days']:.2f} days; round trips {int(res['metrics']['trades'])}."
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
        plot_equity(res["equity"], f"NIFTYBEES RSI-2 {name}", RESULTS / f"meanrevert_{name.lower()}.png")
        rows.append(row("rsi2-bees", name, res["metrics"]))
        rows.append(row("nifty", f"rsi2-{name}", bench["metrics"]))
        print(f"  trades={res['metrics']['trades']} {extra_bits(res)}")

    test = store["TEST"]["res"]
    n_test = int(test["metrics"]["trades"])
    pooled_md = []
    if n_test < MIN_TEST_TRADES:
        pooled = simulate(date(2024, 1, 1), date(2026, 11, 5), CAPITAL)
        plot_equity(pooled["equity"], "NIFTYBEES RSI-2 pooled", RESULTS / "meanrevert_pooled.png")
        rows.append(row("rsi2-bees", "POOLED", pooled["metrics"]))
        rows.append(row("nifty", "rsi2-POOLED", nifty_buy_hold(date(2024, 1, 1), date(2026, 11, 5), CAPITAL)["metrics"]))
        tag = "INSUFFICIENT SAMPLE"
        why = (
            f"TEST produced {n_test} trades (need {MIN_TEST_TRADES}). "
            f"Pooled TRAIN+VALIDATE+TEST: {extra_bits(pooled)}"
        )
        pooled_md = [
            "",
            "TEST sample is below 15 trades. Pooled TRAIN+VALIDATE+TEST is labeled below "
            "as `POOLED` and is **not** the gate.",
            "",
            extra_bits(pooled),
            "",
        ]
    else:
        ok, reasons = clears_test(test, store["TEST"]["bench"])
        tag = "PASSED" if ok else "FAILED"
        why = "; ".join(reasons)

    diagnosis = (
        "Structural diagnosis: Connors-style RSI(2) < 10 only fires after a two-day "
        "collapse, so the book is sparse and the 200-day Nifty filter plus a 2024-start "
        "SMA lookback delay entries further. CNC STT 0.1% both sides plus 0.05% slippage "
        "is large versus a 1–10 day ETF fade. Exit at close > 5-day SMA often cuts the "
        "rebound; the 10-day stop and regime-off next-open flatten residual risk. "
        "No parameters were changed after TEST."
    )

    extra = [
        "",
        MARKER,
        "",
        f"Pre-registered Connors RSI-2 on `{SYMBOL}` (CNC, 95% equity, no leverage).",
        "Regime = Nifty 50 close > 200-day SMA. Entry next open after RSI(2) < 10.",
        "",
        extra_bits(test),
        "",
        "### Metrics",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in rows]
    extra += pooled_md
    extra += [
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
        f"Time-in-market TRAIN {100*store['TRAIN']['res']['time_in_market']:.1f}%, "
        f"VALIDATE {100*store['VALIDATE']['res']['time_in_market']:.1f}%, "
        f"TEST {100*store['TEST']['res']['time_in_market']:.1f}%.",
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
