# CDM Landfill Gas Projects - Raw Data

This directory stores raw CDM documentation and extracted data.

## Structure
- `pdd/` - Project Design Documents (PDF)
- `mr/` - Monitoring Reports (PDF)  
- `extracted/` - Manually extracted JSON/CSV files per project

## Priority Projects (Start Here)
Based on literature, these are known high-quality Tier A candidates:

### South Korea
- **Project 0454** - Sudokwon Landfill Gas Electricity Generation (Seoul metropolitan area). Very well documented, long time series.

### China
- Many projects - need to evaluate each for data completeness

### Thailand
- Several registered landfill gas projects

### Malaysia, Philippines, Indonesia
- CDM projects exist but need assessment

## Extraction Workflow
1. Find project on UNFCCC CDM (https://cdm.unfccc.int/Projects/projsearch.html) with Sectoral Scope 13
2. Download PDD from project page
3. Download all available Monitoring Reports
4. Use templates/cdm_extraction_template.csv to extract data
5. Save extracted data to extracted/ as project_id.json or CSV
6. Compute k-inverse once data is compiled

## Notes
- Always record if collection efficiency is measured or assumed
- Convert methane volumes to STP conditions when possible
- Preserve waste composition for L0 calculation
- Don't guess missing values
