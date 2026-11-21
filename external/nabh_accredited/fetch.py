"""Fetch the NABH "Find an accredited healthcare organisation" list.

Usage:
  python -I fetch.py OUT_DIR all            # every page of the unfiltered list
  python -I fetch.py OUT_DIR counts         # total_results per specialty code
  python -I fetch.py OUT_DIR spec DIA OBG   # every page for each specialty code

Writes raw responses as OUT_DIR/raw/<tag>/page_NNNN.json.gz. Re-runnable:
pages already on disk are skipped. One request per second (robots.txt allows
/wp-admin/admin-ajax.php). Endpoint and form fields were read from
https://nabh.co/wp-content/themes/nabh/js/my-map.js (fetchHospitals).
"""
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

URL = "https://nabh.co/wp-admin/admin-ajax.php"
UA = "Mozilla/5.0 (datathon-research; public-data fetch, 1 req/s)"
DELAY_S = 1.0
SPEC_CODES = ("ANA AYU BLO CAR DEN DER DIA EMD END ENT EYE GAS HEP HOM ICU IMG INF LAB MED NEU "
              "NPH OBG ONC ORT PED PSY PUL REP RHE SID SUR TRN UNA URO YOG PHARMACY AMBULANCE CAE PAN").split()


def post(page, spec=None, retries=3):
    fields = [("action", "get_hospitals"), ("q", ""), ("lat", ""), ("long", ""),
              ("selectedSpecText", ""), ("page", str(page))]
    if spec:
        fields.append(("specialities[]", spec))
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(URL, data=body, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            json.loads(raw)  # validate before saving
            return raw
        except Exception as e:  # network or bad JSON: back off and retry
            print(f"  page {page} spec={spec} attempt {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"giving up on page {page} spec={spec}")


def fetch_all_pages(out, tag, spec=None):
    d = out / "raw" / tag
    d.mkdir(parents=True, exist_ok=True)
    first = d / "page_0001.json.gz"
    if not first.exists():
        first.write_bytes(gzip.compress(post(1, spec)))
        time.sleep(DELAY_S)
    total = json.loads(gzip.decompress(first.read_bytes()))["pagination"]["total_pages"]
    print(f"{tag}: {total} pages")
    for p in range(2, total + 1):
        f = d / f"page_{p:04d}.json.gz"
        if f.exists():
            continue
        f.write_bytes(gzip.compress(post(p, spec)))
        if p % 50 == 0:
            print(f"  {tag} page {p}/{total}")
        time.sleep(DELAY_S)


def counts(out):
    res = {}
    for code in SPEC_CODES:
        res[code] = json.loads(post(1, code))["pagination"]
        print(code, res[code])
        time.sleep(DELAY_S)
    (out / "spec_counts.json").write_text(json.dumps(res, indent=1))


def main(argv):
    out = Path(argv[1])
    mode = argv[2]
    if mode == "all":
        fetch_all_pages(out, "all")
    elif mode == "counts":
        counts(out)
    elif mode == "spec":
        for code in argv[3:]:
            if code not in SPEC_CODES:
                raise SystemExit(f"unknown specialty code {code}")
            fetch_all_pages(out, f"spec_{code}", code)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
