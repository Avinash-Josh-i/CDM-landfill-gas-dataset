"""Assemble the frozen master tables for the Asian Landfill dataset.

.. note::
   The publication-export part of this script is **superseded** by
   ``scripts/16_build_release.py``, which writes the canonical public package to
   ``release/v1.0/``. This script still produces the frozen master tables in
   ``data/processed/`` that the release builder reads.

Joins the three evidence layers into one coherent, provenance-carrying dataset:

* **Tier A** - CDM sites with a metered landfill-gas series (census gate passers).
* **Tier B** - non-metered engineered landfills documented in a CDM PDD.
* **Climate** - NASA POWER monthly-derived annual temperature / humidity / precipitation.

Outputs
-------
data/processed/sites.csv                  one row per landfill
data/processed/annual_observations.csv    one row per landfill-year
data/processed/climate.csv                one row per landfill-year

Stages
------
    python scripts/09_build_repository.py coords   # site spine + coordinates
    python scripts/02_collect_nasa_power.py        # fetch climate for that spine
    python scripts/09_build_repository.py build    # join everything
    python scripts/09_build_repository.py all      # coords + build (climate if present)

Nothing is modelled.  Missing values stay missing and every row carries its provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (INTERIM_CDM, INTERIM_CLIMATE, PROCESSED, RAW_CDM,
                    TIER_DEFINITIONS)

CENSUS = INTERIM_CDM / "census" / "cdm_census_lfg.csv"
TIER_B_DIR = INTERIM_CDM / "tier_b"
TIER_B_SITES = TIER_B_DIR / "tier_b_sites.csv"
TIER_B_INFLOW = TIER_B_DIR / "tier_b_annual_inflow.csv"
CDM_OBS = INTERIM_CDM / "cdm_annual_observations.csv"
CDM_PROJECTS = INTERIM_CDM / "cdm_projects_asia.csv"
CT_ASIA = INTERIM_CLIMATE / "climatetrace_asia_solid_waste_ch4.csv"
NASA = INTERIM_CLIMATE / "nasa_power_annual.csv"
COORDS = INTERIM_CLIMATE / "site_coordinates.csv"
TIER_A_INFLOW_CACHE = INTERIM_CDM / "tier_a_annual_inflow.csv"

HOST_ISO3 = {
    "China": "CHN", "India": "IND", "Indonesia": "IDN", "Philippines": "PHL",
    "Malaysia": "MYS", "Thailand": "THA", "Republic of Korea": "KOR",
    "Korea": "KOR", "Viet Nam": "VNM", "Vietnam": "VNM", "Nepal": "NPL",
    "Bangladesh": "BGD", "Pakistan": "PAK", "Sri Lanka": "LKA", "Japan": "JPN",
    "Cambodia": "KHM", "Laos": "LAO", "Myanmar": "MMR", "Mongolia": "MNG",
    "Singapore": "SGP", "Taiwan": "TWN", "Hong Kong": "HKG",
    "Israel": "ISR", "Iran (Islamic Republic of)": "IRN", "Iran": "IRN",
    "Syrian Arab Republic": "SYR", "United Arab Emirates": "ARE",
    "Saudi Arabia": "SAU", "Jordan": "JOR", "Uzbekistan": "UZB",
    "Kazakhstan": "KAZ", "Kyrgyzstan": "KGZ", "Tajikistan": "TJK",
    "Turkmenistan": "TKM", "Bhutan": "BTN", "Maldives": "MDV",
    "Brunei Darussalam": "BRN", "Timor-Leste": "TLS", "Afghanistan": "AFG",
}

SITE_COLUMNS = [
    "landfill_id", "landfill_name", "country", "iso3", "city",
    "latitude", "longitude", "coordinate_source",
    "opening_year", "closure_year",
    "evidence_tier", "registry", "registry_ref", "project_title", "methodology",
    "registration_date",
    "design_type", "liner_type", "cover_frequency", "leachate_system",
    "gas_control_presence",
    "design_capacity_tonnes", "annual_waste_inflow_tonnes", "annual_inflow_year",
    "annual_inflow_basis", "waste_composition_fractions", "waste_source_type",
    "waste_history_years", "waste_tonnes_cumulative", "cumulative_is_complete",
    "collection_efficiency", "ce_basis", "has_metered_lfg", "n_metered_periods",
    "n_monitoring_reports",
    "data_source_type", "provenance_reference",
    "qa_coords", "qa_waste_history", "qa_composition", "qa_ce", "qa_provenance",
    "source_notes",
]

OBS_COLUMNS = [
    "landfill_id", "iso3", "year", "evidence_tier",
    "waste_inflow_tonnes", "waste_inflow_basis",
    "lfg_total_nm3", "lfg_unit", "lfg_flared_nm3", "lfg_utilised_nm3", "ch4_fraction",
    "methane_collected_tonnes", "methane_flared_tonnes", "methane_utilised_tonnes",
    "methane_collected_tonnes_per_year",
    "collection_efficiency", "ce_basis",
    "period_start", "period_end", "period_days", "period_source", "doc_path",
    "is_measured", "data_source_type", "provenance_reference", "qa_flags",
]

CLIMATE_COLUMNS = [
    "landfill_id", "iso3", "year", "latitude", "longitude",
    "temperature", "humidity", "precipitation", "n_months",
    "climate_source", "coordinate_source", "qa_climate",
]


# ---------------------------------------------------------------------------
# coordinate parsing (PDD text first, name-match proxy second)
# ---------------------------------------------------------------------------
def _load_tier_b_module():
    path = Path(__file__).resolve().parent / "13_collect_tier_b.py"
    spec = importlib.util.spec_from_file_location("tier_b", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dms(deg, minute, sec, hemi):
    v = float(deg) + float(minute) / 60.0 + float(sec) / 3600.0
    return -v if hemi.upper() in {"S", "W"} else v


DMS_RE = re.compile(
    r"(\d{1,3})\s*[°º]\s*(\d{1,2})\s*['′’`„]\s*(\d{1,2}(?:\.\d+)?)\s*[\"″”'’]{0,2}\s*([NSEWnsew])")
DEC_RE = re.compile(
    r"\b(?:latitude|lat\.?)\s*[:=]?\s*(-?\d{1,2}\.\d{2,})\D{0,40}?"
    r"(?:longitude|lon\.?|long\.?)\s*[:=]?\s*(-?\d{1,3}\.\d{2,})", re.I)


def parse_coordinates(text: str) -> tuple[float, float, str] | None:
    # collect DMS tokens and pair a latitude with the next longitude within 120 chars
    toks = [(m.start(), m) for m in DMS_RE.finditer(text)]
    for i, (pos, m) in enumerate(toks):
        if m.group(4).upper() not in {"N", "S"}:
            continue
        lat = _dms(*m.groups()[:3], m.group(4))
        for pos2, m2 in toks[i + 1:]:
            if pos2 - pos > 120:
                break
            if m2.group(4).upper() not in {"E", "W"}:
                continue
            lon = _dms(*m2.groups()[:3], m2.group(4))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return round(lat, 5), round(lon, 5), "pdd_dms"
            break
    m = DEC_RE.search(text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return round(lat, 5), round(lon, 5), "pdd_decimal"
    return None


def _norm_name(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", str(s).lower())
    s = re.sub(r"\b(landfill|site|project|the|of|and|cdm|lfG|msw)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_climatetrace(name: str, iso3: str, ct_sites: pd.DataFrame) -> tuple[float, float] | None:
    if ct_sites.empty or not iso3:
        return None
    from rapidfuzz import fuzz
    cand = ct_sites[ct_sites["country"] == iso3]
    if cand.empty:
        return None
    target = _norm_name(name)
    if not target:
        return None
    scored = [(fuzz.token_set_ratio(target, _norm_name(n)), n, la, lo)
              for n, la, lo in zip(cand["name"], cand["latitude"], cand["longitude"])]
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 90:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 5:
        return None
    return float(scored[0][2]), float(scored[0][3])


# ---------------------------------------------------------------------------
# site spine
# ---------------------------------------------------------------------------
def load_site_spine() -> pd.DataFrame:
    census = pd.read_csv(CENSUS)
    meta = pd.read_csv(CDM_PROJECTS).set_index("ref") if CDM_PROJECTS.exists() else None
    tier_b = pd.read_csv(TIER_B_SITES) if TIER_B_SITES.exists() else pd.DataFrame()
    frames = []
    for _, r in census.iterrows():
        ref = int(r["ref"])
        tier = "tier_a" if r.get("gate_pass") == True else "tier_b"
        if tier == "tier_b" and float(r.get("n_metered_periods") or 0) > 0:
            continue  # a metered site that failed on waste history is not Tier B
        m = meta.loc[ref] if meta is not None and ref in meta.index else None
        host = r.get("host_party")
        row = {
            "landfill_id": f"cdm_{ref}",
            "landfill_name": r.get("title"),
            "country": host,
            "iso3": HOST_ISO3.get(str(host)),
            "registry": "unfccc_cdm",
            "registry_ref": ref,
            "project_title": r.get("title"),
            "methodology": (m.get("methodology") if m is not None else None),
            "registration_date": (m.get("registration_date") if m is not None else None),
            "evidence_tier": tier,
            "opening_year": r.get("waste_opening_year"),
            "closure_year": r.get("waste_closing_year"),
            "waste_history_years": r.get("waste_history_years"),
            "waste_tonnes_cumulative": r.get("waste_tonnes_cumulative"),
            "cumulative_is_complete": bool(r.get("cumulative_is_complete")),
            "collection_efficiency": r.get("ce_value"),
            "ce_basis": r.get("ce_basis"),
            "has_metered_lfg": bool(float(r.get("n_metered_periods") or 0) > 0),
            "n_metered_periods": r.get("n_metered_periods"),
            "n_monitoring_reports": r.get("n_mrs_available"),
            "data_source_type": "cdm_pdd" if tier == "tier_b" else "cdm_pdd+cdm_mr",
            "provenance_reference": (
                f"UNFCCC CDM ref {ref}; PDD data/raw/cdm/census/pdd/{ref}_pdd.pdf"
                + ("; monitoring reports data/raw/cdm/mr/" + str(ref) if tier == "tier_a" else "")
            ),
        }
        if tier == "tier_b" and not tier_b.empty:
            b = tier_b[tier_b["ref"].astype(int) == ref]
            if len(b):
                b = b.iloc[0]
                for col in ("design_type", "liner_type", "cover_frequency",
                            "leachate_system", "gas_control_presence",
                            "design_capacity_tonnes", "annual_waste_inflow_tonnes",
                            "annual_inflow_year", "annual_inflow_basis",
                            "waste_composition_fractions", "waste_source_type"):
                    row[col] = b.get(col)
        frames.append(row)

    sites = pd.DataFrame(frames)
    sites = sites.drop_duplicates("landfill_id").reset_index(drop=True)
    return sites


def attach_coordinates(sites: pd.DataFrame) -> pd.DataFrame:
    ct = pd.read_csv(CT_ASIA) if CT_ASIA.exists() else pd.DataFrame()
    ct_sites = (ct.drop_duplicates("landfill_id")[["name", "country", "latitude", "longitude"]]
                .dropna(subset=["latitude", "longitude"])) if not ct.empty else pd.DataFrame()
    geo = pd.read_csv(INTERIM_CLIMATE / "geocoded_sites.csv") if (INTERIM_CLIMATE / "geocoded_sites.csv").exists() else pd.DataFrame()
    if not geo.empty:
        geo = geo.set_index("landfill_id")

    lats, lons, sources = [], [], []
    for _, r in sites.iterrows():
        ref = int(r["registry_ref"])
        txt = INTERIM_CDM / "census" / "text" / f"pdd_{ref}.txt"
        got = parse_coordinates(txt.read_text()) if txt.exists() else None
        if got:
            lat, lon, src = got
        elif r["landfill_id"] in geo.index:
            g = geo.loc[r["landfill_id"]]
            if pd.notna(g.get("latitude")) and pd.notna(g.get("longitude")):
                lat, lon, src = float(g["latitude"]), float(g["longitude"]), str(g.get("coordinate_source", "geocoded_locality_approx"))
            else:
                proxy = match_climatetrace(r["landfill_name"], r["iso3"], ct_sites)
                if proxy:
                    lat, lon, src = proxy[0], proxy[1], "climate_trace_name_match_proxy"
                else:
                    lat, lon, src = np.nan, np.nan, "not_reported"
        else:
            proxy = match_climatetrace(r["landfill_name"], r["iso3"], ct_sites)
            if proxy:
                lat, lon, src = proxy[0], proxy[1], "climate_trace_name_match_proxy"
            else:
                lat, lon, src = np.nan, np.nan, "not_reported"
        lats.append(lat)
        lons.append(lon)
        sources.append(src)

    sites["latitude"] = lats
    sites["longitude"] = lons
    sites["coordinate_source"] = sources
    return sites


def ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Guarantee the declared schema exists before export (missing stays null)."""
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df


def write_coords_stage() -> pd.DataFrame:
    sites = attach_coordinates(load_site_spine())
    out = sites[["landfill_id", "latitude", "longitude", "coordinate_source"]].copy()
    out.to_csv(COORDS, index=False)
    ok = out.dropna(subset=["latitude", "longitude"])
    print(f"wrote {COORDS} ({len(out)} sites, {len(ok)} with coordinates)")
    print(out["coordinate_source"].value_counts().to_string())
    return sites


# ---------------------------------------------------------------------------
# observations
# ---------------------------------------------------------------------------
def tier_a_observations(sites: pd.DataFrame) -> pd.DataFrame:
    if not CDM_OBS.exists():
        return pd.DataFrame(columns=OBS_COLUMNS)
    obs = pd.read_csv(CDM_OBS)
    obs["landfill_id"] = "cdm_" + obs["registry_ref"].astype(int).astype(str)
    obs = obs.merge(sites[["landfill_id", "iso3", "evidence_tier"]], on="landfill_id", how="inner")
    doc = obs["doc_path"] if "doc_path" in obs.columns else obs.get("doc_label")
    out = pd.DataFrame({
        "landfill_id": obs["landfill_id"],
        "iso3": obs["iso3"],
        "year": pd.to_numeric(obs.get("year"), errors="coerce").astype("Int64"),
        "evidence_tier": obs["evidence_tier"],
        "lfg_total_nm3": obs.get("lfg_total_nm3"),
        "lfg_unit": obs.get("lfg_total_unit"),
        "lfg_flared_nm3": obs.get("lfg_flared_nm3"),
        "lfg_utilised_nm3": obs.get("lfg_utilised_nm3"),
        "ch4_fraction": obs.get("ch4_fraction"),
        "methane_collected_tonnes": obs.get("methane_collected_tonnes"),
        "methane_flared_tonnes": obs.get("methane_flared_tonnes"),
        "methane_utilised_tonnes": obs.get("methane_utilised_tonnes"),
        "methane_collected_tonnes_per_year": obs.get("methane_collected_tonnes_per_year"),
        "collection_efficiency": obs.get("collection_efficiency"),
        "ce_basis": obs.get("ce_basis"),
        "period_start": obs.get("period_start"),
        "period_end": obs.get("period_end"),
        "period_days": obs.get("period_days"),
        "period_source": obs.get("period_source"),
        "doc_path": doc,
        "is_measured": obs.get("lfg_total_nm3").notna(),
        "data_source_type": "cdm_monitoring_report",
        "provenance_reference": "UNFCCC CDM monitoring report: " + doc.astype(str),
    })
    return out


def tier_a_inflow(sites: pd.DataFrame) -> pd.DataFrame:
    """Annual waste placement for Tier A, parsed from the PDD waste tables (cached)."""
    if TIER_A_INFLOW_CACHE.exists():
        return pd.read_csv(TIER_A_INFLOW_CACHE)
    tb = _load_tier_b_module()
    rows = []
    for ref in sites[sites["evidence_tier"] == "tier_a"]["registry_ref"].astype(int):
        pdf = RAW_CDM / "census" / "pdd" / f"{ref}_pdd.pdf"
        if not pdf.exists():
            continue
        for year, tonnes in sorted(tb.parse_waste_series(pdf).items()):
            rows.append({"landfill_id": f"cdm_{ref}", "year": year,
                         "waste_inflow_tonnes": tonnes,
                         "waste_inflow_basis": "pdd_table",
                         "data_source_type": "cdm_pdd_table",
                         "provenance_reference": f"UNFCCC CDM ref {ref} PDD waste table"})
    out = pd.DataFrame(rows)
    out.to_csv(TIER_A_INFLOW_CACHE, index=False)
    return out


def tier_b_observations(sites: pd.DataFrame) -> pd.DataFrame:
    if not TIER_B_INFLOW.exists():
        return pd.DataFrame(columns=OBS_COLUMNS)
    inf = pd.read_csv(TIER_B_INFLOW)
    inf["landfill_id"] = "cdm_" + inf["ref"].astype(int).astype(str)
    inf = inf.merge(sites[["landfill_id", "iso3", "evidence_tier"]], on="landfill_id", how="inner")
    out = pd.DataFrame({
        "landfill_id": inf["landfill_id"],
        "iso3": inf["iso3"],
        "year": pd.to_numeric(inf["year"], errors="coerce").astype("Int64"),
        "evidence_tier": inf["evidence_tier"],
        "waste_inflow_tonnes": inf["waste_inflow_tonnes"],
        "waste_inflow_basis": "pdd_table",
        "is_measured": False,
        "data_source_type": inf["data_source_type"],
        "provenance_reference": inf["provenance_reference"],
    })
    return out


def build_observations(sites: pd.DataFrame) -> pd.DataFrame:
    frames = [tier_a_observations(sites), tier_b_observations(sites)]
    a_inf = tier_a_inflow(sites)
    obs = pd.concat([f for f in frames if not f.empty], ignore_index=True)

    # fold Tier A annual waste into the same site-year rows
    if not a_inf.empty:
        obs = obs.merge(a_inf[["landfill_id", "year", "waste_inflow_tonnes",
                               "waste_inflow_basis"]],
                        on=["landfill_id", "year"], how="outer",
                        suffixes=("", "_pdd"))
        for col in ("waste_inflow_tonnes", "waste_inflow_basis"):
            alt = f"{col}_pdd"
            if alt in obs:
                obs[col] = obs[col].combine_first(obs[alt])
                obs = obs.drop(columns=[alt])
        tier = sites.set_index("landfill_id")["evidence_tier"]
        iso = sites.set_index("landfill_id")["iso3"]
        obs["evidence_tier"] = obs["evidence_tier"].fillna(obs["landfill_id"].map(tier))
        obs["iso3"] = obs["iso3"].fillna(obs["landfill_id"].map(iso))

    for c in OBS_COLUMNS:
        if c not in obs.columns:
            obs[c] = np.nan

    obs = obs[OBS_COLUMNS]
    obs["is_measured"] = obs["is_measured"].fillna(False).astype(bool)
    obs["qa_flags"] = obs.apply(_obs_flags, axis=1)
    return (obs.dropna(subset=["year"])
               .assign(year=lambda d: d["year"].astype(int))
               .sort_values(["landfill_id", "year"])
               .reset_index(drop=True))


def _obs_flags(r: pd.Series) -> str:
    flags = []
    if pd.isna(r.get("waste_inflow_tonnes")):
        flags.append("waste_missing")
    if pd.notna(r.get("lfg_total_nm3")):
        flags.append("lfg_metered")
    if r.get("period_source") in ("not_found", "fallback"):
        flags.append("period_weak")
    if r.get("ce_basis") == "assumed":
        flags.append("ce_assumed")
    days = r.get("period_days")
    if pd.notna(days):
        if float(days) > 400:
            flags.append("period_multi_year")
        elif float(days) < 300:
            flags.append("period_partial_year")
    return ";".join(flags)


# ---------------------------------------------------------------------------
# climate
# ---------------------------------------------------------------------------
def build_climate(sites: pd.DataFrame) -> pd.DataFrame:
    if not NASA.exists():
        return pd.DataFrame(columns=CLIMATE_COLUMNS)
    cl = pd.read_csv(NASA)
    cl = cl.merge(sites[["landfill_id", "iso3", "coordinate_source"]],
                  on="landfill_id", how="inner")
    for c in CLIMATE_COLUMNS:
        if c not in cl.columns:
            cl[c] = np.nan
    cl["qa_climate"] = np.where(
        cl["n_months"].fillna(0) == 12, "complete",
        np.where(cl["n_months"].fillna(0) > 0, "partial", "missing"))
    return cl[CLIMATE_COLUMNS].sort_values(["landfill_id", "year"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# QA + export
# ---------------------------------------------------------------------------
def add_site_qa(sites: pd.DataFrame) -> pd.DataFrame:
    def coords(r):
        if pd.isna(r.get("latitude")):
            return "missing"
        return "proxy" if "proxy" in str(r.get("coordinate_source")) else "ok"

    def waste(r):
        y = r.get("waste_history_years")
        if pd.isna(y):
            return "unknown"
        return "ok" if float(y) >= 10 else "short"

    def comp(r):
        return "parsed" if isinstance(r.get("waste_composition_fractions"), str) and \
            r.get("waste_composition_fractions") else "not_reported"

    def ce(r):
        basis = r.get("ce_basis")
        return basis if basis in ("measured", "assumed", "reported") else "not_reported"

    def prov(r):
        return "ok" if isinstance(r.get("provenance_reference"), str) and \
            len(r.get("provenance_reference")) > 10 else "missing"

    sites["qa_coords"] = sites.apply(coords, axis=1)
    sites["qa_waste_history"] = sites.apply(waste, axis=1)
    sites["qa_composition"] = sites.apply(comp, axis=1)
    sites["qa_ce"] = sites.apply(ce, axis=1)
    sites["qa_provenance"] = sites.apply(prov, axis=1)
    sites["source_notes"] = sites["evidence_tier"].map(TIER_DEFINITIONS)
    return sites


def export(sites: pd.DataFrame, obs: pd.DataFrame, climate: pd.DataFrame) -> None:
    """Write the frozen master tables. Publication export lives in scripts/16."""
    PROCESSED.mkdir(parents=True, exist_ok=True)
    for df, name in ((sites, "sites.csv"), (obs, "annual_observations.csv"),
                     (climate, "climate.csv")):
        df.to_csv(PROCESSED / name, index=False)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["coords", "build", "all"], nargs="?", default="all")
    args = ap.parse_args()

    if args.stage in ("coords", "all"):
        write_coords_stage()
    if args.stage in ("build", "all"):
        sites = attach_coordinates(load_site_spine())
        sites = add_site_qa(sites)
        sites = ensure_columns(sites, SITE_COLUMNS)[SITE_COLUMNS]
        obs = build_observations(sites)
        climate = build_climate(sites)
        export(sites, obs, climate)
        print(f"sites: {len(sites)} (tier_a={int((sites.evidence_tier=='tier_a').sum())}, "
              f"tier_b={int((sites.evidence_tier=='tier_b').sum())})")
        print(f"annual observations: {len(obs)} site-years")
        print(f"climate: {len(climate)} site-years")
        print(f"wrote master tables to {PROCESSED}")


if __name__ == "__main__":
    main()
