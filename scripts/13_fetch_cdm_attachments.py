#!/usr/bin/env python3
"""Fetch every catalogued CDM data attachment (appendices, ER sheets, IRRs).

Scope
-----
The project inventory contains 1,320 document links for the 108 master sites.
After removing boilerplate (glossary/approval/authorization/registration),
monitoring-period labels and PDD/validation reports, exactly **230 data
attachments across 94 CDM projects** remain.  This script fetches those 230.

Why a browser is required
-------------------------
UNFCCC FileStorage is behind Incapsula.  Plain HTTP clients receive a 212-byte
``text/html`` bot-wall with HTTP 200.  A real Chromium session that first warms
up on ``cdm.unfccc.int`` receives the Incapsula cookies, after which the file
can be fetched with the browser context's request API.

The cached URLs in ``document_inventory_all.csv`` are also **truncated** (20
characters instead of 32), so the downloader re-reads each live project page to
recover the full FileStorage links before downloading.

Outputs
-------
data/interim/cdm/attachment_catalogue.csv     one row per catalogued document
data/raw/cdm/attachments/<ref>/<slug>.<ext>   downloaded files (sniffed extension)
data/interim/cdm/attachment_download_log.csv  every attempt, including failures
data/interim/cdm/cdm_document_manifest.csv    merged manifest (existing + new)

Usage
-----
    python scripts/13_fetch_cdm_attachments.py --dry-run
    python scripts/13_fetch_cdm_attachments.py --limit 5
    python scripts/13_fetch_cdm_attachments.py --refs 1582 78 5466
    python scripts/13_fetch_cdm_attachments.py            # all 230, resumable
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA, INTERIM, RAW  # noqa: E402
from _file_sniff import (  # noqa: E402
    is_incapsula_challenge,
    sha256_bytes,
    sha256_file,
    sniff_bytes,
    sniff_file,
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

INTERIM_CDM = INTERIM / "cdm"
RAW_CDM = RAW / "cdm"
OUT_DIR = RAW_CDM / "attachments"
CATALOGUE = INTERIM_CDM / "attachment_catalogue.csv"
DOWNLOAD_LOG = INTERIM_CDM / "attachment_download_log.csv"
MANIFEST = INTERIM_CDM / "cdm_document_manifest.csv"
INVENTORY = INTERIM_CDM / "document_inventory_all.csv"
PROJECTS = INTERIM_CDM / "cdm_projects_asia.csv"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Labels that are project-page boilerplate, not data attachments.
BOILER = {
    "cdm glossary",
    "approval",
    "authorization",
    "registration request form",
    "list of interviewed persons",
    "list of documents",
    "explanation of taking due account of comments",
    "compilation of all comments received",
    "bundling form",
    "validation opinion on changes in pdd",
    "validation opinion",
    "validation report and protocol",
    "validation report of revised monitoring plan",
    "revised monitoring plan",
    "crediting period renewal form",
    "validation opinion on post-registration changes",
}
ATTACH_RE = re.compile(
    r"appendix|enclosure|er sheet|irr|benchmark|ef calculation|investment|financial",
    re.I,
)
PERIOD_RE = re.compile(
    r"^\d{1,2} [a-z]{3} \d{4} - \d{1,2} [a-z]{3} \d{4}$", re.I
)
# The one attachment already supplied manually (ref 1582, Appendix 2).
MANUAL_OVERRIDES = {
    ("1582", "appendix 2 - cdm landfill details"): Path(
        "data/raw/manual/cdm/1582/1582_appendix2_cdm_landfill_details.xls"
    )
}


def slug(text: str, limit: int = 70) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", text or "").strip("_")
    return (s[:limit] or "attachment").lower()


def norm_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def data_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(DATA.resolve()))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Catalogue construction
# ---------------------------------------------------------------------------
def reconcile_catalogue(cat: pd.DataFrame) -> pd.DataFrame:
    """Mark already-downloaded files as ``ok`` without touching the master list.

    Runs on every load so an interrupted/filtered run can resume safely: the
    catalogue is keyed by ``attachment_id`` and is never replaced by a filtered
    subset.
    """
    if not OUT_DIR.exists():
        return cat
    for i, row in cat.iterrows():
        if row.get("status") in {"ok", "manual"}:
            continue
        hits = sorted((OUT_DIR / str(row["ref"])).glob(f"{row['attachment_id']}_*"))
        hits = [h for h in hits if h.suffix.lower() not in {".part", ".download"}]
        if not hits:
            continue
        target = hits[0]
        info = sniff_file(target)
        cat.at[i, "status"] = "ok"
        cat.at[i, "file_path"] = data_rel(target)
        cat.at[i, "actual_format"] = info["format"]
        cat.at[i, "bytes"] = str(info["size"])
        cat.at[i, "sha256"] = sha256_file(target)
        cat.at[i, "notes"] = "reconciled from existing file"
    return cat


def build_catalogue(force: bool = False) -> pd.DataFrame:
    """Build the 230-row attachment catalogue from the document inventory."""
    if CATALOGUE.exists() and not force:
        return reconcile_catalogue(
            pd.read_csv(CATALOGUE, dtype=str, keep_default_na=False)
        )

    inv = pd.read_csv(INVENTORY, dtype=str, keep_default_na=False)
    inv = inv.drop_duplicates(["registry_ref", "url", "doc_text"]).copy()
    inv["lab"] = inv["doc_text"].str.lower().str.strip()

    mask = (
        (inv["doc_type"] == "other")
        & (~inv["lab"].isin(BOILER))
        & (~inv["lab"].str.match(PERIOD_RE))
        & (inv["lab"].str.contains(ATTACH_RE, regex=True))
    )
    cat = inv[mask].copy()
    cat = cat.sort_values(["registry_ref", "doc_text"]).reset_index(drop=True)

    projects = pd.read_csv(PROJECTS, dtype=str, keep_default_na=False)
    proj = projects.set_index(projects["ref"].astype(str))["project_url"].to_dict()

    rows = []
    for i, r in cat.iterrows():
        ref = str(r["registry_ref"])
        label = str(r["doc_text"]).strip()
        manual = MANUAL_OVERRIDES.get((ref, label.lower()))
        status = "manual" if manual else "pending"
        rows.append(
            {
                "attachment_id": f"ATT-{i + 1:04d}",
                "ref": ref,
                "landfill_id": r["landfill_id"],
                "evidence_tier": r["evidence_tier"],
                "label": label,
                "url_cached": r["url"],
                "project_url": proj.get(ref, ""),
                "status": status,
                "file_path": str(manual) if manual else "",
                "actual_format": "xls" if manual else "",
                "sha256": "",
                "bytes": str(manual.stat().st_size) if manual and manual.exists() else "",
                "http_status": "",
                "downloaded_at": "",
                "notes": "supplied manually" if manual else "",
            }
        )

    cat = pd.DataFrame(rows)
    cat = reconcile_catalogue(cat)
    CATALOGUE.parent.mkdir(parents=True, exist_ok=True)
    cat.to_csv(CATALOGUE, index=False, lineterminator="\n")
    print(f"catalogue: {len(cat)} attachments across {cat['ref'].nunique()} projects -> {CATALOGUE}")
    return cat


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------
def warm_up(page) -> None:
    """Visit the CDM home page so Incapsula sets its cookies."""
    try:
        page.goto("https://cdm.unfccc.int/", wait_until="domcontentloaded", timeout=60_000)
    except Exception:
        pass
    page.wait_for_timeout(6_000)


def load_project_links(page, project_url: str) -> list[dict]:
    """Load a live project page and return its FileStorage links."""
    for attempt in range(3):
        try:
            page.goto(project_url, wait_until="domcontentloaded", timeout=90_000)
        except Exception:
            pass
        # The page is wrapped in an Incapsula iframe until the cookie is ready.
        for _ in range(10):
            page.wait_for_timeout(1_500)
            title = page.title() or ""
            if title.startswith("CDM:"):
                break
        if (page.title() or "").startswith("CDM:"):
            break
        page.wait_for_timeout(2_000)

    try:
        links = page.eval_on_selector_all(
            "a",
            "els => els.map(e => ({text: (e.innerText || '').trim(), href: e.href}))",
        )
    except Exception:
        return []
    return [
        {"text": x.get("text", ""), "href": x.get("href", "")}
        for x in links
        if "filestorage" in (x.get("href", "") or "").lower()
    ]


def match_link(label: str, links: list[dict]) -> dict | None:
    """Match a catalogue label to a live project-page link."""
    target = norm_label(label)
    if not target:
        return None
    scored: list[tuple[float, dict]] = []
    for link in links:
        candidate = norm_label(link["text"])
        if not candidate:
            continue
        if candidate == target:
            return link
        if target in candidate or candidate in target:
            scored.append((0.99, link))
            continue
        ratio = difflib.SequenceMatcher(None, target, candidate).ratio()
        if ratio >= 0.82:
            scored.append((ratio, link))
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    return None


def pdf_pages(path: Path) -> int | None:
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(str(path)))
    except Exception:
        return None


def _save_bytes(data: bytes, stem: Path, fmt_info: dict) -> Path:
    ext = fmt_info.get("extension", ".bin")
    target = stem.with_suffix(ext)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    part.write_bytes(data)
    part.replace(target)
    return target


def fetch_one(context, page, url: str, stem: Path) -> dict:
    """Fetch one FileStorage URL, preferring the cookie-bearing request API.

    Returns ``{status, http_status, data, format, method, message}``.
    """
    result = {
        "status": "download_failed",
        "http_status": "",
        "data": b"",
        "format": "",
        "method": "",
        "message": "",
    }

    # 1) Fast path: browser-context request (shares Incapsula cookies).
    try:
        resp = context.request.get(url, timeout=120_000)
        body = resp.body()
        result["http_status"] = str(resp.status)
        if resp.status == 200 and body and not is_incapsula_challenge(body):
            info = sniff_bytes(body)
            if info["format"] not in {"html", "unknown"}:
                result.update(
                    status="ok", data=body, format=info["format"], method="context.request"
                )
                return result
            result["message"] = f"unexpected format {info['format']}"
        elif is_incapsula_challenge(body):
            result["message"] = "incapsula challenge on request"
        else:
            result["message"] = f"http {resp.status}"
    except Exception as exc:  # pragma: no cover - network variability
        result["message"] = f"request error: {str(exc)[:160]}"

    # 2) Slow path: trigger a real browser download.
    tmp = stem.with_suffix(".download")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        with page.expect_download(timeout=60_000) as dl_info:
            try:
                page.goto(url, timeout=60_000)
            except Exception as exc:
                if "Download is starting" not in str(exc):
                    raise
        dl = dl_info.value
        dl.save_as(str(tmp))
        data = tmp.read_bytes()
        tmp.unlink(missing_ok=True)
        if data and not is_incapsula_challenge(data):
            info = sniff_bytes(data)
            if info["format"] not in {"html", "unknown"}:
                result.update(
                    status="ok",
                    data=data,
                    format=info["format"],
                    method="browser_download",
                )
                return result
            result["message"] = f"unexpected format {info['format']}"
        else:
            result["message"] = "incapsula challenge on download"
    except Exception as exc:  # pragma: no cover
        result["message"] = (result["message"] + " | " if result["message"] else "") + (
            f"download error: {str(exc)[:160]}"
        )
    tmp.unlink(missing_ok=True)
    return result


def append_log(rows: list[dict]) -> None:
    if not rows:
        return
    new = pd.DataFrame(rows)
    if DOWNLOAD_LOG.exists():
        old = pd.read_csv(DOWNLOAD_LOG, dtype=str, keep_default_na=False)
        new = pd.concat([old, new], ignore_index=True)
    new.to_csv(DOWNLOAD_LOG, index=False, lineterminator="\n")


def update_manifest(ref: str, label: str, url: str, path: Path, fmt: str, data: bytes) -> None:
    """Upsert one successful download into the shared CDM document manifest."""
    row = {
        "ref": ref,
        "doc_type": "attachment",
        "label": label,
        "path": data_rel(path),
        "bytes": path.stat().st_size,
        "pages": pdf_pages(path) if fmt == "pdf" else None,
        "sha256_16": sha256_bytes(data)[:16],
        "actual_format": fmt,
        "sha256": sha256_bytes(data),
        "http_status": "200",
        "source": "live_project_page",
        "downloaded_at": utc_now(),
        "url": url,
        "notes": "",
    }
    new = pd.DataFrame([row])
    if MANIFEST.exists():
        old = pd.read_csv(MANIFEST, dtype=str, keep_default_na=False)
        new = pd.concat([old, new], ignore_index=True)
        subset = ["ref", "doc_type", "url"]
        new = new.drop_duplicates(subset=subset, keep="last")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(MANIFEST, index=False, lineterminator="\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refs", nargs="*", help="only these CDM refs")
    ap.add_argument("--limit", type=int, help="process at most N pending attachments")
    ap.add_argument("--rebuild-catalogue", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="list work without downloading")
    ap.add_argument("--sleep", type=float, default=0.8, help="base sleep between downloads")
    args = ap.parse_args()

    # ``cat`` is always the full 230-row catalogue.  Filtering only affects the
    # work queue, never the persisted status table (a filtered run must not
    # shrink the catalogue).
    cat = build_catalogue(force=args.rebuild_catalogue)
    cat["status"] = cat["status"].fillna("pending")

    pending_mask = ~cat["status"].isin({"ok", "manual"})
    work = cat[pending_mask].copy()
    if args.refs:
        wanted = {str(r) for r in args.refs}
        work = work[work["ref"].astype(str).isin(wanted)].copy()
    if args.limit:
        work = work.head(args.limit)

    print(f"catalogue rows: {len(cat)} | pending: {len(work)} | refs: {work['ref'].nunique()}")
    if args.dry_run:
        print(work[["attachment_id", "ref", "landfill_id", "label", "project_url"]].to_string(index=False))
        return
    if work.empty:
        print("nothing to do")
        return
    if sync_playwright is None:
        raise SystemExit("playwright is not installed; run: pip install playwright && playwright install chromium")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_rows: list[dict] = []
    status_updates: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent=UA,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            accept_downloads=True,
        )
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = context.new_page()
        warm_up(page)

        for ref, group in work.groupby("ref", sort=False):
            project_url = group["project_url"].iloc[0]
            if not project_url:
                for aid in group["attachment_id"]:
                    status_updates[aid] = {"status": "no_project_url", "notes": "missing project_url"}
                continue

            print(f"\n[{ref}] {len(group)} attachment(s) | {project_url}")
            links = load_project_links(page, project_url)
            print(f"    live links: {len(links)} FileStorage")

            for _, row in group.iterrows():
                aid = row["attachment_id"]
                label = row["label"]
                link = match_link(label, links)
                if not link:
                    print(f"  - {aid} NO LIVE LINK: {label[:70]}")
                    status_updates[aid] = {
                        "status": "no_live_link",
                        "notes": "label not found on live project page",
                    }
                    log_rows.append(
                        {
                            "attachment_id": aid,
                            "ref": ref,
                            "label": label,
                            "url": "",
                            "status": "no_live_link",
                            "http_status": "",
                            "actual_format": "",
                            "bytes": "",
                            "sha256": "",
                            "method": "",
                            "message": "label not found on live project page",
                            "logged_at": utc_now(),
                        }
                    )
                    continue

                url = link["href"]
                stem = OUT_DIR / str(ref) / f"{aid}_{slug(label)}"
                info = fetch_one(context, page, url, stem)

                if info["status"] != "ok":
                    print(f"  - {aid} {info['status']}: {label[:60]} ({info['message'][:60]})")
                    status_updates[aid] = {
                        "status": info["status"],
                        "http_status": info["http_status"],
                        "notes": info["message"][:250],
                    }
                    log_rows.append(
                        {
                            "attachment_id": aid,
                            "ref": ref,
                            "label": label,
                            "url": url,
                            "status": info["status"],
                            "http_status": info["http_status"],
                            "actual_format": info["format"],
                            "bytes": "",
                            "sha256": "",
                            "method": info["method"],
                            "message": info["message"][:250],
                            "logged_at": utc_now(),
                        }
                    )
                    time.sleep(random.uniform(args.sleep, args.sleep + 0.6))
                    continue

                data = info["data"]
                fmt_info = sniff_bytes(data)
                target = _save_bytes(data, stem, fmt_info)
                digest = sha256_bytes(data)
                update_manifest(str(ref), label, url, target, info["format"], data)

                print(
                    f"  + {aid} ok {info['format']} {len(data) // 1024} KB -> {target.name}"
                )
                status_updates[aid] = {
                    "status": "ok",
                    "file_path": data_rel(target),
                    "actual_format": info["format"],
                    "sha256": digest,
                    "bytes": str(len(data)),
                    "http_status": info["http_status"],
                    "downloaded_at": utc_now(),
                    "notes": f"method={info['method']}",
                }
                log_rows.append(
                    {
                        "attachment_id": aid,
                        "ref": ref,
                        "label": label,
                        "url": url,
                        "status": "ok",
                        "http_status": info["http_status"],
                        "actual_format": info["format"],
                        "bytes": str(len(data)),
                        "sha256": digest,
                        "method": info["method"],
                        "message": "",
                        "logged_at": utc_now(),
                    }
                )
                time.sleep(random.uniform(args.sleep, args.sleep + 0.7))

            time.sleep(random.uniform(0.8, 1.5))

        browser.close()

    # Persist catalogue status (resumable).
    for aid, updates in status_updates.items():
        idx = cat.index[cat["attachment_id"] == aid]
        for col, val in updates.items():
            if col not in cat.columns:
                cat[col] = ""
            cat.loc[idx, col] = val
    cat.to_csv(CATALOGUE, index=False, lineterminator="\n")
    append_log(log_rows)

    ok = sum(1 for x in status_updates.values() if x.get("status") == "ok")
    print(f"\ndone: {ok} downloaded, {len(status_updates) - ok} unresolved")
    print(f"catalogue: {CATALOGUE}")
    print(f"log:       {DOWNLOAD_LOG}")


if __name__ == "__main__":
    main()
