# Beginner guide

This repository publishes the **Asian CDM Landfill Gas & Engineering Dataset
v1.0**. This guide is for a first-time user who wants to understand the data
without reading the whole pipeline.

## 1. What the dataset is

A site-level evidence base for **108 CDM-anchored landfill sites in 16 Asian
countries**:

- **22 Tier A sites** have at least one metered landfill-gas monitoring period.
- **86 Tier B sites** have engineering/design documentation but no metered gas.

The data record **recovered/collected** landfill gas, plus engineering, waste and
climate covariates. They do **not** record total methane generated or emitted.

> **Do not use this dataset for country-level methane totals.** It is a
> CDM-selected sample, not a national inventory. See the limitations in
> `release/v1.0/QA_REPORT.md`.

## 2. Start here

1. `release/v1.0/README.md` — dataset card and quick start.
2. `release/v1.0/DATA_DICTIONARY.csv` — every field, unit and allowed value.
3. `release/v1.0/QA_REPORT.md` — checks, fixes, outliers and limitations.
4. `release/v1.0/SOURCES.md` — sources, URLs and attribution.
5. `notebooks/quickstart.ipynb` — runnable examples.

## 3. The release files

| File | Rows | Grain |
|---|---:|---|
| `release/v1.0/data/sites_108.csv` | 108 | one row per site |
| `release/v1.0/data/lfg_measurements.csv` | 48 | one row per measured monitoring period |
| `release/v1.0/data/waste_inflow_annual.csv` | 534 | one row per site-year |
| `release/v1.0/data/waste_composition.csv` | 213 | one row per site-category |
| `release/v1.0/data/climate_annual.csv` | 1,728 | one row per site-year |
| `release/v1.0/data/integrated_sites_108.csv` | 108 | one row per site with summaries |
| `release/v1.0/data/sites_108.geojson` | 108 | one point per site |
| `release/v1.0/data/qa_validation_sample.csv` | 63 | PDF-text validation rows |

## 4. The master tables

The release is built from three frozen tables in `data/processed/`:

| File | Rows | Grain |
|---|---:|---|
| `sites.csv` | 108 | one row per site |
| `annual_observations.csv` | 609 | mixed-grain source observations |
| `climate.csv` | 1,728 | one row per site-year |

The mixed-grain observation table is kept for reproducibility. The release
splits it into clean single-grain tables. **Do not edit the master tables** if you
want the published hashes to remain valid.

## 5. Rebuild and test

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/16_build_release.py
.venv/bin/pytest -q
```

`scripts/16_build_release.py` reads the master tables, writes
`release/v1.0/data/`, and regenerates the dictionary, QA report, sources register
and manifest. It never modifies the master tables.

## 6. How the data were assembled

1. Discover CDM landfill projects in Asia.
2. Download PDDs and monitoring reports.
3. Read monitoring periods from report text, not filenames.
4. Extract LFG volume, CH4 and methane masses.
5. Extract design, waste-history and composition fields from PDDs.
6. Geocode sites and attach NASA POWER climate.
7. Add two SIPSN 2025 site-level inflow values.
8. Apply evidence-backed null-fills with an audit trail.
9. Build the release tables and validate values against PDF text.

The numbered scripts in `scripts/` document each stage. Raw documents are not
published; source URLs are in the release tables.

## 7. How to read the main fields

- `evidence_tier`: `tier_a` = metered LFG; `tier_b` = engineering/design only.
- `has_metered_lfg`: whether the site has measured LFG rows.
- `lfg_total_volume` + `lfg_volume_unit`: reported gas volume and unit
  (`m3`, `Nm3` or `not_reported`). **Do not sum across units.**
- `methane_collected_tonnes`: derived methane mass for the period.
- `waste_inflow_tonnes`: annual waste accepted, from a PDD table or SIPSN.
- `composition_sum`: sum of reported waste fractions; may not equal 1.0.
- `coordinate_quality`: `reported_in_pdd`, `geocoded_city`,
  `geocoded_locality_approximate`, `proxy_name_match` or `unknown`.
- `qa_outlier`: large value flagged for source verification.
- `validation_status`: whether the value string was found in the source PDF text.

## 8. Known issues to check before analysis

- `cdm_839` has an unverified 910.8 million m³ period. Exclude it until verified.
- Two `cdm_933` rows have no reported volume unit.
- 16 of 42 composition records do not sum to 1.0; they are flagged, not fixed.
- 7 annual waste-inflow rows exceed 5 million tonnes/year and are flagged.
- 33 waste-inflow rows fall outside the recorded opening/closure window.
- Many monitoring-report filenames do not match the period inside the PDF. The
  period column is authoritative.

## 9. What not to do

- Do not compute country methane totals from this sample.
- Do not treat recovered gas as methane generated or emitted.
- Do not compare `m3` and `Nm3` without a documented conversion.
- Do not treat Tier B sites as measured sites.
- Do not redistribute the raw source PDFs or workbooks.

## 10. Where to get help

Open an issue with the table, record ID, field, current value, proposed
correction and a source URL/page reference. Corrections with traceable evidence
are prioritised.
