"""Build the site table and landfill-year master table from all collected sources.

Design rules
------------
* Never fabricate a value. Absent stays absent (NaN) with an explicit source column.
* ``methane_generated/collected/flared/utilised/emitted`` stay separate.
* Cumulative waste is only summed over years that are actually present, and every row
  carries ``cumulative_is_complete`` so FOD fitting can drop incomplete series.
* Climate TRACE ``activity`` is modelled waste throughput, so it lands in
  ``waste_accepted_tonnes`` only with ``waste_accepted_source = 'climate_trace_modelled'``
  and ``is_modelled = True``.

Outputs
-------
data/processed/asia_landfill_sites.csv     one row per site
data/processed/asia_landfill_master.csv    one row per site-year

Usage:
    python scripts/03_build_master.py
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA, INTERIM, INTERIM_CLIMATE, MASTER_COLUMNS, PROCESSED

PROCESSED.mkdir(parents=True, exist_ok=True)
CDM = DATA / "interim" / "cdm"


def slug_id(country, name, city=""):
    raw = f"{country}|{name}|{city}".strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")[:60]
    digest = hashlib.sha1(raw.encode()).hexdigest()[:8]
    return f"{slug}_{digest}"


def load_climatetrace() -> pd.DataFrame:
    p = INTERIM_CLIMATE / "climatetrace_asia_solid_waste_ch4.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    out = pd.DataFrame({
        "landfill_id": df["landfill_id"],
        "landfill_name": df["name"],
        "iso3": df["country"],
        "latitude": df["latitude"],
        "longitude": df["longitude"],
        "year": df["year"],
        "waste_accepted_tonnes": pd.to_numeric(df.get("activity"), errors="coerce"),
        "waste_accepted_source": "climate_trace_modelled",
        "methane_emitted": pd.to_numeric(df.get("emissionsQuantity"), errors="coerce"),
        "methane_source": "Climate TRACE source-level solid-waste-disposal CH4",
        "landfill_type": df.get("assetType"),
        "site_source": "Climate TRACE",
        "climate_source": None,
        "registry": "climate_trace",
        "evidence_tier": "tier_c",
        "data_quality": "modelled_external",
        "is_measured": False,
        "is_modelled": True,
        "is_proxy": False,
        "source_notes": "activity = modelled waste throughput, not metered acceptance",
    })
    return out


def load_indonesia() -> pd.DataFrame:
    p = INTERIM / "sipsn_landfills_normalized.csv"
    if not p.exists():
        p = INTERIM / "indonesia_sites_matched.csv"
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p)
    if "landfill_id" not in d.columns:
        d["landfill_id"] = [slug_id("IDN", n, c) for n, c in
                            zip(d.get("landfill_name", ""), d.get("city", ""))]
    d["iso3"] = "IDN"
    d["registry"] = "national_sipsn"
    d["evidence_tier"] = "tier_c"
    d["data_quality"] = d.get("data_quality", "government_reported")
    d["is_measured"] = False
    d["is_modelled"] = False
    d["is_proxy"] = False
    d["waste_accepted_source"] = "sipsn_reported"
    return d


def load_cdm() -> pd.DataFrame:
    p = CDM / "cdm_annual_observations.csv"
    if not p.exists():
        return pd.DataFrame()
    obs = pd.read_csv(p)
    meta_p = CDM / "cdm_projects_asia.csv"
    meta = pd.read_csv(meta_p) if meta_p.exists() else pd.DataFrame()
    if not meta.empty:
        meta = meta.rename(columns={"ref": "registry_ref"})
        keep = ["registry_ref", "title", "host_party", "methodology", "project_url",
                "pdd_download_url", "monitoring_periods", "n_monitoring_reports",
                "first_monitoring_year", "last_monitoring_year"]
        meta = meta[[c for c in keep if c in meta.columns]]
        obs = obs.merge(meta, on="registry_ref", how="left")

    iso3_map = {v: k for k, v in {
        "IND": "India", "CHN": "China", "IDN": "Indonesia", "PHL": "Philippines",
        "KOR": "Republic of Korea", "MYS": "Malaysia", "THA": "Thailand",
        "NPL": "Nepal", "BGD": "Bangladesh", "PAK": "Pakistan", "LKA": "Sri Lanka",
        "VNM": "Viet Nam", "KHM": "Cambodia", "LAO": "Lao People's Democratic Republic",
        "MMR": "Myanmar", "MNG": "Mongolia", "JPN": "Japan",
    }.items()}

    out = pd.DataFrame({
        "registry": "unfccc_cdm",
        "registry_ref": obs["registry_ref"],
        "project_title": obs.get("title"),
        "methodology": obs.get("methodology"),
        "iso3": obs.get("host_party").map(iso3_map) if "host_party" in obs else None,
        "landfill_name": obs.get("title"),
        "monitoring_period": obs.get("monitoring_period"),
        "methane_collected": obs.get("methane_collected_tonnes"),
        "collection_efficiency": obs.get("collection_efficiency"),
        "evidence_tier": np.where(
            obs.get("methane_collected_tonnes").notna(), "tier_a", "tier_b"),
        "data_quality": "operator_reported",
        "is_measured": obs.get("methane_collected_tonnes").notna(),
        "is_modelled": False,
        "is_proxy": False,
        "source_notes": "CDM monitoring report; see cdm_parameter_candidates.csv",
    })
    out["year"] = out["monitoring_period"].astype(str).str.extract(r"(19\d{2}|20\d{2})")
    out["year"] = pd.to_numeric(out["year"], errors="coerce")
    out["landfill_id"] = "cdm_" + out["registry_ref"].astype(str)
    return out


def merge_climate(df: pd.DataFrame) -> pd.DataFrame:
    p = INTERIM_CLIMATE / "nasa_power_annual.csv"
    if p.exists() and not df.empty:
        cl = pd.read_csv(p)
        cols = [c for c in ("landfill_id", "year", "temperature", "humidity",
                            "precipitation", "climate_source") if c in cl.columns]
        df = df.merge(cl[cols], on=["landfill_id", "year"], how="left",
                      suffixes=("", "_nasa"))
        for c in ("temperature", "humidity", "precipitation", "climate_source"):
            if f"{c}_nasa" in df:
                df[c] = df[c].combine_first(df[f"{c}_nasa"])
                df = df.drop(columns=[f"{c}_nasa"])
    p = INTERIM_CLIMATE / "era5_land_annual.csv"
    if p.exists() and not df.empty:
        er = pd.read_csv(p)
        cols = [c for c in ("landfill_id", "year", "soil_moisture",
                            "evapotranspiration") if c in er.columns]
        df = df.merge(er[cols], on=["landfill_id", "year"], how="left",
                      suffixes=("", "_era5"))
        for c in ("soil_moisture", "evapotranspiration"):
            if f"{c}_era5" in df:
                df[c] = df[c].combine_first(df[f"{c}_era5"])
                df = df.drop(columns=[f"{c}_era5"])
    return df


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    if {"precipitation", "evapotranspiration"}.issubset(df.columns):
        df["cmi"] = df["precipitation"] - df["evapotranspiration"]
    df["waste_accepted_tonnes"] = pd.to_numeric(df["waste_accepted_tonnes"], errors="coerce")

    df = df.sort_values(["landfill_id", "year"], na_position="last")

    def cumulative(g):
        s = g["waste_accepted_tonnes"]
        cum = s.fillna(0).cumsum()
        cum[s.isna()] = np.nan           # never imply a cumulative total for an unknown year
        years = g["year"].dropna()
        span = int(years.max() - years.min() + 1) if len(years) > 1 else 1
        g["cumulative_waste_tonnes"] = cum
        g["cumulative_is_complete"] = (s.notna().sum() == span)
        g["waste_years_observed"] = int(s.notna().sum())
        g["waste_year_span"] = span
        return g

    return df.groupby("landfill_id", group_keys=False).apply(cumulative, include_groups=False)


def main():
    frames = [f for f in (load_climatetrace(), load_indonesia(), load_cdm()) if not f.empty]
    if not frames:
        raise SystemExit("No source data. Run the collection scripts first.")

    df = pd.concat(frames, ignore_index=True, sort=False)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["iso3"] = df["iso3"].fillna("")

    df = df.drop_duplicates(
        subset=["landfill_id", "year", "registry", "waste_accepted_source"], keep="last")
    df = merge_climate(df)
    df = add_derived(df)

    for c in MASTER_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan

    df[MASTER_COLUMNS].to_csv(PROCESSED / "asia_landfill_master.csv", index=False)

    sites = (df.sort_values("year")
               .groupby("landfill_id", as_index=False)
               .agg({
                   "landfill_name": "last", "iso3": "last", "latitude": "last",
                   "longitude": "last", "registry": "last", "evidence_tier": "last",
                   "landfill_type": "last", "opening_year": "first", "closure_year": "last",
                   "year": ["min", "max"],
               }))
    sites.columns = ["landfill_id", "landfill_name", "iso3", "latitude", "longitude",
                     "registry", "evidence_tier", "landfill_type", "opening_year",
                     "closure_year", "first_year", "last_year"]
    sites.to_csv(PROCESSED / "asia_landfill_sites.csv", index=False)

    print(f"master rows: {len(df):,} | sites: {df['landfill_id'].nunique():,}")
    print(df.groupby(["evidence_tier", "registry"]).size().to_string())


if __name__ == "__main__":
    main()
