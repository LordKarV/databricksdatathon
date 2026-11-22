"""Shared paths, loaders and the registrable-domain helper for the source-scoring pipeline.

Reuses the audit helpers (audit/provenance domains.py, q1_sources.url_kind, common.facilities) instead of
copying them. Local snapshot only; no warehouse queries.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(os.environ.get("DATATHON_ROOT", Path(__file__).resolve().parents[2]))
RAW = Path(os.environ.get("DATATHON_DATA_ROOT", ROOT / "data")) / "raw"
OUT = ROOT / "derived/v1"
WORK = OUT / "_work"  # intermediate tables, removed by package.py
HERE = Path(__file__).resolve().parent
BUILD_DATE = "2026-11-21"
VERSION = "source_scoring 0.1"

sys.path.insert(0, str(ROOT / "audit/provenance"))
from common import facilities as _prov_facilities  # noqa: E402
from common import host, jlist  # noqa: E402,F401
from domains import classify  # noqa: E402,F401
from q1_sources import official_hosts, url_kind  # noqa: E402,F401

# ponytail: hand-written public-suffix subset covering the hosts seen in source_urls (Indian second-level
# suffixes plus a few foreign ones). Swap for the full Public Suffix List if foreign hosts start to matter.
TWO_LEVEL_SUFFIXES = {
    "co.in", "gov.in", "nic.in", "ac.in", "org.in", "net.in", "edu.in", "res.in", "ernet.in", "firm.in",
    "gen.in", "ind.in", "mil.in", "co.uk", "ac.uk", "org.uk", "gov.uk", "nhs.uk", "com.au", "org.au", "gov.au",
    "co.za", "com.sg", "com.my", "com.pk", "com.bd", "com.np", "co.jp", "com.br", "co.nz", "com.cn", "org.cn",
    "ac.jp", "edu.au", "com.tr", "com.mx", "co.id", "com.ph", "ac.za", "gov.bd", "edu.pk", "com.ng",
}
# hosts under these are separate publishers (each blog / site is its own source)
PRIVATE_SUFFIXES = {"blogspot.com", "wordpress.com", "wixsite.com", "business.site", "github.io"}


def registrable_domain(h: str) -> str:
    """Host -> registrable domain ('pmc.ncbi.nlm.nih.gov' -> 'nih.gov', 'jalandhar.nic.in' stays)."""
    h = (h or "").strip(".").lower()
    if h.startswith("www."):
        h = h[4:]
    parts = [p for p in h.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if ".".join(parts[-2:]) in TWO_LEVEL_SUFFIXES | PRIVATE_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def facilities() -> pd.DataFrame:
    """9,959 records: well-formed rows (UUID id, source='kie') minus 11 byte-identical duplicates."""
    return _prov_facilities()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    assert registrable_domain("pmc.ncbi.nlm.nih.gov") == "nih.gov"
    assert registrable_domain("jalandhar.nic.in") == "jalandhar.nic.in"
    assert registrable_domain("www.practo.com") == "practo.com"
    assert registrable_domain("abc.co.in") == "abc.co.in"
    assert registrable_domain("x.blogspot.com") == "x.blogspot.com"
    print("ss_common.py self-check ok")
