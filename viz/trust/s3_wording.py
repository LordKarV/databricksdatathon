"""Story 3: strong-looking evidence is mostly wording.

Chart s3_wording, two panels per service:
- left: under the first (audit) grader, the share of "strong" grades whose clinical
  prerequisite was met only by the claim sentence itself ("Dialysis unit" satisfies
  "dialysis unit or machine"). Counts read from audit/claims/verify/out/v_grades.json
  (written by audit/claims/verify/v_grades.py; not recomputed here).
- right: after the fix (derived/v1/grades.parquet, grader v2, 4,151 strong grades), the
  share still held up only by a specialty tag or by claim sentences of 3 words or fewer.

Run: .venv-viz/bin/python viz/trust/s3_wording.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import trust_io as io
import style as S

NAMES = {"dialysis": "Dialysis", "mri": "MRI", "trauma": "Trauma", "icu": "ICU", "nicu": "NICU",
         "cardiac_surgery": "Cardiac surgery", "burns": "Burns", "csection": "C-section"}
SHORT_WORDS = 3


def with_ci(df, k, n):
    out = df.copy()
    out[["rate", "lo", "hi"]] = [S.wilson(int(a), int(b)) for a, b in zip(df[k], df[n])]
    return out


def circular():
    c = io.load_json("circularity")["prereq_circularity"]
    d = pd.DataFrame([dict(service=s, k=v["strong_with_circular_prereq"], n=v["strong"]) for s, v in c.items()])
    tot = pd.DataFrame([dict(service="all", k=d.k.sum(), n=d.n.sum())])
    return with_ci(pd.concat([d, tot], ignore_index=True), "k", "n")


def after_fix():
    g = io.load("grades", ["unique_id", "service", "grade", "cite_evidence", "corr_tags_only"])
    s = g[g.grade == "strong"].copy()
    ev = s.cite_evidence.map(json.loads)
    s["short_only"] = ev.map(lambda L: len(L) > 0 and all(len(e["text"].split()) <= SHORT_WORDS for e in L))
    s["thin"] = s.short_only | s.corr_tags_only
    d = s.groupby("service").agg(k=("thin", "sum"), n=("thin", "size"), k_tag=("corr_tags_only", "sum"),
                                 k_short=("short_only", "sum")).reset_index()
    tot = pd.DataFrame([dict(service="all", k=d.k.sum(), n=d.n.sum(), k_tag=d.k_tag.sum(), k_short=d.k_short.sum())])
    examples = ev[s.short_only].map(lambda L: L[0]["text"]).value_counts().head(6)
    return with_ci(pd.concat([d, tot], ignore_index=True), "k", "n"), examples


def panel(ax, d, order, col, title, xlabel):
    d = d.set_index("service").loc[order]
    y = np.arange(len(order))[::-1]
    S.add_interval(ax, y, d.lo * 100, d.hi * 100, horizontal=True, cap=0, lw=2, color=S.AXIS)
    is_all = np.array([s == "all" for s in order])
    ax.plot(d.rate[~is_all] * 100, y[~is_all], "o", color=col, ms=8, zorder=4)
    ax.plot(d.rate[is_all] * 100, y[is_all], "D", color=S.INK, ms=8, zorder=4)
    for yi, (s, r) in zip(y, d.iterrows()):
        small = "; small n" if r.n < S.SMALL_N else ""
        ax.annotate(f"{r.rate * 100:.0f}%  ({int(r.k):,} of {int(r.n):,}{small})", (r.hi * 100, yi), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=10.5, color=S.INK,
                    fontweight="bold" if s == "all" else "normal")
    ax.axhline(y[0] - 0.5, color=S.GRID, lw=1)
    ax.set_yticks(y, ["All 8 services" if s == "all" else NAMES[s] for s in order])
    ax.set_xlim(0, 135)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)
    S.panel_title(ax, title)


def run():
    c = circular()
    a, examples = after_fix()
    order = ["all"] + list(c[c.service != "all"].sort_values("rate", ascending=False).service)
    fig, (l, r) = S.new_figure(size=(12, 6.9), ncols=2, sharey=False)
    panel(l, c, order, S.SEMANTIC["unlikely"], "Before: first grader, strong grades",
          "Prerequisite met only by the claim sentence\nitself (%, 95% Wilson interval)")
    panel(r, a, order, S.SEMANTIC["flagged"], "After the fix: grader v2, strong grades",
          f"Held up only by a specialty tag or by claims of\n{SHORT_WORDS} words or fewer (%, 95% Wilson interval)")
    r.set_yticklabels([])
    ca, aa = c.set_index("service").loc["all"], a.set_index("service").loc["all"]
    S.fig_title(fig, f"A 'strong' grade often means a phrase that names the service: {int(ca.k):,} of {int(ca.n):,} "
                     f"first-grader strong grades met their clinical check with the claim's own words; after the fix, "
                     f"{int(aa.k):,} of {int(aa.n):,} still rest on a tag or a short phrase")
    ex = ", ".join(f'"{t}" ({n})' for t, n in examples.items())
    io.note(fig, f"Left: audit/claims/verify/out/v_grades.json (prereq_circularity; e.g. 'Dialysis unit' counted as "
                 f"both the claim and its 'dialysis unit or machine' prerequisite). Right: derived/v1/grades.parquet, "
                 f"grade = strong; tag only = corr_tags_only; short = every cited evidence sentence has 3 words or "
                 f"fewer. Most common short claims: {ex}.", width=180)
    tidy = pd.concat([c.assign(panel="first_grader_circular_prereq"),
                      a.assign(panel="v2_strong_tag_or_short_only")])
    io.write_csv(tidy[["panel", "service", "k", "n", "rate", "lo", "hi", "k_tag", "k_short"]], "s3_wording")
    alt = (f"Two dot plots by service. Left: under the first grader, {int(ca.k):,} of {int(ca.n):,} strong grades "
           f"({ca.rate * 100:.0f}%) met their clinical prerequisite only through the claim sentence itself; dialysis "
           f"345 of 355, trauma 340 of 353, MRI 433 of 530, but C-section 1 of 23. Right: after prerequisites were "
           f"restricted to other sentences and tags, {int(aa.k):,} of {int(aa.n):,} strong grades ({aa.rate * 100:.0f}%) "
           f"are still held up only by a specialty tag or by claims of three words or fewer such as 'Dialysis' or "
           f"'MRI scanner'; dialysis {int(a.set_index('service').loc['dialysis'].k)} of "
           f"{int(a.set_index('service').loc['dialysis'].n)}.")
    S.save(fig, io.out("s3_wording"), alt)
    print("s3", ca.to_dict(), aa.to_dict())
    return dict(circular=c, after=a)


if __name__ == "__main__":
    run()
