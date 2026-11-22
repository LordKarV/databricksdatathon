"""Story 4: the invisible service. Snakebite deaths by state against records that mention anti-snake venom.

Inputs: data/sources/mds_snakebite_table3.csv (Suraweera et al., eLife 2020, Table 3), derived/v1/claims.parquet
via planner.data_v1 (the planner's own anti_snake_venom matcher, kb/pathways/capabilities.json),
derived/v1/facility_location.parquet (state), kb/web_evidence/out/web_service_summary.parquet (websites).
Output: charts/s4_snakebite.*, data/s4_snakebite.csv.
"""
import pandas as pd

from common import CHARTS, DATA, ROOT, SOURCES, S, note

GROUP = {"ANDHRA PRADESH": "Andhra Pradesh (incl. Telangana)", "TELANGANA": "Andhra Pradesh (incl. Telangana)",
         "BIHAR": "Bihar", "ODISHA": "Odisha", "MADHYA PRADESH": "Madhya Pradesh", "UTTAR PRADESH": "Uttar Pradesh",
         "RAJASTHAN": "Rajasthan", "GUJARAT": "Gujarat", "JHARKHAND": "Jharkhand", "CHHATTISGARH": "Chhattisgarh",
         "JAMMU AND KASHMIR": "Jammu & Kashmir", "LADAKH": "Jammu & Kashmir", "TAMIL NADU": "Tamil Nadu",
         "KARNATAKA": "Karnataka", "MAHARASHTRA": "Maharashtra", "WEST BENGAL": "West Bengal", "PUNJAB": "Punjab",
         "HARYANA": "Haryana", "ASSAM": "Assam", "KERALA": "Kerala",
         **{s: "Northeastern states" for s in ["ARUNACHAL PRADESH", "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND",
                                                "SIKKIM", "TRIPURA"]}}


# Wider wording than the planner's anti_snake_venom evidence words, which miss "snake bite" (two words) unless it is
# followed by "treatment". Exclusions found by reading every hit (verify/out/v4b_loose.log): the "Animal bites
# (Excluding Snake Bite)" line of public-hospital records, and wound care for snake bite wounds.
SNAKE = r"snake\s*-?\s*bites?|snakebite|anti-?\s*snake|anti-?\s*venom|snake envenomation|snake/insect bites|\bASV\b"
SNAKE_EXCLUDE = r"excluding snake|snake bite wounds"


def snake_mentions():
    c = pd.read_parquet(ROOT / "derived/v1/claims.parquet", columns=["unique_id", "text", "attribution", "nonoffer"])
    c = c[(c.attribution != "other_facility") & ~c.nonoffer.fillna(False)]
    hit = c.text.str.contains(SNAKE, case=False, na=False) & ~c.text.str.contains(SNAKE_EXCLUDE, case=False, na=False)
    return set(c[hit].unique_id)


def build():
    from planner.data_v1 import V1Store
    asv = set(V1Store(v1=ROOT / "derived/v1", caps_path=ROOT / "kb/pathways/capabilities.json")._match("anti_snake_venom"))
    wide = snake_mentions()
    f = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "state_final"])
    w = pd.read_parquet(ROOT / "kb/web_evidence/out/web_service_summary.parquet",
                        columns=["unique_id", "service_id", "web_positive"])
    web = set(w[(w.service_id == "snakebite_antivenom") & w.web_positive].unique_id)
    f["mds_group"] = f.state_final.map(GROUP).fillna("All other states")
    f["asv"] = f.unique_id.isin(asv)
    f["wide"] = f.unique_id.isin(wide)
    f["web"] = f.unique_id.isin(web)
    g = f.groupby("mds_group").agg(records=("unique_id", "size"), asv_records=("asv", "sum"),
                                   snake_records=("wide", "sum"), web_snakebite_records=("web", "sum")).reset_index()
    m = pd.read_csv(SOURCES / "mds_snakebite_table3.csv")
    t = m.merge(g, on="mds_group", how="left").fillna({"records": 0, "asv_records": 0, "snake_records": 0, "web_snakebite_records": 0})
    t["deaths_per_year"] = t.est_deaths_2001_14_thousands * 1000 / 14
    ci = [S.wilson(int(k), int(n)) for k, n in zip(t.asv_records, t.records)]
    t["asv_share"], t["asv_lo95"], t["asv_hi95"] = zip(*ci)
    ci = [S.wilson(int(k), int(n)) for k, n in zip(t.snake_records, t.records)]
    t["snake_share"], t["snake_lo95"], t["snake_hi95"] = zip(*ci)
    return (t.sort_values("deaths_per_year", ascending=False).reset_index(drop=True), len(f), len(asv), len(web),
            int(f.wide.sum()))


def chart(t, n_all, n_asv, n_web, n_wide):
    fig, (ax, bx) = S.new_figure(size=(13, 8.4), ncols=2, sharey=True, gridspec_kw={"width_ratios": [1.15, 1]})
    y = range(len(t))
    hb = t.burden_group == "higher"
    cols = [S.CATEGORICAL[1] if h else S.SEQUENTIAL[5] for h in hb]
    bars = ax.barh(list(y), t.deaths_per_year, color=cols, height=0.7, **S.bar_style())
    S.label_bars(ax, bars, labels=[f"{v:,.0f}" for v in t.deaths_per_year], horizontal=True, fontsize=10)
    ax.set_yticks(list(y), [f"{g}" for g in t.mds_group], fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlabel("Estimated snakebite deaths per year, 2001-2014 average")
    ax.set_xlim(0, t.deaths_per_year.max() * 1.18)
    ax.xaxis.set_major_formatter(S.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    ax.grid(axis="y", visible=False)
    hb_share = t[hb].deaths_per_year.sum() / t.deaths_per_year.sum()
    S.panel_title(ax, f"Deaths (orange = 8 higher-burden states, {hb_share*100:.0f}% of deaths)")
    # right: share of records mentioning ASV, with Wilson 95% interval; website mentions as a text column
    yy = list(y)
    S.add_interval(bx, yy, t.snake_lo95 * 100, t.snake_hi95 * 100, horizontal=True, color=S.INK_2)
    bx.scatter(t.snake_share * 100, yy, s=60, color=S.CATEGORICAL[0], edgecolor=S.SURFACE, lw=1.5, zorder=4)
    for i, r in t.iterrows():
        bx.annotate(f"{int(r.snake_records)} of {int(r.records):,} (matcher {int(r.asv_records)})", (r.snake_hi95 * 100, i),
                    xytext=(6, 0), textcoords="offset points", va="center", fontsize=9.5, color=S.INK)
        bx.text(1.0, i, f"{int(r.web_snakebite_records)}", transform=bx.get_yaxis_transform(), ha="right",
                va="center", fontsize=9.5, color=S.INK_2)
    bx.text(1.0, -0.55, "Websites mention\nsnakebite (count)", transform=bx.get_yaxis_transform(), ha="right", va="bottom",
            fontsize=9.5, color=S.INK_2)
    bx.set_xlim(0, 10)
    bx.set_xlabel("Records that describe snakebite care (%)\ndot = estimate, line = 95% Wilson CI")
    bx.grid(axis="y", visible=False)
    n_hb = int(t[hb].snake_records.sum())
    hb_deaths = round(t[hb].deaths_per_year.sum(), -2)
    S.panel_title(bx, f"Records on snakebite care: {n_wide} of {n_all:,} (matcher: {n_asv})")
    S.fig_title(fig, f"Only {n_wide} of {n_all:,} facility records describe snakebite care, and {n_hb} of them are in the "
                     f"eight states with {hb_share*100:.0f}% of India's snakebite deaths (about {hb_deaths:,.0f} a year)")
    note(fig, "Deaths: Suraweera et al., eLife 2020;9:e54076, Table 3 (Million Death Study, estimated deaths 2001-14 / 14), "
              "https://elifesciences.org/articles/54076. Records: own, non-negated sentences of derived/v1/claims.parquet that "
              "mention snake bite, snakebite, anti-snake venom, antivenom or ASV, excluding 'Animal bites (Excluding Snake Bite)' "
              "and snake bite wound care; 'matcher' = the planner's anti_snake_venom evidence words (kb/pathways/capabilities.json), "
              "which miss 'snake bite' on its own. States from "
              "derived/v1/facility_location.parquet, grouped as in Table 3. Websites: kb/web_evidence/out/web_service_summary.parquet "
              "(snakebite_antivenom, web_positive; includes non-treatment mentions such as audit committees).", width=205)
    top = t.iloc[0]
    named = ", ".join(f"{r.mds_group} {int(r.snake_records)}" for r in t.itertuples() if r.snake_records > 0)
    alt = (f"Two aligned horizontal charts by state. Left: estimated snakebite deaths per year (2001-2014 average, "
           f"Million Death Study), highest in {top.mds_group} at about {top.deaths_per_year:,.0f}; the eight higher-burden "
           f"states account for {hb_share*100:.0f}%. Right: share of facility records that describe snakebite care with 95% "
           f"intervals: {n_wide} of {n_all:,} in all ({named}); {n_hb} in the higher-burden states, none in Bihar "
           f"(0 of {int(t[t.mds_group == 'Bihar'].records.iloc[0])}). The planner's anti-snake venom matcher finds only "
           f"{n_asv}, all in Kerala and Tamil Nadu, so it abstains everywhere. Facility websites mention snakebite in "
           f"{n_web} records.")
    S.save(fig, CHARTS / "s4_snakebite", alt)


def main():
    t, n_all, n_asv, n_web, n_wide = build()
    t.to_csv(DATA / "s4_snakebite.csv", index=False)
    chart(t, n_all, n_asv, n_web, n_wide)
    print(t[["mds_group", "deaths_per_year", "records", "snake_records", "asv_records", "snake_hi95",
             "web_snakebite_records"]].round(3).to_string())
    print(n_all, n_asv, n_web, n_wide)


if __name__ == "__main__":
    main()
