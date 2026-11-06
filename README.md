# Asian CDM Landfill Gas & Engineering Dataset

**A provenance-tracked, site-level dataset of 108 CDM-anchored landfill sites in
16 Asian countries.**

- **22 sites** with measured landfill-gas recovery (48 monitoring rows, 2006–2018)
- **86 sites** with engineering, design and waste-history documentation
- **534 annual waste-inflow records**
- **42 sites** with waste composition
- **1,728 site-years** of NASA POWER climate covariates (2010–2025)

> **Not a national emissions inventory.** The 108 sites are a CDM-selected
> sample, not a representative sample of all Asian landfills. The data record
> recovered/collected landfill gas, not total methane generated or emitted. Do
> **not** use this dataset for country-level methane totals.

The canonical release is in **[`release/v1.0/`](release/v1.0/)**. Start with:

- [`release/v1.0/README.md`](release/v1.0/README.md) — dataset card and quick start
- [`release/v1.0/DATASET_CARD.md`](release/v1.0/DATASET_CARD.md) — datasheet
- [`release/v1.0/DATA_DICTIONARY.csv`](release/v1.0/DATA_DICTIONARY.csv) — every field
- [`release/v1.0/QA_REPORT.md`](release/v1.0/QA_REPORT.md) — checks, fixes, outliers
- [`release/v1.0/SOURCES.md`](release/v1.0/SOURCES.md) — sources and attribution

## Release files

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

## Master tables

The release is built from three frozen master tables, which are **read-only
inputs** and are never modified by the release builder:

| File | Rows | Grain |
|---|---:|---|
| `data/processed/sites.csv` | 108 | one row per site |
| `data/processed/annual_observations.csv` | 609 | mixed-grain source observations |
| `data/processed/climate.csv` | 1,728 | one row per site-year |

The mixed-grain master observation table is deliberately retained for
reproducibility. The release splits it into single-grain tables.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# rebuild the release from the frozen master tables
.venv/bin/python scripts/16_build_release.py

# run tests
.venv/bin/pytest -q
```

The builder reads the master tables, writes `release/v1.0/data/`, and regenerates
the data dictionary, QA report, sources register and manifest. It does not
modify the master tables.

## Repository layout

```text
release/v1.0/          canonical public release (data, docs, licenses, manifest)
data/processed/        frozen master tables used to build the release
data/raw/              source PDFs/JSON/workbooks (local only, not published)
data/interim/          extraction, audit and provenance tables (local only)
scripts/               numbered data pipeline + release builder
notebooks/             quickstart notebook
tests/                 data-integrity and release tests
docs/                  methodology and collection guides
```

Raw PDFs, workbooks, API responses and extraction logs are **not** redistributed.
The release publishes derived facts, source URLs and QA evidence. Local raw data
is ignored by Git. Re-fetch scripts are in `scripts/` and access notes are in
`ACCESS_NEEDED.md`.

## Scope

**Use it for**

- site-level case studies and benchmarking,
- landfill-gas model calibration and validation,
- engineering covariate analysis,
- feasibility screening,
- MRV/provenance workflow design,
- a validation layer for national inventories.

**Do not use it for**

- country-level methane emission totals,
- national inventories or regulatory reporting,
- treating recovered methane as methane generated/emitted,
- treating the 108 sites as representative of all Asian landfills,
- comparing `m3` and `Nm3` without a documented conversion.

See [`release/v1.0/README.md`](release/v1.0/README.md) and
[`release/v1.0/QA_REPORT.md`](release/v1.0/QA_REPORT.md) for the full limitations.

## License and citation

- **Data and documentation:** CC BY 4.0 — see [`LICENSE-DATA`](LICENSE-DATA).
- **Code:** MIT — see [`LICENSE`](LICENSE).
- **Citation:** see [`CITATION.cff`](CITATION.cff). A DOI will be added after the
  Zenodo deposit.

Source documents remain subject to their publishers' terms. See
[`release/v1.0/SOURCES.md`](release/v1.0/SOURCES.md).

## Contributing and corrections

Please open an issue with:

- the table and record ID,
- the field and current value,
- the correction,
- a source URL and page reference.

Corrections with traceable source evidence are prioritised.
