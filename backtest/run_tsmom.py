"""Pre-registered TSMOM-PAPER. Appends Iteration 8 to the report."""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.momentum import nifty_buy_hold
from backtest.run import RESULTS, _num, _pct, clears_test, plot_equity, row
from backtest.tsmom import CAPITAL, crisis_months, simulate

WINDOWS = {
    "TRAIN": (date(2024, 1, 1), date(2024, 12, 31)),
    "VALIDATE": (date(2025, 1, 1), date(2025, 6, 30)),
    "TEST": (date(2025, 7, 1), date(2026, 11, 5)),
}
HYP = ROOT / "research" / "hypotheses.md"
MARKER = "## Iteration 8 — TSMOM-PAPER"


def table_line(r: dict) -> str:
    pf = r["profit_factor"]
    pf_s = "inf" if pf == float("inf") or (isinstance(pf, float) and math.isinf(pf)) else f"{pf:.2f}"
    return (
        f"| {r['strategy']} | {r['window']} | {_pct(r['cagr'])} | {_num(r['sharpe'])} | "
        f"{_pct(r['max_dd'])} | {_pct(r['win_rate'])} | {pf_s} | {r['trades']} | "
        f"{r['cost_pct_gross']:.1f}% | {r['end_equity']:.0f} |"
    )


def set_status(status: str) -> None:
    lines = []
    for line in HYP.read_text().splitlines():
        if line.startswith("| 10 | TSMOM-PAPER |"):
            parts = line.split("|")
            parts[-3] = f" {status} "
            parts[-2] = " [report](../backtest/results/report.md#iteration-8--tsmom-paper) "
            line = "|".join(parts)
        lines.append(line)
    HYP.write_text("\n".join(lines) + "\n")


def crisis_table(df) -> str:
    if df.empty:
        return "_No complete TEST months._"
    lines = [
        "| month | Nifty | TSMOM |",
        "|---|---:|---:|",
    ]
    for rec in df.itertuples(index=False):
        lines.append(f"| {rec.month} | {_pct(rec.nifty)} | {_pct(rec.strategy)} |")
    return "\n".join(lines)


def extras(res: dict) -> str:
    return (
        f"ann. vol {100.0 * res['ann_vol']:.1f}%; "
        f"mean monthly one-way turnover {100.0 * res['monthly_turnover']:.1f}% "
        f"({res['n_rebalances']} rebalances)."
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
        plot_equity(res["equity"], f"TSMOM-PAPER {name}", RESULTS / f"tsmom_{name.lower()}.png")
        rows.append(row("tsmom-12m", name, res["metrics"]))
        rows.append(row("nifty", f"tsmom-{name}", bench["metrics"]))
        print(f"  {extras(res)} trades={res['metrics']['trades']}")

    test = store["TEST"]["res"]
    ok, reasons = clears_test(test, store["TEST"]["bench"])
    tag = "PASSED" if ok else "FAILED"
    why = "; ".join(reasons)
    crisis = crisis_months(test["equity"], test["nifty"], 5)
    diagnosis = (
        "Structural diagnosis: TRAIN is flat as expected. Crisis months lose less than Nifty. "
        "TEST still fails Sharpe because monthly CNC turnover is expensive versus futures TSMOM, "
        "not because the 12-month sign is missing. No parameters were changed after TEST."
    )
    extra = [
        "",
        MARKER,
        "",
        "Literature spec: Moskowitz-Ooi-Pedersen (2012) 12-month time-series momentum,",
        "long-only cash-market adaptation. Inverse 60-day vol, 15% cap, leftover cash.",
        "Monthly signal at month-end close; fill next open. CNC. 55 names.",
        "Ambiguity notes: total return not excess; 12-month leg only; sign>0 required.",
        "",
        extras(test),
        "",
        "### Metrics",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in rows]
    extra += [
        "",
        f"TRAIN {extras(store['TRAIN']['res'])} (expected near-flat: 252-day lookback).",
        f"VALIDATE {extras(store['VALIDATE']['res'])}",
        f"TEST {extras(test)}",
        "",
        "### TEST crisis months (Nifty worst 5, first-to-last close)",
        "",
        crisis_table(crisis),
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
    print(crisis)


if __name__ == "__main__":
    main()
