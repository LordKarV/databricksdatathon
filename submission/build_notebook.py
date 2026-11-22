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
   - 7b. What we compared against: not the nearest, not the unreachable best
8. Data stories
9. Limits
10. How to open the app

Every number below is computed in this notebook from the repository's files or the provided dataset, or copied
from a named report file by a function that fails if the report changes shape. Outputs show aggregate numbers,
charts and a few quoted facility sentences as examples. No table of the provided records is printed.
""")

md("""
## 0. Setup

**To rebuild the team dataset on Databricks first:** run `submission/00_rebuild_derived.ipynb`. It reads the
Marketplace tables on Free Edition serverless, runs the repository's rules-only cleaning, claims and source-scoring
pipeline, writes `derived/v1` to a Unity Catalog volume and checks every table against `derived/v1/MANIFEST.json`.
The cell below prints the result of its last Free Edition run. This notebook then reads `derived/v1` and the frozen
model v2 export in `derived/v2`.

**On Databricks Free Edition:** clone the repository as a Git folder and open this notebook from `submission/`.
It reads the provided dataset from the Marketplace catalog through Spark. If you installed the listing under
another catalog name, change `CATALOG` below.

**Locally:** the same cells read the repository's cleaned tables in `derived/v1/` instead. Set `MODE` below to
force one or the other.

**Your own rebuild:** `00_rebuild_derived.ipynb` rebuilds `derived/v1` from the Marketplace table into a volume.
Put that folder (the one holding `derived/v1`, by default `/Volumes/workspace/referral_saathi/uploads/rebuild`) in
the `data_root` widget, or in the `DATATHON_ROOT` environment variable locally. Every table below and the app
builds then read your rebuild, and section 0.1 checks that it gives the same app as the repository's copy. Empty
means the repository's `derived/v1`.

Some steps cannot run inside Free Edition: the website crawl, web labelling and external downloads. They ran
offline. Their outputs are summary files in the repository, or tables in a Unity Catalog volume (`VOLUME`).
Each section that uses one says so.
""")

code('''
import hashlib
import json
import math
import os
import re
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
# Where derived/v1 is read from: the data_root widget on Databricks, else DATATHON_ROOT, else this repository.
try:
    dbutils.widgets.text("data_root", "")  # noqa: F821 (dbutils is predefined on Databricks)
    DATA_ROOT = Path(dbutils.widgets.get("data_root") or os.environ.get("DATATHON_ROOT") or ROOT)  # noqa: F821
except NameError:
    DATA_ROOT = Path(os.environ.get("DATATHON_ROOT") or ROOT)
if not (DATA_ROOT / "derived" / "v1" / "MANIFEST.json").is_file():
    raise FileNotFoundError(f"{DATA_ROOT}/derived/v1/MANIFEST.json not found: check data_root")
os.environ["DATATHON_ROOT"] = str(DATA_ROOT)  # the app builds below (subprocesses) read the same folder
V1 = DATA_ROOT / "derived" / "v1"
REPO_URL = "https://github.com/LordKarV/databricksdatathon/blob/dev/"
print("running on", "Databricks" if ON_DATABRICKS else "a local machine", "| repository at", ROOT.name,
      "| derived/v1 from", "the repository" if DATA_ROOT == ROOT else DATA_ROOT)
rebuilt = re.search(r"On Free Edition serverless it gave [^.]+\\.", (ROOT / "submission/README.md").read_text())
print("00_rebuild_derived.ipynb:", " ".join(rebuilt.group(0).split()) if rebuilt else "no Free Edition run recorded")
''')

md("""
The app reads small exports built from `derived/v1` and `derived/v2`, using only the standard library at run time.
The next cell rebuilds them every time (a few seconds each), so an export left over from an older checkout can never
be read by mistake; a failed build stops the notebook. The order matters: the planner first, then the facts, whose
export copies the sentences the planner cites, then the "How this works" page data.
""")

code('''
BUILDS = [("planner/out/planner_v2.json.gz", "planner/export_v2.py"),
          ("app/facts/out/facts.json.gz", "app/facts/build.py"),
          ("app/howto/out/how.json", "app/howto/build.py")]
for out, script in BUILDS:  # always rebuild: a stale export once broke a Databricks run
    r = subprocess.run([sys.executable, script], cwd=ROOT, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"{script} failed: {r.stderr[-800:]}")
    print(f"built   {out}: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else 'ok'}")
''')

md("""
### 0.1 Check: does your rebuild give the same app?

Runs only when `data_root` points at a rebuild. It builds the app's facility facts and the 36 offline state packs
twice, from the repository's `derived/v1` and from yours, into a temporary folder, and compares them. The facts
hash covers every facility, pair, quote and score the app serves, but not the build time or the folder it was
read from. The packs are compared byte for byte with the same build date. PASS means a judge's rebuild drives
exactly the app we ship. Table-level checks against `MANIFEST.json` are in `00_rebuild_derived.ipynb`.
""")

code('''
import tempfile


def app_build(data_root: Path, out: Path, built: str) -> dict:
    """Facts hash and per-state pack hashes, built from data_root/derived/v1 into out."""
    env = {**os.environ, "DATATHON_ROOT": str(data_root)}
    for script, args in (("app/facts/build.py", ["--out", str(out / "facts")]),
                         ("app/packs/build_packs.py", ["--out", str(out / "packs"), "--built", built])):
        r = subprocess.run([sys.executable, script, *args], cwd=ROOT, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{script} failed on {data_root}: {r.stderr[-500:] or r.stdout[-500:]}")
    packs = json.loads((out / "packs" / "index.json").read_text())["packs"]
    return {"facts": (out / "facts" / "facts.sha").read_text().strip(),
            "packs": {k: v["sha256"] for k, v in packs.items()}}


if DATA_ROOT == ROOT:
    print("data_root is the repository: nothing to compare. Set data_root to your rebuild to run this check.")
else:
    built = json.loads((ROOT / "derived/v1/MANIFEST.json").read_text())["build_date"]
    with tempfile.TemporaryDirectory() as tmp:
        repo, mine = app_build(ROOT, Path(tmp) / "repo", built), app_build(DATA_ROOT, Path(tmp) / "mine", built)
    rows = [("facts (facilities, pairs, quotes, scores)", repo["facts"], mine["facts"])]
    rows += [(f"pack {k}", repo["packs"][k], mine["packs"].get(k, "missing")) for k in sorted(repo["packs"])]
    check = pd.DataFrame(rows, columns=["output", "from the repository", "from your rebuild"])
    check["result"] = (check["from the repository"] == check["from your rebuild"]).map({True: "PASS", False: "DIFF"})
    n_pass = int((check.result == "PASS").sum())
    print(f"{n_pass} of {len(check)} app outputs identical: {'PASS' if n_pass == len(check) else 'DIFF'}")
    display(check[check.result != "PASS"] if n_pass < len(check) else check.head(3))  # noqa: F821
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


PHONE = r"(?:\\+91[ -]?|\\b)[6-9]\\d{4}[ -]?\\d{5}\\b"  # Indian mobile numbers: never printed in this public notebook


def show_table(t, cols=None, max_chars=140):
    df = pd.DataFrame(t["rows"], columns=t["columns"]).replace(PHONE, "[a phone number]", regex=True)
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

The fixed list below is the base everything else stands on: exact and residual duplicates, map points that were
impossible or outside India, and points moved to where the facility really is. What is left is mostly claims that
nobody can verify from the web, and the phone and opening-hours facts that no listing carries. That is why the
app says "call first", and section 6 measures how much of it remains.
""")

code('''
fixed, flagged, cannot = (how.table("REPORT.md", h) for h in ("Fixed", "Flagged", "Cannot be handled by cleaning"))
print(f"fixed: {len(fixed['rows'])} problems | flagged: {len(flagged['rows'])} | cannot be fixed by cleaning: "
      f"{len(cannot['rows'])}")
show_table(cannot)
test_eval = ROOT / "model/gold/v3/test_eval/results.json"
if test_eval.is_file():
    v = json.loads(test_eval.read_text())["verdicts"]
    print(f"What remains after cleaning: in the sealed TEST a web check found no decisive answer for {v['no_info']} of "
          f"{sum(v.values())} facility-service pairs ({v['no_info'] / sum(v.values()):.0%}).")
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

In plain words: for every facility and service the model adds up points, like a credit scorecard, and turns the
sum into a chance. It has three small scorecards, each a glass box:
- **offers:** does the facility really offer the service? This is the score the app shows (P_S).
- **location:** is the facility at the place the map says (P_L)?
- **exists:** is it a real, working facility (P_E)?

Each row of points comes from a named family of witnesses, for example the listing's own sentences about the
service, text that names another facility, a public list such as NABH or e-RaktKosh, the facility's own website,
or the public standard (IPHS) for a government hospital of that level. The rows on a card add up exactly to its
score; nothing is hidden.

**Fairness coding.** When a source cannot see a facility at all (no website of its own, a list that does not cover
its type, not a public hospital), its family is coded *not observable* and adds 0 points. A missing website never
counts against a small or public facility.

The weights are expert settings derived from audit rates, written down before the labels were read. The shipped
version, **A_platt**, adds one calibration step fitted on the DEV labels: every point is multiplied by the same
factor and one constant is added, so the card stays additive. The cells below read the frozen model card,
`derived/v2/model_card.json`.
""")

code('''
card = json.loads((ROOT / "derived/v2/model_card.json").read_text())
FAMILY = {"base": "base rate for the service", "T": "the listing's own text about the service",
          "C": "text that names another facility", "C_prior": "record breadth and operator (contamination prior)",
          "N": "non-offer cue (referral, camp, plan, negation)", "S": "scope (eye, dental, IVF or lab facility)",
          "P": "prerequisites (ICU, theatre, blood bank)", "X": "public and registry lists",
          "W": "the facility's own website", "O": "open data (OpenStreetMap, Wikidata)",
          "D": "dataset details (same text as T)", "K": "public standard (IPHS) for the facility's level",
          "R": "reader slot (weight 0, never fires)", "context": "facility level and type"}
platt = card["service_head"]["platt"]
print("model_version", card["model_version"])
print(f"offers head: {card['selected']} = {card['service_head']['base_scorecard']}, plus one Platt step "
      f"(a {platt['a']:.4f}, c {platt['c']:.4f}; fitted on {platt['fitted_on']})")
print("  what p means:", card["selected_meaning"])
print("location head:", card["location_head"]["shipped"])
print("exists head:", card["existence_head"])
print("labels:", card["label_provenance"]["wording"])
for c in card["caveats"]:
    print(" -", c)
fam = pd.DataFrame(card["per_family_points"])
fam.insert(1, "witness family", fam.family.map(FAMILY))
display(fam.rename(columns={"count": "terms", "min": "lowest points", "max": "highest points"}).set_index("family"))
''')

md("""
**How the shipped model was chosen.** The order of candidates and the rule were fixed before any were fitted:
- **A**, the expert prior scorecard;
- **A_platt**, A with one calibration step;
- **B**, a fitted monotone logistic scorecard, and **B_platt**;
- **C**, an explainable boosting machine (an additive glass-box model, interactions off).

The least-fitted candidate ships unless a more-fitted one lowers the out-of-fold log loss by at least one paired
cluster standard error. The headline labels are web checks with a decisive answer: confirmed against contradicted.
The base rate (a constant) is shown as a reference. Further C variants were run as ablations outside the
pre-set order and were not used for selection (`model/v2/final/SELECT.md`).
""")

code('''
def ci(v, d=3):
    return f"{v[0]:.{d}f} [{v[1]:.{d}f}, {v[2]:.{d}f}]"


sel, lp = card["selection_headline"], card["label_provenance"]
print("Rule:", card["selection_rule"])
print(re.search(r"Intervals: [^.]+\\.", (ROOT / "model/v2/final/SELECT.md").read_text()).group(0))
print(f"Headline labels: {lp['headline']['n']} decided DEV pairs, {lp['headline']['pos']} confirmed and "
      f"{lp['headline']['neg']} contradicted ({lp['wording']}). TEST pairs are excluded from every training row.")
CANDIDATES = ["A", "A_platt", "B", "B_platt", "C", "base_rate"]
display(pd.DataFrame([{"candidate": k, "out-of-fold log loss": ci(m["log_loss"]), "AUROC": ci(m["auroc"]),
                       "Brier": ci(m["brier"]), "ECE": ci(m["ece"])}
                      for k, m in sel["table"].items() if k in CANDIDATES]).set_index("candidate"))
for s in sel["selection"]["steps"]:
    print(f"{s['candidate']} against {s['incumbent']}: log loss {s['diff']:+.3f} (SE {s['se']:.3f}, "
          f"95% {s['ci95'][0]:+.3f} to {s['ci95'][1]:+.3f}): {'replaces' if s['replaces'] else 'does not replace'}")
sens = card["selection_sensitivity"]
print(f"Selected: {sel['selection']['selected']}. With 'searched and found nothing' counted as not offered "
      f"({sens['table']['A']['n']} pairs) the rule selects {sens['selection']['selected']} too.")
''')

md("""
**Calibration, bands and how many to call.** A score should come true about as often as it says. The table puts
the DEV pairs into score bins and compares the mean score with the share that was confirmed. The app shows
words, not raw scores: LIKELY, CALL FIRST, NO SERVICE TEXT or UNLIKELY, from thresholds chosen on DEV. Conformal
top-k says how many options to list so that a confirmed facility is among them most of the time.
""")

code('''
cal = pd.DataFrame(card["calibration_by_score_bin"])
cal["confirmed share"] = cal.k_confirmed / cal.n_decided
cal["95% interval"] = cal.wilson95.map(lambda w: f"{w[0]:.2f} to {w[1]:.2f}")
cal["score bin"] = cal.apply(lambda r: f"{r.p_min:.1f} to {r.p_max:.1f}", axis=1)
display(cal.set_index("score bin")[["n_decided", "k_confirmed", "k_contradicted", "mean_p", "confirmed share",
                                    "95% interval"]].round(3))
print("note:", card["calibration_note"])
fig, ax = plt.subplots(figsize=(4.2, 3.4))
err = [cal["confirmed share"] - cal.wilson95.map(min), cal.wilson95.map(max) - cal["confirmed share"]]
ax.errorbar(cal.mean_p, cal["confirmed share"], yerr=err, fmt="o", color="#4c72b0", capsize=3)
ax.plot([0, 1], [0, 1], ls="--", color="#999999")
ax.set_xlabel("mean score in the bin")
ax.set_ylabel("share confirmed")
ax.set_title("Calibration on DEV (out of fold)")
plt.tight_layout()
plt.show()

th, bt = card["thresholds"], card["band_thresholds"]
lk, ul = th["likely"], th["unlikely"]
print(f"LIKELY needs p >= {bt['likely']['p']:.4f}, location >= {bt['likely']['p_location']} and exists >= "
      f"{bt['likely']['p_exists']}. On DEV: {lk['k_correct']} of {lk['n']} LIKELY pairs confirmed "
      f"(95% {lk['wilson95'][0]:.3f} to {lk['wilson95'][1]:.3f}).")
print(f"UNLIKELY needs p <= {bt['unlikely']['p']:.2f}{' (fallback value)' if th['t_U_fallback'] else ''}. On DEV: "
      f"{ul['k_correct']} of {ul['n']} UNLIKELY pairs contradicted (95% {ul['wilson95'][0]:.3f} to {ul['wilson95'][1]:.3f}).")
print("rule:", bt["rule"])
bands = card["bands_all_pairs"]
print("all pairs by band:", ", ".join(f"{k} {v:,}" for k, v in bands.items()), f"(of {sum(bands.values()):,})")
for urgency, c in card["conformal"].items():
    print(f"conformal top-k, {urgency} ({', '.join(c['services'])}): list k = {c['k']}; a confirmed facility is "
          f"among them in {c['coverage_k']} of {c['n_queries']} DEV queries (95% from {c['coverage_wilson95'][0]:.2f}); "
          f"a random order of the same lists reaches {c['random_order_coverage']:.2f}")
print("note:", card["conformal_note"])
''')

md("""
**Public and private facilities.** Public facilities are few in the labels and nearly all confirmed, so we cannot
measure how well the score ranks them. The sentence below is the wording agreed on #79, with the numbers read
from the model card.
""")

code('''
pvp = card["public_vs_private"]
pub = pvp["public"]
print(f"On {pub['n']} labelled public pairs ({pub['contradicted']} contradicted) we could not show that the score "
      "ranks public facilities better than chance; the sample is too small to tell.")
print()
for op in ("public", "private"):
    m = pvp[op]["metrics"][card["selected"]]
    print(f"{op:8} {pvp[op]['n']:>4} pairs ({pvp[op]['confirmed']} confirmed, {pvp[op]['contradicted']} contradicted): "
          f"AUROC {ci(m['auroc'], 2)}, log loss {ci(m['log_loss'], 2)}")
''')

md("""
**One worked example.** The full ledger of one real pair, Sadar Hospital Gopalganj (a district hospital in Bihar;
its record name is printed below) for dialysis, read from `derived/v2/facility_service_scores.parquet`. Each row is
a witness with its points; the base and the rows add up to the score, which is checked below. `lo` and `hi` are the track record of the score bin
(the share confirmed among DEV pairs in the same bin), not an interval around p.
""")

code('''
scores = pd.read_parquet(ROOT / "derived/v2/facility_service_scores.parquet")
names = pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id", "name", "district"])
rec = names[names.name.str.contains("Sadar Hospital", na=False) & names.district.str.upper().eq("GOPALGANJ")]
assert len(rec) == 1, "the worked example should name exactly one record"
row = scores[scores.unique_id.eq(rec.unique_id.iloc[0]) & scores.service_id.eq("dialysis")].iloc[0]
PTS = card["per_term_weights"][0]["shipped_points"] / card["per_term_weights"][0]["shipped_logit"]  # points per logit
ledger = pd.DataFrame(json.loads(row.contributions))
ledger.insert(1, "witness family", ledger.family.map(FAMILY))
ledger["evidence"] = ledger.evidence_ids.map(len)
base_pts = row.base * PTS
total = base_pts + ledger.points.sum()
p_from_ledger = 1 / (1 + math.exp(-total / PTS))
print(f"{rec.name.iloc[0]} ({rec.district.iloc[0].title()}), dialysis: {row.band} {list(row.overlays)}, "
      f"operator {row.operator}")
with pd.option_context("display.max_colwidth", 70):
    display(ledger[["label", "witness family", "card_phrase", "evidence", "points"]].round(1))
print(f"base {base_pts:+.1f} + rows {ledger.points.sum():+.1f} = {total:+.1f} points; "
      f"p = 1 / (1 + exp(-points / {PTS:.2f})) = {p_from_ledger:.4f}; stored p = {row.p:.4f}")
assert abs(p_from_ledger - row.p) < 1e-9
print(f"location P_L {row.p_location:.3f}, exists P_E {row.p_exists:.3f}; score-bin track record {row.lo:.2f} to {row.hi:.2f}")
''')

md("""
**The frozen TEST.** Before any TEST label was read, the model was frozen: its version is a hash of the
parameters, thresholds and code, and its predictions for the sealed TEST pairs were committed with their SHA-256.
The TEST labels are web checks by agents, like DEV, so they are agent-labelled, not human-checked. TEST was opened
once, after the freeze; the cell checks both hashes and reads `model/gold/v3/test_eval/results.json`. The headline
metric is confirmed against contradicted.

Cleaning (section 3) already fixed duplicates, impossible or out-of-country map points and misplaced points. What
the model is left with is mostly claims that nobody can settle from the web (the "no decisive answer" share below)
and the phone and opening-hours facts that no listing carries. That is why the app's default is "call first".
""")

code('''
pred = ROOT / "model/v2/test_predictions.parquet"
sealed_sha = (ROOT / "model/v2/test_predictions.sha256").read_text().split()[0]
tp = pd.read_parquet(pred, columns=["pair_id", "model_version"])
print("model_version (model_card.json):", card["model_version"])
print(f"TEST predictions: {len(tp)} pairs, sha256 {sealed_sha}")
print("bytes match the committed sha256:", hashlib.sha256(pred.read_bytes()).hexdigest() == sealed_sha,
      "| written by this model_version:", set(tp.model_version) == {card["model_version"]})
TEST_EVAL = ROOT / "model/gold/v3/test_eval/results.json"
if not TEST_EVAL.is_file():
    print("TEST is sealed and not yet opened.")
else:
    te = json.loads(TEST_EVAL.read_text())
    assert te["model_version"] == card["model_version"] and te["test_predictions_sha256"] == sealed_sha
    print(f"Opened once, against these predictions (model/gold/v3/OPENING_LOG.md). {te['about']}")
    v = te["verdicts"]
    n_all = sum(v.values())
    print(f"Verdicts: {v['confirmed']} confirmed, {v['contradicted']} contradicted, and {v['no_info']} of {n_all} "
          f"({v['no_info'] / n_all:.0%}) with no decisive answer on the web.")

    def test_row(name, m):
        lk = m["LIKELY_confirmed"]
        return {"TEST pairs": name, "n": m["n"], "confirmed": m["confirmed"], "contradicted": m["contradicted"],
                "AUROC": f"{m['auroc']:.3f} [{m['auroc_ci95'][0]:.3f}, {m['auroc_ci95'][1]:.3f}]",
                "log loss": f"{m['log_loss']:.3f} [{m['log_loss_ci95'][0]:.3f}, {m['log_loss_ci95'][1]:.3f}]",
                "base-rate log loss": m["base_rate_log_loss"], "Brier": m["brier"], "ECE": m["ece5"],
                "LIKELY confirmed": f"{lk['k']} of {lk['n']}" + (f" ({lk['rate']:.3f} [{lk['ci95'][0]:.3f}, "
                                                                f"{lk['ci95'][1]:.3f}])" if lk["n"] else "")}

    ops, meth = te["by_operator_decided"], te["by_method_decided"]
    display(pd.DataFrame([test_row("headline: all decided", te["headline_decided"]),
                          *(test_row(f"{op} (decided)", ops[op]) for op in ("public", "private")),
                          *(test_row(f"labelled by {k} (decided)", m) for k, m in meth.items()),
                          test_row("sensitivity: no decisive answer = not offered", te["sensitivity_no_info_as_0"])])
            .set_index("TEST pairs"))
    pub = ops["public"]
    print(f"Public facilities: {pub['n']} decided pairs, AUROC interval {pub['auroc_ci95'][0]:.3f} to "
          f"{pub['auroc_ci95'][1]:.3f}: " + ("ranking shown." if pub["auroc_ci95"][0] > 0.5 else
                                          "it includes 0.5, so ranking public facilities is not shown."))
''')

md("""
**A negative result: the reader.** We fine-tuned a small transformer to read each sentence and say whether it is
about this facility and whether it offers the service. We trained MiniLM on the lead's Mac, and bge-small and
multilingual-e5 on a Databricks GPU. On the hand-labelled sentences none beats the rules where it
would have to (the F1 on the class that matters, label 0, with the paired bootstrap interval of the difference
above zero), and on "offers" every reader is far worse. So the model keeps the rules and the reader slot has
weight 0.
""")

code('''
RD = ROOT / "model/reader"
mac = json.loads((RD / "out/metrics_full.json").read_text())
gpu = json.loads((RD / "out_gpu/metrics_gpu_remaining.json").read_text())
gpu_name = re.search(r"NVIDIA [A-Z0-9]+", (RD / "out_gpu/nvidia_smi.txt").read_text()).group(0)
rules = mac["rules_on_hand_labels"]
out = [{"system": "rules (the bar)", "where": "-", "about_this F1": rules["about_this"]["class_0"]["f1"],
        "about_this minus rules": "-", "offers F1": rules["offers"]["class_0"]["f1"], "offers minus rules": "-"}]
for run, where in ((mac, f"{mac['hardware']['cpu']}, MPS"), (gpu, f"Databricks, {gpu_name}")):
    for name, r in run["runs"].items():
        row = {"system": name, "where": where}
        for head in ("about_this", "offers"):
            v = r["hand_labels"][head]
            d = v["reader_vs_rules"]["class_0"]
            row[f"{head} F1"] = v["reader"]["class_0"]["f1"]
            row[f"{head} minus rules"] = (f"{d['f1_reader_minus_rules']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]"
                                          + (" beats" if d["ci95"][0] > 0 else ""))
        out.append(row)
print(f"F1 on label 0 (about another facility / not an offer), {mac['eval_rows']} hand-labelled sentences; "
      "bracket = 95% paired bootstrap interval of reader minus rules")
display(pd.DataFrame(out).set_index("system"))
print("model card:", next(c for c in card["caveats"] if "reader" in c))
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
from facts.engine import Engine
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
        rng = "similar scores confirmed" if o["range_kind"] == "similar_scores" else "range"
        print(f"   {o['band_word'].upper()}: score {o['p']:.2f} ({rng} {o['p_lo']:.2f} to {o['p_hi']:.2f}); "
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
            print("  ", v["text"])
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
md("""
## 7b. What we compared against: not the nearest, not the unreachable best

The organizers clarified the impact criterion (#86): a tool that always sends people to the closest place is not
impactful, because it ignores everything else, and one that sends them to the best place on paper is not actionable
if they cannot reach it. So we compare the app with both, in two ways:
- **A simulated referral world** (`sim/`, #92). Each simulated world decides in secret which listings are true,
  simulated patients go through each referral policy (call, travel, turned away, try the next), and we count who
  reaches care within the time window. Several truth scenarios are always shown together, because one drawn from the
  model's own score would favour the app by construction. Everything from it is labelled SIMULATED.
- **Real data at the demo places** (`validation/policy_compare.py`, #93): the facility each policy picks first, its
  travel time against the service's window, and the published DEV label where one exists.
""")

code('''
SIM_FILES = [ROOT / "sim/out/metrics.parquet", Path("/Volumes/workspace/referral_saathi/uploads/sim/metrics.parquet")]
sim_file = next((p for p in SIM_FILES if p.is_file()), None)
if sim_file is None:
    print("SIMULATED results: pending. The simulation (#92) is not in this version of the repository yet.")
    print("When sim/out/metrics.parquet exists, this cell shows, for dialysis (planned) and trauma (emergency) in")
    print("Bihar and Uttar Pradesh, the share of simulated patients treated within the time window under each policy")
    print("(the app, the app offline, nearest, nearest + call first, best on paper), with seed-bootstrap intervals,")
    print("for scenarios S0-high and S0-low (base-rate bounds, read together), S1, S2 and S3. All of it SIMULATED.")
else:
    m = pd.read_parquet(sim_file)
    m = m[m.state.eq("ALL")] if "state" in m else m
    m = m.assign(v=[f"{r.treated_in_window:.2f} [{r.treated_in_window_lo:.2f}, {r.treated_in_window_hi:.2f}]"
                    for r in m.itertuples()])
    print(f"SIMULATED ({sim_file.name}): share treated within the time window, seed-bootstrap interval. "
          "S0-high and S0-low are base-rate bounds: read them together, never one alone.")
    display(m.pivot_table(index=["service", "policy"], columns="scenario", values="v", aggfunc="first"))
''')

md("""
**A method finding from the simulation (#92).** In an early run the app got fewer simulated trauma patients to care
within the window than the simple rule "nearest place that lists the service, call first". It held in every
scenario, including the one where the model's own scores are the truth. The cause is the ranking, not the model: it
traded extra travel for a higher score, while a phone call settles the question in a few minutes, so for an
emergency a nearer place that plausibly offers the service, called first, is worth more. For dialysis, a planned
service with a longer window, the score paid off. The decision on #92: for emergency services only, rank by the
expected chance of care within the window when calls go out nearest plausible place first (UNLIKELY pairs and
pairs with no quoted sentence excluded; the score as a filter and tie-break). Planned services keep the current
rule. The model itself (scores, bands and the frozen TEST predictions) does not change. The size of the gap depends
on the assumed call and turn-away constants, so it is reported as a simulated method finding, not as field evidence.
""")

code('''
pc = ROOT / "validation/out/policy_compare.csv"
if not pc.is_file():
    print("REAL DATA policy comparison: pending (run validation/policy_compare.py, #93; its CSV is not committed yet).")
    print("It will show, per policy (app, nearest, best on paper) at the demo places: answers, median travel minutes,")
    print("how many first picks are inside the service's time window, how many are LIKELY, and the published DEV")
    print("labels (confirmed or contradicted) where they exist. Real data, not simulated.")
else:
    d = pd.read_csv(pc)
    d = d[d.facility.notna() & d.facility.ne("")]
    print("REAL DATA at the demo places, not simulated; gold = published DEV labels only, so coverage is small")
    display(d.groupby("policy").agg(answers=("service", "size"), median_minutes=("minutes", "median"),
                                    in_window=("in_window", "sum"), likely=("band", lambda b: int((b == "LIKELY").sum())),
                                    gold_confirmed=("gold", lambda g: int((g == "confirmed").sum())),
                                    gold_contradicted=("gold", lambda g: int((g == "contradicted").sum()))))
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
md("""
## 9. Limits

The dataset the app uses is much cleaner than the one we were given: the first cell below shows what the cleaning
fixed. What remains is mostly service claims nobody can verify from the web, plus phone and hours facts no listing
carries. That is why the app says "call first". Every number is read from the named file.
""")

code('''
geo = json.loads((ROOT / "cleaning/geo_identity/summary.json").read_text())
far = geo["coords_gt50km_from_pin_before(audit)_after(repaired)"]
busy = geo["busy_pins_gt25km_from_facility_median_before_after"]
print("What the cleaning fixed (cleaning/geo_identity/summary.json, before -> after):")
for label, (a, b) in [("duplicate records", geo["rows_before_after_dedup"]),
                      ("map points outside India", geo["coords_outside_india_before_used_after"]),
                      ("records with a resolved state", geo["stated_state_resolved_before_after"])]:
    print(f"  {label:58} {a:>6,} -> {b:,}")
print(f"  {'listing points > 50 km from their PIN (repaired PIN centres)':58} {far[0][0]:>6,} -> {far[1][0]:,}"
      f"  (of {far[0][1]:,} -> {far[1][1]:,} measurable)")
print(f"  {'busy PIN centres > 25 km from their facilities median':58} {busy[0]:>6,} -> {busy[1]:,}  (of {busy[2]:,})")
''')

code('''
h = json.loads((ROOT / "app/howto/out/how.json").read_text())["facts"]
test = json.loads((ROOT / "model/gold/v3/test_eval/results.json").read_text())
dev = json.loads((ROOT / "model/gold/v3/dev_labels.json").read_text())["report"]
v, ni = test["verdicts"], test["no_info_by_operator"]
pub, prv = test["by_operator_decided"]["public"], test["by_operator_decided"]["private"]
nst = test["headline_decided"]["NO_SERVICE_TEXT_confirmed"]
trust = geo["trust"]
n_rec = geo["rows_before_after_dedup"][1]
lc = geo["loc_conf"]
src = geo["loc_src"]
cap = next(r for r in how.table("REPORT.md", "Service claim evidence")["rows"] if r[0] == "claims-09")[2]
cap = cap.split(";")[0]
assert cap.startswith("Capacity missing"), cap
ci = lambda x: f"[{x[0]:.3f}, {x[1]:.3f}]"  # noqa: E731
n_test = sum(v.values())
print("What remains (gold v3: model/gold/v3/test_eval/results.json and dev_labels.json):")
print(f"- Service claims are mostly unverifiable: {v['no_info']} of {n_test} TEST pairs "
      f"({v['no_info'] / n_test:.0%}) are no_info; public {ni['public']['rate']:.0%}, private "
      f"{ni['private']['rate']:.0%}. DEV: {dev['verdicts']['no_info']} of {dev['pairs']} ({dev['no_info_rate']:.0%}).")
print(f"- Public facilities, ranking not shown: TEST AUROC {pub['auroc']:.3f} {ci(pub['auroc_ci95'])} on "
      f"{pub['n']} decided public pairs; the interval includes 0.5, as on DEV. "
      f"Private: {prv['auroc']:.3f} {ci(prv['auroc_ci95'])}.")
print(f"- Listings omit services: {nst['k']} of {nst['n']} decided TEST pairs with no sentence of their own about "
      "the service (NO_SERVICE_TEXT) were confirmed on the web.")
print(f"- Phones are unverified: {trust['records_with_display_phone']:,} of {n_rec:,} records "
      f"({trust['records_with_display_phone'] / n_rec:.0%}) list a number; none has been checked to reach the "
      "facility.")
print(f"- Locations: {lc['low'] + lc['disputed']:,} map points are low-confidence ({lc['low']:,}) or disputed "
      f"({lc['disputed']:,}); {src['postcode_centre']:,} sit at a postcode centre and {src['address_city_centre']:,} "
      "at a city centre.")
print(f"- No checked opening hours, 24x7 status or live capacity: the provided table has no hours field; "
      f"{h['hours_records']['value']:,} of {h['hours_records']['of']:,} records say anything about hours, only in "
      "free text, and OpenStreetMap adds 134 opening_hours facts (kb/opendata/OPENDATA.md); none is checked. Bed "
      f"capacity: {cap.lower()} raw records (REPORT.md claims-09). Nothing says whether a bed or a slot is free today.")
print("- Gold labels are agent-made from public web pages, not phone calls or visits. A human spot-check of 25 pairs "
      "is set up (PR #105, model/gold/v3/human_check/) and not yet done.")
print(f"- Thin rural coverage: {h['bihar_records']['value']:,} of {h['bihar_records']['of']:,} records are in Bihar.")
bands = card["bands_all_pairs"]
print(f"- Model v2 bands {bands['LIKELY']:,} of {sum(bands.values()):,} facility-service pairs Likely; everything else "
      "asks for a call first or says no.")
print("- Travel times are rough estimates (straight line times a road factor), shown as ranges.")
''')

md("""
**Paths forward.** The app's call-outcome reports (#65, section 9b) are the path for phones, hours and
turn-aways. An official public-facility source, such as state health department lists, is future work.
""")

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 9b. Field reports

Health workers already know which hospitals took their patients. The app lets them say so with fixed choices only,
no star ratings and no free text: after a call ("Said yes", or "Said no" with an optional reason) and after a
referral ("Accepted" or "Turned away", with a reason and the wait). Each report is one row in `call_outcomes`, keyed
by a one-way hash of the signed-in user, never the user, the patient or a phone number.

Reports enter the score as **one more row of the ledger**, "Field reports", so the card still adds up to the score
it shows (`app/community/field.py`, `field_adjust`):
- **A Beta update.** The model's score counts as N0 earlier reports. N0 is an assumption, not a measurement.
- **Weights.** An accepted visit counts in full and a phone "yes" at half weight, because a receptionist's yes is not
  a confirmation. A "does not offer" reason counts in full after a visit and at half weight on the phone. Older
  reports fade, and each reporter counts once.
- **A minimum number of distinct reporters** before anything moves, so one person cannot change a public verdict
  about a real hospital.
- **Temporary reasons** (no bed, doctor away, machine down, asked to pay, closed) never lower the score. They show
  only as a dated note about availability.
- **Never raise a band.** Reports can take a Likely pair below the Likely line, which turns it into "Not verified:
  call first". Every other band stays as the model set it, even when the reports are good.
- **The disagree rule.** When the reports against outweigh the reports for, the card says "Reports disagree with the
  listing: call first". Reports alone never make a public "Unlikely", and without listing text they never lift a
  pair to Likely.

The cell prints these settings from the code and runs `field_adjust` on a synthetic example: invented reporters
about an unnamed facility, not real reports.
""")

code('''
from datetime import UTC, datetime, timedelta

from community import field
from facts.engine import _logit
from outcomes import REASONS_TEMPORARY

print(f"N0 = {field.N0:g} (assumption) | phone yes weight {field.PHONE_WEIGHT:g} | at least {field.MIN_REPORTERS} "
      f"distinct reporters | half-life {field.HALF_LIFE_DAYS:g} days over {field.WINDOW_DAYS} days | notes for "
      f"{field.NOTE_DAYS} days | temporary reasons: {', '.join(REASONS_TEMPORARY)}")
print(f"Likely line used by the rebanding rule {field.T_LIKELY:.2f}; reports alone never go below {field.T_UNLIKELY:.2f}")

NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)  # SYNTHETIC: a fixed clock, so the example output never changes


def report(who, days_ago, kind, outcome, reason=None):
    return {"reporter_key": who, "created_at": NOW - timedelta(days=days_ago), "kind": kind, "outcome": outcome,
            "reason": reason}


SYNTHETIC = [  # (case, model p, model band, listing has text, reports): all invented
    ("one reporter says not offered", 0.85, "LIKELY", True, [report("r1", 2, "visit", "turned_away", "service_not_here")]),
    ("two not offered, one phone yes", 0.85, "LIKELY", True,
     [report("r1", 2, "visit", "turned_away", "service_not_here"), report("r2", 5, "visit", "turned_away", "equipment_absent"),
      report("r3", 1, "call", "yes")]),
    ("four turned away: not offered", 0.85, "LIKELY", True,
     [report(f"r{i}", i, "visit", "turned_away", "service_not_here") for i in (1, 2, 3, 4)]),
    ("two temporary reasons", 0.85, "LIKELY", True,
     [report("r1", 1, "visit", "turned_away", "no_bed"), report("r2", 3, "call", "no", "doctor_absent")]),
    ("three accepted, no listing text", 0.65, "NO_SERVICE_TEXT", False,
     [report(f"r{i}", i, "visit", "accepted") for i in (1, 2, 3)]),
]
print("\\nSYNTHETIC example (invented reports, unnamed facility):")
for case, p0, band, has_text, reps in SYNTHETIC:
    r = field.field_adjust(p0, reps, NOW, has_text=has_text, likely=band == "LIKELY")
    assert abs(_logit(p0) + r["term"] - _logit(r["p"])) < 1e-9  # the ledger row keeps the card additive
    after = "CALL_FIRST (Not verified)" if r["rebanded"] else band
    print(f"\\n- {case}: {r['n_reporters']} reporter(s) counted; p {p0:.2f} -> {r['p']:.3f} "
          f"(Field reports row {r['term']:+.3f} logit); band {band} -> {after}")
    for line in r["lines"] + r["notes"]:
        print("    ", line["en"])
''')

md("""
**Area pulse.** Coordinators and district planners see counts per district and service, never single reports.
Small cells are hidden (k-anonymity), a facility or reason cell needs more reporters than a district cell, and a
shown total never lets a hidden cell be recovered by subtraction. The rules below are read from
`app/community/pulse.py`, and the known limit from `app/README.md`.
""")

code('''
from community import pulse

app_readme = (ROOT / "app/README.md").read_text()
print(f"district x service cell: at least {pulse.MIN_REPORTERS} distinct reporters and {pulse.MIN_REPORTS} reports")
print(f"facility or reason cell: at least {pulse.DETAIL_REPORTERS} distinct reporters and {pulse.DETAIL_REPORTS} reports")
print(f"one window: the last {pulse.WINDOW_DAYS} days in whole weeks; every answer says: {pulse.HIDDEN_NOTE['en']}")
limit = re.search(r"Known limit \\(COMMUNITY_CHECK\\.md 2E\\): (.+?)\\n  - ", app_readme, re.S).group(1)
print("\\nKnown limit (2E):", " ".join(limit.split()))
''')

# ---------------------------------------------------------------------------------------------------------------------
md("""
## 10. How to open the app

The app runs as a Databricks App, `referral-saathi`, in the team's workspace. Judges get access as workspace
users. It is built for a phone:
- **Start:** tap a service; the app uses GPS, or a PIN code, village or district.
- **Voice:** speak in Hindi or English. Speech is turned into text on the app server (Whisper), in the language the
  user chose, never guessed; the audio is decoded in memory and never stored or logged. The text goes into the text
  box, where it can be fixed, and the app reads its answers aloud.
- **Results:** whom to call first, with the evidence on each card; "Why this?" opens the full WHY and HOW.
- **Offline, across state borders:** after one online visit the phone saves its own state's facility data and the
  data of every neighbouring state with a facility within the search radius, so answers keep working without
  internet, including when the nearest facility is across the border.
- **Family journey card:** "Send to family" makes one self-contained page with the emergency numbers first, then the
  stops in order with phone, address and map links, what to bring and what to ask. It opens on any phone without a
  login and makes no network requests. It holds no patient data and no scores.
- **"How this works":** in the header, this notebook's story in plain words.

To run it locally: `.venv-app/bin/python -m uvicorn app:app` from `app/` (see `app/README.md`). The numbers below
are read from the code, `app/README.md`, `app/voice/VOICE_CHECK.md` and `submission/measured_on_databricks.json`.
""")

code('''
from facts.engine import RADIUS_KM
from voice.transcribe import MODEL as WHISPER_MODEL

dep = json.loads((ROOT / "submission/measured_on_databricks.json").read_text())
v = dep["voice"]
check = (ROOT / "app/voice/VOICE_CHECK.md").read_text()
clip_s = [float(re.search(rf"^\\| {c['clip']} \\([^)]*\\) \\| {c['lang']} \\| ([\\d.]+) \\|", check, re.M).group(1))
          for c in v["clips"]]
right = [c for c in v["clips"] if c["parsed"] == c["expected"]]
print(f"Voice: faster-whisper '{WHISPER_MODEL}' on the app server, language forced to the user's choice, audio never "
      "stored.")
print(f"  measured on the deployed app ({v['machine']}): {v['latency_s'][0]} to {v['latency_s'][1]} s per request for "
      f"clips of {min(clip_s)} to {max(clip_s)} s; {len(right)} of {len(v['clips'])} test clips parsed to the right "
      f"service ({', '.join(c['clip'] + ' ' + c['lang'] + ' -> ' + c['parsed'] for c in right)})")
print(f"  source: {dep['source']}")
border = re.search(r"Of the ([\\d,]+) PIN centroids within (\\d+) km of a state border.*?for ([\\d.]+)% of \\(PIN, "
                   r"service\\) pairs \\(([\\d,]+) of ([\\d,]+)", app_readme, re.S)
n_pins, km, pct, k, n = border.groups()
assert abs(100 * int(k.replace(",", "")) / int(n.replace(",", "")) - float(pct)) < 0.05
print(f"Offline packs: the phone saves every state pack with a facility within {RADIUS_KM} km of the fix. Of "
      f"{n_pins} PIN centroids within {km} km of a state border, the nearest facility offering the service is in "
      f"another state for {pct}% of (PIN, service) pairs ({k} of {n}; app/README.md).")
''')

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
