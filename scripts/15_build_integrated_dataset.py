#!/usr/bin/env python3
"""Build the integrated 108-site deliverable without touching the source files.

Outputs
-------
data/processed/integrated/sites_108_integrated.csv   one row per site
data/processed/integrated/sites_108_integrated.xlsx  Sites + observations + climate
data/processed/integrated/README.md                  column guide and caveats

The existing ``sites.csv``, ``annual_observations.csv`` and ``climate.csv`` are
read-only inputs and are never modified.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
OUT = PROCESSED / "integrated"


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.replace("", pd.NA), errors="coerce")


def clean_join(values: pd.Series) -> str:
    return "; ".join(sorted({str(v).strip() for v in values if str(v).strip()}))


def observation_summary(obs: pd.DataFrame) -> pd.DataFrame:
    measured = obs[obs["is_measured"].astype(str).str.lower() == "true"].copy()
    rows = []
    for lid, group in obs.groupby("landfill_id", sort=False):
        m = measured[measured["landfill_id"] == lid]
        years = numeric(group["year"]).dropna()
        rows.append(
            {
                "landfill_id": lid,
                "obs_n_rows": len(group),
                "obs_n_years": int(years.nunique()) if len(years) else 0,
                "obs_year_min": int(years.min()) if len(years) else "",
                "obs_year_max": int(years.max()) if len(years) else "",
                "obs_n_measured_rows": len(m),
                "obs_lfg_total_nm3_sum": round(
                    numeric(m["lfg_total_nm3"]).sum(min_count=1), 3
                )
                if m["lfg_total_nm3"].ne("").any()
                else "",
                "obs_methane_collected_t_sum": round(
                    numeric(m["methane_collected_tonnes"]).sum(min_count=1), 3
                )
                if m["methane_collected_tonnes"].ne("").any()
                else "",
                "obs_methane_flared_t_sum": round(
                    numeric(m["methane_flared_tonnes"]).sum(min_count=1), 3
                )
                if m["methane_flared_tonnes"].ne("").any()
                else "",
                "obs_methane_utilised_t_sum": round(
                    numeric(m["methane_utilised_tonnes"]).sum(min_count=1), 3
                )
                if m["methane_utilised_tonnes"].ne("").any()
                else "",
                "obs_sources": clean_join(group["data_source_type"]),
                "obs_qa_flags": clean_join(group["qa_flags"]),
            }
        )
    return pd.DataFrame(rows)


def climate_summary(climate: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lid, group in climate.groupby("landfill_id", sort=False):
        years = numeric(group["year"]).dropna()
        rows.append(
            {
                "landfill_id": lid,
                "climate_n_years": int(years.nunique()) if len(years) else 0,
                "climate_year_min": int(years.min()) if len(years) else "",
                "climate_year_max": int(years.max()) if len(years) else "",
                "climate_mean_temperature_c": round(
                    numeric(group["temperature"]).mean(), 3
                ),
                "climate_mean_humidity_pct": round(
                    numeric(group["humidity"]).mean(), 3
                ),
                "climate_mean_annual_precipitation_mm": round(
                    numeric(group["precipitation"]).mean(), 3
                ),
                "climate_sources": clean_join(group["climate_source"]),
                "climate_qa": clean_join(group["qa_climate"]),
            }
        )
    return pd.DataFrame(rows)


def build() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sites = pd.read_csv(PROCESSED / "sites.csv", dtype=str, keep_default_na=False)
    obs = pd.read_csv(
        PROCESSED / "annual_observations.csv", dtype=str, keep_default_na=False
    )
    climate = pd.read_csv(
        PROCESSED / "climate.csv", dtype=str, keep_default_na=False
    )
    if len(sites) != 108:
        raise SystemExit(f"expected 108 sites, found {len(sites)}")

    integrated = (
        sites.merge(observation_summary(obs), on="landfill_id", how="left")
        .merge(climate_summary(climate), on="landfill_id", how="left")
    )
    integrated["has_lfg_observations"] = (
        pd.to_numeric(integrated["obs_n_measured_rows"], errors="coerce")
        .fillna(0)
        .gt(0)
        .map({True: "True", False: "False"})
    )
    integrated["has_climate"] = (
        pd.to_numeric(integrated["climate_n_years"], errors="coerce")
        .fillna(0)
        .gt(0)
        .map({True: "True", False: "False"})
    )
    if len(integrated) != 108 or integrated["landfill_id"].nunique() != 108:
        raise SystemExit("integrated table is not one row per site")
    return integrated, obs, climate


def write_xlsx(integrated: pd.DataFrame, obs: pd.DataFrame,
               climate: pd.DataFrame) -> None:
    path = OUT / "sites_108_integrated.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        integrated.to_excel(writer, sheet_name="Sites", index=False)
        obs.to_excel(writer, sheet_name="Annual Observations", index=False)
        climate.to_excel(writer, sheet_name="Climate", index=False)
        for name, frame in [
            ("Sites", integrated),
            ("Annual Observations", obs),
            ("Climate", climate),
        ]:
            sheet = writer.sheets[name]
            sheet.freeze_panes = "A2"
            for idx, column in enumerate(frame.columns, start=1):
                width = max(10, min(42, len(str(column)) + 2))
                sheet.column_dimensions[
                    sheet.cell(row=1, column=idx).column_letter
                ].width = width


def write_readme(integrated: pd.DataFrame, obs: pd.DataFrame,
                 climate: pd.DataFrame) -> None:
    measured = pd.to_numeric(
        integrated["obs_n_measured_rows"], errors="coerce"
    ).fillna(0)
    lines = [
        "# Integrated 108-site dataset",
        "",
        f"- Sites: **{len(integrated)}** (one row per site)",
        f"- Annual observation rows: **{len(obs)}**",
        f"- Climate site-years: **{len(climate)}**",
        f"- Sites with measured LFG observations: **{int((measured > 0).sum())}**",
        f"- Sites with climate rows: **{integrated['has_climate'].eq('True').sum()}**",
        "",
        "## Files",
        "",
        "- `sites_108_integrated.csv` — flat one-row-per-site table "
        "(site attributes + observation and climate summaries).",
        "- `sites_108_integrated.xlsx` — the same site table plus the full "
        "`Annual Observations` and `Climate` sheets.",
        "",
        "## How it is built",
        "",
        "`scripts/15_build_integrated_dataset.py` reads, but never modifies:",
        "",
        "- `data/processed/sites.csv`",
        "- `data/processed/annual_observations.csv`",
        "- `data/processed/climate.csv`",
        "",
        "Blank source values stay blank. No values are modelled or imputed.",
        "",
        "## Summary columns",
        "",
        "| Column | Meaning |",
        "|---|---|",
        "| obs_n_rows | Annual-observation rows available for the site |",
        "| obs_n_years | Distinct years in the observation table |",
        "| obs_year_min / obs_year_max | First and last observation year |",
        "| obs_n_measured_rows | Rows where `is_measured=True` |",
        "| obs_lfg_total_nm3_sum | Sum of measured LFG volume (Nm3) |",
        "| obs_methane_collected_t_sum | Sum of measured methane collected (t) |",
        "| obs_methane_flared_t_sum | Sum of measured methane flared (t) |",
        "| obs_methane_utilised_t_sum | Sum of measured methane utilised (t) |",
        "| obs_sources / obs_qa_flags | Distinct provenance and QA flags |",
        "| climate_n_years | Distinct climate years |",
        "| climate_year_min / climate_year_max | Climate coverage range |",
        "| climate_mean_temperature_c | Mean annual temperature (C) |",
        "| climate_mean_humidity_pct | Mean relative humidity (%) |",
        "| climate_mean_annual_precipitation_mm | Mean annual precipitation (mm) |",
        "| has_lfg_observations | True when at least one measured LFG row exists |",
        "| has_climate | True when at least one climate year exists |",
        "",
        "## Caveats",
        "",
        "- Observation sums cover only the measured rows; non-measured rows are kept "
        "in the full observation sheet but are not summed.",
        "- Climate means are simple means over the available site-years (2010-2025).",
        "- `waste_composition_fractions` and other JSON-like site fields are "
        "preserved as strings from the master table.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    integrated, obs, climate = build()
    integrated.to_csv(
        OUT / "sites_108_integrated.csv", index=False, lineterminator="\n"
    )
    write_xlsx(integrated, obs, climate)
    write_readme(integrated, obs, climate)
    print(f"integrated sites: {len(integrated)} rows x {len(integrated.columns)} cols")
    print(f"observation rows: {len(obs)}; climate rows: {len(climate)}")
    print(f"written: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
