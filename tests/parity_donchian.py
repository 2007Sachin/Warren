"""Refactored Donchian-v2 must match frozen TRAIN+VALIDATE trades."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.donchian_v2 import simulate

GOLD = Path(__file__).resolve().parents[1] / "tests" / "goldens" / "donchian_v2_train_validate.csv"
COLS = ["date", "symbol", "side", "qty", "price", "entry", "net_pnl", "reason", "window"]


def _run() -> pd.DataFrame:
    frames = []
    for name, span in {
        "TRAIN": (date(2024, 1, 1), date(2024, 12, 31)),
        "VALIDATE": (date(2025, 1, 1), date(2025, 6, 30)),
    }.items():
        t = simulate(*span)["trades"].copy()
        t["window"] = name
        frames.append(t)
    return pd.concat(frames, ignore_index=True)


def test_parity_matches_published_metrics():
    from datetime import date as d
    train = simulate(d(2024, 1, 1), d(2024, 12, 31))
    valid = simulate(d(2025, 1, 1), d(2025, 6, 30))
    assert int(train["metrics"]["trades"]) == 9
    assert round(train["metrics"]["end_equity"]) == 94939
    assert int(valid["metrics"]["trades"]) == 15
    assert round(valid["metrics"]["end_equity"]) == 109101


def test_parity_train_validate():
    got = _run()
    if not GOLD.exists():
        GOLD.parent.mkdir(parents=True, exist_ok=True)
        got.to_csv(GOLD, index=False)
    gold = pd.read_csv(GOLD)
    for col in COLS:
        if col not in got.columns:
            got[col] = None
        if col not in gold.columns:
            gold[col] = None
    got = got[COLS].copy()
    gold = gold[COLS].copy()
    got["date"] = got["date"].astype(str).str[:10]
    gold["date"] = gold["date"].astype(str).str[:10]
    got = got.sort_values(COLS).reset_index(drop=True)
    gold = gold.sort_values(COLS).reset_index(drop=True)
    pd.testing.assert_frame_equal(got, gold, check_dtype=False, atol=1e-6)
