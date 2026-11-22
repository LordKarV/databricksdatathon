"""Export what the live website check needs at run time (issue #37), so the app needs no pandas or repo code.

Writes app/verify/out/sites.json.gz ({unique_id: {name, city, urls}}; official and official-like URLs from
derived/v1/source_urls.parquet, home pages first, at most 5) and app/verify/out/lexicon.json (service patterns
and non-offer cues from cleaning/claims/lexicon.py, as plain `re` strings). Run from the repo root:
    .venv-app/bin/python app/verify/build_sites.py
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
# App service id -> lexicon key (cleaning/claims/lexicon.py)
APP_TO_LEXICON = {"burn_care": "burns", "cardiac_surgery": "cardiac_surgery", "dialysis": "dialysis",
                  "emergency_csection": "csection", "mri": "mri", "nicu": "nicu", "trauma_emergency": "trauma"}
MAX_URLS = 5


def load_lexicon() -> dict:
    sys.path[:0] = [str(ROOT / "audit" / "claims"), str(ROOT / "cleaning" / "claims")]
    import lexicon as lx  # noqa: PLC0415  (repo-relative import; lexicon.py's own absolute path is another machine)

    services = {}
    for app_id, key in APP_TO_LEXICON.items():
        spec = lx.SERVICES[key]
        services[app_id] = {"core": spec["core"].pattern,
                            "exclude": spec["exclude"].pattern if spec.get("exclude") is not None else None}
    return {"services": services, "nonoffer": {k: lx.CUES[k].pattern for k in lx.NONOFFER},
            "source": "cleaning/claims/lexicon.py"}


def path_rank(url: str) -> tuple[int, int]:
    p = urlsplit(url).path.strip("/")
    return (0 if not p else 1, len(p))


def load_sites() -> dict:
    urls = pd.read_parquet(ROOT / "derived/v1/source_urls.parquet", columns=["unique_id", "url", "source_class"])
    urls = urls[urls.source_class.isin(["official", "official_like"]) & urls.url.str.match(r"https?://")]
    urls = (urls.assign(rank=urls.url.map(path_rank)).sort_values(["unique_id", "rank"])
            .drop_duplicates(["unique_id", "url"]))
    fac = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "name", "address_city"])
    fac = fac.set_index("unique_id")
    out = {}
    for uid, g in urls.groupby("unique_id", sort=False):
        if uid not in fac.index:
            continue
        row = fac.loc[uid]
        out[uid] = {"name": row["name"], "city": row["address_city"] if isinstance(row["address_city"], str) else None,
                    "urls": g.url.head(MAX_URLS).tolist()}
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    sites = load_sites()
    (OUT / "sites.json.gz").write_bytes(gzip.compress(json.dumps(sites, separators=(",", ":")).encode(), 9))
    (OUT / "lexicon.json").write_text(json.dumps(load_lexicon(), indent=1))
    print(f"{len(sites)} facilities with an official website; sites.json.gz {(OUT / 'sites.json.gz').stat().st_size} B")


if __name__ == "__main__":
    main()
