"""Pre-registered HARMONIC-XABCD walk-forward. Appends Iteration 2 to the report."""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.harmonic import CAPITAL, simulate
from backtest.momentum import nifty_buy_hold
from backtest.run import RESULTS, _num, _pct, clears_test, plot_equity, row

WINDOWS = {
    "VALIDATE": (date(2025, 8, 1), date(2026, 2, 28)),
    "TEST": (date(2026, 3, 1), date(2026, 11, 5)),
}
MIN_TEST_TRADES = 20
HYP = ROOT / "research" / "hypotheses.md"


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
    g = trades.groupby("pattern").agg(
        trades=("net_pnl", "size"),
        net=("net_pnl", "sum"),
        wins=("net_pnl", lambda s: int((s > 0).sum())),
        losses=("net_pnl", lambda s: int((s < 0).sum())),
    )
    lines = [
        "| pattern | trades | wins | losses | net P&L | profit factor |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, rec in g.iterrows():
        sub = trades[trades["pattern"] == name]
        wins = sub.loc[sub["net_pnl"] > 0, "net_pnl"].sum()
        loss = sub.loc[sub["net_pnl"] < 0, "net_pnl"].abs().sum()
        pf = (wins / loss) if loss > 0 else (math.inf if wins > 0 else 0.0)
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        lines.append(
            f"| {name} | {int(rec.trades)} | {int(rec.wins)} | {int(rec.losses)} | "
            f"{rec.net:.0f} | {pf_s} |"
        )
    return "\n".join(lines)


def trade_list(trades) -> str:
    if trades.empty:
        return "_None._"
    cols = ["date", "symbol", "pattern", "side", "entry", "exit", "net_pnl", "reason"]
    show = trades[cols].copy()
    show["date"] = show["date"].astype(str)
    lines = [
        "| date | symbol | pattern | side | entry | exit | net | reason |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for rec in show.itertuples(index=False):
        lines.append(
            f"| {rec.date} | {rec.symbol} | {rec.pattern} | {rec.side} | "
            f"{rec.entry:.2f} | {rec.exit:.2f} | {rec.net_pnl:.2f} | {rec.reason} |"
        )
    return "\n".join(lines)


def set_hypothesis_status(status: str, link: str) -> None:
    text = HYP.read_text()
    old = "| 4 | HARMONIC-XABCD |"
    lines = text.splitlines()
    out = []
    for line in lines:
        if line.startswith("| 4 | HARMONIC-XABCD |"):
            parts = line.split("|")
            # status is field -3 (before result link)
            parts[-3] = f" {status} "
            parts[-2] = f" {link} "
            line = "|".join(parts)
        out.append(line)
    HYP.write_text("\n".join(out) + "\n")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    primary = {}
    rows = []
    for name, (start, end) in WINDOWS.items():
        print(f"running 2% {name}...")
        res = simulate(0.02, start, end, CAPITAL)
        bench = nifty_buy_hold(start, end, CAPITAL)
        primary[name] = {"res": res, "bench": bench}
        plot_equity(res["equity"], f"HARMONIC-XABCD 2% {name}", RESULTS / f"harmonic_{name.lower()}.png")
        rows.append(row("harmonic-2pct", name, res["metrics"]))
        rows.append(row("nifty", f"harmonic-{name}", bench["metrics"]))

    print("running 3% sensitivity...")
    sens_rows = []
    for name, (start, end) in WINDOWS.items():
        res = simulate(0.03, start, end, CAPITAL)
        bench = primary[name]["bench"]
        sens_rows.append(row("harmonic-3pct", name, res["metrics"]))
        sens_rows.append(row("nifty", f"harmonic3-{name}", bench["metrics"]))
        primary[name]["sens"] = res

    test = primary["TEST"]["res"]
    n_test = int(test["metrics"]["trades"])
    if n_test < MIN_TEST_TRADES:
        verdict_tag = "INSUFFICIENT SAMPLE"
        why = f"TEST produced {n_test} trades (need {MIN_TEST_TRADES}). Aggregate gate metrics are not used."
        ok = False
    else:
        ok, reasons = clears_test(test, primary["TEST"]["bench"])
        verdict_tag = "PASSED" if ok else "FAILED"
        why = "; ".join(reasons)

    diagnosis = (
        "Structural diagnosis: a confirmed 2% ZigZag on 15-minute cash bars is a slow "
        "geometry clock, D is only tradable after a further full-threshold reversal, and "
        "entry still waits for a close back inside the PRZ, so most completions never fill. "
        "The 10-bar time stop (two and a half hours) then cuts anything that does fill "
        "before a 0.382 AD retracement can reasonably complete. That is a mismatch between "
        "pattern scale and holding time, not a missing Fibonacci ratio. Shorts are a "
        "cash-market approximation. No parameters were changed after TEST."
    )

    extra = [
        "",
        "## Iteration 2 — HARMONIC-XABCD",
        "",
        "Pre-registered 15-minute XABCD harmonics (ZigZag 2% for the TEST decision).",
        "Conservative choices: ±0.05 XB/XD; C beyond A is Group 2; coverage-false days dropped before ZigZag;",
        "entry on the first close in the PRZ after the confirmation bar; same-bar stop beats target;",
        "20% equity notional, no leverage; Rs 20 flat MIS brokerage from costs.py (not min(Rs 20, 0.03%)).",
        "Universe: RELIANCE, HDFCBANK, INFY, TCS, SBIN. Skip `backtest_ok=false` days.",
        "MIS costs from `backtest/costs.py`. Shorts modelled as cash-market MIS.",
        "",
        "### Metrics (2% ZigZag)",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in rows]
    extra += [
        "",
        "### Pattern-type breakdown (2%, VALIDATE + TEST combined)",
        "",
        pattern_table(pd_concat_trades(primary)),
        "",
        "### 3% ZigZag sensitivity (not used for TEST)",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in sens_rows]
    extra += [
        "",
        f"### Verdict: {verdict_tag}",
        "",
        why,
        "",
        diagnosis,
        "",
        "TEST trades (2%):",
        "",
        trade_list(test["trades"]),
        "",
    ]
    report = RESULTS / "report.md"
    existing = report.read_text() if report.exists() else ""
    marker = "## Iteration 2 — HARMONIC-XABCD"
    if marker in existing:
        existing = existing.split(marker)[0].rstrip()
    report.write_text(existing + "\n" + "\n".join(extra) + "\n")
    set_hypothesis_status(verdict_tag, "[report](../backtest/results/report.md#iteration-2--harmonic-xabcd)")
    print(verdict_tag)
    print(why)
    print("wrote", report)


def pd_concat_trades(primary: dict):
    import pandas as pd
    frames = [primary[w]["res"]["trades"] for w in WINDOWS]
    frames = [f for f in frames if not f.empty]
    if not frames:
        import pandas as pd
        return pd.DataFrame(columns=["pattern", "net_pnl"])
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    main()
