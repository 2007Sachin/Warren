"""Phase 2 walk-forward: daily momentum vs 15m ORB, both after costs vs Nifty."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import vectorbt as vbt

from backtest.loaders import NIFTY, daily_close
from backtest.momentum import nifty_buy_hold, run_windows as run_mom
from backtest.orb import run_windows as run_orb

RESULTS = ROOT / "backtest" / "results"
CAPITAL = 100_000.0

MOM_WINDOWS = {
    "TRAIN": (date(2024, 1, 1), date(2024, 12, 31)),
    "VALIDATE": (date(2025, 1, 1), date(2025, 6, 30)),
    "TEST": (date(2025, 7, 1), date(2026, 11, 5)),
}
ORB_WINDOWS = {
    "VALIDATE": (date(2025, 8, 1), date(2026, 2, 28)),
    "TEST": (date(2026, 3, 1), date(2026, 11, 5)),
}


def _pct(x: float) -> str:
    if x != x or x is None:
        return "n/a"
    if abs(x) == float("inf"):
        return "inf"
    return f"{100.0 * x:.2f}%"


def _num(x: float) -> str:
    if x != x or x is None:
        return "n/a"
    if abs(x) == float("inf"):
        return "inf"
    return f"{x:.2f}"


def plot_equity(series: pd.Series, title: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 4))
    if len(series):
        ax.plot(series.index, series.values, color="#1f4e79")
    ax.set_title(title)
    ax.set_ylabel("Equity (Rs)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def clears_test(strat: dict, bench: dict) -> tuple[bool, list[str]]:
    s, b = strat["metrics"], bench["metrics"]
    reasons = []
    beats = s["cagr"] > b["cagr"]
    reasons.append(f"CAGR { _pct(s['cagr']) } vs Nifty { _pct(b['cagr']) } ({'beats' if beats else 'does not beat'})")
    sharpe_ok = s["sharpe"] > 0.8
    reasons.append(f"Sharpe {s['sharpe']:.2f} {'>' if sharpe_ok else '<='} 0.8")
    dd_ok = s["max_dd"] > -0.20  # less severe than -20%
    reasons.append(f"max DD { _pct(s['max_dd']) } {'<' if dd_ok else '>='} 20%")
    return beats and sharpe_ok and dd_ok, reasons


def row(strategy: str, window: str, metrics: dict) -> dict:
    return {
        "strategy": strategy,
        "window": window,
        "cagr": metrics["cagr"],
        "sharpe": metrics["sharpe"],
        "max_dd": metrics["max_dd"],
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "trades": metrics["trades"],
        "cost_pct_gross": metrics["cost_pct_gross"],
        "end_equity": metrics["end_equity"],
    }


def write_report(rows: list[dict], verdict: str, path: Path) -> None:
    df = pd.DataFrame(rows)
    lines = [
        "# Phase 2 backtest comparison",
        "",
        "Capital Rs 1,00,000. All figures after Angel One cash-market costs",
        "(Rs 20 brokerage per order, STT, stamp, exchange, SEBI, GST, 0.05% slippage).",
        "Only the TEST window decides. Parameters were not tuned after seeing TEST.",
        "",
        "## Windows",
        "",
        "- Momentum TRAIN 2024-01 → 2024-12, VALIDATE 2025-01 → 2025-06, TEST 2025-07 → 2026-11.",
        "- ORB has no TRAIN (15m history starts 2025-08). VALIDATE 2025-08 → 2026-02, TEST 2026-03 → 2026-11.",
        "- ORB skips `backtest_ok=false` days and hard-exits at the 15:00 15-minute bar close.",
        "",
        "## Results",
        "",
        "| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        pf = "inf" if r["profit_factor"] == float("inf") else f"{r['profit_factor']:.2f}"
        lines.append(
            f"| {r['strategy']} | {r['window']} | {_pct(r['cagr'])} | {_num(r['sharpe'])} | "
            f"{_pct(r['max_dd'])} | {_pct(r['win_rate'])} | {pf} | {r['trades']} | "
            f"{r['cost_pct_gross']:.1f}% | {r['end_equity']:.0f} |"
        )
    lines += ["", "## Verdict", "", verdict, ""]
    path.write_text("\n".join(lines))


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    nifty_px = daily_close(NIFTY)
    vbt.Portfolio.from_holding(nifty_px, freq="1D")  # library smoke; verdict uses after-cost engine

    mom = run_mom(MOM_WINDOWS, CAPITAL)
    for name, (start, end) in MOM_WINDOWS.items():
        bench = nifty_buy_hold(start, end, CAPITAL)
        plot_equity(mom[name]["equity"], f"Momentum {name}", RESULTS / f"momentum_{name.lower()}.png")
        plot_equity(bench["equity"], f"Nifty buy-hold {name}", RESULTS / f"nifty_momentum_{name.lower()}.png")
        rows.append(row("momentum", name, mom[name]["metrics"]))
        rows.append(row("nifty", f"momentum-{name}", bench["metrics"]))
        mom[name]["bench"] = bench

    orb = run_orb(ORB_WINDOWS, CAPITAL)
    for name, (start, end) in ORB_WINDOWS.items():
        bench = nifty_buy_hold(start, end, CAPITAL)
        plot_equity(orb[name]["equity"], f"ORB {name}", RESULTS / f"orb_{name.lower()}.png")
        plot_equity(bench["equity"], f"Nifty buy-hold ORB {name}", RESULTS / f"nifty_orb_{name.lower()}.png")
        rows.append(row("orb", name, orb[name]["metrics"]))
        rows.append(row("nifty", f"orb-{name}", bench["metrics"]))
        orb[name]["bench"] = bench

    mom_ok, mom_why = clears_test(mom["TEST"], mom["TEST"]["bench"])
    orb_ok, orb_why = clears_test(orb["TEST"], orb["TEST"]["bench"])

    lines = [
        "Gate: TEST window only — beat Nifty CAGR after costs, Sharpe > 0.8, max DD < 20%.",
        "",
        "Momentum TEST: " + ("PASS. " if mom_ok else "FAIL. ") + "; ".join(mom_why) + ".",
        "ORB TEST: " + ("PASS. " if orb_ok else "FAIL. ") + "; ".join(orb_why) + ".",
        "",
    ]
    if mom_ok and not orb_ok:
        lines.append("Verdict: momentum clears the TEST gate; ORB does not.")
    elif orb_ok and not mom_ok:
        lines.append("Verdict: ORB clears the TEST gate; momentum does not.")
    elif mom_ok and orb_ok:
        lines.append("Verdict: both strategies clear the TEST gate.")
    else:
        lines.append("Verdict: neither strategy clears the TEST gate. A negative result is the result.")
    verdict = "\n".join(lines)
    write_report(rows, verdict, RESULTS / "report.md")
    print(verdict)
    print("wrote", RESULTS / "report.md")


if __name__ == "__main__":
    main()
