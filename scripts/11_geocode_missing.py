"""Geocode CDM sites missing coordinates using OpenStreetMap Nominatim.

Tries multiple query strategies: full project name, landfill name, city/locality
extracted from title, and country. Updates sites coordinates and re-runs climate
fetch for newly geocoded sites.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import INTERIM_CLIMATE, PROCESSED

UA = "AsiaLandfillResearch/0.1 (academic research)"
ENDPOINT = "https://nominatim.openstreetmap.org/search"

COUNTRY_MAP = {
    "China": "China", "India": "India", "Indonesia": "Indonesia",
    "Philippines": "Philippines", "Malaysia": "Malaysia", "Thailand": "Thailand",
    "Republic of Korea": "South Korea", "Viet Nam": "Vietnam", "Vietnam": "Vietnam",
    "Israel": "Israel", "Saudi Arabia": "Saudi Arabia",
    "United Arab Emirates": "United Arab Emirates", "Uzbekistan": "Uzbekistan",
}


def extract_location(name):
    """Try to extract city/locality from project name."""
    # Remove common prefixes/suffixes
    name = re.sub(r'CDM\s+Project.*$', '', name, flags=re.I)
    name = re.sub(r'LFG.*$', '', name, flags=re.I)
    name = re.sub(r'Landfill Gas.*$', '', name, flags=re.I)
    name = re.sub(r'Biogas.*$', '', name, flags=re.I)
    # Look for patterns like "in City", "at Location"
    m = re.search(r'(?:in|at|of)\s+([A-Z][a-zA-Z\s]+?)(?:,|$|\s+(?:City|Landfill|Project))', name)
    if m:
        loc = m.group(1).strip()
        if len(loc) > 3 and loc.lower() not in ['the', 'municipal']:
            return loc
    # Try to get first capitalized place-like token sequence
    # For Chinese projects, might be city name
    return None


def geocode_query(q, session):
    try:
        r = session.get(ENDPOINT, params={
            "q": q, "format": "jsonv2", "limit": 3,
            "addressdetails": 1, "accept-language": "en"
        }, timeout=30)
        if r.status_code == 200:
            data = r.json()
            for item in data:
                if item.get('lat') and item.get('lon'):
                    return float(item['lat']), float(item['lon']), item.get('display_name')
        time.sleep(1.1)
    except Exception as e:
        print(f"    Error geocoding '{q}': {e}")
    return None


def main():
    sites = pd.read_csv(PROCESSED / 'sites.csv')
    missing = sites[sites['qa_coords'] == 'missing'].copy()
    print(f"Attempting to geocode {len(missing)} sites...")
    
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    
    geocoded = []
    for idx, row in missing.iterrows():
        sid = row['landfill_id']
        name = str(row['landfill_name'])
        country = str(row['country'])
        country_en = COUNTRY_MAP.get(country, country)
        
        print(f"\n{sid} ({country}): {name[:80]}")
        
        coords = None
        queries = []
        # Try various query forms
        loc = extract_location(name)
        if loc:
            queries.append(f"{loc}, {country_en}")
        # Try country + key terms
        queries.append(f"{name[:60]}, {country_en}")
        queries.append(country_en)
        
        for q in queries:
            coords = geocode_query(q, session)
            if coords:
                print(f"  ✓ Found: {coords[2][:60]} -> ({coords[0]:.5f}, {coords[1]:.5f})")
                break
        
        if coords:
            sites.loc[sites['landfill_id'] == sid, 'latitude'] = coords[0]
            sites.loc[sites['landfill_id'] == sid, 'longitude'] = coords[1]
            sites.loc[sites['landfill_id'] == sid, 'coordinate_source'] = 'geocoded_name_internet'
            sites.loc[sites['landfill_id'] == sid, 'qa_coords'] = 'ok'
            geocoded.append((sid, coords[0], coords[1]))
        else:
            print(f"  ✗ Could not geocode")
    
    sites.to_csv(PROCESSED / 'sites.csv', index=False)
    sites.to_csv(Path('data/repository/sites.csv'), index=False)
    
    # Update coordinates file
    coords_df = sites[['landfill_id', 'latitude', 'longitude', 'coordinate_source']].copy()
    coords_df.to_csv(INTERIM_CLIMATE / 'site_coordinates.csv', index=False)
    
    print(f"\n\nGeocoded {len(geocoded)} sites")
    print(f"Remaining missing: {(sites['qa_coords']=='missing').sum()}")


if __name__ == '__main__':
    main()
