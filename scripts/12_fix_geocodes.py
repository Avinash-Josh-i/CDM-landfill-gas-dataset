"""Improved geocoding for CDM sites - use better queries to get actual landfill/city locations."""
from __future__ import annotations

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


def geocode_query(q, session):
    try:
        r = session.get(ENDPOINT, params={
            "q": q, "format": "jsonv2", "limit": 1,
            "addressdetails": 1, "accept-language": "en"
        }, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if data and data[0].get('lat') and data[0].get('lon'):
                item = data[0]
                # Avoid country-level results
                if item.get('addresstype') == 'country' or item.get('class') == 'boundary' and item.get('type') == 'administrative' and item.get('place_rank', 0) > 10:
                    return None
                return float(item['lat']), float(item['lon']), item.get('display_name')
        time.sleep(1.2)
    except Exception as e:
        print(f"    Error: {e}")
    return None


def main():
    sites = pd.read_csv(PROCESSED / 'sites.csv')
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    
    # Sites with bad geocodes (country centroids)
    bad = [(34.54, 108.92), (-2.48, 117.89), (36.64, 127.7), (30.81, 34.86), (25.62, 42.35), (4.57, 102.27), (24.0, 54.0), (41.32, 63.95)]
    
    fixed = 0
    for idx, row in sites.iterrows():
        lat, lon = row['latitude'], row['longitude']
        if pd.isna(lat) or pd.isna(lon):
            continue
        # Check if it's a bad centroid
        is_bad = any(abs(lat - b[0]) < 0.01 and abs(lon - b[1]) < 0.01 for b in bad)
        if not is_bad and row['coordinate_source'] not in ['geocoded_name_internet']:
            continue
        if is_bad or row['coordinate_source'] == 'geocoded_name_internet':
            sid = row['landfill_id']
            name = str(row['landfill_name'])
            country = str(row['country'])
            
            # Better queries
            queries = []
            # Extract city names
            if 'Shenyang' in name: queries.append('Shenyang Laohuchong, China')
            elif 'Liaoning' in name: queries.append('Shenyang, China')
            elif 'Taiyuan' in name: queries.extend(['Taiyuan Xingou, China', 'Taiyuan, China'])
            elif 'Dalian' in name: queries.append('Dalian, China')
            elif 'Hunan' in name and 'Loudi' in name: queries.append('Loudi, China')
            elif 'Xiangtan' in name: queries.append('Xiangtan, China')
            elif 'Huizhou' in name: queries.append('Huizhou, China')
            elif 'Qingdao' in name: queries.append('Qingdao, China')
            elif 'Wuhan' in name: queries.append('Wuhan, China')
            elif 'Linyi' in name: queries.append('Linyi, China')
            elif 'Baoding' in name: queries.append('Baoding, China')
            elif 'Changchun' in name: queries.append('Changchun, China')
            elif 'Shenzhen' in name: queries.append('Shenzhen, China')
            elif 'Zouping' in name: queries.append('Zouping, China')
            elif 'Huangshi' in name: queries.append('Huangshi, China')
            elif 'Luohe' in name: queries.append('Luohe, China')
            elif 'Jiyuan' in name: queries.append('Jiyuan, China')
            elif 'Changsha' in name: queries.append('Changsha, China')
            elif 'Baoji' in name: queries.append('Baoji, China')
            elif 'Anyang' in name: queries.append('Anyang, China')
            elif 'Xining' in name: queries.append('Xining, China')
            elif 'Ningbo' in name: queries.append('Ningbo, China')
            elif 'Luoyang' in name: queries.append('Luoyang, China')
            elif 'Guilin' in name: queries.append('Guilin, China')
            elif 'Zunyi' in name: queries.append('Zunyi, China')
            elif 'Yichang' in name: queries.append('Yichang, China')
            elif 'Shangqiu' in name: queries.append('Shangqiu, China')
            elif 'Mudanjiang' in name: queries.append('Mudanjiang, China')
            elif 'Liuzhou' in name: queries.append('Liuzhou, China')
            elif 'Handan' in name: queries.append('Handan, China')
            elif 'Pontianak' in name: queries.append('Pontianak, Indonesia')
            elif 'Makassar' in name: queries.append('Makassar, Indonesia')
            elif 'Palembang' in name: queries.append('Palembang, Indonesia')
            elif 'Bantargebang' in name: queries.append('Bantar Gebang, Bekasi, Indonesia')
            elif 'Mokpo' in name: queries.append('Mokpo, South Korea')
            elif 'Gwangju' in name: queries.append('Gwangju, South Korea')
            elif 'Jinju' in name: queries.append('Jinju, South Korea')
            elif 'Wonju' in name: queries.append('Wonju, South Korea')
            elif 'Changwon' in name: queries.append('Changwon, South Korea')
            elif 'Jeddah' in name: queries.append('Jeddah, Saudi Arabia')
            elif 'Ipoh' in name: queries.append('Ipoh, Malaysia')
            elif 'Dubai' in name: queries.append('Dubai, UAE')
            elif 'Yoshlik' in name or 'Uzbekistan' in name: queries.append('Tashkent, Uzbekistan')
            else:
                # Try to extract city from name
                m = re.search(r'(?:in|at|of)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', name)
                if m:
                    queries.append(f"{m.group(1)}, {country}")
                queries.append(f"{country} landfill")
            
            print(f"{sid}: {name[:50]}...")
            for q in queries:
                coords = geocode_query(q, session)
                if coords:
                    print(f"  → {coords[2][:60]} ({coords[0]:.4f}, {coords[1]:.4f})")
                    sites.at[idx, 'latitude'] = coords[0]
                    sites.at[idx, 'longitude'] = coords[1]
                    sites.at[idx, 'coordinate_source'] = 'geocoded_precise'
                    sites.at[idx, 'qa_coords'] = 'ok'
                    fixed += 1
                    break
            else:
                print(f"  → Still bad/unresolved")
    
    sites.to_csv(PROCESSED / 'sites.csv', index=False)
    sites.to_csv(Path('data/repository/sites.csv'), index=False)
    sites[['landfill_id', 'latitude', 'longitude', 'coordinate_source']].to_csv(INTERIM_CLIMATE / 'site_coordinates.csv', index=False)
    print(f"\nFixed {fixed} sites")


if __name__ == '__main__':
    main()
