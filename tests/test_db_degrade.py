"""Ledger stays parquet-only when DATABASE_URL is missing or unreachable."""
from __future__ import annotations

import os
from pathlib import Path

from paper.ledger import orders, upsert_order


def test_parquet_only_without_database_url(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    monkeypatch.setenv("PAPER_STORE", str(tmp_path))
    import paper.ledger as ledger
    ledger.STORE = Path(tmp_path)
    import db
    db.close()
    db._warned = False
    created = upsert_order({
        "client_tag": "parquet-only:AAA-EQ:2025-10-01:BUY",
        "symbol": "AAA-EQ",
        "side": "BUY",
        "qty": 1,
        "limit_price": 10.0,
        "status": "PENDING",
        "signal_date": "2025-10-01",
    })
    assert created is True
    assert len(orders()) == 1
    again = upsert_order({
        "client_tag": "parquet-only:AAA-EQ:2025-10-01:BUY",
        "symbol": "AAA-EQ",
        "side": "BUY",
        "qty": 1,
        "limit_price": 10.0,
        "status": "FILLED",
        "signal_date": "2025-10-01",
        "fill_date": "2025-10-02",
        "fill_price": 9.9,
    })
    assert again is False
    assert str(orders().iloc[0]["status"]) == "FILLED"
