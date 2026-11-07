from __future__ import annotations

from datetime import date

import pandas as pd

from runtime.report import expired_rate, render_report


def test_expired_row_and_rate_math():
    od = pd.DataFrame([
        {
            "client_tag": "donchian-v2:AAA-EQ:2025-10-06:BUY",
            "symbol": "AAA-EQ",
            "side": "BUY",
            "qty": 10,
            "limit_price": 100.0,
            "status": "EXPIRED",
            "signal_date": "2025-10-06",
            "fill_date": "2025-10-07",
            "fill_price": None,
            "costs_breakdown": '{"expired_open": 103.0, "gap_pct": 0.03}',
        },
        {
            "client_tag": "donchian-v2:BBB-EQ:2025-10-06:BUY",
            "symbol": "BBB-EQ",
            "side": "BUY",
            "qty": 10,
            "limit_price": 50.0,
            "status": "FILLED",
            "signal_date": "2025-10-06",
            "fill_date": "2025-10-07",
            "fill_price": 49.5,
            "costs_breakdown": "{}",
        },
        {
            "client_tag": "donchian-v2:CCC-EQ:2025-10-08:BUY",
            "symbol": "CCC-EQ",
            "side": "BUY",
            "qty": 4,
            "limit_price": 200.0,
            "status": "EXPIRED",
            "signal_date": "2025-10-08",
            "fill_date": "2025-10-09",
            "fill_price": None,
            "costs_breakdown": '{"expired_open": 210.0, "gap_pct": 0.05}',
        },
        {
            "client_tag": "donchian-v2:AAA-EQ:2025-10-09:SELL",
            "symbol": "AAA-EQ",
            "side": "SELL",
            "qty": 10,
            "limit_price": 99.0,
            "status": "EXPIRED",
            "signal_date": "2025-10-09",
            "fill_date": "2025-10-10",
            "fill_price": None,
            "costs_breakdown": '{"expired_open": 90.0, "gap_pct": -0.09}',
        },
    ])
    stats = expired_rate(od, week_end=date(2025, 10, 9))
    assert stats["cum_n"] == 3  # entry BUY only
    assert stats["cum_exp"] == 2
    assert abs(stats["cum_rate"] - 2 / 3) < 1e-9
    assert stats["week_n"] == 3
    assert stats["week_exp"] == 2
    md = render_report(od, pd.DataFrame(), pd.DataFrame(), week_end=date(2025, 10, 9))
    assert "## Expired orders" in md
    assert "AAA-EQ" in md
    assert "103" in md or "103.0" in md
    assert "WARNING" in md  # 66% > 10%
    assert "2/3" in md or "66.7%" in md
