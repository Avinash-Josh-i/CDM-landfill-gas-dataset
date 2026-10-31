"""Geocode CDM landfill localities that have no coordinate in their PDD.

Why this exists
---------------
Only about a quarter of the census PDDs state a coordinate.  The rest name a town,
municipality or district but never give a latitude/longitude.  Dropping those sites from
the climate join would bias the repository towards the few projects with a well-written
location section, so this script resolves the *named locality* through OpenStreetMap
Nominatim and records it as an explicitly approximate, city-level proxy.

It never invents a landfill location.  Every output row carries the query that produced
it, the matched OSM place name and ``coordinate_precision=locality`` so downstream users
can filter it out.  Sites whose locality cannot be resolved stay missing.

Outputs
-------
data/interim/climate/geocoded_sites.csv   one row per resolved landfill
data/interim/climate/geocode_cache.json   raw query -> response cache

Usage
-----
    python scripts/10_geocode_sites.py
    python scripts/10_geocode_sites.py --refs 71 941 1258 --refresh
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import INTERIM_CDM, INTERIM_CLIMATE

CENSUS = INTERIM_CDM / "census" / "cdm_census_lfg.csv"
TEXT_DIR = INTERIM_CDM / "census" / "text"
OUT = INTERIM_CLIMATE / "geocoded_sites.csv"
CACHE = INTERIM_CLIMATE / "geocode_cache.json"

ENDPOINT = "https://nominatim.openstreetmap.org/search"
UA = "AsiaLandfillResearch/0.1 (academic research)"
PAUSE = 1.1  # Nominatim usage policy: max 1 request/second

COUNTRY = {
    "China": "China", "India": "India", "Indonesia": "Indonesia",
    "Philippines": "Philippines", "Malaysia": "Malaysia", "Thailand": "Thailand",
    "Republic of Korea": "South Korea", "Korea": "South Korea",
    "Viet Nam": "Vietnam", "Vietnam": "Vietnam", "Nepal": "Nepal",
    "Bangladesh": "Bangladesh", "Pakistan": "Pakistan", "Sri Lanka": "Sri Lanka",
    "Japan": "Japan", "Cambodia": "Cambodia", "Laos": "Laos", "Myanmar": "Myanmar",
    "Mongolia": "Mongolia", "Singapore": "Singapore", "Taiwan": "Taiwan",
    "Hong Kong": "Hong Kong", "Israel": "Israel",
    "Iran (Islamic Republic of)": "Iran", "Iran": "Iran",
    "Syrian Arab Republic": "Syria", "United Arab Emirates": "United Arab Emirates",
    "Saudi Arabia": "Saudi Arabia", "Jordan": "Jordan", "Uzbekistan": "Uzbekistan",
    "Kazakhstan": "Kazakhstan", "Kyrgyzstan": "Kyrgyzstan", "Tajikistan": "Tajikistan",
    "Turkmenistan": "Turkmenistan", "Bhutan": "Bhutan", "Maldives": "Maldives",
    "Brunei Darussalam": "Brunei", "Timor-Leste": "Timor-Leste",
    "Afghanistan": "Afghanistan",
}

GENERIC = {
    "landfill", "landfills", "site", "project", "plant", "gas", "lfg", "msw",
    "municipal", "solid", "waste", "disposal", "dump", "dumpsite", "the", "a", "an",
    "city", "municipality", "province", "county", "region", "area", "village",
    "district", "town", "community", "island", "state", "prefecture", "zone",
    "sanitary", "controlled", "engineered", "open", "new", "phase", "stage",
    "republic", "democratic", "people", "kingdom", "union", "federal",
}

# Nominatim classes that describe a populated place / administrative unit rather than
# a building, shop or road.
PLACE_CLASSES = {"place", "boundary"}
PLACE_TYPES = {
    "city", "town", "village", "hamlet", "municipality", "suburb", "quarter",
    "neighbourhood", "county", "state", "district", "region", "province",
    "administrative", "borough", "locality", "island", "city_district",
}

PLACE = r"[A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-]+){0,3}"

LOCATION_PATTERNS = [
    rf"(?:project|landfill|site|plant|activity)[^.]{{0,120}}?(?:is\s+)?(?:located|situated)\s+(?:in|at|near|on)\s+(?:the\s+)?({PLACE})",
    rf"(?:located|situated)\s+(?:in|at|near|on)\s+(?:the\s+)?({PLACE})",
    rf"(?:in|at|near)\s+(?:the\s+)?({PLACE})\s+(?:city|municipality|province|county|district|prefecture)",
]

TITLE_PATTERNS = [
    # "Landfill Gas ... at the Matuail Landfill"
    rf"\b(?:at|in|near)\s+(?:the\s+)?({PLACE})\s+(?:landfill|dumpsite|dump|disposal)",
    # "Nanjing Tianjingwa Landfill ..." / "Krubong Melaka LFG ..."
    rf"^({PLACE})\s+(?:landfill|msw|municipal|integrated|solid|lfg|gas)",
]


def clean_locality(raw: str) -> str | None:
    words = [w for w in re.split(r"\s+", raw.strip()) if w]
    # drop trailing generic descriptors ("X Landfill", "X City")
    while words and words[-1].lower().strip(".,") in GENERIC:
        words.pop()
    if not words:
        return None
    locality = " ".join(words).strip(" ,.;:")
    if len(locality) < 3 or locality.isdigit():
        return None
    if locality.lower() in GENERIC:
        return None
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", locality):
        return None
    return locality


def variants(locality: str) -> list[str]:
    """'Nanjing Tianjingwa' -> also try 'Nanjing' and 'Tianjingwa'."""
    out = [locality]
    parts = locality.split()
    if len(parts) > 1:
        for cand in (parts[0], parts[-1], " ".join(parts[:2])):
            if cand not in out:
                out.append(cand)
    return [v for v in out if len(v) >= 3 and v.lower() not in GENERIC]


def candidates(title: str, text: str, country: str = "") -> list[str]:
    """Locality guesses, title first (usually the most specific place name)."""
    raw: list[str] = []
    for pat in TITLE_PATTERNS:
        m = re.search(pat, title or "", re.I | re.M)
        if m:
            loc = clean_locality(m.group(1))
            if loc:
                raw.append(loc)
    flat = re.sub(r"\s+", " ", text or "")
    for pat in LOCATION_PATTERNS:
        for m in re.finditer(pat, flat):
            loc = clean_locality(m.group(1))
            if loc:
                raw.append(loc)

    out: list[str] = []
    for loc in raw:
        if country and loc.lower() == country.lower():
            continue
        for v in variants(loc):
            if v.lower() == (country or "").lower():
                continue
            if v not in out:
                out.append(v)
    return out[:8]


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))


def query(q: str, cache: dict, refresh: bool, session: requests.Session) -> list[dict]:
    if not refresh and q in cache:
        return cache[q]
    r = session.get(ENDPOINT, params={"q": q, "format": "jsonv2", "limit": 3,
                                     "addressdetails": 1, "accept-language": "en"},
                    timeout=45)
    r.raise_for_status()
    data = r.json()
    cache[q] = data
    save_cache(cache)
    time.sleep(PAUSE)
    return data


def pick(results: list[dict], locality: str, country: str = "") -> dict | None:
    """Prefer an administrative place whose name matches the query locality."""
    good = []
    for x in results:
        if not x.get("lat") or not x.get("lon"):
            continue
        cls = x.get("class", "")
        typ = x.get("type", "")
        # keep places/boundaries (cities, districts); skip street/building/amenity
        if cls not in PLACE_CLASSES and cls != "":
            # 'place' is common for villages; boundary for admin
            pass
        if cls == "highway" or cls == "building" or cls == "amenity":
            continue
        good.append(x)
    if not good:
        return None
    target = locality.lower()

    def score(x):
        name = str(x.get("name", "")).lower()
        addr = x.get("address", {}) or {}
        names = [str(v).lower() for v in addr.values() if v]
        display = str(x.get("display_name", "")).lower()
        exact = name == target or target in names
        token_match = sum(1 for t in re.findall(r"[a-z]{3,}", target) if t in display)
        rank = x.get("place_rank", 0)
        in_country = (country.lower() in display) if country else False
        return (exact, in_country, token_match, -rank)

    good.sort(key=score, reverse=True)
    best = good[0]
    hay = " ".join([str(best.get("display_name", "")), str(best.get("name", ""))]).lower()
    if not any(tok in hay for tok in re.findall(r"[a-z]{3,}", target) if tok not in GENERIC):
        return None
    if country and country.lower() not in hay and "korea" not in country.lower():
        # allow if it's a clear administrative match nearby? Nominatim usually includes country
        pass
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", nargs="*", type=int)
    ap.add_argument("--refresh", action="store_true", help="ignore the query cache")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    census = pd.read_csv(CENSUS)
    if args.refs:
        census = census[census["ref"].astype(int).isin(args.refs)]
    if args.limit:
        census = census.head(args.limit)

    cache = load_cache()
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    rows, misses = [], []
    for i, r in census.reset_index(drop=True).iterrows():
        ref = int(r["ref"])
        title = str(r.get("title") or "")
        country = COUNTRY.get(str(r.get("host_party")), str(r.get("host_party") or ""))
        txt = TEXT_DIR / f"pdd_{ref}.txt"
        text = txt.read_text() if txt.exists() else ""

        hit = None
        tried = []
        for loc in candidates(title, text, country):
            for q in (f"{loc}, {country}", loc):
                tried.append(q)
                try:
                    res = query(q, cache, args.refresh, session)
                except Exception as exc:  # network hiccup: keep going, record it
                    misses.append({"ref": ref, "reason": f"{type(exc).__name__}: {exc}", "tried": q})
                    res = []
                best = pick(res, loc, country)
                if best:
                    hit = (loc, q, best)
                    break
            if hit:
                break

        if hit:
            loc, q, best = hit
            rows.append({
                "landfill_id": f"cdm_{ref}",
                "ref": ref,
                "latitude": round(float(best["lat"]), 5),
                "longitude": round(float(best["lon"]), 5),
                "locality": loc,
                "geocode_query": q,
                "matched_place": best.get("display_name"),
                "matched_type": best.get("addresstype") or best.get("type"),
                "coordinate_source": "geocoded_locality_approx",
                "coordinate_precision": "locality",
            })
            print(f"{i+1}/{len(census)} {ref}: {loc} -> {best.get('display_name', '')[:70]}")
        else:
            misses.append({"ref": ref, "reason": "no_result", "tried": "; ".join(tried)})
            print(f"{i+1}/{len(census)} {ref}: unresolved")

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    pd.DataFrame(misses).to_csv(INTERIM_CLIMATE / "geocode_misses.csv", index=False)
    print(f"\nwrote {OUT} ({len(out)} resolved, {len(misses)} unresolved)")


if __name__ == "__main__":
    main()
