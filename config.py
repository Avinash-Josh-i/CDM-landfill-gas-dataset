"""Project-wide paths and constants.

Layout (Phase 1, publication build)
------------------------------------
data/raw/climate/                 Climate TRACE API responses
data/raw/cdm/index/               cached UNFCCC CDM project pages (JSON)
data/raw/cdm/mr/                  monitoring-report PDFs (Tier A archive)
data/raw/cdm/census/              census PDDs + census MR sample
data/raw/national/                national / bilateral source files
data/interim/climate/             normalised Climate TRACE + NASA POWER tables
data/interim/cdm/                 CDM discovery, extraction and census tables
data/processed/                   sites.csv, annual_observations.csv, climate.csv
data/repository/                  publication export + data dictionary + manifest
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
REPOSITORY = DATA / "repository"
DOCS = ROOT / "docs"

RAW_CLIMATE = RAW / "climate"
RAW_CDM = RAW / "cdm"
INTERIM_CLIMATE = INTERIM / "climate"
INTERIM_CDM = INTERIM / "cdm"

for _d in (RAW, INTERIM, PROCESSED, REPOSITORY, DOCS,
           RAW_CLIMATE, RAW_CDM, INTERIM_CLIMATE, INTERIM_CDM):
    _d.mkdir(parents=True, exist_ok=True)

COUNTRIES = {
    "IND": "India",
    "CHN": "China",
    "IDN": "Indonesia",
    "PHL": "Philippines",
    "TWN": "Taiwan",
    "HKG": "Hong Kong",
    "KOR": "South Korea",
    "MYS": "Malaysia",
    "THA": "Thailand",
    "NPL": "Nepal",
    "BGD": "Bangladesh",
    "PAK": "Pakistan",
    "LKA": "Sri Lanka",
    "JPN": "Japan",
    "VNM": "Vietnam",
    "KHM": "Cambodia",
    "LAO": "Laos",
    "MMR": "Myanmar",
    "MNG": "Mongolia",
    "SGP": "Singapore",
    "KAZ": "Kazakhstan",
    "UZB": "Uzbekistan",
    "KGZ": "Kyrgyzstan",
    "TJK": "Tajikistan",
    "TKM": "Turkmenistan",
    "BTN": "Bhutan",
    "MDV": "Maldives",
    "BRN": "Brunei",
    "TLS": "Timor-Leste",
    "AFG": "Afghanistan",
    "PRK": "North Korea",
}

START_YEAR = 2010
END_YEAR = 2025

# Evidence tiers used throughout the project.
#   tier_a: metered LFG recovery + documented waste placement history
#   tier_b: engineered landfill with documented design/operation but no metered LFG
#   tier_c: inventory only (coordinates, throughput, atmospheric CH4) - out-of-domain
TIER_DEFINITIONS = {
    "tier_a": "metered LFG recovery + >=10 years documented waste placement",
    "tier_b": "engineered landfill with documented design/operation; no metered LFG",
    "tier_c": "inventory or modelled only; out-of-domain evaluation",
}

# Legacy wide schema used by scripts/03_build_master.py (pre-repository layout).
# The publication schema lives in scripts/09_build_repository.py.
MASTER_COLUMNS = [
    "landfill_id", "landfill_name", "country", "iso3", "city", "latitude", "longitude",
    "opening_year", "closure_year", "year",
    "registry", "registry_ref", "project_title", "methodology",
    "crediting_period_start", "crediting_period_end",
    "waste_accepted_tonnes", "waste_accepted_source", "cumulative_waste_tonnes",
    "food_fraction", "paper_fraction", "wood_fraction", "textile_fraction",
    "organic_fraction", "composition_source",
    "methane_generated", "methane_collected", "methane_flared", "methane_utilized",
    "methane_emitted",
    "collection_efficiency", "ce_measured_or_assumed",
    "l0", "doc", "docf", "mcf", "f", "k_inverse", "k_ci_low", "k_ci_high",
    "k_identifiable",
    "temperature", "precipitation", "humidity", "soil_moisture",
    "evapotranspiration", "cmi", "monsoon_index",
    "landfill_type", "cover_type", "gas_collection_system", "gas_system_expansion_events",
    "site_source", "waste_source", "composition_source", "methane_source",
    "climate_source", "evidence_tier", "data_quality",
    "is_measured", "is_modelled", "is_proxy", "source_notes",
]
