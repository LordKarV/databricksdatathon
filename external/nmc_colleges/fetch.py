"""Fetch the NMC MBBS college list and per-college course detail.

Usage: python -I fetch.py <out_dir>

Writes <out_dir>/list.json (all MBBS list rows) and <out_dir>/details.jsonl
(one detail record per college_id). Resumable: college_ids already present
in details.jsonl are skipped. Polite: 1.1 s between requests.
Contact fields (email, mobile, landline, fax, contacts) are dropped before
saving; we have no use for them and some are personal addresses.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://nmc.org.in/college-courses"
HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "datathon-research-client/0.1",
}
DELAY_S = 1.1
PER_PAGE = 100
DROP = {"email", "mobile", "landline", "fax", "contacts"}


def get(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.loads(r.read().decode("utf-8"))
            if not body.get("success"):
                raise ValueError(f"success=false for {url}")
            return body
        except Exception as e:  # retry network/JSON errors, then give up loudly
            print(f"retry {attempt + 1} {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def fetch_list(out):
    rows, page, last = [], 1, 1
    while page <= last:
        body = get(f"{BASE}/list?page={page}&per_page={PER_PAGE}")
        rows.extend(body["data"])
        last = body["pagination"]["last_page"]
        total = body["pagination"]["total"]
        page += 1
        time.sleep(DELAY_S)
    assert len(rows) == total, (len(rows), total)
    (out / "list.json").write_text(json.dumps(rows, ensure_ascii=False))
    print(f"list rows {len(rows)}, total_seats {body.get('total_seats')}")
    return rows


def fetch_details(out, ids):
    path = out / "details.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(l)["id"] for l in path.read_text().splitlines() if l.strip()}
    with path.open("a") as f:
        for cid in ids:
            if cid in done:
                continue
            rec = get(f"{BASE}/detail/{cid}")["data"]
            rec = {k: v for k, v in rec.items() if k not in DROP}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            time.sleep(DELAY_S)
    print(f"details done: {len(ids)} ids")


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    rows = fetch_list(out)
    ids = sorted({r["college_id"] for r in rows})
    fetch_details(out, ids)


if __name__ == "__main__":
    main()
