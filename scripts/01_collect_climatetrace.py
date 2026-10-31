"""Collect solid-waste-disposal CH4 point sources from the public Climate TRACE API.

Climate TRACE is used for (a) an Asia-wide landfill site spine with coordinates and
(b) atmospheric methane emissions (``methane_emitted``). It is NOT methane generated,
collected, flared or utilised, and its ``activity`` figure (tonnes of waste handled) is a
model input, not a metered waste-acceptance record.

API notes (verified 2026-10):
  * Country filters (``gadm_id``, ``countries``, ``iso3``) are silently ignored by
    ``/v7/sources``, so we page the global result set once per year and filter locally.
  * ``limit`` is capped at 10,000 -> must page with ``offset``.
  * Source-level coverage starts in 2021.

Usage:
    python scripts/01_collect_climatetrace.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import INTERIM_CLIMATE, RAW_CLIMATE, START_YEAR

BASE = os.getenv("CLIMATE_TRACE_BASE_URL", "https://api.climatetrace.org/v7").rstrip("/")
INTERIM = INTERIM_CLIMATE
RAW_DIR = RAW_CLIMATE
INTERIM.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "AsiaLandfillResearch/0.1 (academic research)"})

CT_FIRST_YEAR = 2021
END_YEAR = 2025

# Asia (plus a few neighbours kept for LOCO comparisons).
ASIA_ISO3 = {
    "AFG", "BGD", "BTN", "BRN", "KHM", "CHN", "HKG", "IND", "IDN", "JPN",
    "KAZ", "KGZ", "LAO", "LKA", "MAC", "MDV", "MNG", "MMR", "MYS", "NPL",
    "PAK", "PHL", "PRK", "SGP", "THA", "TJK", "TKM", "TLS", "TWN", "UZB",
    "VNM",
}

KEEP = [
    "id", "name", "country", "assetType", "sourceType", "gas", "year",
    "emissionsQuantity", "emissionsFactor", "emissionsFactorUnits",
    "activity", "activityUnits", "capacity", "capacityUnits", "capacityFactor",
    "centroid.latitude", "centroid.longitude",
]


def fetch_year(year: int, page_size: int = 10_000) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            "year": year,
            "gas": "ch4",
            "subsectors": "solid-waste-disposal",
            "limit": page_size,
            "offset": offset,
        }
        r = SESSION.get(f"{BASE}/sources", params=params, timeout=180)
        r.raise_for_status()
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        time.sleep(0.3)
    return rows


def normalize(rows: list[dict], year: int) -> pd.DataFrame:
    df = pd.json_normalize(rows, sep=".")
    for col in KEEP:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[KEEP].rename(columns={
        "id": "climate_trace_source_id",
        "centroid.latitude": "latitude",
        "centroid.longitude": "longitude",
    })
    df["year"] = year
    return df


def _build(rows_by_year: dict[int, list[dict]]) -> None:
    frames = []
    for year in sorted(rows_by_year):
        rows = rows_by_year[year]
        if not rows:
            print(f"{year}: no data (API coverage ends before this year)")
            continue
        df = normalize(rows, year)
        frames.append(df)
        print(f"{year}: {len(rows):,} global rows, {df['country'].isin(ASIA_ISO3).sum():,} in Asia")

    if not frames:
        raise SystemExit("Climate TRACE returned no rows; check API availability.")

    all_df = pd.concat(frames, ignore_index=True)
    all_df.to_csv(INTERIM / "climatetrace_global_solid_waste_ch4.csv", index=False)

    asia = all_df[all_df["country"].isin(ASIA_ISO3)].copy()
    asia["latitude"] = pd.to_numeric(asia["latitude"], errors="coerce")
    asia["longitude"] = pd.to_numeric(asia["longitude"], errors="coerce")
    asia["landfill_id"] = "ct_" + asia["climate_trace_source_id"].astype(str)
    asia = asia.sort_values(["landfill_id", "year"])
    asia.to_csv(INTERIM / "climatetrace_asia_solid_waste_ch4.csv", index=False)

    spans = asia.groupby("landfill_id")["year"].agg(["min", "max", "count"])
    print(f"\nAsia rows: {len(asia):,} | unique sites: {len(spans):,}")
    print(f"sites with coordinates: {asia.drop_duplicates('landfill_id')[['latitude', 'longitude']].notna().all(axis=1).sum():,}")
    print(f"sites with >=3 years: {(spans['count'] >= 3).sum():,}")
    print(asia.groupby("country").size().sort_values(ascending=False).to_string())


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-raw", action="store_true",
                    help="rebuild interim CSVs from cached data/raw/climate JSON (no API calls)")
    args = ap.parse_args()

    years = range(max(CT_FIRST_YEAR, START_YEAR), END_YEAR + 1)
    rows_by_year: dict[int, list[dict]] = {}
    for year in years:
        if args.from_raw:
            cached = RAW_DIR / f"sources_solid_waste_ch4_{year}.json"
            if not cached.exists():
                print(f"{year}: no cached raw file, skipped")
                continue
            rows_by_year[year] = pd.read_json(cached).to_dict("records")
            continue
        rows = fetch_year(year)
        if rows:
            (RAW_DIR / f"sources_solid_waste_ch4_{year}.json").write_text(
                pd.DataFrame(rows).to_json(orient="records"))
        rows_by_year[year] = rows
    _build(rows_by_year)


if __name__ == "__main__":
    main()
