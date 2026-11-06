# Changelog

## 2026-11-06 — v1.0.0 public release

- Added the publishable `release/v1.0/` package: cleaned single-grain tables,
  data dictionary, QA report, source register, manifest, GeoJSON, dataset card
  and quickstart notebook.
- Split the 609-row mixed-grain observation table into
  `lfg_measurements.csv` (48 measured rows) and `waste_inflow_annual.csv`
  (534 annual rows).
- Kept `m3`/`Nm3` as reported and exposed the unit per row; no unsafe conversion.
- Fixed five `ce_basis`/`qa_ce` inconsistencies, standardised country names and
  dates, dropped the empty `city` column, and added composition completeness
  flags without renormalising fractions.
- Added stable observation/waste IDs, source URLs, outlier flags and PDF-text
  validation evidence (47/48 measured LFG values; 15/15 waste sample).
- Added `LICENSE` (MIT, code), `LICENSE-DATA` (CC BY 4.0, data), `CITATION.cff`,
  `pyproject.toml`, `notebooks/quickstart.ipynb` and `tests/test_release.py`.
- Rewrote the root README and `.gitignore` for a public GitHub release; raw PDFs,
  interim data and local working files are excluded.
- Removed superseded local artefacts: `data/repository/`,
  `data/processed/integrated/`, `data_manifest.csv`, `CLEANUP_DELETED_FILES.txt`,
  `reports/`, `sources/`, `docs/archive/` and stale caches.

## 2026-11-04
- Deep-cleaned the workspace: removed 2,343 redundant/cache/intermediate files
  (274.3 MB) and 427 empty directories. `.venv`, the three master tables and the
  publication repository copy were preserved.
- Recorded every deleted path with size, SHA256, reason and recovery method in
  `CLEANUP_DELETED_FILES.txt`.
- Kept the two applied attachment workbooks (refs 2518 and 2525); the other 227
  CDM attachment payloads were removed and can be re-fetched with
  `scripts/13_fetch_cdm_attachments.py`.
- Canonicalised 22 PDD paths in `data/interim/cdm/cdm_document_manifest.csv` to
  `data/raw/cdm/census/pdd/`; removed the duplicate `data/raw/cdm/pdd/` tree.
- Added `scripts/15_build_integrated_dataset.py` and the integrated deliverable:
  `data/processed/integrated/sites_108_integrated.csv` (108 x 67) and
  `sites_108_integrated.xlsx` with `Sites`, `Annual Observations` and `Climate`
  sheets.
- Regenerated `data_manifest.csv` for the 534 remaining files.

## 2026-11-03
- Installed and pinned `playwright==1.64.1` and `python-calamine==0.9.1`.
- Created the durable manual upload loop: `data/raw/manual/` with SHA256-tracked
  uploads for the ref-1582 appendix workbook and the SIPSN 2025 facility inventory.
- Added `scripts/_file_sniff.py`: magic-byte detection for PDF/OLE2/XLSX/ZIP/DOC
  plus the 212-byte Incapsula challenge filter.
- Added `scripts/13_fetch_cdm_attachments.py`: fetches all 230 CDM data
  attachments across 94 projects from live project pages, resumable, with
  `actual_format`, SHA256 and provenance recorded in the CDM manifest.
- Added `scripts/14_ingest_excel_sources.py`: parses the three CDM "landfill
  details" workbooks (refs 1582, 2518, 2525) and the SIPSN facility inventory,
  triages downloaded attachments into covariate candidates, and applies
  validated null-fills with an audit trail.
- Applied 10 evidence-backed null-fills (15 cells including companions); logged
  12 conflicts and 3 holds without overwriting master values.
- Extracted physical covariates (area, disposal area, cells, depth, disposal
  history) for refs 1582/2518/2525 into
  `data/interim/excel_sources/landfill_details_covariates.csv`.

## 2026-11-02
- Added extraction coverage audit (interim/cdm/extraction_coverage.csv) for all 206 MRs.
- Extracted verified emission reductions (tCO2e) with GWP where available.
- Re-geocoded sites with missing/wrong coordinates; resolved shared coordinate groups.
- Added has_observations, n_observation_rows, n_metered_periods_census_flag to sites.
- Synced processed/ and repository/.
- Added tests and virtualenv setup.
