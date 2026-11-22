"""Story 2: claim inflation. How many services, specialties and claim sentences a record carries, against its size.

Inputs: derived/v1/claims.parquet (claim sentences), kb/taxonomy/out/lexicon_matches.parquet and
kb/taxonomy/specialty_map.csv (services claimed, via claims_io.dataset_claims), data/raw/facilities.parquet
(specialties), model/proto/evidence/pair_features.parquet (type, beds, doctors as cleaned there).
Outputs: charts/s2_inflation.{png,svg,txt}, data/s2_facility_claims.csv (one row per record),
data/s2_by_size.csv (medians, IQR and bootstrap intervals per size bin), data/s2_small_tertiary.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import claims_io as io
from claims_io import S

DOC_BINS = [(1, 1, "1"), (2, 4, "2-4"), (5, 9, "5-9"), (10, 49, "10-49"), (50, np.inf, "50+")]
TYPES = {"hospital": S.CATEGORICAL[0], "clinic": S.CATEGORICAL[1]}
TERTIARY = ["icu", "neurosurgery", "cardiac_surgery", "cath_lab_angioplasty", "kidney_transplant", "radiotherapy",
            "dialysis", "trauma_care"]


def facility_table() -> pd.DataFrame:
    f = io.facilities()
    c = io.read("claims", ["unique_id", "dup_in_record"])
    n_claims = c[~c.dup_in_record].groupby("unique_id").size().rename("n_claims")
    dc = io.dataset_claims()
    svc = dc[dc.text_pos | dc.spec].groupby("unique_id").service_id.nunique().rename("n_services")
    spec = io.raw_specialties().groupby("unique_id").size().rename("n_specialty_values")
    f = f.set_index("unique_id").join([n_claims, svc, spec]).fillna(
        {"n_claims": 0, "n_services": 0, "n_specialty_values": 0}).reset_index()

    def dbin(d):
        if not np.isfinite(d) or d <= 0:
            return "not stated"
        return next(lab for lo, hi, lab in DOC_BINS if lo <= d <= hi)
    f["doctor_bin"] = f.doctors.map(dbin)
    return f, dc


def boot_median(x, n_boot=1000, seed=11):
    x = np.asarray(x, float)
    if len(x) == 0:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    m = np.median(x[rng.integers(0, len(x), (n_boot, len(x)))], axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def by_size(f: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for t in TYPES:
        for lab in [b[2] for b in DOC_BINS] + ["not stated"]:
            g = f[(f.facility_type == t) & (f.doctor_bin == lab)]
            for metric in ["n_services", "n_claims", "n_specialty_values"]:
                x = g[metric]
                lo, hi = boot_median(x)
                rows.append({"facility_type": t, "doctor_bin": lab, "metric": metric, "n": len(g),
                             "median": float(x.median()) if len(g) else np.nan,
                             "q25": float(x.quantile(.25)) if len(g) else np.nan,
                             "q75": float(x.quantile(.75)) if len(g) else np.nan, "median_lo": lo, "median_hi": hi})
    return pd.DataFrame(rows)


def small_tertiary(f: pd.DataFrame, dc: pd.DataFrame) -> pd.DataFrame:
    """Records stating 1 or 2 doctors that claim a tertiary service (text claim or mapped specialty)."""
    small = f[(f.doctors >= 1) & (f.doctors <= 2)]
    c = dc[(dc.text_pos | dc.spec) & dc.unique_id.isin(small.unique_id)]
    rows = [{"service_id": s, **io.rate_row(c[c.service_id == s].unique_id.nunique(), len(small)),
             "text_claims": int(c[(c.service_id == s) & c.text_pos].unique_id.nunique())} for s in TERTIARY]
    any_t = c[c.service_id.isin(TERTIARY)].unique_id.nunique()
    rows.append({"service_id": "any_of_these", **io.rate_row(any_t, len(small)),
                 "text_claims": int(c[c.service_id.isin(TERTIARY) & c.text_pos].unique_id.nunique())})
    return pd.DataFrame(rows)


LABEL = {"icu": "ICU", "neurosurgery": "Neurosurgery", "cardiac_surgery": "Cardiac surgery",
         "cath_lab_angioplasty": "Cath lab / angioplasty", "kidney_transplant": "Kidney transplant",
         "radiotherapy": "Radiotherapy", "dialysis": "Dialysis", "trauma_care": "Trauma care",
         "any_of_these": "Any of these 8"}


def chart(f, b, st, t):
    fig, (ax, bx) = S.new_figure(ncols=2, gridspec_kw={"width_ratios": [1.2, 1]})
    labs = [x[2] for x in DOC_BINS] + ["not stated"]
    xs = np.arange(len(labs))
    for i, (ty, col) in enumerate(TYPES.items()):
        d = b[(b.metric == "n_services") & (b.facility_type == ty)].set_index("doctor_bin").loc[labs]
        off = (i - 0.5) * 0.24
        ax.vlines(xs + off, d.q25, d.q75, color=col, lw=1.6, alpha=0.5)
        ax.errorbar(xs + off, d["median"], yerr=[d["median"] - d.median_lo, d.median_hi - d["median"]],
                    fmt="o", color=col, ms=8, mec=S.SURFACE, mew=1.5, elinewidth=3, capsize=0, zorder=3)
        ax.annotate(f"{ty.capitalize()}s", (len(labs) - 2 + off, d["median"]["50+"]), xytext=(10, 0),
                    textcoords="offset points", va="center", fontsize=11, color=S.INK)
    ns = {ty: b[(b.metric == "n_services") & (b.facility_type == ty)].set_index("doctor_bin").n for ty in TYPES}
    ax.set_xticks(xs, [f"{lab}\nH {ns['hospital'][lab]:,}\nC {ns['clinic'][lab]:,}" for lab in labs], fontsize=10.5)
    ax.axvspan(len(labs) - 1.5, len(labs) - 0.5, color=S.NEUTRAL, zorder=0)
    ax.set_xlabel("Doctors stated in the record (H, C: hospitals and clinics per bin)")
    ax.set_ylabel("Taxonomy services claimed (of 36)")
    ax.set_ylim(-0.4, 13)
    S.panel_title(ax, "Dot: median, 95% bootstrap interval; thin bar: middle half")
    small = [f"{ty}s {lab} (n = {ns[ty][lab]})" for ty in TYPES for lab in labs if ns[ty][lab] < S.SMALL_N]
    if small:
        S.small_n_note(ax, 0, where=(0.99, 0.94), text="Small sample: " + ", ".join(small))

    d = t.iloc[::-1].reset_index(drop=True)
    ys = np.arange(len(d))
    spec_only = d.k - d.text_claims
    bx.barh(ys, d.text_claims / d.n * 100, color=S.CATEGORICAL[0], height=0.62, **S.bar_style())
    bx.barh(ys, spec_only / d.n * 100, left=d.text_claims / d.n * 100, color=S.SEQUENTIAL[3], height=0.62,
            **S.bar_style())
    S.add_interval(bx, ys, d.lo * 100, d.hi * 100, horizontal=True)
    for y, r in zip(ys, d.itertuples()):
        bx.text(r.hi * 100 + 0.8, y, f"{r.k:,} ({r.text_claims:,} in text)", va="center", fontsize=10.5)
    bx.set_yticks(ys, [LABEL[s] for s in d.service_id])
    bx.set_xlim(0, 52)
    bx.set_xlabel(f"% of {int(d.n.iloc[0]):,} records with 1-2 doctors (95% Wilson)")
    bx.grid(axis="y", visible=False)
    bx.text(0.99, 0.42, "Dark: a claim sentence says so\nLight: only a specialties value", transform=bx.transAxes,
            ha="right", va="center", fontsize=10.5, color=S.INK_2)
    S.panel_title(bx, "Tertiary services claimed by the smallest records")
    tert = t[t.service_id == "any_of_these"].iloc[0]
    icu = t[t.service_id == "icu"].iloc[0]
    S.fig_title(fig, f"Small records claim big services: {tert.k:,} of {tert.n:,} records that state 1-2 doctors "
                     f"({tert.rate:.0%}) claim a tertiary service, {icu.k} of them an ICU")
    S.source_note(fig, f"Sources: {io.rel('claims')}, {io.rel('lexicon_matches')}, {io.rel('specialty_map')}, "
                       f"\n{io.rel('pair_features')} (doctors and type). Shaded: no doctor count ({st['not_stated']:,} "
                       f"hospitals and clinics).\nSpearman rho, doctors vs services claimed: {st['rho']:.2f} "
                       f"[{st['rho_lo']:.2f}, {st['rho_hi']:.2f}], n = {st['rho_n']:,}. A stated doctor count may be "
                       "the doctors named on a web page, not the staff.\nShare claiming any of the 8 rises with "
                       "stated doctors: " + ", ".join(f"{k} {v['rate']:.0%} (n = {v['n']:,})" for k, v in st["bands"].items())
                       + ". A small record's claim is a flag\nto check, not proof of a false claim.")
    alt = (f"Left: median taxonomy services claimed by doctor count. Hospitals stating 1 doctor claim a median of "
           f"{st['h1']:.0f} of 36 services, hospitals with 50 or more doctors {st['h50']:.0f}; clinics stating 1 "
           f"doctor claim {st['c1']:.0f}. Rank correlation {st['rho']:.2f} (95% interval {st['rho_lo']:.2f} to "
           f"{st['rho_hi']:.2f}). Right: of {tert.n:,} records stating 1 or 2 doctors, {tert.k:,} ({tert.rate:.0%}) "
           f"claim at least one of 8 tertiary services: ICU {icu.k}, neurosurgery "
           f"{t[t.service_id == 'neurosurgery'].k.iloc[0]}, trauma care {t[t.service_id == 'trauma_care'].k.iloc[0]}, "
           f"cardiac surgery {t[t.service_id == 'cardiac_surgery'].k.iloc[0]}. For neurosurgery most of these rest only "
           f"on a specialties value ({t[t.service_id == 'neurosurgery'].text_claims.iloc[0]} have a claim sentence). "
           "For comparison, the share claiming any of the 8 is " + ", ".join(f"{v['rate']:.0%} at {k} doctors"
           for k, v in st["bands"].items()) + ".")
    S.save(fig, io.chart_path("s2_inflation"), alt)


def main():
    f, dc = facility_table()
    io.save_csv(f[["unique_id", "facility_type", "beds", "doctors", "doctor_bin", "n_specialty_values", "n_services",
                   "n_claims", "list_truncated"]], "s2_facility_claims")
    b = by_size(f)
    io.save_csv(b, "s2_by_size")
    t = small_tertiary(f, dc)
    io.save_csv(t, "s2_small_tertiary")
    tert_ids = set(dc[(dc.text_pos | dc.spec) & dc.service_id.isin(TERTIARY)].unique_id)
    bands = {}
    for lo_, hi_, lab in [(1, 2, "1-2"), (3, 9, "3-9"), (10, 49, "10-49"), (50, np.inf, "50+")]:
        ids = f[(f.doctors >= lo_) & (f.doctors <= hi_)].unique_id
        bands[lab] = io.rate_row(ids.isin(tert_ids).sum(), len(ids))
    g = f[(f.doctors > 0) & f.facility_type.isin(TYPES)]
    rho, lo, hi = io.spearman_ci(g.doctors, g.n_services)
    gb = f[(f.beds > 0) & f.facility_type.isin(TYPES)]
    rho_b = io.spearman_ci(gb.beds, gb.n_services)
    med = lambda t, lab: b[(b.metric == "n_services") & (b.facility_type == t) & (b.doctor_bin == lab)]["median"].iloc[0]  # noqa: E731
    st = {"h1": med("hospital", "1"), "h50": med("hospital", "50+"), "c1": med("clinic", "1"),
          "rho": rho, "rho_lo": lo, "rho_hi": hi, "rho_n": len(g),
          "rho_beds": rho_b, "rho_beds_n": len(gb),
          "bands": bands, "not_stated": int(((f.doctor_bin == "not stated") & f.facility_type.isin(TYPES)).sum())}
    chart(f, b, st, t)
    print("s2", st)
    print(b[b.metric == "n_services"].to_string(index=False))
    print(t.to_string(index=False))
    return st


if __name__ == "__main__":
    main()
