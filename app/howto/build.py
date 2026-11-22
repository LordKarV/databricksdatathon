"""Build the 'How this works' page data (issue #45): app/howto/out/how.json. No hand-typed numbers.

Every number on the page comes from here, and every entry names the repo file it came from:
- counts are computed from derived/v1, the facts export and kb/pathways;
- tables and lists are copied verbatim (only backticks and bold markers stripped) from REPORT.md,
  model/MODEL_SPEC.md and research/DATASETS.md, found by their heading; a missing heading or table fails the build;
- ranking constants are read from app/facts/engine.py, so the page cannot drift from the code.
Run from the repo root after app/facts/build.py:
    .venv-app/bin/python app/howto/build.py
When #11 lands, point EVAL at its results file and rerun; the page refreshes without code changes.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
OUT = Path(__file__).resolve().parent / "out"
V1 = "derived/v1"
REPORT, SPEC, DATASETS = "REPORT.md", "model/MODEL_SPEC.md", "research/DATASETS.md"
EVAL = SPEC  # #11 replaces this with its v2 results file
REPO_URL = "https://github.com/LordKarV/databricksdatathon/blob/dev/"
FAR_KM = 50  # the report's threshold for "far from its own PIN"; shown on the page as a fact
HOURS = re.compile(r"\b24 ?(?:x|/|\*|hrs?|hours) ?7?\b|round the clock|\bopen(?:s)? (?:from|daily|on|till)|"
                   r"\b\d{1,2}(?::\d{2})? ?(?:am|pm)\b|opening hours|timings?\b", re.I)


def clean(cell: str) -> str:
    return re.sub(r"\*\*|`", "", cell).strip()


def section(path: str, heading: str) -> list[str]:
    """Lines under the heading that starts with `heading`, up to the next heading of the same or higher level."""
    lines = (ROOT / path).read_text().splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("#") and ln.lstrip("#").strip().startswith(heading)),
                 None)
    if start is None:
        raise SystemExit(f"{path}: heading {heading!r} not found")
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("#") and len(ln) - len(ln.lstrip("#")) <= level:
            break
        out.append(ln)
    return out


def table(path: str, heading: str, keep: list[str] | None = None) -> dict:
    rows = [ln for ln in section(path, heading) if ln.startswith("|")]
    if len(rows) < 3:
        raise SystemExit(f"{path} / {heading}: no table")
    split = lambda ln: [clean(c) for c in ln.strip().strip("|").split("|")]  # noqa: E731
    head, body = split(rows[0]), [split(r) for r in rows[2:]]
    idx = list(range(len(head))) if keep is None else [head.index(k) for k in keep]
    return {"source": path, "heading": heading, "columns": [head[i] for i in idx],
            "rows": [[r[i] for i in idx] for r in body]}


def bullets(path: str, heading: str) -> dict:
    items: list[str] = []
    for ln in section(path, heading):
        if ln.startswith("- "):
            items.append(clean(ln[2:]))
        elif ln.startswith("  ") and items:
            items[-1] += " " + clean(ln)
    if not items:
        raise SystemExit(f"{path} / {heading}: no list")
    return {"source": path, "heading": heading, "items": items}


def fact(value, source: str, how: str, of=None) -> dict:
    d = {"value": value, "source": source, "how": how}
    if of is not None:
        d["of"] = of
    return d


def facts() -> dict:
    loc = pd.read_parquet(ROOT / V1 / "facility_location.parquet", columns=["unique_id", "state_final",
                                                                            "raw_coords_to_pin_km"])
    d = loc.raw_coords_to_pin_km
    grades = pd.read_parquet(ROOT / V1 / "grades.parquet", columns=["unique_id"])
    dps = pd.read_parquet(ROOT / V1 / "data_point_scores.parquet", columns=["dp_type", "status"])
    svc = dps[dps.dp_type == "service_claim"]
    claims = pd.read_parquet(ROOT / V1 / "claims.parquet", columns=["unique_id", "text"])
    hours = claims[claims.text.str.contains(HOURS, na=False)].unique_id.nunique()
    rules = pd.read_parquet(ROOT / V1 / "evidence_rules.parquet")
    pathways = json.loads((ROOT / "kb/pathways/care_pathways.json").read_text())
    pw = pathways["pathways"] if isinstance(pathways, dict) and "pathways" in pathways else pathways
    names = [str(p.get("name") or p.get("id")).split(":")[0] for p in (pw.values() if isinstance(pw, dict) else pw)]
    sys.path.insert(0, str(APP))
    from facts import engine  # noqa: PLC0415
    eng = engine.Engine.load()
    if eng is None:
        raise SystemExit("run app/facts/build.py first")
    app_pairs = sum(len(v) for v in eng.pairs.values())
    likely = sum(p.status == "verified_true" for v in eng.pairs.values() for p in v)
    bihar = int((loc.state_final.str.upper() == "BIHAR").sum())
    return {
        "records": fact(len(loc), f"{V1}/facility_location.parquet", "rows"),
        "far_km": fact(FAR_KM, REPORT, "threshold used in the report's location findings"),
        "coords_far": fact(int((d > FAR_KM).sum()), f"{V1}/facility_location.parquet",
                           f"raw_coords_to_pin_km > {FAR_KM}", of=int(d.notna().sum())),
        "pairs_graded": fact(len(grades), f"{V1}/grades.parquet", "facility-service pairs graded"),
        "pairs_verified_true": fact(int((svc.status == "verified_true").sum()), f"{V1}/data_point_scores.parquet",
                                    "service_claim rows with status verified_true"),
        "app_pairs": fact(app_pairs, "app/facts/build.py", "pairs for the app's services"),
        "app_likely": fact(likely, "app/facts/engine.py", "pairs the interim rule bands Likely"),
        "evidence_rules": fact(len(rules), f"{V1}/evidence_rules.parquet", "rules"),
        "handchecked": fact(int((rules.handcheck_true + rules.handcheck_false).sum()), f"{V1}/evidence_rules.parquet",
                            "hand-checked cases behind the rules"),
        "radius_km": fact(engine.RADIUS_KM, "app/facts/engine.py", "RADIUS_KM"),
        "tie_min": fact(engine.TIE_MIN, "app/facts/engine.py", "TIE_MIN: emergency order, nearest plausible first"),
        "scale_planned": fact(engine.TIME_SCALE["planned"], "app/facts/engine.py", "TIME_SCALE planned"),
        "n_options": fact(engine.N_OPTIONS, "app/facts/engine.py", "N_OPTIONS"),
        "pathways": fact(len(names), "kb/pathways/care_pathways.json", "pathways"),
        "pathway_names": fact(", ".join(str(n) for n in names), "kb/pathways/care_pathways.json", "names"),
        "bihar_records": fact(bihar, f"{V1}/facility_location.parquet", "state_final = Bihar", of=len(loc)),
        "hours_records": fact(int(hours), f"{V1}/claims.parquet",
                              "records with any sentence about opening hours or 24/7", of=len(loc)),
    }


def source_classes() -> dict:
    with open(ROOT / V1 / "source_classes.csv") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: -int(r["n_urls"]))
    return {"source": f"{V1}/source_classes.csv", "heading": "source classes", "columns":
            ["Source class", "URLs", "Reliability", "90% interval"],
            "rows": [[r["source_class"].replace("_", " "), f"{int(r['n_urls']):,}", f"{float(r['reliability']):.2f}",
                      f"{float(r['ci05']):.2f} to {float(r['ci95']):.2f}"] for r in rows]}


def main() -> None:
    how = {
        "built_at": time.strftime("%Y-%m-%d", time.gmtime()),
        "repo_url": REPO_URL,
        "facts": facts(),
        "tables": {
            "findings": table(REPORT, "1.1 The 5 findings",
                              ["Finding", "Verified count / denominator", "What goes wrong for a patient"]),
            "fixed": table(REPORT, "Fixed"),
            "flagged": table(REPORT, "Flagged"),
            "cannot": table(REPORT, "Cannot be handled by cleaning"),
            "labels": table(EVAL, "4.1 What the labels are"),
            "auroc": table(EVAL, "4.2 Pair-level discrimination",
                           ["system", "all 71 test", "searched only (39, 17 pos)"]),
            "top1": table(EVAL, "4.6 End-to-end top-1", ["system", "confirmed top-1 [Wilson]",
                                                       "contradicted, wrong place or nonexistent (Unsafe@1)"]),
            "sources": source_classes(),
            "datasets": table(DATASETS, "Summary", ["Dataset", "Role", "Licence for a public demo"]),
        },
        "lists": {"did_not_work": bullets(EVAL, "4.11 Claims that did not survive review")},
    }
    t = how["tables"]
    for k, n in {"n_fixed": "fixed", "n_flagged": "flagged", "n_cannot": "cannot"}.items():
        how["facts"][k] = fact(len(t[n]["rows"]), t[n]["source"], f"rows in the '{t[n]['heading']}' table")
    OUT.mkdir(exist_ok=True)
    (OUT / "how.json").write_text(json.dumps(how, indent=1, ensure_ascii=False))
    size = (OUT / "how.json").stat().st_size
    print(f"how.json: {len(how['facts'])} facts, {len(how['tables'])} tables, {size / 1000:.1f} KB")


if __name__ == "__main__":
    main()
