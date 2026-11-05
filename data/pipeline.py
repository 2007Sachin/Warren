"""Phase 1 daily candle pipeline.

Reads config/watchlist.yaml, fetches ONE_DAY candles from SmartAPI, and
writes Parquet under data/store/candles/{exchange}/{symbol}.parquet.
Existing files are updated from the last stored timestamp and deduped.
"""
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.fetch_candles import fetch

log = logging.getLogger("pipeline")

WATCHLIST = ROOT / "config" / "watchlist.yaml"
STORE = ROOT / "data" / "store" / "candles"
IST = ZoneInfo("Asia/Kolkata")
FULL_FROM = "2024-01-01 09:15"


def load_watchlist(path: Path = WATCHLIST) -> list[dict]:
    with open(path) as f:
        doc = yaml.safe_load(f)
    symbols = doc.get("symbols") or []
    if not symbols:
        raise RuntimeError(f"No symbols in {path}")
    return symbols


def candle_path(exchange: str, symbol: str) -> Path:
    return STORE / exchange / f"{symbol}.parquet"


def _from_date(existing: pd.DataFrame | None) -> str:
    if existing is None or existing.empty:
        return FULL_FROM
    last = pd.to_datetime(existing["timestamp"]).max()
    return last.strftime("%Y-%m-%d 09:15")


def merge(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    df = pd.concat([existing, fresh], ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    return df.sort_values("timestamp").reset_index(drop=True)


def _fetch_with_retry(token: str, exchange: str, symbol: str, from_dt: str, to_dt: str):
    last_error = None
    for attempt in (1, 2):
        try:
            return fetch(token, exchange, "1d", from_dt, to_dt, pause=1.0), None
        except Exception as exc:
            last_error = exc
            log.warning("%s %s attempt %d failed: %s", exchange, symbol, attempt, exc)
            if attempt == 1:
                # Rate-limit responses need longer than the 1 req/sec pace.
                time.sleep(5.0)
    log.error("skipping %s %s after retry: %s", exchange, symbol, last_error)
    return None, last_error


def run(path: Path = WATCHLIST) -> list[tuple[str, str]]:
    load_dotenv(ROOT / ".env")
    symbols = load_watchlist(path)
    to_dt = datetime.now(IST).strftime("%Y-%m-%d 15:30")
    failures: list[tuple[str, str]] = []
    log.info("pipeline start: %d symbols, through %s", len(symbols), to_dt)

    for item in symbols:
        symbol = str(item["symbol"])
        exchange = str(item["exchange"])
        token = str(item["token"])
        dest = candle_path(exchange, symbol)
        existing = pd.read_parquet(dest) if dest.exists() else None
        from_dt = _from_date(existing)
        mode = "incremental" if existing is not None else "full"
        log.info("%s %s %s fetch %s -> %s", exchange, symbol, mode, from_dt, to_dt)

        fresh, err = _fetch_with_retry(token, exchange, symbol, from_dt, to_dt)
        if fresh is None:
            failures.append((f"{exchange}:{symbol}", str(err)))
            continue

        out = merge(existing, fresh) if existing is not None else fresh
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(dest, index=False)
        log.info("wrote %d rows -> %s", len(out), dest)

    log.info("pipeline done: %d failure(s)", len(failures))
    for name, err in failures:
        log.error("FAILED %s: %s", name, err)
    return failures


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    failed = run()
    sys.exit(1 if failed else 0)
