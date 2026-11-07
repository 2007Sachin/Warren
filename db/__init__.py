"""Pooled Neon Postgres helper. Never raises into the trading loop."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("warren.db")
_warned = False
_conn = None

CONNECT_TIMEOUT = 5


def database_url_set() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


def _dsn() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    return url or None


def _warn_once(exc: BaseException) -> None:
    global _warned
    if _warned:
        return
    _warned = True
    log.warning("Neon unreachable; Parquet-only (%s)", type(exc).__name__)


def close() -> None:
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


def _connect():
    global _conn
    dsn = _dsn()
    if not dsn:
        return None
    if _conn is not None and not _conn.closed:
        return _conn
    try:
        import psycopg
        _conn = psycopg.connect(dsn, connect_timeout=CONNECT_TIMEOUT, autocommit=True)
        return _conn
    except Exception as exc:
        _conn = None
        _warn_once(exc)
        return None


def execute(sql: str, params: tuple | list | dict | None = None) -> list[tuple] | None:
    """Run SQL on the pooled URL. Returns rows, [] for no rows, or None if degraded."""
    conn = _connect()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            return cur.fetchall()
    except Exception as exc:
        close()
        _warn_once(exc)
        return None


def available() -> bool:
    if not database_url_set():
        return False
    rows = execute("select 1")
    return rows is not None


def _jsonb(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        from psycopg.types.json import Jsonb
        return Jsonb(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            from psycopg.types.json import Jsonb
            return Jsonb(parsed)
        except Exception:
            return value
    return value


def upsert_paper_order(row: dict) -> None:
    execute(
        """
        insert into paper_orders (
          client_tag, symbol, side, qty, limit_price, status,
          signal_date, fill_date, fill_price, costs_breakdown
        ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (client_tag) do update set
          status = excluded.status,
          fill_date = excluded.fill_date,
          fill_price = excluded.fill_price,
          costs_breakdown = excluded.costs_breakdown,
          qty = excluded.qty,
          limit_price = excluded.limit_price
        """,
        (
            row.get("client_tag"),
            row.get("symbol"),
            str(row.get("side") or "").upper(),
            int(row.get("qty") or 0),
            row.get("limit_price"),
            row.get("status") or "PENDING",
            row.get("signal_date"),
            row.get("fill_date"),
            row.get("fill_price"),
            _jsonb(row.get("costs_breakdown")),
        ),
    )


def upsert_paper_position(row: dict) -> None:
    qty = int(row.get("qty") or 0)
    if qty <= 0:
        execute("delete from paper_positions where symbol = %s", (row.get("symbol"),))
        return
    execute(
        """
        insert into paper_positions (symbol, qty, avg_price, stop_price, opened_at, client_tag)
        values (%s,%s,%s,%s,%s,%s)
        on conflict (symbol) do update set
          qty = excluded.qty,
          avg_price = excluded.avg_price,
          stop_price = excluded.stop_price,
          opened_at = excluded.opened_at,
          client_tag = excluded.client_tag
        """,
        (
            row.get("symbol"), qty, row.get("avg_price") or row.get("avg"),
            row.get("stop_price"), row.get("opened_at"), row.get("client_tag"),
        ),
    )


def upsert_paper_daily_pnl(row: dict) -> None:
    execute(
        """
        insert into paper_daily_pnl (date, realized, unrealized, equity, drawdown)
        values (%s,%s,%s,%s,%s)
        on conflict (date) do nothing
        """,
        (
            row.get("date"),
            row.get("realized") or 0,
            row.get("unrealized") or 0,
            row.get("equity"),
            row.get("drawdown") or 0,
        ),
    )


def insert_advisor_vote(row: dict) -> None:
    payload = row.get("payload")
    execute(
        """
        insert into advisor_votes (ts, advisor, vote_type, payload, acted_on)
        values (coalesce(%s::timestamptz, now()), %s, %s, %s, %s)
        """,
        (
            row.get("ts"),
            row.get("advisor") or "laya",
            row.get("vote_type"),
            _jsonb(payload),
            bool(row.get("acted_on")),
        ),
    )


def paper_order_count() -> int | None:
    rows = execute("select count(*) from paper_orders")
    if rows is None:
        return None
    return int(rows[0][0])
