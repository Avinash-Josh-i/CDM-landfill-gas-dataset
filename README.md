# Asia Landfill Project

Publication-ready repository of **108 Asian landfill sites** (22 Tier A CDM sites
with metered landfill-gas observations + 86 Tier B engineered landfills), with
NASA POWER climate coverage for 2010-2025.

## Main datasets

| File | Rows | Grain |
|---|---|---|
| `data/processed/sites.csv` | 108 | one row per landfill |
| `data/processed/annual_observations.csv` | 609 | one row per observation / monitoring period |
| `data/processed/climate.csv` | 1,728 | one row per landfill-year |

These three files are the stable master tables and were **not modified** by the
2026-11-04 cleanup.

## Integrated 108-site deliverable

- `data/processed/integrated/sites_108_integrated.csv` — flat, one row per site
  (site attributes plus observation and climate summaries; 108 x 67).
- `data/processed/integrated/sites_108_integrated.xlsx` — the same site table
  plus full `Annual Observations` and `Climate` sheets.
- `data/processed/integrated/README.md` — column guide and caveats.

Rebuild with:

```bash
.venv/bin/python scripts/15_build_integrated_dataset.py
```

## Repository layout

- `data/raw/` — source documents (CDM PDDs, monitoring reports, climate JSON,
  manual uploads).
- `data/interim/` — extraction, audit and provenance tables.
- `data/processed/` — clean master tables and the integrated deliverable.
- `data/repository/` — publication copy with metadata.
- `scripts/` — numbered pipeline scripts.
- `docs/` — methodology, ingest and collection guides.

## Housekeeping

The full record of files removed during the deep clean is in
`CLEANUP_DELETED_FILES.txt` (path, size, SHA256, reason and recovery method).
Raw CDM attachments other than the two applied workbooks were removed and can be
re-fetched with `scripts/13_fetch_cdm_attachments.py`.

See `data_dictionary.md` for schema and `.venv` / `requirements.txt` for the
pinned environment.
