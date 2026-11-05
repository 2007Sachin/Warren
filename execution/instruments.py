"""Download the Angel One instrument master and index it to Parquet.

The master file is a large daily JSON — download once per day, index locally,
never parse it per-lookup.
"""
import os, io, logging
import pandas as pd
import requests

log = logging.getLogger("instruments")
URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
OUT = "data/store/instruments.parquet"


def refresh() -> pd.DataFrame:
    log.info("Downloading instrument master...")
    df = pd.read_json(io.BytesIO(requests.get(URL, timeout=120).content))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_parquet(OUT, index=False)
    log.info("Saved %d instruments -> %s", len(df), OUT)
    return df


def load() -> pd.DataFrame:
    return pd.read_parquet(OUT)


def find(symbol: str, exchange: str = "NSE") -> pd.DataFrame:
    df = load()
    return df[(df["symbol"].str.contains(symbol, case=False)) & (df["exch_seg"] == exchange)]


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    df = refresh()
    print(df.head())
    print(find("RELIANCE"))
