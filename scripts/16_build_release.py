#!/usr/bin/env python3
"""Build the publishable v1.0 release from the frozen master tables.

The three master tables are read-only inputs and are never modified:

    data/processed/sites.csv
    data/processed/annual_observations.csv
    data/processed/climate.csv

Outputs
-------
release/v1.0/data/                  cleaned, single-grain release tables
release/v1.0/DATA_DICTIONARY.csv    one row per published column
release/v1.0/QA_REPORT.md           quality checks, fixes and known issues
release/v1.0/SOURCES.md             source and attribution register
release/v1.0/manifest.csv           SHA256 + size for every release file

The release deliberately keeps ``m3`` and ``Nm3`` as-reported. No unit
conversion is applied because the source reports do not carry the temperature
and pressure needed for a defensible normalisation.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
INTERIM = ROOT / "data" / "interim"
RELEASE = ROOT / "release" / "v1.0"
DATA_OUT = RELEASE / "data"
RELEASE_DATE = "2026-11-06"

SIPSN_URL = "https://sampahnasional.kemenlh.go.id/portal-indikatif/fasilitas/tpa-tpst"
NASA_POWER_URL = "https://power.larc.nasa.gov/"
CLIMATE_TRACE_URL = "https://climatetrace.org/data"
CDM_SEARCH_URL = "https://cdm.unfccc.int/Projects/projsearch.html"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/"

STANDARD_COUNTRY = {
    "BGD": "Bangladesh",
    "CHN": "China",
    "IND": "India",
    "IDN": "Indonesia",
    "IRN": "Iran",
    "ISR": "Israel",
    "JOR": "Jordan",
    "KOR": "South Korea",
    "MYS": "Malaysia",
    "PHL": "Philippines",
    "SAU": "Saudi Arabia",
    "SYR": "Syria",
    "THA": "Thailand",
    "ARE": "United Arab Emirates",
    "UZB": "Uzbekistan",
    "VNM": "Vietnam",
}

REGION = {
    "CHN": "East Asia",
    "KOR": "East Asia",
    "IDN": "Southeast Asia",
    "MYS": "Southeast Asia",
    "PHL": "Southeast Asia",
    "THA": "Southeast Asia",
    "VNM": "Southeast Asia",
    "BGD": "South Asia",
    "IND": "South Asia",
    "IRN": "Middle East and West Asia",
    "ISR": "Middle East and West Asia",
    "JOR": "Middle East and West Asia",
    "SAU": "Middle East and West Asia",
    "SYR": "Middle East and West Asia",
    "ARE": "Middle East and West Asia",
    "UZB": "Central Asia",
}

COORDINATE_QUALITY = {
    "pdd_dms": "reported_in_pdd",
    "geocoded_city_v2": "geocoded_city",
    "geocoded_city_v2_offset": "geocoded_city_offset",
    "geocoded_locality_approx": "geocoded_locality_approximate",
    "climate_trace_name_match_proxy": "proxy_name_match",
    "not_reported": "unknown",
}


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.replace("", pd.NA), errors="coerce")


def norm_path(value: str) -> str:
    value = str(value).replace("\\", "/").strip()
    if value.startswith("data/"):
        value = value[5:]
    return value.lstrip("/")


def iso_date(value: str) -> str:
    parsed = pd.to_datetime(value, format="%d %b %y", errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def int_or_blank(value) -> str:
    if pd.isna(value):
        return ""
    return str(int(value))


def bool_text(value) -> str:
    return "True" if bool(value) else "False"


def filename_periods(name: str) -> list:
    dates = re.findall(r"(\d{1,2})_([A-Za-z]{3})_(\d{4})", name)
    out = []
    for day, month, year in dates:
        try:
            out.append(pd.Timestamp(f"{day} {month} {year}").date())
        except Exception:
            continue
    return out


def filename_period_mismatch(doc_path: str, start: str, end: str) -> bool:
    dates = filename_periods(Path(doc_path).name)
    if len(dates) < 2:
        return False
    try:
        start_date = pd.Timestamp(start).date()
        end_date = pd.Timestamp(end).date()
    except Exception:
        return False
    return dates[0] != start_date or dates[-1] != end_date


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_sites(sites: pd.DataFrame, projects: pd.DataFrame, waste: pd.DataFrame,
                lfg: pd.DataFrame, composition: pd.DataFrame) -> pd.DataFrame:
    if waste.empty:
        waste = pd.DataFrame({"landfill_id": [], "year": []})
    if lfg.empty:
        lfg = pd.DataFrame({"landfill_id": [], "year": []})
    if composition.empty:
        composition = pd.DataFrame(
            {
                "landfill_id": [],
                "category": [],
                "composition_sum": [],
                "composition_is_complete": [],
            }
        )
    df = sites.copy()
    df["country_name_source"] = df["country"]
    df["country"] = df["iso3"].map(STANDARD_COUNTRY).fillna(df["country"])
    df["region"] = df["iso3"].map(REGION).fillna("Other Asia")
    df["registration_date"] = df["registration_date"].map(iso_date)
    df["coordinate_quality"] = (
        df["coordinate_source"].map(COORDINATE_QUALITY).fillna("unknown")
    )

    project_map = projects.drop_duplicates("ref").set_index("ref")
    df["cdm_project_url"] = df["registry_ref"].map(project_map["project_url"])
    df["pdd_url"] = df["registry_ref"].map(project_map["pdd_download_url"])

    df = df.rename(
        columns={
            "annual_waste_inflow_tonnes": "annual_waste_inflow_reported_tonnes",
            "annual_inflow_year": "annual_inflow_reference_year",
            "ce_basis": "collection_efficiency_basis",
            "n_observation_rows": "n_source_observation_rows",
            "has_observations": "has_any_observation",
        }
    )
    df["qa_collection_efficiency"] = df["collection_efficiency_basis"].where(
        df["collection_efficiency"].ne(""), "not_reported"
    )

    # Replace stale master QA flags with flags derived from the current values.
    df["qa_composition"] = ""
    df.loc[df["waste_composition_fractions"].ne(""), "qa_composition"] = "reported"
    composition_sum = composition.groupby("landfill_id")["composition_sum"].first()
    composition_complete = composition.groupby("landfill_id")[
        "composition_is_complete"
    ].first()
    composition_n = composition.groupby("landfill_id")["category"].nunique()
    df["has_waste_composition"] = df["landfill_id"].isin(composition_sum.index).map(
        {True: "True", False: "False"}
    )
    df["composition_n_categories"] = df["landfill_id"].map(composition_n)
    df["composition_sum"] = df["landfill_id"].map(composition_sum)
    df["composition_is_complete"] = df["landfill_id"].map(composition_complete)
    df.loc[df["has_waste_composition"].eq("False"), "qa_composition"] = "not_reported"

    waste_counts = waste.groupby("landfill_id").size()
    waste_years = waste.groupby("landfill_id")["year"].agg(["min", "max"])
    lfg_counts = lfg.groupby("landfill_id").size()
    lfg_years = lfg.groupby("landfill_id")["year"].agg(["min", "max"])
    df["waste_inflow_rows"] = df["landfill_id"].map(waste_counts).fillna(0).astype(int)
    df["waste_inflow_year_min"] = df["landfill_id"].map(waste_years["min"])
    df["waste_inflow_year_max"] = df["landfill_id"].map(waste_years["max"])
    df["lfg_measurement_rows"] = df["landfill_id"].map(lfg_counts).fillna(0).astype(int)
    df["lfg_measured_year_min"] = df["landfill_id"].map(lfg_years["min"])
    df["lfg_measured_year_max"] = df["landfill_id"].map(lfg_years["max"])

    def derive_has(row: pd.Series, count_col: str) -> str:
        return bool_text(pd.notna(row[count_col]) and float(row[count_col]) > 0)

    df["has_waste_inflow"] = df.apply(lambda r: derive_has(r, "waste_inflow_rows"), axis=1)
    df["has_measured_lfg"] = df.apply(
        lambda r: derive_has(r, "lfg_measurement_rows"), axis=1
    )

    columns = [
        "landfill_id", "landfill_name", "country", "country_name_source", "iso3",
        "region", "latitude", "longitude", "coordinate_source", "coordinate_quality",
        "opening_year", "closure_year", "evidence_tier", "registry", "registry_ref",
        "project_title", "methodology", "registration_date", "cdm_project_url",
        "pdd_url", "design_type", "liner_type", "cover_frequency", "leachate_system",
        "gas_control_presence", "design_capacity_tonnes",
        "annual_waste_inflow_reported_tonnes", "annual_inflow_reference_year",
        "annual_inflow_basis", "waste_source_type", "waste_history_years",
        "waste_tonnes_cumulative", "cumulative_is_complete", "collection_efficiency",
        "collection_efficiency_basis", "qa_collection_efficiency", "has_metered_lfg",
        "n_metered_periods", "n_monitoring_reports", "data_source_type",
        "provenance_reference", "qa_waste_history", "qa_composition", "qa_provenance",
        "source_notes", "has_waste_composition", "composition_n_categories",
        "composition_sum", "composition_is_complete", "waste_inflow_rows",
        "waste_inflow_year_min", "waste_inflow_year_max", "lfg_measurement_rows",
        "lfg_measured_year_min", "lfg_measured_year_max", "has_any_observation",
        "has_waste_inflow", "n_source_observation_rows",
    ]
    return df[columns].sort_values("landfill_id").reset_index(drop=True)


def build_lfg(obs: pd.DataFrame, sites: pd.DataFrame, url_by_path: dict,
              label_by_path: dict, project_url_by_ref: dict,
              validation: pd.DataFrame) -> pd.DataFrame:
    df = obs[obs["is_measured"].str.lower().eq("true")].copy()
    df = df.sort_values(["landfill_id", "period_start", "period_end"]).reset_index(
        drop=True
    )
    df.insert(0, "observation_id", [f"LFG-{i:04d}" for i in range(1, len(df) + 1)])
    df = df.rename(
        columns={
            "lfg_total_nm3": "lfg_total_volume",
            "lfg_unit": "lfg_volume_unit",
            "lfg_flared_nm3": "lfg_flared_volume",
            "lfg_utilised_nm3": "lfg_utilised_volume",
        }
    )
    site_lookup = sites.set_index("landfill_id")
    df["country"] = df["landfill_id"].map(site_lookup["country"])
    df["evidence_tier"] = df["landfill_id"].map(site_lookup["evidence_tier"])
    df["collection_efficiency"] = df["landfill_id"].map(
        site_lookup["collection_efficiency"]
    )
    df["collection_efficiency_basis"] = df["landfill_id"].map(
        site_lookup["collection_efficiency_basis"]
    )

    df["source_url"] = df["doc_path"].map(lambda p: url_by_path.get(norm_path(p), ""))
    df["source_document"] = df["doc_path"].map(lambda p: Path(str(p)).name)
    df["source_manifest_label"] = df["doc_path"].map(
        lambda p: label_by_path.get(norm_path(p), "")
    )
    df["cdm_project_url"] = df["landfill_id"].map(
        lambda lid: project_url_by_ref.get(str(lid).replace("cdm_", ""), "")
    )
    df["extraction_method"] = "cdm_monitoring_report_table_or_text"
    df["lfg_volume_unit"] = df["lfg_volume_unit"].replace("", "not_reported")

    validation = validation.set_index("record_key")
    def val(row: pd.Series, col: str) -> str:
        key = f"{row['landfill_id']}|{row['period_start']}|{row['period_end']}"
        if key not in validation.index:
            return ""
        return str(validation.loc[key, col])

    df["validation_status"] = df.apply(lambda r: val(r, "validation_status"), axis=1)
    df["validation_pages"] = df.apply(lambda r: val(r, "validation_pages"), axis=1)

    df["qa_unit"] = df["lfg_volume_unit"].map(
        lambda u: "reported" if u in {"m3", "Nm3"} else "not_reported"
    )
    df["qa_period_multi_year"] = (
        numeric(df["period_days"]).gt(366).fillna(False)
        | df["qa_flags"].str.contains("period_multi_year", na=False)
    ).map({True: "True", False: "False"})
    df["qa_period_partial_year"] = df["qa_flags"].str.contains(
        "period_partial_year", na=False
    ).map({True: "True", False: "False"})
    df["qa_filename_period_mismatch"] = [
        bool_text(filename_period_mismatch(p, s, e))
        for p, s, e in zip(df["doc_path"], df["period_start"], df["period_end"])
    ]
    df["qa_outlier"] = numeric(df["lfg_total_volume"]).gt(100_000_000).map(
        {True: "True", False: "False"}
    )
    df["qa_outlier_reason"] = ""
    df.loc[df["qa_outlier"].eq("True"), "qa_outlier_reason"] = (
        "Reported LFG volume exceeds 100 million m3 in one monitoring period; "
        "verify against source table."
    )

    notes = []
    for _, row in df.iterrows():
        parts = []
        if row["qa_unit"] == "not_reported":
            parts.append("Volume unit not stated in source; values retained as reported.")
        if row["qa_filename_period_mismatch"] == "True":
            parts.append(
                "Monitoring period is taken from the report text; the local filename "
                "dates do not match the period inside the document."
            )
        if row["qa_outlier"] == "True":
            parts.append("Large reported volume; flagged for source verification.")
        if row["validation_status"] == "not_found":
            parts.append(
                "Reported value was not found in the extracted PDF text; treat as "
                "unverified until checked against the source table."
            )
        notes.append(" ".join(parts))
    df["notes"] = notes

    columns = [
        "observation_id", "landfill_id", "country", "iso3", "evidence_tier", "year",
        "period_start", "period_end", "period_days", "period_source",
        "lfg_total_volume", "lfg_volume_unit", "lfg_flared_volume",
        "lfg_utilised_volume", "ch4_fraction", "methane_collected_tonnes",
        "methane_flared_tonnes", "methane_utilised_tonnes",
        "methane_collected_tonnes_per_year", "collection_efficiency",
        "collection_efficiency_basis", "source_url", "source_document",
        "source_manifest_label", "cdm_project_url", "extraction_method", "qa_flags",
        "qa_filename_period_mismatch", "qa_period_multi_year",
        "qa_period_partial_year", "qa_unit", "qa_outlier", "qa_outlier_reason",
        "validation_status", "validation_pages", "notes",
    ]
    return df[columns].reset_index(drop=True)


def build_waste(obs: pd.DataFrame, sites: pd.DataFrame, projects: pd.DataFrame,
                validation: pd.DataFrame) -> pd.DataFrame:
    site_lookup = sites.set_index("landfill_id")
    project_map = projects.drop_duplicates("ref").set_index("ref")

    pdd = obs[obs["data_source_type"].eq("cdm_pdd_table")].copy()
    pdd["source_url"] = pdd["landfill_id"].map(
        lambda lid: project_map.loc[str(lid).replace("cdm_", ""), "pdd_download_url"]
        if str(lid).replace("cdm_", "") in project_map.index else ""
    )
    pdd["source_document"] = pdd["landfill_id"].map(
        lambda lid: f"{str(lid).replace('cdm_', '')}_pdd.pdf"
    )
    pdd["extraction_method"] = "cdm_pdd_table"
    pdd["inflow_basis"] = pdd["waste_inflow_basis"]

    sipsn = sites[sites["annual_inflow_basis"].eq("sipsn_2025")].copy()
    year_col = (
        "annual_inflow_reference_year"
        if "annual_inflow_reference_year" in sipsn.columns
        else "annual_inflow_year"
    )
    value_col = (
        "annual_waste_inflow_reported_tonnes"
        if "annual_waste_inflow_reported_tonnes" in sipsn.columns
        else "annual_waste_inflow_tonnes"
    )
    sipsn_rows = pd.DataFrame(
        {
            "landfill_id": sipsn["landfill_id"],
            "iso3": sipsn["iso3"],
            "year": sipsn[year_col],
            "waste_inflow_tonnes": sipsn[value_col],
            "inflow_basis": "sipsn_2025",
            "data_source_type": "sipsn_2025",
            "source_url": SIPSN_URL,
            "source_document": "sipsn_tpa_facilities_2025.xlsx",
            "extraction_method": "sipsn_2025_facility_inventory",
            "qa_flags": "",
        }
    )

    df = pd.concat([pdd, sipsn_rows], ignore_index=True, sort=False)
    df["country"] = df["landfill_id"].map(site_lookup["country"])
    df["evidence_tier"] = df["landfill_id"].map(site_lookup["evidence_tier"])
    df["opening_year"] = df["landfill_id"].map(site_lookup["opening_year"])
    df["closure_year"] = df["landfill_id"].map(site_lookup["closure_year"])
    df = df.sort_values(["landfill_id", "year", "data_source_type"]).reset_index(
        drop=True
    )
    df.insert(0, "waste_record_id", [f"WST-{i:04d}" for i in range(1, len(df) + 1)])

    def outlier(row: pd.Series) -> str:
        value = pd.to_numeric(row["waste_inflow_tonnes"], errors="coerce")
        return bool_text(pd.notna(value) and value > 5_000_000)

    df["qa_outlier"] = df.apply(outlier, axis=1)
    df["qa_outlier_reason"] = ""
    df.loc[df["qa_outlier"].eq("True"), "qa_outlier_reason"] = (
        "Reported annual inflow exceeds 5 million tonnes; verify against source table."
    )

    def outside_operation(row: pd.Series) -> str:
        year = pd.to_numeric(row["year"], errors="coerce")
        opening = pd.to_numeric(row["opening_year"], errors="coerce")
        closure = pd.to_numeric(row["closure_year"], errors="coerce")
        if pd.isna(year):
            return "False"
        if pd.notna(opening) and year < opening:
            return "True"
        if pd.notna(closure) and year > closure:
            return "True"
        return "False"

    df["qa_year_outside_operation"] = df.apply(outside_operation, axis=1)

    validation = validation.set_index("record_key")
    df["validation_status"] = [
        str(validation.loc[f"{r.landfill_id}|{r.year}", "validation_status"])
        if f"{r.landfill_id}|{r.year}" in validation.index else "not_sampled"
        for r in df.itertuples()
    ]

    notes = []
    for _, row in df.iterrows():
        parts = []
        if row["data_source_type"] == "sipsn_2025":
            parts.append(
                "Site-level 2025 inflow from the SIPSN facility inventory; not part "
                "of the PDD annual series."
            )
        if row["qa_outlier"] == "True":
            parts.append("Large reported inflow; flagged for source verification.")
        if row["qa_year_outside_operation"] == "True":
            parts.append(
                "Year falls outside the recorded opening/closure window; may reflect "
                "a pre-opening waste-history definition or a data-entry issue."
            )
        notes.append(" ".join(parts))
    df["notes"] = notes

    columns = [
        "waste_record_id", "landfill_id", "country", "iso3", "evidence_tier", "year",
        "waste_inflow_tonnes", "inflow_basis", "data_source_type", "source_url",
        "source_document", "extraction_method", "qa_outlier", "qa_outlier_reason",
        "qa_year_outside_operation", "validation_status", "notes",
    ]
    return df[columns].reset_index(drop=True)


def build_composition(sites: pd.DataFrame, projects: pd.DataFrame) -> pd.DataFrame:
    project_map = projects.drop_duplicates("ref").set_index("ref")
    rows = []
    for _, site in sites[sites["waste_composition_fractions"].ne("")].iterrows():
        fractions = json.loads(site["waste_composition_fractions"])
        total = round(sum(float(v) for v in fractions.values()), 6)
        complete = bool_text(0.98 <= total <= 1.02)
        ref = str(site["landfill_id"]).replace("cdm_", "")
        pdd_url = (
            project_map.loc[ref, "pdd_download_url"] if ref in project_map.index else ""
        )
        for category, value in fractions.items():
            rows.append(
                {
                    "landfill_id": site["landfill_id"],
                    "country": site["country"],
                    "iso3": site["iso3"],
                    "category": category,
                    "fraction": float(value),
                    "composition_sum": total,
                    "composition_n_categories": len(fractions),
                    "composition_is_complete": complete,
                    "source_url": pdd_url,
                    "source_document": f"{ref}_pdd.pdf",
                    "extraction_method": "cdm_pdd_composition_table",
                    "qa_note": (
                        "Fractions are as reported and are not renormalised."
                        if complete == "True"
                        else "Fractions do not sum to 1.0 (outside 0.98-1.02); "
                        "retained as reported and flagged, not renormalised."
                    ),
                }
            )
    df = pd.DataFrame(rows)
    df = df.sort_values(["landfill_id", "category"]).reset_index(drop=True)
    df.insert(0, "composition_record_id", [f"WSC-{i:04d}" for i in range(1, len(df) + 1)])
    return df[
        [
            "composition_record_id", "landfill_id", "country", "iso3", "category",
            "fraction", "composition_sum", "composition_n_categories",
            "composition_is_complete", "source_url", "source_document",
            "extraction_method", "qa_note",
        ]
    ]


def build_climate(climate: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    site_lookup = sites.set_index("landfill_id")
    df = climate.rename(
        columns={
            "temperature": "temperature_c",
            "humidity": "humidity_pct",
            "precipitation": "precipitation_mm",
        }
    )
    df["country"] = df["landfill_id"].map(site_lookup["country"])
    return df[
        [
            "landfill_id", "country", "iso3", "year", "latitude", "longitude",
            "temperature_c", "humidity_pct", "precipitation_mm", "n_months",
            "climate_source", "coordinate_source", "qa_climate",
        ]
    ].sort_values(["landfill_id", "year"]).reset_index(drop=True)


def build_integrated(sites: pd.DataFrame, lfg: pd.DataFrame, waste: pd.DataFrame,
                     climate: pd.DataFrame) -> pd.DataFrame:
    rows = []
    lfg_groups = {lid: g for lid, g in lfg.groupby("landfill_id")}
    waste_groups = {lid: g for lid, g in waste.groupby("landfill_id")}
    climate_groups = {lid: g for lid, g in climate.groupby("landfill_id")}

    for _, site in sites.iterrows():
        lid = site["landfill_id"]
        record = site.to_dict()
        lg = lfg_groups.get(lid)
        wg = waste_groups.get(lid)
        cg = climate_groups.get(lid)

        if lg is not None:
            m3 = numeric(lg.loc[lg["lfg_volume_unit"].eq("m3"), "lfg_total_volume"])
            nm3 = numeric(lg.loc[lg["lfg_volume_unit"].eq("Nm3"), "lfg_total_volume"])
            record.update(
                {
                    "lfg_measurement_rows": len(lg),
                    "lfg_measured_year_min": int_or_blank(numeric(lg["year"]).min()),
                    "lfg_measured_year_max": int_or_blank(numeric(lg["year"]).max()),
                    "lfg_total_m3_sum": round(m3.sum(min_count=1), 3) if len(m3) else "",
                    "lfg_total_nm3_sum": round(nm3.sum(min_count=1), 3) if len(nm3) else "",
                    "lfg_rows_unit_not_reported": int(
                        lg["lfg_volume_unit"].eq("not_reported").sum()
                    ),
                    "lfg_volume_unit_mixed": bool_text(
                        lg["lfg_volume_unit"].eq("m3").any()
                        and lg["lfg_volume_unit"].eq("Nm3").any()
                    ),
                    "methane_collected_t_sum": round(
                        numeric(lg["methane_collected_tonnes"]).sum(min_count=1), 3
                    ) if lg["methane_collected_tonnes"].ne("").any() else "",
                    "methane_flared_t_sum": round(
                        numeric(lg["methane_flared_tonnes"]).sum(min_count=1), 3
                    ) if lg["methane_flared_tonnes"].ne("").any() else "",
                    "methane_utilised_t_sum": round(
                        numeric(lg["methane_utilised_tonnes"]).sum(min_count=1), 3
                    ) if lg["methane_utilised_tonnes"].ne("").any() else "",
                }
            )
        else:
            record.update(
                {
                    "lfg_measurement_rows": 0,
                    "lfg_measured_year_min": "",
                    "lfg_measured_year_max": "",
                    "lfg_total_m3_sum": "",
                    "lfg_total_nm3_sum": "",
                    "lfg_rows_unit_not_reported": 0,
                    "lfg_volume_unit_mixed": "False",
                    "methane_collected_t_sum": "",
                    "methane_flared_t_sum": "",
                    "methane_utilised_t_sum": "",
                }
            )

        if wg is not None:
            years = numeric(wg["year"])
            latest_idx = years.idxmax() if years.notna().any() else None
            record.update(
                {
                    "waste_inflow_rows": len(wg),
                    "waste_inflow_year_min": int_or_blank(years.min()),
                    "waste_inflow_year_max": int_or_blank(years.max()),
                    "waste_inflow_sum_available_tonnes": round(
                        numeric(wg["waste_inflow_tonnes"]).sum(min_count=1), 3
                    ),
                    "waste_inflow_latest_year": int_or_blank(years.max()),
                    "waste_inflow_latest_tonnes": (
                        wg.loc[latest_idx, "waste_inflow_tonnes"]
                        if latest_idx is not None else ""
                    ),
                }
            )
        else:
            record.update(
                {
                    "waste_inflow_rows": 0,
                    "waste_inflow_year_min": "",
                    "waste_inflow_year_max": "",
                    "waste_inflow_sum_available_tonnes": "",
                    "waste_inflow_latest_year": "",
                    "waste_inflow_latest_tonnes": "",
                }
            )

        if cg is not None:
            cyears = numeric(cg["year"])
            record.update(
                {
                    "has_climate": "True",
                    "climate_n_years": int(cyears.nunique()),
                    "climate_year_min": int_or_blank(cyears.min()),
                    "climate_year_max": int_or_blank(cyears.max()),
                    "climate_mean_temperature_c": round(
                        numeric(cg["temperature_c"]).mean(), 3
                    ),
                    "climate_mean_humidity_pct": round(
                        numeric(cg["humidity_pct"]).mean(), 3
                    ),
                    "climate_mean_annual_precipitation_mm": round(
                        numeric(cg["precipitation_mm"]).mean(), 3
                    ),
                }
            )
        else:
            record.update(
                {
                    "has_climate": "False",
                    "climate_n_years": 0,
                    "climate_year_min": "",
                    "climate_year_max": "",
                    "climate_mean_temperature_c": "",
                    "climate_mean_humidity_pct": "",
                    "climate_mean_annual_precipitation_mm": "",
                }
            )

        record["has_measured_lfg"] = bool_text(record["lfg_measurement_rows"] > 0)
        record["has_waste_inflow"] = bool_text(record["waste_inflow_rows"] > 0)
        record["has_waste_composition"] = bool_text(
            str(record.get("has_waste_composition", "False")) == "True"
        )
        rows.append(record)

    df = pd.DataFrame(rows)
    leading = [c for c in sites.columns if c in df.columns]
    trailing = [c for c in df.columns if c not in leading]
    return df[leading + trailing].sort_values("landfill_id").reset_index(drop=True)


def build_geojson(sites: pd.DataFrame) -> dict:
    features = []
    for _, row in sites.iterrows():
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "landfill_id": row["landfill_id"],
                    "landfill_name": row["landfill_name"],
                    "country": row["country"],
                    "iso3": row["iso3"],
                    "region": row["region"],
                    "evidence_tier": row["evidence_tier"],
                    "coordinate_source": row["coordinate_source"],
                    "coordinate_quality": row["coordinate_quality"],
                    "opening_year": row["opening_year"],
                    "closure_year": row["closure_year"],
                    "has_metered_lfg": row["has_metered_lfg"],
                    "lfg_measurement_rows": int(row["lfg_measurement_rows"]),
                    "has_waste_inflow": row["has_waste_inflow"],
                    "has_waste_composition": row["has_waste_composition"],
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "asian_cdm_landfills_108",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }


def build_validation_sample(lfg: pd.DataFrame, waste: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in lfg.iterrows():
        rows.append(
            {
                "validation_id": f"VAL-{len(rows) + 1:04d}",
                "table": "lfg_measurements",
                "record_key": f"{row['landfill_id']}|{row['period_start']}|{row['period_end']}",
                "landfill_id": row["landfill_id"],
                "field": "lfg_total_volume",
                "value": row["lfg_total_volume"],
                "period_or_year": f"{row['period_start']} to {row['period_end']}",
                "validation_status": row["validation_status"],
                "validation_pages": row["validation_pages"],
                "source_url": row["source_url"],
                "source_document": row["source_document"],
                "note": (
                    "Value string found in the source PDF text."
                    if row["validation_status"] == "found"
                    else "Value string not found in the source PDF text; treat as unverified."
                ),
            }
        )
    sampled = waste[waste["validation_status"].ne("not_sampled")]
    for _, row in sampled.iterrows():
        rows.append(
            {
                "validation_id": f"VAL-{len(rows) + 1:04d}",
                "table": "waste_inflow_annual",
                "record_key": f"{row['landfill_id']}|{row['year']}",
                "landfill_id": row["landfill_id"],
                "field": "waste_inflow_tonnes",
                "value": row["waste_inflow_tonnes"],
                "period_or_year": row["year"],
                "validation_status": row["validation_status"],
                "validation_pages": "",
                "source_url": row["source_url"],
                "source_document": row["source_document"],
                "note": "Value string found in the source PDD text (random 15-row sample).",
            }
        )
    return pd.DataFrame(rows)


def write_dictionary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []

    def add(table, column, description, unit="", dtype="string", allowed="",
            source="", derivation="", notes=""):
        rows.append(
            {
                "table": table,
                "column": column,
                "description": description,
                "unit": unit,
                "dtype": dtype,
                "allowed_values": allowed,
                "missing_code": "blank",
                "source": source,
                "derivation": derivation,
                "notes": notes,
            }
        )

    def add_table(table, specs):
        for column in tables[table].columns:
            spec = specs.get(column, {})
            add(
                table,
                column,
                spec.get("description", f"Published field: {column}."),
                spec.get("unit", ""),
                spec.get("dtype", "string"),
                spec.get("allowed", ""),
                spec.get("source", ""),
                spec.get("derivation", ""),
                spec.get("notes", ""),
            )

    site_specs = {
        "landfill_id": dict(description="Stable site identifier.", dtype="string", allowed="cdm_<UNFCCC ref>", source="Master site table", derivation="Registry reference with cdm_ prefix."),
        "landfill_name": dict(description="Site/project name as recorded in the CDM documentation."),
        "country": dict(description="Standardised country name.", allowed="Short English country names", source="UNFCCC host party", derivation="Normalised from the UNFCCC host-party name."),
        "country_name_source": dict(description="Country name exactly as recorded in the source.", notes="Kept for traceability."),
        "iso3": dict(description="ISO 3166-1 alpha-3 country code.", allowed="16 Asian country codes"),
        "region": dict(description="Analytical region used in the release.", allowed="East Asia; Southeast Asia; South Asia; Middle East and West Asia; Central Asia"),
        "latitude": dict(description="Site latitude in decimal degrees (WGS84).", unit="degrees_north", dtype="float"),
        "longitude": dict(description="Site longitude in decimal degrees (WGS84).", unit="degrees_east", dtype="float"),
        "coordinate_source": dict(description="Method used to obtain the coordinate.", allowed="pdd_dms; geocoded_city_v2; geocoded_city_v2_offset; geocoded_locality_approx; climate_trace_name_match_proxy; not_reported"),
        "coordinate_quality": dict(description="Harmonised coordinate-quality class.", allowed="reported_in_pdd; geocoded_city; geocoded_city_offset; geocoded_locality_approximate; proxy_name_match; unknown", derivation="Mapped from coordinate_source."),
        "opening_year": dict(description="Year the landfill began operation, as documented.", dtype="integer"),
        "closure_year": dict(description="Year the landfill closed, if documented.", dtype="integer", notes="Blank means not reported, not necessarily still open."),
        "evidence_tier": dict(description="Evidence tier.", allowed="tier_a; tier_b", notes="tier_a = metered LFG series; tier_b = engineering/design documentation without metered LFG."),
        "registry": dict(description="Registry that supplied the site record.", allowed="unfccc_cdm"),
        "registry_ref": dict(description="UNFCCC CDM project reference number.", dtype="integer"),
        "project_title": dict(description="CDM project title."),
        "methodology": dict(description="CDM methodology or methodology combination."),
        "registration_date": dict(description="CDM registration date.", dtype="date", allowed="ISO 8601 YYYY-MM-DD", derivation="Converted from the source format (DD Mon YY)."),
        "cdm_project_url": dict(description="Public UNFCCC CDM project page.", dtype="url"),
        "pdd_url": dict(description="Public URL of the project design document (PDD).", dtype="url", notes="The PDD itself is not redistributed in this release."),
        "design_type": dict(description="Landfill design class reported in the PDD."),
        "liner_type": dict(description="Liner description reported in the PDD."),
        "cover_frequency": dict(description="Cover / intermediate-cover practice reported in the PDD."),
        "leachate_system": dict(description="Leachate management description reported in the PDD."),
        "gas_control_presence": dict(description="Gas-control and utilisation chain reported for the site."),
        "design_capacity_tonnes": dict(description="Design capacity reported in the PDD.", unit="tonnes", dtype="float", notes="Only available for a small subset of sites."),
        "annual_waste_inflow_reported_tonnes": dict(description="Site-level annual waste inflow from the most recent PDD year or SIPSN 2025.", unit="tonnes/year", dtype="float", notes="This is a site-level reference value, not a complete annual series. Use waste_inflow_annual.csv for the series."),
        "annual_inflow_reference_year": dict(description="Year of the site-level annual inflow value.", dtype="integer"),
        "annual_inflow_basis": dict(description="Basis of the site-level annual inflow value.", allowed="pdd_table_last_year; sipsn_2025; not_reported"),
        "waste_source_type": dict(description="Waste stream type reported.", allowed="municipal_solid_waste; industrial"),
        "waste_history_years": dict(description="Documented waste-placement history length.", unit="years", dtype="float"),
        "waste_tonnes_cumulative": dict(description="Cumulative waste placed, as documented.", unit="tonnes", dtype="float"),
        "cumulative_is_complete": dict(description="Whether the cumulative waste value is documented as a complete lifetime total.", allowed="True; False"),
        "collection_efficiency": dict(description="Landfill-gas collection efficiency.", unit="fraction", dtype="float", allowed="0-1"),
        "collection_efficiency_basis": dict(description="Basis of the collection-efficiency value.", allowed="measured; reported; assumed; not_reported"),
        "qa_collection_efficiency": dict(description="QA status of the collection-efficiency value.", allowed="measured; reported; assumed; not_reported", derivation="Set to collection_efficiency_basis when a value exists, otherwise not_reported."),
        "has_metered_lfg": dict(description="Whether the site has at least one metered LFG row in the release.", allowed="True; False"),
        "n_metered_periods": dict(description="Number of metered monitoring periods in the master observation table.", dtype="integer"),
        "n_monitoring_reports": dict(description="Number of CDM monitoring reports available for the site.", dtype="integer"),
        "data_source_type": dict(description="Source-document combination used for the site.", allowed="cdm_pdd; cdm_pdd+cdm_mr"),
        "provenance_reference": dict(description="Human-readable provenance string from the master table."),
        "qa_waste_history": dict(description="QA status of the waste-history fields.", allowed="ok; short; unknown"),
        "qa_composition": dict(description="QA status of the waste-composition record.", allowed="reported; not_reported"),
        "qa_provenance": dict(description="QA status of the provenance record.", allowed="ok"),
        "source_notes": dict(description="Short source note from the master table."),
        "has_waste_composition": dict(description="Whether the site has a waste-composition record.", allowed="True; False"),
        "composition_n_categories": dict(description="Number of waste categories in the site composition record.", dtype="integer"),
        "composition_sum": dict(description="Sum of reported waste-composition fractions.", unit="fraction", dtype="float", notes="Not forced to 1.0."),
        "composition_is_complete": dict(description="Whether composition_sum is within 0.98-1.02.", allowed="True; False"),
        "waste_inflow_rows": dict(description="Number of annual waste-inflow rows in waste_inflow_annual.csv.", dtype="integer"),
        "waste_inflow_year_min": dict(description="First year in the annual waste-inflow series.", dtype="integer"),
        "waste_inflow_year_max": dict(description="Last year in the annual waste-inflow series.", dtype="integer"),
        "lfg_measurement_rows": dict(description="Number of measured LFG rows in lfg_measurements.csv.", dtype="integer"),
        "lfg_measured_year_min": dict(description="First measurement year.", dtype="integer"),
        "lfg_measured_year_max": dict(description="Last measurement year.", dtype="integer"),
        "has_any_observation": dict(description="Whether any source observation row exists for the site.", allowed="True; False"),
        "has_waste_inflow": dict(description="Whether the site has at least one annual waste-inflow row.", allowed="True; False"),
        "n_source_observation_rows": dict(description="Legacy count of mixed-grain source observation rows.", dtype="integer"),
    }
    add_table("sites_108.csv", site_specs)

    lfg_specs = {
        "observation_id": dict(description="Stable release identifier for the measured LFG row.", allowed="LFG-0001 ..."),
        "landfill_id": dict(description="Site identifier."),
        "country": dict(description="Standardised country name."),
        "iso3": dict(description="ISO 3166-1 alpha-3 country code."),
        "evidence_tier": dict(description="Evidence tier of the site.", allowed="tier_a"),
        "year": dict(description="Year assigned from the monitoring-period start.", dtype="integer", notes="A period spanning two calendar years is assigned to its start year."),
        "period_start": dict(description="Monitoring-period start date.", dtype="date"),
        "period_end": dict(description="Monitoring-period end date.", dtype="date"),
        "period_days": dict(description="Monitoring-period length.", unit="days", dtype="integer"),
        "period_source": dict(description="How the period was obtained.", allowed="text; text_words; fallback; not_found"),
        "lfg_total_volume": dict(description="Total landfill-gas volume reported for the monitoring period.", unit="m3 or Nm3 as stated in lfg_volume_unit", dtype="float", notes="Not converted; unit is reported per row."),
        "lfg_volume_unit": dict(description="Volume unit exactly as reported.", allowed="m3; Nm3; not_reported", notes="m3 and Nm3 are not mixed or converted."),
        "lfg_flared_volume": dict(description="Landfill-gas volume flared in the period.", unit="same as lfg_volume_unit", dtype="float"),
        "lfg_utilised_volume": dict(description="Landfill-gas volume utilised in the period.", unit="same as lfg_volume_unit", dtype="float"),
        "ch4_fraction": dict(description="Methane concentration reported for the period.", unit="fraction", dtype="float", notes="May be a percentage in the source; value retained as supplied in the master table."),
        "methane_collected_tonnes": dict(description="Methane collected in the period, as derived in the master pipeline.", unit="tonnes CH4", dtype="float"),
        "methane_flared_tonnes": dict(description="Methane flared in the period.", unit="tonnes CH4", dtype="float"),
        "methane_utilised_tonnes": dict(description="Methane utilised in the period.", unit="tonnes CH4", dtype="float"),
        "methane_collected_tonnes_per_year": dict(description="Annualised collected methane where the pipeline could derive it.", unit="tonnes CH4/year", dtype="float"),
        "collection_efficiency": dict(description="Site-level collection efficiency attached to the row.", unit="fraction", dtype="float"),
        "collection_efficiency_basis": dict(description="Basis of the attached collection efficiency.", allowed="measured; reported; assumed; not_reported"),
        "source_url": dict(description="Public URL of the monitoring report used for the row.", dtype="url"),
        "source_document": dict(description="Downloaded monitoring-report filename."),
        "source_manifest_label": dict(description="Document label from the CDM document manifest.", notes="The filename/label can differ from the period inside the report."),
        "cdm_project_url": dict(description="Public UNFCCC CDM project page.", dtype="url"),
        "extraction_method": dict(description="Extraction route used.", allowed="cdm_monitoring_report_table_or_text"),
        "qa_flags": dict(description="Semicolon-separated QA flags from the master pipeline."),
        "qa_filename_period_mismatch": dict(description="Whether the filename dates disagree with the monitoring period read from the report text.", allowed="True; False", notes="The period column is authoritative; the filename is not."),
        "qa_period_multi_year": dict(description="Whether the period is longer than 366 days.", allowed="True; False"),
        "qa_period_partial_year": dict(description="Whether the period covers only part of a year.", allowed="True; False"),
        "qa_unit": dict(description="Whether the volume unit was stated.", allowed="reported; not_reported"),
        "qa_outlier": dict(description="Whether the reported volume exceeds 100 million m3.", allowed="True; False"),
        "qa_outlier_reason": dict(description="Reason for the outlier flag."),
        "validation_status": dict(description="Result of searching the source PDF text for the reported value.", allowed="found; not_found; blank"),
        "validation_pages": dict(description="PDF page numbers where the value string was found.", notes="Semicolon-separated; blank when not found."),
        "notes": dict(description="Row-level release note."),
    }
    add_table("lfg_measurements.csv", lfg_specs)

    waste_specs = {
        "waste_record_id": dict(description="Stable release identifier for the annual waste-inflow row.", allowed="WST-0001 ..."),
        "landfill_id": dict(description="Site identifier."),
        "country": dict(description="Standardised country name."),
        "iso3": dict(description="ISO 3166-1 alpha-3 country code."),
        "evidence_tier": dict(description="Evidence tier of the site.", allowed="tier_a; tier_b"),
        "year": dict(description="Calendar year of the waste inflow.", dtype="integer"),
        "waste_inflow_tonnes": dict(description="Waste accepted in the year.", unit="tonnes/year", dtype="float"),
        "inflow_basis": dict(description="Basis of the annual value.", allowed="pdd_table; sipsn_2025"),
        "data_source_type": dict(description="Source table type.", allowed="cdm_pdd_table; sipsn_2025"),
        "source_url": dict(description="Public URL of the PDD or national inventory.", dtype="url"),
        "source_document": dict(description="Source filename or inventory name."),
        "extraction_method": dict(description="Extraction route used.", allowed="cdm_pdd_table; sipsn_2025_facility_inventory"),
        "qa_outlier": dict(description="Whether annual inflow exceeds 5 million tonnes.", allowed="True; False"),
        "qa_outlier_reason": dict(description="Reason for the outlier flag."),
        "qa_year_outside_operation": dict(description="Whether the year falls outside the recorded opening/closure window.", allowed="True; False"),
        "validation_status": dict(description="PDF-text validation status for the random sample.", allowed="found; not_found; not_sampled"),
        "notes": dict(description="Row-level release note."),
    }
    add_table("waste_inflow_annual.csv", waste_specs)

    comp_specs = {
        "composition_record_id": dict(description="Stable release identifier for the composition row.", allowed="WSC-0001 ..."),
        "landfill_id": dict(description="Site identifier."),
        "country": dict(description="Standardised country name."),
        "iso3": dict(description="ISO 3166-1 alpha-3 country code."),
        "category": dict(description="Waste category.", allowed="food; paper; wood; textile; plastic; glass; metal; other"),
        "fraction": dict(description="Reported mass fraction for the category.", unit="fraction", dtype="float", notes="Not renormalised."),
        "composition_sum": dict(description="Sum of all categories for the site.", unit="fraction", dtype="float"),
        "composition_n_categories": dict(description="Number of categories for the site.", dtype="integer"),
        "composition_is_complete": dict(description="Whether composition_sum is within 0.98-1.02.", allowed="True; False"),
        "source_url": dict(description="Public URL of the PDD.", dtype="url"),
        "source_document": dict(description="PDD filename."),
        "extraction_method": dict(description="Extraction route used.", allowed="cdm_pdd_composition_table"),
        "qa_note": dict(description="Completeness note."),
    }
    add_table("waste_composition.csv", comp_specs)

    climate_specs = {
        "landfill_id": dict(description="Site identifier."),
        "country": dict(description="Standardised country name."),
        "iso3": dict(description="ISO 3166-1 alpha-3 country code."),
        "year": dict(description="Calendar year.", dtype="integer"),
        "latitude": dict(description="Latitude used for the climate query.", unit="degrees_north", dtype="float"),
        "longitude": dict(description="Longitude used for the climate query.", unit="degrees_east", dtype="float"),
        "temperature_c": dict(description="Annual mean air temperature.", unit="degrees Celsius", dtype="float", source="NASA POWER"),
        "humidity_pct": dict(description="Annual mean relative humidity.", unit="percent", dtype="float", source="NASA POWER"),
        "precipitation_mm": dict(description="Annual precipitation total.", unit="mm/year", dtype="float", source="NASA POWER"),
        "n_months": dict(description="Number of months contributing to the annual value.", dtype="integer", notes="12 indicates a complete year."),
        "climate_source": dict(description="Climate data product/API."),
        "coordinate_source": dict(description="Coordinate source used for the climate query."),
        "qa_climate": dict(description="Climate completeness flag.", allowed="complete; partial"),
    }
    add_table("climate_annual.csv", climate_specs)

    integrated_specs = dict(site_specs)
    integrated_specs.update(
        {
            "lfg_total_m3_sum": dict(description="Sum of reported LFG volumes where the unit is m3.", unit="m3", dtype="float", notes="Sum of monitoring-period volumes, not an annual rate; not comparable with Nm3 rows."),
            "lfg_total_nm3_sum": dict(description="Sum of reported LFG volumes where the unit is Nm3.", unit="Nm3", dtype="float", notes="Sum of monitoring-period volumes, not an annual rate."),
            "lfg_rows_unit_not_reported": dict(description="Number of measured rows with no volume unit.", dtype="integer"),
            "lfg_volume_unit_mixed": dict(description="Whether the site has both m3 and Nm3 rows.", allowed="True; False"),
            "methane_collected_t_sum": dict(description="Sum of measured methane collected.", unit="tonnes CH4", dtype="float"),
            "methane_flared_t_sum": dict(description="Sum of measured methane flared.", unit="tonnes CH4", dtype="float"),
            "methane_utilised_t_sum": dict(description="Sum of measured methane utilised.", unit="tonnes CH4", dtype="float"),
            "waste_inflow_sum_available_tonnes": dict(description="Sum of annual inflow across available years.", unit="tonnes", dtype="float", notes="Available-year sum, not a lifetime total and not adjusted for missing years."),
            "waste_inflow_latest_year": dict(description="Latest year with an annual inflow value.", dtype="integer"),
            "waste_inflow_latest_tonnes": dict(description="Annual inflow in the latest available year.", unit="tonnes/year", dtype="float"),
            "has_climate": dict(description="Whether climate rows exist for the site.", allowed="True; False"),
            "climate_n_years": dict(description="Number of climate site-years.", dtype="integer"),
            "climate_year_min": dict(description="First climate year.", dtype="integer"),
            "climate_year_max": dict(description="Last climate year.", dtype="integer"),
            "climate_mean_temperature_c": dict(description="Mean annual temperature across available climate years.", unit="degrees Celsius", dtype="float"),
            "climate_mean_humidity_pct": dict(description="Mean annual relative humidity across available climate years.", unit="percent", dtype="float"),
            "climate_mean_annual_precipitation_mm": dict(description="Mean annual precipitation across available climate years.", unit="mm/year", dtype="float"),
        }
    )
    add_table("integrated_sites_108.csv", integrated_specs)

    validation_specs = {
        "validation_id": dict(description="Stable validation-sample identifier.", allowed="VAL-0001 ..."),
        "table": dict(description="Release table that was checked.", allowed="lfg_measurements; waste_inflow_annual"),
        "record_key": dict(description="Source record key used for the lookup."),
        "landfill_id": dict(description="Site identifier."),
        "field": dict(description="Field that was checked.", allowed="lfg_total_volume; waste_inflow_tonnes"),
        "value": dict(description="Value searched for in the source PDF text."),
        "period_or_year": dict(description="Monitoring period or calendar year of the checked value."),
        "validation_status": dict(description="Result of the PDF-text search.", allowed="found; not_found"),
        "validation_pages": dict(description="PDF pages where the value string was found.", notes="Semicolon-separated; blank when not found."),
        "source_url": dict(description="Public source URL.", dtype="url"),
        "source_document": dict(description="Source filename."),
        "note": dict(description="Human-readable validation note."),
    }
    add_table("qa_validation_sample.csv", validation_specs)

    df = pd.DataFrame(rows)
    # Safety net: every published column must have a dictionary row.
    for table, frame in tables.items():
        existing = set(df.loc[df["table"].eq(table), "column"])
        for column in frame.columns:
            if column not in existing:
                add(table, column, f"Published field: {column}.")
    return pd.DataFrame(rows)


def write_sources(path: Path) -> None:
    text = f"""# Sources and attribution

This release is a **derived compilation**. The raw PDFs, workbooks and API
responses are not redistributed. Each derived row links to a public source URL
where one is available.

## Primary sources

| Source | What it supplied | URL | Access |
|---|---|---|---|
| UNFCCC CDM project search | Project identity, host party, methodology, registration date, PDD and monitoring-report links | {CDM_SEARCH_URL} | Public web/PDF |
| UNFCCC CDM project design documents (PDDs) | Design attributes, waste history, composition, collection efficiency, annual waste inflow | Project-specific URLs in `sites_108.csv` (`pdd_url`) and `waste_inflow_annual.csv` (`source_url`) | Public PDF |
| UNFCCC CDM monitoring reports | Metered LFG volume, flared/utilised volume, methane concentration, methane masses | Project-specific URLs in `lfg_measurements.csv` (`source_url`) | Public PDF |
| NASA POWER | Annual temperature, relative humidity and precipitation for 2010-2025 | {NASA_POWER_URL} | Public API |
| Climate TRACE | Asia-wide landfill site spine and coordinates only | {CLIMATE_TRACE_URL} | Public API/bulk |
| SIPSN (Indonesia) | 2025 site-level waste inflow for two Indonesian sites | {SIPSN_URL} | Public portal/Excel |
| OpenStreetMap Nominatim | Geocoding of site localities where PDD coordinates were missing | {NOMINATIM_URL} | Public API, rate-limited |
| CDM landfill-detail workbooks (refs 1582, 2518, 2525) | Applied engineering covariates and null-fills, with audit trail | UNFCCC CDM project attachments | Public PDF/XLS |

## What is *not* redistributed

- Raw PDDs, monitoring reports and attachment PDFs.
- The original SIPSN workbook.
- The original Climate TRACE and NASA POWER API responses.
- Internal extraction logs and local file paths.

The release publishes **extracted facts, source URLs, QA flags and derived
tables** only. Users who need the original documents should retrieve them from
the URLs in the tables, subject to the source terms.

## Attribution

If you use this dataset, please cite the dataset (see `CITATION.cff`) and
acknowledge the underlying sources:

- **UNFCCC CDM** for project design documents and monitoring reports.
- **NASA POWER** for climate covariates.
- **Climate TRACE** for the site spine and coordinates used during assembly.
- **SIPSN / Ministry of Environment of Indonesia** for the 2025 facility inflow values.
- **OpenStreetMap contributors** for geocoding where used.

## Licensing of source material

The release compilation is offered under CC BY 4.0 (see `LICENSE-DATA`). Source
documents remain subject to the terms of their publishers. This release does not
grant rights to redistribute those source documents. Check the UNFCCC CDM,
SIPSN, NASA POWER and Climate TRACE terms before reusing source material.

## Citation of the dataset

Use the DOI assigned by Zenodo once the record is published. Until then, cite the
version and URL in `CITATION.cff`.
"""
    path.write_text(text, encoding="utf-8")


def write_qa_report(path: Path, sites: pd.DataFrame, lfg: pd.DataFrame,
                    waste: pd.DataFrame, composition: pd.DataFrame,
                    climate: pd.DataFrame, validation: pd.DataFrame,
                    master_hashes: dict) -> None:
    countries = sites["iso3"].nunique()
    tier_a = int(sites["evidence_tier"].eq("tier_a").sum())
    tier_b = int(sites["evidence_tier"].eq("tier_b").sum())
    lfg_found = int(lfg["validation_status"].eq("found").sum())
    lfg_not_found = int(lfg["validation_status"].eq("not_found").sum())
    waste_found = int(
        waste[waste["validation_status"].ne("not_sampled")]["validation_status"]
        .eq("found")
        .sum()
    )
    waste_sampled = int(waste["validation_status"].ne("not_sampled").sum())
    outliers = lfg[lfg["qa_outlier"].eq("True")]
    waste_outliers = waste[waste["qa_outlier"].eq("True")]

    def pct(n, d):
        return f"{100 * n / d:.1f}%"

    lines = [
        "# QA report - release v1.0",
        "",
        f"Release date: **{RELEASE_DATE}**",
        "",
        "## Release counts",
        "",
        "| Table | Rows | Grain |",
        "|---|---:|---|",
        f"| `sites_108.csv` | {len(sites)} | one row per site |",
        f"| `lfg_measurements.csv` | {len(lfg)} | one row per measured monitoring period |",
        f"| `waste_inflow_annual.csv` | {len(waste)} | one row per site-year |",
        f"| `waste_composition.csv` | {len(composition)} | one row per site-category |",
        f"| `climate_annual.csv` | {len(climate)} | one row per site-year |",
        f"| `integrated_sites_108.csv` | {len(sites)} | one row per site |",
        "",
        f"- Sites: **{len(sites)}** across **{countries}** countries.",
        f"- Tier A (metered LFG): **{tier_a}**; Tier B (engineering only): **{tier_b}**.",
        f"- Measured LFG rows: **{len(lfg)}** across **{lfg['landfill_id'].nunique()}** sites.",
        f"- Annual waste-inflow rows: **{len(waste)}** across **{waste['landfill_id'].nunique()}** sites.",
        f"- Sites with waste composition: **{sites['has_waste_composition'].eq('True').sum()}**.",
        f"- Sites with climate: **{len(climate)}** site-years across **{climate['landfill_id'].nunique()}** sites.",
        "",
        "## Fixes applied for this release",
        "",
        "1. **Mixed grains split.** The 609-row master observation table mixed PDD annual waste inflow with monitoring-period LFG measurements. v1.0 publishes separate `waste_inflow_annual.csv` and `lfg_measurements.csv` tables.",
        "2. **Units kept honest.** `lfg_total_nm3` was renamed to `lfg_total_volume` and paired with `lfg_volume_unit`. Values are **not** converted between `m3` and `Nm3` because the source reports do not contain the temperature/pressure needed for a defensible conversion.",
        "3. **Collection-efficiency QA fixed.** Five sites had `ce_basis` and `qa_ce` disagreeing. The release uses one `collection_efficiency_basis` and derives `qa_collection_efficiency` from it.",
        "4. **Composition validated, not renormalised.** Every site composition has a `composition_sum` and `composition_is_complete` flag. Fractions outside 0.98-1.02 are retained and flagged.",
        "5. **Country names standardised.** UNFCCC names such as 'Viet Nam', 'Iran (Islamic Republic of)' and 'Republic of Korea' were mapped to short names while retaining the original in `country_name_source`.",
        "6. **Registration dates normalised.** All 108 dates were converted to ISO 8601.",
        "7. **Empty `city` column dropped.** It was 100% empty.",
        "8. **Stable IDs and source URLs added.** Every measured row has an `observation_id` and public source URL; every waste row has a `waste_record_id` and source URL.",
        "9. **Outliers flagged, not silently removed.** LFG volumes above 100 million m3 and annual inflows above 5 million tonnes are flagged in `qa_outlier`.",
        "10. **PDF-text validation.** All 48 measured LFG values were searched in the source PDF text. 47 were found; the one failure is the `cdm_839` 910.8 million m3 outlier. A random 15-row waste-inflow sample was also checked; 15/15 were found.",
        "11. **Filename mismatch documented.** Many monitoring-report filenames do not match the period inside the PDF. The period columns were extracted from the report text, which is authoritative; the mismatch is exposed as `qa_filename_period_mismatch`.",
        "",
        "## Validation",
        "",
        f"- Measured LFG values found in source PDF text: **{lfg_found} of {lfg_found + lfg_not_found}**.",
        f"- Random waste-inflow sample found in PDD text: **{waste_found} of {waste_sampled}**.",
        "- Validation means the value string was found in the extracted PDF text; it is not a full independent re-extraction of every table.",
        "- The detailed sample is in `data/qa_validation_sample.csv`.",
        "",
        "## Known outliers and unresolved items",
        "",
    ]

    if len(outliers):
        lines.append("### LFG volume outliers")
        lines.append("")
        lines.append("| Site | Period | Reported volume | Unit | Validation |")
        lines.append("|---|---|---:|---|---|")
        for _, row in outliers.iterrows():
            lines.append(
                f"| {row['landfill_id']} | {row['period_start']} to {row['period_end']} | "
                f"{row['lfg_total_volume']} | {row['lfg_volume_unit']} | {row['validation_status']} |"
            )
        lines.append("")
        lines.append(
            "`cdm_839` reports 910,802,000 m3 for 2010-02-02 to 2012-06-30. "
            "That value was **not found** in the extracted PDF text; the visible "
            "table shows values around 10.8 million m3. Treat this row as unverified "
            "and exclude it from analysis until it is checked against the source table."
        )
        lines.append("")
    else:
        lines.append("No LFG outliers above the threshold.")
        lines.append("")

    if len(waste_outliers):
        lines.append("### Annual waste-inflow outliers")
        lines.append("")
        lines.append("| Site | Year | Inflow (t/year) |")
        lines.append("|---|---:|---:|")
        for _, row in waste_outliers.iterrows():
            lines.append(
                f"| {row['landfill_id']} | {row['year']} | {row['waste_inflow_tonnes']} |"
            )
        lines.append("")
        lines.append(
            "These may be legitimate mega-site values or extraction/cumulative-vs-annual "
            "errors. They are flagged, not removed."
        )
        lines.append("")

    outside = waste[waste["qa_year_outside_operation"].eq("True")]
    lines.extend(
        [
            "### Other known limitations",
            "",
            f"- **{len(outside)} annual waste-inflow rows** fall outside the recorded opening/closure window. They are flagged in `qa_year_outside_operation`.",
            f"- **{int(sites['has_metered_lfg'].eq('False').sum())} of {len(sites)} sites have no metered LFG.** They are engineering/design records, not measurement sites.",
            "- Measured LFG is **recovered/collected gas**, not total methane generated or emitted. Fugitive emissions and oxidation are not measured.",
            "- The sample is **CDM-selected** and not a representative sample of Asian landfills.",
            "- Coordinates are mixed quality: only a subset come directly from PDD coordinates; many are geocoded approximations or proxy matches.",
            "- Some fields are very sparse: design capacity (7/108), cover frequency (14/108), liner type (34/108). They are retained as optional engineering descriptors.",
            "- Climate values are reanalysis-model outputs from NASA POWER, not site measurements.",
            "",
            "## What this release must not be used for",
            "",
            "**Do not use this dataset to estimate country-level methane emissions.** "
            "It is a CDM-selected site sample, not a national landfill inventory. "
            "It lacks a complete site universe, representative sampling, activity-data "
            "time series, IPCC FOD parameters, fugitive-emission measurements and an "
            "uncertainty framework. It can support site-level case studies, model "
            "calibration, feasibility screening and validation layers.",
            "",
            "## Master-file integrity",
            "",
            "The release is derived from the frozen master tables below. Their SHA256 "
            "hashes are recorded here so users can confirm the release was built from "
            "the intended inputs.",
            "",
            "| Master file | SHA256 |",
            "|---|---|",
        ]
    )
    for name, digest in master_hashes.items():
        lines.append(f"| `data/processed/{name}` | `{digest}` |")
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```bash",
            "python scripts/16_build_release.py",
            "pytest -q",
            "```",
            "",
            "The builder reads the master tables and never modifies them. PDF-text "
            "validation is cached in `data/interim/release/` so the release can be rebuilt "
            "without the raw PDF archive; delete the cache and rerun with the PDFs present "
            "to re-validate.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(path: Path) -> None:
    rows = []
    for file in sorted(RELEASE.rglob("*")):
        if not file.is_file() or file.name == "manifest.csv":
            continue
        rel = file.relative_to(RELEASE).as_posix()
        row = {
            "path": rel,
            "bytes": file.stat().st_size,
            "sha256": hash_file(file),
            "rows": "",
            "columns": "",
        }
        if file.suffix == ".csv" and file.parent == DATA_OUT:
            frame = pd.read_csv(file, dtype=str, keep_default_na=False)
            row["rows"] = len(frame)
            row["columns"] = len(frame.columns)
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False)


def main() -> None:
    sites_master = read_csv(PROCESSED / "sites.csv")
    obs = read_csv(PROCESSED / "annual_observations.csv")
    climate_master = read_csv(PROCESSED / "climate.csv")
    projects = read_csv(INTERIM / "cdm" / "cdm_projects_asia.csv")
    manifest = read_csv(INTERIM / "cdm" / "cdm_document_manifest.csv")

    if len(sites_master) != 108:
        raise SystemExit(f"expected 108 sites, found {len(sites_master)}")

    projects["ref"] = projects["ref"].astype(str)
    projects = projects.drop_duplicates("ref")
    url_by_path = {
        norm_path(row.path): row.url
        for row in manifest.itertuples()
        if str(row.url).strip()
    }
    label_by_path = {
        norm_path(row.path): row.label
        for row in manifest.itertuples()
        if str(row.label).strip()
    }
    project_url_by_ref = dict(zip(projects["ref"], projects["project_url"]))

    val_lfg_path = INTERIM / "release" / "validation_lfg.csv"
    val_waste_path = INTERIM / "release" / "validation_waste.csv"
    validation_lfg = read_csv(val_lfg_path) if val_lfg_path.exists() else pd.DataFrame(
        columns=["record_key", "validation_status", "validation_pages"]
    )
    validation_waste = read_csv(val_waste_path) if val_waste_path.exists() else pd.DataFrame(
        columns=["record_key", "validation_status", "validation_pages"]
    )

    if DATA_OUT.exists():
        shutil.rmtree(DATA_OUT)
    DATA_OUT.mkdir(parents=True, exist_ok=True)

    # Intermediate tables needed for site summaries.
    composition = build_composition(sites_master, projects)
    lfg = build_lfg(
        obs,
        build_sites(sites_master, projects, pd.DataFrame(), pd.DataFrame(), composition),
        url_by_path,
        label_by_path,
        project_url_by_ref,
        validation_lfg,
    )
    waste = build_waste(obs, sites_master, projects, validation_waste)
    sites = build_sites(sites_master, projects, waste, lfg, composition)
    climate = build_climate(climate_master, sites)
    integrated = build_integrated(sites, lfg, waste, climate)

    # Rebuild lfg/waste with final site attributes for country/tier consistency.
    lfg = build_lfg(
        obs, sites, url_by_path, label_by_path, project_url_by_ref, validation_lfg
    )
    waste = build_waste(obs, sites, projects, validation_waste)

    tables = {
        "sites_108.csv": sites,
        "lfg_measurements.csv": lfg,
        "waste_inflow_annual.csv": waste,
        "waste_composition.csv": composition,
        "climate_annual.csv": climate,
        "integrated_sites_108.csv": integrated,
    }
    for name, frame in tables.items():
        frame.to_csv(DATA_OUT / name, index=False)

    geojson = build_geojson(sites)
    (DATA_OUT / "sites_108.geojson").write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    validation = build_validation_sample(lfg, waste)
    validation.to_csv(DATA_OUT / "qa_validation_sample.csv", index=False)

    dictionary = write_dictionary({**tables, "qa_validation_sample.csv": validation})
    dictionary.to_csv(RELEASE / "DATA_DICTIONARY.csv", index=False)

    master_hashes = {
        name: hash_file(PROCESSED / name)
        for name in ["sites.csv", "annual_observations.csv", "climate.csv"]
    }
    write_qa_report(
        RELEASE / "QA_REPORT.md",
        sites,
        lfg,
        waste,
        composition,
        climate,
        validation,
        master_hashes,
    )
    write_sources(RELEASE / "SOURCES.md")
    write_manifest(RELEASE / "manifest.csv")

    print(f"built {RELEASE}")
    print(f"  sites={len(sites)} lfg={len(lfg)} waste={len(waste)} "
          f"composition={len(composition)} climate={len(climate)}")
    print(f"  validation rows={len(validation)} found="
          f"{int(validation['validation_status'].eq('found').sum())} "
          f"not_found={int(validation['validation_status'].eq('not_found').sum())}")


if __name__ == "__main__":
    main()
