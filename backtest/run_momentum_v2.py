"""Momentum v2 walk-forward. Appends Iteration 1 to backtest/results/report.md."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.loaders import equity_universe
from backtest.momentum import nifty_buy_hold, run_v2_windows
from backtest.run import CAPITAL, MOM_WINDOWS, RESULTS, _num, _pct, clears_test, plot_equity, row


def plot_overlay(strat, bench, title: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(strat.index, strat.values, color="#1f4e79", label="Momentum v2")
    ax.plot(bench.index, bench.values, color="#c45911", label="Nifty 50 buy-hold")
    ax.set_title(title)
    ax.set_ylabel("Equity (Rs)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def table_line(r: dict) -> str:
    pf = "inf" if r["profit_factor"] == float("inf") else f"{r['profit_factor']:.2f}"
    return (
        f"| {r['strategy']} | {r['window']} | {_pct(r['cagr'])} | {_num(r['sharpe'])} | "
        f"{_pct(r['max_dd'])} | {_pct(r['win_rate'])} | {pf} | {r['trades']} | "
        f"{r['cost_pct_gross']:.1f}% | {r['end_equity']:.0f} |"
    )


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    names = equity_universe()
    print(f"universe {len(names)} names")
    v2 = run_v2_windows(MOM_WINDOWS, CAPITAL)
    rows = []
    for name, (start, end) in MOM_WINDOWS.items():
        bench = nifty_buy_hold(start, end, CAPITAL)
        v2[name]["bench"] = bench
        plot_equity(v2[name]["equity"], f"Momentum v2 {name}", RESULTS / f"momentum_v2_{name.lower()}.png")
        rows.append(row("momentum_v2", name, v2[name]["metrics"]))
        rows.append(row("nifty", f"momentum_v2-{name}", bench["metrics"]))
    plot_overlay(
        v2["TEST"]["equity"],
        v2["TEST"]["bench"]["equity"],
        "Momentum v2 vs Nifty — TEST",
        RESULTS / "momentum_v2_test_vs_nifty.png",
    )
    ok, why = clears_test(v2["TEST"], v2["TEST"]["bench"])
    cash_frac = v2["TEST"]["cash_frac"]
    cash_line = (
        f"TEST days in cash (no holdings, including regime filter): "
        f"{100.0 * cash_frac:.1f}% ({v2['TEST']['cash_days']} / "
        f"{len(v2['TEST']['equity'])} sessions)."
    )
    verdict = (
        "Momentum v2 TEST: " + ("PASS. " if ok else "FAIL. ") + "; ".join(why) + ".\n\n"
        + cash_line + "\n\n"
        + (
            "Verdict: Momentum v2 clears the TEST gate."
            if ok
            else "Verdict: Momentum v2 does not clear the TEST gate. Stop momentum here; do not tune parameters."
        )
    )
    extra = [
        "",
        "## Iteration 1 — Momentum v2",
        "",
        "Universe: Nifty Next 50 plus the original 5 names (~55 CNC names). Rank 90-day return",
        "minus last-5-day return. Hold top 5 equal weight, rebalance every 21 sessions,",
        "drop names below rank 8. If Nifty 50 close is below its 200-day SMA on a rebalance day,",
        "flatten to cash until it closes back at or above the SMA. Long-only, no leverage.",
        "Same costs and TEST gate. Parameters were not tuned after seeing TEST.",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    extra += [table_line(r) for r in rows]
    extra += ["", cash_line, "", "![Momentum v2 vs Nifty TEST](momentum_v2_test_vs_nifty.png)", "", verdict, ""]
    report = RESULTS / "report.md"
    existing = report.read_text() if report.exists() else ""
    report.write_text(existing.rstrip() + "\n" + "\n".join(extra) + "\n")
    print(verdict)
    print("wrote", report)


if __name__ == "__main__":
    main()
