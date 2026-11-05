"""One-time rewrite of candle Parquet files to tz-naive IST wall-clock."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.fetch_candles import normalize_timestamps

STORE = ROOT / "data" / "store" / "candles"


def migrate(store: Path = STORE) -> int:
    paths = sorted(store.glob("*/*.parquet"))
    for path in paths:
        df = pd.read_parquet(path)
        before = df["timestamp"].dtype
        df["timestamp"] = normalize_timestamps(df["timestamp"])
        df.to_parquet(path, index=False)
        print(f"{path.relative_to(ROOT)}: {before} -> {df['timestamp'].dtype} "
              f"({df['timestamp'].min()} .. {df['timestamp'].max()})")
    return len(paths)


if __name__ == "__main__":
    n = migrate()
    print(f"migrated {n} files")
