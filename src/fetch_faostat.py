from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from src.config import (
    RAW_DIR,
    PROCESSED_DIR,
    PRODUCTION_ZIP_URL,
    TRADE_ZIP_URL,
    COMMODITIES,
    START_YEAR,
    END_YEAR,
)


# Download helper
def download_zip(url: str, save_as: Path) -> Path:
    """
    Downloads a large zip file from FAOSTAT bulk downloads.

    Why headers?
    Some FAO bulk endpoints redirect to a newer domain that blocks
    requests without a browser-like User-Agent (403 Forbidden).
    """
    save_as.parent.mkdir(parents=True, exist_ok=True)

    if save_as.exists() and save_as.stat().st_size > 0:
        print(f"[SKIP] Already exists: {save_as.name}")
        return save_as

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "*/*",
        "Referer": "https://www.fao.org/faostat/",
    }

    print(f"[DOWNLOAD] {url}")
    with requests.get(url, stream=True, timeout=60, headers=headers, allow_redirects=True) as r:
        r.raise_for_status()
        with open(save_as, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    print(f"[OK] Saved: {save_as}")
    return save_as


# Find main CSV inside the zip
def find_main_csv(zf: zipfile.ZipFile) -> str:
    """
    FAOSTAT bulk zip contains several files.
    The main dataset is the largest CSV file.
    """
    csv_files = [name for name in zf.namelist() if name.lower().endswith(".csv")]
    if not csv_files:
        raise ValueError("No CSV found inside the zip file.")

    # pick the CSV with the largest size
    csv_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
    return csv_files[0]


# Read zip CSV in chunks & filter early
def read_filtered_chunks(zip_path: Path, keep_elements: list[str]) -> pd.DataFrame:
    """
    Reads the big normalized FAOSTAT CSV inside the zip in chunks.

    For each chunk, we filter:
      - Year range
      - Item in COMMODITIES
      - Element in keep_elements

    Then we append only the filtered rows.
    """
    collected = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        csv_name = find_main_csv(zf)
        print(f"[READ] {zip_path.name} -> {csv_name}")

        with zf.open(csv_name) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")

            for chunk in pd.read_csv(text, chunksize=300_000):
                # filter years
                chunk = chunk[(chunk["Year"] >= START_YEAR) & (chunk["Year"] <= END_YEAR)]

                # filter commodities
                chunk = chunk[chunk["Item"].isin(COMMODITIES)]

                # filter elements (Production, Import Quantity, Export Quantity)
                chunk = chunk[chunk["Element"].isin(keep_elements)]

                if not chunk.empty:
                    collected.append(chunk)

    if not collected:
        return pd.DataFrame()

    return pd.concat(collected, ignore_index=True)


# Production pipeline
def fetch_production() -> pd.DataFrame:
    """
    Produces a clean production dataset with country, country_code, commodity, commodity_code, year, production_qty
    """
    zip_path = RAW_DIR / "production.zip"
    download_zip(PRODUCTION_ZIP_URL, zip_path)

    df = read_filtered_chunks(zip_path, keep_elements=["Production"])
    if df.empty:
        raise RuntimeError("Production data came back empty. Commodity names may not match.")

    df = df.rename(
        columns={
            "Area": "country",
            "Area Code": "country_code",
            "Item": "commodity",
            "Item Code": "commodity_code",
            "Year": "year",
            "Value": "production_qty",
        }
    )

    keep_cols = ["country", "country_code", "commodity", "commodity_code", "year", "production_qty"]
    return df[keep_cols].copy()


# Trade pipeline (imports & exports)
def fetch_trade() -> pd.DataFrame:
    """
    Produces a trade dataset with country, commodity, year, import_qty, export_qty
    """
    zip_path = RAW_DIR / "trade.zip"
    download_zip(TRADE_ZIP_URL, zip_path)

    df = read_filtered_chunks(zip_path, keep_elements=["Import quantity", "Export quantity"])
    if df.empty:
        raise RuntimeError("Trade data came back empty. Commodity names may not match.")

    df = df.rename(
        columns={
            "Area": "country",
            "Area Code": "country_code",
            "Item": "commodity",
            "Item Code": "commodity_code",
            "Year": "year",
            "Element": "element",
            "Value": "trade_qty",
        }
    )

    # Convert long to wide, one column for imports, one for exports
    pivot = (
        df.pivot_table(
            index=["country", "country_code", "commodity", "commodity_code", "year"],
            columns="element",
            values="trade_qty",
            aggfunc="sum",
        )
        .reset_index()
    )
    pivot = pivot.rename(
        columns={
            "Import quantity": "import_qty",
            "Export quantity": "export_qty",
        }
    )


    # If missing, treat as 0
    pivot["import_qty"] = pivot["import_qty"].fillna(0)
    pivot["export_qty"] = pivot["export_qty"].fillna(0)

    return pivot


# Save outputs
def run():
    """
    Runs the whole ingestion:
      - fetch filtered production
      - fetch filtered trade
      - save both to data/processed
    """
    prod = fetch_production()
    trade = fetch_trade()

    prod_out = PROCESSED_DIR / "production_filtered.parquet"
    trade_out = PROCESSED_DIR / "trade_filtered.parquet"

    prod.to_parquet(prod_out, index=False)
    trade.to_parquet(trade_out, index=False)

    print(f"[SAVE] {prod_out}")
    print(f"[SAVE] {trade_out}")


if __name__ == "__main__":
    run()