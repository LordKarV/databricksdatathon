"""Write and run submission/02_simulation.ipynb, the simulation appendix (issue #92). Every number in it is SIMULATED.

Same pattern as submission/build_notebook.py: the cells live here as plain strings, the script writes the .ipynb,
executes it with the local kernel and saves it with outputs.
    .venv-app/bin/python submission/build_sim_notebook.py            # write + execute
    .venv-app/bin/python submission/build_sim_notebook.py --no-run   # write only
On Databricks the notebook takes the run size from widgets and writes to the team volume.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent
NB = HERE / "02_simulation.ipynb"
MAX_MB = 5

CELLS: list[tuple[str, str]] = []


def md(s: str) -> None:
    CELLS.append(("md", s.strip("\n")))


def code(s: str) -> None:
    CELLS.append(("code", s.strip("\n")))


md("""
# Appendix: a simulated referral world

**Simulated. Not field results.** Nothing on this page was observed in the field. Every number comes from a
simulation in which we invent the truth about each facility, then send simulated patients to them.

**Why simulate?** To answer the question a judge would ask: does the app get more patients to care in time than
sending them to the nearest listing, or to the "best" hospital on paper? Since the true answer is unknown for real
facilities, we invent several hidden truths and check whether the answer changes between them.

**Four hidden truths (scenarios), the first as two bounds.** Each result is shown for all of them, never for one
alone:
- **S0, "the text says nothing":** whether a facility offers the service depends only on the service and on the
  operator (public, private, unknown). Listing sentences and model scores carry no information. This is where the
  app can lose. The rate comes from few hand checks (about 15 decided pairs per service), so S0 is two bounds,
  always read together (simulated, base-rate bounds):
  - **S0-high:** confirmed among the decided checks (a "no information" check is left out);
  - **S0-low:** a "no information" check counts as "does not offer".
- **S1, "the model is right":** each facility offers the service with the probability our model gives. This is
  the app's best case, and circular, so it is never shown alone.
- **S2, "from our hand checks":** offer rates by service and by evidence stratum (strong, weak, suspect, not
  mentioned), from the web-checked DEV pairs. It does not use the model's scores.
- **S3, "the data is as bad as the audit says":** S2, plus sentences attributed to another facility are false,
  and map points are wrong at the rate measured on the cleaned data (#103): 6 of 30 points the cleaning moved,
  6 of 8 kept points marked low or disputed in the geo audit, none of the rest (the true point is 25 km away).

S2 and S3 come from the same DEV labels the model's calibration step was fitted on, so they favour the app by
construction; S0 does not.

**Policies compared**, each trying at most 3 facilities before calling 108:
- **app:** the app as shipped (online answer; the offline state pack when there is no mobile data), phoning ahead;
- **app_offline:** the state pack only;
- **nearest:** the 3 nearest listings that name the service (by estimated travel time), no phone call;
- **nearest_call_first:** the same, phoning each one first like the app, so we can tell the value of the ranking
  from the value of calling ahead;
- **best_on_paper:** the 3 highest-scored listings in the state, ignoring distance.

Method, assumptions and honesty rules: [`sim/README.md`](../sim/README.md). Issue #92.
""")

code('''
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ON_DATABRICKS = "DATABRICKS_RUNTIME_VERSION" in os.environ
ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "sim" / "run.py").is_file())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from sim import world  # noqa: E402

if ON_DATABRICKS:
    dbutils.widgets.text("seeds", "20")  # noqa: F821 (dbutils is predefined on Databricks)
    dbutils.widgets.text("cases_per_seed", "200")  # noqa: F821
    SEEDS = int(dbutils.widgets.get("seeds"))  # noqa: F821
    CASES = int(dbutils.widgets.get("cases_per_seed"))  # noqa: F821
    OUT = Path("/Volumes/workspace/referral_saathi/uploads/sim")
else:  # the environment can change the run size
    SEEDS = int(os.environ.get("SIM_SEEDS", "20"))
    CASES = int(os.environ.get("SIM_CASES", "200"))  # per state x service x seed
    OUT = ROOT / "sim" / "out"
OUT.mkdir(parents=True, exist_ok=True)
SCENARIOS = list(world.SCENARIOS)  # S0-high, S0-low, S1, S2, S3
STATES = ["BIHAR", "UTTAR PRADESH"]
SERVICES = ["dialysis", "trauma_emergency"]
shown = OUT if ON_DATABRICKS else OUT.relative_to(ROOT)
print(f"SIMULATED run: {SEEDS} seeds x {CASES} cases per state and service, {STATES}, {SERVICES}, "
      f"output {shown}")
''')

md("""
## The run

For each seed: one set of simulated patients (origins at PIN code centres in Bihar and Uttar Pradesh, from
`sim/world.py`), the same for every policy and every scenario. Each policy picks its facilities once; the
scenario's hidden truth then decides what happens on the phone and at the door (`sim/execute.py`). The same coin
flips apply to the same patient at the same facility under every policy (common random numbers), so differences
come from the policies. Intervals are 90% seed-bootstrap intervals.
""")

code('''
from sim.run import simulate, sweep_verdicts, table

res = simulate(SCENARIOS, list(range(SEEDS)), CASES, STATES, SERVICES, OUT, n_boot=500, sweep=True, verbose=False)
print("SIMULATED. World and truth: sim/world.py; executor: sim/execute.py; baselines: sim/policies_baseline.py")
print(f"{len(res['cases']):,} simulated cases, {len(res['events']):,} simulated events, {res['seconds']:.0f} s")
''')

md("""
## Simulated outcomes, by scenario

*Treated in window*: share of patients treated within the time window (60 min for trauma, 120 min for dialysis).
*Wasted trips*: arrivals turned away. *Unsafe first stop*: the first place travelled to does not exist or does not
offer the service. *Gave up*: three facilities tried without treatment (or time ran out), so the worker calls 108.
Both states pooled. S0-high and S0-low are printed together: they are bounds, not two results.
""")

code('''
t = table(res["metrics"])
with pd.option_context("display.width", 250, "display.max_columns", 20):
    print("\\n=== S0, the text says nothing (SIMULATED, base-rate bounds: read high and low together) ===")
    print(t[t.scenario.str.startswith("S0")].sort_values(["service", "policy", "scenario"]).to_string(index=False))
    for sc in [s for s in SCENARIOS if not s.startswith("S0")]:
        print(f"\\n=== {sc} (SIMULATED, not field results) ===")
        print(t[t.scenario == sc].drop(columns="scenario").to_string(index=False))
''')

code('''
m = res["metrics"]
m = m[m.state == "ALL"]
policies = ["app", "app_offline", "nearest_call_first", "nearest", "best_on_paper"]
panels = ["S0", *[s for s in SCENARIOS if not s.startswith("S0")]]
fig, axes = plt.subplots(len(SERVICES), len(panels), figsize=(13, 4.8), sharex=True, sharey=True)
for i, svc in enumerate(SERVICES):
    for j, sc in enumerate(panels):
        ax = axes[i, j]
        d = m[m.service == svc]
        for k, pol in enumerate(policies):
            color = "#2a78d6" if pol == "app" else "#8a8984"
            if sc == "S0":  # the base-rate bounds: S0-low to S0-high, each a point estimate
                lo, hi = (100 * d[(d.scenario == b) & (d.policy == pol)].treated_in_window.iloc[0]
                          for b in ("S0-low", "S0-high"))
                ax.plot([lo, hi], [k, k], color=color, lw=3, alpha=0.45, solid_capstyle="round")
                ax.plot([lo, hi], [k, k], "o", ms=6, color=color, mec="white", mew=1.5)
                continue
            r = d[(d.scenario == sc) & (d.policy == pol)].iloc[0]
            ax.plot([100 * r.treated_in_window_lo, 100 * r.treated_in_window_hi], [k, k], color=color, lw=3,
                    solid_capstyle="round")
            ax.plot(100 * r.treated_in_window, k, "o", ms=6, color=color, mec="white", mew=1.5)
        ax.set_yticks(range(len(policies)), policies)
        ax.set_ylim(len(policies) - 0.5, -0.5)  # app on top
        ax.grid(axis="x", color="#e6e5e0", lw=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        if i == 0:
            ax.set_title("S0: low to high bound" if sc == "S0" else sc, fontsize=11)
        if j == 0:
            ax.set_ylabel(svc.replace("_", " "), fontsize=10)
        if i == len(SERVICES) - 1:
            ax.set_xlabel("treated in window, % (90% CI)", fontsize=9)
fig.suptitle("SIMULATED, not field results: share treated in time per hidden-truth scenario "
             "(S0: simulated, base-rate bounds; others: 90% CI)", fontsize=12)
fig.tight_layout()
(OUT / "figures").mkdir(exist_ok=True)
fig.savefig(OUT / "figures" / "sim_treated_in_window.png", dpi=150)
plt.show()
''')

md("""
## How much depends on the assumptions

The world needs numbers nobody has measured: how often a facility accepts a patient, how often a listed phone number
reaches it, how often a "yes" on the phone is wrong, and how often a facility is open (`world.KNOBS`). Each is set
low, middle and high in turn, with the others at the middle. The table shows **app minus nearest_call_first**, in
percentage points of patients treated in window, with a 90% interval. A level where the interval reaches zero or
below is a point where the app no longer beats the nearest listing called ahead.
""")

code('''
s = res["sensitivity"].copy()
s["cell"] = ((100 * s["diff"]).round(1).astype(str) + " [" + (100 * s.diff_lo).round(1).astype(str) + ", "
             + (100 * s.diff_hi).round(1).astype(str) + "]" + s.app_beats.map({True: "", False: " *"}))
print("SIMULATED. app minus nearest_call_first, treated in window (points). * = app does not clearly beat it.")
with pd.option_context("display.width", 250, "display.max_columns", 20):
    print(s.pivot_table(index=["knob", "level"], columns=["scenario", "service"], values="cell",
                        aggfunc="first").to_string())
print("\\nVerdict at the middle assumptions, and the swept levels where it changes (SIMULATED):")
with pd.option_context("display.width", 250, "display.max_colwidth", 120):
    print(sweep_verdicts(res["sensitivity"]).to_string(index=False))
''')

md("""
## Limits

- **Simulated, not field results.** The hidden truths are built from our own data and the hand-checked DEV pairs;
  a real referral network will differ.
- Patients are drawn uniformly over PIN code centres, not by population (no population table is in the repo).
  Travel time is the travel estimate's middle value, with no spread.
- The call, turn-away and give-up times and the four swept knobs are assumptions; the size of any gap depends on
  them (see the sweep above). The S0 rate rests on about 15 decided checks per service, hence the two bounds.
- Two services and two states only. "App + field reports" and the multi-stop planner route are future work.
- S1 is circular: it assumes the model is right. Read it next to S0, where the listing text says nothing.
""")


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
        NotebookClient(nb, timeout=1800, kernel_name=args.kernel, resources={"metadata": {"path": str(HERE)}}).execute()
        nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
        errors = [o for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", [])
                  if o.get("output_type") == "error"]
        if errors:
            print(f"errors: {len(errors)}", file=sys.stderr)
            nbformat.write(nb, NB)
            return 1
    nbformat.write(nb, NB)
    print(f"wrote {NB.name}: {len(nb.cells)} cells, {NB.stat().st_size / 1e6:.2f} MB")
    return 0 if NB.stat().st_size / 1e6 < MAX_MB else 1


if __name__ == "__main__":
    raise SystemExit(main())
