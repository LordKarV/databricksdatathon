"""Parse raw NABH pages into parquet tables.

Usage: python -I parse.py DATA_DIR
Reads DATA_DIR/raw/all/*.json.gz and DATA_DIR/raw/spec_<CODE>/*.json.gz.
Writes DATA_DIR/nabh_hco.parquet (one row per listed card) and
DATA_DIR/nabh_hco_specialty.parquet (acc_no, spec_code) when spec pages exist.
Phone numbers are deliberately not kept (small clinics often list a personal mobile).
"""
import gzip
import html
import json
import re
import sys
from pathlib import Path

import pandas as pd

PIN_RE = re.compile(r"(\d{6})\s*$")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.S)
    return clean(m.group(1)) if m else ""


def parse_card(c: str) -> dict:
    col1 = first(r'hs-col-1">(.*?)</div>', c)
    addr = first(r'hs-col-2">(.*?)</div>', c)
    col4 = re.search(r'hs-col-4">\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', c, re.S)
    web = re.search(r'href="([^"]+)"[^>]*>\s*Visit Website', c)
    badge = re.search(r'badge-icon badge-icon-([a-z-]+)\s*(?:nomen-([A-Za-z0-9-]+))?', c)
    cert_url = html.unescape(col4.group(1)).split("?")[0] if col4 else ""  # drop S3 signatures
    pin = PIN_RE.search(addr)
    parts = [p.strip() for p in PIN_RE.sub("", addr).split(",") if p.strip() and p.strip().lower() != "india"]
    return {
        "name": col1,
        "address": addr,
        "pin": pin.group(1) if pin else None,
        # ponytail: tail-of-address split; the site appends ", City, State, PIN" to most rows
        "addr_state": parts[-1] if pin and parts else None,
        "addr_city": parts[-2] if pin and len(parts) >= 2 else None,
        "acc_no": clean(col4.group(2)) if col4 else "",
        "cert_url": cert_url,
        "website": html.unescape(web.group(1)) if web else None,
        "status": first(r'certification-icon">(.*?)</span>', c)
        or first(r'accreditation-remarks">\s*(\w+(?: \w+)?) on', c) or None,
        "remarks": first(r'accreditation-remarks">(.*?)</div>', c) or None,
        "badge_class": badge.group(1) if badge else None,
        "nomen": badge.group(2) if badge and badge.group(2) else None,
    }


def parse_page(path: Path) -> list:
    d = json.loads(gzip.decompress(path.read_bytes()))
    geo = {}
    for m in d.get("mapData") or []:
        geo.setdefault((clean(m.get("name")), clean(m.get("address"))), (m.get("lat"), m.get("lng")))
    rows = []
    for i, c in enumerate(d["html"].split("card organisation-list")[1:]):
        r = parse_card(c)
        lat, lng = geo.get((r["name"], r["address"]), (None, None))
        rows.append({**r, "lat": lat, "lng": lng, "page": int(path.stem.split("_")[1].split(".")[0]), "pos": i})
    return rows


def main(data_dir: str) -> None:
    base = Path(data_dir)
    rows = [r for p in sorted((base / "raw" / "all").glob("page_*.json.gz")) for r in parse_page(p)]
    df = pd.DataFrame(rows)
    df["prefix"] = df["acc_no"].str.extract(r"^([A-Za-z]+)", expand=False).str.upper()
    df.to_parquet(base / "nabh_hco.parquet", index=False)
    print("nabh_hco rows", len(df))
    spec = []
    for d in sorted((base / "raw").glob("spec_*")):
        code = d.name[len("spec_"):]
        pages = sorted(d.glob("page_*.json.gz"))
        want = json.loads(gzip.decompress(pages[0].read_bytes()))["pagination"]["total_pages"] if pages else 0
        if not pages or len(pages) < want:
            print(f"skip {code}: {len(pages)}/{want} pages (incomplete)")
            continue
        for p in pages:
            spec += [{"acc_no": r["acc_no"], "name": r["name"], "address": r["address"], "spec_code": code}
                     for r in parse_page(p)]
    if spec:
        sdf = pd.DataFrame(spec).drop_duplicates()
        sdf.to_parquet(base / "nabh_hco_specialty.parquet", index=False)
        print("nabh_hco_specialty rows", len(sdf), sdf.spec_code.value_counts().to_dict())


if __name__ == "__main__":
    main(sys.argv[1])
