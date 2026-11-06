# Dataset card — Asian CDM Landfill Gas & Engineering Dataset v1.0

## Motivation

Landfill methane is a material but poorly measured part of the waste sector.
Country inventories rely on modelled emission factors, while site-level measured
landfill-gas data are rare and scattered. CDM landfill-gas projects are one of the
few places where design data, waste history and metered gas recovery are published
together under a standard monitoring regime.

This dataset assembles those published facts for **108 Asian landfill sites** so
that researchers, engineers and analysts can work with measured recovery data and
engineering covariates without re-parsing hundreds of PDFs.

- **Purpose:** site-level evidence base and validation layer.
- **Created by:** Avinash Joshi, 2026.
- **Funding:** none.
- **Contact:** open an issue in the GitHub repository.

## Composition

### Instances

| Table | Instances | What each instance represents |
|---|---:|---|
| `sites_108.csv` | 108 | one landfill / CDM project site |
| `lfg_measurements.csv` | 48 | one metered monitoring period |
| `waste_inflow_annual.csv` | 534 | one site-year of waste inflow |
| `waste_composition.csv` | 213 | one site-category fraction |
| `climate_annual.csv` | 1,728 | one site-year of climate |
| `integrated_sites_108.csv` | 108 | one site with summaries |

### Sites

- 16 countries: China (52), Israel (9), Malaysia (9), Indonesia (8), South Korea
  (7), Philippines (4), Thailand (4), Vietnam (3), and 1–2 sites in Bangladesh,
  India, Iran, Jordan, Saudi Arabia, Syria, United Arab Emirates and Uzbekistan.
- 22 **Tier A** sites: at least one metered LFG period plus documented waste
  placement history.
- 86 **Tier B** sites: documented design/operation but no metered LFG series.
- The sample is **CDM-selected** and is not representative of all Asian landfills.

### Variables

See `DATA_DICTIONARY.csv` for every published field. Key groups:

- **Identity and location:** `landfill_id`, name, country, ISO3, region,
  latitude, longitude, coordinate source/quality.
- **Design and operation:** design type, liner, cover, leachate, gas control,
  design capacity.
- **Waste history:** annual inflow, cumulative waste, waste history length,
  composition, collection efficiency.
- **Measured LFG:** period, volume and unit, flared/utilised volume, CH4
  concentration, methane masses.
- **Climate:** annual temperature, humidity and precipitation.
- **QA:** source URLs, validation status, outlier flags, period flags.

### Missingness

Missingness is structural, not random. Important examples:

- design capacity: 7/108 sites;
- cover frequency: 14/108;
- liner type: 34/108;
- collection efficiency: 34/108;
- waste composition: 42/108;
- annual waste inflow series: 50/108;
- metered LFG: 22/108.

Blank means **not reported in the sources**. No values are modelled or imputed.

## Collection process

1. Discovered CDM landfill projects in Asia from the UNFCCC CDM project tracker.
2. Downloaded PDDs and monitoring reports (public PDFs).
3. Read monitoring-period dates from the report text, not the filename.
4. Extracted LFG volume, CH4 concentration, flared/utilised volume and derived
   methane masses.
5. Extracted design and waste-history tables from PDDs.
6. Geocoded sites from PDD coordinates, then Nominatim for gaps.
7. Attached NASA POWER climate for 2010–2025.
8. Added SIPSN 2025 site-level inflow for two Indonesian sites.
9. Applied evidence-backed null-fills from three CDM landfill-detail workbooks,
   with an audit trail.
10. Split the master observation table into single-grain release tables for v1.0.

### Source documents

- UNFCCC CDM PDDs and monitoring reports (public).
- NASA POWER (public API).
- Climate TRACE (site spine and coordinates only).
- SIPSN Indonesia (public portal/Excel).
- OpenStreetMap Nominatim (geocoding).
- CDM landfill-detail workbooks for refs 1582, 2518 and 2525.

Raw PDFs and workbooks are **not** redistributed. Source URLs are in the tables.

## Preprocessing and cleaning

- Standardised country names and added ISO3 plus a region.
- Converted registration dates to ISO 8601.
- Dropped the 100% empty `city` column.
- Split mixed-grain observations into annual waste inflow and measured LFG tables.
- Renamed `lfg_total_nm3` to `lfg_total_volume` and added `lfg_volume_unit`.
- Kept `m3` and `Nm3` as reported; no conversion.
- Fixed five `ce_basis`/`qa_ce` inconsistencies by using one CE basis and deriving
  the QA field.
- Added composition completeness flags; did not renormalise fractions.
- Added stable `observation_id` and `waste_record_id`.
- Added source URLs, extraction method and validation status.
- Flagged LFG and waste outliers instead of removing them.
- Added GeoJSON output.
- Validated all 48 measured LFG values and a 15-row waste sample against PDF text.

## Uses

### Intended

- Site-level case studies and benchmarking.
- Calibration/validation of landfill-gas and methane models.
- Engineering covariate analysis.
- Feasibility screening and project comparison.
- MRV workflow design and provenance research.
- Teaching sparse, provenance-heavy environmental data.

### Not intended

- Country-level methane emission estimates or national inventories.
- Regulatory reporting or investment-grade emissions accounting.
- Treating the sample as representative of all Asian landfills.
- Treating recovered methane as methane generated or emitted.
- Comparing `m3` and `Nm3` values without conversion.

## Distribution

- Data and documentation: CC BY 4.0.
- Code: MIT.
- Canonical archive: Zenodo DOI (to be assigned).
- Mirrors: GitHub release, Kaggle, Hugging Face Datasets.
- No raw source documents are redistributed.

## Maintenance

- Corrections should include the source URL and page reference.
- The v1.0 schema is frozen for reproducibility.
- Future versions may add sites, measured years or national inventory links.
- Outlier rows remain in the release with flags so users can decide whether to
  exclude them.

## Ethical and legal considerations

- The dataset describes public infrastructure and public CDM project data. It
  contains no personal data.
- Source documents remain subject to their publishers' terms. Users are
  responsible for checking UNFCCC, SIPSN, NASA POWER and Climate TRACE terms.
- The dataset should not be used to make claims about a country's total emissions
  or about individual site liability.

## Limitations

- CDM selection bias; China is over-represented.
- Sparse and uneven measured LFG coverage (48 rows, 22 sites, 2006–2018).
- No complete annual measured series; most sites have 1–3 rows.
- Recovered methane is not total methane generated or emitted.
- Some coordinates are geocoded approximations or proxy matches.
- Composition and collection-efficiency values are often assumed or incomplete.
- No uncertainty framework for extrapolation.
- No independent full re-extraction of every waste-inflow value; validation is a
  PDF-text search, with a 15-row random sample for waste data.
- One LFG outlier (`cdm_839`, 910.8 million m³) failed PDF-text validation and
  should be excluded until verified.
