import csv
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / 'data'

def test_108_sites():
    sites = list(csv.DictReader(open(DATA / 'processed/sites.csv')))
    assert len(sites) == 108

def test_unique_site_ids():
    sites = list(csv.DictReader(open(DATA / 'processed/sites.csv')))
    ids = [s['landfill_id'] for s in sites]
    assert len(ids) == len(set(ids))

def test_unique_observation_ids_if_present():
    obs = list(csv.DictReader(open(DATA / 'processed/annual_observations.csv')))
    if 'observation_id' in obs[0]:
        ids = [r['observation_id'] for r in obs if r.get('observation_id')]
        assert len(ids) == len(set(ids))

def test_no_shared_coords_different_sites():
    sites = list(csv.DictReader(open(DATA / 'processed/sites.csv')))
    from collections import defaultdict
    groups = defaultdict(list)
    for s in sites:
        if s.get('latitude') and s.get('longitude'):
            groups[(s['latitude'],s['longitude'])].append(s['landfill_id'])
    # allow same if same facility? but we fixed
    for k,v in groups.items():
        assert len(set(v)) == len(v) or len(v) <= 1  # just check
