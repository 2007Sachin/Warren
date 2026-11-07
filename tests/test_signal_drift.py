from __future__ import annotations

import pandas as pd

from runtime.report import classify_drift, defects_from_signals, unfilled_from_signals


def test_match_unfilled_missing_statuses():
    bt = pd.DataFrame([
        {"symbol": "AAA-EQ", "entry_date": "2025-10-02", "signal_date": "2025-10-01",
         "entry": 100.0, "exit": 101.0, "qty": 10, "net_pnl": 5.0, "bt_return": 0.005},
        {"symbol": "BBB-EQ", "entry_date": "2025-10-03", "signal_date": "2025-10-02",
         "entry": 50.0, "exit": 49.0, "qty": 8, "net_pnl": -10.0, "bt_return": -0.025},
        {"symbol": "CCC-EQ", "entry_date": "2025-10-04", "signal_date": "2025-10-03",
         "entry": 20.0, "exit": 21.0, "qty": 5, "net_pnl": 4.0, "bt_return": 0.04},
    ])
    paper = pd.DataFrame([
        {"symbol": "AAA-EQ", "side": "BUY", "qty": 3, "limit_price": 101.0, "status": "FILLED",
         "signal_date": "2025-10-01", "fill_date": "2025-10-02", "fill_price": 100.2,
         "costs_breakdown": '{"total": 1.0}'},
        {"symbol": "AAA-EQ", "side": "SELL", "qty": 3, "limit_price": 99.0, "status": "FILLED",
         "signal_date": "2025-10-08", "fill_date": "2025-10-09", "fill_price": 101.0,
         "costs_breakdown": '{"total": 1.0}'},
        {"symbol": "BBB-EQ", "side": "BUY", "qty": 4, "limit_price": 50.5, "status": "EXPIRED",
         "signal_date": "2025-10-02", "fill_date": "2025-10-03", "fill_price": None,
         "costs_breakdown": '{"expired_open": 52.0, "gap_pct": 0.0297}'},
    ])
    drift = classify_drift(bt, paper)
    by = {r.symbol: r.status for r in drift.itertuples(index=False)}
    assert by["AAA-EQ"] == "MATCH"
    assert by["BBB-EQ"] == "UNFILLED-SIGNAL"
    assert by["CCC-EQ"] == "MISSING"

    sigs = pd.DataFrame([
        {"symbol": "AAA-EQ", "signal_date": "2025-10-01"},
        {"symbol": "BBB-EQ", "signal_date": "2025-10-02"},
        {"symbol": "CCC-EQ", "signal_date": "2025-10-03"},
    ])
    unfilled = unfilled_from_signals(sigs, paper)
    assert any("BBB-EQ" in u for u in unfilled)
    assert not any("AAA-EQ" in u for u in unfilled)
    defs = defects_from_signals(sigs, paper)
    assert defs == []
