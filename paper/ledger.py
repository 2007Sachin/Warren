"""Paper ledger: parquet always; Neon when DATABASE_URL is reachable."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(os.environ.get("PAPER_STORE", ROOT / "data" / "store" / "paper"))


def _path(name: str) -> Path:
    STORE.mkdir(parents=True, exist_ok=True)
    return STORE / f"{name}.parquet"


def _read(name: str) -> pd.DataFrame:
    dest = _path(name)
    if not dest.exists():
        return pd.DataFrame()
    return pd.read_parquet(dest)


def _write(name: str, df: pd.DataFrame) -> None:
    df.to_parquet(_path(name), index=False)


def _serialize(row: dict) -> dict:
    out = dict(row)
    if isinstance(out.get("costs_breakdown"), dict):
        out["costs_breakdown"] = json.dumps(out["costs_breakdown"])
    for k in ("signal_date", "fill_date", "opened_at", "date"):
        if k in out and out[k] is not None and not isinstance(out[k], str):
            out[k] = str(out[k])
    return out


def upsert_order(row: dict) -> bool:
    """Insert by client_tag. Returns True if a new row was written."""
    orders = _read("paper_orders")
    tag = row["client_tag"]
    if not orders.empty and tag in set(orders["client_tag"].astype(str)):
        mask = orders["client_tag"].astype(str) == tag
        for k, v in row.items():
            if k == "costs_breakdown" and isinstance(v, dict):
                orders.loc[mask, k] = json.dumps(v)
            else:
                orders.loc[mask, k] = v
        _write("paper_orders", orders)
        from db import upsert_paper_order
        upsert_paper_order(row)
        return False
    add = pd.DataFrame([_serialize(row)])
    out = pd.concat([orders, add], ignore_index=True) if not orders.empty else add
    _write("paper_orders", out)
    from db import upsert_paper_order
    upsert_paper_order(row)
    return True


def set_position(row: dict) -> None:
    pos = _read("paper_positions")
    if pos.empty:
        pos = pd.DataFrame(columns=["symbol", "qty", "avg_price", "stop_price", "opened_at", "client_tag"])
    pos = pos[pos["symbol"] != row["symbol"]]
    if int(row.get("qty") or 0) > 0:
        pos = pd.concat([pos, pd.DataFrame([_serialize(row)])], ignore_index=True)
    _write("paper_positions", pos)
    from db import upsert_paper_position
    upsert_paper_position(row)


def upsert_daily_pnl(row: dict) -> bool:
    pnl = _read("paper_daily_pnl")
    day = str(row["date"])
    payload = _serialize(row)
    if not pnl.empty and day in set(pnl["date"].astype(str)):
        return False
    add = pd.DataFrame([payload])
    out = pd.concat([pnl, add], ignore_index=True) if not pnl.empty else add
    _write("paper_daily_pnl", out)
    from db import upsert_paper_daily_pnl
    upsert_paper_daily_pnl(row)
    return True


def append_vote(row: dict) -> None:
    votes = _read("advisor_votes")
    add = pd.DataFrame([_serialize(row)])
    out = pd.concat([votes, add], ignore_index=True) if not votes.empty else add
    _write("advisor_votes", out)
    from db import insert_advisor_vote
    insert_advisor_vote(row)


def positions() -> pd.DataFrame:
    return _read("paper_positions")


def orders() -> pd.DataFrame:
    return _read("paper_orders")


def daily_pnl() -> pd.DataFrame:
    return _read("paper_daily_pnl")


def equity_start(capital: float = 100_000.0) -> float:
    pnl = daily_pnl()
    if pnl.empty:
        return capital
    return float(pnl.sort_values("date").iloc[-1]["equity"])


def peak_equity(capital: float = 100_000.0) -> float:
    pnl = daily_pnl()
    if pnl.empty:
        return capital
    return float(max(capital, pnl["equity"].max()))
