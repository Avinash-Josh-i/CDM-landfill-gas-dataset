"""Magic-byte file sniffing shared by the CDM downloader and Excel ingest.

The UNFCCC FileStorage endpoint sometimes returns a 212-byte Incapsula challenge
with ``Content-Type: text/html`` and HTTP 200.  Extension-based detection is
therefore unsafe.  Everything here inspects the bytes (and, for ZIP/OLE2, the
container entries) instead of trusting the URL or the server headers.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path

OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

# Extension assigned to each sniffed format.  ``ole``/``zip`` are deliberately
# generic because we only use them when the container cannot be identified.
EXTENSIONS = {
    "pdf": ".pdf",
    "xls": ".xls",
    "doc": ".doc",
    "ppt": ".ppt",
    "xlsx": ".xlsx",
    "docx": ".docx",
    "pptx": ".pptx",
    "zip": ".zip",
    "html": ".html",
    "text": ".txt",
    "rtf": ".rtf",
    "ole": ".ole",
    "encrypted_ooxml": ".ole",
    "unknown": ".bin",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ole_stream_name(data: bytes) -> str | None:
    """Identify an OLE2 container by probing its directory stream names.

    OLE2 directory entry names are UTF-16LE, so both the ASCII and UTF-16LE
    encodings are checked (``strings -el`` shows them as plain text).
    """
    # Password-protected OOXML workbooks are OLE2 wrappers around an
    # ``EncryptedPackage`` stream; they cannot be parsed without the password.
    if b"EncryptedPackage" in data or "EncryptedPackage".encode("utf-16-le") in data:
        return "encrypted_ooxml"
    for name, fmt in (
        (b"Workbook", "xls"),
        (b"Book", "xls"),
        (b"WordDocument", "doc"),
        (b"PowerPoint Document", "ppt"),
    ):
        if name in data or name.decode("ascii").encode("utf-16-le") in data:
            return fmt
    return None


def _zip_kind(path: str | Path | None, data: bytes) -> str:
    """Identify a ZIP container.  ``path`` is preferred; bytes are a fallback."""
    source = path if path is not None else io.BytesIO(data)
    try:
        with zipfile.ZipFile(source) as zf:
            names = set(zf.namelist())
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        return "zip"
    except Exception:
        pass
    # Without a seekable file, probe the first local-file header name.
    m = re.search(rb"PK\x03\x04.{22}([^\x00]{1,120})", data[:4096], re.S)
    if m:
        name = m.group(1).decode("latin-1", "ignore").lower()
        if name.startswith("xl/"):
            return "xlsx"
        if name.startswith("word/"):
            return "docx"
        if name.startswith("ppt/"):
            return "pptx"
    return "zip"


def is_incapsula_challenge(data: bytes) -> bool:
    """Return True for the tiny Incapsula / bot-wall HTML shell.

    The live shell is 212 bytes and contains ``_Incapsula_Resource``.  We also
    reject any small HTML page, because a real attachment is never HTML.
    """
    if not data:
        return False
    low = data[:4096].lower()
    if b"_incapsula_resource" in low or b"incapsula" in low:
        return True
    head = low.lstrip()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        # Small HTML = challenge / error shell.  Large HTML is still not a
        # valid attachment, but is reported as ``html`` rather than challenge.
        return len(data) <= 8192
    return False


def sniff_bytes(data: bytes, path: str | Path | None = None) -> dict:
    """Sniff ``data`` and return ``{format, extension, size, ...}``.

    ``path`` is optional but improves ZIP subtype detection (XLSX vs DOCX).
    """
    size = len(data)
    head = data[:16]
    fmt = "unknown"

    if head.startswith(b"%PDF"):
        fmt = "pdf"
    elif head.startswith(OLE2_MAGIC):
        fmt = _ole_stream_name(data) or "ole"
    elif head.startswith(ZIP_MAGICS):
        fmt = _zip_kind(path, data)
    elif head.startswith(b"{\\rtf"):
        fmt = "rtf"
    else:
        low = data[:4096].lstrip().lower()
        if low.startswith(b"<!doctype html") or low.startswith(b"<html"):
            fmt = "html"
        else:
            sample = data[:8192]
            if sample:
                printable = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b <= 126)
                if printable / len(sample) > 0.90:
                    fmt = "text"

    return {
        "format": fmt,
        "extension": EXTENSIONS.get(fmt, ".bin"),
        "size": size,
        "is_incapsula": is_incapsula_challenge(data),
        "is_tabular": fmt in {"xls", "xlsx"},
        "is_pdf": fmt == "pdf",
        "magic_hex": head.hex(),
    }


def sniff_file(path: str | Path) -> dict:
    """Sniff a file on disk, reading only what is needed for the container."""
    p = Path(path)
    size = p.stat().st_size
    with p.open("rb") as fh:
        head = fh.read(16)
        if head.startswith(OLE2_MAGIC):
            # OLE2 directory entries can live anywhere in the file (and their
            # names are UTF-16LE), so inspect the whole container.
            fh.seek(0)
            data = fh.read()
        else:
            data = head
    if head.startswith(ZIP_MAGICS):
        info = sniff_bytes(head, path=p)
    else:
        info = sniff_bytes(data, path=p)
    info["size"] = size
    return info
