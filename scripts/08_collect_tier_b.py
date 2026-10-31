"""Harvest non-metered engineered landfills into a Tier B attribute table.

Tier B is the validation / prior layer: sites whose engineering and operation are
documented in a CDM Project Design Document but which have **no metered landfill-gas
series** (``n_metered_periods == 0``).  Nothing here is modelled and nothing is inferred
from an emission reduction.

Fields are only filled when the PDD states them.  A missing attribute stays null and its
provenance says ``not_reported``; the script never guesses a liner, cover regime or gas
system from the project type.

Outputs
-------
data/interim/cdm/tier_b/tier_b_sites.csv          one row per site
data/interim/cdm/tier_b/tier_b_annual_inflow.csv  one row per site-year waste placement
data/interim/cdm/tier_b/tier_b_parse_log.csv      per-site extraction status

Usage
-----
    python scripts/08_collect_tier_b.py
    python scripts/08_collect_tier_b.py --refs 78 323 1505
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import INTERIM_CDM, RAW_CDM

CENSUS = INTERIM_CDM / "census" / "cdm_census_lfg.csv"
PROJECTS = INTERIM_CDM / "cdm_projects_asia.csv"
TEXT_DIR = INTERIM_CDM / "census" / "text"
PDD_DIR = RAW_CDM / "census" / "pdd"
OUT_DIR = INTERIM_CDM / "tier_b"
OUT_DIR.mkdir(parents=True, exist_ok=True)

YEAR = r"(?:19\d{2}|20\d{2})"


def _load_extract():
    """Reuse the PDF readers from script 10 (no code duplication)."""
    path = Path(__file__).resolve().parent / "10_extract_cdm_data.py"
    spec = importlib.util.spec_from_file_location("cdm_extract", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


extract = _load_extract()


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------
def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "")


def page_index(text: str) -> list[tuple[int, int]]:
    """(char offset, page number) from the 'page N' footers in the PDD text."""
    marks = [(m.start(), int(m.group(1)))
             for m in re.finditer(r"\bpage\s+(\d{1,3})\b", text, re.I)]
    return marks


def page_of(marks: list[tuple[int, int]], pos: int) -> int | None:
    page = None
    for off, pno in marks:
        if off <= pos:
            page = pno
        else:
            break
    return page


def snippet(text: str, start: int, end: int, pad: int = 90) -> str:
    return norm(text[max(0, start - pad):end + pad])[:260]


def first_match(text: str, patterns: list[str], marks, flags=re.I):
    for pat in patterns:
        for m in re.finditer(pat, text, flags):
            return m, page_of(marks, m.start())
    return None, None


# ---------------------------------------------------------------------------
# field extractors
# ---------------------------------------------------------------------------
DESIGN_PATTERNS = [
    (r"\bsanitary\s+landfill\b", "sanitary_landfill"),
    (r"\bsecured\s+landfill\b", "sanitary_landfill"),
    (r"\bengineered\s+landfill\b", "engineered_landfill"),
    (r"\bcontrolled\s+(?:dump|dumpsite|landfill|disposal)\b", "controlled_dump"),
    (r"\bopen\s+dump(?:ing|site)?\b", "open_dump"),
    (r"\buncontrolled\s+(?:dump|disposal|landfill)\b", "open_dump"),
]


def parse_design_type(text: str, marks) -> dict:
    hits = []
    for pat, label in DESIGN_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            hits.append((m.start(), label, m))
    if not hits:
        return {"design_type": None, "design_type_page": None,
                "design_type_evidence": "not_reported"}
    # The opening site description is the most reliable place; prefer the earliest
    # mention of a sanitary/engineered/controlled design over a later generic "open dump".
    priority = {"sanitary_landfill": 0, "engineered_landfill": 1,
                "controlled_dump": 2, "open_dump": 3}
    hits.sort(key=lambda h: (priority[h[1]], h[0]))
    pos, label, m = hits[0]
    return {"design_type": label, "design_type_page": page_of(marks, pos),
            "design_type_evidence": snippet(text, m.start(), m.end())}


LINER_PATTERNS = {
    "hdpe": r"\bHDPE\b|high[\s-]*density\s+polyethylene",
    "geomembrane": r"\bgeomembrane\b|geo[\s-]*membrane",
    "gcl": r"\bGCL\b|geosynthetic\s+clay\s+liner|bentonite",
    "compacted_clay": r"\bcompacted\s+clay\b|clay\s+liner|clay\s+layer",
    "composite": r"composite\s+liner",
}


def parse_liner(text: str, marks) -> dict:
    found, pages, evidence = [], [], ""
    for label, pat in LINER_PATTERNS.items():
        m = re.search(pat, text, re.I)
        if m:
            found.append(label)
            pages.append(page_of(marks, m.start()))
            evidence = evidence or snippet(text, m.start(), m.end())
    if not found:
        return {"liner_type": None, "liner_page": None, "liner_evidence": "not_reported"}
    return {"liner_type": "+".join(dict.fromkeys(found)),
            "liner_page": next((p for p in pages if p), None),
            "liner_evidence": evidence}


COVER_PATTERNS = {
    "daily": r"\bdaily\s+cover\b|cover(?:ed)?\s+(?:the\s+)?waste\s+(?:daily|each\s+day)",
    "intermediate": r"\bintermediate\s+cover\b",
    "final": r"\bfinal\s+cover\b|\bcapping\b|\bcap\s+layer\b",
}


def parse_cover(text: str, marks) -> dict:
    found, pages, evidence = [], [], ""
    for label, pat in COVER_PATTERNS.items():
        m = re.search(pat, text, re.I)
        if m:
            found.append(label)
            pages.append(page_of(marks, m.start()))
            evidence = evidence or snippet(text, m.start(), m.end())
    if not found:
        return {"cover_frequency": None, "cover_page": None,
                "cover_evidence": "not_reported"}
    # "daily+intermediate+final" is more informative than a single regime
    return {"cover_frequency": "+".join(found),
            "cover_page": next((p for p in pages if p), None),
            "cover_evidence": evidence}


LEACHATE_PATTERNS = {
    "collection": r"leachate\s+collection",
    "treatment": r"leachate\s+treatment|leachate\s+treatment\s+plant",
    "recirculation": r"leachate\s+recirculation",
    "extraction": r"leachate\s+extraction",
    "pond": r"leachate\s+pond|leachate\s+lagoon",
    "spraying": r"leachate\s+spray",
}


def parse_leachate(text: str, marks) -> dict:
    found, pages, evidence = [], [], ""
    for label, pat in LEACHATE_PATTERNS.items():
        m = re.search(pat, text, re.I)
        if m:
            found.append(label)
            pages.append(page_of(marks, m.start()))
            evidence = evidence or snippet(text, m.start(), m.end())
    if not found:
        return {"leachate_system": None, "leachate_page": None,
                "leachate_evidence": "not_reported"}
    return {"leachate_system": "+".join(found),
            "leachate_page": next((p for p in pages if p), None),
            "leachate_evidence": evidence}


GAS_PATTERNS = {
    "active_extraction": r"gas\s+(?:collection|extraction)\s+(?:system|well|network)|"
                         r"LFG\s+collection\s+system|vertical\s+gas\s+wells",
    "flare": r"\bflare\s+(?:stack|system)?\b|\bflaring\b",
    "passive_venting": r"passive\s+vent|gas\s+vent(?:ing|s)?\b",
    "power_generation": r"electricity\s+generation|power\s+generation|gas\s+engine",
}


def parse_gas_control(text: str, marks) -> dict:
    found, pages, evidence = [], [], ""
    for label, pat in GAS_PATTERNS.items():
        m = re.search(pat, text, re.I)
        if m:
            found.append(label)
            pages.append(page_of(marks, m.start()))
            evidence = evidence or snippet(text, m.start(), m.end())
    if not found:
        return {"gas_control_presence": "none_reported", "gas_control_page": None,
                "gas_control_evidence": "not_reported"}
    return {"gas_control_presence": "+".join(found),
            "gas_control_page": next((p for p in pages if p), None),
            "gas_control_evidence": evidence}


def parse_design_capacity(text: str, marks) -> dict:
    pats = [
        r"(?:design|total|storage|disposal|landfill)\s+capacity[^0-9]{0,40}?"
        r"([\d][\d,\.]*)\s*(million\s+tonnes?|million\s+tons?|kilo\s*tonnes?|kt|tonnes?|tons?)\b",
        r"capacity\s+of\s+([\d][\d,\.]*)\s*(million\s+tonnes?|million\s+tons?|kilo\s*tonnes?|kt|tonnes?|tons?)\b",
    ]
    for pat in pats:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        v = float(m.group(1).replace(",", ""))
        unit = m.group(2).lower().replace(" ", "")
        if unit.startswith("million"):
            v *= 1_000_000
        elif unit in {"kilotonnes", "kilotonne", "kt"}:
            v *= 1_000
        if 1_000 <= v <= 1e9:
            return {"design_capacity_tonnes": v,
                    "design_capacity_page": page_of(marks, m.start()),
                    "design_capacity_evidence": snippet(text, m.start(), m.end())}
    return {"design_capacity_tonnes": None, "design_capacity_page": None,
            "design_capacity_evidence": "not_reported"}


def parse_waste_source(text: str) -> str | None:
    low = text.lower()
    if re.search(r"industrial\s+waste|hazardous\s+waste", low) and \
            not re.search(r"municipal\s+solid\s+waste", low):
        return "industrial"
    if re.search(r"municipal\s+solid\s+waste|\bMSW\b|household\s+waste|domestic\s+waste",
                 text, re.I):
        return "municipal_solid_waste"
    if re.search(r"commercial\s+waste", low):
        return "commercial"
    if re.search(r"\bwaste\b", low):
        return "municipal_solid_waste"
    return None


COMPONENTS = {
    "food": r"food(?:\s+waste)?|kitchen|organic\s+waste|putrescible",
    "paper": r"paper|cardboard",
    "wood": r"wood|timber",
    "textile": r"textile|cloth",
    "plastic": r"plastic",
    "glass": r"glass",
    "metal": r"metal",
    "other": r"other|inert|miscellaneous",
}


def parse_composition(text: str) -> tuple[dict | None, str]:
    """Waste composition percentages, only when >=3 components are explicit."""
    vals: dict[str, float] = {}
    for label, pat in COMPONENTS.items():
        for m in re.finditer(
                r"(?:" + pat + r")[^%\d]{0,40}?(\d{1,2}(?:\.\d+)?)\s*%", text, re.I):
            v = float(m.group(1))
            if 0 < v <= 100:
                vals[label] = v / 100.0
                break
    if len(vals) < 3:
        return None, "not_reported"
    total = sum(vals.values())
    if not (0.5 <= total <= 1.15):
        return None, f"rejected_sum_{total:.2f}"
    return vals, "pdd_text"


# ---------------------------------------------------------------------------
# annual waste placement series (reuses the census table rules)
# ---------------------------------------------------------------------------
BAD_TABLE = re.compile(r"\bCERs?\b|emission\s+reduction|credited|credits?", re.I)
WASTE_HDR = re.compile(r"waste|disposed|disposal|landfill|refuse|msw", re.I)
TONNE_HDR = re.compile(r"tonnes?|tons?|mg|t/y|t\b", re.I)


def parse_waste_series(pdf: Path) -> dict[int, float]:
    series: dict[int, float] = {}
    try:
        tables = extract.read_pdf_tables(pdf)
    except Exception:
        return series
    for _, table in tables:
        if not table:
            continue
        header = " ".join(str(c) for row in table[:5] for c in row).lower()
        if BAD_TABLE.search(header) or not (WASTE_HDR.search(header) and TONNE_HDR.search(header)):
            continue
        for row in table:
            if len(row) < 2 or re.search(r"\btotal\b", str(row[0]), re.I):
                continue
            years = re.findall(r"\b" + YEAR + r"\b", str(row[0]))
            if len(years) != 1:
                continue
            for cell in row[1:]:
                v = extract.to_float(cell)
                if v and 100 < v < 1e9 and not (1900 <= v <= 2035):
                    series[int(years[0])] = v
                    break
    return series


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_row(ref: int, census_row: pd.Series, meta: pd.Series | None) -> tuple[dict, list[dict], dict]:
    txt_path = TEXT_DIR / f"pdd_{ref}.txt"
    pdf_path = PDD_DIR / f"{ref}_pdd.pdf"
    text = txt_path.read_text() if txt_path.exists() else ""
    marks = page_index(text)

    row = {
        "ref": ref,
        "landfill_name": census_row.get("title"),
        "host_party": census_row.get("host_party"),
        "methodology": meta.get("methodology") if meta is not None else None,
        "registration_date": meta.get("registration_date") if meta is not None else None,
        "pdd_path": str(pdf_path.relative_to(RAW_CDM.parent.parent)) if pdf_path.exists() else None,
    }
    if not text:
        row.update({"design_type": None, "data_source_type": "pdd_missing",
                    "provenance_reference": f"UNFCCC CDM ref {ref}: PDD text unavailable"})
        return row, [], {"ref": ref, "status": "pdd_missing", "n_inflow_years": 0}

    row.update(parse_design_type(text, marks))
    row.update(parse_liner(text, marks))
    row.update(parse_cover(text, marks))
    row.update(parse_leachate(text, marks))
    row.update(parse_gas_control(text, marks))
    row.update(parse_design_capacity(text, marks))

    comp, comp_status = parse_composition(text)
    row["waste_composition_fractions"] = json.dumps(comp, sort_keys=True) if comp else None
    for k in ("food", "paper", "wood", "textile", "plastic", "glass", "metal", "other"):
        row[f"{k}_fraction"] = (comp or {}).get(k)
    row["composition_status"] = comp_status
    row["waste_source_type"] = parse_waste_source(text)
    row["data_source_type"] = "cdm_pdd"
    row["provenance_reference"] = (
        f"UNFCCC CDM project ref {ref}; PDD 'project design document' "
        f"(data/raw/cdm/census/pdd/{ref}_pdd.pdf)"
    )

    series = parse_waste_series(pdf_path) if pdf_path.exists() else {}
    inflow_rows = [{"ref": ref, "year": y, "waste_inflow_tonnes": v,
                    "data_source_type": "cdm_pdd_table",
                    "provenance_reference": row["provenance_reference"]}
                   for y, v in sorted(series.items())]
    if series:
        last_year = max(series)
        row["annual_waste_inflow_tonnes"] = series[last_year]
        row["annual_inflow_year"] = last_year
        row["annual_inflow_basis"] = "pdd_table_last_year"
    else:
        row["annual_waste_inflow_tonnes"] = None
        row["annual_inflow_year"] = None
        row["annual_inflow_basis"] = "not_reported"

    row["waste_opening_year"] = census_row.get("waste_opening_year")
    row["waste_closing_year"] = census_row.get("waste_closing_year")
    row["waste_history_years"] = census_row.get("waste_history_years")
    row["waste_tonnes_cumulative"] = census_row.get("waste_tonnes_cumulative")
    row["cumulative_is_complete"] = bool(census_row.get("cumulative_is_complete"))

    log = {"ref": ref, "status": "ok", "n_inflow_years": len(series),
           "design_type": row.get("design_type"),
           "liner": row.get("liner_type"), "cover": row.get("cover_frequency"),
           "leachate": row.get("leachate_system"),
           "gas_control": row.get("gas_control_presence"),
           "composition": comp_status}
    return row, inflow_rows, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", nargs="*", type=int)
    ap.add_argument("--include-metered", action="store_true",
                    help="include sites that have a metered LFG series (off by default)")
    args = ap.parse_args()

    census = pd.read_csv(CENSUS)
    meta = pd.read_csv(PROJECTS).set_index("ref") if PROJECTS.exists() else None

    sel = census.copy()
    if not args.include_metered:
        sel = sel[(sel["gate_pass"] != True) & (sel["n_metered_periods"].fillna(0) == 0)]
    if args.refs:
        sel = sel[sel["ref"].astype(int).isin(args.refs)]

    print(f"Tier B scope: {len(sel)} non-metered engineered landfill candidates")

    rows, inflow, logs = [], [], []
    for _, r in sel.iterrows():
        ref = int(r["ref"])
        m = meta.loc[ref] if meta is not None and ref in meta.index else None
        row, inf, log = build_row(ref, r, m)
        rows.append(row)
        inflow.extend(inf)
        logs.append(log)

    sites = pd.DataFrame(rows).sort_values("ref")
    sites.to_csv(OUT_DIR / "tier_b_sites.csv", index=False)
    pd.DataFrame(inflow).to_csv(OUT_DIR / "tier_b_annual_inflow.csv", index=False)
    pd.DataFrame(logs).to_csv(OUT_DIR / "tier_b_parse_log.csv", index=False)

    print(f"wrote {OUT_DIR/'tier_b_sites.csv'} ({len(sites)} sites)")
    print(f"wrote {OUT_DIR/'tier_b_annual_inflow.csv'} ({len(inflow)} site-years)")
    for col in ("design_type", "liner_type", "cover_frequency", "leachate_system",
                "gas_control_presence", "waste_source_type"):
        filled = sites[col].notna().sum()
        print(f"  {col:24s} {filled:3d}/{len(sites)} reported")
    print(f"  composition               {sites['waste_composition_fractions'].notna().sum():3d}/{len(sites)} parsed")
    print(f"  annual inflow             {sites['annual_waste_inflow_tonnes'].notna().sum():3d}/{len(sites)} reported")


if __name__ == "__main__":
    main()
