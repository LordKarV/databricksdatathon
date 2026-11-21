"""Map free-text inputs to a fixed service list via Databricks serving endpoints (strict JSON).

Usage: python map_services.py <endpoint> [id ...]
Results are appended to out/map_<endpoint>.jsonl; ids already there are skipped, so a rerun
never spends a second call on the same case. Latency is wall time of the `databricks api post`
process, so it includes CLI start-up (measured separately, see REPORT.md).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from inputs import CASES, HARD, SERVICES

HERE = Path(__file__).parent
OUT = HERE / "out"

SYSTEM = (
    "You route patients in India to the right kind of hospital care. The user message is what a "
    "family member or health worker typed or said, in English, Hindi, Hinglish (romanised Hindi), "
    "Marathi or another Indian language. Pick exactly one service from this list: "
    "dialysis (recurring kidney blood cleaning), csection (emergency caesarean, obstructed or "
    "abnormal labour, breech, transverse), nicu (sick or premature newborn), cardiac_surgery "
    "(bypass, valve, heart hole repair), mri, burns, trauma (accident, fall, fracture, head injury, "
    "bleeding), icu (critical illness needing intensive care or ventilator), other (anything else). "
    "urgency: emergency (minutes to hours), urgent (within days), routine. red_flag: true if the "
    "text shows a danger sign that means go now (unconscious, heavy bleeding, breathing trouble, "
    "labour with complication, large or facial burn). decisive_phrase: copy the exact words from the "
    "user message that decided the service, verbatim, in the original script. Answer only JSON."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "service": {"type": "string", "enum": SERVICES},
        "urgency": {"type": "string", "enum": ["emergency", "urgent", "routine"]},
        "red_flag": {"type": "boolean"},
        "decisive_phrase": {"type": "string"},
    },
    "required": ["service", "urgency", "red_flag", "decisive_phrase"],
    "additionalProperties": False,
}


def call(endpoint: str, text: str) -> tuple[dict, float]:
    body = {
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
        "temperature": 0,
        "max_tokens": 200,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "route", "schema": SCHEMA, "strict": True}},
    }
    t0 = time.perf_counter()
    p = subprocess.run(["databricks", "api", "post", f"/serving-endpoints/{endpoint}/invocations",
                        "--json", json.dumps(body, ensure_ascii=False)],
                       capture_output=True, text=True, env={**os.environ, "DATABRICKS_CONFIG_PROFILE": "vf"})
    ms = (time.perf_counter() - t0) * 1000
    if p.returncode != 0:
        return {"error": (p.stderr or p.stdout)[-500:]}, ms
    return json.loads(p.stdout), ms


def parse(resp: dict) -> dict:
    """Return the model's JSON answer, or {'parse_error': ...} if it is not valid against SCHEMA."""
    try:
        content = resp["choices"][0]["message"]["content"]
        ans = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        return {"parse_error": f"{type(e).__name__}: {str(resp)[:300]}"}
    if not isinstance(ans, dict) or ans.get("service") not in SERVICES or not isinstance(ans.get("red_flag"), bool):
        return {"parse_error": f"schema violation: {ans}"}
    return ans


def main() -> None:
    endpoint, only = sys.argv[1], set(sys.argv[2:])
    OUT.mkdir(exist_ok=True)
    path = OUT / f"map_{endpoint}.jsonl"
    done = {json.loads(l)["id"] for l in path.read_text().splitlines()} if path.exists() else set()
    with path.open("a") as f:
        for cid, lang, text, exp_s, exp_rf in CASES + HARD:
            if cid in done or (only and cid not in only):
                continue
            resp, ms = call(endpoint, text)
            ans = parse(resp) if "error" not in resp else {"call_error": resp["error"]}
            row = {"id": cid, "lang": lang, "text": text, "expected_service": exp_s,
                   "expected_red_flag": exp_rf, "ms": round(ms), "answer": ans,
                   "usage": resp.get("usage")}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(cid, ans.get("service"), exp_s, round(ms), "ms", ans.get("parse_error") or ans.get("call_error") or "")


if __name__ == "__main__":
    main()
