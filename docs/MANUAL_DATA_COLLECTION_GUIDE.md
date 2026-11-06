# Manual Data Collection Guide

Last updated: 2026-11-03

This guide tells you which manual sources are worth pursuing, what documents to collect, where to put them, and how to record them so they can be integrated into `data/processed/sites.csv` and `data/processed/annual_observations.csv`.

---

## 1. Current state

- Master: `data/processed/sites.csv` — 108 sites, 46 columns.
- 59 extracted values have been integrated:
  - 28 `waste_composition_fractions`
  - 17 `leachate_system`
  - 5 `collection_efficiency` (+ 5 `ce_basis`)
  - 2 `liner_type`
  - 7 other site covariates (2 coordinates, 2 closure years, 1 design type, 2 annual inflow + companion fields)
- `data/interim/actual_values.csv` — all 59 proposal rows marked `applied`.
- Three CDM "landfill details" workbooks parsed for physical covariates (refs 1582, 2518, 2525); area, cell count, depth and disposal totals are in `data/interim/excel_sources/landfill_details_covariates.csv` because the master has no column for them.
- Pre-integration backups were removed in the 2026-11-04 cleanup; the current master
  (`data/processed/sites.csv`) and `data/interim/actual_values.csv` are the retained
  record. See `CHANGELOG.md` for the cleanup history.
- The durable manual upload loop is closed for the two starting files:
  - `data/raw/manual/cdm/1582/1582_appendix2_cdm_landfill_details.xls` (ref 1582 Appendix 2, OLE2 XLS)
  - `data/raw/manual/sipsn/ALL/sipsn_tpa_facilities_2025.xlsx` (SIPSN 2025, 397 facilities)
  - Both have SHA256 checksums and `status=resolved` in `data/interim/manual_uploads_manifest.csv`.
- `data/interim/manual_help_required.csv` — 65 rows:
  - 53 site-level `no_mrs_available` rows (downgraded to low priority)
  - 11 source-access barriers
  - 1 targeted `pdd_appendix` action (ref 1582) — **resolved**
- The 230 CDM data attachments across 94 projects are catalogued in
  `data/interim/cdm/attachment_catalogue.csv`. Only the two applied landfill-details
  workbooks (refs 2518 and 2525) remain on disk after the 2026-11-04 cleanup; all other
  payloads were removed and can be re-fetched into `data/raw/cdm/attachments/<ref>/`
  with `scripts/13_fetch_cdm_attachments.py`.

---

## 2. Key finding: the 53 "missing MR" sites have no MRs

Every one of the 53 site rows has `n_mrs_available = 0` in `data/interim/cdm/census/census_manifest.csv`.

Live spot-checks on 2026-11-03:

| Project | Result |
|---|---|
| Ref 71 (Nanjing) | 6 monitoring reports listed, all issued |
| Ref 78 (Matuail) | "Requests for Issuance" section present but empty |
| Ref 1582 (Pontianak) | same — no MRs |

**Do not spend time trying to download monitoring reports for the 53.** They never had issuance requests, so the reports do not exist.

What those pages do contain:

| Document | Availability across the 53 |
|---|---|
| PDD | already downloaded |
| PDD appendices | 51 / 53 sites (121 appendices, mostly financial/ER calculations) |
| Dedicated "landfill details" appendix | 3 (refs 1582, 2518, 2525) |
| Validation report | 46 / 53 sites (not downloaded) |
| Monitoring reports | 0 / 53 |

---

## 3. What to collect, in priority order

| Priority | Source | Current sites | Files you will find | Fields it can fill |
|---|---|---|---|---|
| 1 | UNFCCC refs 1582, 2518, 2525, Appendix 2 — "cdm landfill details" | 3 | **Collected** (OLE2 XLS) | opening/closure, design type, area, cells, depth, composition, cumulative waste |
| 2 | SIPSN TPA/TPST (Indonesia) | 8 | **Collected** (XLSX, 397 facilities) | design capacity, annual inflow, facility status |
| 3 | Korea Public Data Portal | 7 | CSV/Excel/API JSON | design capacity, facility basics, treatment methods |
| 4 | SWCorp Malaysia | 9 | PDF reports / landfill studies | composition, inflow, capacity |
| 5 | Thailand PCD | 4 | PDF reports / statistics | leachate, capacity, inflow |
| 6 | SIPSN Waste Composition (Indonesia) | 8 (2 missing composition) | Excel/CSV by city/year | composition for `cdm_2518`, `cdm_4566` |
| 7 | ADB / World Bank Bangladesh | 1 (`cdm_78`) | PDF city/project reports | design type, liner, CE, capacity |
| 8 | WasteMAP | all 108 | web export / CSV | capacity, coordinates — modelled, use as cross-check only |
| Optional | Copernicus ERA5-Land | all 108 | NetCDF/GRIB | climate covariates only |
| Skip | 53 UNFCCC MRs | 53 | none | none — no MRs exist |
| Skip | MOENV Taiwan | 0 | GIS/CSV/Excel | no Taiwan sites in the master |
| Skip | World Bank / Pakistan | 0 | operator PDFs | no Pakistan sites in the master |

---

## 4. Where to put files and how to name them

Use the existing repository layout where possible.

### CDM documents

```
data/raw/cdm/census/pdd/<ref>_pdd.pdf                     # already present
data/raw/cdm/census/pdd/<ref>_appendix<N>_<slug>.pdf      # validation/census appendix
data/raw/cdm/attachments/<ref>/ATT-####_<slug>.<ext>      # 230 data attachments (script 13)
data/raw/cdm/attachments/<ref>/                           # XLS/XLSX/ZIP/PDF, extension sniffed from bytes
data/raw/cdm/census/validation/<ref>_validation.pdf
data/raw/cdm/census/mr/<ref>_mr_<n>.pdf                   # only if MRs actually exist
```

### National datasets

```
data/raw/national/<ISO3>/<source>_<year>_<slug>.<ext>
```

Examples:

```
data/raw/national/IDN/sipsn_tpa_2025_facilities.xlsx
data/raw/national/KOR/data_go_kr_facilities_2025.csv
data/raw/national/MYS/swcorp_landfill_report_2024.pdf
data/raw/national/THA/pcd_msw_report_2024.pdf
```

### Miscellaneous manual reports

```
data/raw/manual/<source_slug>/<landfill_id or ALL>/<file>
```

Examples:

```
data/raw/manual/cdm/1582/1582_appendix2_cdm_landfill_details.xls
data/raw/manual/sipsn/ALL/sipsn_tpa_facilities_2025.xlsx
data/raw/manual/ADB_WB_BGD/cdm_78/matuail_city_report.pdf
data/raw/manual/WASTEMAP/ALL/wastemap_export_2026-11-03.csv
```

### Field / operator visits

```
data/raw/field/<landfill_id>/<YYYY-MM-DD>_<doc_type>_<slug>.<ext>
```

Examples:

```
data/raw/field/cdm_78/2026-11-10_weighbridge_2025.xlsx
data/raw/field/cdm_78/2026-11-10_liner_drawing.pdf
data/raw/field/cdm_78/2026-11-10_waste_sampling_sheet.pdf
```

---

## 5. Record every file in the manifest

File: `data/interim/manual_uploads_manifest.csv`

One row per file.

| Column | Meaning |
|---|---|
| `upload_id` | `UP-0001`, `UP-0002`, ... |
| `landfill_id` | master site ID (`cdm_78`) or `ALL` |
| `registry_ref` | CDM ref where applicable |
| `source_name` | e.g. `SIPSN TPA/TPST` |
| `document_type` | `pdd_appendix`, `validation_report`, `monitoring_report`, `facility_inventory`, `composition_study`, `operator_record`, `field_measurement`, `permit`, `photo`, `other` |
| `file_path` | path relative to the repo root |
| `source_url` | exact URL used |
| `retrieved_date` | `YYYY-MM-DD` |
| `retrieved_by` | your name or initials |
| `pages` | page range or sheet name, e.g. `p12-14` or `Sheet: TPA` |
| `field_targets` | semicolon-separated master columns, e.g. `liner_type;leachate_system` |
| `confidence` | `high`, `medium`, `low` |
| `status` | `pending`, `resolved`, or `rejected` |
| `bytes` | file size in bytes |
| `sha256` | full SHA256 checksum (verify duplicates rather than deleting originals) |
| `original_path` | where the file lived before being copied into `data/raw/manual/` |
| `notes` | caveats, e.g. "city-level proxy, not facility-specific" |
| `parse_status`, `parsed_fields`, `parsed_at` | added by `scripts/14_ingest_excel_sources.py` after parsing |

Example row (real, resolved upload):

```csv
UP-0001,cdm_1582,1582,UNFCCC CDM project page,pdd_appendix,data/raw/manual/cdm/1582/1582_appendix2_cdm_landfill_details.xls,https://cdm.unfccc.int/UserManagement/FileStorage/6WJEWR6ZHG8W8Z5XPL5NIM6KGF89OJ,2026-11-03,manual,Sheets: Data Sheet Oct 06; Population; Disposal Data; Methane Generation,opening_year;closure_year;design_type;design_capacity_m3;collection_efficiency;waste_tonnes_cumulative,high,resolved,1154560,f0fd77c10d52ed58e56c2bd5d63b83fc63ca5dd2d30f4e941f596daf0ebf7a9c,data/cdm landfill details.xls,OLE2 legacy XLS (magic D0CF11E0). Pontianak / TPA Batu Layang landfill workbook (ref 1582 Appendix 2). Original left in place; duplicate verified by SHA256.,parsed,opening_year;closure_year;design_type;design_capacity_m3;capture_efficiency;waste_tonnes_cumulative;composition,2026-11-03T15:19:08+00:00
```

---

## 6. Field mapping cheat sheet

### `sites.csv`

| Column | Required format | Example |
|---|---|---|
| `waste_composition_fractions` | JSON dict of fractions 0–1; keys `food`, `paper`, `plastic`, `glass`, `metal`, `textile`, `wood`, `other` | `{"food": 0.44, "paper": 0.12, "other": 0.31}` |
| `collection_efficiency` | fraction 0–1 | `0.70` |
| `ce_basis` | `reported`, `assumed`, `measured`, `not_reported` | `measured` |
| `liner_type` | lowercase tokens joined by `+`: `hdpe`, `gcl`, `compacted_clay`, `geomembrane`, `composite` | `hdpe+compacted_clay` |
| `leachate_system` | lowercase tokens joined by `+`: `collection`, `extraction`, `treatment`, `recirculation`, `pond` | `collection+treatment` |
| `design_capacity_tonnes` | numeric tonnes | `500000` |
| `annual_waste_inflow_tonnes` | numeric tonnes/year | `431100` |
| `annual_inflow_year` | integer year | `2008` |
| `annual_inflow_basis` | short token | `weighbridge`, `pdd_table_last_year` |
| `opening_year`, `closure_year` | integer year | `1994` |
| `design_type` | `sanitary_landfill`, `controlled_dump`, `open_dump` | `sanitary_landfill` |
| `cover_frequency` | `daily`, `final`, `daily+final` | `daily+final` |
| `gas_control_presence` | lowercase tokens joined by `+` | `active_extraction+flare+power_generation` |
| `latitude`, `longitude` | decimal degrees | `23.70527` |
| `waste_source_type` | short token | `municipal_solid_waste` |
| `waste_history_years` | numeric years | `28` |
| `waste_tonnes_cumulative` | numeric tonnes | `8065600` |

### `annual_observations.csv`

| Column | Format |
|---|---|
| `year` | integer |
| `waste_inflow_tonnes` | numeric |
| `lfg_total_nm3` | numeric |
| `lfg_flared_nm3` | numeric |
| `lfg_utilised_nm3` | numeric |
| `ch4_fraction` | fraction 0–1 |
| `methane_collected_tonnes` | numeric |
| `methane_flared_tonnes` | numeric |
| `methane_utilised_tonnes` | numeric |
| `collection_efficiency` | fraction 0–1 |
| `period_start`, `period_end` | `YYYY-MM-DD` |
| `is_measured` | `True` / `False` |

---

## 7. Evidence and confidence rules

- Prefer **site-specific** values. Use city/national values only when explicitly adopted by the project or clearly labelled as a proxy.
- Record the exact **page, table, or cell** in the manifest.
- Never copy a number just because it appears near a keyword. Check what it describes.
- Leave a field blank if the source does not state it. Do not infer liner/leachate/CE.
- For composition, note if components do not sum to ~1.0 (the master allows slight deviation, but it must be explained).
- Distinguish:
  - **gas collection efficiency** (valid for `collection_efficiency`) from **waste collection rate** (not valid).
  - **bottom/base liner** (valid for `liner_type`) from **cap/cover liner** or **HDPE pipes** (not valid).
  - **leachate generation** from **treatment capacity** or **storage tank capacity** (not the same field).
- Negative statements ("no liner", "no leachate collection") are still useful for `design_type`/`gas_control_presence`, but should not be converted into positive tokens.

---

## 8. What not to collect

- Monitoring reports for the 53 `no_mrs_available` sites — they do not exist.
- MOENV Taiwan or Pakistan operator data — no current master sites in those countries.
- Generic IPCC default composition tables unless the project explicitly adopts them as its site composition.
- HDPE pipe/pipeline mentions as liner evidence.
- Cap/cover synthetic liners as bottom liners.
- Waste-collection rates as gas collection efficiency.
- Copies of the existing PDDs — they are already in `data/raw/cdm/census/pdd/`.

---

## 9. Step-by-step checklist

1. ~~Download UNFCCC refs 1582, 2518, 2525 **Appendix 2 — cdm landfill details**.~~ **Done** — ref 1582 is in `data/raw/manual/cdm/1582/`; refs 2518/2525 were fetched by `13_fetch_cdm_attachments.py` into `data/raw/cdm/attachments/`.
2. ~~Export the **SIPSN TPA/TPST** facility table (Indonesia).~~ **Done** — `data/raw/manual/sipsn/ALL/sipsn_tpa_facilities_2025.xlsx`.
3. If easy, export **SIPSN waste composition** for the cities of `cdm_2518` and `cdm_4566`.
4. Register for the **Korea Public Data Portal** and download waste-facility datasets.
5. Access **SWCorp Malaysia** in a browser and download landfill reports/studies.
6. Access **Thailand PCD** and download MSW/landfill reports.
7. Download **ADB/World Bank Matuail** reports for `cdm_78`.
8. Export the **WasteMAP** site inventory as a cross-check.
9. Do **not** pursue the 53 UNFCCC MRs.
10. Do **not** pursue MOENV Taiwan or Pakistan unless adding new sites.
11. Put every file in the folder conventions above.
12. Add one row per file to `data/interim/manual_uploads_manifest.csv`.
13. Optional: download validation reports for the 46 sites that have them (low expected yield).
14. Optional: field/operator visits — use `data/raw/field/<landfill_id>/` and record weighbridge, permits, liner/leachate drawings, composition sampling, LFG logs.
15. Tell me when the files and manifest are ready; I will parse, validate, add proposals to `actual_values.csv`, and integrate them.

---

## 10. How integration will work

For each uploaded file:

1. Parse the document and extract only field-relevant values.
2. Add proposals to `data/interim/actual_values.csv` with:
   - target table/column
   - proposed value and format
   - evidence file, page, and snippet
   - confidence and verification status
3. Validate: target cell is still blank, JSON/format is correct, values are in range, tokens are in the master vocabulary.
4. Integrate with a backup and a before/after diff, exactly as done for the 59 values already applied.
