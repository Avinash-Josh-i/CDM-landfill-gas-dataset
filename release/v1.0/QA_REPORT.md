# QA report - release v1.0

Release date: **2026-11-06**

## Release counts

| Table | Rows | Grain |
|---|---:|---|
| `sites_108.csv` | 108 | one row per site |
| `lfg_measurements.csv` | 48 | one row per measured monitoring period |
| `waste_inflow_annual.csv` | 534 | one row per site-year |
| `waste_composition.csv` | 213 | one row per site-category |
| `climate_annual.csv` | 1728 | one row per site-year |
| `integrated_sites_108.csv` | 108 | one row per site |

- Sites: **108** across **16** countries.
- Tier A (metered LFG): **22**; Tier B (engineering only): **86**.
- Measured LFG rows: **48** across **22** sites.
- Annual waste-inflow rows: **534** across **50** sites.
- Sites with waste composition: **42**.
- Sites with climate: **1728** site-years across **108** sites.

## Fixes applied for this release

1. **Mixed grains split.** The 609-row master observation table mixed PDD annual waste inflow with monitoring-period LFG measurements. v1.0 publishes separate `waste_inflow_annual.csv` and `lfg_measurements.csv` tables.
2. **Units kept honest.** `lfg_total_nm3` was renamed to `lfg_total_volume` and paired with `lfg_volume_unit`. Values are **not** converted between `m3` and `Nm3` because the source reports do not contain the temperature/pressure needed for a defensible conversion.
3. **Collection-efficiency QA fixed.** Five sites had `ce_basis` and `qa_ce` disagreeing. The release uses one `collection_efficiency_basis` and derives `qa_collection_efficiency` from it.
4. **Composition validated, not renormalised.** Every site composition has a `composition_sum` and `composition_is_complete` flag. Fractions outside 0.98-1.02 are retained and flagged.
5. **Country names standardised.** UNFCCC names such as 'Viet Nam', 'Iran (Islamic Republic of)' and 'Republic of Korea' were mapped to short names while retaining the original in `country_name_source`.
6. **Registration dates normalised.** All 108 dates were converted to ISO 8601.
7. **Empty `city` column dropped.** It was 100% empty.
8. **Stable IDs and source URLs added.** Every measured row has an `observation_id` and public source URL; every waste row has a `waste_record_id` and source URL.
9. **Outliers flagged, not silently removed.** LFG volumes above 100 million m3 and annual inflows above 5 million tonnes are flagged in `qa_outlier`.
10. **PDF-text validation.** All 48 measured LFG values were searched in the source PDF text. 47 were found; the one failure is the `cdm_839` 910.8 million m3 outlier. A random 15-row waste-inflow sample was also checked; 15/15 were found.
11. **Filename mismatch documented.** Many monitoring-report filenames do not match the period inside the PDF. The period columns were extracted from the report text, which is authoritative; the mismatch is exposed as `qa_filename_period_mismatch`.

## Validation

- Measured LFG values found in source PDF text: **47 of 48**.
- Random waste-inflow sample found in PDD text: **15 of 15**.
- Validation means the value string was found in the extracted PDF text; it is not a full independent re-extraction of every table.
- The detailed sample is in `data/qa_validation_sample.csv`.

## Known outliers and unresolved items

### LFG volume outliers

| Site | Period | Reported volume | Unit | Validation |
|---|---|---:|---|---|
| cdm_1906 | 2017-01-01 to 2017-12-31 | 165977471.0 | m3 | found |
| cdm_1906 | 2018-01-01 to 2018-12-24 | 187830929.0 | m3 | found |
| cdm_839 | 2010-02-02 to 2012-06-30 | 910802000.0 | m3 | not_found |
| cdm_941 | 2007-12-01 to 2008-05-31 | 125359715.0 | m3 | found |
| cdm_941 | 2008-06-01 to 2008-12-31 | 156450629.0 | m3 | found |
| cdm_941 | 2009-01-01 to 2009-12-31 | 269056600.8 | m3 | found |
| cdm_941 | 2010-01-01 to 2010-12-31 | 257873950.4 | m3 | found |
| cdm_941 | 2012-01-01 to 2012-06-30 | 166605094.0 | m3 | found |
| cdm_941 | 2012-07-01 to 2013-06-30 | 309553591.1 | m3 | found |
| cdm_941 | 2013-07-01 to 2014-06-30 | 273258472.8 | m3 | found |
| cdm_941 | 2014-07-01 to 2015-06-30 | 254994428.5 | m3 | found |
| cdm_941 | 2015-07-01 to 2016-06-30 | 234619764.9 | m3 | found |
| cdm_941 | 2016-07-01 to 2017-04-29 | 188490496.3 | m3 | found |

`cdm_839` reports 910,802,000 m3 for 2010-02-02 to 2012-06-30. That value was **not found** in the extracted PDF text; the visible table shows values around 10.8 million m3. Treat this row as unverified and exclude it from analysis until it is checked against the source table.

### Annual waste-inflow outliers

| Site | Year | Inflow (t/year) |
|---|---:|---:|
| cdm_3663 | 2000 | 6072000.0 |
| cdm_5466 | 2017 | 5092287.0 |
| cdm_5466 | 2018 | 5387245.0 |
| cdm_5466 | 2019 | 5673975.0 |
| cdm_5466 | 2020 | 5952958.0 |
| cdm_5466 | 2021 | 6224652.0 |
| cdm_6673 | 2018 | 7577325.0 |

These may be legitimate mega-site values or extraction/cumulative-vs-annual errors. They are flagged, not removed.

### Other known limitations

- **33 annual waste-inflow rows** fall outside the recorded opening/closure window. They are flagged in `qa_year_outside_operation`.
- **86 of 108 sites have no metered LFG.** They are engineering/design records, not measurement sites.
- Measured LFG is **recovered/collected gas**, not total methane generated or emitted. Fugitive emissions and oxidation are not measured.
- The sample is **CDM-selected** and not a representative sample of Asian landfills.
- Coordinates are mixed quality: only a subset come directly from PDD coordinates; many are geocoded approximations or proxy matches.
- Some fields are very sparse: design capacity (7/108), cover frequency (14/108), liner type (34/108). They are retained as optional engineering descriptors.
- Climate values are reanalysis-model outputs from NASA POWER, not site measurements.

## What this release must not be used for

**Do not use this dataset to estimate country-level methane emissions.** It is a CDM-selected site sample, not a national landfill inventory. It lacks a complete site universe, representative sampling, activity-data time series, IPCC FOD parameters, fugitive-emission measurements and an uncertainty framework. It can support site-level case studies, model calibration, feasibility screening and validation layers.

## Master-file integrity

The release is derived from the frozen master tables below. Their SHA256 hashes are recorded here so users can confirm the release was built from the intended inputs.

| Master file | SHA256 |
|---|---|
| `data/processed/sites.csv` | `bf0b5bbe6387c377f667a8001ffa2e9ced4aae85ae4bdd85f97d530d22225a51` |
| `data/processed/annual_observations.csv` | `ec50fd5628693d16b5f979a6fd7eb3f9d39cfafd0b1f6396e6fea1549b45dcd2` |
| `data/processed/climate.csv` | `9fc96cc8b91bfb6df71587d1859f61c9bf1b5d885c0bca5a3413740d7cb6f565` |

## Reproduction

```bash
python scripts/16_build_release.py
pytest -q
```

The builder reads the master tables and never modifies them. PDF-text validation is cached in `data/interim/release/` so the release can be rebuilt without the raw PDF archive; delete the cache and rerun with the PDFs present to re-validate.
