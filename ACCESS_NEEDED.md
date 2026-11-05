# Access needed

## No account/key required
- Climate TRACE public API
- NASA POWER public API (monthly/point)
- Public UNFCCC CDM project pages and monitoring reports
- OpenStreetMap Nominatim (polite, rate-limited)

## One free credential needed later
### Copernicus Climate Data Store (ERA5-Land)
Create a free CDS account and configure the official API token locally in `~/.cdsapirc`.
Do not commit tokens. ERA5-Land is optional and was not used in Phase 1.

## Manual downloads may be needed
Some national portals use CAPTCHAs or require manual export. Place files under `data/raw/national/<ISO3>/` and add parsers as needed.
