# Asian CDM Landfill Gas & Engineering Dataset

**v1.0.0 · 2026-11-06 · 108 sites · 16 countries · measured LFG 2006–2018**

A provenance-tracked, site-level dataset of **108 CDM-anchored landfill sites in
Asia**, combining:

- measured landfill-gas (LFG) recovery at **22 sites**,
- engineering, design and waste-history attributes for **86 additional sites**,
- 534 annual waste-inflow records,
- waste-composition records for **42 sites**, and
- 1,728 site-years of NASA POWER climate covariates (2010–2025).

> **This is not a national emissions inventory.**
> The 108 sites are a **CDM-selected sample**, not a representative sample of all
> Asian landfills. The dataset records **recovered/collected** landfill gas, not
> total methane generated or emitted. It must **not** be used to estimate
> country-level methane emissions or to build country totals.

---

## Why this dataset exists

Site-level measured landfill-gas data are scarce. CDM projects publish design
documents and monitoring reports under a standard MRV regime, so they provide a
rare, traceable window into real landfill-gas recovery. This release extracts
those facts into analysis-ready tables, keeps the source URLs, and separates
measured data from design/context data.

It is designed for:

- site-level case studies and benchmarking,
- landfill-gas model calibration and validation,
- feasibility screening for landfill-gas projects,
- engineering pattern analysis (liners, covers, leachate, gas control),
- MRV / provenance workflow design,
- a validation layer for national inventories — **not a substitute for one**.

---

## What is in the release

| File | Rows | Grain | Description |
|---|---:|---|---|
| `data/sites_108.csv` | 108 | one row per site | identity, coordinates, design, waste history, QA flags |
| `data/lfg_measurements.csv` | 48 | one row per measured monitoring period | LFG volume, flared/utilised volume, CH4, derived methane masses |
| `data/waste_inflow_annual.csv` | 534 | one row per site-year | annual waste inflow from PDD tables + 2 SIPSN site-level values |
| `data/waste_composition.csv` | 213 | one row per site-category | reported fractions with completeness flags |
| `data/climate_annual.csv` | 1,728 | one row per site-year | NASA POWER temperature, humidity, precipitation |
| `data/integrated_sites_108.csv` | 108 | one row per site | site table + observation and climate summaries |
| `data/sites_108.geojson` | 108 | one point per site | coordinates with quality labels |
| `data/qa_validation_sample.csv` | 63 | one row per checked value | PDF-text validation results |
| `DATA_DICTIONARY.csv` | — | one row per column | definitions, units, allowed values, derivations |
| `QA_REPORT.md` | — | — | checks, fixes, outliers and limitations |
| `SOURCES.md` | — | — | source register and attribution |
| `manifest.csv` | — | — | SHA256 and size for every release file |

### Key numbers

- **108 sites** in **16 countries**.
- **22 Tier A** sites with at least one metered LFG period; **86 Tier B** sites
  with design/operation documentation but no metered LFG.
- **48 measured LFG rows** across 22 sites; 2006–2018.
- **Only 1 site has 10 measured rows**; most measured sites have 1–3.
- **534 annual waste-inflow rows** across 50 sites.
- **42 sites** have waste composition; **16 of 42** composition records do not
  sum to 1.0 and are flagged, not renormalised.
- **34 sites** have a collection-efficiency value: 6 measured, 10 reported,
  18 assumed, and 74 not reported (site-level basis).
- **1,728 climate site-years**, 2010–2025.

## Quick start

```python
import pandas as pd

sites = pd.read_csv("release/v1.0/data/sites_108.csv")
lfg = pd.read_csv("release/v1.0/data/lfg_measurements.csv")
waste = pd.read_csv("release/v1.0/data/waste_inflow_annual.csv")
climate = pd.read_csv("release/v1.0/data/climate_annual.csv")

print(sites.groupby(["region", "evidence_tier"]).size())
print(lfg.groupby("country").size().sort_values(ascending=False))
print(waste.groupby("landfill_id")["year"].agg(["min", "max"]).head())
```

A runnable notebook is in `notebooks/quickstart.ipynb` in the repository.

### Filtering the high-confidence subset

```python
measured = lfg[lfg["validation_status"].eq("found")].copy()
tier_a = sites[sites["evidence_tier"].eq("tier_a")]
```

`cdm_839` reports an unverified 910.8 million m³ period and should be excluded
from analysis until checked against the source table. See `QA_REPORT.md`.

---

## Units and interpretation

- `lfg_total_volume`, `lfg_flared_volume` and `lfg_utilised_volume` are **as
  reported** in `lfg_volume_unit`. The release contains both `m3` and `Nm3` and
  does **not** convert between them. A defensible conversion needs temperature
  and pressure that the source tables do not consistently provide.
- `methane_collected_tonnes`, `methane_flared_tonnes` and
  `methane_utilised_tonnes` are methane masses derived in the master pipeline.
- `composition_sum` is the sum of reported fractions. It is **not** forced to
  1.0.
- `annual_waste_inflow_reported_tonnes` in `sites_108.csv` is a **site-level
  reference value**, not a complete annual series. Use
  `waste_inflow_annual.csv` for the series.
- `lfg_total_m3_sum` and `lfg_total_nm3_sum` in the integrated table are sums of
  **monitoring-period** volumes, not annual rates and not directly comparable
  across units.

---

## Data quality and provenance

- Every measured LFG row has a **public source URL** and a stable `observation_id`.
- Every annual waste-inflow row has a stable `waste_record_id` and a source URL.
- **47 of 48** measured LFG values were found in the source PDF text. The one
  failure is the `cdm_839` 910.8 million m³ outlier, which is flagged.
- A random **15-row** waste-inflow sample was checked against PDD text: **15/15**
  found.
- Monitoring-period dates were read from the report text. Many local filenames
  do not match the period inside the PDF; this is exposed as
  `qa_filename_period_mismatch` and is **not** a reason to distrust the period
  column.
- Outliers are flagged, not silently removed:
  - LFG volume > 100 million m³ per monitoring period,
  - annual waste inflow > 5 million tonnes/year,
  - waste-inflow year outside the recorded opening/closure window.
- Two measured rows (`cdm_933`) have **no reported volume unit**. They are kept
  with `lfg_volume_unit = not_reported`.

See `QA_REPORT.md` for the full list and `DATA_DICTIONARY.csv` for every field.

---

## Scope and limitations

**Appropriate uses**

- Site-level analysis of CDM landfill-gas projects.
- Benchmarking measured recovery, flaring and utilisation at the 22 Tier A sites.
- Engineering covariate analysis across Tier B sites.
- Model calibration, validation and feasibility screening.
- Teaching and demonstrating provenance-aware environmental data workflows.

**Inappropriate uses**

- Country-level methane emission totals or national inventories.
- Treating the 108 sites as representative of all Asian landfills.
- Treating recovered methane as total methane generated or emitted.
- Comparing `m3` and `Nm3` values without a documented conversion.
- Using the dataset as a regulatory or investment-grade emissions estimate.

Why country totals are not supported: the sample is CDM-selected, covers 16
countries unevenly (China alone has 52 sites), has no complete national site
universe, lacks representative sampling, lacks IPCC FOD parameters and activity
time series, and does not measure fugitive emissions or oxidation.

---

## License

- **Data and documentation:** CC BY 4.0 (`LICENSE-DATA`).
- **Code:** MIT (`LICENSE`).

Source documents remain subject to their publishers' terms. Raw PDFs and
workbooks are **not** redistributed. See `SOURCES.md`.

## Citation

Use the DOI assigned by Zenodo once the record is published. Until then, cite:

> Joshi, A. (2026). *Asian CDM Landfill Gas & Engineering Dataset* (v1.0.0)
> [Data set]. Zenodo. DOI to be assigned.

A machine-readable citation is in `CITATION.cff`.

## Versioning

- `v1.0.0` — first public release (2026-11-06).
- Future versions should add sites, measured years or national inventory links;
  they should not silently change the v1.0 schema.

## Contact

Open an issue in the GitHub repository for data corrections, source suggestions
or reuse questions. Corrections with a source URL and page reference are
especially welcome.
