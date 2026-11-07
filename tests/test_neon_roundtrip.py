"""Live Neon round-trip. Skips when DATABASE_URL is unset."""
from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip(),
    reason="DATABASE_URL unset",
)


def test_paper_order_roundtrip_and_append_only():
    from db import execute, upsert_paper_order

    tag = f"test-neon:{uuid.uuid4()}"
    row = {
        "client_tag": tag,
        "symbol": "TEST-EQ",
        "side": "BUY",
        "qty": 3,
        "limit_price": 100.5,
        "status": "PENDING",
        "signal_date": "2025-10-01",
        "fill_date": None,
        "fill_price": None,
        "costs_breakdown": {"note": "roundtrip"},
    }
    upsert_paper_order(row)
    got = execute(
        "select client_tag, symbol, side, qty, limit_price::float, status from paper_orders where client_tag = %s",
        (tag,),
    )
    assert got is not None
    assert len(got) == 1
    assert got[0][0] == tag
    assert got[0][1] == "TEST-EQ"
    assert got[0][2] == "BUY"
    assert int(got[0][3]) == 3
    assert abs(float(got[0][4]) - 100.5) < 1e-9
    assert got[0][5] == "PENDING"

    upsert_paper_order(row)
    again = execute("select count(*) from paper_orders where client_tag = %s", (tag,))
    assert again is not None
    assert int(again[0][0]) == 1

    execute(
        "insert into advisor_votes (advisor, vote_type, payload, acted_on) values (%s,%s,%s,%s)",
        ("test", "roundtrip", None, False),
    )
    ids = execute("select id from advisor_votes where advisor = %s order by id desc limit 1", ("test",))
    assert ids is not None and ids
    vid = ids[0][0]
    import psycopg

    dsn = os.environ["DATABASE_URL"]
    denied = False
    with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("update advisor_votes set acted_on = true where id = %s", (vid,))
            except psycopg.errors.InsufficientPrivilege:
                denied = True
            except psycopg.Error as exc:
                denied = exc.sqlstate == "42501" or "append-only" in str(exc)
    assert denied, "advisor_votes UPDATE must be denied"

    print("round-trip: insert ok, idempotent upsert ok, advisor_votes UPDATE denied")
