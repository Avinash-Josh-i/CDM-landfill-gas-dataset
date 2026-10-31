# Asian Landfill Data Repository

Phase 1 publication build (no modeling). This repository assembles CDM-verified landfill data with provenance and QA flags.

## Structure

```
data/raw/{climate,cdm/{index,mr,census},national}
data/interim/{climate,cdm}
data/processed/{sites.csv,annual_observations.csv,climate.csv}
data/repository/  (publication copy + README + data dictionary + manifest)
scripts/           (collection, extraction, census, Tier B, repository assembly)
templates/         (sites/annual_observations/climate templates)
sources/           (source registry)
docs/              (archived docs)
```

## Evidence tiers

- **Tier A** (22 sites): CDM sites with metered landfill-gas series and >=10 years documented waste placement. `annual_observations.csv` contains metered LFG volumes, CH4 fractions, derived methane, and period provenance. Collection efficiency provenance is tracked (`ce_basis`: measured/assumed/reported/not_reported).
- **Tier B / CDM-Adjacent Engineered Landfill Specifications** (86 sites): non-metered engineered landfills documented in CDM PDDs with no metered LFG series. These are a CDM-adjacent subset (not a representative survey of all Asian municipal dumps). Design/operation attributes (liners, covers, leachate/gas control, waste composition where reported) and waste inflow are harvested where stated; nothing is inferred or modeled.
- **Climate**: NASA POWER monthly-derived annual temperature, humidity, precipitation (joined where coordinates exist). Climate TRACE provides the Asia-wide solid-waste spine.

## Outputs

| File | Grain | Description |
|---|---|---|
| `data/processed/sites.csv` | one row per landfill | identity, coordinates, design, waste history, QA flags, provenance |
| `data/processed/annual_observations.csv` | one row per landfill-year | waste inflow (Tier A/B where available) and metered LFG/methane (Tier A) |
| `data/processed/climate.csv` | one row per landfill-year | NASA POWER annual climate joined to sites with coordinates |

Publication copies and metadata live in `data/repository/` (`manifest.csv` with SHA-256 checksums, `data_dictionary.md`, `README.md`).

## Quick start (Phase 1)

```bash
python scripts/01_collect_climatetrace.py --from-raw
python scripts/02_collect_nasa_power.py  # for repository spine
python scripts/05_download_cdm_docs.py --refs <tier_a_refs>
python scripts/06_extract_cdm_data.py --refs <tier_a_refs>
python scripts/07_cdm_census.py         # build census/gates
python scripts/08_collect_tier_b.py
python scripts/09_build_repository.py coords
python scripts/02_collect_nasa_power.py
python scripts/09_build_repository.py build
```

## Principles

- Missing values stay missing; nothing fabricated.
- CERs/emissions are never treated as metered LFG.
- Monitoring periods come only from inside PDFs; CE only from explicit percentages.
- `f_vCH4`, `FG`, `h` never populate `ch4_fraction`. `cumulative_is_complete` false if any year missing.
- Every site and observation carries provenance; QA flags indicate proxy/assumed/not_reported.
