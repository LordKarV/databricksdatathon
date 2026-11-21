"""Fetch the LGD geography subset from the ramSeraph open-data mirror.

Usage: python -I fetch.py <out_dir>

Reads the live JSON index, downloads the current daily Parquet file for each
dataset in WANTED, verifies its sha256 against the index, and writes
<dataset>.parquet plus metadata.json and fetch_log.json into out_dir.
Re-runnable: a file whose sha256 already matches is skipped.
"""
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

INDEX_URL = "https://ramseraph.github.io/opendata/lgd/data/metadata.json"
WANTED = [
    "states", "districts", "subdistricts", "blocks", "villages",
    "pincode_villages", "pincode_urban", "urban_local_bodies", "statewise_ulbs_coverage",
]
MAX_BYTES = 300 * 1024 * 1024
HEADERS = {"User-Agent": "datathon-research-client"}
PAUSE_S = 1.0  # polite: about 1 request per second


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = get(INDEX_URL)
    (out_dir / "metadata.json").write_bytes(raw)
    index = json.loads(raw)
    log = {"index_url": INDEX_URL, "published_at": index.get("published_at"), "files": []}
    for name in WANTED:
        daily = index["datasets"][name]["daily"]
        f = daily["file"]
        if f["size"] > MAX_BYTES:
            raise SystemExit(f"{name}: {f['size']} bytes exceeds cap, fetch a subset instead")
        dest = out_dir / f"{name}.parquet"
        if dest.exists() and sha256(dest.read_bytes()) == f["sha256"]:
            status = "cached"
        else:
            time.sleep(PAUSE_S)
            body = get(f["url"])
            if sha256(body) != f["sha256"]:
                raise SystemExit(f"{name}: sha256 mismatch for {f['url']}")
            dest.write_bytes(body)
            status = "downloaded"
        log["files"].append({"dataset": name, "url": f["url"], "sha256": f["sha256"],
                             "bytes": f["size"], "rows": daily["rows"],
                             "observed_on": daily["observed_on"], "status": status})
        print(name, status, f["size"], daily["rows"], daily["observed_on"])
    (out_dir / "fetch_log.json").write_text(json.dumps(log, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
