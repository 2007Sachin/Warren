"""Coverage manifest for intraday candles.

One row per symbol, trading day, and interval. `backtest_ok` is false on
Muhurat 2025-10-21 and on any day missing a bar that starts in 09:15–11:00.
Gaps at 15:15 or later stay true.
"""
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.pipeline import INTRADAY_FROM, candle_path, load_watchlist

MANIFEST = ROOT / "data" / "store" / "coverage_manifest.parquet"
MUHURAT = date(2025, 10, 21)
ORB_START = time(9, 15)
ORB_END = time(11, 0)
CLOSING_GAP_FROM = time(15, 15)
STEPS = {"15m": (15, time(15, 15)), "5m": (5, time(15, 25))}


def expected_starts(interval: str) -> list[time]:
    step, last = STEPS[interval]
    cursor = datetime(2000, 1, 1, 9, 15)
    end = datetime(2000, 1, 1, last.hour, last.minute)
    starts = []
    while cursor <= end:
        starts.append(cursor.time())
        cursor += timedelta(minutes=step)
    return starts


def backtest_ok(day: date, missing: list[time]) -> bool:
    if day == MUHURAT:
        return False
    return not any(ORB_START <= stamp <= ORB_END for stamp in missing)


def build(path: Path | None = None) -> pd.DataFrame:
    rows = []
    for item in load_watchlist():
        symbol = str(item["symbol"])
        exchange = str(item["exchange"])
        daily = pd.read_parquet(candle_path(exchange, symbol, "1d"))
        days = sorted(
            d for d in pd.to_datetime(daily["timestamp"]).dt.date.unique()
            if d >= INTRADAY_FROM.date()
        )
        for interval in item.get("intraday") or []:
            starts = expected_starts(interval)
            dest = candle_path(exchange, symbol, interval)
            present: dict[date, set[time]] = {}
            if dest.exists():
                frame = pd.read_parquet(dest)
                ts = pd.to_datetime(frame["timestamp"])
                for day, grp in ts.groupby(ts.dt.date):
                    present[day] = set(grp.dt.time)
            for day in days:
                have = present.get(day, set())
                missing = [stamp for stamp in starts if stamp not in have]
                rows.append({
                    "symbol": symbol,
                    "exchange": exchange,
                    "date": day.isoformat(),
                    "interval": interval,
                    "expected_bars": len(starts),
                    "actual_bars": len(starts) - len(missing),
                    "missing_bar_starts": [stamp.strftime("%H:%M") for stamp in missing],
                    "backtest_ok": backtest_ok(day, missing),
                })
    return pd.DataFrame(rows)


def summary(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        frame.groupby(["symbol", "interval"], sort=False)["backtest_ok"]
        .agg(days="size", ok="sum")
        .reset_index()
    )
    grouped["pct_backtest_ok"] = (grouped["ok"] / grouped["days"] * 100).round(2)
    return grouped


def write(frame: pd.DataFrame, dest: Path = MANIFEST) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(dest, index=False)
    return dest


def main() -> pd.DataFrame:
    frame = build()
    path = write(frame)
    stats = summary(frame)
    print(f"wrote {len(frame)} rows -> {path}")
    for row in stats.itertuples(index=False):
        print(
            f"{row.symbol} {row.interval}: {int(row.ok)}/{int(row.days)} "
            f"backtest_ok={row.pct_backtest_ok:.2f}%"
        )
    return frame


if __name__ == "__main__":
    main()
