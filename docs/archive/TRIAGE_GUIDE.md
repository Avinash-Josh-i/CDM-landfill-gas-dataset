# CDM Triage Guide for Landfill Gas Projects in Asia

## Goal
Find >=25-30 sites with >=10 years of waste-in-place AND metered LFG recovery for Tier A training set.

## Step 1: Search UNFCCC CDM Database

Go to: https://cdm.unfccc.int/Projects/projsearch.html

### Search filters:
1. **Sectoral Scope**: Select "Waste handling and disposal" (scope 13) - CRITICAL
2. **Host Country**: Do country by country, prioritize in this order:
   - South Korea (KOR) - Start here (Sudokwon is Project 0454)
   - China (CHN) - Many projects
   - Thailand (THA)
   - Malaysia (MYS)
   - Philippines (PHL)
   - Indonesia (IDN)
   - India (IND) - often less detailed but worth checking
   - Others as time permits

3. **Status**: Start with "Registered" (active/completed with monitoring). Also check "Registered" projects.
4. **Scale**: Both Large and Small scale - check both

## Step 2: For Each Project, Triage Criteria

For each project in results, click through and evaluate:

### Must Haves (Tier A candidates)
- [ ] **Has Monitoring Reports** - Look in "Monitoring" tab. More reports = longer time series = better
- [ ] **Reports methane collected/recovered** - Look for "amount of methane captured", "LFG collected", volumes in m³ or Nm³
- [ ] **Waste disposal history** - Annual waste amounts (tonnes/Mg) for multiple years
- [ ] **Collection efficiency** - Either measured or stated. Note if assumed vs measured
- [ ] **>=10 years of data** - Sum up monitoring periods

### Nice to Haves
- [ ] Waste composition breakdown (helps with L0 calculation)
- [ ] Coordinates/location details
- [ ] Opening year of landfill
- [ ] Gas collection system details (active/passive, wells, cover type)

### Red Flags (likely Tier B or not usable)
- [ ] Only PDD, no monitoring reports
- [ ] Only estimates/modelled without metered data
- [ ] Very short crediting period with little data
- [ ] Unclear separation of methane quantities

## Step 3: Quick Assessment Rating

Rate each candidate:
- **Tier A**: Has metered CH4 collected + waste history >=10 years + clear CE → PRIORITY
- **Tier B**: Has data but gaps (missing CE, shorter series, composition missing) → May be usable with assumptions
- **Tier C/Reject**: Insufficient data → Skip for training

## Step 4: Document Everything

For each project you examine, add to `cdm_project_tracker.csv`:
- Project ID/Ref number
- Host country
- Title
- Status, dates
- Has waste data? (Y/N)
- Has methane collected? (Y/N)  
- Has CE? (Y/N)
- Years of data (count)
- Number of monitoring reports
- Priority tier (A/B/C)
- Notes on data availability
- Links to PDD/MR if you download them

## Tips
- Sudokwon (Korea) is Project 0454 - definitely start here
- Look for projects with "electricity generation" or "flaring" - they usually have metering
- "Composting" or other project types won't have landfill gas recovery data
- Some projects might be PoAs (Programmes of Activities) - more complex, maybe skip initially
- Download PDFs immediately if they look promising (UNFCCC site structure can change)

## Known High-Priority Starting Points
Search for these patterns in titles:
- "landfill gas", "LFG", "methane recovery", "biogas"
- Avoid: "composting", "waste recycling" alone
