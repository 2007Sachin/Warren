"""Drift report must not compare paper vs backtest equity."""
from __future__ import annotations

import pandas as pd

from runtime.report import classify_drift, render_report


def test_report_does_not_compare_equity():
    bt = pd.DataFrame([
        {"symbol": "AAA-EQ", "entry_date": "2025-10-02", "signal_date": "2025-10-01",
         "entry": 100.0, "exit": 101.0, "qty": 10, "net_pnl": 5.0, "bt_return": 0.005},
    ])
    paper = pd.DataFrame([
        {"symbol": "AAA-EQ", "side": "BUY", "qty": 3, "limit_price": 101.0, "status": "FILLED",
         "signal_date": "2025-10-01", "fill_date": "2025-10-02", "fill_price": 100.2,
         "costs_breakdown": '{"total": 1.0}'},
        {"symbol": "AAA-EQ", "side": "SELL", "qty": 3, "limit_price": 99.0, "status": "FILLED",
         "signal_date": "2025-10-08", "fill_date": "2025-10-09", "fill_price": 101.0,
         "costs_breakdown": '{"total": 1.0}'},
    ])
    md = render_report(paper, bt, pd.DataFrame([{"symbol": "AAA-EQ", "signal_date": "2025-10-01"}]))
    assert "equity" not in md.lower() or "not compared" in md.lower()
    assert "daily P&L are not compared" in md
    drift = classify_drift(bt, paper)
    assert "equity" not in drift.columns
    assert list(drift["status"]) == ["MATCH"]
