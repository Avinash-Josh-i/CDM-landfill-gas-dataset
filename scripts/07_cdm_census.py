"""CDM Tier-A census: PDD + one (or a few) monitoring reports per candidate.

Scope is the ``landfill_gas_candidate`` rows in ``data/interim/cdm/cdm_projects_asia.csv``.
The census answers one question: how many CDM landfill projects have

    waste_history_years >= 10   AND   n_metered_periods >= 1

where a "metered period" means the monitoring report publishes a structured
``Data / Parameter: LFG total`` block with a numeric value.  Emission reductions
(CERs) are *not* treated as metered LFG.

Downloads land in a new ``data/raw/cdm/census/`` subtree and are resumable.
Nothing in the existing ``pdd/``, ``mr/`` or interim files is deleted or overwritten.

Usage:
    python scripts/07_cdm_census.py download
    python scripts/07_cdm_census.py parse
    python scripts/07_cdm_census.py all
    python scripts/07_cdm_census.py parse --refs 941 1258
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA, RAW

ROOT = Path(__file__).resolve().parents[1]
CDM_INTERIM = DATA / "interim" / "cdm"
CENSUS_INTERIM = CDM_INTERIM / "census"
CENSUS_RAW = RAW / "cdm" / "census"
PDD_DIR = CENSUS_RAW / "pdd"
MR_DIR = CENSUS_RAW / "mr"
TEXT_DIR = CENSUS_INTERIM / "text"
MR_CACHE = CENSUS_INTERIM / "mr_parse"
WASTE_CACHE = CENSUS_INTERIM / "waste_parse"
MANIFEST = CENSUS_INTERIM / "census_manifest.csv"
OUT = CENSUS_INTERIM / "cdm_census_lfg.csv"
PROJECTS = CDM_INTERIM / "cdm_projects_asia.csv"
INDEX_DIR = RAW / "cdm" / "index"

for d in (CENSUS_INTERIM, CENSUS_RAW, PDD_DIR, MR_DIR, TEXT_DIR, MR_CACHE, WASTE_CACHE):
    d.mkdir(parents=True, exist_ok=True)

WASTE_PARSER_VERSION = "2"

PERIOD_RE = re.compile(r"^\d{1,2} \w{3} \d{4}\s*-\s*\d{1,2} \w{3} \d{4}$")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


docs = _load_module("cdm_docs", ROOT / "scripts" / "09_download_cdm_docs.py")
extract = _load_module("cdm_extract", ROOT / "scripts" / "10_extract_cdm_data.py")


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------
def _period_docs(detail: dict) -> list[dict]:
    out = []
    for d in detail.get("all_documents") or []:
        text = (d.get("text") or "").strip()
        href = d.get("href") or ""
        if href.startswith("http") and PERIOD_RE.match(text):
            out.append({"text": text, "href": href})
    # sort by the first date in the label
    def key(d):
        m = re.findall(r"\b(19\d{2}|20\d{2})\b", d["text"])
        return (int(m[0]) if m else 9999, d["text"])
    return sorted(out, key=key)


LFG_VOL_UNIT = r"(?:Nm3|N\s*m3|Sm3|S\s*m3|m3|m³)"
_LFG_VOL_FWD = re.compile(
    r"(?:landfill\s+gas|\bLFG)[^\n]{0,90}?([\d][\d,\.]{2,})\s*" + LFG_VOL_UNIT + r"\b", re.I)
_LFG_VOL_REV = re.compile(
    r"([\d][\d,\.]{2,})\s*" + LFG_VOL_UNIT + r"\s+(?:of\s+)?(?:landfill\s+gas|\bLFG)", re.I)
_NOT_LFG_VOL = re.compile(
    r"methane|\bCH4\b|CER|emission\s+reduction|tCO2|exhaust|flare\s+gas", re.I)
_BAD_VOL_CONTEXT = re.compile(
    r"design\s+capacity|capacity|meter|differential|range|maximum|max\.?|rated|"
    r"model|up\s+to|<=|≥|>=|<|>|per\s+hour|/h\b|hourly|flow\s+rate", re.I)


def _lfg_volume_from_text(text: str) -> tuple[float, str] | None:
    """Find an explicitly measured LFG volume (Nm3/Sm3/m3) in MR prose.

    This is *not* an emission reduction: it is a flow-meter quantity of raw
    landfill gas.  Lines about methane/CH4 volume, exhaust gas or CERs are
    rejected so the census never back-calculates LFG from CERs.  Meter
    specifications and design-capacity thresholds (e.g. "LFG <= 1/2 of design
    capacity [2,000 Nm3]" or "LFG total Meter ... 7500 m3") are also rejected.
    """
    for pat, fwd in ((_LFG_VOL_FWD, True), (_LFG_VOL_REV, False)):
        for m in pat.finditer(text):
            if fwd:
                between = text[m.start():m.start(1)]
                if _NOT_LFG_VOL.search(between) or _BAD_VOL_CONTEXT.search(between):
                    continue
            else:
                around = text[max(0, m.start() - 40):m.end()]
                if _NOT_LFG_VOL.search(around) or _BAD_VOL_CONTEXT.search(around):
                    continue
            v = _to_num(m.group(1))
            if v and v > 100:
                return v, "Nm3"
    return None


def _mr_has_lfg(path: Path) -> tuple[bool, dict]:
    """Parse one MR and return (has_lfg_total_block, compact result)."""
    pages = extract.read_pdf_text(path)
    if not pages:
        return False, {"unreadable": True, "period_source": "not_found"}
    txt = "\n".join(t for _, t in pages)
    blocks = extract.parse_d2_blocks(pages)
    lfg = [b for b in blocks if b.get("canonical") == "lfg_total_nm3" and b.get("value") is not None]
    ch4 = [b for b in blocks if b.get("canonical") == "ch4_fraction" and b.get("value") is not None]
    flared = [b for b in blocks if b.get("canonical") in ("lfg_flared_nm3", "lfg_utilised_nm3")
              and b.get("value") is not None]
    narr = _lfg_volume_from_text(txt)
    # CH4 fraction / flaring can also be reported in prose rather than a D2 block.
    ch4_text = bool(re.search(
        r"(?:methane|CH4)\s+(?:content|fraction)|w\s*CH4|fraction\s+of\s+methane", txt, re.I))
    flare_text = bool(re.search(
        r"landfill\s+gas\s+to\s+(?:flare|power|heat)|LFG\s*(?:flare|electricity|thermal)|"
        r"LFG\s+flared|gas\s+collection\s+and\s+(?:flaring|combustion)", txt, re.I))
    d1, d2, days, how = extract.detect_period(pages)
    res = {
        "unreadable": False,
        "has_lfg_total_block": bool(lfg),
        "has_ch4_fraction": bool(ch4) or ch4_text,
        "has_flared_or_utilised": bool(flared) or flare_text,
        "lfg_unit": lfg[0].get("unit") if lfg else (narr[1] if narr else ""),
        "example_value": lfg[0].get("value") if lfg else (narr[0] if narr else None),
        "lfg_evidence": ("structured_block" if lfg
                         else "narrative_volume" if narr else "none"),
        "lfg_narrative_value": narr[0] if narr else None,
        "period_start": d1.isoformat() if d1 else None,
        "period_end": d2.isoformat() if d2 else None,
        "period_days": days,
        "period_source": how,
        "n_lfg_blocks": len(lfg),
        "n_ch4_blocks": len(ch4),
        "n_flare_util_blocks": len(flared),
    }
    return bool(lfg), res



def download(refs: list[int] | None, limit: int | None, max_mr: int,
             force: bool = False) -> None:
    df = pd.read_csv(PROJECTS)
    df = df[df["landfill_class"] == "landfill_gas_candidate"].copy()
    if refs:
        df = df[df["ref"].astype(int).isin(refs)]
    df = df.sort_values("ref")
    if limit:
        df = df.head(limit)
    print(f"census download scope: {len(df)} projects", flush=True)

    manifest_rows = []
    if MANIFEST.exists():
        old = pd.read_csv(MANIFEST)
        manifest_rows = old.to_dict("records")
        done = ({int(r["ref"]) for r in manifest_rows if str(r.get("status")) == "ok"}
                if not force else set())
    else:
        done = set()

    with docs.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=docs.UA, accept_downloads=True)
        page = ctx.new_page()
        page.goto("https://cdm.unfccc.int/Projects/projsearch.html",
                  wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(2000)

        for i, (_, row) in enumerate(df.iterrows(), 1):
            ref = int(row["ref"])
            if ref in done:
                print(f"[{i}/{len(df)}] {ref}: already done", flush=True)
                continue
            print(f"[{i}/{len(df)}] {ref} {str(row['title'])[:70]}", flush=True)
            detail = {}
            cache = INDEX_DIR / f"project_{ref}.json"
            if cache.exists():
                try:
                    detail = json.loads(cache.read_text())
                except Exception:
                    detail = {}

            pdd_url = ((detail.get("pdd_links") or [{}])[0].get("href")
                       or (row.get("pdd_download_url") if isinstance(row.get("pdd_download_url"), str) else ""))
            pdd_path = PDD_DIR / f"{ref}_pdd.pdf"
            pdd_ok = False
            if pdd_url:
                pdd_ok = docs.download(page, pdd_url, pdd_path)
            print(f"    pdd {'ok' if pdd_ok else 'FAILED'}", flush=True)

            mrs = _period_docs(detail)
            if not mrs:
                # fall back to the scrape's URL list, without trusting its labels
                urls = [u for u in str(row.get("monitoring_report_urls") or "").split("; ")
                        if u.startswith("http")]
                mrs = [{"text": f"mr_{j+1}", "href": u} for j, u in enumerate(urls)]

            mr_ok = False
            mr_url = ""
            mr_path = None
            mr_attempts = 0
            mr_result = {}
            for k, d in enumerate(mrs[:max_mr], 1):
                mr_attempts = k
                target = MR_DIR / f"{ref}_mr_{k}.pdf"
                ok = docs.download(page, d["href"], target)
                if not ok:
                    print(f"    mr {k} FAILED", flush=True)
                    continue
                has_lfg, res = _mr_has_lfg(target)
                mr_result = res
                print(f"    mr {k} ok | LFG block={has_lfg} | period={res.get('period_source')}", flush=True)
                if has_lfg:
                    mr_ok = True
                    mr_url = d["href"]
                    mr_path = target
                    break
                # keep the first readable MR as the census evidence if none has LFG
                if mr_path is None:
                    mr_url = d["href"]
                    mr_path = target

            if mr_path is None and mrs:
                # no MR downloaded at all; still record the first URL for provenance
                mr_url = mrs[0]["href"]

            row_out = {
                "ref": ref,
                "title": row.get("title"),
                "host_party": row.get("host_party"),
                "n_mrs_available": int(row.get("n_monitoring_reports") or 0),
                "pdd_url": pdd_url,
                "pdd_path": str(pdd_path.relative_to(ROOT)) if pdd_ok else "",
                "pdd_ok": bool(pdd_ok),
                "mr_url": mr_url,
                "mr_path": str(mr_path.relative_to(ROOT)) if mr_path else "",
                "mr_ok": bool(mr_path is not None),
                "mr_attempts": mr_attempts,
                "status": "ok" if (pdd_ok or mr_path is not None) else "failed",
                "mr_has_lfg_total_block": bool(mr_result.get("has_lfg_total_block", False)),
                "mr_period_source": mr_result.get("period_source", ""),
                "downloaded_at": pd.Timestamp.now("UTC").isoformat(timespec="seconds"),
            }
            manifest_rows = [r for r in manifest_rows if int(r.get("ref", -1)) != ref]
            manifest_rows.append(row_out)
            pd.DataFrame(manifest_rows).to_csv(MANIFEST, index=False)
            time.sleep(0.3)

        browser.close()
    print(f"wrote {MANIFEST} ({len(manifest_rows)} rows)", flush=True)


# ---------------------------------------------------------------------------
# PDD parsing: waste history, composition, CE
# ---------------------------------------------------------------------------
YEAR = r"(?:19\d{2}|20\d{2})"


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _to_num(s: str) -> float | None:
    if s is None:
        return None
    s = str(s).replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def _year_values(text: str) -> list[int]:
    return [int(y) for y in re.findall(r"\b" + YEAR + r"\b", text)]


def _pdd_text(ref: int) -> str:
    txt = TEXT_DIR / f"pdd_{ref}.txt"
    if txt.exists():
        return txt.read_text()
    path = PDD_DIR / f"{ref}_pdd.pdf"
    if not path.exists():
        return ""
    pages = extract.read_pdf_text(path)
    out = "\n".join(t for _, t in pages)
    txt.write_text(out)
    return out


def parse_waste_history(text: str, ref: int | None = None) -> dict:
    """Best-effort PDD waste history.

    The gate is about the *site*, not the crediting window: a landfill that took
    waste for >=10 years qualifies even if its CDM monitoring is shorter.  We use
    explicit opening/closure statements first, then the span of an annual waste
    table.  Sentences about crediting periods, emission projections or legislation
    are deliberately ignored: they are the usual source of a bogus 20-30 year span.
    """
    t = _norm_space(text)
    low = t.lower()
    sents = re.split(r"(?<=[.!?])\s+", t)
    openings: list[tuple[int, int]] = []   # (priority, year); lower priority is better
    closings: list[tuple[int, int]] = []

    # Strong, standalone table lines ("Started operation 1995" / "Finish operation 2014")
    for m in re.finditer(r"\bstarted\s+operation\b[^0-9]{0,20}(" + YEAR + r")", low):
        openings.append((0, int(m.group(1))))
    for m in re.finditer(r"\bfinish(?:ed)?\s+operation\b[^0-9]{0,20}(" + YEAR + r")", low):
        closings.append((0, int(m.group(1))))

    open_pats = [
        (1, r"(?:waste|refuse|msw)[^.]{0,80}?(?:began|started|commenced)[^.]{0,60}?"
            r"(?:dumped|disposed|landfilled|received)[^.]{0,60}?\b(" + YEAR + r")\b"),
        (1, r"(?:landfill|dump(?:site)?|site)[^.]{0,80}?"
            r"(?:put\s+into\s+operation|started\s+operation|began\s+operation|"
            r"commenced\s+operation|in\s+operation\s+since|operational\s+since)"
            r"[^.]{0,60}?\b(" + YEAR + r")\b"),
        (2, r"(?:landfill|dump(?:site)?|site)[^.]{0,60}?"
            r"(?:constructed|built|established|opened|reopened|commissioned)"
            r"[^.]{0,60}?\b(" + YEAR + r")\b"),
        (3, r"(?:landfill|dump(?:site)?|site)[^.]{0,80}?\bfrom\s+(" + YEAR + r")\b"),
        (3, r"\bfrom\s+(" + YEAR + r")\b[^.]{0,100}?(?:waste|refuse|msw|landfill|dump)"),
        (4, r"(?:waste|refuse|msw)[^.]{0,100}?\b(" + YEAR + r")\b"),
    ]
    close_pats = [
        (1, r"(?:landfill|dump(?:site)?|site)[^.]{0,100}?"
            r"(?:closed|closure|ceased|finish(?:ed)?\s+operation|cut[- ]?off|"
            r"end\s+of\s+(?:the\s+)?year)[^.]{0,60}?\b(" + YEAR + r")\b"),
        (1, r"(?:closed|closure|ceased|finish(?:ed)?\s+operation|cut[- ]?off)[^.]{0,100}?"
            r"(?:landfill|dump(?:site)?|site)[^.]{0,60}?\b(" + YEAR + r")\b"),
        (2, r"(?:in\s+operation|operating|operation)[^.]{0,40}?"
            r"(?:until|up\s+to|through)[^.]{0,20}?\b(" + YEAR + r")\b"),
        (2, r"(?:landfilling|disposal|waste)[^.]{0,80}?"
            r"(?:until|up\s+to|through)[^.]{0,40}?\b(" + YEAR + r")\b"),
        (3, r"(?:until|up\s+to|through)\s+(?:the\s+)?(?:end\s+of\s+)?(?:year\s+)?"
            r"(" + YEAR + r")\b"),
    ]
    bad_close_context = re.compile(
        r"crediting\s+period|monitoring\s+period|biogas|emission|generation|"
        r"production|decrease|increase|model|projection|forecast|commitment\s+period", re.I)

    for sent in sents:
        sl = sent.lower()
        if not re.search(r"waste|refuse|msw|landfill|dump|disposal", sl):
            continue
        for prio, pat in open_pats:
            for m in re.finditer(pat, sl):
                y = int(m.group(1))
                span = sl[m.start():m.start(1)]
                # "expected to be in operation until 2023" is a closure, not an opening
                if re.search(r"until|up\s+to|through|expected\s+to\s+be", span):
                    continue
                if 1900 <= y <= 2035:
                    openings.append((prio, y))
        if bad_close_context.search(sent):
            continue
        for prio, pat in close_pats:
            for m in re.finditer(pat, sl):
                y = int(m.group(1))
                if 1900 <= y <= 2035:
                    closings.append((prio, y))

    # annual series from tables / text
    series: dict[int, float] = {}
    if ref is not None:
        try:
            tables = extract.read_pdf_tables(PDD_DIR / f"{ref}_pdd.pdf")
        except Exception:
            tables = []
    else:
        tables = []
    for _, table in tables:
        if not table:
            continue
        header_years = []
        for cell in table[0]:
            ys = re.findall(r"\b" + YEAR + r"\b", str(cell))
            header_years.append(int(ys[0]) if ys else None)
        if sum(1 for y in header_years if y) >= 3:
            header_txt = " ".join(str(c) for c in table[0]).lower()
            if re.search(r"\bCERs?\b|emission\s+reduction|credited|credits?", header_txt, re.I):
                continue
            for row in table[1:]:
                joined = " ".join(str(c) for c in row).lower()
                if not re.search(r"waste|disposed|disposal|landfill|refuse|msw", joined):
                    continue
                if re.search(r"\bCERs?\b|emission\s+reduction|credited|credits?", joined, re.I):
                    continue
                if not re.search(r"tonnes?|tons?|mg|t\b", joined):
                    continue
                for ci, cell in enumerate(row[1:], 1):
                    if ci < len(header_years) and header_years[ci]:
                        v = _to_num(cell)
                        if v and 100 < v < 1e9:
                            series[header_years[ci]] = v
    # row-oriented tables: year in first column, waste in second.  The data rows
    # themselves usually just say "2001 | 573,300", so the header row decides
    # whether the table is a waste series.  CER / emission-reduction tables are
    # explicitly excluded: they are not waste tonnage.
    bad_table = re.compile(r"\bCERs?\b|emission\s+reduction|credited|credits?", re.I)
    for _, table in tables:
        if not table:
            continue
        header_txt = " ".join(str(c) for c in table[0]).lower()
        if bad_table.search(header_txt):
            continue
        # Header text often spans several rows (e.g. "Waste / received by /
        # the landfill / per year"), so also look at the leading rows as a block.
        header_txt = " ".join(str(c) for row in table[:5] for c in row).lower()
        header_is_waste = (re.search(r"waste|disposed|disposal|landfill|refuse|msw", header_txt)
                           and re.search(r"tonnes?|tons?|mg|t/y|t\b", header_txt))
        for row in table:
            if len(row) < 2:
                continue
            first = str(row[0])
            if re.search(r"\btotal\b", first, re.I):
                continue
            ys = re.findall(r"\b" + YEAR + r"\b", first)
            if len(ys) != 1:
                continue
            joined = " ".join(str(c) for c in row).lower()
            if bad_table.search(joined):
                continue
            if not (header_is_waste
                    or re.search(r"waste|disposed|disposal|landfill|refuse|msw", joined)):
                continue
            for cell in row[1:]:
                v = _to_num(cell)
                if v and 100 < v < 1e9 and not (1900 <= v <= 2035):
                    series[int(ys[0])] = v
                    break

    # Text fallback only when the PDF has no usable waste table.  Keep the
    # longest run of consecutive years so a flaring/emissions table elsewhere in
    # the PDD cannot masquerade as a waste series.
    if not series:
        cand: dict[int, float] = {}
        for header in ("waste disposed", "waste in t/y", "total waste", "landfilled amount",
                       "waste disposal data", "annual waste", "waste received",
                       "waste accumulated", "waste input"):
            idx = low.find(header)
            if idx < 0:
                continue
            window = t[idx:idx + 2500]
            for m in re.finditer(
                    r"\b(" + YEAR + r")\b(?!\s*[-–—]\s*\d)[^0-9]{0,20}([\d][\d,]{2,})", window):
                y, v = int(m.group(1)), _to_num(m.group(2))
                if v and 1000 < v < 1e9 and not (1900 <= v <= 2035):
                    cand.setdefault(y, v)
        if cand:
            best: list[int] = []
            run: list[int] = []
            for y in sorted(cand):
                if run and y == run[-1] + 1:
                    run.append(y)
                else:
                    run = [y]
                if len(run) > len(best):
                    best = list(run)
            if len(best) >= 3:
                series = {y: cand[y] for y in best}

    # cumulative statement.  Avoid the regulatory "more than 500,000 tons" trap.
    cumulative = None
    cum_pat = re.compile(
        r"(?:cumulative|total)\s+(?:waste|refuse|msw)[^0-9]{0,40}?"
        r"([\d][\d,.]*)\s*(kilo\s*tonnes?|kilotonnes?|kt|million\s*tonnes?|mt|tonnes?|tons?|mg)",
        re.I)
    m = cum_pat.search(t)
    if m:
        v = _to_num(m.group(1))
        unit = m.group(2).lower().replace(" ", "")
        if v is not None:
            if unit in {"kilotonnes", "kilotonne", "kt"}:
                v *= 1_000
            elif unit in {"milliontonnes", "milliontonne", "mt"}:
                v *= 1_000_000
            cumulative = v
    if cumulative is None:
        m = re.search(
            r"waste\s+in\s+place\s*(?:\(tonnes?\))?\s*[:=]?\s*([\d][\d,.]*)\s*"
            r"(tonnes?|tons?|mg)", t, re.I)
        if m and not re.search(r"more\s+than\s*$", t[max(0, m.start() - 20):m.start()], re.I):
            cumulative = _to_num(m.group(1))

    if series:
        s_years = sorted(series)
        s_min, s_max = s_years[0], s_years[-1]
        if cumulative is None:
            cumulative = float(sum(series.values()))
    else:
        s_min = s_max = None

    # Earliest credible opening year; latest credible closure year.  Tiers are
    # confidence bands, not a ranking to min/max on, because a reopened site can
    # have a high-confidence "reopened 2000" that is *later* than its 1973 origin.
    open_years = [y for p, y in openings if p <= 3] or [y for _, y in openings]
    close_years = [y for p, y in closings if p <= 2] or [y for _, y in closings]
    opening = min(open_years) if open_years else s_min
    closing = max(close_years) if close_years else s_max
    if opening is None and s_min is not None:
        opening = s_min
    if closing is None and s_max is not None:
        closing = s_max
    if opening and closing and closing < opening:
        closing = opening
    years = (closing - opening + 1) if opening and closing else None

    # A series is only "complete" if it covers every year of the site's history,
    # not merely every year between its own first and last point.
    if series and opening and closing:
        complete = all(y in series for y in range(opening, closing + 1))
    elif series:
        complete = len(series) == (s_max - s_min + 1)
    else:
        complete = False

    return {
        "waste_history_years": years,
        "waste_opening_year": opening,
        "waste_closing_year": closing,
        "waste_tonnes_cumulative": cumulative,
        "cumulative_is_complete": bool(complete),
        "waste_series_years": len(series),
        "waste_series_first_year": s_min,
        "waste_series_last_year": s_max,
        "waste_history_basis": (
            "pdd_opening_closure" if openings and closings
            else "pdd_series_span" if series
            else "pdd_text_range" if openings or closings
            else "unknown"),
    }


def _cached_waste_history(ref: int, text: str) -> dict:
    """Cache the expensive PDF-table waste parse per ref + parser version."""
    cache = WASTE_CACHE / f"{ref}.json"
    if cache.exists():
        try:
            d = json.loads(cache.read_text())
            if d.get("_version") == WASTE_PARSER_VERSION:
                return d
        except Exception:
            pass
    d = parse_waste_history(text, ref)
    d["_version"] = WASTE_PARSER_VERSION
    cache.write_text(json.dumps(d, indent=1))
    return d


def parse_composition(text: str) -> dict:
    t = _norm_space(text)
    low = t.lower()
    vals = {}
    for key, pat in {
        "food_fraction": r"food(?:\s+waste)?[^.%]{0,40}?(\d+(?:\.\d+)?)\s*%",
        "paper_fraction": r"paper(?:\s+and\s+cardboard)?[^.%]{0,40}?(\d+(?:\.\d+)?)\s*%",
        "wood_fraction": r"wood(?:\s+and\s+yard)?[^.%]{0,40}?(\d+(?:\.\d+)?)\s*%",
        "textile_fraction": r"textile[^.%]{0,40}?(\d+(?:\.\d+)?)\s*%",
    }.items():
        m = re.search(pat, low)
        if m:
            v = _to_num(m.group(1))
            if v is not None:
                vals[key] = v / 100.0
    has_comp = len(vals) >= 2 or bool(re.search(r"waste\s+composition|composition\s+of\s+(?:the\s+)?waste", low))

    def _param(key_pat: str) -> float | None:
        """First non-zero numeric value attached to a parameter name.

        The IPCC default text reads "DOC = fraction of degradable organic
        carbon ... default value = 0.", so a bare regex happily returns 0.0.
        Zero (and sub-1%) values are skipped, and DOCf is matched before DOC.
        """
        for m in re.finditer(
                r"\b" + key_pat + r"\b\s*(?:value)?\s*(?:=|:)?\s*"
                r"(\d+(?:\.\d+)?)\s*(%)?", t, re.I):
            v = _to_num(m.group(1))
            if v is None or v <= 0.01:
                continue
            return v / 100.0 if v > 1 else v
        return None

    docf = _param(r"docf")
    doc = _param(r"doc(?!f)")
    mcf = _param(r"mcf")
    return {
        "has_composition": bool(has_comp),
        "doc_pct": doc,
        "docf": docf,
        "mcf": mcf,
        **vals,
    }


def parse_ce(text: str, source: str) -> dict:
    """Explicit % only.  The old regex matched the '2' in '2nd site'."""
    t = _norm_space(text)
    pats = [
        # table layout: "Gas collection efficiency % 30"
        r"collection\s+efficiency\s*(?:\(%\)|%)\s*[:=]?\s*(\d+(?:\.\d+)?)",
        r"collection\s+efficiency[^.%]{0,100}?(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%[^.]{0,100}?collection\s+efficiency",
        r"(?:proportion|fraction)\s+of\s+methane\s+collected[^.%]{0,50}?(\d+(?:\.\d+)?)\s*%",
        r"methane\s+collection\s+(?:efficiency|rate)[^.%]{0,50}?(\d+(?:\.\d+)?)\s*%",
    ]
    for pat in pats:
        for m in re.finditer(pat, t, re.I):
            v = _to_num(m.group(1))
            if v is None or not (0 < v <= 100):
                continue
            lo = max(0, m.start() - 160)
            hi = min(len(t), m.end() + 160)
            ctx = t[lo:hi].lower()
            if re.search(r"measur|monitor|tracer|flow\s*balance|test", ctx):
                basis = "measured"
            elif re.search(r"assum|default|estimat|design|theoretical|feasibility", ctx):
                basis = "assumed"
            else:
                basis = "reported"
            return {
                "ce_value": v / 100.0,
                "ce_basis": basis,
                "ce_source": source,
                "ce_snippet": t[lo:hi][:300],
            }
    return {"ce_value": None, "ce_basis": "not_reported", "ce_source": "", "ce_snippet": ""}


# ---------------------------------------------------------------------------
# census assembly
# ---------------------------------------------------------------------------
def parse(refs: list[int] | None, limit: int | None) -> None:
    if not MANIFEST.exists():
        raise SystemExit("Run the download stage first.")
    man = pd.read_csv(MANIFEST)
    if refs:
        man = man[man["ref"].astype(int).isin(refs)]
    if limit:
        man = man.head(limit)

    rows = []
    for _, r in man.iterrows():
        ref = int(r["ref"])
        pdd_text = _pdd_text(ref)
        waste = (_cached_waste_history(ref, pdd_text) if pdd_text else {
            "waste_history_years": None, "waste_opening_year": None,
            "waste_closing_year": None, "waste_tonnes_cumulative": None,
            "cumulative_is_complete": False, "waste_series_years": 0,
            "waste_series_first_year": None, "waste_series_last_year": None,
            "waste_history_basis": "pdd_unreadable",
        })
        comp = parse_composition(pdd_text) if pdd_text else {
            "has_composition": False, "doc_pct": None, "docf": None, "mcf": None,
        }
        ce = parse_ce(pdd_text, "pdd") if pdd_text else {
            "ce_value": None, "ce_basis": "not_reported", "ce_source": "", "ce_snippet": ""}

        mr_cache = MR_CACHE / f"{ref}.json"
        mr_res = {}
        if mr_cache.exists():
            try:
                mr_res = json.loads(mr_cache.read_text())
            except Exception:
                mr_res = {}
        if (mr_res and ("lfg_evidence" not in mr_res
                        or mr_res.get("lfg_evidence") == "narrative_volume")):
            mr_res = {}          # recompute: older parser / tightened narrative rule
        if not mr_res:
            mr_path = ROOT / str(r.get("mr_path") or "")
            if mr_path.exists():
                _, mr_res = _mr_has_lfg(mr_path)
                mr_cache.write_text(json.dumps(mr_res, indent=1))
            else:
                mr_res = {
                    "unreadable": False, "has_lfg_total_block": False,
                    "has_ch4_fraction": False, "has_flared_or_utilised": False,
                    "lfg_unit": "", "example_value": None, "lfg_evidence": "none",
                    "period_start": None, "period_end": None, "period_days": None,
                    "period_source": "not_found", "n_lfg_blocks": 0,
                    "n_ch4_blocks": 0, "n_flare_util_blocks": 0,
                }

        # If the manifest's chosen MR has no LFG evidence, check the other MRs
        # already downloaded for this ref: the downloader keeps the first report
        # while a later one may carry the measured volume.
        mr_path_rel = str(r.get("mr_path") or "")
        if (not mr_res.get("has_lfg_total_block")
                and not mr_res.get("lfg_narrative_value")
                and int(r.get("mr_attempts") or 0) > 1):
            for cand in sorted(MR_DIR.glob(f"{ref}_mr_*.pdf")):
                if str(cand.relative_to(ROOT)) == mr_path_rel:
                    continue
                _, alt = _mr_has_lfg(cand)
                if alt.get("has_lfg_total_block") or alt.get("lfg_narrative_value"):
                    mr_res = alt
                    mr_path_rel = str(cand.relative_to(ROOT))
                    mr_cache.write_text(json.dumps(alt, indent=1))
                    break

        # MR CE wins over PDD CE when present
        mr_text = ""
        mr_path = ROOT / mr_path_rel
        if mr_path.exists():
            pages = extract.read_pdf_text(mr_path)
            mr_text = "\n".join(t for _, t in pages)
        mr_ce = parse_ce(mr_text, "mr") if mr_text else {
            "ce_value": None, "ce_basis": "not_reported", "ce_source": "", "ce_snippet": ""}
        if mr_ce["ce_value"] is not None:
            ce = mr_ce

        n_metered = 1 if (mr_res.get("has_lfg_total_block")
                          or mr_res.get("lfg_narrative_value")) else 0
        span = (mr_res.get("period_days") / 365.25
                if mr_res.get("period_days") and n_metered else None)

        reasons = []
        if not r.get("pdd_ok"):
            reasons.append("pdd_unavailable")
        if waste.get("waste_history_years") is None:
            reasons.append("waste_history_unknown")
        elif waste["waste_history_years"] < 10:
            reasons.append("waste_history_lt_10y")
        if not r.get("mr_ok"):
            reasons.append("no_monitoring_report" if int(r.get("n_mrs_available") or 0) == 0
                           else "mr_download_failed")
        elif mr_res.get("unreadable"):
            reasons.append("mr_unreadable")
        elif n_metered == 0:
            reasons.append("no_lfg_total_block")

        gate = (waste.get("waste_history_years") is not None
                and waste["waste_history_years"] >= 10
                and n_metered >= 1)
        if gate:
            reasons = ["pass"]

        rows.append({
            "ref": ref,
            "title": r.get("title"),
            "host_party": r.get("host_party"),
            "gate_pass": bool(gate),
            "has_lfg_total_block": bool(mr_res.get("has_lfg_total_block")),
            "has_ch4_fraction": bool(mr_res.get("has_ch4_fraction")),
            "has_flared_or_utilised": bool(mr_res.get("has_flared_or_utilised")),
            "lfg_unit": mr_res.get("lfg_unit") or "",
            "example_value": mr_res.get("example_value"),
            "lfg_evidence": mr_res.get("lfg_evidence") or "none",
            "n_metered_periods": n_metered,
            "metered_span_years": round(span, 3) if span is not None else None,
            "period_start": mr_res.get("period_start"),
            "period_end": mr_res.get("period_end"),
            "period_source": mr_res.get("period_source") or "not_found",
            "n_mrs_available": int(r.get("n_mrs_available") or 0),
            "mr_attempts": int(r.get("mr_attempts") or 0),
            "waste_history_years": waste.get("waste_history_years"),
            "waste_opening_year": waste.get("waste_opening_year"),
            "waste_closing_year": waste.get("waste_closing_year"),
            "waste_tonnes_cumulative": waste.get("waste_tonnes_cumulative"),
            "cumulative_is_complete": bool(waste.get("cumulative_is_complete")),
            "waste_history_basis": waste.get("waste_history_basis"),
            "has_composition": bool(comp.get("has_composition")),
            "doc_pct": comp.get("doc_pct"),
            "docf": comp.get("docf"),
            "mcf": comp.get("mcf"),
            "ce_value": ce.get("ce_value"),
            "ce_basis": ce.get("ce_basis") or "not_reported",
            "ce_source": ce.get("ce_source") or "",
            "failure_reason": "; ".join(reasons),
        })

    out = pd.DataFrame(rows).sort_values("ref")
    # A partial run must not truncate the census: merge the refreshed refs back
    # into the existing output instead of overwriting the whole file.
    if refs and OUT.exists():
        try:
            old = pd.read_csv(OUT)
            keep = old[~old["ref"].astype(int).isin([int(x) for x in refs])]
            out = (pd.concat([keep, out], ignore_index=True)
                   .drop_duplicates("ref", keep="last")
                   .sort_values("ref"))
        except Exception:
            pass
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(out)} rows)", flush=True)
    print(f"gate pass: {int(out['gate_pass'].sum())}/{len(out)}", flush=True)
    print(out["failure_reason"].value_counts().to_string(), flush=True)


def report() -> None:
    if not OUT.exists():
        raise SystemExit("No census output yet; run the parse stage first.")
    df = pd.read_csv(OUT)
    n = len(df)
    passed = df[df["gate_pass"].astype(bool)]
    print(f"\n=== CDM Tier-A census ({OUT}) ===")
    print(f"scope: {n} landfill_gas_candidate projects")
    print(f"gate pass (waste_history_years >= 10 AND n_metered_periods >= 1): "
          f"{len(passed)}/{n}")
    print("\nfailure_reason breakdown:")
    print(df["failure_reason"].value_counts().to_string())
    print("\nLFG evidence among passers:")
    print(passed["lfg_evidence"].value_counts().to_string())
    print("\nCE basis among passers:")
    print(passed["ce_basis"].value_counts().to_string())
    print(f"\nhas_composition among passers: {int(passed['has_composition'].sum())}/{len(passed)}")
    print(f"cumulative_is_complete among passers: "
          f"{int(passed['cumulative_is_complete'].sum())}/{len(passed)}")
    weak = df[df["period_source"].isin(["not_found", "fallback"])]
    print(f"\nperiod_source not_found/fallback: {len(weak)}")
    if len(weak):
        print(weak[["ref", "period_source", "n_metered_periods", "gate_pass"]]
              .to_string(index=False))
    if len(passed):
        print("\npassing refs:")
        print(passed[["ref", "host_party", "waste_history_years", "n_metered_periods",
                      "lfg_evidence", "has_composition", "ce_value", "ce_basis"]]
              .to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["download", "parse", "report", "all"],
                    nargs="?", default="all")
    ap.add_argument("--refs", nargs="*", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-mr", type=int, default=5,
                    help="try up to N monitoring reports until a metered LFG block is found")
    ap.add_argument("--force", action="store_true", help="re-download refs already in the manifest")
    args = ap.parse_args()

    if args.stage in ("download", "all"):
        download(args.refs, args.limit, args.max_mr, force=args.force)
    if args.stage in ("parse", "all"):
        parse(args.refs, args.limit)
    if args.stage in ("report", "all"):
        report()


if __name__ == "__main__":
    main()
