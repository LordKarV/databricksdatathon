"""Story 6: what cleaning could and could not fix.

Chart s6_cleaning: records affected by each issue (of 9,959), grouped by what the
cleaning pipeline did with it: fixed, flagged to the user, or cannot be fixed by any
rule. Every count is recomputed here from the cleaned tables, except the two marked
(measure.json), which are read from cleaning/claims/out/measure.json.

Inputs: data/raw/PROFILE.json, derived/v1/{facility_location, record_trust, facility_groups,
claims, grades}.parquet, cleaning/claims/out/measure.json.
Run: .venv-viz/bin/python viz/trust/s6_cleaning.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import trust_io as io
import style as S

GROUPS = [("fixed", "Fixed by a stated rule", S.SEMANTIC["verified"]),
          ("flagged", "Flagged to the user, not repaired", S.SEMANTIC["flagged"]),
          ("cannot", "Cannot be fixed by cleaning", S.SEMANTIC["unlikely"])]


def has(series, flag):
    return series.map(lambda x: x is not None and flag in set(x))


def ledger():
    loc = io.load("location", ["unique_id", "loc_src", "loc_conf"])
    rt = io.load("record_trust", ["unique_id", "trust_flags", "scale_flags", "email_issue", "trust_level"])
    gr = io.load("groups", ["unique_id", "dup_group_id", "group_size"])
    cl = io.load("claims", ["unique_id", "attribution", "context", "dup_in_record", "services"])
    g = io.load("grades", ["unique_id", "grade", "corr_tags_only", "risk_outpatient_type", "truncated"])
    prof = io.load_json("profile")
    N = len(loc)

    def ids(mask, frame):
        return set(frame.loc[mask, "unique_id"])

    quarantined = ids(cl.attribution == "other_facility", cl)
    anon = ids((cl.attribution == "unanchored") & (cl.services != ""), cl) & quarantined
    n_anon_sent = int(((cl.attribution == "unanchored") & (cl.services != "") & cl.unique_id.isin(quarantined)
                       & ~cl.dup_in_record.fillna(False).astype(bool)).sum())  # distinct sentences, as measure.json
    items = [
        ("fixed", "Malformed rows dropped (fragments, truncated)", 0, prof["rows"] - prof["row_integrity"]["well_formed"],
         "of 10,088 raw rows"),
        ("fixed", "Byte-identical duplicate rows dropped", 0, prof["row_integrity"]["well_formed"] - N,
         f"{prof['row_integrity']['well_formed']:,} well-formed rows to {N:,} records"),
        ("fixed", "Residual duplicates linked into one card", len(ids(gr.group_size > 1, gr)), None,
         f"{gr.loc[gr.group_size > 1, 'dup_group_id'].nunique()} groups"),
        ("fixed", "Ranked on a corrected point, not the listing pin", len(ids(loc.loc_src != "listing_coordinates", loc)),
         None, "postcode, city or map-link point"),
        ("fixed", "Directory phone removed from display", len(ids(has(rt.trust_flags, "official_phone_is_directory"), rt)),
         None, ""),
        ("fixed", "Placeholder or unparseable email dropped", len(ids(rt.email_issue.notna(), rt)), None, ""),
        ("fixed", "Duplicate claim sentences counted once", len(ids(cl.dup_in_record.fillna(False).astype(bool), cl)),
         None, f"{int(cl.dup_in_record.fillna(False).astype(bool).sum()):,} sentences"),
        ("fixed", "Sentences naming another facility quarantined", len(quarantined), None,
         f"{int((cl.attribution == 'other_facility').sum()):,} sentences"),
        ("flagged", "Location low confidence", len(ids(loc.loc_conf == "low", loc)), None, "note cites postcode and city"),
        ("flagged", "Location disputed (two candidate towns)", len(ids(loc.loc_conf == "disputed", loc)), None, ""),
        ("flagged", "Size or capacity implausible or contradicted", len(ids(rt.scale_flags.map(lambda x: x is not None and len(x) > 0), rt)),
         None, "caveat line"),
        ("flagged", "A strong grade backed only by a specialty tag",
         len(ids((g.grade == "strong") & g.corr_tags_only, g)), None, "'corroborated only by a label'"),
        ("flagged", "Outpatient type claiming an inpatient service", len(ids(g.risk_outpatient_type.fillna(False).astype(bool), g)),
         None, "'ask if they admit'"),
        ("cannot", "Service text naming no facility, in a record naming another", len(anon), None,
         f"{n_anon_sent:,} sentences; no rule can see them"),
        ("cannot", "Merged record: a sentence places care at another facility", len(ids(cl.context == "direct", cl)),
         None, "record cannot be split"),
        ("cannot", "Lists cut at 50 items", len(ids(g.truncated.fillna(False).astype(bool), g)), None,
         "a missing service may still exist"),
    ]
    d = pd.DataFrame(items, columns=["group", "issue", "records", "rows", "unit_note"])
    d["count"] = d.records.where(d.records > 0, d.rows).astype(int)
    d["unit"] = np.where(d.records > 0, "records", "rows")
    d[["rate", "lo", "hi"]] = [S.wilson(int(c), N) if u == "records" else (np.nan,) * 3 for c, u in zip(d["count"], d.unit)]
    clean = set(rt.loc[rt.trust_level == "no_concerns", "unique_id"])
    cannot = anon | ids(cl.context == "direct", cl) | ids(g.truncated.fillna(False).astype(bool), g)
    extra = dict(N=N, n_clean=len(clean), clean_but_cannot=len(clean & cannot), n_cannot=len(cannot),
                 n_anon_sent=n_anon_sent)
    return d, extra


def run():
    d, x = ledger()
    fig, axes = S.new_figure(size=(12, 8.4), nrows=3, sharex=True,
                             gridspec_kw=dict(height_ratios=[(d.group == k).sum() for k, _, _ in GROUPS]))
    for ax, (key, title, col) in zip(axes, GROUPS):
        s = d[d.group == key].iloc[::-1]
        y = np.arange(len(s))
        ax.barh(y, s["count"], color=col, height=0.66, **S.bar_style())
        for yi, r in zip(y, s.itertuples()):
            share = f" ({r.rate * 100:.1f}%)" if r.unit == "records" else f" {r.unit}"
            extra = f"; {r.unit_note}" if r.unit_note else ""
            ax.annotate(f"{r.count:,}{share}{extra}", (r.count, yi), xytext=(5, 0), textcoords="offset points",
                        va="center", fontsize=10.5, color=S.INK)
        ax.set_yticks(y, s.issue, fontsize=11)
        ax.grid(axis="y", visible=False)
        S.panel_title(ax, f"{title}")
    axes[-1].set_xlim(0, d["count"].max() * 1.6)
    axes[-1].set_xlabel(f"Records affected (of {x['N']:,}; two top rows count raw rows)")
    S.fig_title(fig, f"Cleaning fixes geometry, contacts and duplicates but cannot see copied text: "
                     f"{x['n_cannot']:,} records ({x['n_cannot'] / x['N'] * 100:.0f}%) keep a problem no rule can fix, "
                     f"{x['clean_but_cannot']:,} of them among the {x['n_clean']:,} rated 'no concerns'")
    io.note(fig, "Counts recomputed from derived/v1 (facility_location loc_src / loc_conf, record_trust flags, "
                 "facility_groups, claims attribution / context / dup_in_record, grades) and data/raw/PROFILE.json. "
                 "Groups overlap: a record can appear in several bars. Copied service text = a service sentence that names "
                 "no facility in a record that also has quarantined text (cleaning/claims/out/measure.json reports the same "
                 "7,514 sentences in 1,390 records). Bar shares carry 95% intervals under +/-1 point (census).")
    io.write_csv(d, "s6_cleaning")
    fx = d[d.group == "fixed"]
    alt = (f"Three stacked groups of horizontal bars: what cleaning fixed, what it flags, and what it cannot fix, as "
           f"records affected out of {x['N']:,}. Fixed includes {int(fx.set_index('issue').loc['Ranked on a corrected point, not the listing pin', 'count']):,} "
           f"records ranked on a corrected point and {int(fx.set_index('issue').loc['Sentences naming another facility quarantined', 'count']):,} "
           f"records with quarantined sentences. Cannot be fixed: {int(d.set_index('issue').loc['Service text naming no facility, in a record naming another', 'count']):,} "
           f"records hold {x['n_anon_sent']:,} copied service sentences that name no facility, "
           f"{int(d.set_index('issue').loc['Lists cut at 50 items', 'count']):,} have lists cut at 50 items. In total "
           f"{x['n_cannot']:,} records carry at least one problem cleaning cannot fix, {x['clean_but_cannot']:,} of them "
           f"among the {x['n_clean']:,} that the cleaning pipeline rates as having no concerns.")
    S.save(fig, io.out("s6_cleaning"), alt)
    print("s6", x)
    print(d[["group", "issue", "count", "unit"]].to_string())
    return d, x


if __name__ == "__main__":
    run()
