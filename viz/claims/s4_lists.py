"""Story 4: official lists vs the dataset. Who is missing from whom.

For each list, records fall in three groups: the dataset claims the thing and the list has the facility (both), the
dataset claims it and no list match was found (dataset only), and the list has the facility but its record is silent
(list only). A fourth number is the list entries with no matching record at all.
Inputs (data/external, local only; per-facility facts with citation, never redistributed as lists):
nabh_accredited/nabh_vf_match.parquet and match_stats.json, eraktkosh_blood_centres/erk_vf_matches.parquet and
join_stats.json, laqshya_master/laqshya_vf_matches.parquet and laqshya_facilities.parquet,
mohfw_trauma_196/tcf_vf_matches.csv and tcf_196.csv, pmndp_counts_and_state_lists/pmndp_state_counts.csv (NHSRC
columns only); kb/vf_details/out/facility_details.parquet (dataset NABH claims); claims_io.dataset_claims (services);
model/proto/evidence/pair_features.parquet (operator); derived/v1/facility_location.parquet (state).
Outputs: charts/s4_lists.{png,svg,txt}, charts/s4_pmndp.{png,svg,txt}, data/s4_lists.csv, data/s4_pmndp.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import claims_io as io
from claims_io import S

SEG = [("dataset_only", "Dataset claims it, list match not found", S.CATEGORICAL[1]),
       ("both", "Both", S.SEMANTIC["verified"]),
       ("list_only", "On the list, record silent", S.CATEGORICAL[2])]


def three_way(name, what, claim: set, listed: set, list_total: int, list_matched: int, universe: str) -> dict:
    both = claim & listed
    r = io.rate_row(len(claim - listed), len(claim))
    return {"list": name, "claim": what, "universe": universe, "dataset_claims": len(claim),
            "dataset_only": len(claim - listed), "both": len(both), "list_only": len(listed - claim),
            "list_entries": list_total, "list_entries_matched": list_matched,
            "list_entries_not_in_dataset": list_total - list_matched,
            "share_claims_unmatched": r["rate"], "share_claims_unmatched_lo": r["lo"], "share_claims_unmatched_hi": r["hi"]}


def build() -> tuple[pd.DataFrame, dict]:
    fac = io.facilities()
    ids = set(fac.unique_id)
    public = set(fac[fac.operator_public].unique_id)
    dc = io.dataset_claims()
    claim = lambda svcs: set(dc[(dc.text_pos | dc.spec) & dc.service_id.isin(svcs)].unique_id)  # noqa: E731
    vd = io.read("vf_details")
    nabh_claim = set(vd[(vd.fact_type == "accreditation") & (vd.attribute == "NABH") & (vd.n_usable > 0)].unique_id) & ids

    nabh = io.read("nabh_match")
    nabh = nabh[nabh.unique_id.isin(ids)]
    ns = io.read("nabh_stats")
    rows = [three_way("NABH accreditation", "NABH in the record text", nabh_claim, set(nabh.unique_id),
                      ns["nabh_rows"], int(nabh.nabh_id.nunique()), "all 9,959 records")]
    entry = nabh[nabh.unique_id.isin(nabh_claim)]
    extra = {"nabh_both_status": entry.drop_duplicates("unique_id").status.value_counts().to_dict()}

    erk = io.read("erk_match")
    es = io.read("erk_stats")
    rows.append(three_way("e-RaktKosh blood centres", "blood bank service", claim(["blood_bank"]),
                          set(erk.unique_id) & ids, es["erk_centres"], int(erk.hospital_code.nunique()
                          + erk.hospital_code.isna().sum()), "all 9,959 records"))

    lqf = io.read("laqshya_facilities")
    lq = io.read("laqshya_match").merge(lqf[["lq_id", "Maternity OT"]], on="lq_id")
    lq_mot = lq[lq["Maternity OT"].notna()]
    rows.append(three_way("LaQshya Maternity OT", "C-section (public records)", claim(["emergency_csection"]) & public,
                          set(lq_mot.unique_id) & public, int(lqf["Maternity OT"].notna().sum()),
                          int(lq_mot.lq_id.nunique()), f"{len(public):,} public records"))

    tcf = io.read("tcf_match")
    rows.append(three_way("MoHFW trauma care facilities", "trauma or emergency (public)",
                          claim(["trauma_care", "emergency_24x7"]) & public, set(tcf.vf_id) & public,
                          len(io.read("tcf_list")), int(tcf.sno.nunique()), f"{len(public):,} public records"))
    return pd.DataFrame(rows), extra


def pmndp() -> pd.DataFrame:
    fac = io.facilities()
    dc = io.dataset_claims()
    dial = set(dc[(dc.text_pos | dc.spec) & (dc.service_id == "dialysis")].unique_id)
    f = fac.assign(state=fac.state_final.str.lower(), dial=fac.unique_id.isin(dial))
    g = f.groupby("state").agg(vf_records=("unique_id", "size"), vf_dialysis=("dial", "sum"),
                               vf_public_dialysis=("dial", lambda s: int((s & f.loc[s.index, "operator_public"]).sum())))
    p = io.read("pmndp_states", ["state_key", "nhsrc_functional_centres", "nhsrc_functional_districts"])
    p = p.assign(state=p.state_key.replace({"dadra and nagar haveli and daman and diu":
                                            "the dadra and nagar haveli and daman and diu"}))
    out = p.merge(g, left_on="state", right_index=True, how="left").fillna(
        {"vf_records": 0, "vf_dialysis": 0, "vf_public_dialysis": 0})
    return out.drop(columns=["state_key"]).sort_values("nhsrc_functional_centres", ascending=False)


def chart_lists(d: pd.DataFrame, extra: dict):
    fig, ax = S.new_figure(size=(12, 6.2))
    ys = np.arange(len(d))
    for y, r in zip(ys, d.itertuples()):
        tot = r.dataset_only + r.both + r.list_only
        left = 0.0
        for key, _, col in SEG:
            v = getattr(r, key)
            w = 100 * v / tot
            ax.barh(y, w, left=left, color=col, height=0.6, **S.bar_style())
            if w >= 4:
                ink = "#ffffff" if key == "both" else S.INK
                ax.text(left + w / 2, y, f"{v:,}", ha="center", va="center", fontsize=11, color=ink)
            elif v > 0:  # too thin to hold its label: put the count just above the segment
                ax.text(left + w / 2, y - 0.36, f"{v:,}", ha="center", va="bottom", fontsize=10, color=S.INK)
            left += w
        ax.text(102, y - 0.12, f"{r.list_entries_not_in_dataset:,} of {r.list_entries:,}", fontsize=11, va="center")
        ax.text(102, y + 0.16, "list entries with no record", fontsize=9.5, va="center", color=S.INK_2)
    sub = {"LaQshya Maternity OT": "\nsubset list: dataset-only expected", "MoHFW trauma care facilities": "\nsubset list: dataset-only expected"}
    ax.set_yticks(ys, [f"{r.list}\n{r.claim}{sub.get(r.list, '')}" for r in d.itertuples()], fontsize=10.5)
    ax.set_ylim(len(d) - 0.5, -1.05)
    ax.set_xlim(0, 125)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Share of records in any of the three groups (%)")
    ax.grid(axis="y", visible=False)
    for x, (key, lab, col) in zip([0, 42, 55], SEG):  # direct key above the first bar, in text ink next to a swatch
        ax.add_patch(__import__("matplotlib").patches.Rectangle((x, -0.95), 2.2, 0.22, color=col, clip_on=False))
        ax.text(x + 3, -0.84, lab, va="center", fontsize=10.5)
    n = d.iloc[0]
    # figure-level headline: an axes title starts right of the long row labels and ran off the right edge
    S.fig_title(fig, f"{n.dataset_only:,} of {n.dataset_claims:,} records that say NABH ({n.share_claims_unmatched:.0%}, "
                        f"95% CI {n.share_claims_unmatched_lo:.0%}-{n.share_claims_unmatched_hi:.0%}) were not found on NABH's "
                        f"current list, and {n.list_only:,} of {n.both + n.list_only:,} list-matched records never "
                        f"mention NABH", wrap=80)
    st = extra["nabh_both_status"]
    S.source_note(fig, "Sources: data/external NABH, e-RaktKosh, LaQshya, MoHFW trauma 196 matches (hand-checked 39/40, "
                       "16/20 + 2 likely, 17/20 + 3 plausible, 19/20);\ndataset claims from kb/vf_details (NABH) and the "
                       "taxonomy (services). Matcher recall was not measured, so 'list match not found' is an upper bound "
                       f"on false claims.\nOf {n.both:,} NABH 'both', {st.get('Certified', 0)} hold only entry-level "
                       "'Certified' status. LaQshya and trauma rows use public records only.")
    parts = [f"{r.list}: {r.dataset_only:,} dataset-only, {r.both:,} both, {r.list_only:,} list-only; "
             f"{r.list_entries_not_in_dataset:,} of {r.list_entries:,} list entries have no record." for r in d.itertuples()]
    alt = ("Stacked bars comparing four official lists with what records claim. " + " ".join(parts) +
           f" {n.share_claims_unmatched:.0%} of records that mention NABH were not found on NABH's current list; matcher "
           "recall was not measured, so this is an upper bound on false claims.")
    S.save(fig, io.chart_path("s4_lists"), alt)


def chart_pmndp(p: pd.DataFrame):
    d = p[p.nhsrc_functional_centres > 0].sort_values("nhsrc_functional_centres").reset_index(drop=True)
    fig, ax = S.new_figure(size=(11, 10))
    ys = np.arange(len(d))
    ax.hlines(ys, d.vf_public_dialysis, d.nhsrc_functional_centres, color=S.GRID, lw=2.5, zorder=1)
    ax.scatter(d.nhsrc_functional_centres, ys, color=S.CATEGORICAL[0], s=55, zorder=3, edgecolor=S.SURFACE, lw=1.5)
    ax.scatter(d.vf_public_dialysis, ys, color=S.CATEGORICAL[1], s=55, zorder=3, edgecolor=S.SURFACE, lw=1.5)
    for y, r in zip(ys, d.itertuples()):
        ax.text(r.nhsrc_functional_centres + 3, y, f"{r.nhsrc_functional_centres:.0f}", va="center", fontsize=9.5,
                color=S.INK_2)
    ax.set_yticks(ys, [s.title().replace(" And ", " and ") for s in d.state])
    ax.tick_params(axis="y", labelsize=10)
    ax.set_xlim(0, d.nhsrc_functional_centres.max() * 1.12)
    ax.set_ylim(-0.7, len(d) - 0.3)
    ax.set_xlabel("Public dialysis centres (count)")
    ax.grid(axis="y", visible=False)
    for i, (lab, col) in enumerate([("PMNDP functional public dialysis centres (NHSRC)", S.CATEGORICAL[0]),
                                    ("Public records in the dataset that mention dialysis", S.CATEGORICAL[1])]):
        ax.scatter([0.45], [0.16 - i * 0.045], transform=ax.transAxes, s=55, color=col, clip_on=False)
        ax.text(0.47, 0.16 - i * 0.045, lab, transform=ax.transAxes, va="center", fontsize=10.5)
    tot_p, tot_v = int(p.nhsrc_functional_centres.sum()), int(p.vf_public_dialysis.sum())
    b = p[p.state == "bihar"].iloc[0]
    u = p[p.state == "uttar pradesh"].iloc[0]
    S.finding_title(ax, f"PMNDP runs {tot_p:,} public dialysis centres; the dataset holds {tot_v} public records that "
                        f"mention dialysis, of {int(io.facilities().operator_public.sum())} public records in all (Bihar "
                        f"{b.vf_public_dialysis:.0f} vs {b.nhsrc_functional_centres:.0f}, "
                        f"Uttar Pradesh {u.vf_public_dialysis:.0f} vs {u.nhsrc_functional_centres:.0f})", wrap=72)
    S.source_note(fig, f"Sources: {io.rel('pmndp_states')} (NHSRC columns; PMNDP via NHSRC, reproduced with "
                       f"acknowledgement);\n{io.rel('lexicon_matches')}, {io.rel('specialty_map')}, "
                       f"{io.rel('pair_features')} (public operator),\n{io.rel('facility_location')} (state). Counts, not "
                       "a facility match: PMNDP publishes no national facility list. States with 0 centres omitted.")
    alt = (f"Dot plot by state of public dialysis centres under PMNDP ({tot_p:,} in total) against public facility "
           f"records in the dataset that mention dialysis ({tot_v} in total). Bihar has "
           f"{b.nhsrc_functional_centres:.0f} PMNDP centres and {b.vf_public_dialysis:.0f} such records; Uttar Pradesh "
           f"{u.nhsrc_functional_centres:.0f} and {u.vf_public_dialysis:.0f}. Silence in the dataset about dialysis at "
           "a public district hospital is not evidence that it has none.")
    S.save(fig, io.chart_path("s4_pmndp"), alt)


def main():
    d, extra = build()
    io.save_csv(d, "s4_lists")
    chart_lists(d, extra)
    p = pmndp()
    io.save_csv(p, "s4_pmndp")
    chart_pmndp(p)
    print(d.T.to_string())
    print(extra)
    print(p.head(8).to_string(index=False), int(p.nhsrc_functional_centres.sum()), int(p.vf_public_dialysis.sum()))
    print("states without VF match:", p[p.vf_records == 0].state.tolist())


if __name__ == "__main__":
    main()
