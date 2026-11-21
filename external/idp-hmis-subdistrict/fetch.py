"""Fetch a column subset of HMIS sub-district indicators from the India Data Portal CKAN datastore.

The full CSV is 408,524,822 bytes (over the team's 300 MB per-download cap), so this pulls
every row but only the ~25 columns the product uses, as CSV pages from datastore_search.
ckan.indiadataportal.com refused TCP connections on 2026-11-21; ckandev.indiadataportal.com
serves the same package (id 5841ceaf-...), so it is tried second.

Usage: python -I fetch.py OUT_DIR [--max-pages N]
"""
import json
import sys
import time
import urllib.parse
import urllib.request

HOSTS = ["ckan.indiadataportal.com", "ckandev.indiadataportal.com"]
PKG = "health-management-information-system-hmis"
RESOURCE_NAME = "Major Health Indicators Sub-district Level"
UA = "datathon-research-client"
PAGE = 32000  # CKAN default ckan.datastore.search.rows_max
FIELDS = [
    "_id", "date", "state_name", "state_code", "district_name", "district_code",
    "subdistrict_name", "subdistrict_code", "sector",
    "csec_total", "inst_deliv_csec", "csec_night", "live_birth_male", "live_birth_female",
    "home_deliv_sba", "home_deliv_non_sba", "sncu_inborn_m", "sncu_inborn_f",
    "outborn_male", "outborn_female", "death_sncu", "admit_nbsu", "preterm_nb",
    "emer_trauma_acc_poison", "emer_burn", "emer_cardiac", "emer_cva", "emer_ob_comp",
    "emer_snakebite", "death_emer_dept", "major_surg_nonobgyn", "op_major_ga_sa",
    "xray_tests", "usg_tests", "lab_tests_done", "blood_units_issued",
    "outpatient_acute_heart_diseases", "outpatient_oncology",
    "inpatient_male_adults", "inpatient_female_adults",
]


def get(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def pick_host(out_dir):
    for h in HOSTS:
        url = f"https://{h}/api/3/action/package_show?id={PKG}"
        try:
            body = get(url, 60)
        except OSError as e:
            print(f"host {h} failed: {e}", file=sys.stderr)
            time.sleep(1)
            continue
        with open(f"{out_dir}/package_show.json", "wb") as f:
            f.write(body)
        res = [r for r in json.loads(body)["result"]["resources"] if r["name"] == RESOURCE_NAME]
        if len(res) != 1 or not res[0].get("datastore_active"):
            raise SystemExit(f"resource '{RESOURCE_NAME}' not found or not in datastore on {h}")
        print(f"metadata from {url}; resource {res[0]['id']} size {res[0].get('size')}")
        return h, res[0]["id"]
    raise SystemExit("no CKAN host reachable")


def main():
    out_dir = sys.argv[1]
    max_pages = int(sys.argv[sys.argv.index("--max-pages") + 1]) if "--max-pages" in sys.argv else 10**6
    host, rid = pick_host(out_dir)
    out_path = f"{out_dir}/hmis_subdistrict_subset.csv"
    n_rows, offset, page = 0, 0, 0
    with open(out_path, "w", encoding="utf-8", newline="") as out:
        out.write(",".join(FIELDS) + "\n")
        while page < max_pages:
            q = urllib.parse.urlencode({
                "resource_id": rid, "fields": ",".join(FIELDS), "sort": "_id",
                "limit": PAGE, "offset": offset, "records_format": "csv", "include_total": "false",
            })
            url = f"https://{host}/api/3/action/datastore_search?{q}"
            for attempt in range(3):
                try:
                    d = json.loads(get(url))
                    break
                except OSError as e:
                    print(f"offset {offset} attempt {attempt}: {e}", file=sys.stderr)
                    time.sleep(5 * (attempt + 1))
            else:
                raise SystemExit(f"giving up at offset {offset}")
            if not d.get("success"):
                raise SystemExit(f"API error at offset {offset}: {d.get('error')}")
            recs = d["result"]["records"]  # CSV text without header when records_format=csv
            if not recs.strip():
                break
            out.write(recs if recs.endswith("\n") else recs + "\n")
            got = recs.count("\n") if recs.endswith("\n") else recs.count("\n") + 1
            n_rows += got
            offset += PAGE
            page += 1
            print(f"page {page} offset {offset} rows so far {n_rows}", flush=True)
            if got < PAGE:
                break
            time.sleep(1)  # polite: about 1 request per second
    print(f"wrote {n_rows} rows to {out_path} from https://{host}/api/3/action/datastore_search?resource_id={rid}")


if __name__ == "__main__":
    main()
