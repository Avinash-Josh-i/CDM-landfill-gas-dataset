# Sources and attribution

This release is a **derived compilation**. The raw PDFs, workbooks and API
responses are not redistributed. Each derived row links to a public source URL
where one is available.

## Primary sources

| Source | What it supplied | URL | Access |
|---|---|---|---|
| UNFCCC CDM project search | Project identity, host party, methodology, registration date, PDD and monitoring-report links | https://cdm.unfccc.int/Projects/projsearch.html | Public web/PDF |
| UNFCCC CDM project design documents (PDDs) | Design attributes, waste history, composition, collection efficiency, annual waste inflow | Project-specific URLs in `sites_108.csv` (`pdd_url`) and `waste_inflow_annual.csv` (`source_url`) | Public PDF |
| UNFCCC CDM monitoring reports | Metered LFG volume, flared/utilised volume, methane concentration, methane masses | Project-specific URLs in `lfg_measurements.csv` (`source_url`) | Public PDF |
| NASA POWER | Annual temperature, relative humidity and precipitation for 2010-2025 | https://power.larc.nasa.gov/ | Public API |
| Climate TRACE | Asia-wide landfill site spine and coordinates only | https://climatetrace.org/data | Public API/bulk |
| SIPSN (Indonesia) | 2025 site-level waste inflow for two Indonesian sites | https://sampahnasional.kemenlh.go.id/portal-indikatif/fasilitas/tpa-tpst | Public portal/Excel |
| OpenStreetMap Nominatim | Geocoding of site localities where PDD coordinates were missing | https://nominatim.openstreetmap.org/ | Public API, rate-limited |
| CDM landfill-detail workbooks (refs 1582, 2518, 2525) | Applied engineering covariates and null-fills, with audit trail | UNFCCC CDM project attachments | Public PDF/XLS |

## What is *not* redistributed

- Raw PDDs, monitoring reports and attachment PDFs.
- The original SIPSN workbook.
- The original Climate TRACE and NASA POWER API responses.
- Internal extraction logs and local file paths.

The release publishes **extracted facts, source URLs, QA flags and derived
tables** only. Users who need the original documents should retrieve them from
the URLs in the tables, subject to the source terms.

## Attribution

If you use this dataset, please cite the dataset (see `CITATION.cff`) and
acknowledge the underlying sources:

- **UNFCCC CDM** for project design documents and monitoring reports.
- **NASA POWER** for climate covariates.
- **Climate TRACE** for the site spine and coordinates used during assembly.
- **SIPSN / Ministry of Environment of Indonesia** for the 2025 facility inflow values.
- **OpenStreetMap contributors** for geocoding where used.

## Licensing of source material

The release compilation is offered under CC BY 4.0 (see `LICENSE-DATA`). Source
documents remain subject to the terms of their publishers. This release does not
grant rights to redistribute those source documents. Check the UNFCCC CDM,
SIPSN, NASA POWER and Climate TRACE terms before reusing source material.

## Citation of the dataset

Use the DOI assigned by Zenodo once the record is published. Until then, cite the
version and URL in `CITATION.cff`.
