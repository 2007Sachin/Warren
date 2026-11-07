"""Fit/evaluate the advisor gate on TRAIN/VALIDATE Donchian-v2 trades."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from agents.laya_advisor import save_mode
from backtest.donchian_v2 import simulate
from backtest.loaders import NIFTY, daily_close

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "store" / "paper" / "laya_labels.csv"
MAJORITY_MARGIN = 0.05


def _regime_label(ret_20d: float | None) -> str:
    if ret_20d is None or (isinstance(ret_20d, float) and np.isnan(ret_20d)):
        return "ranging"
    if ret_20d <= -0.08:
        return "crisis"
    if abs(ret_20d) < 0.02:
        return "ranging"
    if ret_20d > 0.04:
        return "trending"
    return "volatile"


def _rows(window: str, start: date, end: date) -> pd.DataFrame:
    res = simulate(start, end)
    nifty = daily_close(NIFTY).dropna()
    ret20 = nifty.pct_change(20)
    sells = res["round_trips"]
    rows = []
    for rec in sells.itertuples(index=False):
        d = pd.Timestamp(rec.date)
        r20 = float(ret20.loc[d]) if d in ret20.index and pd.notna(ret20.loc[d]) else None
        rows.append({
            "window": window,
            "date": str(rec.date),
            "symbol": rec.symbol,
            "net_pnl": rec.net_pnl,
            "regime": _regime_label(r20),
            "quality": 2 if rec.net_pnl > 0 else 0,
        })
    return pd.DataFrame(rows)


def ece(probs: np.ndarray, y: np.ndarray, n_bins: int = 5) -> float:
    if len(y) == 0:
        return 0.0
    bins = np.linspace(0, 1, n_bins + 1)
    acc = 0.0
    for i in range(n_bins):
        m = (probs >= bins[i]) & (probs < bins[i + 1] if i < n_bins - 1 else probs <= bins[i + 1])
        if not m.any():
            continue
        acc += abs(y[m].mean() - probs[m].mean()) * m.mean()
    return float(acc)


def main() -> None:
    train = _rows("TRAIN", date(2024, 1, 1), date(2024, 12, 31))
    valid = _rows("VALIDATE", date(2025, 1, 1), date(2025, 6, 30))
    labels = pd.concat([train, valid], ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    labels.to_csv(OUT, index=False)
    print(f"wrote {len(labels)} rows -> {OUT}")

    if valid.empty or "regime" not in valid:
        save_mode("log-only", "empty VALIDATE")
        print("VALIDATE empty; advisor mode=log-only")
        return

    majority = valid["regime"].value_counts().idxmax()
    maj_acc = float((valid["regime"] == majority).mean())
    # Mock / unavailable laya: predicted class is TRAIN majority (time-safe).
    train_maj = train["regime"].value_counts().idxmax() if not train.empty else majority
    pred = np.array([train_maj] * len(valid))
    acc = float((pred == valid["regime"].to_numpy()).mean())
    y_bin = (valid["regime"] == train_maj).to_numpy().astype(float)
    probs = np.full(len(valid), y_bin.mean() if len(valid) else 0.5)
    print(f"VALIDATE regime majority={majority} majority_acc={maj_acc:.3f}")
    print(f"VALIDATE regime model_acc={acc:.3f} ECE={ece(probs, y_bin):.3f}")
    q_acc = float((valid["quality"] == 0).mean())  # naive all-lose baseline
    print(f"VALIDATE quality naive_loss_rate={q_acc:.3f}")

    beat = acc >= maj_acc + MAJORITY_MARGIN
    try:
        import laya  # noqa: F401
        have = True
    except Exception:
        have = False
    if not have:
        save_mode("log-only", "laya unavailable; mock abstain")
        print("advisor mode=log-only (laya not installed; mock)")
        return
    if not beat:
        save_mode("log-only", f"acc {acc:.3f} < majority {maj_acc:.3f}+{MAJORITY_MARGIN}")
        print("advisor mode=log-only (VALIDATE regime head did not beat majority by 5 points)")
        return
    save_mode("active", f"acc {acc:.3f} >= {maj_acc + MAJORITY_MARGIN:.3f}")
    print("advisor mode=active")


if __name__ == "__main__":
    main()
