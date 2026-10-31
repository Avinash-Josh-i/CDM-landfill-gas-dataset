"""Extract CDM landfill-gas parameters from downloaded PDD / monitoring-report PDFs.

Why the period comes from inside the PDF
----------------------------------------
The CDM project page lists monitoring periods and document links separately, and the two
lists are not guaranteed to be in the same order. Positional pairing therefore mislabels
files (a file named ``30_Apr_2007_30_Nov_2007.pdf`` was found to contain Jul 2016 data).
Every monitoring period in this script is read from the report text itself, so the label
always matches the numbers underneath it.

Extraction layers
-----------------
1. **Template block parser (high confidence).** CDM-MR reports carry a "SECTION D.2 Data
   and parameters monitored" section with one block per parameter. pdfplumber emits the
   fields out of visual order, so blocks are rebuilt across line and page breaks. Three
   template variants are supported::

       Data / Parameter:  LFG            Data/parameter: LFG
       total,y                           total,y
       Data unit: Nm3                    Unit Nm3
       Value(s) of monitored 125,359,715 Value(s) of monitored 188,490,496.3
       parameter:                        parameter:

   Value regions that are monthly tables are collapsed using their ``Total`` row; when
   both a "Measured" and an "Applied" column exist, both are retained.

2. **Proximity scanner (low confidence).** Keyword+number co-occurrence for values in prose.

Nothing is invented: a value is only emitted when a number is unambiguously attached to a
parameter block. Ambiguous multi-number blocks are skipped and flagged.

Outputs
-------
data/interim/cdm/text/<ref>/<doc>.txt                  page-tagged full text
data/interim/cdm/cdm_parameter_candidates.csv          every candidate with provenance
data/interim/cdm/cdm_annual_observations.csv           annual series per monitoring period
data/interim/cdm/cdm_extraction_report.csv             per-project status

Usage
-----
    python scripts/06_extract_cdm_data.py
    python scripts/06_extract_cdm_data.py --refs 941 1258
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA, ROOT

INTERIM = DATA / "interim" / "cdm"
TEXT_DIR = INTERIM / "text"
MANIFEST = INTERIM / "cdm_document_manifest.csv"
TEXT_DIR.mkdir(parents=True, exist_ok=True)

CH4_DENSITY_T_PER_M3 = 0.0007168  # t CH4 per m3 CH4 at 0 degC, 1 atm

NUM = r"[-+]?\d[\d,]*(?:\.\d+)?"
UNIT = r"(?:Nm3/h|Nm3|nM3|m3/h|m3|m³|tonnes?|tons?|tCH4|Mg|kg|%|percent|MWh|GWh)"
DATE = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+\w{3,9}\s+\d{4})"

PARAM_START_RE = re.compile(r"^\s*Data\s*/\s*[Pp]arameter\s*:", re.I)
UNIT_LINE_RE = re.compile(r"^\s*(?:Data\s*unit|Unit)\b\s*:?\s*(.*)", re.I)
DESC_LINE_RE = re.compile(r"^\s*Description\b\s*:?\s*(.*)", re.I)

LABEL_LINE_RE = re.compile(
    r"^\s*(Data\s*/\s*[Pp]arameter|Data\s*unit|Unit\b|Description|Source of data used|"
    r"Source of data|Measured\s*/|Measured/|Choice of data|Purpose of data|"
    r"Value\(s\)|Indicate what|Monitoring\s*equipment|Measuring/|Calculation method|"
    r"QA/QC|Additional comment)", re.I)

VALUE_START_RE = re.compile(r"^\s*Value\(s\)", re.I)
VALUE_END_RE = re.compile(
    r"^\s*(Indicate what|Monitoring\s*equipment|Measuring/|Calculation method|"
    r"QA/QC procedures|Additional comment|Purpose of data|Choice of data)", re.I)

METHANE_TERMS = r"(?:landfill\s*gas|LFG|methane|CH\s*4|biogas)"
QTY_VERBS = (r"(?:collected|captured|recovered|extracted|generated|produced|"
             r"flared|utilis(?:ed|ation)|utiliz(?:ed|ation)|combusted|destroyed)")

SENTENCE_RE = re.compile(
    rf"(?i)({METHANE_TERMS})[^\n]{{0,120}}?{QTY_VERBS}[^\n]{{0,80}}?({NUM})\s*({UNIT})")
REVERSE_RE = re.compile(
    rf"(?i)({NUM})\s*({UNIT})[^\n]{{0,80}}?({METHANE_TERMS})[^\n]{{0,80}}?{QTY_VERBS}")

# A collection-efficiency figure must carry an explicit % / fraction unit and must not be
# part of another word ("2nd site" produced a spurious CE = 0.02 before this guard).
CE_RE = re.compile(
    r"(?i)(?:collection\s+efficiency|\bCE\b)[^\n]{0,60}?(?<![\w.])"
    r"(\d+(?:\.\d+)?)\s*(%|percent|fraction)")

WASTE_RE = re.compile(
    rf"(?i)(?:waste|MSW|refuse|garbage)[^\n]{{0,60}}?"
    rf"(?:disposed|deposited|accepted|received|treated|delivered|landfilled)"
    rf"[^\n]{{0,60}}?({NUM})\s*(tonnes?|tons?|t\b|Mg\b)")

PERIOD_KW_RE = re.compile(
    r"(?is)monitoring\s+period[^\n]{0,200}?(" + DATE + r")\s*(?:to|until|[-–—])\s*(" + DATE + r")")
PERIOD_WORD_RE = re.compile(
    r"(?is)monitoring\s+period[^\n]{0,120}?(?:from\s+)?(?:the\s+)?"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(\w+)\s+(\d{4})[^\n]{0,60}?"
    r"(?:to|until|[-–—])\s*(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+of\s+(\w+)\s+(\d{4})")
PERIOD_ANY_RE = re.compile(r"(" + DATE + r")\s*(?:[-–—]|to|until)\s*(" + DATE + r")")

CANON_RULES = [
    (("lfg total", "lfg collected"), "lfg_total_nm3"),
    (("lfg flare", "lfg flared"), "lfg_flared_nm3"),
    (("lfg electricity", "lfg util", "lfg combust"), "lfg_utilised_nm3"),
    (("w ch4",), "ch4_fraction"),
    (("f vch4",), "ch4_fraction"),          # exact; f_vCH4,FG,h is exhaust gas, excluded below
    (("ch4 fraction",), "ch4_fraction"),
    (("flare efficiency", "fe"), "flare_efficiency"),
    (("d ch4", "ch4 density"), "ch4_density"),
    (("ce", "collection efficiency"), "collection_efficiency"),
]

VALUE_TOKEN_RE = re.compile(rf"(?<![\w.])({NUM})\s*({UNIT})?", re.I)


def to_float(s) -> float | None:
    if s is None:
        return None
    s = str(s).replace(" ", "").replace(",", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    if not s or s in {"-", ".", "-."}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def norm_unit(u: str) -> str:
    s = (u or "").lower().replace("³", "3")
    if "%" in s or "percent" in s:
        return "percent"
    if re.search(r"mg\s*/\s*m3", s):
        return "mg/m3"
    if re.search(r"nm\s*3\s*/\s*h", s):
        return "nm3/h"
    if re.search(r"\bnm\s*3|\bm3", s):
        return "m3"
    if re.search(r"mwh|gwh", s):
        return "mwh"
    if re.search(r"tch4|t-ch4|tonnes?|\bmg\b", s):
        return "tonnes"
    if re.search(r"\bkg\b", s):
        return "kg"
    return ""


def read_pdf_text(path: Path) -> list[tuple[int, str]]:
    import pdfplumber
    pages = []
    try:
        pdf_ctx = pdfplumber.open(path)
    except Exception as e:
        print(f"    unreadable PDF {path.name}: {type(e).__name__}")
        return pages
    with pdf_ctx as pdf:
        for i, page in enumerate(pdf.pages, 1):
            try:
                pages.append((i, page.extract_text() or ""))
            except Exception:
                pages.append((i, ""))
    return pages


def read_pdf_tables(path: Path):
    import pdfplumber
    out = []
    try:
        pdf_ctx = pdfplumber.open(path)
    except Exception:
        return out
    with pdf_ctx as pdf:
        for i, page in enumerate(pdf.pages, 1):
            try:
                for table in page.extract_tables() or []:
                    clean = [["" if c is None else str(c).replace("\n", " ").strip() for c in row]
                             for row in table]
                    out.append((i, clean))
            except Exception:
                continue
    return out


def snip(text: str, lo: int, hi: int, pad: int = 120) -> str:
    return re.sub(r"\s+", " ", text[max(0, lo - pad):hi + pad]).strip()


def canon_param(param: str) -> str | None:
    k = (param or "").lower().replace("_", " ").replace(".", " ")
    k = re.sub(r"[,\s]+", " ", k).strip()
    k = re.sub(r"\s+[a-z]$", "", k)          # drop trailing period variable (",y" -> " y")
    if "fg" in k.split() or k.endswith("fg"):   # exhaust/flare gas, not raw LFG
        return None
    for keys, field in CANON_RULES:
        for key in keys:
            if k == key or k.startswith(key):
                return field
    return None


def parse_value_region(region: list[str]) -> tuple[float | None, float | None, str, str]:
    """Return (measured, applied, unit, note) from a 'Value(s) ...' region.

    Handles single values, ranges with an explicit average, monthly tables with a Total
    row, and tables with separate Measured/Applied columns.
    """
    body = " ".join(region)
    applied_col = bool(re.search(r"(?i)applied\s+value", body))

    # ---- monthly table: use the Total row -----------------------------------
    total_nums: list[float] = []
    for line in region:
        m = re.search(r"(?i)\btotal\b(.*)$", line)
        if not m:
            continue
        nums = [float(x.replace(",", ""))
                for x in re.findall(NUM, m.group(1)) if x.strip(" ,.")]
        if len(nums) > len(total_nums):
            total_nums = nums
    if total_nums:
        if len(total_nums) >= 2 and applied_col:
            return total_nums[0], total_nums[1], "", "table total (measured/applied)"
        return total_nums[0], total_nums[0], "", "table total"

    # ---- single value / range ----------------------------------------------
    body_clean = re.sub(r"^\s*Value\(s\)\s*", "", body, flags=re.I)
    body_clean = re.sub(r"(?i)\bof\s+monitored\b|\bmonitored\s+parameter\b|\bparameter\b",
                        " ", body_clean)
    body_clean = body_clean.replace(":", " ")

    avg = re.search(r"(?i)average[^0-9]{0,20}([-+]?\d[\d,]*(?:\.\d+)?)", body_clean)
    if avg:
        v = float(avg.group(1).replace(",", ""))
        unit_m = re.search(rf"{NUM}\s*({UNIT})", body_clean, re.I)
        return v, v, norm_unit(unit_m.group(1)) if unit_m else "", "explicit average"

    tokens = [(float(m.group(1).replace(",", "")), norm_unit(m.group(2) or ""))
              for m in VALUE_TOKEN_RE.finditer(body_clean)]
    tokens = [t for t in tokens if t[0] is not None]
    if not tokens:
        return None, None, "", "no numeric value"

    if len(tokens) == 1:
        return tokens[0][0], tokens[0][0], tokens[0][1], "single value"

    rng = re.search(rf"({NUM})\s*[~\-–]\s*({NUM})", body_clean)
    if rng:
        a = float(rng.group(1).replace(",", ""))
        b = float(rng.group(2).replace(",", ""))
        if b >= a:
            return round((a + b) / 2, 6), None, tokens[-1][1], "range midpoint"

    return None, None, tokens[-1][1], f"ambiguous ({len(tokens)} numbers)"


def parse_d2_blocks(pages: list[tuple[int, str]]) -> list[dict]:
    """Parse CDM-MR 'Data / Parameter' blocks, keeping page provenance."""
    lines: list[tuple[int, str]] = []
    for pno, text in pages:
        for ln in text.splitlines():
            lines.append((pno, ln))

    # Restrict to the D.2 "monitored" section when the report has one, so ex-ante
    # defaults (GWP, density, grid EF) do not masquerade as monitored values.
    d2 = next((i for i, (_, ln) in enumerate(lines)
               if re.search(r"D\.?\s*2\.?\s+Data\s+and\s+parameters\s+monitored", ln, re.I)), 0)

    starts = [i for i, (_, ln) in enumerate(lines)
              if i >= d2 and PARAM_START_RE.match(ln)]
    blocks: list[dict] = []
    for idx, s in enumerate(starts):
        e = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        chunk = lines[s:e]
        raw = [ln for _, ln in chunk]
        page0 = chunk[0][0]

        first = PARAM_START_RE.sub("", raw[0]).strip()
        parts = [first] if first else []
        for ln in raw[1:]:
            if LABEL_LINE_RE.match(ln) or not ln.strip():
                break
            parts.append(ln.strip())
        param = " ".join(parts).strip()

        unit_raw = ""
        for j, ln in enumerate(raw):
            m = UNIT_LINE_RE.match(ln)
            if m:
                unit_parts = [m.group(1).strip()]
                for nxt in raw[j + 1:]:
                    if LABEL_LINE_RE.match(nxt) or not nxt.strip():
                        break
                    unit_parts.append(nxt.strip())
                unit_raw = " ".join(unit_parts)
                break

        desc = ""
        for j, ln in enumerate(raw):
            m = DESC_LINE_RE.match(ln)
            if m:
                desc_parts = [m.group(1).strip()]
                for nxt in raw[j + 1:]:
                    if LABEL_LINE_RE.match(nxt) or not nxt.strip():
                        break
                    desc_parts.append(nxt.strip())
                desc = " ".join(desc_parts)
                break

        value_page, region = page0, []
        for j, ln in enumerate(raw):
            if not VALUE_START_RE.match(ln):
                continue
            value_page = chunk[j][0]
            region = [ln]
            for pno, nxt in chunk[j + 1:]:
                if VALUE_END_RE.match(nxt) or PARAM_START_RE.match(nxt):
                    break
                region.append(nxt)
            break

        measured, applied, value_unit, note = (None, None, "", "")
        if region:
            measured, applied, value_unit, note = parse_value_region(region)

        value = applied if applied is not None else measured
        blocks.append({
            "param_raw": param,
            "unit_raw": unit_raw,
            "unit": norm_unit(value_unit) or norm_unit(unit_raw),
            "description": desc,
            "value_measured": measured,
            "value_applied": applied,
            "value": value,
            "value_note": note,
            "page": value_page if value is not None else page0,
            "canonical": canon_param(param),
        })
    return blocks


def scan_text(ref, label, doc_type, text, page) -> list[dict]:
    rows = []
    for kind, pat, order in (
        ("sentence", SENTENCE_RE, "term_first"),
        ("reverse", REVERSE_RE, "value_first"),
    ):
        for m in pat.finditer(text):
            g = m.groups()
            if order == "term_first":
                term, value, unit = g[0], g[1], g[2]
            else:
                value, unit, term = g[0], g[1], g[2]
            rows.append(dict(
                ref=ref, doc_type=doc_type, label=label, page=page,
                pattern=kind, parameter="methane_quantity", term=str(term).lower(),
                value=to_float(value), unit_raw=unit, unit=norm_unit(unit),
                snippet=snip(text, m.start(), m.end()), confidence="low",
            ))
    for m in CE_RE.finditer(text):
        val = to_float(m.group(1))
        if val is None:
            continue
        raw = m.group(2) or ""
        if norm_unit(raw) == "percent" or val > 1:
            val = val / 100.0
        if 0 < val <= 1:
            rows.append(dict(
                ref=ref, doc_type=doc_type, label=label, page=page,
                pattern="collection_efficiency", parameter="collection_efficiency",
                term="ce", value=val, unit_raw=raw, unit="fraction",
                snippet=snip(text, m.start(), m.end()), confidence="medium",
            ))
    for m in WASTE_RE.finditer(text):
        rows.append(dict(
            ref=ref, doc_type=doc_type, label=label, page=page,
            pattern="waste_quantity", parameter="waste_accepted", term="msw",
            value=to_float(m.group(1)), unit_raw=m.group(2), unit=norm_unit(m.group(2)),
            snippet=snip(text, m.start(), m.end()), confidence="low",
        ))
    return rows


def extract_tables(ref, label, doc_type, tables) -> list[dict]:
    """Total rows of tables whose header mentions methane / LFG with a unit."""
    rows = []
    for page, table in tables:
        if not table or len(table) < 2:
            continue
        header = " ".join(table[0]).lower()
        if not re.search(r"ch\s*4|methane|landfill gas|lfg|biogas", header):
            continue
        for row in table:
            joined = " ".join(row).strip()
            if not re.match(r"(?i)^total", joined):
                continue
            for c_i, cell in enumerate(row):
                if c_i == 0:
                    continue
                val = to_float(cell)
                if val is None or abs(val) < 1e-6:
                    continue
                col_header = table[0][c_i].lower() if c_i < len(table[0]) else ""
                if re.search(r"\bkg\b", col_header):
                    unit = "kg"
                elif re.search(r"tch4|t-ch4|tonnes?|\bt\b|\bmg\b", col_header):
                    unit = "tonnes"
                elif re.search(r"\bnm3|m3|m³", col_header):
                    unit = "m3"
                elif re.search(r"%|percent", col_header):
                    unit = "percent"
                else:
                    continue
                rows.append(dict(
                    ref=ref, doc_type=doc_type, label=label, page=page,
                    pattern="table_total",
                    parameter="ch4_fraction" if unit == "percent" else "methane_quantity",
                    term=col_header[:80], value=val, unit_raw=unit, unit=unit,
                    snippet=joined[:300],
                    confidence="high" if unit in {"tonnes", "kg"} else "medium",
                ))
    return rows


def load_pages(ref: int, label: str, doc_type: str, path: Path) -> list[tuple[int, str]]:
    out_dir = TEXT_DIR / str(ref)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt = out_dir / f"{doc_type}_{re.sub(r'[^0-9A-Za-z]+', '_', label)[:50]}.txt"
    if txt.exists():
        raw = txt.read_text()
        blocks = raw.split("\n\n=== PAGE ")
        pages = []
        for blk in blocks:
            m = re.match(r"(\d+) ===\n(.*)", blk, re.S)
            if m:
                pages.append((int(m.group(1)), m.group(2)))
        if pages:
            return pages
    pages = read_pdf_text(path)
    txt.write_text("\n\n".join(f"=== PAGE {i} ===\n{t}" for i, t in pages))
    return pages


def _to_date(s: str) -> date | None:
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d %b %Y", "%d %B %Y"):
        try:
            return pd.to_datetime(s, format=fmt).date()
        except Exception:
            continue
    d = pd.to_datetime(s, dayfirst=True, errors="coerce")
    return None if pd.isna(d) else d.date()


def detect_period(pages: list[tuple[int, str]]) -> tuple[date | None, date | None, int | None, str]:
    """Read the monitoring period from the report text.

    Reports state it in several ways:
        7th Monitoring Period: 01/04/2011 - 30/09/2011
        Monitoring period: 30/04/2007 - 30/11/2007
        monitoring period (from the 1st of January 2013 to the 31st of December 2013)
    Only lines that mention "monitoring period" are considered, so crediting-period and
    methodology dates are never mistaken for the reporting window.
    """
    lines: list[str] = []
    for _, text in pages[:20]:
        lines.extend(text.splitlines())

    for i, ln in enumerate(lines):
        if "monitoring period" not in ln.lower():
            continue
        window = " ".join(lines[i:i + 3])
        m = PERIOD_KW_RE.search(window)
        if m:
            d1, d2 = _to_date(m.group(1)), _to_date(m.group(2))
            if d1 and d2 and d2 > d1 and (d2 - d1).days < 1500:
                return d1, d2, (d2 - d1).days + 1, "text"
        m = PERIOD_WORD_RE.search(window)
        if m:
            d1 = _to_date(f"{m.group(1)} {m.group(2)} {m.group(3)}")
            d2 = _to_date(f"{m.group(4)} {m.group(5)} {m.group(6)}")
            if d1 and d2 and d2 > d1 and (d2 - d1).days < 1500:
                return d1, d2, (d2 - d1).days + 1, "text_words"

    # last resort: first plausible range on the first two pages
    head = "\n".join(t for _, t in pages[:2])
    for m in PERIOD_ANY_RE.finditer(head):
        d1, d2 = _to_date(m.group(1)), _to_date(m.group(2))
        if d1 and d2 and d2 > d1 and (d2 - d1).days < 1500:
            return d1, d2, (d2 - d1).days + 1, "fallback"
    return None, None, None, "not_found"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", nargs="*", type=int)
    args = ap.parse_args()

    if not MANIFEST.exists():
        raise SystemExit("Run scripts/05_download_cdm_docs.py first.")
    man = pd.read_csv(MANIFEST)
    if args.refs:
        man = man[man["ref"].isin(args.refs)]

    cand: list[dict] = []
    reports: list[dict] = []
    periods: list[dict] = []

    for ref, grp in man.groupby("ref"):
        ref = int(ref)
        n_blocks = n_scan = n_tables = 0
        for _, doc in grp.iterrows():
            rel = str(doc["path"])
            path = next((c for c in (ROOT / rel, ROOT / "data" / rel, DATA / rel)
                         if c.exists()), None)
            if path is None:
                print(f"{ref}: missing {rel}")
                continue
            label = str(doc.get("label") or path.stem)
            doc_type = str(doc.get("doc_type"))
            pages = load_pages(ref, label, doc_type, path)

            if doc_type == "monitoring_report":
                d1, d2, days, how = detect_period(pages)
                periods.append(dict(ref=ref, doc_path=rel, manifest_label=label,
                                    period_start=d1, period_end=d2, period_days=days,
                                    period_source=how))

            for b in parse_d2_blocks(pages):
                if b["value"] is None or not b["canonical"]:
                    continue
                cand.append(dict(
                    ref=ref, doc_type=doc_type, label=label, page=b["page"],
                    pattern="mr_template_block", parameter=b["canonical"],
                    term=b["param_raw"][:80], value=b["value"],
                    value_measured=b["value_measured"], value_applied=b["value_applied"],
                    unit_raw=b["unit_raw"], unit=b["unit"],
                    snippet=(b["description"] or "")[:300],
                    confidence="high", value_note=b["value_note"],
                ))
                n_blocks += 1

            for i, text in pages:
                if not text.strip():
                    continue
                found = scan_text(ref, label, doc_type, text, i)
                cand.extend(found)
                n_scan += len(found)

            if doc_type == "monitoring_report":
                tbl = extract_tables(ref, label, doc_type, read_pdf_tables(path))
                cand.extend(tbl)
                n_tables += len(tbl)

        print(f"{ref}: {len(grp)} docs | template values={n_blocks} | "
              f"scan hits={n_scan} | table totals={n_tables}")
        reports.append(dict(ref=ref, documents=len(grp), template_values=n_blocks,
                            scan_hits=n_scan, table_totals=n_tables))

    if not cand:
        print("No candidates extracted.")
        return

    cand_df = pd.DataFrame(cand)
    cand_df.to_csv(INTERIM / "cdm_parameter_candidates.csv", index=False)
    print(f"\nwrote {INTERIM/'cdm_parameter_candidates.csv'} ({len(cand_df)} rows)")

    if periods:
        per_df = pd.DataFrame(periods).sort_values(["ref", "period_start"], na_position="last")
        per_df.to_csv(INTERIM / "cdm_monitoring_periods.csv", index=False)
        print(f"wrote {INTERIM/'cdm_monitoring_periods.csv'} ({len(per_df)} monitoring reports)")

    # ---- annual observations: exactly one row per monitoring report ----------
    if not periods:
        print("No monitoring reports found; annual observations will be empty.")
        pd.DataFrame(columns=["registry_ref", "doc_label"]).to_csv(
            INTERIM / "cdm_annual_observations.csv", index=False)
        pd.DataFrame(reports).to_csv(INTERIM / "cdm_extraction_report.csv", index=False)
        return

    per = pd.DataFrame(periods)
    blocks = cand_df[(cand_df.pattern == "mr_template_block") &
                     (cand_df.doc_type == "monitoring_report")].copy()

    def agg(part, name):
        s = part[part.parameter == name]["value"].dropna()
        return float(s.median()) if len(s) else None

    rows = []
    for r in per.itertuples():
        part = blocks[(blocks["ref"] == r.ref) & (blocks["label"] == r.manifest_label)]
        lfg_total = agg(part, "lfg_total_nm3")
        lfg_flared = agg(part, "lfg_flared_nm3")
        lfg_util = agg(part, "lfg_utilised_nm3")
        wch4 = agg(part, "ch4_fraction")
        ce = agg(part, "collection_efficiency")
        frac = None if wch4 is None else (wch4 / 100.0 if wch4 > 1 else wch4)
        unit_rows = part[part.parameter == "lfg_total_nm3"]
        lfg_unit = str(unit_rows["unit"].iloc[0]) if len(unit_rows) else ""

        def tonnes(vol):
            return None if vol is None or frac is None else vol * frac * CH4_DENSITY_T_PER_M3

        days = r.period_days
        m_col = tonnes(lfg_total)
        rows.append(dict(
            registry_ref=int(r.ref),
            doc_label=r.manifest_label,
            doc_path=r.doc_path,
            period_start=r.period_start,
            period_end=r.period_end,
            period_days=days,
            period_source=r.period_source,
            year=(pd.to_datetime(r.period_start).year if pd.notna(r.period_start) else None),
            lfg_total_nm3=lfg_total,
            lfg_total_unit=lfg_unit,
            lfg_flared_nm3=lfg_flared,
            lfg_utilised_nm3=lfg_util,
            ch4_fraction=frac,
            methane_collected_tonnes=m_col,
            methane_flared_tonnes=tonnes(lfg_flared),
            methane_utilised_tonnes=tonnes(lfg_util),
            methane_collected_tonnes_per_year=(
                None if m_col is None or not days else m_col * 365.0 / days),
            collection_efficiency=ce,
            ce_basis="reported" if ce is not None else "not_reported",
            n_candidates=len(part),
        ))

    ann_df = (pd.DataFrame(rows)
              .sort_values(["registry_ref", "period_start"], na_position="last"))
    ann_df.to_csv(INTERIM / "cdm_annual_observations.csv", index=False)
    n_ok = ann_df["lfg_total_nm3"].notna().sum()
    print(f"wrote {INTERIM/'cdm_annual_observations.csv'} "
          f"({len(ann_df)} monitoring reports, {n_ok} with a metered LFG total)")

    pd.DataFrame(reports).to_csv(INTERIM / "cdm_extraction_report.csv", index=False)


if __name__ == "__main__":
    main()
