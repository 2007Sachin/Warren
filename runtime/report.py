"""Weekly paper report vs Nifty and vs Donchian-v2 backtest signals."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.donchian_v2 import simulate
from backtest.loaders import NIFTY, daily_close
from paper.ledger import daily_pnl, orders

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _nifty() -> pd.Series:
    try:
        import yfinance as yf
        df = yf.download("^NSEI", progress=False)
        if df is not None and len(df):
            s = df["Close"]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            return s
    except Exception:
        pass
    return daily_close(NIFTY)


def write_weekly(path: Path | None = None) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    dest = path or REPORTS / "weekly.md"
    pnl = daily_pnl()
    od = orders()
    bt = simulate(date(2025, 7, 1), date(2026, 11, 5))
    sig = bt.get("signals", pd.DataFrame())
    defects = []
    live = []
    if not od.empty:
        buys = od[od["side"] == "BUY"]
        for rec in buys.itertuples(index=False):
            d = str(rec.signal_date)[:10]
            live.append((d, rec.symbol))
            if not sig.empty:
                hit = sig[(sig["symbol"] == rec.symbol) & (sig["signal_date"].astype(str).str[:10] == d)]
                if hit.empty:
                    defects.append(f"{d} {rec.symbol} live signal not in backtest set")
    nifty = _nifty()
    lines = ["# Weekly paper report", ""]
    if defects:
        lines += ["## DEFECTS", ""] + [f"- {d}" for d in defects] + [""]
    else:
        lines += ["## DEFECTS", "", "_None._", ""]
    if not pnl.empty:
        eq = pnl.sort_values("date")
        lines += [
            f"Paper equity start {eq.iloc[0]['equity']:.0f} end {eq.iloc[-1]['equity']:.0f}.",
            f"Max drawdown {100.0 * eq['drawdown'].min():.2f}%.",
            "",
        ]
    lines += ["## Paper orders", ""]
    if od.empty:
        lines.append("_No orders._")
    else:
        show = od.tail(40)
        lines.append("| " + " | ".join(show.columns.astype(str)) + " |")
        lines.append("|" + "|".join("---" for _ in show.columns) + "|")
        for rec in show.itertuples(index=False):
            lines.append("| " + " | ".join(str(x) for x in rec) + " |")
    dest.write_text("\n".join(lines) + "\n")
    return dest


if __name__ == "__main__":
    print("wrote", write_weekly())
