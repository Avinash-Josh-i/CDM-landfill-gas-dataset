# Excel / Manual Source Ingest Report

Generated: 2026-11-04T11:02:41+00:00

> **Post-cleanup note (2026-11-04):** 227 of the 229 triaged attachment payloads were
> removed during the deep clean. Only the refs 2518 and 2525 landfill-details workbooks
> remain in `data/raw/cdm/attachments/`; re-fetch the rest with
> `scripts/13_fetch_cdm_attachments.py`. The counts below describe the ingest run, not
> the current on-disk state. See `CHANGELOG.md` for the cleanup record.

## Sources

- CDM landfill-details workbooks:
  - `cdm_1582`: `/home/avinash-joshi/Documents/personal/asia_landfill_project/data/raw/manual/cdm/1582/1582_appendix2_cdm_landfill_details.xls`
  - `cdm_2518`: `/home/avinash-joshi/Documents/personal/asia_landfill_project/data/raw/cdm/attachments/2518/ATT-0062_appendix_2_final_landfill_details_2518_makassar.xls`
  - `cdm_2525`: `/home/avinash-joshi/Documents/personal/asia_landfill_project/data/raw/cdm/attachments/2525/ATT-0068_appendix_2_cdm_landfill_details_2525_palembang.xls`
- SIPSN facility inventory: `data/raw/manual/sipsn/ALL/sipsn_tpa_facilities_2025.xlsx`
- Downloaded attachment directory: `data/raw/cdm/attachments`

## Triage

- Files triaged: **229**
  - `xls`: 154
  - `pdf`: 42
  - `zip`: 18
  - `xlsx`: 14
  - `encrypted_ooxml`: 1

## Site matching (Indonesia)

- Master sites matched to a SIPSN facility: **5 / 8**
  - `cdm_938` -> TPA Regional Sarbagita (alias_name, 2 row(s), inflow=405434.71069)
  - `cdm_1582` -> TPA BATU LAYANG (alias_name, 1 row(s), inflow=137907.9451)
  - `cdm_2518` -> TPA Tamangapa (alias_name, 1 row(s), inflow=257905.3598)
  - `cdm_2751` -> TPA Piyungan (Regional) (alias_name, 3 row(s), inflow=29986.210450000002)
  - `cdm_6486` -> TPST Bantargebang (alias_name, 6 row(s), inflow=2145325.82519)

## Attachment covariate candidates

- Flagged rows: **5147** across **91** projects
- Files with tabular candidates: **229**

| Category | Rows |
|---|---|
| gas_control | 1193 |
| capacity | 467 |
| waste_tonnage | 135 |
| area | 71 |
| leachate | 55 |
| opening_closure | 44 |
| depth_height | 26 |
| liner | 4 |

Candidates are review-only: attachment layouts vary too much to auto-apply. See `data/interim/excel_sources/attachment_candidate_values.csv`.

## Reviewed attachment sources (not promoted)

- `cdm_4077` (Batam): the investment-analysis workbooks report landfill area 12 ha and average depth 12.5 m (`capex opex`), but the master has no area/depth columns. Recorded here for a future schema decision; no update applied.
- `cdm_4566` (bundled): baseline/ER workbooks span several facilities, and the quoted 7 m/15 m depths are LFG well depths, not landfill depth. No per-site mapping, so no update applied.

## Proposals

- Approved & applied: **10** values (59 cells incl. companions)
- Conflicts (not applied): **12**
- Held for review: **3**

### Applied in the most recent run

| Site | Column | Old | New | Source |
|---|---|---|---|---|
| cdm_2518 | waste_composition_fractions | `` | `{"food": 0.675, "glass": 0.025, "metal": 0.01, "other": 0.085, "paper": 0.105, "plastic": 0.075, "textile": 0.01, "wood": 0.015}` | CDM ref 2518 Appendix 2 (landfill details workbook) |
| cdm_2525 | closure_year | `` | `2016` | CDM ref 2525 Appendix 2 (landfill details workbook) |

Full applied history: `data/interim/actual_values.csv` (59 cells, all `integration_action=applied`).

### Conflicts / holds

- `cdm_938` `latitude`: proposed `-8.719299` vs master `1.50748` — Master (1.50748, 102.15779) is 1841 km from the SIPSN facility (-8.71929915, 115.22062135); not overwritten.
- `cdm_938` `longitude`: proposed `115.220621` vs master `102.15779` — Master (1.50748, 102.15779) is 1841 km from the SIPSN facility (-8.71929915, 115.22062135); not overwritten.
- `cdm_938` `annual_waste_inflow_tonnes`: proposed `405434.71` vs master `115.0` — Master has 115.0 (2014.0, pdd_table_last_year); SIPSN reports 2025 receipts. Not overwritten.
- `cdm_938` `design_type`: proposed `open_dump` vs master `sanitary_landfill` — Master has sanitary_landfill; SIPSN describes 'Open Dumping'. Not overwritten.
- `cdm_1582` `annual_waste_inflow_tonnes`: proposed `137907.95` vs master `1641982.0` — Master has 1641982.0 (1994.0, pdd_table_last_year); SIPSN reports 2025 receipts. Not overwritten.
- `cdm_2751` `annual_waste_inflow_tonnes`: proposed `29986.21` vs master `108000.0` — Master has 108000.0 (2002.0, pdd_table_last_year); SIPSN reports 2025 receipts. Not overwritten.
- `cdm_2751` `design_type`: proposed `controlled_dump` vs master `sanitary_landfill` — Master has sanitary_landfill; SIPSN describes 'Control Landfill'. Not overwritten.
- `cdm_6486` `design_type`: proposed `open_dump` vs master `sanitary_landfill` — Master has sanitary_landfill; SIPSN describes 'Open Dumping'. Not overwritten.
- `cdm_1582` `opening_year`: proposed `1996` vs master `1993` — Master has 1993; workbook says 1996. Not overwritten.
- `cdm_1582` `design_type`: proposed `controlled_dump` vs master `sanitary_landfill` — Master has sanitary_landfill; workbook describes it as semi controlled. Not overwritten.
- `cdm_2525` `opening_year`: proposed `1994` vs master `1993` — Master has 1993; workbook says 1994. Not overwritten.
- `cdm_2525` `design_type`: proposed `open_dump` vs master `sanitary_landfill` — Master has sanitary_landfill; workbook describes it as open dumping. Not overwritten.
- `cdm_1582` `waste_tonnes_cumulative`: proposed `417501.26` vs master `` — Workbook total through 2006 (disposal table runs to 2020); not a current measured cumulative value.
- `cdm_2518` `waste_tonnes_cumulative`: proposed `3530029.57` vs master `` — Workbook total through 2016; not a current measured cumulative value.
- `cdm_2525` `waste_tonnes_cumulative`: proposed `1153084.97` vs master `` — Historical workbook total; not a current measured cumulative value.

## CDM landfill-details workbook extracts

### `cdm_1582` — sheet `Data Sheet Oct 06`

- `landfill_name`: TPA Batu Layang
- `opening_year`: 1996
- `closure_year`: 2020
- `design_type_raw`: semi controlled
- `design_capacity_m3`: 1040000
- `total_area_ha`: 19.5
- `disposal_area_ha`: 18
- `n_cells`: 12
- `n_closed_cells`: 2
- `closed_cell_capping`: Not covered
- `height_above_m`: 7
- `depth_below_m`: 3 to 4
- `current_volume_m3`: 300000
- `distance_city_km`: 15
- `collection_service_fraction`: 0.49765808570647935
- `total_disposed_t`: 417501.26
- `total_disposed_m3`: 1386459.05
- `disposal_last_year`: 2016
- `disposal_table_end_year`: 2020
- `total_disposed_horizon`: 2006
- `capture_efficiency`: 0.7
- `composition`: food=0.83, glass=0.021, metal=0.02, other=0.002, paper=0.05, plastic=0.06, textile=0.001, wood=0.015

### `cdm_2518` — sheet `Data Collection Sheet`

- `landfill_name`: TPA Tamangapa
- `opening_year`: 1993
- `closure_year`: 2016
- `design_type_raw`: Controlled
- `total_area_ha`: 14.3
- `disposal_area_ha`: 6.6832
- `n_cells`: 6 zones
- `n_closed_cells`: 2
- `closed_cell_capping`: Cover Soil
- `height_above_m`: Min 4m - Max 20m
- `distance_city_km`: 15
- `collection_service_fraction`: 0.4729104876165684
- `total_disposed_t`: 3530029.57
- `disposal_last_year`: 2016
- `disposal_table_end_year`: 2016
- `total_disposed_horizon`: 2016
- `composition`: food=0.675, glass=0.025, metal=0.01, other=0.085, paper=0.105, plastic=0.075, textile=0.01, wood=0.015

### `cdm_2525` — sheet `Data Collection Sheet`

- `landfill_name`: TPA I Sukawinatan
- `opening_year`: 1994
- `closure_year`: 2016
- `design_type_raw`: open dumping
- `total_area_ha`: 25
- `disposal_area_ha`: 17
- `n_cells`: 8
- `n_closed_cells`: 1
- `closed_cell_capping`: 1
- `height_above_m`: refer site map
- `current_volume_m3`: 4000000
- `distance_city_km`: 10 km
- `collection_service_fraction`: 0.275992413624356
- `total_disposed_t`: 1153084.97
- `disposal_last_year`: 2015
- `disposal_table_end_year`: 2016
- `composition`: food=0.675, glass=0.025, metal=0.01, other=0.085, paper=0.105, plastic=0.075, textile=0.01, wood=0.015


## Files

- Proposals: `data/interim/excel_sources/excel_source_proposals.csv`
- Diff: `data/interim/excel_ingest_diff.csv`
- Site covariates: `data/interim/indonesia/sipsn_site_covariates.csv`
- Facility covariates: `data/interim/indonesia/sipsn_facility_covariates.csv`
- Triage: `data/interim/excel_sources/file_triage.csv`
