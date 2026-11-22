"""Story 6: hours. How many facilities have any stated hours or 24x7 evidence, by source, and do sources agree.

Sources (each a facility-level fact table, usable rows only):
  dataset text  kb/vf_details/out/facility_details.parquet (n_usable > 0)
  own website   kb/web_evidence/out/web_facility_details.parquet (attributable pages only, n_usable > 0)
  OpenStreetMap kb/opendata/vf_opendata_facts.parquet (source osm: is_24x7, opening_hours, emergency tag)
Measures per record: a 24x7 statement (any unit except helpline and home care), 24x7 emergency, a clock-time schedule
(OPD, general, doctor sessions, lab, pharmacy, dialysis; not helpline or visiting hours), and any of these.
OSM has no "24x7 emergency" field: its row uses emergency=yes (a tag that an emergency department exists).
Outputs: charts/s6_hours.{png,svg,txt}, data/s6_hours_by_source.csv, data/s6_emergency_agreement.csv,
data/s6_facility_hours.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import claims_io as io
from claims_io import S

NOT_FACILITY_24 = {"helpline", "home_care"}
NOT_SCHEDULE = {"helpline", "visiting"}
MEASURES = [("any_hours", "Any hours or 24x7 statement"), ("any24", "A 24x7 statement"),
            ("emerg24", "24x7 emergency"), ("schedule", "A clock-time schedule (OPD etc.)")]
SOURCES = [("dataset", "Dataset text", S.CATEGORICAL[0]), ("web", "Own website", S.CATEGORICAL[1]),
           ("osm", "OpenStreetMap", S.CATEGORICAL[2]), ("any", "Any of the three", S.INK_2)]


def facts_sets(df: pd.DataFrame) -> dict:
    d = df[df.n_usable > 0]
    h24 = d[(d.fact_type == "hours_24x7") & ~d.attribute.isin(NOT_FACILITY_24)]
    sch = d[d.fact_type.isin(["opd_hours", "hours_dialysis_shifts"]) & ~d.attribute.isin(NOT_SCHEDULE)]
    out = {"any24": set(h24.unique_id), "emerg24": set(h24[h24.attribute == "emergency"].unique_id),
           "schedule": set(sch.unique_id)}
    out["any_hours"] = out["any24"] | out["schedule"]
    return out


def osm_sets() -> dict:
    o = io.read("opendata_facts")
    o = o[o.source == "osm"]
    t24 = set(o[(o.field == "is_24x7") & (o.value == "True")].unique_id)
    sch = set(o[((o.field == "is_24x7") & (o.value == "False")) | (o.field == "opening_hours_unparsed")].unique_id)
    return {"any24": t24, "emerg24": set(o[(o.field == "emergency") & (o.value == "yes")].unique_id), "schedule": sch,
            "any_hours": t24 | sch}


def build():
    ids = set(io.facilities().unique_id)
    si = io.read("site_identity")
    sites = set(si[si.attributable & si.kind.isin(["site", "branch"])].unique_id) & ids
    src = {"dataset": facts_sets(io.read("vf_details")), "web": facts_sets(io.read("web_facility_details")),
           "osm": osm_sets()}
    src = {k: {m: v & ids for m, v in d.items()} for k, d in src.items()}
    src["any"] = {m: src["dataset"][m] | src["web"][m] | src["osm"][m] for m, _ in MEASURES}
    rows = [{"source": s, "measure": m, **io.rate_row(len(src[s][m]), len(ids))} for s, _, _ in SOURCES for m, _ in MEASURES]
    rows += [{"source": "web_among_sites", "measure": m, **io.rate_row(len(src["web"][m]), len(sites))} for m, _ in MEASURES]
    tab = pd.DataFrame(rows)
    d, w = src["dataset"]["emerg24"] & sites, src["web"]["emerg24"] & sites
    agree = pd.DataFrame([{"group": "both", "k": len(d & w)}, {"group": "dataset_only", "k": len(d - w)},
                          {"group": "website_only", "k": len(w - d)}, {"group": "neither", "k": len(sites - d - w)}])
    agree["n_records_with_site"] = len(sites)
    fac = pd.DataFrame({"unique_id": sorted(ids)})
    for s in ["dataset", "web", "osm"]:
        for m, _ in MEASURES:
            fac[f"{s}_{m}"] = fac.unique_id.isin(src[s][m])
    fac["has_site"] = fac.unique_id.isin(sites)
    return tab, agree, fac, len(ids), len(sites)


def chart(tab, agree, n_ids, n_sites):
    fig, (ax, bx) = S.new_figure(ncols=2, gridspec_kw={"width_ratios": [1.65, 1]})
    h = 0.2
    for j, (m, mlab) in enumerate(MEASURES):
        for i, (s, slab, col) in enumerate(SOURCES):
            r = tab[(tab.source == s) & (tab.measure == m)].iloc[0]
            y = j + (i - 1.5) * h
            ax.barh(y, r.rate * 100, height=h * 0.92, color=col, **S.bar_style())
            S.add_interval(ax, [y], [r.lo * 100], [r.hi * 100], horizontal=True, cap=2, lw=1)
            lab = f"{r.k:,}" + (" (emergency=yes tag)" if (s == "osm" and m == "emerg24") else "")
            ax.text(r.hi * 100 + 0.6, y, lab, va="center", fontsize=9.5)
    ax.set_yticks(range(len(MEASURES)), [lab for _, lab in MEASURES])
    ax.set_ylim(len(MEASURES) - 0.45, -0.75)
    ax.set_xlim(0, 62)
    ax.set_xlabel(f"Share of {n_ids:,} records (%, 95% Wilson)")
    ax.grid(axis="y", visible=False)
    for i, (s, slab, col) in enumerate(SOURCES):
        x = 1 + i * 14.5
        ax.add_patch(__import__("matplotlib").patches.Rectangle((x, -0.7), 1.2, 0.16, color=col))
        ax.text(x + 1.8, -0.62, slab, va="center", fontsize=10)
    S.panel_title(ax, "Records with each kind of hours evidence, by source")

    a = agree.set_index("group").k
    tot = a.both + a.dataset_only + a.website_only
    left = 0
    # "Both" sits on top, not between the two blues: #2a78d6 next to #184f95 fails the validator's
    # normal-vision floor (dE 14.7 < 15); orange between them passes (dE >= 24.7).
    for g, lab, col in [("dataset_only", "Dataset only", S.CATEGORICAL[0]),
                        ("website_only", "Website only", S.CATEGORICAL[1]), ("both", "Both", S.SEMANTIC["verified"])]:
        w = 100 * a[g] / tot
        bx.bar(0, w, bottom=left, width=0.5, color=col, **S.bar_style())
        bx.text(0.3, left + w / 2, f"{lab}: {a[g]:,} ({w:.0f}%)", va="center", fontsize=10.5)
        left += w
    bx.set_xlim(-0.4, 1.6)
    bx.set_ylim(0, 100)
    bx.set_xticks([])
    bx.set_ylabel("Share (%)")
    bx.grid(axis="x", visible=False)
    S.panel_title(bx, f"24x7 emergency: dataset vs website\n(n = {tot:,} of {n_sites:,} with own site)")
    an = tab[(tab.source == "any") & (tab.measure == "any_hours")].iloc[0]
    sc = tab[(tab.source == "any") & (tab.measure == "schedule")].iloc[0]
    e = tab[(tab.source == "any") & (tab.measure == "emerg24")].iloc[0]
    ds = tab[(tab.source == "dataset") & (tab.measure == "schedule")].iloc[0]
    wb = tab[(tab.source == "web") & (tab.measure == "schedule")].iloc[0]
    S.fig_title(fig, f"Hours live on websites: the dataset gives clock-time hours for {ds.k:,} records, facility "
                     f"websites for {wb.k:,}; {n_ids - an.k:,} of {n_ids:,} records have no hours evidence at all")
    S.source_note(fig, f"Sources: {io.rel('vf_details')}, {io.rel('web_facility_details')} (attributable pages), "
                       f"\n{io.rel('opendata_facts')} (OSM, ODbL, (c) OpenStreetMap contributors).\nPrecision: dataset 24x7 "
                       "facts 6/6 hand-checked; website 24x7 emergency 9/10, other 24x7 scopes 1/5 (kb/web_evidence/qa); "
                       "OSM tags not checked. Absence of hours is not evidence of closure.")
    parts = []
    for m, mlab in MEASURES:
        vals = ", ".join(f"{slab} {tab[(tab.source == s) & (tab.measure == m)].k.iloc[0]:,}" for s, slab, _ in SOURCES)
        parts.append(f"{mlab}: {vals}.")
    alt = (f"Grouped bars of how many of {n_ids:,} facility records have hours evidence, by source. " + " ".join(parts) +
           f" Any hours of any kind: {an.k:,} ({an.rate:.0%}). Among {n_sites:,} records with their own website, "
           f"{tot:,} have a 24x7 emergency statement from the dataset or the site: {a.both:,} from both, "
           f"{a.dataset_only:,} from the dataset only and {a.website_only:,} from the website only.")
    S.save(fig, io.chart_path("s6_hours"), alt)


def main():
    tab, agree, fac, n_ids, n_sites = build()
    io.save_csv(tab, "s6_hours_by_source")
    io.save_csv(agree, "s6_emergency_agreement")
    io.save_csv(fac, "s6_facility_hours")
    chart(tab, agree, n_ids, n_sites)
    print(tab.pivot(index="measure", columns="source", values="k").to_string())
    print(agree.to_string(index=False))


if __name__ == "__main__":
    main()
