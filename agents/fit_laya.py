"""Fit/evaluate the advisor gate on TRAIN/VALIDATE Donchian-v2 trades."""
from __future__ import annotations

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
REGIME_Q = {
    "regime": {
        "type": "choice",
        "instructions": "Classify the Indian cash-equity regime from the features.",
        "criteria": {
            "trending": "Persistent directional move; 20-day return is large and breadth agrees.",
            "ranging": "Choppy market; 20-day return is small.",
            "volatile": "Two-way swings without a clean trend.",
            "crisis": "Sharp drawdown or stress.",
        },
    }
}


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
            "ret_20d": r20,
            "regime": _regime_label(r20),
            "quality": 2 if rec.net_pnl > 0 else 0,
        })
    return pd.DataFrame(rows)


def ece(conf: np.ndarray, correct: np.ndarray, n_bins: int = 5) -> float:
    if len(correct) == 0:
        return 0.0
    bins = np.linspace(0, 1, n_bins + 1)
    acc = 0.0
    for i in range(n_bins):
        hi = bins[i + 1]
        m = (conf >= bins[i]) & ((conf < hi) if i < n_bins - 1 else (conf <= hi))
        if not m.any():
            continue
        acc += abs(correct[m].mean() - conf[m].mean()) * m.mean()
    return float(acc)


def _predict_regimes(agent, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    preds, confs = [], []
    for rec in frame.itertuples(index=False):
        state = {"ret_20d": rec.ret_20d, "symbol": rec.symbol, "date": rec.date}
        out = agent.predict(state, REGIME_Q)
        ans = (out.get("answers") or {}).get("regime") or {}
        preds.append(ans.get("choice") or "ranging")
        confs.append(float(ans.get("answer_confidence") or ans.get("confidence") or 0.0))
    return np.array(preds), np.array(confs)


def _metrics(y: np.ndarray, pred: np.ndarray, conf: np.ndarray) -> dict:
    acc = float((pred == y).mean()) if len(y) else 0.0
    return {"acc": acc, "ece": ece(conf, (pred == y).astype(float))}


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
    print(f"VALIDATE regime majority={majority} majority_acc={maj_acc:.3f}")

    try:
        from laya import Agent
        agent = Agent(device="cpu", compile=False)
        tr_pred, tr_conf = _predict_regimes(agent, train) if not train.empty else (np.array([]), np.array([]))
        va_pred, va_conf = _predict_regimes(agent, valid)
        tr = _metrics(train["regime"].to_numpy(), tr_pred, tr_conf) if len(tr_pred) else {"acc": 0.0, "ece": 0.0}
        va = _metrics(valid["regime"].to_numpy(), va_pred, va_conf)
        print(f"TRAIN  regime model_acc={tr['acc']:.3f} ECE={tr['ece']:.3f} (real laya Agent)")
        print(f"VALIDATE regime model_acc={va['acc']:.3f} ECE={va['ece']:.3f} (real laya Agent)")
        acc = va["acc"]
        have = True
    except Exception as exc:
        have = False
        train_maj = train["regime"].value_counts().idxmax() if not train.empty else majority
        pred = np.array([train_maj] * len(valid))
        acc = float((pred == valid["regime"].to_numpy()).mean())
        print(f"VALIDATE regime model_acc={acc:.3f} ECE=n/a")
        print(f"laya Agent failed: {type(exc).__name__}: {exc}")
        save_mode("log-only", f"laya Agent failed: {exc}")
        print("advisor mode=log-only (install/runtime error)")
        return

    beat = acc >= maj_acc + MAJORITY_MARGIN
    if not have:
        save_mode("log-only", "laya unavailable")
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
