"""Story 1: the long tail of specialty values, and how the taxonomy folds it into a few dozen services.

Inputs: kb/taxonomy/specialty_map.csv (2,933 distinct raw values, label and facility count),
data/raw/facilities.parquet (raw specialties arrays, for the per-type default-tag check),
model/proto/evidence/pair_features.parquet (facility type).
Outputs: charts/s1_longtail.{png,svg,txt}, charts/s1_default_tags.{png,svg,txt},
data/s1_rank_frequency.csv, data/s1_label_shares.csv, data/s1_default_tags.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import claims_io as io
from claims_io import S

KIND_ORDER = ["service", "too_general", "not_a_service", "out_of_scope"]
KIND_LABEL = {"service": "Maps to a taxonomy service", "too_general": "Too general (e.g. internal medicine)",
              "not_a_service": "Not a service (e.g. healthcare tourism)", "out_of_scope": "Out of scope (e.g. dentistry)"}
# 3 categorical hues on a scatter (style cap) plus the neutral for the biggest, least relevant group.
KIND_COLOR = {"service": S.CATEGORICAL[0], "too_general": S.CATEGORICAL[1], "not_a_service": S.CATEGORICAL[2],
              "out_of_scope": S.OTHER}


def label_kind(sid: str) -> str:
    return sid if sid in ("too_general", "out_of_scope", "not_a_service") else "service"


def build_tables():
    m = io.read("specialty_map").copy()
    m = m[m.specialty != ""]  # one empty-string value, not a specialty (basis "empty or whitespace")
    m["kind"] = m.service_id.map(label_kind)
    m = m.sort_values("n_facilities", ascending=False).reset_index(drop=True)
    m["rank"] = np.arange(1, len(m) + 1)
    rf = m[["rank", "specialty", "service_id", "kind", "n_facilities", "method"]]

    services = sorted({s for v in m.service_id[m.kind == "service"] for s in v.split(";")})
    tot_v, tot_m = len(m), int(m.n_facilities.sum())
    shares = pd.DataFrame([{"kind": k, "distinct_values": int((m.kind == k).sum()),
                            "facility_mentions": int(m.n_facilities[m.kind == k].sum())} for k in KIND_ORDER])
    shares["share_values"] = shares.distinct_values / tot_v
    shares["share_mentions"] = shares.facility_mentions / tot_m
    stats = {"values": tot_v, "mentions": tot_m, "services": len(services),
             "singletons": int((m.n_facilities == 1).sum()), "le2": int((m.n_facilities <= 2).sum()),
             "top10_share": m.n_facilities.head(10).sum() / tot_m,
             "top10_count": int(m.n_facilities.head(10).sum()),
             "service_values": int((m.kind == "service").sum()),
             "slope": float(np.polyfit(np.log10(m["rank"]), np.log10(m.n_facilities), 1)[0])}
    return rf, shares, stats


def build_defaults():
    """Share of each facility type whose raw specialties list contains each of the 8 most common values."""
    f = io.facilities()[["unique_id", "facility_type"]]
    sp = io.raw_specialties().merge(f, on="unique_id")
    top = sp.specialty.value_counts().head(8).index.tolist()
    n_type = f.facility_type.value_counts()
    rows = []
    for t in ["hospital", "clinic", "dentist"]:
        for v in top:
            k = sp[(sp.facility_type == t) & (sp.specialty == v)].unique_id.nunique()
            r = io.rate_row(k, n_type[t])
            rows.append({"facility_type": t, "specialty": v, **r})
    return pd.DataFrame(rows), top, n_type


def chart_longtail(rf, shares, st):
    fig, (ax, bx) = S.new_figure(ncols=2, gridspec_kw={"width_ratios": [1.55, 1]})
    # one scatter in shuffled order, so dense ties (the flat steps at 1, 2, 3 facilities) show the real colour mix
    d = rf.sample(frac=1, random_state=3)
    ax.scatter(d["rank"], d.n_facilities, s=9, c=d.kind.map(KIND_COLOR), alpha=0.8, linewidths=0, zorder=2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Rank of specialty value (1 = most common, log scale)")
    ax.set_ylabel("Facilities listing the value (log scale)")
    top = rf.iloc[0]
    ax.annotate(f"{top.specialty}: {top.n_facilities:,} facilities", (1, top.n_facilities), xytext=(14, -4),
                textcoords="offset points", fontsize=10.5, color=S.INK, va="center")
    first1 = rf[rf.n_facilities == 1]["rank"].min()
    ax.annotate(f"{st['singletons']:,} values ({st['singletons'] / st['values']:.0%})\nappear in exactly one facility",
                (np.sqrt(first1 * rf["rank"].max()), 1), xytext=(0.98, 0.62), textcoords="axes fraction", fontsize=10.5,
                color=S.INK, ha="right",
                arrowprops=dict(arrowstyle="-", color=S.INK_2, lw=0.8))
    ax.set_ylim(0.6, 2e4)
    S.panel_title(ax, f"All {st['values']:,} distinct raw values, n = 9,959 records")
    # direct labels in place of a legend: one line per colour, in text ink next to a coloured marker
    for i, k in enumerate(KIND_ORDER):
        y = 0.30 - i * 0.065
        ax.scatter([0.035], [y], transform=ax.transAxes, s=40, color=KIND_COLOR[k], clip_on=False)
        n = int(shares.distinct_values[shares.kind == k].iloc[0])
        ax.text(0.06, y, f"{KIND_LABEL[k]}: {n:,} values", transform=ax.transAxes, va="center", fontsize=10.5)

    # right panel: two 100% bars, distinct values vs facility mentions, split by label kind
    ys = {"Distinct values": "share_values", "Facility mentions": "share_mentions"}
    for j, (lab, col) in enumerate(ys.items()):
        left = 0.0
        for k in KIND_ORDER:
            w = float(shares[col][shares.kind == k].iloc[0]) * 100
            bx.barh(j, w, left=left, color=KIND_COLOR[k], height=0.55, **S.bar_style())
            if w >= 6:
                ink = "#ffffff" if k in ("service",) else S.INK
                bx.text(left + w / 2, j, f"{w:.0f}%", ha="center", va="center", fontsize=11, color=ink)
            left += w
    bx.set_yticks([0, 1], [f"Distinct values\n(n = {st['values']:,})", f"Facility mentions\n(n = {st['mentions']:,})"])
    bx.invert_yaxis()
    bx.set_xlim(0, 100)
    bx.set_xlabel("Share (%)")
    bx.grid(axis="y", visible=False)
    sv = shares.set_index("kind")
    bx.text(0, 1.55, f"{sv.distinct_values['service']:,} values ({sv.share_values['service']:.0%}) map to the "
                     f"{st['services']} services;\nthey carry {sv.share_mentions['service']:.0%} of mentions.",
            fontsize=10.5, color=S.INK_2, va="top")
    bx.set_ylim(1.9, -0.6)
    S.panel_title(bx, "Where the values go after the taxonomy")
    S.fig_title(fig, f"Specialty strings are a long tail: {st['singletons']:,} of {st['values']:,} values occur once, "
                     f"and only {st['service_values']} map to any taxonomy service ({st['services']} of the 36 receive one)")
    S.source_note(fig, f"Source: {io.rel('specialty_map')} (labels by rule, LLM, manual and fuzzy match). "
                       f"Log-log slope of rank vs count: {st['slope']:.2f}. "
                       "2,933 values in the file include one empty string, dropped here.")
    alt = (f"Rank-frequency plot of {st['values']:,} distinct specialty values in 9,959 facility records, on log "
           f"axes. The most common, {top.specialty}, is listed by {top.n_facilities:,} facilities; "
           f"{st['singletons']:,} values ({st['singletons'] / st['values']:.0%}) appear in exactly one facility. "
           f"The top 10 values account for {st['top10_share']:.0%} of {st['mentions']:,} facility mentions. "
           f"{sv.distinct_values['service']:,} values ({sv.share_values['service']:.0%}) map to one of "
           f"{st['services']} taxonomy services and carry {sv.share_mentions['service']:.0%} of mentions; "
           f"{sv.distinct_values['out_of_scope']:,} are out of scope and {sv.distinct_values['too_general']:,} too general.")
    S.save(fig, io.chart_path("s1_longtail"), alt)


def chart_defaults(d, top, n_type):
    fig, ax = S.new_figure(size=(12, 5.6))
    types = ["hospital", "clinic", "dentist"]
    grid = d.pivot(index="facility_type", columns="specialty", values="rate").loc[types, top] * 100
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", [S.SURFACE] + S.SEQUENTIAL)
    ax.imshow(grid.values, cmap=cmap, vmin=0, vmax=100, aspect="auto")
    for i, t in enumerate(types):
        for j, v in enumerate(top):
            r = d[(d.facility_type == t) & (d.specialty == v)].iloc[0]
            ink = "#ffffff" if r.rate > 0.6 else S.INK
            ax.text(j, i, f"{r.rate:.0%}\n{r.k:,}/{r.n:,}", ha="center", va="center", fontsize=10, color=ink)
    ax.set_xticks(range(len(top)), [v for v in top], rotation=25, ha="right")
    ax.set_yticks(range(3), [f"{t.capitalize()} (n = {n_type[t]:,})" for t in types])
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xlabel("The 8 most common raw specialty values")
    h = d[(d.facility_type == "hospital") & (d.specialty == "internalMedicine")].iloc[0]
    c = d[(d.facility_type == "clinic") & (d.specialty == "familyMedicine")].iloc[0]
    S.finding_title(ax, f"The most common specialties are type defaults: internalMedicine on {h.k:,} of {h.n:,} "
                        f"hospitals, familyMedicine on {c.k:,} of {c.n:,} clinics",
                    subtitle="Share of each facility type whose specialties list contains the value (cell: % and k/n)", wrap=80)
    S.source_note(fig, f"Source: {io.rel('facilities_raw')} specialties arrays; type from {io.rel('pair_features')}.\n"
                       "95% Wilson intervals in data/s1_default_tags.csv; widest interval "
                       f"{(d.hi - d.lo)[d.facility_type != 'dentist'].max() * 100:.1f} points for hospitals and clinics, "
                       f"{(d.hi - d.lo)[d.facility_type == 'dentist'].max() * 100:.1f} for dentists.")
    dn = d[(d.facility_type == "dentist") & (d.specialty == "familyMedicine")].iloc[0]
    alt = (f"Heat table of the 8 most common specialty values by facility type. internalMedicine is listed by "
           f"{h.k:,} of {h.n:,} hospitals ({h.rate:.1%}); familyMedicine by {c.k:,} of {c.n:,} clinics ({c.rate:.1%}) "
           f"and by {dn.k} of {dn.n} dentists ({dn.rate:.0%}). Values present on nearly every record of a type carry "
           f"no information about what that facility offers.")
    S.save(fig, io.chart_path("s1_default_tags"), alt)


def main():
    rf, shares, st = build_tables()
    io.save_csv(rf, "s1_rank_frequency")
    io.save_csv(shares, "s1_label_shares")
    chart_longtail(rf, shares, st)
    d, top, n_type = build_defaults()
    io.save_csv(d, "s1_default_tags")
    chart_defaults(d, top, n_type)
    print("s1", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in st.items()})
    print(shares.to_string(index=False))
    print(d.to_string(index=False))
    return st


if __name__ == "__main__":
    main()
