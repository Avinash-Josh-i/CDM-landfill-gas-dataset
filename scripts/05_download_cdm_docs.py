"""Download PDD and monitoring-report PDFs for discovered CDM landfill-gas projects.

UNFCCC FileStorage URLs are protected by Incapsula: plain ``requests``/``curl`` calls return
a bot-challenge stub. A real Chromium session (Playwright) that first visits the CDM site
receives a downloadable PDF, so every file is fetched through a browser download event.

Usage:
    python scripts/05_download_cdm_docs.py                 # all projects with documents
    python scripts/05_download_cdm_docs.py --refs 78 124   # specific projects
    python scripts/05_download_cdm_docs.py --min-reports 1 --limit 50
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA, RAW

INTERIM = DATA / "interim" / "cdm"
RAW_CDM = RAW / "cdm"
PDD_DIR = RAW_CDM / "pdd"
MR_DIR = RAW_CDM / "mr"
MANIFEST = INTERIM / "cdm_document_manifest.csv"
PDD_DIR.mkdir(parents=True, exist_ok=True)
MR_DIR.mkdir(parents=True, exist_ok=True)
INTERIM.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def slug(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_")
    return s[:60] or "doc"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def pdf_pages(path: Path) -> int | None:
    try:
        import pypdfium2 as pdfium  # optional fast check
        pdf = pdfium.PdfDocument(str(path))
        return len(pdf)
    except Exception:
        pass
    try:
        with path.open("rb") as fh:
            data = fh.read()
        return len(re.findall(rb"/Type\s*/Page[^s]", data)) or None
    except Exception:
        return None


def download(page, url: str, target: Path, timeout: int = 90_000) -> bool:
    """Fetch one FileStorage URL through the browser download pipeline."""
    if target.exists() and target.stat().st_size > 1024:
        return True
    box: list[str] = []

    def on_download(d):
        try:
            d.save_as(str(target))
            box.append(d.suggested_filename or target.name)
        except Exception as e:  # pragma: no cover - browser-level failure
            box.append(f"ERR {e}")

    page.once("download", on_download)
    try:
        page.goto(url, timeout=timeout)
    except Exception as e:
        if "Download is starting" not in str(e):
            page.remove_listener("download", on_download)
            print(f"    goto failed: {str(e).splitlines()[0]}")
            return False
    # give the browser time to flush the file
    for _ in range(30):
        if box:
            break
        page.wait_for_timeout(500)
    page.remove_listener("download", on_download)
    if not target.exists() or target.stat().st_size < 1024:
        return False
    head = target.read_bytes()[:5]
    if head != b"%PDF-":
        target.unlink(missing_ok=True)
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", nargs="*", type=int)
    ap.add_argument("--min-reports", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--include-pdd", action="store_true", default=True)
    args = ap.parse_args()

    src = INTERIM / "cdm_projects_asia.csv"
    if not src.exists():
        raise SystemExit("Run scripts/04_cdm_discover.py details first.")
    df = pd.read_csv(src)
    df["n_monitoring_reports"] = pd.to_numeric(df.get("n_monitoring_reports"), errors="coerce").fillna(0).astype(int)

    if args.refs:
        df = df[df["ref"].astype(int).isin(args.refs)]
    else:
        df = df[df["n_monitoring_reports"] >= args.min_reports]
        df = df.sort_values(["n_monitoring_reports", "last_monitoring_year"], ascending=False)

    if args.limit:
        df = df.head(args.limit)
    print(f"projects to process: {len(df)}")

    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, accept_downloads=True)
        page = ctx.new_page()
        page.goto("https://cdm.unfccc.int/Projects/projsearch.html",
                  wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(2000)

        for i, (_, row) in enumerate(df.iterrows(), 1):
            ref = int(row["ref"])
            print(f"[{i}/{len(df)}] {ref} {str(row['title'])[:70]} | MRs={row['n_monitoring_reports']}")

            if args.include_pdd and isinstance(row.get("pdd_download_url"), str):
                target = PDD_DIR / f"{ref}_pdd.pdf"
                ok = download(page, row["pdd_download_url"], target)
                if ok:
                    rows.append({
                        "ref": ref, "doc_type": "pdd", "label": "project design document",
                        "path": str(target.relative_to(RAW_CDM.parent.parent)), "bytes": target.stat().st_size,
                        "pages": pdf_pages(target), "sha256_16": sha256(target),
                        "url": row["pdd_download_url"],
                    })
                    print(f"    pdd ok ({target.stat().st_size//1024} KB)")
                else:
                    print("    pdd FAILED")

            urls = str(row.get("monitoring_report_urls") or "")
            periods = str(row.get("monitoring_periods") or "").split("; ")
            urls = [u for u in urls.split("; ") if u.startswith("http")]
            proj_dir = MR_DIR / str(ref)
            proj_dir.mkdir(parents=True, exist_ok=True)
            for j, url in enumerate(urls):
                label = periods[j] if j < len(periods) and periods[j] else f"mr_{j+1}"
                target = proj_dir / f"{slug(label)}.pdf"
                ok = download(page, url, target)
                if ok:
                    rows.append({
                        "ref": ref, "doc_type": "monitoring_report", "label": label,
                        "path": str(target.relative_to(RAW_CDM.parent.parent)), "bytes": target.stat().st_size,
                        "pages": pdf_pages(target), "sha256_16": sha256(target), "url": url,
                    })
                    print(f"    mr ok  {label} ({target.stat().st_size//1024} KB)")
                else:
                    print(f"    mr FAILED {label}")
                time.sleep(0.4)
            time.sleep(0.4)

        browser.close()

    if rows:
        new = pd.DataFrame(rows)
        if MANIFEST.exists():
            old = pd.read_csv(MANIFEST)
            new = pd.concat([old, new], ignore_index=True).drop_duplicates(
                subset=["ref", "doc_type", "path"], keep="last")
        new.to_csv(MANIFEST, index=False)
        print(f"\nmanifest: {MANIFEST} ({len(new)} documents)")


if __name__ == "__main__":
    main()
