"""DuckDB reads over the Phase 1 candle store."""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "store" / "candles"


def load(symbol: str, exchange: str = "NSE") -> pd.DataFrame:
    path = STORE / exchange / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    return duckdb.execute(
        "SELECT * FROM read_parquet(?) ORDER BY timestamp",
        [str(path)],
    ).df()


def summary() -> None:
    paths = sorted(STORE.glob("*/*.parquet"))
    if not paths:
        print("no candle files")
        return
    for path in paths:
        exchange = path.parent.name
        symbol = path.stem
        rows, start, end = duckdb.execute(
            """
            SELECT count(*)::BIGINT,
                   min(timestamp),
                   max(timestamp)
            FROM read_parquet(?)
            """,
            [str(path)],
        ).fetchone()
        print(f"{exchange} {symbol}: rows={rows} range={start} -> {end}")


if __name__ == "__main__":
    summary()
