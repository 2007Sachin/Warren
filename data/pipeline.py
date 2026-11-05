"""Candle pipeline: daily bars and chunked 15m/5m intraday bars.

Daily files live under data/store/candles/. Intraday files live under
data/store/candles_15m/ and data/store/candles_5m/. Existing files are
updated from the last stored timestamp and deduped.
"""
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.fetch_candles import fetch

DEFAULT_PAUSE = 2.5
# 30s, 90s, 270s — three retries after the first attempt.
RATE_BACKOFFS = (30, 90, 270)

log = logging.getLogger("pipeline")

WATCHLIST = ROOT / "config" / "watchlist.yaml"
STORE_ROOT = ROOT / "data" / "store"
DAILY_STORE = STORE_ROOT / "candles"
IST = ZoneInfo("Asia/Kolkata")
FULL_FROM = "2024-01-01 09:15"
INTRADAY_FROM = datetime(2025, 8, 1, 9, 15)
# getCandleData caps rows per call. 15m ~25 bars/day, 5m ~75.
INTRADAY_WINDOW_DAYS = {"15m": 30, "5m": 10}
EXPECTED_BARS = {"15m": 25, "5m": 75}


def load_watchlist(path: Path = WATCHLIST) -> list[dict]:
    with open(path) as f:
        doc = yaml.safe_load(f)
    symbols = doc.get("symbols") or []
    if not symbols:
        raise RuntimeError(f"No symbols in {path}")
    return symbols


def candle_path(exchange: str, symbol: str, interval: str = "1d") -> Path:
    folder = DAILY_STORE if interval == "1d" else STORE_ROOT / f"candles_{interval}"
    return folder / exchange / f"{symbol}.parquet"


def _from_date(existing: pd.DataFrame | None, full_from: str, *, clock: bool) -> str:
    if existing is None or existing.empty:
        return full_from
    last = pd.to_datetime(existing["timestamp"]).max()
    pattern = "%Y-%m-%d %H:%M" if clock else "%Y-%m-%d 09:15"
    return last.strftime(pattern)


def iter_windows(start: datetime, end: datetime, days: int):
    """Half-open calendar windows [start, start+days), last window ends at `end`."""
    if start >= end:
        return
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        yield cur, nxt
        cur = nxt


def merge(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    df = pd.concat([existing, fresh], ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    return df.sort_values("timestamp").reset_index(drop=True)


def _rate_limited(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "ag8001" in msg or "exceeding access rate" in msg or "invalid token" in msg


def _fetch_with_retry(token: str, exchange: str, symbol: str, interval: str, from_dt: str, to_dt: str):
    last_error = None
    backoffs = list(RATE_BACKOFFS)
    attempt = 0
    while True:
        attempt += 1
        try:
            return fetch(token, exchange, interval, from_dt, to_dt, pause=DEFAULT_PAUSE), None
        except Exception as exc:
            last_error = exc
            if _rate_limited(exc) and backoffs:
                wait = backoffs.pop(0)
                log.warning(
                    "%s %s attempt %d rate-limited (%s); retry in %ss",
                    exchange, symbol, attempt, exc, wait,
                )
                time.sleep(wait)
                continue
            if not _rate_limited(exc) and attempt == 1:
                log.warning("%s %s attempt %d failed: %s", exchange, symbol, attempt, exc)
                time.sleep(DEFAULT_PAUSE)
                continue
            break
    log.error("skipping %s %s after retries: %s", exchange, symbol, last_error)
    return None, last_error


def run(path: Path = WATCHLIST, only: set[str] | None = None) -> list[tuple[str, str]]:
    load_dotenv(ROOT / ".env")
    symbols = load_watchlist(path)
    to_dt = datetime.now(IST).strftime("%Y-%m-%d 15:30")
    failures: list[tuple[str, str]] = []
    log.info("pipeline start: %d symbols, through %s", len(symbols), to_dt)

    for item in symbols:
        symbol = str(item["symbol"])
        if only and symbol not in only:
            continue
        exchange = str(item["exchange"])
        token = str(item["token"])
        dest = candle_path(exchange, symbol, "1d")
        existing = pd.read_parquet(dest) if dest.exists() else None
        from_dt = _from_date(existing, FULL_FROM, clock=False)
        mode = "incremental" if existing is not None else "full"
        log.info("%s %s %s fetch %s -> %s", exchange, symbol, mode, from_dt, to_dt)

        fresh, err = _fetch_with_retry(token, exchange, symbol, "1d", from_dt, to_dt)
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


def _parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


def _write(dest: Path, frame: pd.DataFrame) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(dest, index=False)


def _fetch_symbol_interval(item: dict, interval: str, to_dt: datetime) -> str | None:
    symbol = str(item["symbol"])
    exchange = str(item["exchange"])
    token = str(item["token"])
    dest = candle_path(exchange, symbol, interval)
    existing = pd.read_parquet(dest) if dest.exists() else None
    full_from = INTRADAY_FROM.strftime("%Y-%m-%d %H:%M")
    from_text = _from_date(existing, full_from, clock=True)
    start = _parse_stamp(from_text)
    if start < INTRADAY_FROM:
        start = INTRADAY_FROM
    mode = "incremental" if existing is not None else "full"
    window_days = INTRADAY_WINDOW_DAYS[interval]
    windows = list(iter_windows(start, to_dt, window_days))
    log.info(
        "%s %s %s %s %s -> %s (%d x %d-day windows)",
        exchange, symbol, interval, mode, from_text, to_dt.strftime("%Y-%m-%d %H:%M"),
        len(windows), window_days,
    )
    if not windows:
        log.info("%s %s %s already current", exchange, symbol, interval)
        return None

    acc = existing
    for i, (win_start, win_end) in enumerate(windows, start=1):
        a = win_start.strftime("%Y-%m-%d %H:%M")
        b = win_end.strftime("%Y-%m-%d %H:%M")
        log.info("%s %s %s window %d/%d %s -> %s", exchange, symbol, interval, i, len(windows), a, b)
        fresh, err = _fetch_with_retry(token, exchange, symbol, interval, a, b)
        if fresh is None:
            return f"{exchange}:{symbol}:{interval} {a}->{b}: {err}"
        if fresh.empty:
            log.info("%s %s %s window %d empty", exchange, symbol, interval, i)
            continue
        acc = merge(acc, fresh) if acc is not None else fresh
        _write(dest, acc)
        log.info("%s %s %s rows=%d", exchange, symbol, interval, len(acc))
    return None


def run_intraday(path: Path = WATCHLIST, only: set[str] | None = None,
                 intervals: set[str] | None = None) -> list[tuple[str, str]]:
    load_dotenv(ROOT / ".env")
    symbols = load_watchlist(path)
    to_dt = datetime.now(IST).replace(tzinfo=None, second=0, microsecond=0)
    session_end = to_dt.replace(hour=15, minute=30)
    if to_dt > session_end:
        to_dt = session_end
    failures: list[str] = []
    started = time.perf_counter()
    log.info("intraday pipeline start through %s", to_dt.strftime("%Y-%m-%d %H:%M"))
    for item in symbols:
        symbol = str(item["symbol"])
        if only and symbol not in only:
            continue
        for interval in item.get("intraday") or []:
            if intervals and interval not in intervals:
                continue
            if interval not in INTRADAY_WINDOW_DAYS:
                failures.append(f"{symbol}:{interval}: unsupported interval")
                continue
            err = _fetch_symbol_interval(item, interval, to_dt)
            if err:
                log.error("FAILED %s", err)
                failures.append(err)
    elapsed = time.perf_counter() - started
    log.info("intraday pipeline done: %d failure(s) in %.1fs", len(failures), elapsed)
    print(f"INTRADAY RUNTIME {elapsed:.1f}s")
    return [(f.split(":", 1)[0], f) for f in failures]


def coverage(path: Path = WATCHLIST, only: set[str] | None = None) -> pd.DataFrame:
    """Days whose bar count is not 25 (15m) or 75 (5m), using the daily calendar."""
    rows = []
    for item in load_watchlist(path):
        symbol = str(item["symbol"])
        if only and symbol not in only:
            continue
        exchange = str(item["exchange"])
        daily_path = candle_path(exchange, symbol, "1d")
        if not daily_path.exists():
            continue
        daily = pd.read_parquet(daily_path)
        days = set(pd.to_datetime(daily["timestamp"]).dt.date)
        days = {d for d in days if d >= INTRADAY_FROM.date()}
        for interval in item.get("intraday") or []:
            expected = EXPECTED_BARS.get(interval)
            dest = candle_path(exchange, symbol, interval)
            if not dest.exists():
                for day in sorted(days):
                    rows.append({"symbol": symbol, "interval": interval, "date": str(day), "bars": 0, "expected": expected})
                continue
            frame = pd.read_parquet(dest)
            ts = pd.to_datetime(frame["timestamp"])
            counts = ts.dt.date.value_counts().to_dict()
            for day in sorted(days):
                got = int(counts.get(day, 0))
                if got != expected:
                    rows.append({
                        "symbol": symbol,
                        "interval": interval,
                        "date": str(day),
                        "bars": got,
                        "expected": expected,
                    })
    return pd.DataFrame(rows, columns=["symbol", "interval", "date", "bars", "expected"])


def print_coverage(frame: pd.DataFrame) -> None:
    if frame.empty:
        print("COVERAGE OK: every trading day has 25 x 15m and 75 x 5m bars")
        return
    print(f"COVERAGE GAPS: {len(frame)} symbol-days")
    print(frame.to_string(index=False))


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Fetch watchlist candles")
    parser.add_argument("--symbol", action="append", help="Limit to these watchlist symbols")
    parser.add_argument("--intraday", action="store_true", help="Fetch 15m and 5m bars")
    parser.add_argument("--interval", action="append", help="Limit intraday intervals")
    args = parser.parse_args()
    only = set(args.symbol) if args.symbol else None
    if args.intraday:
        failed = run_intraday(only=only, intervals=set(args.interval) if args.interval else None)
        print_coverage(coverage(only=only))
    else:
        failed = run(only=only)
    sys.exit(1 if failed else 0)
