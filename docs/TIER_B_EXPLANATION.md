# Why Tier B is limited to 86 sites (and what they are)

## Definition
Tier B = CDM-Adjacent Engineered Landfill Specifications. These are sites from the UNFCCC CDM project pipeline that have:
- A CDM PDD on file (in `data/raw/cdm/census/pdd/`)
- No metered landfill-gas monitoring series (`n_metered_periods == 0` in census)
- Failed the Tier A gate (`gate_pass != True`) OR were not metered even if other criteria differed

From the census (`data/interim/cdm/census/cdm_census_lfg.csv`): 86 non-metered sites, 22 metered (Tier A), 14 failed but metered (excluded).

## What limits it to 86?
1. **Source universe is fixed to CDM projects**: We only considered CDM landfill projects discovered/parsed in the census (`cdm_projects_asia.csv` + census). We did not scrape other sources (national inventories, WB/ADB reports, university studies) into Tier B.
2. **Explicit gate**: Tier B requires no metered LFG (`n_metered_periods == 0`). Any site with >=1 metered monitoring period goes to Tier A track (or is excluded if it fails waste-history gate).
3. **Documentation requirement**: Must have a parseable PDD in the census set to extract design attributes. Sites without accessible PDD text/structure aren't harvested.
4. **No inference**: We only fill attributes that are explicitly stated; we don't guess liner/cover/gas systems.

## Are more sites possible?
Yes, but only by expanding the source set beyond CDM:
- Ingest national landfill inventories (e.g. Indonesia SIPSN has site lists; other countries vary)
- Parse development bank/environmental assessment reports
- Add academic case studies with explicit design parameters
- Systematically crawl government waste management portals

Each would require new parsers and provenance tracking. The current 86 is the count of CDM PDDs meeting the "non-metered engineered landfill with documented design/operation" criterion in this pipeline, not a quota.

## Use
Use Tier B to understand Asian sanitary engineering patterns (liner prevalence, cover regimes, leachate/gas control, composition where reported) - but do not treat it as a representative sample of all municipal dumps in any country.
