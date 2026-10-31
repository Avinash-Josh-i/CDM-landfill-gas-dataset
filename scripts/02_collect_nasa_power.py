"""Fetch climate features from NASA POWER for each landfill coordinate.

Safety rules
------------
- **1984 floor rule**: NASA POWER satellite-era coverage starts ~1984. Never query
  before 1984; for sites opened before 1984 we clip start to max(opening_year, 1984).
  If opening_year is missing or < 1984 we still clip to 1984.
- **Monthly export**: Write both ``data/interim/climate/climate_monthly.csv`` (site-year-month)
  and ``data/interim/climate/nasa_power_annual.csv`` (aggregated).

Usage
-----
    python scripts/02_collect_nasa_power.py
    python scripts/02_collect_nasa_power.py --sites data/processed/sites.csv
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import END_YEAR, INTERIM_CLIMATE, PROCESSED, RAW_CLIMATE, START_YEAR

BASE = "https://power.larc.nasa.gov/api/temporal/monthly/point"
CACHE = RAW_CLIMATE / "nasa_power"
CACHE.mkdir(parents=True, exist_ok=True)
INTERIM_CLIMATE.mkdir(parents=True, exist_ok=True)
OUT_ANNUAL = INTERIM_CLIMATE / "nasa_power_annual.csv"
OUT_MONTHLY = INTERIM_CLIMATE / "climate_monthly.csv"
FILL = -999.0
POWER_EARLIEST = 1984


SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "AsiaLandfillResearch/0.1 (academic research)"})


def site_key(lat: float, lon: float) -> str:
    return hashlib.sha1(f"{float(lat):.5f},{float(lon):.5f}".encode()).hexdigest()[:16]


def clip_years(opening_year):
    start = int(START_YEAR)
    if opening_year is not None and not (isinstance(opening_year, float) and np.isnan(opening_year)):
        try:
            oy = int(opening_year)
            if oy > start:
                start = oy
        except Exception:
            pass
    start = max(start, POWER_EARLIEST)
    end = int(END_YEAR)
    if start > end:
        start = end
    return start, end


def request_power(lat: float, lon: float, start_year: int, end_year: int,
                  precip_param: str = "PRECTOTCORR") -> dict:
    params = {
        "parameters": f"T2M,RH2M,{precip_param}",
        "community": "AG",
        "longitude": round(float(lon), 5),
        "latitude": round(float(lat), 5),
        "start": str(start_year),
        "end": str(end_year),
        "format": "JSON",
    }
    r = SESSION.get(BASE, params=params, timeout=120)
    r.raise_for_status()
    payload = r.json()
    if "properties" not in payload:
        raise ValueError(f"unexpected POWER response: {str(payload)[:200]}")
    return payload


def values(payload: dict, param: str) -> dict:
    return payload.get("properties", {}).get("parameter", {}).get(param, {}) or {}


def extract_monthly(payload: dict, precip_param: str, landfill_id: str,
                    lat: float, lon: float) -> pd.DataFrame:
    t2m = values(payload, "T2M")
    rh = values(payload, "RH2M")
    pr = values(payload, precip_param)
    months = sorted({k for k in set(t2m) | set(rh) | set(pr) if len(k) == 6 and k.isdigit()})

    rows = []
    for key in months:
        year, month = int(key[:4]), int(key[4:])
        if not (1 <= month <= 12):
            continue
        days = calendar.monthrange(year, month)[1]
        tv = t2m.get(key)
        rv = rh.get(key)
        pv = pr.get(key)
        rows.append({
            "landfill_id": landfill_id,
            "year": year,
            "month": month,
            "days_in_month": days,
            "latitude": lat,
            "longitude": lon,
            "temperature_c": float(tv) if tv is not None and float(tv) > FILL + 1 else np.nan,
            "relative_humidity_pct": float(rv) if rv is not None and float(rv) > FILL + 1 else np.nan,
            "precipitation_mm_day": float(pv) if pv is not None and float(pv) > FILL + 1 else np.nan,
            "precipitation_mm_month": float(pv) * days if pv is not None and float(pv) > FILL + 1 else np.nan,
            "climate_source": f"NASA POWER monthly API ({precip_param})",
        })
    return pd.DataFrame(rows)


def aggregate_monthly(monthly_df: pd.DataFrame, landfill_id: str,
                      lat: float, lon: float, precip_param: str) -> pd.DataFrame:
    if monthly_df.empty:
        return pd.DataFrame()
    rows = []
    for year, g in monthly_df.groupby("year"):
        tvals = g["temperature_c"].dropna()
        hvals = g["relative_humidity_pct"].dropna()
        pvals = g["precipitation_mm_month"].dropna()
        rows.append({
            "landfill_id": landfill_id,
            "year": int(year),
            "latitude": lat,
            "longitude": lon,
            "temperature": float(tvals.mean()) if len(tvals) else np.nan,
            "humidity": float(hvals.mean()) if len(hvals) else np.nan,
            "precipitation": float(pvals.sum()) if len(pvals) else np.nan,
            "n_months": int(len(g[g["temperature_c"].notna()]) or len(tvals)),
            "climate_source": f"NASA POWER monthly API ({precip_param})",
        })
    return pd.DataFrame(rows)


def load_sites(sites_path: str | None) -> pd.DataFrame:
    candidates = []
    if sites_path:
        candidates.append(Path(sites_path))
    candidates += [
        INTERIM_CLIMATE / "site_coordinates.csv",
        PROCESSED / "sites.csv",
        INTERIM_CLIMATE / "climatetrace_asia_solid_waste_ch4.csv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if not {"latitude", "longitude"}.issubset(df.columns):
            continue
        if "landfill_id" not in df.columns:
            if "climate_trace_source_id" in df.columns:
                df["landfill_id"] = "ct_" + df["climate_trace_source_id"].astype(str)
            else:
                df["landfill_id"] = [f"site_{i}" for i in range(len(df))]
        df = df.dropna(subset=["latitude", "longitude"])
        df = df[(df["latitude"].between(-90, 90)) & (df["longitude"].between(-180, 180))]
        keep = ["landfill_id", "latitude", "longitude"]
        if "opening_year" in df.columns:
            keep.append("opening_year")
        out = df[keep].drop_duplicates("landfill_id")
        if len(out):
            print(f"sites: {path} ({len(out)} with coordinates)")
            return out
    raise SystemExit("No site-coordinate file found. Run `14_build_repository.py coords` first.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", help="CSV with landfill_id, latitude, longitude")
    ap.add_argument("--limit", type=int, help="only fetch the first N sites")
    args = ap.parse_args()

    sites = load_sites(args.sites)
    if args.limit:
        sites = sites.head(args.limit)

    all_annual = []
    all_monthly = []
    failures = []
    for i, r in sites.reset_index(drop=True).iterrows():
        lat, lon = float(r.latitude), float(r.longitude)
        oy = r.get("opening_year") if "opening_year" in sites.columns else None
        start_year, end_year = clip_years(oy)
        key = site_key(lat, lon)
        cache_file = CACHE / f"{key}_{start_year}_{end_year}.json"
        precip = "PRECTOTCORR"
        if cache_file.exists():
            payload = json.loads(cache_file.read_text())
            precip = payload.get("_precip_param", precip)
        else:
            try:
                payload = request_power(lat, lon, start_year, end_year, precip)
                if not values(payload, precip):
                    raise ValueError("PRECTOTCORR missing")
            except Exception as exc:
                precip = "PRECTOT"
                try:
                    payload = request_power(lat, lon, start_year, end_year, precip)
                except Exception as exc2:
                    failures.append((r.landfill_id, f"{type(exc2).__name__}: {exc2}"))
                    print(f"{i+1}/{len(sites)} {r.landfill_id} FAILED")
                    continue
            payload["_precip_param"] = precip
            payload["_start_year"] = start_year
            payload["_end_year"] = end_year
            cache_file.write_text(json.dumps(payload))
            time.sleep(0.25)

        monthly = extract_monthly(payload, precip, str(r.landfill_id), lat, lon)
        if not monthly.empty:
            all_monthly.append(monthly)
        annual = aggregate_monthly(monthly, str(r.landfill_id), lat, lon, precip)
        if not annual.empty:
            all_annual.append(annual)
        print(f"{i+1}/{len(sites)} {r.landfill_id} ({len(monthly)} months, {len(annual)} years, start={start_year})")

    if all_monthly:
        out_m = pd.concat(all_monthly, ignore_index=True).sort_values(["landfill_id", "year", "month"])
        out_m.to_csv(OUT_MONTHLY, index=False)
        print(f"\nwrote {OUT_MONTHLY} ({len(out_m)} rows, {out_m['landfill_id'].nunique()} sites)")
    if all_annual:
        out_a = pd.concat(all_annual, ignore_index=True).sort_values(["landfill_id", "year"])
        out_a.to_csv(OUT_ANNUAL, index=False)
        print(f"wrote {OUT_ANNUAL} ({len(out_a)} site-years, {out_a['landfill_id'].nunique()} sites)")
    else:
        print("No climate rows collected.")
    if failures:
        print(f"{len(failures)} sites failed:")
        for site, msg in failures[:20]:
            print(f"  {site}: {msg}")


if __name__ == "__main__":
    main()
