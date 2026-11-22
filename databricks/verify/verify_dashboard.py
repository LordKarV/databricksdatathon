"""Check the live planner dashboard: lifecycle state, published snapshot, every dataset query from the
workspace copy (not the local JSON) runs with rows, and the published URL answers HTTP 200 with a token.
Run: .venv/bin/python databricks/verify/verify_dashboard.py
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_ID = (ROOT / "databricks" / "dashboard" / "dashboard_id.txt").read_text().strip()
WH = "6a2f5637720a2c17"
ENV_PROFILE = ["--profile", "vf"]


def cli(*args: str) -> dict:
    r = subprocess.run(["databricks", *args, *ENV_PROFILE, "-o", "json"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[:500])
    return json.loads(r.stdout)


def run(statement: str, catalog: str, schema: str) -> tuple[str, int]:
    body = {"warehouse_id": WH, "statement": statement, "catalog": catalog, "schema": schema,
            "wait_timeout": "50s", "disposition": "INLINE", "format": "JSON_ARRAY"}
    r = cli("api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body))
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(5)
        r = cli("api", "get", f"/api/2.0/sql/statements/{r['statement_id']}")
    st = r["status"]["state"]
    return (st if st == "SUCCEEDED" else st + ": " + r["status"].get("error", {}).get("message", "")[:200],
            r.get("manifest", {}).get("total_row_count", 0))


def main() -> int:
    d = cli("lakeview", "get", DASH_ID)
    pub = cli("api", "get", f"/api/2.0/lakeview/dashboards/{DASH_ID}/published")
    print("lifecycle", d.get("lifecycle_state"), "| published revision", pub.get("revision_create_time"),
          "embed_credentials", pub.get("embed_credentials"), "| draft updated", d.get("update_time"))
    ser = json.loads(d["serialized_dashboard"])
    bad = 0
    for ds in ser["datasets"]:
        cat, sch = ds.get("catalog", ""), ds.get("schema", "")
        state, n = run("".join(ds["queryLines"]), cat, sch)
        ok = state == "SUCCEEDED" and n > 0
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'} {ds['name']:24} {cat}.{sch} rows={n} {state}")
    print("pages", len(ser["pages"]), "widgets", sum(len(p["layout"]) for p in ser["pages"]))
    host = cli("auth", "env")["env"]["DATABRICKS_HOST"].rstrip("/")
    tok = cli("auth", "token")["access_token"]  # never printed
    for url in (f"{host}/sql/dashboardsv3/{DASH_ID}/published",
                f"{host}/api/2.0/lakeview/dashboards/{DASH_ID}/published"):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                print("HTTP", resp.status, url, "bytes", len(resp.read()))
        except urllib.error.HTTPError as e:
            bad += 1
            print("HTTP", e.code, url)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
