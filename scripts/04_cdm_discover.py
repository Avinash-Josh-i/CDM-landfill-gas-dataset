"""Discover UNFCCC CDM landfill / waste-handling projects (Sectoral Scope 13).

The CDM project search is a server-side, session-bound form protected by Incapsula.
Plain HTTP clients are blocked, so a real browser (Playwright/Chromium) drives the form.

Stages:
    python scripts/04_cdm_discover.py list      # scrape the full scope-13 project list
    python scripts/04_cdm_discover.py details   # fetch project pages for Asian projects
    python scripts/04_cdm_discover.py all

Outputs:
    data/interim/cdm/cdm_projects_all.csv
    data/interim/cdm/cdm_projects_asia.csv
    data/raw/cdm/index/project_<ref>.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA, RAW

SEARCH_URL = "https://cdm.unfccc.int/Projects/projsearch.html"
INTERIM = DATA / "interim" / "cdm"
INDEX_DIR = RAW / "cdm" / "index"
INTERIM.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Host-party spellings used by the UNFCCC CDM registry.
ASIA_HOSTS = {
    "Afghanistan", "Bahrain", "Bangladesh", "Bhutan", "Brunei Darussalam",
    "Cambodia", "China", "China (Hong Kong)", "Hong Kong", "India", "Indonesia",
    "Iran (Islamic Republic of)", "Iraq", "Israel", "Japan", "Jordan",
    "Kazakhstan", "Kuwait", "Kyrgyzstan", "Lao People's Democratic Republic",
    "Lebanon", "Malaysia", "Maldives", "Mongolia", "Myanmar", "Nepal",
    "Oman", "Pakistan", "Philippines", "Qatar", "Republic of Korea", "Korea",
    "Saudi Arabia", "Singapore", "Sri Lanka", "Syrian Arab Republic",
    "Taiwan", "Tajikistan", "Thailand", "Timor-Leste", "Turkey", "Turkmenistan",
    "United Arab Emirates", "Uzbekistan", "Viet Nam", "Vietnam", "Yemen",
    "Democratic People's Republic of Korea",
}

# Methodologies / keywords that indicate landfill-gas recovery (metered methane).
LFG_HINTS = [
    "landfill", "lfg", "methane recovery", "methane capture", "gas recovery",
    "waste gas", "biogas", "dumpsite", "dumping site",
]
# Project types that are scope 13 but never yield landfill-gas collection labels.
NEGATIVE_HINTS = [
    "compost", "composting", "vermicompost", "waste water", "wastewater",
    "swine", "manure", "poultry", "animal waste", "co-composting",
    "recycling", "segregation", "incineration", "anaerobic digestion of",
    "industrial wastewater", "palm oil", "tapioca", "starch",
]


def is_asia(host: str) -> bool:
    return host.strip() in ASIA_HOSTS


def classify(title: str, methodology: str) -> str:
    """Classify a scope-13 project as landfill-gas relevant or not.

    Methodology codes are the strongest signal: ACM0001 / AM0003 / AM0011 /
    AMS-III.G / AMS-III.L are landfill-gas methodologies. Title keywords are the
    fallback, because some registrations list only the umbrella methodology.
    A title that mentions wastewater, lagoons or digesters is NOT a landfill site even
    if it says "methane extraction".
    """
    meth = (methodology or "").upper()
    t = (title or "").lower()

    landfill_meth = ("ACM0001", "AM0003", "AM0011", "AMS-III.G", "AMS-III.L",
                     "AMS.III.G", "AMS.III.L")
    if any(code in meth for code in landfill_meth):
        return "landfill_gas_candidate"

    if any(k in t for k in ("landfill", "lfg", "dumpsite", "dumping site", "dump site")):
        return "landfill_gas_candidate"

    if any(k in t for k in NEGATIVE_HINTS):
        return "other_waste"
    return "unclear"


def run_search(page) -> int:
    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_selector("#Scopes", timeout=60_000)
    page.select_option("#Scopes", ["13"])
    page.select_option("#Status", "Registered")
    page.click("input[name=button]")
    page.wait_for_timeout(6000)
    body = page.inner_text("body")
    m = re.search(r"Total projects found:\s*([\d,]+)", body)
    total = int(m.group(1).replace(",", "")) if m else 0
    return total


PAGE_JS = """() => {
  const tables = [...document.querySelectorAll('table.formTable')];
  for (const t of tables) {
    const head = t.innerText.slice(0, 300);
    if (head.includes('Title') && head.includes('Ref')) {
      return [...t.querySelectorAll('tr')].map(tr => ({
        cells: [...tr.querySelectorAll('td')].map(td => td.innerText.trim()),
        links: [...tr.querySelectorAll('a')].map(a => ({text: a.innerText.trim(), href: a.href}))
      })).filter(r => r.cells.length >= 6);
    }
  }
  return [];
}"""


def page_count(page) -> int:
    html = page.content()
    pages = [int(x) for x in re.findall(r'style="cursor: pointer;">(\d+)</a>', html)]
    return max(pages) if pages else 1


def scrape_list(page) -> pd.DataFrame:
    total = run_search(page)
    print(f"scope 13 registered projects: {total}")
    n_pages = page_count(page)
    print(f"pages: {n_pages}")

    rows = []
    for p in range(1, n_pages + 1):
        if p > 1:
            link = page.get_by_role("link", name=str(p), exact=True)
            if not link.count():
                # page numbers beyond the visible window: step through "next" pages
                print(f"  page {p}: link not visible, stopping")
                break
            link.first.click()
            page.wait_for_timeout(4500)
        data = page.evaluate(PAGE_JS)
        for r in data:
            cells = r["cells"]
            if len(cells) < 7:
                continue
            href = next((l["href"] for l in r["links"] if "/Projects/DB/" in l["href"]), "")
            rows.append({
                "registration_date": cells[0],
                "title": cells[1],
                "host_party": cells[2],
                "other_parties": cells[3].replace("\n", "; "),
                "methodology": cells[4].replace("\n", " ").strip(),
                "reductions_t_co2e_pa": cells[5].replace(",", "").strip(),
                "ref": cells[6].strip(),
                "project_url": href,
                "page": p,
            })
        print(f"  page {p}/{n_pages}: {len(data)} rows (cumulative {len(rows)})")
        time.sleep(0.4)

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["ref"]).reset_index(drop=True)
    df["project_url"] = df["project_url"].replace("", pd.NA)
    df["is_asia"] = df["host_party"].str.strip().isin(ASIA_HOSTS)
    df["landfill_class"] = [
        classify(t, m) for t, m in zip(df["title"].astype(str), df["methodology"].astype(str))
    ]
    return df


DETAIL_JS = """() => {
  const out = {text: document.body.innerText, links: []};
  for (const a of document.querySelectorAll('a')) {
    out.links.push({text: a.innerText.trim(), href: a.href});
  }
  return out;
}"""


def parse_detail(html_text: str, links: list[dict]) -> dict:
    """Parse a CDM project page into structured fields.

    The project page renders as ``<label>\\t<value>`` lines, so we split on tabs
    instead of collapsing whitespace.
    """
    fields: dict[str, str] = {}
    for line in html_text.splitlines():
        if "\t" not in line:
            continue
        label, _, value = line.partition("\t")
        label = label.strip().lower()
        value = value.strip()
        if label and value and label not in fields:
            fields[label] = value

    def grab(key: str):
        return fields.get(key)

    t = html_text

    docs = []
    for l in links:
        href = l.get("href") or ""
        text = (l.get("text") or "").strip()
        low = href.lower()
        if not (".pdf" in low or "filestorage" in low or "user_management" in low):
            continue
        if not text:
            continue
        docs.append({"text": text, "href": href})

    mr_links = [d for d in docs if re.search(r"monitor", d["text"], re.I)]
    pdd_links = [d for d in docs if re.search(r"design document|pdd", d["text"], re.I)]
    validation_links = [d for d in docs if re.search(r"validation report", d["text"], re.I)]

    # Monitoring reports are published under "Requests for Issuance and related
    # documentation" and are labelled with the monitoring period, not the word
    # "monitoring". e.g. "01 Jan 2006 - 31 Dec 2006".
    period_re = re.compile(r"^\d{1,2} \w{3} \d{4}\s*-\s*\d{1,2} \w{3} \d{4}$")
    seen = set()
    for d in docs:
        if period_re.match(d["text"]) and d["href"] not in seen:
            seen.add(d["href"])
            mr_links.append({"text": d["text"], "href": d["href"], "kind": "monitoring_period"})
        elif re.search(r"Issuance request|Monitoring report", d["text"], re.I) and d["href"] not in seen:
            seen.add(d["href"])
            mr_links.append({"text": d["text"], "href": d["href"], "kind": "issuance"})

    periods = sorted({d["text"] for d in mr_links if d.get("kind") == "monitoring_period"})
    first_year = last_year = None
    for p in periods:
        yrs = re.findall(r"\b(19\d{2}|20\d{2})\b", p)
        if yrs:
            first_year = min(int(yrs[0]), first_year) if first_year else int(yrs[0])
            last_year = max(int(yrs[-1]), last_year) if last_year else int(yrs[-1])

    return {
        "host_parties": grab("host parties"),
        "sectoral_scopes": grab("sectoral scopes"),
        "activity_scale": grab("activity scale"),
        "methodologies": grab("methodologies used"),
        "amount_of_reductions": grab("amount of reductions"),
        "registration_date_page": grab("registration date"),
        "crediting_period": grab("crediting period"),
        "pdd_links": pdd_links,
        "validation_links": validation_links,
        "monitoring_report_links": mr_links,
        "monitoring_periods": periods,
        "first_monitoring_year": first_year,
        "last_monitoring_year": last_year,
        "all_documents": docs,
        "n_documents": len(docs),
        "n_monitoring_reports": len(seen),
    }


def scrape_details(df: pd.DataFrame, limit: int | None = None,
                   shard: int = 0, nshards: int = 1) -> pd.DataFrame:
    targets = df[(df["is_asia"]) & (df["landfill_class"].isin(["landfill_gas_candidate", "unclear"]))]
    if limit:
        targets = targets.head(limit)
    if nshards > 1:
        targets = targets.iloc[shard::nshards]
    print(f"project pages to fetch: {len(targets)} (shard {shard}/{nshards})")

    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        for i, (_, row) in enumerate(targets.iterrows(), 1):
            ref = row["ref"]
            cache = INDEX_DIR / f"project_{ref}.json"
            if cache.exists():
                detail = json.loads(cache.read_text())
            else:
                url = row["project_url"]
                if not isinstance(url, str) or not url.startswith("http"):
                    print(f"  {ref}: no project url")
                    continue
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                    page.wait_for_timeout(1200)
                    payload = page.evaluate(DETAIL_JS)
                    detail = parse_detail(payload["text"], payload["links"])
                    detail["ref"] = ref
                    detail["project_url"] = url
                    cache.write_text(json.dumps(detail, indent=1, ensure_ascii=False))
                except Exception as e:
                    print(f"  {ref}: ERROR {e}")
                    continue
                time.sleep(0.5)
            records.append({**row.to_dict(), **{
                k: detail.get(k) for k in (
                    "sectoral_scopes", "activity_scale", "methodologies",
                    "amount_of_reductions", "registration_date_page", "crediting_period",
                    "n_documents", "n_monitoring_reports",
                    "first_monitoring_year", "last_monitoring_year",
                )
            }, "pdd_download_url": (detail.get("pdd_links") or [{}])[0].get("href"),
               "monitoring_periods": "; ".join(detail.get("monitoring_periods") or []),
               "monitoring_report_urls": "; ".join(d["href"] for d in detail.get("monitoring_report_links") or [])})
            if i % 10 == 0:
                print(f"  {i}/{len(targets)} {ref} mr={detail.get('n_monitoring_reports')}")
        browser.close()

    return pd.DataFrame(records)


def rebuild_from_cache(list_csv: Path) -> pd.DataFrame:
    """Rebuild the Asia detail table from cached project JSON (no network)."""
    df = pd.read_csv(list_csv)
    # re-apply the current classifier so a tightened rule takes effect without a new scrape
    df["landfill_class"] = [classify(t, m) for t, m in
                            zip(df["title"].astype(str), df["methodology"].astype(str))]
    rows = []
    period_re = re.compile(r"^\d{1,2} \w{3} \d{4}\s*-\s*\d{1,2} \w{3} \d{4}$")
    for _, row in df.iterrows():
        cache = INDEX_DIR / f"project_{row['ref']}.json"
        if not cache.exists():
            continue
        detail = json.loads(cache.read_text())
        docs = detail.get("all_documents") or []
        periods = sorted({d["text"] for d in docs if period_re.match(d["text"] or "")})
        hrefs, seen = [], set()
        for d in docs:
            if period_re.match(d["text"] or "") and d["href"] not in seen:
                seen.add(d["href"])
                hrefs.append(d["href"])
        yrs = [int(y) for p in periods for y in re.findall(r"\b(19\d{2}|20\d{2})\b", p)]
        rows.append({**row.to_dict(), **{
            k: detail.get(k) for k in (
                "sectoral_scopes", "activity_scale", "methodologies",
                "amount_of_reductions", "registration_date_page", "crediting_period",
                "n_documents",
            )
        },
            "n_monitoring_reports": len(hrefs),
            "monitoring_periods": "; ".join(periods),
            "first_monitoring_year": min(yrs) if yrs else None,
            "last_monitoring_year": max(yrs) if yrs else None,
            "pdd_download_url": (detail.get("pdd_links") or [{}])[0].get("href"),
            "monitoring_report_urls": "; ".join(hrefs),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["list", "details", "reparse", "all"], default="all", nargs="?")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    args = ap.parse_args()

    list_csv = INTERIM / "cdm_projects_all.csv"
    if args.stage in ("list", "all") or not list_csv.exists():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA)
            page = ctx.new_page()
            df = scrape_list(page)
            browser.close()
        df.to_csv(list_csv, index=False)
        print(f"wrote {list_csv} ({len(df)} projects; {int(df['is_asia'].sum())} in Asia)")

    if args.stage in ("details", "all"):
        df = pd.read_csv(list_csv)
        det = scrape_details(df, limit=args.limit, shard=args.shard, nshards=args.nshards)
        if not det.empty:
            if args.nshards > 1:
                out = INTERIM / f"cdm_projects_asia.shard{args.shard}.csv"
            else:
                out = INTERIM / "cdm_projects_asia.csv"
            det.to_csv(out, index=False)
            print(f"wrote {out} ({len(det)} projects)")

    if args.stage == "reparse":
        out = INTERIM / "cdm_projects_asia.csv"
        det = rebuild_from_cache(list_csv)
        det.to_csv(out, index=False)
        print(f"reparsed {len(det)} cached project pages -> {out}")


if __name__ == "__main__":
    main()
