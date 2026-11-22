"""Call the live referral-saathi app with a bearer token (never printed): GET /api/ping and a real
POST /api/plan, and summarise the plan's options.
Run: .venv/bin/python databricks/verify/verify_app.py
"""
import json
import subprocess
import sys
import urllib.request

APP = "https://referral-saathi-7474649134616784.aws.databricksapps.com"
BODY = {"service": "dialysis", "lat": 25.6, "lon": 85.14, "accuracy_m": 30, "source": "gps", "depth": "quick"}


def token() -> str:
    r = subprocess.run(["databricks", "auth", "token", "--profile", "vf", "-o", "json"],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["access_token"]


def call(path: str, tok: str, body: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(APP + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> int:
    tok = token()
    st, raw = call("/api/ping", tok)
    print("GET /api/ping", st, raw[:200].decode(errors="replace"))
    st2, raw2 = call("/api/plan", tok, BODY)
    print("POST /api/plan", st2, "bytes", len(raw2))
    try:
        plan = json.loads(raw2)
    except ValueError:
        print(raw2[:500].decode(errors="replace"))
        return 1
    print("top-level keys", sorted(plan)[:30])
    opts = plan.get("options") or plan.get("results") or []
    print("n options", len(opts))
    for o in opts[:5]:
        print(" ", json.dumps({k: o.get(k) for k in list(o)[:8]}, default=str)[:400])
    return 0 if st == 200 and st2 == 200 and opts else 1


if __name__ == "__main__":
    sys.exit(main())
