"""Write and run submission/referral_saathi.ipynb (issue #57).

The notebook's cells live here as plain strings, so a reviewer can read the notebook source in one diff. This script
writes the .ipynb, executes it top to bottom with the local kernel and saves it WITH outputs, which is what judges
read on GitHub. On Databricks the same notebook runs from a Git folder; its first code cell picks the data source.
    .venv-app/bin/python submission/build_notebook.py            # write + execute (kernel: rs-app, else python3)
    .venv-app/bin/python submission/build_notebook.py --no-run   # write only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent
NB = HERE / "referral_saathi.ipynb"
MAX_MB = 20

CELLS: list[tuple[str, str]] = []


def md(s: str) -> None:
    CELLS.append(("md", s.strip("\n")))


def code(s: str) -> None:
    CELLS.append(("code", s.strip("\n")))


# ---------------------------------------------------------------------------------------------------------------------
md("""
# Referral Saathi: whom to call first, and why

A health worker in rural India has a patient who needs dialysis, an emergency caesarean or trauma care. The
facility list she could search says many things that are not true: hospitals that "offer" a service because a
sentence about another hospital was pasted into their record, map points in the wrong district, and claims no one
has checked. **Referral Saathi** reads every listing sentence, keeps only evidence about the facility itself,
says how sure it is in words, and tells her whom to call first and why. It works offline and on a cheap phone.

This notebook is the code and the reasoning behind the app, in plain words first:

1. The problem and the data
2. What is wrong with the data
3. Cleaning: fixed, flagged, and what cannot be fixed
4. Sources and external evidence
5. The knowledge base
6. The model and an honest evaluation
7. `recommend(service, location)` with its WHY and HOW, on 3 real queries, including a multi-stop plan
8. Data stories
9. Limits
10. How to open the app

Every number below is computed in this notebook from the repository's files or the provided dataset, or copied
from a named report file by a function that fails if the report changes shape. Outputs show aggregate numbers,
charts and a few quoted facility sentences as examples. No table of the provided records is printed.
""")

md("""
## 0. Setup

**On Databricks Free Edition:** clone the repository as a Git folder and open this notebook from `submission/`.
It reads the provided dataset from the Marketplace catalog through Spark. If you installed the listing under
another catalog name, change `CATALOG` below.

**Locally:** the same cells read the repository's cleaned tables in `derived/v1/` instead. Set `MODE` below to
force one or the other.

Some steps cannot run inside Free Edition: the website crawl, web labelling and external downloads. They ran
offline. Their outputs are summary files in the repository, or tables in a Unity Catalog volume (`VOLUME`).
Each section that uses one says so.
""")

code('''
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

MODE = "auto"   # "auto", "databricks" or "local"
CATALOG = "databricks_virtue_foundation_dataset_dais_2026"
SCHEMA = "virtue_foundation_dataset"
VOLUME = f"/Volumes/{CATALOG}/referral_saathi/offline_outputs"   # created by the team for the offline steps

ON_DATABRICKS = MODE == "databricks" or (MODE == "auto" and "DATABRICKS_RUNTIME_VERSION" in os.environ)
ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "derived" / "v1").is_dir())
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

plt.rcParams.update({"figure.dpi": 100, "figure.figsize": (7, 3.2), "axes.spines.top": False,
                     "axes.spines.right": False})
V1 = ROOT / "derived" / "v1"
REPO_URL = "https://github.com/LordKarV/databricksdatathon/blob/dev/"
print("running on", "Databricks" if ON_DATABRICKS else "a local machine", "| repository at", ROOT.name)
''')

md("""
The app reads small exports built from `derived/v1`, using only the standard library at run time. If they are
missing (a fresh clone), the next cell builds them. The order matters: the planner first, then the facts, whose
export copies the sentences the planner cites, then the "How this works" page data.
""")

code('''
BUILDS = [("planner/out/planner_v1.json.gz", "planner/export_v1.py"),
          ("app/facts/out/facts.json.gz", "app/facts/build.py"),
          ("app/howto/out/how.json", "app/howto/build.py")]
for out, script in BUILDS:
    if (ROOT / out).is_file():
        print(f"ok      {out}")
    else:
        r = subprocess.run([sys.executable, script], cwd=ROOT, capture_output=True, text=True, check=False)
        print(f"built   {out}: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]}")
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 1. The problem and the data

The provided dataset is one table of Indian health facilities, scraped from the web: names, addresses, map
points, phone numbers, and free-text lists of procedures, equipment, capabilities and specialties. A health
worker needs three facts from it, and it states none of them reliably:
- Does the facility exist?
- Is it where the map says?
- Does it really offer the service?
""")

code('''
if ON_DATABRICKS:
    raw = spark.table(f"{CATALOG}.{SCHEMA}.facilities")  # noqa: F821 (spark is predefined on Databricks)
    n_records, n_columns = raw.count(), len(raw.columns)
    by_type = raw.groupBy("facilityTypeId").count().toPandas().set_index("facilityTypeId")["count"]
    by_state = (raw.groupBy("address_stateOrRegion").count().toPandas()
                .set_index("address_stateOrRegion")["count"])
    print(f"Provided table {CATALOG}.{SCHEMA}.facilities: {n_records:,} records, {n_columns} columns")
else:
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id", "state_final"])
    # record counts by type for every usable record, as counted by the crawl's target builder
    by_type = pd.read_csv(ROOT / "kb/crawl/coverage_by_type.csv").set_index("ftype")["records"]
    n_records = len(loc)
    by_state = loc.state_final.value_counts()
    print(f"Local run: {n_records:,} usable records in derived/v1 (the cleaned copy of the provided table)")

fig, ax = plt.subplots(1, 2, figsize=(9, 3.2))
by_type.sort_values().tail(6).plot.barh(ax=ax[0], color="#4c72b0", title="Records by facility type")
by_state.sort_values().tail(10).plot.barh(ax=ax[1], color="#4c72b0", title="Top 10 states by records")
plt.tight_layout()
plt.show()
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 2. What is wrong with the data

We audited the table before cleaning it. These are the five findings that matter most for a patient. Each count
was checked by hand on samples; the full method is in `REPORT.md`. The table is copied from the report by
`app/howto/build.py`, the same function that feeds the app's "How this works" page, so the notebook and the app
cannot disagree.
""")

code('''
from howto import build as how


def show_table(t, cols=None, max_chars=140):
    df = pd.DataFrame(t["rows"], columns=t["columns"])
    if cols:
        df = df[cols]
    with pd.option_context("display.max_colwidth", max_chars):
        display(df)
    print(f"source: {t['source']}, section '{t['heading']}'")

findings = how.table("REPORT.md", "1.1 The 5 findings", ["Finding", "Verified count / denominator",
                                                      "What goes wrong for a patient"])
show_table(findings)
''')

md("One of those findings, recomputed here from the cleaned location table: how far each record's map point is"
   " from the centre of its own PIN code.")

code('''
d = pd.read_parquet(V1 / "facility_location.parquet", columns=["raw_coords_to_pin_km"]).raw_coords_to_pin_km.dropna()
far50, far100 = int((d > 50).sum()), int((d > 100).sum())
print(f"{far50:,} of {len(d):,} map points are more than 50 km from their own PIN code ({far100:,} more than 100 km).")
ax = d.clip(lower=0.1).map(math.log10).plot.hist(bins=60, color="#4c72b0")
ax.axvline(math.log10(50), color="#c44e52", ls="--", label="50 km")
ax.set_xlabel("distance from own PIN centre (log10 km)")
ax.set_ylabel("records")
ax.legend()
plt.tight_layout()
plt.show()
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 3. Cleaning: fixed, flagged, and what cannot be fixed

Cleaning does three different things, and the app treats them differently:
- **Fixed:** repaired in `derived/v1`.
- **Flagged:** kept, but shown to the user as a warning on the card.
- **Cannot be fixed by cleaning:** the answer is a phone call before travelling, and the app says so.
""")

code('''
fixed, flagged, cannot = (how.table("REPORT.md", h) for h in ("Fixed", "Flagged", "Cannot be handled by cleaning"))
print(f"fixed: {len(fixed['rows'])} problems | flagged: {len(flagged['rows'])} | cannot be fixed by cleaning: "
      f"{len(cannot['rows'])}")
show_table(cannot)
''')

code('''
show_table(fixed, max_chars=90)
''')

md("""
The core of the cleaning is sentence attribution. Every listing sentence is split out with an id, then tagged:
- about this facility (`own_anchored`);
- about another facility (`other_facility`, often copied from a group or a directory page);
- ambiguous;
- or unanchored (a plain service phrase with no name in it).

Only sentences about the facility itself, or unanchored sentences, count as evidence. The others are listed as
ignored.
""")

code('''
claims = pd.read_parquet(V1 / "claims.parquet", columns=["attribution"])
att = claims.attribution.value_counts()
print(f"{len(claims):,} listing sentences; {att.get('other_facility', 0):,} name another facility and never count "
      "as evidence for this one.")
att.plot.barh(color="#4c72b0", title="Listing sentences by attribution")
plt.tight_layout()
plt.show()
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 4. Sources and external evidence

Every record was scraped from web pages: social media pages, insurance-scheme lists, directories, the facility's
own website. We scored how often each kind of source was right, against claims confirmed or contradicted by a
second source. The reliability and its 90% interval come from `derived/v1/source_classes.csv`.
""")

code('''
sc = pd.read_csv(V1 / "source_classes.csv").sort_values("n_urls", ascending=False)
print(f"{sc.n_urls.sum():,} source URLs in {len(sc)} classes")
ax = sc.set_index("source_class").reliability.sort_values().plot.barh(
    xerr=None, color="#4c72b0", title="Reliability by kind of source (share of checked claims that held)")
ax.set_xlim(0.5, 1)
plt.tight_layout()
plt.show()
''')

md("""
We evaluated 14 public lists as independent evidence (accreditation, blood centres, maternity certification,
OpenStreetMap and others), with a hand check of the match quality and the licence of each for a public demo.
Restricted lists are used only as per-facility facts and are never printed here.
""")

code('''
show_table(how.table("research/DATASETS.md", "Summary", ["Dataset", "Role", "Licence for a public demo",
                                                        "Hand check"]))
''')

md("""
Two offline witnesses add independent text and tags. Neither can run inside Free Edition: the crawl needs
outbound HTTP for about an hour, and the matching needs large downloads. Their summaries are committed in `kb/`.
""")

code('''
crawl = json.loads((ROOT / "kb/crawl/crawl_stats.json").read_text())
osm = json.loads((ROOT / "kb/opendata/stats.json").read_text())
print(f"Website crawl: {crawl['sites_reachable']:,} of {crawl['sites_attempted']:,} facility websites reachable "
      f"({crawl['runtime']['minutes_total']} minutes over {crawl['runtime']['runs']} runs).")
cov = osm["coverage"]
print(f"Open data: {cov['any_match']['n']:,} of {osm['vf_facilities']:,} records matched to OpenStreetMap or "
      f"Wikidata ({cov['any_match']['share_of_vf']:.0%}); opening hours parsed for {cov['hours_parsed']['n']:,}.")
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 5. The knowledge base

- **Taxonomy** (`kb/taxonomy/lexicon.json`): the services, the phrases that count as evidence for each, and the
  prerequisites a real unit needs. For example, dialysis needs a nephrologist or a dialysis machine.
- **Evidence rules** (`derived/v1/evidence_rules.parquet`): how strong each pattern of evidence is, checked by
  hand on real cases.
- **Care pathways** (`kb/pathways/care_pathways.json`): for time-critical cases, which kind of facility to reach
  first and within how long, each step quoted from a guideline or marked as an assumption.
""")

code('''
lex = json.loads((ROOT / "kb/taxonomy/lexicon.json").read_text())
rules = pd.read_parquet(V1 / "evidence_rules.parquet")
grades = pd.read_parquet(V1 / "grades.parquet", columns=["grade"])
pathways = json.loads((ROOT / "kb/pathways/care_pathways.json").read_text())["pathways"]
print(f"{len(lex['services'])} services in the taxonomy; {len(rules)} evidence rules from "
      f"{int((rules.handcheck_true + rules.handcheck_false).sum())} hand-checked cases; "
      f"{len(grades):,} facility-service pairs graded.")
print("Care pathways:", "; ".join(p["name"].split(":")[0] for p in pathways))
grades.grade.value_counts().plot.barh(color="#4c72b0", title="Evidence grade of each facility-service pair")
plt.tight_layout()
plt.show()
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 6. The model and an honest evaluation

> **To be completed by the team lead after #11** (the fitted model). This section will load the fitted scores
> (`derived/v2/facility_service_scores.parquet`) and print the final evaluation.

Until then, the app uses an interim, conservative rule. It says "Likely" only when a second source confirmed the
service; everything else is "Not verified: call first". Below is the current measured evaluation of the
prototype model, including the baselines and an LLM judge, copied from `model/MODEL_SPEC.md`.
""")

code('''
show_table(how.table("model/MODEL_SPEC.md", "4.2 Pair-level discrimination",
                     ["system", "all 71 test", "searched only (39, 17 pos)"]))
''')

code('''
did_not = how.bullets("model/MODEL_SPEC.md", "4.11 Claims that did not survive review")
print("What did not work (from the statistical review):\\n")
for x in did_not["items"][:5]:
    print(" -", x[:230] + ("..." if len(x) > 230 else ""))
print(f"\\n... {len(did_not['items'])} in all, in {did_not['source']}")
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 7. `recommend(service, location)`: the answer, its WHY and its HOW

This is the same code the app serves at `POST /api/plan`, imported from `app/`:
- `facts.engine.Engine`: the scores, bands and evidence for each facility and service;
- `itinerary`: the multi-stop route from `planner/`.

For each option it prints:
- the band in words, the score with its range, and the travel estimate;
- the listing's own sentences, word for word, with their ids;
- the points that add up to the score;
- the question to ask on the phone.
""")

code('''
from facts.engine import RULE_PLAIN, Engine
from itinerary import attach

ENGINE = Engine.load()
print(f"engine loaded: {len(ENGINE.fid):,} facilities, {sum(len(v) for v in ENGINE.pairs.values()):,} "
      f"facility-service pairs, {len(ENGINE.claims):,} quotable sentences; data {ENGINE.meta['source']} "
      f"as of {ENGINE.meta['as_of']}")

def recommend(service: str, lat: float, lon: float) -> dict:
    """The /api/plan payload for a service at a point (rounded to about 1 km, as the app does)."""
    return attach(ENGINE.plan(service, round(lat, 2), round(lon, 2), None, "notebook"), ENGINE)

def show(plan: dict, n: int = 3) -> None:
    label = plan["query"]["service_label"]["en"]
    print(f"== {label} near {plan['location']['lat']}, {plan['location']['lon']}")
    if plan["abstain"]:
        print("   SAYS NO:", plan["abstain"]["text"])
    for o in plan["options"][:n]:
        t = o["travel"]
        print(f"\\n{o['rank']}. {o['name']} ({o['district']}, {o['state']})")
        print(f"   {o['band_word'].upper()}: score {o['p']:.2f} (range {o['p_lo']:.2f} to {o['p_hi']:.2f}); "
              f"{t['km']:.0f} km, about {t['low']}-{t['high']} min ({t['label']})")
        for e in o["evidence"][:2]:
            print(f'   WHY  "{e["quote"]}"  [{e["claim_id"]}]')
        pts = " + ".join(f"{c['label']} {c['points']:+d}" for c in o["contributions"])
        print(f"   HOW  {pts} = {sum(c['points'] for c in o['contributions']):+d} points")
        if o.get("why_first_text"):
            print("   FIRST", o["why_first_text"])
        print("   ASK ", o["call_ahead"][0]["question"])
    it = plan.get("itinerary")
    if it and it["plans"]:
        r = it["plans"][0]
        print(f"\\n   ROUTE ({it['pathway_name']}): {r['type_word']}")
        for k, s in enumerate(r["stops"], 1):
            print(f"   {k}. {s['purpose_word']}: {s['name']}, arrive about {s['eta_low']}-{s['eta_high']} min, "
                  f"chance {s['p']:.2f}, {s['n_evidence']} evidence lines")
        if r["vs_direct"]:
            v = r["vs_direct"]
            print(f"   vs going straight to {v['direct_name']} ({v['direct_minutes']} min): chance of care in time "
                  f"{v['direct_p_objective']:.2f} direct against {v['plan_p_objective']:.2f} with this route")
''')

code('''
show(recommend("dialysis", 24.79, 85.0))          # Gaya, Bihar
''')

code('''
show(recommend("emergency_csection", 19.88, 75.34))   # Aurangabad district, Maharashtra
''')

code('''
show(recommend("trauma_emergency", 25.15, 83.68))     # NH-19 near Mohania, Bihar: a multi-stop plan
''')

# ---------------------------------------------------------------------------------------------------------------------
md("## 8. Data stories")

code('''
stories = ROOT / "viz" / "STORYBOOK.md"
if stories.is_file():
    heads = [ln.lstrip("# ").strip() for ln in stories.read_text().splitlines() if ln.startswith("## ")]
    print("Data stories in viz/STORYBOOK.md:")
    for head in heads:
        print(" -", head)
else:
    print("The data stories (issue #53) are not in this version yet; this cell lists them once viz/ lands.")
''')

# ---------------------------------------------------------------------------------------------------------------------
md("## 9. Limits")

code('''
h = json.loads((ROOT / "app/howto/out/how.json").read_text())["facts"]
print(f"- Thin rural coverage: {h['bihar_records']['value']:,} of {h['bihar_records']['of']:,} records are in Bihar.")
print(f"- Only {h['app_likely']['value']} of {h['app_pairs']['value']:,} facility-service pairs the app serves are "
      "confirmed by a second source; everything else is 'call first'.")
print("- Labels come from public web pages, not from phone calls or visits.")
print(f"- Opening hours: {h['hours_records']['value']:,} of {h['hours_records']['of']:,} records mention hours at all; "
      "nothing says whether a bed or a slot is free today.")
print("- Travel times are rough estimates (straight line times a road factor), shown as ranges.")
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 9b. Learning from phone calls (reviewed, never automatic)

When a health worker taps "Said yes", "Said no" or "No answer" after calling, the app writes one row to
`workspace.referral_saathi.call_outcomes`. A row holds the facility, the service, the answer, the call questions,
the model version, the district and the time. It never holds patient data.

The cell below reads those rows and shows how they *would* move the weight of each evidence family. It uses a
Beta update: the family's mean score today counts as 10 earlier calls, and each answered call adds one more. Nothing
is retrained from here; a person reviews the table first.
""")

code('''
from collections import defaultdict

OUTCOMES_TABLE = "workspace.referral_saathi.call_outcomes"
PRIOR_CALLS = 10
rows = []
if ON_DATABRICKS:
    try:
        q = f"SELECT facility_id, service_id, outcome, count(*) AS n FROM {OUTCOMES_TABLE} GROUP BY ALL"
        rows = [tuple(r) for r in spark.sql(q).collect()]  # noqa: F821 (spark is predefined on Databricks)
    except Exception as e:  # table missing in this workspace
        print("call_outcomes is not readable here:", type(e).__name__)
if not rows:
    print("No call outcomes recorded in this environment yet; the table below fills in as calls are recorded.")

fam = defaultdict(lambda: {"yes": 0, "no": 0, "no_answer": 0, "score_sum": 0.0, "pairs": 0})
for rule_rows in ENGINE.pairs.values():
    for p in rule_rows:
        fam[p.rule]["score_sum"] += p.score
        fam[p.rule]["pairs"] += 1
for fid, sid, outcome, n in rows:
    i = ENGINE.fid.get(fid)
    p = ENGINE.index.get(sid, {}).get(i) if i is not None else None
    if p is not None:
        fam[p.rule][outcome] += int(n)
print(f"{'evidence family':52} {'pairs':>6} {'yes':>4} {'no':>4} {'mean now':>9} {'would be':>9}")
for rule, f in sorted(fam.items(), key=lambda kv: -kv[1]["pairs"]):
    mean = f["score_sum"] / f["pairs"]
    new = (mean * PRIOR_CALLS + f["yes"]) / (PRIOR_CALLS + f["yes"] + f["no"])
    label = RULE_PLAIN.get(rule, rule)[:52]
    print(f"{label:52} {f['pairs']:>6,} {f['yes']:>4} {f['no']:>4} {mean:>9.2f} {new:>9.2f}")
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 10. How to open the app

The app runs as a Databricks App, `referral-saathi`, in the team's workspace. Judges get access as workspace
users. It is built for a phone:
- **Start:** tap a service; the app uses GPS, or a PIN code, village or district.
- **Results:** whom to call first, with the evidence on each card; "Why this?" opens the full WHY and HOW.
- **Offline:** after one online visit, the state's facility data is saved and answers keep working without
  internet.
- **"How this works":** in the header, this notebook's story in plain words.

To run it locally: `.venv-app/bin/python -m uvicorn app:app` from `app/` (see `app/README.md`).
""")

# ---------------------------------------------------------------------------------------------------------------------
md("""
## Appendix: all our code

Every Python module in the repository, by folder, with a link. The notebook imports `app/`, `planner/`, `geo/`
and `app/howto/` directly. The rest are the offline pipelines that produced `derived/v1` and the `kb/`
summaries.
""")

code('''
from IPython.display import Markdown

SKIP = {".venv-app", ".venv", "node_modules", "build", "out", "__pycache__", ".git", ".claude"}
try:  # tracked files only, so every link resolves on GitHub; plain folder walk where git is not available
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True)
    mods = sorted(Path(x) for x in tracked.stdout.split())
except (OSError, subprocess.CalledProcessError):
    mods = sorted(p.relative_to(ROOT) for p in ROOT.rglob("*.py") if not SKIP & set(p.relative_to(ROOT).parts))
by_dir = {}
for m in mods:
    by_dir.setdefault(m.parts[0], []).append(m)
lines = [f"{len(mods)} modules in {len(by_dir)} top-level folders.\\n"]
for top, ms in by_dir.items():
    lines.append(f"**{top}/** ({len(ms)}): " + ", ".join(f"[{m.relative_to(top) if len(m.parts) > 1 else m}]"
                                                         f"({REPO_URL}{m.as_posix()})" for m in ms))
Markdown("\\n\\n".join(lines))
''')


# ---------------------------------------------------------------------------------------------------------------------
def build() -> nbformat.NotebookNode:
    nb = new_notebook()
    nb.cells = [new_markdown_cell(s) if kind == "md" else new_code_cell(s) for kind, s in CELLS]
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.metadata["language_info"] = {"name": "python"}
    return nb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-run", action="store_true")
    ap.add_argument("--kernel", default="rs-app")
    args = ap.parse_args()
    nb = build()
    if not args.no_run:
        NotebookClient(nb, timeout=600, kernel_name=args.kernel, resources={"metadata": {"path": str(HERE)}}).execute()
        nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
        errors = [o for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", [])
                  if o.get("output_type") == "error"]
        empty = [i for i, c in enumerate(nb.cells) if c.cell_type == "code" and not c.get("outputs")]
        if errors or empty:
            print(f"errors: {len(errors)}, code cells without output: {empty}", file=sys.stderr)
            nbformat.write(nb, NB)
            return 1
    nbformat.write(nb, NB)
    mb = NB.stat().st_size / 1e6
    print(f"wrote {NB.name}: {len(nb.cells)} cells, {mb:.2f} MB")
    return 0 if mb < MAX_MB else 1


if __name__ == "__main__":
    raise SystemExit(main())
