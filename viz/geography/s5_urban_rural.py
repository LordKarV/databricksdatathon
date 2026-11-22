"""Story 5: the urban-rural gap in where the evidence sits.

Settlement class per 1 km cell: simplified Degree of Urbanisation on WorldPop 2025
(common.degree_of_urbanisation: urban centre >= 1,500 people/km2 in clusters of 50,000+; town or
semi-dense >= 300/km2 in clusters of 5,000+; rural = the rest). Each record takes the class of the
cell under its cleaned location. Travel minutes as in s4 (MAP friction, checked in travel_check).
Outputs: charts/s5_urban_rural.*, data/s5_classes.csv, data/s5_numbers.json.
"""
import json

import numpy as np
import pandas as pd

import common as C
from common import S

SERVICES = [("trauma", "Trauma or 24x7 emergency"), ("dialysis", "Dialysis"), ("csection", "Emergency C-section")]
LIMIT = 60
ORDER = [3, 2, 1]


def main():
    d = C.facilities()
    G = C.build_grid()
    pop = G["pop"].ravel()
    cls = G["degurba"].ravel()
    rows = []
    for code in ORDER:
        m = cls == code
        r = dict(code=code, cls=C.DEGURBA_LABELS[code], pop=float(pop[m].sum()), records=int((d.degurba == code).sum()))
        for svc, _ in SERVICES:
            r[f"{svc}_corr"] = int((d[f"{svc}_corroborated"] & (d.degurba == code)).sum())
        rows.append(r)
    t = pd.DataFrame(rows)
    for col in ["pop", "records"] + [f"{s}_corr" for s, _ in SERVICES]:
        t[f"{col}_share"] = t[col] / t[col].sum()
    for svc, _ in SERVICES:
        m = d.on_grid & d[f"{svc}_corroborated"]
        tt = C.cached_travel(f"{svc}_corr", d.row[m], d.col[m]).ravel()
        for code in ORDER:
            k = cls == code
            i = t.code == code
            t.loc[i, f"{svc}_within60"] = float((pop[k] * (tt[k] <= LIMIT)).sum() / pop[k].sum())
            t.loc[i, f"{svc}_median_min"] = C.weighted_quantile(np.minimum(tt[k], 10_000), pop[k], 0.5)
    C.save_csv(t, "s5_classes")
    rur = t.set_index("code").loc[1]
    urb = t.set_index("code").loc[3]
    nums = dict(classes=t.to_dict("records"), n_records=len(d),
                rural_pop_share=float(rur.pop_share), rural_records=int(rur.records),
                urban_pop_share=float(urb.pop_share), urban_records_share=float(urb.records_share),
                records_per_m_urban=float(urb.records / urb["pop"] * 1e6),
                records_per_m_rural=float(rur.records / rur["pop"] * 1e6),
                rural_trauma60=float(rur.trauma_within60), urban_trauma60=float(urb.trauma_within60))
    C.save_numbers("s5", nums)
    chart(t, nums)
    print(json.dumps(nums, indent=1, default=float))


def chart(t, nums):
    fig, (a, b) = S.new_figure((12, 6.8), ncols=2, gridspec_kw=dict(width_ratios=[1.15, 1]))
    cols = {3: S.SEQUENTIAL[12], 2: S.SEQUENTIAL[7], 1: S.SEQUENTIAL[3]}  # step 2 failed light-end contrast
    bars = [("pop", "People\n(WorldPop)"), ("records", "All records"), ("trauma_corr", "Confirmed\ntrauma/ER"),
            ("dialysis_corr", "Confirmed\ndialysis"), ("csection_corr", "Confirmed\nC-section")]
    x = np.arange(len(bars))
    bottom = np.zeros(len(bars))
    for r in t.itertuples():
        v = np.array([getattr(r, f"{k}_share") for k, _ in bars]) * 100
        a.bar(x, v, bottom=bottom, color=cols[r.code], width=0.62, label=r.cls + (" (sparsest)" if r.code == 1 else ""), **S.bar_style())
        for xi, (vi, bi) in enumerate(zip(v, bottom)):
            if vi >= 6:
                a.text(xi, bi + vi / 2, f"{vi:.0f}%", ha="center", va="center", fontsize=10.5,
                       color="#ffffff" if r.code != 1 else S.INK)
        bottom += v
    totals = [t["pop"].sum() / 1e6] + [t[k].sum() for k, _ in bars[1:]]
    a.set_xticks(x, [f"{l}\n{'%.0f M' % n if i == 0 else 'n = %d' % n}" for i, ((_, l), n) in enumerate(zip(bars, totals))],
                 fontsize=10.5)
    a.set_ylim(0, 100)
    a.set_ylabel("Share of the column (%)")
    a.grid(axis="x", visible=False)
    a.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, fontsize=10.5)
    S.panel_title(a, "Where people live vs where records sit")
    y = np.arange(len(SERVICES))
    h = 0.26
    for j, code in enumerate(ORDER):
        r = t.set_index("code").loc[code]
        v = [r[f"{s}_within60"] * 100 for s, _ in SERVICES]
        bb = a_bars = b.barh(y + (j - 1) * h, v, height=h, color=cols[code], **S.bar_style())
        S.label_bars(b, bb, labels=[f"{x:.0f}%" for x in v], horizontal=True, fontsize=10)
    b.set_yticks(y, [l for _, l in SERVICES])
    b.invert_yaxis()
    b.set_xlim(0, 112)
    b.set_xlabel(f"People within {LIMIT} min of a confirmed facility (%)")
    b.grid(axis="y", visible=False)
    S.panel_title(b, "Share within an hour, by settlement class\n(bars top to bottom: urban centre, town, rural)")
    S.fig_title(fig, f"{nums['urban_records_share'] * 100:.0f}% of records sit in urban centres, home to "
                     f"{nums['urban_pop_share'] * 100:.0f}% of people; in the sparsest areas ({nums['rural_pop_share'] * 100:.0f}% of "
                     f"people) only {nums['rural_trauma60'] * 100:.0f}% are within an hour of confirmed trauma care, "
                     f"against {nums['urban_trauma60'] * 100:.0f}% in urban centres")
    C.note(fig, "Settlement class: simplified Degree of Urbanisation (GHSL/Eurostat thresholds, no gap filling) on "
                "WorldPop 2025 1 km cells; it counts dense villages of the Gangetic plain as towns, so its rural share "
                "is smaller than the Census 2011 rural share (68.8%). Records are placed by cleaned location; a record "
                "geocoded to its town centre counts as urban. Confirmed = dataset claim plus a second check, mostly the own website "
                "(see s6). Population classes are modelled, so no sampling interval applies; travel error range in s4.")
    rows = "; ".join(f"{r.cls}: {r.pop_share * 100:.0f}% of people, {r.records_share * 100:.0f}% of records, "
                     f"{r.trauma_within60 * 100:.0f}% within an hour of confirmed trauma care, "
                     f"{r.dialysis_within60 * 100:.0f}% of dialysis, {r.csection_within60 * 100:.0f}% of C-section"
                     for r in t.itertuples())
    S.save(fig, C.CHARTS / "s5_urban_rural",
           alt_text="Two panels. Left: stacked bars of the share of people, records and confirmed facilities in urban "
                    "centres, towns and rural areas. Right: share of people within an hour of a confirmed facility, "
                    "by settlement class. " + rows + ".")


if __name__ == "__main__":
    main()
