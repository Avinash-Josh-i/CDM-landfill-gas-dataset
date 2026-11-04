#!/usr/bin/env python3
"""Ingest and triage Excel/CSV sources; enrich the site spine with null-fills.

Sources handled
---------------
1. ``data/raw/manual/cdm/1582/1582_appendix2_cdm_landfill_details.xls``
   Pontianak / TPA Batu Layang landfill workbook (CDM ref 1582 Appendix 2).
2. ``data/raw/manual/sipsn/ALL/sipsn_tpa_facilities_2025.xlsx``
   KLHK/SIPSN national TPA/TPST facility inventory (397 rows x 34 cols).
3. Every tabular file downloaded by ``13_fetch_cdm_attachments.py`` into
   ``data/raw/cdm/attachments/<ref>/`` (XLS, XLSX and XLSX-in-ZIP).

Design rules
------------
* Values are extracted with a sheet/cell or sheet/row reference.
* Nothing is overwritten: proposals are applied only when the master cell is
  blank, and only after format/vocabulary/range validation.
* Conflicts (source says X, master already says Y) are written to the proposal
  table with ``status=conflict`` and are **not** applied.
* Partial values (e.g. cumulative waste through 2006) are marked ``hold``.
* Every applied value is appended to ``data/interim/actual_values.csv`` so the
  audit trail remains complete.

Usage
-----
    python scripts/14_ingest_excel_sources.py --skip-attachments
    python scripts/14_ingest_excel_sources.py --skip-attachments --apply
    python scripts/14_ingest_excel_sources.py --apply
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA, INTERIM, PROCESSED, RAW  # noqa: E402
from _file_sniff import sha256_file, sniff_file  # noqa: E402

MANUAL = RAW / "manual"
SIPSN = MANUAL / "sipsn" / "ALL" / "sipsn_tpa_facilities_2025.xlsx"
PONTIANAK = MANUAL / "cdm" / "1582" / "1582_appendix2_cdm_landfill_details.xls"
ATT_DIR = RAW / "cdm" / "attachments"
CATALOGUE = INTERIM / "cdm" / "attachment_catalogue.csv"

OUT = INTERIM / "excel_sources"
IND = INTERIM / "indonesia"
SITES = PROCESSED / "sites.csv"
ACTUAL = INTERIM / "actual_values.csv"
MANIFEST = INTERIM / "manual_uploads_manifest.csv"
PROPOSALS = OUT / "excel_source_proposals.csv"
SITE_COVARIATES = IND / "sipsn_site_covariates.csv"
FACILITY_COVARIATES = IND / "sipsn_facility_covariates.csv"
MATCHES = IND / "sipsn_site_matches.csv"
PONTIANAK_KV = OUT / "cdm_1582_landfill_details_extracted.csv"
LANDFILL_DETAILS = OUT / "landfill_details_covariates.csv"
TRIAGE = OUT / "file_triage.csv"
CANDIDATES = OUT / "attachment_candidate_values.csv"
DIFF = INTERIM / "excel_ingest_diff.csv"
REPORT = Path(__file__).resolve().parents[1] / "docs" / "EXCEL_INGEST_REPORT.md"

ALLOWED_DESIGN = {"sanitary_landfill", "controlled_dump", "open_dump"}
LEACHATE_TOKENS = {"collection", "extraction", "treatment", "recirculation", "pond"}
GAS_TOKENS = {
    "active_extraction",
    "flare",
    "passive_venting",
    "power_generation",
    "no_control",
}
DESIGN_MAP = {
    "open dumping": "open_dump",
    "open dump": "open_dump",
    "control landfill": "controlled_dump",
    "controlled landfill": "controlled_dump",
    "semi controlled": "controlled_dump",
    "sanitary landfill": "sanitary_landfill",
}

# Explicit, evidence-backed aliases for the 8 Indonesian master sites.  The
# bundled project (cdm_4566) covers several facilities and is intentionally not
# mapped to a single row.
SITE_ALIASES = {
    "cdm_938": ["sarbagita", "suwung"],
    "cdm_1582": ["batu layang"],
    "cdm_2518": ["tamangapa"],
    "cdm_2525": ["sukawinatan", "palembang"],
    "cdm_2751": ["piyungan"],
    "cdm_4077": ["telaga punggur", "punggur", "batam"],
    "cdm_4566": [],
    "cdm_6486": ["bantargebang", "bantar gebang"],
}

KEYWORD_RE = re.compile(
    r"capacity|kapasitas|area|luas|liner|leachate|lindi|tonnage|tonnes|waste|sampah|"
    r"methane|metana|closure|opening|cell|depth|height|volume",
    re.I,
)

# Conservative categories used to triage attachments into physical covariates.
# These only produce review candidates; they are never auto-applied to the
# master because attachment formats vary widely.
COVARIATE_CATEGORIES = {
    "capacity": re.compile(r"capacity|kapasitas", re.I),
    "area": re.compile(r"\barea\b|luas|hectare|hektar", re.I),
    "liner": re.compile(r"\bliner\b|geomembrane|hdpe|compacted clay|clay liner", re.I),
    "leachate": re.compile(r"leachate|lindi", re.I),
    "waste_tonnage": re.compile(
        r"(waste|msw|sampah).{0,40}(tonne|ton\b|ton/year|t/year)|"
        r"(tonne|ton\b|ton/year).{0,40}(waste|msw|sampah)",
        re.I,
    ),
    "gas_control": re.compile(r"methane|metana|landfill gas|\blfg\b|flare", re.I),
    "opening_closure": re.compile(
        r"opening|closure|closed|start.{0,10}operat|tahun.{0,10}operasi", re.I
    ),
    "depth_height": re.compile(r"depth|height|kedalaman|tinggi", re.I),
}


def covariate_categories(text: str) -> str:
    hits = [name for name, rx in COVARIATE_CATEGORIES.items() if rx.search(text or "")]
    return ";".join(hits)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def norm_text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def to_float(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def to_int(value):
    f = to_float(value)
    return int(f) if f is not None else None


def excel_cell(row: int, col: int) -> str:
    """0-based row/col -> A1 reference."""
    letters = ""
    c = col + 1
    while c:
        c, rem = divmod(c - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row + 1}"


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def detect_line_ending(path: Path) -> str:
    raw = path.read_bytes()
    return "\r\n" if raw.count(b"\r\n") > raw.count(b"\n") / 2 else "\n"


def read_sheets(path: Path) -> dict[str, pd.DataFrame]:
    info = sniff_file(path)
    if info["format"] == "xls":
        engine = "calamine"
    elif info["format"] == "xlsx":
        engine = "openpyxl"
    else:
        return {}
    book = pd.ExcelFile(path, engine=engine)
    return {
        name: pd.read_excel(path, sheet_name=name, header=None, engine=engine)
        for name in book.sheet_names
    }


def find_value(df: pd.DataFrame, patterns: list[str], max_right: int = 4):
    """Find the first label matching any pattern and return the next numeric/text value.

    Returns ``(value, sheet_cell, matched_label)``.  Searches all cells so it
    handles both label/value pairs (col A/B) and inline tables (col C/D).
    """
    for r in range(len(df)):
        for c in range(df.shape[1]):
            cell = df.iat[r, c]
            text = norm_text(cell)
            if not text:
                continue
            if any(p.lower() in text for p in patterns):
                for cc in range(c + 1, min(c + 1 + max_right, df.shape[1])):
                    val = df.iat[r, cc]
                    if pd.notna(val) and str(val).strip() != "":
                        return val, excel_cell(r, cc), str(cell).strip()
    return None, "", ""


# ---------------------------------------------------------------------------
# SIPSN facility inventory
# ---------------------------------------------------------------------------
def load_sipsn(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Data", engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    numeric = [
        "sampah_diterima_tahun",
        "jml_kelola_tahun",
        "sampah_olah_organik_tahun",
        "sampah_olah_anorganik_tahun",
        "recovery_pemulung_tahun",
        "lat",
        "lng",
        "luas",
        "luas_landfill_aktif",
        "jml_sumur_pantau",
        "jml_uji_lindi",
    ]
    for col in numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["nama_norm"] = df["nama"].map(norm_text)
    df["dati2_norm"] = df["nama_dati2"].map(norm_text)
    return df


def aggregate_facility(hit: pd.DataFrame, method: str, distance_km=None) -> dict:
    name = hit["nama"].mode().iloc[0] if not hit["nama"].mode().empty else ""
    ipal = hit["ada_ipal"].dropna().astype(str)
    ipal_state = (
        "Ada"
        if any(s.strip().lower().startswith("ada") for s in ipal)
        else ("Tidak" if len(ipal) else "")
    )
    methane = hit["pemanfaatan_methan_rev"].dropna().astype(str)
    methane_use = methane.mode().iloc[0] if not methane.mode().empty else ""
    lat = hit["lat"].mean() if hit["lat"].notna().any() else None
    lng = hit["lng"].mean() if hit["lng"].notna().any() else None
    return {
        "facility_name": name,
        "province": hit["nama_propinsi"].mode().iloc[0] if not hit["nama_propinsi"].mode().empty else "",
        "city": hit["nama_dati2"].mode().iloc[0] if not hit["nama_dati2"].mode().empty else "",
        "rows_aggregated": len(hit),
        "inflow_2025_t": hit["sampah_diterima_tahun"].sum(min_count=1),
        "managed_2025_t": hit["jml_kelola_tahun"].sum(min_count=1),
        "latitude": lat,
        "longitude": lng,
        "area_ha": hit["luas"].max() if hit["luas"].notna().any() else None,
        "active_area_m2": hit["luas_landfill_aktif"].max() if hit["luas_landfill_aktif"].notna().any() else None,
        "operational_system": hit["sistem_operasional"].mode().iloc[0]
        if not hit["sistem_operasional"].mode().empty
        else "",
        "leachate_plant": ipal_state,
        "leachate_tests": hit["jml_uji_lindi"].max() if hit["jml_uji_lindi"].notna().any() else None,
        "monitoring_wells": hit["jml_sumur_pantau"].max()
        if hit["jml_sumur_pantau"].notna().any()
        else None,
        "drainage": hit["ada_drainase"].mode().iloc[0] if not hit["ada_drainase"].mode().empty else "",
        "methane_use": methane_use,
        "cover_frequency_raw": hit["penutupan_sampah_zona_aktif"].mode().iloc[0]
        if not hit["penutupan_sampah_zona_aktif"].mode().empty
        else "",
        "weighbridge": hit["jembatan_timbang"].mode().iloc[0]
        if not hit["jembatan_timbang"].mode().empty
        else "",
        "opening_date_raw": hit["tgl_awal_operasi"].dropna().astype(str).iloc[0]
        if hit["tgl_awal_operasi"].notna().any()
        else "",
        "closure_date_raw": hit["tgl_akhir_operasi"].dropna().astype(str).iloc[0]
        if hit["tgl_akhir_operasi"].notna().any()
        else "",
        "match_method": method,
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "confidence": "high" if method.startswith("alias") else "medium",
    }


def match_sites(df: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, site in sites.iterrows():
        lid = site["landfill_id"]
        aliases = SITE_ALIASES.get(lid, [])
        hit = df.iloc[0:0]
        method = ""
        distance = None

        if aliases:
            mask = df["nama_norm"].apply(lambda n: any(a in n for a in aliases))
            # City names are only a fallback for aliases that name a city.
            city_mask = df["dati2_norm"].apply(lambda n: any(a in n for a in aliases))
            hit = df[mask] if mask.any() else df[city_mask]
            method = "alias_name" if mask.any() else ("alias_city" if city_mask.any() else "")
        if hit.empty and pd.notna(site.get("latitude")) and pd.notna(site.get("longitude")):
            try:
                slat, slon = float(site["latitude"]), float(site["longitude"])
            except (TypeError, ValueError):
                slat = slon = None
            if slat is not None:
                cand = df[df["lat"].notna() & df["lng"].notna()].copy()
                if not cand.empty:
                    cand["dist"] = cand.apply(
                        lambda r: haversine_km(slat, slon, r["lat"], r["lng"]), axis=1
                    )
                    nearest = cand.sort_values("dist").iloc[0]
                    if nearest["dist"] <= 15:
                        hit = df[df["nama_norm"] == nearest["nama_norm"]]
                        method = "nearest_coordinate"
                        distance = float(nearest["dist"])
        if hit.empty:
            continue
        rec = aggregate_facility(hit, method or "unknown", distance)
        rec["landfill_id"] = lid
        rows.append(rec)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# CDM "landfill details" workbooks (refs 1582, 2518, 2525)
# ---------------------------------------------------------------------------
# These workbooks share the same three-column-block layout:
#   * general information labels in A, values in B
#   * waste/composition labels in C, values in D
#   * historical disposal table: year in E, tonnes in G
# The sheet name differs ("Data Sheet Oct 06" vs "Data Collection Sheet") and
# the cumulative-waste label differs (single "since opening" total vs split
# historical/forecast totals), so both are handled explicitly.
DETAIL_SHEET_NAMES = ("Data Sheet Oct 06", "Data Collection Sheet")

COMPOSITION_LABELS = [
    ("wood", ["wood"]),
    ("paper", ["paper"]),
    ("food", ["organic (food", "organic"]),
    ("textile", ["textile"]),
    ("plastic", ["plastic"]),
    ("glass", ["glass"]),
    ("metal", ["metal"]),
    ("other", ["other"]),
]


def find_label_value(df: pd.DataFrame, patterns: list[str], label_col: int,
                     value_col: int, skip: tuple[str, ...] = ("-",)):
    """Return the value beside a label in a fixed column pair.

    ``find_value`` scans rightwards from any matching cell, which can pick up
    the *next block's* label (e.g. "Design Capacity" -> "Institutional: (%)").
    The landfill-details workbooks use stable label/value columns, so anchor
    the lookup to them.  Returns ``(value, cell, matched_label)``.
    """
    if label_col >= df.shape[1] or value_col >= df.shape[1]:
        return None, "", ""
    for r in range(len(df)):
        raw = df.iat[r, label_col]
        text = norm_text(raw)
        if not text or not any(p.lower() in text for p in patterns):
            continue
        val = df.iat[r, value_col]
        if pd.notna(val) and str(val).strip() not in {"", *skip}:
            return val, excel_cell(r, value_col), str(raw).strip()
    return None, "", ""


def detect_detail_sheet(sheets: dict[str, pd.DataFrame]) -> str | None:
    for name in DETAIL_SHEET_NAMES:
        if name in sheets:
            return name
    for name, df in sheets.items():
        if df.shape[0] and df.shape[1]:
            if "landfill data" in norm_text(df.iat[0, 0]):
                return name
    return None


def parse_landfill_details(path: Path) -> tuple[pd.DataFrame, dict]:
    sheets = read_sheets(path)
    sheet_name = detect_detail_sheet(sheets)
    if sheet_name is None:
        return pd.DataFrame(), {}
    ds = sheets[sheet_name]

    kv_rows = []
    extracted = {}

    def grab(patterns, name, label_col=0, value_col=1):
        val, cell, label = find_label_value(ds, patterns, label_col, value_col)
        if val is not None:
            extracted[name] = val
            kv_rows.append(
                {
                    "field": name,
                    "value": val,
                    "sheet": sheet_name,
                    "cell": cell,
                    "label": label,
                }
            )
        return val

    grab(["name of landfill"], "landfill_name")
    grab(["year landfill opened"], "opening_year")
    grab(["year landfill closed", "planned closure"], "closure_year")
    grab(["type of landfill"], "design_type_raw")
    grab(["design capacity"], "design_capacity_m3")
    grab(["total area of landfill"], "total_area_ha")
    grab(["total area for msw disposal"], "disposal_area_ha")
    grab(["number of cells"], "n_cells")
    grab(["area of each cell"], "cell_area_ha")
    grab(["number of closed cells"], "n_closed_cells")
    grab(["closed cells have capping soil"], "closed_cell_capping")
    grab(["height of cells above ground"], "height_above_m")
    grab(["depth of cells below ground"], "depth_below_m")
    grab(["current year"], "current_year")
    grab(["current volume of msw"], "current_volume_m3")
    grab(["volume of closed cells"], "closed_cells_volume_m3")
    grab(
        ["collection service of total msw generation"],
        "collection_service_fraction",
        label_col=2,
        value_col=3,
    )
    grab(["distance from the city centre", "distance from the city center"],
         "distance_city_km")

    # Cumulative waste: some workbooks record one "since opening" total while
    # others split it into historical + forecast periods.  Sum only the tonne
    # rows (never the cubic-metre rows) and keep each component for audit.
    tonnes_total = 0.0
    m3_total = 0.0
    n_tonnes = 0
    n_m3 = 0
    for r in range(len(ds)):
        if ds.shape[1] <= 3:
            break
        label = norm_text(ds.iat[r, 2])
        if "total msw disposed" not in label:
            continue
        val = to_float(ds.iat[r, 3])
        if val is None:
            continue
        kv_rows.append(
            {
                "field": "total_disposed_component",
                "value": val,
                "sheet": sheet_name,
                "cell": excel_cell(r, 3),
                "label": str(ds.iat[r, 2]).strip(),
            }
        )
        if "tonne" in label or "(ton" in label:
            tonnes_total += val
            n_tonnes += 1
        elif "cubic" in label or "m3" in label:
            m3_total += val
            n_m3 += 1
    if n_tonnes:
        extracted["total_disposed_t"] = round(tonnes_total, 2)
    if n_m3:
        extracted["total_disposed_m3"] = round(m3_total, 2)

    # Composition (col C labels, col D values).  Some workbooks store
    # percentages and others fractions; decide from the set total (≈1 vs ≈100)
    # so a genuine 1% value is not mistaken for 100%.
    raw_comp = {}
    for key, patterns in COMPOSITION_LABELS:
        val, cell, label = find_label_value(ds, patterns, 2, 3)
        v = to_float(val)
        if v is not None:
            raw_comp[key] = (v, cell, label)
    composition = {}
    if raw_comp:
        scale = 100.0 if sum(v for v, _, _ in raw_comp.values()) > 1.5 else 1.0
        for key, (v, cell, label) in raw_comp.items():
            composition[key] = round(v / scale, 6)
            kv_rows.append(
                {
                    "field": f"composition_{key}",
                    "value": composition[key],
                    "sheet": sheet_name,
                    "cell": cell,
                    "label": label,
                }
            )
    extracted["composition"] = composition

    # Historical disposal table: year in col E, tonnes in col G.
    disposal = []
    for r in range(len(ds)):
        year = to_int(ds.iat[r, 4]) if ds.shape[1] > 4 else None
        tonnes = to_float(ds.iat[r, 6]) if ds.shape[1] > 6 else None
        if year and 1980 <= year <= 2050 and tonnes is not None:
            disposal.append(
                {
                    "field": "disposal_year_tonnes",
                    "value": tonnes,
                    "sheet": sheet_name,
                    "cell": excel_cell(r, 6),
                    "label": str(year),
                }
            )
    kv_rows.extend(disposal)
    extracted["disposal"] = disposal
    if disposal:
        years = [int(float(d["label"])) for d in disposal]
        positive = [
            int(float(d["label"])) for d in disposal
            if (to_float(d["value"]) or 0) > 0
        ]
        extracted["disposal_table_end_year"] = max(years)
        if positive:
            extracted["disposal_last_year"] = max(positive)

    # Infer how far the workbook's cumulative total actually reaches by walking
    # the disposal table until the running sum matches the stated total.
    stated_total = to_float(extracted.get("total_disposed_t"))
    if stated_total and disposal:
        running = 0.0
        tolerance = max(1.0, stated_total * 0.005)
        for year, tonnes in sorted(
            (int(float(d["label"])), to_float(d["value"])) for d in disposal
        ):
            running += tonnes
            if abs(running - stated_total) <= tolerance:
                extracted["total_disposed_horizon"] = year
                break

    # Capture efficiency (assumed) from any sheet; accept only plausible
    # fractions so header cells or zero-filled rows are not mistaken for it.
    for name, df in sheets.items():
        found = False
        for r in range(len(df)):
            for c in range(df.shape[1]):
                if "capture efficiency" not in norm_text(df.iat[r, c]):
                    continue
                for cc in range(c + 1, min(c + 4, df.shape[1])):
                    val = to_float(df.iat[r, cc])
                    if val is not None and 0 < val <= 1:
                        extracted["capture_efficiency"] = val
                        extracted["capture_efficiency_sheet"] = name
                        kv_rows.append(
                            {
                                "field": "capture_efficiency",
                                "value": val,
                                "sheet": name,
                                "cell": excel_cell(r, cc),
                                "label": str(df.iat[r, c]).strip(),
                            }
                        )
                        found = True
                        break
                if found:
                    break
            if found:
                break
        if found:
            break

    extracted["_sheet"] = sheet_name
    return pd.DataFrame(kv_rows), extracted


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------
def add_proposal(store, sites, lid, column, proposed, source_name, file_path,
                 sheet, cell, evidence, confidence="medium", apply=False,
                 status="approved", unit="", value_format="", notes=""):
    row = sites.loc[sites["landfill_id"] == lid]
    current = row.iloc[0][column] if not row.empty and column in sites.columns else ""
    store.append(
        {
            "landfill_id": lid,
            "target_table": "sites",
            "target_column": column,
            "current_value": str(current),
            "proposed_value": str(proposed),
            "value_format": value_format,
            "unit": unit,
            "source_name": source_name,
            "file_path": str(file_path),
            "sheet": sheet,
            "cell": cell,
            "evidence": evidence,
            "confidence": confidence,
            "apply": bool(apply),
            "status": status,
            "notes": notes,
        }
    )


def build_sipsn_proposals(matches: pd.DataFrame, sites: pd.DataFrame, store: list) -> None:
    for _, m in matches.iterrows():
        lid = m["landfill_id"]
        row = sites[sites["landfill_id"] == lid].iloc[0]
        src = "SIPSN TPA/TPST 2025"
        row_lat = to_float(row["latitude"])
        row_lon = to_float(row["longitude"])
        src_lat = to_float(m["latitude"])
        src_lon = to_float(m["longitude"])
        coord_distance = (
            haversine_km(row_lat, row_lon, src_lat, src_lon)
            if None not in (row_lat, row_lon, src_lat, src_lon)
            else None
        )

        # Coordinates: fill when blank, flag only large discrepancies (>25 km).
        if not str(row["latitude"]).strip() and pd.notna(m["latitude"]):
            add_proposal(
                store, sites, lid, "latitude", round(float(m["latitude"]), 6), src,
                SIPSN, "Data", f"row {m['rows_aggregated']} aggregated", "facility GPS",
                "high", True, "approved", "degrees", "decimal_degrees",
            )
        if not str(row["longitude"]).strip() and pd.notna(m["longitude"]):
            add_proposal(
                store, sites, lid, "longitude", round(float(m["longitude"]), 6), src,
                SIPSN, "Data", f"row {m['rows_aggregated']} aggregated", "facility GPS",
                "high", True, "approved", "degrees", "decimal_degrees",
            )
        if coord_distance is not None and coord_distance > 25:
            note = (
                f"Master ({row_lat}, {row_lon}) is {coord_distance:.0f} km from the "
                f"SIPSN facility ({src_lat}, {src_lon}); not overwritten."
            )
            for col, val in (("latitude", round(src_lat, 6)), ("longitude", round(src_lon, 6))):
                add_proposal(
                    store, sites, lid, col, val, src, SIPSN, "Data",
                    f"rows aggregated={m['rows_aggregated']}", "facility GPS",
                    "high", False, "conflict", "degrees", "decimal_degrees", note,
                )

        # Annual inflow: fill when blank; flag material disagreements rather
        # than overwriting a PDD-derived value.
        current_inflow = to_float(row["annual_waste_inflow_tonnes"])
        src_inflow = to_float(m["inflow_2025_t"])
        if not str(row["annual_waste_inflow_tonnes"]).strip() and src_inflow is not None:
            add_proposal(
                store, sites, lid, "annual_waste_inflow_tonnes",
                round(src_inflow, 2), src, SIPSN, "Data",
                f"rows aggregated={m['rows_aggregated']}",
                f"sampah_diterima_tahun sum for {m['facility_name']}",
                "high", True, "approved", "tonnes/year", "numeric",
                "companion: annual_inflow_year=2025; annual_inflow_basis=sipsn_2025",
            )
        elif current_inflow and src_inflow:
            denom = max(abs(current_inflow), abs(src_inflow))
            if denom and abs(current_inflow - src_inflow) / denom > 0.05:
                add_proposal(
                    store, sites, lid, "annual_waste_inflow_tonnes",
                    round(src_inflow, 2), src, SIPSN, "Data",
                    f"rows aggregated={m['rows_aggregated']}",
                    f"sampah_diterima_tahun sum for {m['facility_name']}",
                    "medium", False, "conflict", "tonnes/year", "numeric",
                    f"Master has {row['annual_waste_inflow_tonnes']} "
                    f"({row['annual_inflow_year'] or 'year unknown'}, "
                    f"{row['annual_inflow_basis'] or 'basis unknown'}); "
                    "SIPSN reports 2025 receipts. Not overwritten.",
                )

        # Design type: fill when blank; flag disagreements.  Ref 1582 already
        # has a site-specific workbook conflict, so skip the duplicate here.
        mapped = DESIGN_MAP.get(norm_text(m["operational_system"]))
        if not str(row["design_type"]).strip() and mapped:
            add_proposal(
                store, sites, lid, "design_type", mapped, src, SIPSN, "Data",
                "sistem_operasional", f"operational system={m['operational_system']}",
                "high", True, "approved", "", "token",
            )
        elif (
            lid != "cdm_1582"
            and mapped
            and str(row["design_type"]).strip()
            and mapped != str(row["design_type"]).strip()
        ):
            add_proposal(
                store, sites, lid, "design_type", mapped, src, SIPSN, "Data",
                "sistem_operasional", f"operational system={m['operational_system']}",
                "medium", False, "conflict", "", "token",
                f"Master has {row['design_type']}; SIPSN describes "
                f"'{m['operational_system']}'. Not overwritten.",
            )

        # Leachate treatment: only when blank and IPAL exists.
        if not str(row["leachate_system"]).strip() and m["leachate_plant"] == "Ada":
            add_proposal(
                store, sites, lid, "leachate_system", "treatment", src, SIPSN, "Data",
                "ada_ipal", "IPAL present at facility",
                "medium", True, "approved", "", "token_list",
            )

        # Gas control: only when blank and the source is explicit.
        if not str(row["gas_control_presence"]).strip():
            use = norm_text(m["methane_use"])
            mapping = {
                "tidak ada gas metana dibakar": "flare",
                "tidak ada melepas gas metana ke udara": "passive_venting",
                "untuk energi listrik": "active_extraction+power_generation",
            }
            if use in mapping:
                add_proposal(
                    store, sites, lid, "gas_control_presence", mapping[use], src,
                    SIPSN, "Data", "pemanfaatan_methan_rev", m["methane_use"],
                    "medium", True, "approved", "", "token_list",
                )


def compositions_differ(current_json: str, proposed: dict) -> bool:
    """True when an existing composition JSON differs materially from proposed."""
    try:
        current = json.loads(current_json) if str(current_json).strip() else {}
    except (TypeError, ValueError):
        return True
    if not current:
        return True
    keys = set(current) | set(proposed)
    for key in keys:
        a = to_float(current.get(key))
        b = to_float(proposed.get(key))
        if a is None or b is None:
            if a != b:
                return True
        elif abs(a - b) > 0.001:
            return True
    return False


def build_landfill_detail_proposals(lid: str, path: Path, extracted: dict,
                                    sites: pd.DataFrame, store: list) -> None:
    """Propose master updates from a CDM "landfill details" workbook.

    Only columns that exist in ``sites.csv`` are proposed.  Physical covariates
    such as area, cell count and depth are written to the interim extraction
    table instead, because the master schema has no column for them.
    """
    row = sites[sites["landfill_id"] == lid].iloc[0]
    ref = lid.replace("cdm_", "")
    src = f"CDM ref {ref} Appendix 2 (landfill details workbook)"
    sheet = extracted.get("_sheet", "")
    p = Path(path)

    opening = to_int(extracted.get("opening_year"))
    current_opening = to_int(row["opening_year"])
    if opening:
        if not current_opening:
            add_proposal(
                store, sites, lid, "opening_year", opening, src, p, sheet, "",
                "Year Landfill opened", "medium", True, "approved", "year", "integer",
            )
        elif opening != current_opening:
            add_proposal(
                store, sites, lid, "opening_year", opening, src, p, sheet, "",
                "Year Landfill opened", "medium", False, "conflict", "year", "integer",
                f"Master has {current_opening}; workbook says {opening}. Not overwritten.",
            )

    closure = to_int(extracted.get("closure_year"))
    current_closure = to_int(row["closure_year"])
    if closure:
        if not current_closure:
            add_proposal(
                store, sites, lid, "closure_year", closure, src, p, sheet, "",
                "Year Landfill closed or Planned closure",
                "medium", True, "approved", "year", "integer",
                "Planned closure recorded in the workbook.",
            )
        elif closure != current_closure:
            add_proposal(
                store, sites, lid, "closure_year", closure, src, p, sheet, "",
                "Year Landfill closed or Planned closure",
                "medium", False, "conflict", "year", "integer",
                f"Master has {current_closure}; workbook says {closure}. Not overwritten.",
            )

    dtype = DESIGN_MAP.get(norm_text(extracted.get("design_type_raw")))
    current_dtype = str(row["design_type"]).strip()
    if dtype:
        if not current_dtype:
            add_proposal(
                store, sites, lid, "design_type", dtype, src, p, sheet, "",
                f"Type of Landfill={extracted['design_type_raw']}",
                "medium", True, "approved", "", "token",
            )
        elif dtype != current_dtype:
            add_proposal(
                store, sites, lid, "design_type", dtype, src, p, sheet, "",
                f"Type of Landfill={extracted['design_type_raw']}",
                "medium", False, "conflict", "", "token",
                f"Master has {current_dtype}; workbook describes it as "
                f"{extracted['design_type_raw']}. Not overwritten.",
            )

    composition = extracted.get("composition") or {}
    if composition:
        proposed_json = json.dumps(dict(sorted(composition.items())))
        current_comp = str(row["waste_composition_fractions"]).strip()
        if not current_comp:
            add_proposal(
                store, sites, lid, "waste_composition_fractions", proposed_json,
                src, p, sheet, "", "MSW Composition percentages (normalised to fractions)",
                "medium", True, "approved", "fraction", "json",
            )
        elif compositions_differ(current_comp, composition):
            add_proposal(
                store, sites, lid, "waste_composition_fractions", proposed_json,
                src, p, sheet, "", "MSW Composition percentages (normalised to fractions)",
                "medium", False, "conflict", "fraction", "json",
                f"Master composition differs from the workbook. Not overwritten.",
            )

    ce = to_float(extracted.get("capture_efficiency"))
    if ce is not None and not str(row["collection_efficiency"]).strip():
        add_proposal(
            store, sites, lid, "collection_efficiency", ce, src, p,
            extracted.get("capture_efficiency_sheet", sheet), "",
            "Capture efficiency next to methane captured",
            "medium", True, "approved", "fraction", "fraction",
            "companion: ce_basis=assumed; ex-ante model value, not measured",
        )

    total = to_float(extracted.get("total_disposed_t"))
    if total and not str(row["waste_tonnes_cumulative"]).strip():
        horizon = extracted.get("total_disposed_horizon")
        if horizon:
            end = extracted.get("disposal_table_end_year")
            extra = (
                f" (disposal table runs to {int(float(end))})"
                if end and int(float(end)) > int(float(horizon))
                else ""
            )
            note = (
                f"Workbook total through {int(float(horizon))}{extra}; not a "
                "current measured cumulative value."
            )
        else:
            note = (
                "Historical workbook total; not a current measured cumulative "
                "value."
            )
        add_proposal(
            store, sites, lid, "waste_tonnes_cumulative", round(total, 2), src,
            p, sheet, "", "Total MSW disposed since opening (tonne)",
            "medium", False, "hold", "tonnes", "numeric", note,
        )


def discover_landfill_details() -> dict[str, tuple[Path, str]]:
    """Locate every catalogued CDM "landfill details" workbook.

    Returns ``{landfill_id: (path, catalogue_label)}``.  Paths in the
    catalogue are relative to ``data/``; absolute paths are left untouched.
    """
    found: dict[str, tuple[Path, str]] = {}
    if not CATALOGUE.exists():
        return found
    cat = pd.read_csv(CATALOGUE, dtype=str, keep_default_na=False)
    for _, row in cat.iterrows():
        label = str(row.get("label", ""))
        haystack = norm_text(f"{label} {row.get('file_path', '')}")
        if "landfill detail" not in haystack:
            continue
        lid = str(row.get("landfill_id", "")).strip() or f"cdm_{row.get('ref', '')}"
        if lid in found:
            continue
        raw = Path(str(row.get("file_path", "")))
        path = raw if raw.is_absolute() else DATA / raw
        if path.exists():
            found[lid] = (path, label)
    return found


# ---------------------------------------------------------------------------
# Attachment triage
# ---------------------------------------------------------------------------
def triage_attachments(scan_pdfs: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, candidates = [], []
    if not ATT_DIR.exists():
        return pd.DataFrame(rows), pd.DataFrame(candidates)

    ref_map = {}
    if CATALOGUE.exists():
        cat = pd.read_csv(CATALOGUE, dtype=str, keep_default_na=False)
        ref_map = dict(zip(cat["ref"].astype(str), cat["landfill_id"]))

    for path in sorted(ATT_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() in {".part", ".download"}:
            continue
        ref = path.parent.name
        landfill_id = ref_map.get(str(ref), f"cdm_{ref}")
        info = sniff_file(path)
        row = {
            "ref": ref,
            "landfill_id": landfill_id,
            "file": str(path),
            "format": info["format"],
            "extension": info["extension"],
            "bytes": info["size"],
            "sha256": sha256_file(path),
            "sheets": "",
            "rows": "",
            "cols": "",
            "covariate_categories": "",
            "status": "triaged",
            "notes": "",
        }

        tabular_paths: list[tuple[Path, str]] = []
        if info["format"] in {"xls", "xlsx"}:
            tabular_paths.append((path, ""))
        elif info["format"] == "zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    members = [m for m in zf.namelist() if m.lower().endswith((".xls", ".xlsx"))]
                    if members:
                        dest = OUT / "attachments_parsed" / ref / path.stem
                        dest.mkdir(parents=True, exist_ok=True)
                        for m in members:
                            zf.extract(m, dest)
                            tabular_paths.append((dest / m, m))
                        row["notes"] = f"zip members: {len(members)}"
            except Exception as exc:
                row["status"] = "zip_error"
                row["notes"] = str(exc)[:200]

        sheet_names = []
        file_categories: set[str] = set()
        for tab_path, member in tabular_paths:
            try:
                sheets = read_sheets(tab_path)
            except Exception as exc:
                row["notes"] = (row["notes"] + f" | read error {exc}")[:250]
                continue
            for name, df in sheets.items():
                sheet_names.append(f"{member}:{name}" if member else name)
                dest_dir = OUT / "attachments_parsed" / ref / path.stem
                dest_dir.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r"[^0-9A-Za-z]+", "_", f"{member}_{name}").strip("_")[:90]
                df.head(20_000).to_csv(dest_dir / f"{safe}.csv", index=False, header=False)
                for r in range(min(len(df), 400)):
                    vals = [str(v).strip() for v in df.iloc[r].tolist() if pd.notna(v)]
                    if not vals:
                        continue
                    joined = " | ".join(vals)
                    if KEYWORD_RE.search(joined):
                        cats = covariate_categories(joined)
                        file_categories.update(c for c in cats.split(";") if c)
                        candidates.append(
                            {
                                "landfill_id": landfill_id,
                                "ref": ref,
                                "file": str(path),
                                "format": info["format"],
                                "sheet": name,
                                "row": r + 1,
                                "categories": cats,
                                "cells": joined[:500],
                                "sha256": row["sha256"],
                            }
                        )
            row["rows"] = max(
                [int(row["rows"] or 0)] + [len(df) for df in sheets.values()]
            )
            row["cols"] = max(
                [int(row["cols"] or 0)] + [df.shape[1] for df in sheets.values()]
            )
        row["sheets"] = ";".join(sheet_names)[:500]
        row["covariate_categories"] = ";".join(sorted(file_categories))

        if info["format"] == "pdf" and scan_pdfs:
            try:
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(str(path))
                text = []
                for page in range(min(len(pdf), 3)):
                    text.append(pdf[page].get_textpage().get_text_range())
                blob = "\n".join(text)
                if KEYWORD_RE.search(blob):
                    cats = covariate_categories(blob)
                    file_categories.update(c for c in cats.split(";") if c)
                    candidates.append(
                        {
                            "landfill_id": landfill_id,
                            "ref": ref,
                            "file": str(path),
                            "format": "pdf",
                            "sheet": f"pdf p1-{min(len(pdf), 3)}",
                            "row": "",
                            "categories": cats,
                            "cells": KEYWORD_RE.sub(
                                lambda m: m.group(0), blob[:800]
                            ),
                            "sha256": row["sha256"],
                        }
                    )
            except Exception as exc:
                row["notes"] = (row["notes"] + f" | pdf error {exc}")[:250]

        rows.append(row)
    return pd.DataFrame(rows), pd.DataFrame(candidates)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def validate(column: str, value: str) -> tuple[bool, str]:
    if column in {"latitude", "longitude"}:
        v = to_float(value)
        if v is None:
            return False, "not numeric"
        if column == "latitude" and not (-90 <= v <= 90):
            return False, "latitude out of range"
        if column == "longitude" and not (-180 <= v <= 180):
            return False, "longitude out of range"
    elif column in {"annual_waste_inflow_tonnes", "waste_tonnes_cumulative"}:
        v = to_float(value)
        if v is None or v <= 0:
            return False, "not a positive number"
    elif column == "design_type":
        if value not in ALLOWED_DESIGN:
            return False, "not in design vocabulary"
    elif column == "leachate_system":
        tokens = set(str(value).split("+"))
        if not tokens <= LEACHATE_TOKENS:
            return False, "token outside leachate vocabulary"
    elif column == "gas_control_presence":
        tokens = set(str(value).split("+"))
        if not tokens <= GAS_TOKENS:
            return False, "token outside gas vocabulary"
    elif column == "collection_efficiency":
        v = to_float(value)
        if v is None or not (0 <= v <= 1):
            return False, "fraction outside 0-1"
    elif column == "closure_year":
        v = to_int(value)
        if v is None or not (1900 <= v <= 2100):
            return False, "year out of range"
    return True, "ok"


def apply_proposals(proposals: pd.DataFrame, sites: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    backup = INTERIM / "sites_backup_before_excel_ingest.csv"
    if not backup.exists():
        shutil.copy2(SITES, backup)
    diff = []
    eol = detect_line_ending(SITES)

    for _, p in proposals.iterrows():
        if p["status"] != "approved" or str(p["apply"]).lower() not in {"true", "1"}:
            continue
        lid, col = p["landfill_id"], p["target_column"]
        idx = sites.index[sites["landfill_id"] == lid]
        if len(idx) == 0:
            continue
        i = idx[0]
        if str(sites.at[i, col]).strip():
            continue
        ok, reason = validate(col, p["proposed_value"])
        if not ok:
            proposals.loc[p.name, "status"] = "invalid"
            proposals.loc[p.name, "notes"] = (str(p["notes"]) + f" | {reason}").strip(" |")
            continue

        old = sites.at[i, col]
        sites.at[i, col] = p["proposed_value"]
        diff.append(
            {
                "landfill_id": lid,
                "column": col,
                "old_value": old,
                "new_value": p["proposed_value"],
                "source": p["source_name"],
                "evidence": p["evidence"],
            }
        )

        # Companion fields that define the semantics of the new value.
        if col == "annual_waste_inflow_tonnes":
            if "annual_inflow_year" in sites.columns:
                sites.at[i, "annual_inflow_year"] = "2025"
            if "annual_inflow_basis" in sites.columns:
                sites.at[i, "annual_inflow_basis"] = "sipsn_2025"
        if col == "collection_efficiency" and "ce_basis" in sites.columns:
            sites.at[i, "ce_basis"] = "assumed"

    sites.to_csv(SITES, index=False, lineterminator=eol)
    diff_cols = ["landfill_id", "column", "old_value", "new_value", "source", "evidence"]
    diff_df = pd.DataFrame(diff, columns=diff_cols)
    # Keep the last non-empty diff as an audit artefact; an idempotent re-run
    # (0 changes) must not erase the record of what was applied earlier.
    if not diff_df.empty or not DIFF.exists():
        diff_df.to_csv(DIFF, index=False, lineterminator="\n")
    return proposals, diff_df


def append_actual_values(diff: pd.DataFrame, proposals: pd.DataFrame) -> None:
    if diff.empty:
        return
    cols = [
        "landfill_id", "target_table", "target_column", "proposed_value",
        "value_format", "current_value", "source_field", "source_value_raw",
        "evidence_filename", "evidence_page", "evidence_snippet", "confidence",
        "verification_status", "integration_action", "companion_updates", "notes",
    ]
    rows = []
    for _, d in diff.iterrows():
        p = proposals[
            (proposals["landfill_id"] == d["landfill_id"])
            & (proposals["target_column"] == d["column"])
            & (proposals["proposed_value"] == d["new_value"])
        ]
        p = p.iloc[0] if not p.empty else None
        companions = ""
        if d["column"] == "annual_waste_inflow_tonnes":
            companions = json.dumps(
                {"annual_inflow_year": "2025", "annual_inflow_basis": "sipsn_2025"}
            )
        elif d["column"] == "collection_efficiency":
            companions = json.dumps({"ce_basis": "assumed"})
        rows.append(
            {
                "landfill_id": d["landfill_id"],
                "target_table": "sites",
                "target_column": d["column"],
                "proposed_value": d["new_value"],
                "value_format": p["value_format"] if p is not None else "",
                "current_value": d["old_value"],
                "source_field": p["evidence"] if p is not None else d["evidence"],
                "source_value_raw": p["proposed_value"] if p is not None else d["new_value"],
                "evidence_filename": p["file_path"] if p is not None else "",
                "evidence_page": p["sheet"] if p is not None else "",
                "evidence_snippet": p["evidence"] if p is not None else d["evidence"],
                "confidence": p["confidence"] if p is not None else "medium",
                "verification_status": "verified_manual",
                "integration_action": "applied",
                "companion_updates": companions,
                "notes": p["notes"] if p is not None else "",
            }
        )
    new = pd.DataFrame(rows, columns=cols)
    if ACTUAL.exists():
        old = pd.read_csv(ACTUAL, dtype=str, keep_default_na=False)
        new = pd.concat([old, new], ignore_index=True)
        new = new.drop_duplicates(
            subset=["landfill_id", "target_column", "proposed_value"], keep="last"
        )
    new.to_csv(ACTUAL, index=False, lineterminator="\n")


def update_manifest(parsed_fields: dict) -> None:
    if not MANIFEST.exists():
        return
    df = pd.read_csv(MANIFEST, dtype=str, keep_default_na=False)
    for col in ["parse_status", "parsed_fields", "parsed_at"]:
        if col not in df.columns:
            df[col] = ""
    for i, row in df.iterrows():
        if row.get("upload_id") in parsed_fields:
            df.at[i, "parse_status"] = "parsed"
            df.at[i, "parsed_fields"] = parsed_fields[row["upload_id"]]
            df.at[i, "parsed_at"] = now()
    df.to_csv(MANIFEST, index=False, lineterminator="\n")


def write_report(triage: pd.DataFrame, matches: pd.DataFrame, proposals: pd.DataFrame,
                 diff: pd.DataFrame, extracted: dict,
                 candidates: pd.DataFrame | None = None) -> None:
    applied = proposals[
        (proposals["status"] == "approved")
        & (proposals["apply"].astype(str).str.lower().isin({"true", "1"}))
    ]  # noqa: E712
    conflicts = proposals[proposals["status"] == "conflict"]
    holds = proposals[proposals["status"] == "hold"]
    applied_cells = None
    if ACTUAL.exists():
        hist = pd.read_csv(ACTUAL, dtype=str, keep_default_na=False)
        applied_cells = int(
            (hist.get("integration_action", pd.Series(dtype=str)) == "applied").sum()
        )
    lines = [
        "# Excel / Manual Source Ingest Report",
        "",
        f"Generated: {now()}",
        "",
        "## Sources",
        "",
        "- CDM landfill-details workbooks:",
    ]
    for lid, info in (extracted or {}).items():
        lines.append(f"  - `{lid}`: `{info.get('_path', '')}`")
    lines += [
        f"- SIPSN facility inventory: `{SIPSN.relative_to(Path.cwd())}`",
        f"- Downloaded attachment directory: `{ATT_DIR.relative_to(Path.cwd())}`",
        "",
        "## Triage",
        "",
        f"- Files triaged: **{len(triage)}**",
    ]
    if not triage.empty:
        for fmt, n in triage["format"].value_counts().items():
            lines.append(f"  - `{fmt}`: {n}")
    lines += [
        "",
        "## Site matching (Indonesia)",
        "",
        f"- Master sites matched to a SIPSN facility: **{len(matches)} / 8**",
    ]
    if not matches.empty:
        for _, m in matches.iterrows():
            lines.append(
                f"  - `{m['landfill_id']}` -> {m['facility_name']} "
                f"({m['match_method']}, {m['rows_aggregated']} row(s), inflow={m['inflow_2025_t']})"
            )
    if candidates is not None and not candidates.empty:
        cat_counts: dict[str, int] = {}
        for value in candidates["categories"].fillna(""):
            for cat in str(value).split(";"):
                if cat:
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
        lines += [
            "",
            "## Attachment covariate candidates",
            "",
            f"- Flagged rows: **{len(candidates)}** across **{candidates['ref'].nunique()}** projects",
            f"- Files with tabular candidates: **{len(triage[triage['status'] == 'triaged'])}**",
            "",
            "| Category | Rows |",
            "|---|---|",
        ]
        for cat, n in sorted(cat_counts.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"| {cat} | {n} |")
        lines.append("")
        lines.append(
            "Candidates are review-only: attachment layouts vary too much to auto-apply. "
            "See `data/interim/excel_sources/attachment_candidate_values.csv`."
        )
    lines += [
        "",
        "## Reviewed attachment sources (not promoted)",
        "",
        "- `cdm_4077` (Batam): the investment-analysis workbooks report landfill area "
        "12 ha and average depth 12.5 m (`capex opex`), but the master has no "
        "area/depth columns. Recorded here for a future schema decision; no update applied.",
        "- `cdm_4566` (bundled): baseline/ER workbooks span several facilities, and the "
        "quoted 7 m/15 m depths are LFG well depths, not landfill depth. No per-site "
        "mapping, so no update applied.",
    ]
    lines += [
        "",
        "## Proposals",
        "",
        f"- Approved & applied: **{len(applied)}** values"
        + (f" ({applied_cells} cells incl. companions)" if applied_cells else ""),
        f"- Conflicts (not applied): **{len(conflicts)}**",
        f"- Held for review: **{len(holds)}**",
        "",
    ]
    if not diff.empty:
        lines.append("### Applied in the most recent run")
        lines.append("")
        lines.append("| Site | Column | Old | New | Source |")
        lines.append("|---|---|---|---|---|")
        for _, d in diff.iterrows():
            lines.append(
                f"| {d['landfill_id']} | {d['column']} | `{d['old_value']}` | "
                f"`{d['new_value']}` | {d['source']} |"
            )
        lines.append("")
        if applied_cells:
            lines.append(
                f"Full applied history: `{ACTUAL.relative_to(Path.cwd())}` "
                f"({applied_cells} cells, all `integration_action=applied`)."
            )
            lines.append("")
    if not conflicts.empty:
        lines.append("### Conflicts / holds")
        lines.append("")
        for _, p in pd.concat([conflicts, holds]).iterrows():
            lines.append(
                f"- `{p['landfill_id']}` `{p['target_column']}`: proposed "
                f"`{p['proposed_value']}` vs master `{p['current_value']}` — {p['notes']}"
            )
    lines += [
        "",
        "## CDM landfill-details workbook extracts",
        "",
    ]
    for lid, info in (extracted or {}).items():
        lines.append(f"### `{lid}` — sheet `{info.get('_sheet', '')}`")
        lines.append("")
        for key in [
            "landfill_name", "opening_year", "closure_year", "design_type_raw",
            "design_capacity_m3", "total_area_ha", "disposal_area_ha", "n_cells",
            "n_closed_cells", "closed_cell_capping", "height_above_m",
            "depth_below_m", "current_volume_m3", "distance_city_km",
            "collection_service_fraction", "total_disposed_t",
            "total_disposed_m3", "disposal_last_year",
            "disposal_table_end_year", "total_disposed_horizon",
            "capture_efficiency",
        ]:
            if key in info:
                lines.append(f"- `{key}`: {info[key]}")
        if info.get("composition"):
            comp = ", ".join(
                f"{k}={v}" for k, v in sorted(info["composition"].items())
            )
            lines.append(f"- `composition`: {comp}")
        lines.append("")
    lines += [
        "",
        "## Files",
        "",
        f"- Proposals: `{PROPOSALS.relative_to(Path.cwd())}`",
        f"- Diff: `{DIFF.relative_to(Path.cwd())}`",
        f"- Site covariates: `{SITE_COVARIATES.relative_to(Path.cwd())}`",
        f"- Facility covariates: `{FACILITY_COVARIATES.relative_to(Path.cwd())}`",
        f"- Triage: `{TRIAGE.relative_to(Path.cwd())}`",
    ]
    REPORT.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write approved null-fills to sites.csv")
    ap.add_argument("--skip-attachments", action="store_true")
    ap.add_argument("--scan-pdfs", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    IND.mkdir(parents=True, exist_ok=True)

    sites = pd.read_csv(SITES, dtype=str, keep_default_na=False)
    sites_eol = detect_line_ending(SITES)
    print(f"sites: {len(sites)} rows, {len(sites.columns)} cols (EOL={'CRLF' if sites_eol == chr(13)+chr(10) else 'LF'})")

    # --- SIPSN -------------------------------------------------------------
    matches = pd.DataFrame()
    proposals: list[dict] = []
    sipsn = load_sipsn(SIPSN)
    print(f"SIPSN facilities: {len(sipsn)} rows")
    idn = sites[sites["country"] == "Indonesia"].copy()
    matches = match_sites(sipsn, idn)
    matches.to_csv(MATCHES, index=False, lineterminator="\n")
    print(f"matched master sites: {len(matches)}/{len(idn)}")
    if not matches.empty:
        print(matches[["landfill_id", "facility_name", "rows_aggregated",
                       "inflow_2025_t", "match_method", "confidence"]].to_string(index=False))

    # Facility-level covariate table (all 397 rows, not just matched sites).
    fac_cols = [
        "nama_propinsi", "nama_dati2", "nama", "jenis", "sistem_operasional",
        "sampah_diterima_tahun", "jml_kelola_tahun", "sampah_olah_organik_tahun",
        "sampah_olah_anorganik_tahun", "recovery_pemulung_tahun", "lat", "lng",
        "luas", "luas_landfill_aktif", "tgl_awal_operasi", "tgl_akhir_operasi",
        "jembatan_timbang", "penutupan_sampah_zona_aktif", "jml_sumur_pantau",
        "ada_ipal", "jml_uji_lindi", "ada_drainase", "pemanfaatan_methan_rev",
        "jml_kk_manfaat_methan",
    ]
    sipsn[[c for c in fac_cols if c in sipsn.columns]].to_csv(
        FACILITY_COVARIATES, index=False, lineterminator="\n"
    )
    if not matches.empty:
        matches.to_csv(SITE_COVARIATES, index=False, lineterminator="\n")

    build_sipsn_proposals(matches, sites, proposals)

    # --- CDM landfill-details workbooks -----------------------------------
    detail_frames = []
    extractions = {}
    for lid, (path, _label) in discover_landfill_details().items():
        kv, extracted = parse_landfill_details(path)
        if kv.empty:
            print(f"landfill details: {lid} not parsed ({path.name})")
            continue
        kv.insert(0, "landfill_id", lid)
        kv.insert(1, "ref", lid.replace("cdm_", ""))
        kv.insert(2, "file", str(path))
        detail_frames.append(kv)
        extracted["_path"] = str(path)
        extractions[lid] = extracted
        if lid == "cdm_1582":
            kv.drop(columns=["landfill_id", "ref", "file"]).to_csv(
                PONTIANAK_KV, index=False, lineterminator="\n"
            )
        build_landfill_detail_proposals(lid, path, extracted, sites, proposals)
        print(
            f"landfill details: {lid} parsed {len(kv)} fields "
            f"({extracted.get('_sheet', '')})"
        )
    if detail_frames:
        pd.concat(detail_frames, ignore_index=True).to_csv(
            LANDFILL_DETAILS, index=False, lineterminator="\n"
        )
    print(f"landfill-details workbooks: {len(detail_frames)}")

    # --- Attachment triage -------------------------------------------------
    if args.skip_attachments:
        triage = pd.DataFrame()
        candidates = pd.DataFrame()
    else:
        triage, candidates = triage_attachments(scan_pdfs=args.scan_pdfs)
        triage.to_csv(TRIAGE, index=False, lineterminator="\n")
        candidates.to_csv(CANDIDATES, index=False, lineterminator="\n")
        print(f"attachments triaged: {len(triage)} | candidate rows: {len(candidates)}")

    # --- Proposals / apply ------------------------------------------------
    prop = pd.DataFrame(proposals)
    if prop.empty:
        prop = pd.DataFrame(columns=[
            "landfill_id", "target_table", "target_column", "current_value",
            "proposed_value", "value_format", "unit", "source_name", "file_path",
            "sheet", "cell", "evidence", "confidence", "apply", "status", "notes",
        ])
    # Proposal ledger is idempotent: after a value is applied it is no longer
    # regenerated (the master cell is no longer blank), so merge with the prior
    # ledger to keep the applied/conflict/hold audit trail visible on re-runs.
    if PROPOSALS.exists():
        old = pd.read_csv(PROPOSALS, dtype=str, keep_default_na=False)
        if not old.empty:
            key = ["landfill_id", "target_column", "source_name"]
            fresh = prop.copy()
            fresh["_k"] = list(map(tuple, fresh[key].astype(str).values))
            fresh_keys = set(fresh["_k"])
            old_keys = pd.Series(
                list(map(tuple, old[key].astype(str).values)), index=old.index
            )
            # Keep applied history (approved rows are no longer regenerated once
            # the master cell is filled) and any review row the current
            # extraction still produces.  Drop stale conflicts/holds that the
            # current extraction no longer generates.
            keep_mask = (old["status"].astype(str) == "approved") | old_keys.isin(fresh_keys)
            keep = old[keep_mask & ~old_keys.isin(fresh_keys)]
            prop = pd.concat([keep, fresh.drop(columns="_k")], ignore_index=True)
    prop = prop.drop(columns=["proposal_id"], errors="ignore")
    # Normalise after merging with the on-disk ledger (CSV strings vs booleans).
    prop["apply"] = prop["apply"].astype(str).str.lower().isin({"true", "1"})
    prop.insert(0, "proposal_id", [f"EXC-{i + 1:04d}" for i in range(len(prop))])
    prop.to_csv(PROPOSALS, index=False, lineterminator="\n")
    print(f"proposals: {len(prop)} | approved: {(prop['status'] == 'approved').sum()} "
          f"| conflicts: {(prop['status'] == 'conflict').sum()} "
          f"| hold: {(prop['status'] == 'hold').sum()}")

    if args.apply:
        prop, diff = apply_proposals(prop, sites)
        prop.to_csv(PROPOSALS, index=False, lineterminator="\n")
        append_actual_values(diff, prop)
        print(f"applied: {len(diff)} cells -> {DIFF}")
        if diff.empty and DIFF.exists():
            diff = pd.read_csv(DIFF, dtype=str, keep_default_na=False)
        update_manifest(
            {
                "UP-0001": "opening_year;closure_year;design_type;design_capacity_m3;"
                           "capture_efficiency;waste_tonnes_cumulative;composition;"
                           "total_area_ha;disposal_area_ha;n_cells;height_above_m;"
                           "depth_below_m;collection_service_fraction",
                "UP-0002": "latitude;longitude;annual_waste_inflow_tonnes;design_type;"
                           "leachate_system;gas_control_presence;facility_covariates",
            }
        )
    else:
        diff = pd.read_csv(DIFF, dtype=str, keep_default_na=False) if DIFF.exists() else pd.DataFrame()

    write_report(triage, matches, prop, diff, extractions, candidates)
    print(f"report: {REPORT}")


if __name__ == "__main__":
    main()
