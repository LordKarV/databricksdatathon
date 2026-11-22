"""Story 6: the funnel. How many origins the planner sends to a single definitive facility.

Input: data/plans_best.csv (state samples only), derived/v1/grades.parquet and facility_location.parquet for
the count of Bihar records graded for C-section. Output: charts/s6_funnel.*, data/s6_funnel.csv.
"""
import textwrap

import pandas as pd

from common import CHARTS, DATA, PATHWAY_LABEL, ROOT, STATE_COLOR, STATE_SETS, STUB_NOTE, S, note

ORDER = ["obstetric_emergency", "major_trauma", "dialysis_start", "burns", "stemi", "sick_newborn"]


def build(df):
    rows = []
    for pid in ORDER:
        for st in STATE_SETS:
            x = df[(df.pathway == pid) & (df.origin_set == st) & (df.best_type != "abstain")]
            vc = x.groupby(["def_name", "def_district"]).size().sort_values(ascending=False)
            (name, district), k = vc.index[0], int(vc.iloc[0])
            p, lo, hi = S.wilson(k, len(x))
            rows.append({"pathway": pid, "origin_set": st, "n_planned": len(x), "n_destinations": len(vc),
                         "top_facility": name, "top_district": district, "top_count": k, "top_share": p,
                         "lo95": lo, "hi95": hi, "top3_share": vc.iloc[:3].sum() / len(x)})
    return pd.DataFrame(rows)


def chart(t, n_cs_bihar, n_cs_ok):
    fig, ax = S.new_figure(size=(13, 8.6))
    y, ys, labels = 0.0, [], []
    for pid in ORDER:
        ax.text(-0.01, y - 0.2, PATHWAY_LABEL[pid], transform=ax.get_yaxis_transform(), ha="right", va="center",
                fontsize=12, fontweight="bold")
        y += 0.8
        for st in STATE_SETS:
            r = t[(t.pathway == pid) & (t.origin_set == st)].iloc[0]
            ax.barh(y, r.top_share * 100, height=0.72, color=STATE_COLOR[st], **S.bar_style())
            S.add_interval(ax, [y], [r.lo95 * 100], [r.hi95 * 100], horizontal=True)
            name = textwrap.shorten(r.top_facility.split(",")[0], 44, placeholder="...")
            ax.annotate(f"{name}: {r.top_count} of {r.n_planned}; "
                        f"{r.n_destinations} destinations in all", (r.hi95 * 100, y), xytext=(6, 0),
                        textcoords="offset points", va="center", fontsize=9.5, color=S.INK)
            ys.append(y)
            labels.append(st)
            y += 1
        y += 0.5
    ax.set_yticks(ys, labels, fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 160)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("Share of planned origins whose best plan ends at the single most-chosen facility (%, 95% Wilson CI)")
    ax.grid(axis="y", visible=False)
    ob = t[(t.pathway == "obstetric_emergency") & (t.origin_set == "Bihar")].iloc[0]
    tr = t[(t.pathway == "major_trauma") & (t.origin_set == "Bihar")].iloc[0]
    S.fig_title(fig, f"In Bihar the planner funnels {ob.top_share*100:.0f}% of obstetric emergencies to one sub-divisional "
                     f"hospital: {n_cs_bihar - n_cs_ok} of the {n_cs_bihar} Bihar records graded for C-section never mention "
                     f"blood transfusion, so the stub scores them near zero")
    note(fig, "150 random PIN centroids per state, abstentions excluded (n per row in the label). Definitive obstetric care "
              "needs comprehensive EmOC and blood transfusion; trauma needs surgery, blood, CT, ICU and a trauma specialty. "
              "The stub gives an unmentioned capability p = 0.02 and multiplies capabilities, so a facility whose record "
              "names all of them wins every nearby origin. For definitive trauma in Bihar, AIIMS Patna scores 0.01 because its record "
              "matches no trauma-centre, neurosurgery or orthopaedics evidence word, and Paras HMRI because it never mentions "
              "blood (verify/out/v6_mechanism.log). " + STUB_NOTE, width=200)
    alt = ("Horizontal bars by pathway and state sample showing the share of origins whose best plan ends at the most "
           "chosen definitive facility, with 95% Wilson intervals. " + "; ".join(
               f"{PATHWAY_LABEL[r.pathway]} {r.origin_set}: {r.top_facility.split(',')[0]} {r.top_count} of {r.n_planned} "
               f"({r.top_share*100:.0f}%), {r.n_destinations} destinations" for r in t.itertuples())
           + f". Why: {n_cs_bihar - n_cs_ok} of the {n_cs_bihar} Bihar records graded for C-section never mention blood "
             "transfusion, which the stub scores 0.02, so only "
           + f"{n_cs_ok} clear the planner's 0.05 floor. Probabilities are the derived/v1 stub.")
    S.save(fig, CHARTS / "s6_funnel", alt)


def main():
    df = pd.read_csv(DATA / "plans_best.csv")
    t = build(df[df.origin_set.isin(STATE_SETS)])
    t.to_csv(DATA / "s6_funnel.csv", index=False)
    g = pd.read_parquet(ROOT / "derived/v1/grades.parquet", columns=["unique_id", "service", "grade"])
    f = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "state_final"])
    x = g.merge(f, on="unique_id")
    cs = x[(x.state_final == "BIHAR") & (x.service == "csection") & x.grade.isin(["strong", "moderate"])]
    n_cs = len(cs)
    from planner.data_v1 import V1Store
    store = V1Store(v1=ROOT / "derived/v1", caps_path=ROOT / "kb/pathways/capabilities.json")
    # records whose definitive obstetric stage clears the planner's candidate floor (comprehensive EmOC x blood >= 0.05)
    n_cs_ok = sum(store.capability_p(u, "comprehensive_emoc")[0] * store.capability_p(u, "blood_transfusion")[0] >= 0.05
                  for u in cs.unique_id)
    chart(t, n_cs, n_cs_ok)
    print(t.round(3).to_string())
    print("Bihar csection strong/moderate:", n_cs)


if __name__ == "__main__":
    main()
