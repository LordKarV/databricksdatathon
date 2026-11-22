"""Story 5: what facility websites say that the dataset does not, and the reverse.

Population: usable records with an attributable own site or branch page (identity high or medium, never a chain
homepage). Dataset claim = claims_io.dataset_claims (text_pos or a mapped specialty). Two web evidence levels:
  any    = a positive quote (the kb/web_evidence definition; QA population-weighted precision 0.69);
  strict = strong quote on 2+ pages or a list item (QA cells A and B, 16 of 16 correct).
This re-derives kb/web_evidence/out/compare_by_service.csv (asserted below) and adds the strict level and the
claim-kind x source-overlap split.
Inputs: kb/web_evidence/out/{site_identity, web_service_summary, web_services}.parquet, data/raw/facilities.parquet
(source_urls), kb/taxonomy (via claims_io.dataset_claims), kb/web_evidence/qa/out/qa_results.json.
Outputs: charts/s5_web_by_service.{png,svg,txt}, charts/s5_why_unconfirmed.{png,svg,txt},
data/s5_by_service.csv, data/s5_claim_kind.csv, data/s5_claims.csv.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

import claims_io as io
from claims_io import S

MIN_CLAIMS = 100


def host(u: str) -> str:
    return re.sub(r"^(www|m)\.", "", re.sub(r"^https?://", "", u.strip().lower()).split("/")[0])


def population():
    si = io.read("site_identity")
    own = si[si.attributable & si.kind.isin(["site", "branch"])]
    raw = io.read("facilities_raw", ["unique_id", "source_urls"]).drop_duplicates("unique_id")
    hosts = {}
    for u, s in zip(raw.unique_id, raw.source_urls):
        try:
            vals = json.loads(s) if isinstance(s, str) and s.startswith("[") else []
        except ValueError:
            vals = []
        hosts[u] = {host(x) for x in vals if isinstance(x, str)}
    same = {u for u, site in zip(own.unique_id, own.site) if site in hosts.get(u, set())}
    return set(own.unique_id), set(own[own.has_services_page].unique_id), same


def web_levels():
    ss = io.read("web_service_summary")
    ss = ss[ss.web_positive & (ss.scope != "chain_home")]
    lk = io.read("web_services", ["unique_id", "service_id", "quote", "final_url", "field", "line_kind", "attributable",
                                  "scope"])
    any_row = set(zip(lk[lk.attributable & lk.scope.isin(["own_site", "branch_page"])].unique_id,
                      lk[lk.attributable & lk.scope.isin(["own_site", "branch_page"])].service_id))
    lk = lk.drop_duplicates(["unique_id", "service_id", "quote", "final_url", "field"])
    m = ss.merge(lk[["unique_id", "service_id", "quote", "final_url", "field", "line_kind"]],
                 left_on=["unique_id", "service_id", "best_quote", "best_url", "best_field"],
                 right_on=["unique_id", "service_id", "quote", "final_url", "field"], how="left")
    pos = set(zip(m.unique_id, m.service_id))
    strict = set(zip(*m[m.web_positive_strong & ((m.n_pages_positive >= 2) | (m.line_kind == "item"))][
        ["unique_id", "service_id"]].T.values))
    return pos, strict, any_row


def build():
    pop, has_sp, same = population()
    pos, strict, any_row = web_levels()
    dc = io.dataset_claims()
    dc = dc[dc.unique_id.isin(pop)]
    k = list(zip(dc.unique_id, dc.service_id))
    dc = dc.assign(conf=[x in pos for x in k], conf_strict=[x in strict for x in k], any_web=[x in any_row for x in k],
                   services_page=dc.unique_id.isin(has_sp), site_in_sources=dc.unique_id.isin(same))
    claims = dc[dc.text_pos | dc.spec].copy()
    claims["kind"] = np.where(claims.text_pos, "text", "specialty_only")
    mention = set(zip(dc.unique_id, dc.service_id))  # text_any or spec: any dataset mention
    rows = []
    for s in sorted(claims.service_id.unique().tolist()) + ["ALL"]:
        c = claims if s == "ALL" else claims[claims.service_id == s]
        wp = {x for x in pos if x[0] in pop and (s == "ALL" or x[1] == s)}
        ws = {x for x in strict if x[0] in pop and (s == "ALL" or x[1] == s)}
        sil = c[c.services_page]
        r = {"service_id": s, "dataset_claims": len(c)}
        for lab, kk, nn in [("confirm", c.conf.sum(), len(c)), ("confirm_strict", c.conf_strict.sum(), len(c)),
                            ("web_only", len(wp - mention), len(wp)), ("web_only_strict", len(ws - mention), len(ws)),
                            ("silent", (~sil.any_web).sum(), len(sil))]:
            rr = io.rate_row(kk, nn)
            r.update({f"{lab}_k": rr["k"], f"{lab}_n": rr["n"], f"{lab}_rate": rr["rate"], f"{lab}_lo": rr["lo"],
                      f"{lab}_hi": rr["hi"]})
        rows.append(r)
    bs = pd.DataFrame(rows)
    ref = io.read("compare_by_service").set_index("service_id")
    for s, r in bs.set_index("service_id").iterrows():  # re-derivation check against the published table
        assert r.dataset_claims == ref.loc[s, "dataset_claims"] and r.confirm_k == ref.loc[s, "confirmed"], s
        assert r.web_only_k == ref.loc[s, "web_only"] and r.silent_k == ref.loc[s, "silent"], s
    kind = []
    for kname in ["text", "specialty_only"]:
        for same_src in [False, True]:
            g = claims[(claims.kind == kname) & (claims.site_in_sources == same_src)]
            for lab, col in [("any", "conf"), ("strict", "conf_strict")]:
                kind.append({"claim_kind": kname, "site_in_vf_sources": same_src, "web_level": lab,
                             **io.rate_row(g[col].sum(), len(g))})
    return bs, pd.DataFrame(kind), claims, len(pop)


NAMES = {"emergency_24x7": "24x7 emergency", "icu": "ICU", "ultrasound": "Ultrasound", "trauma_care": "Trauma care",
         "ct_scan": "CT scan", "neurosurgery": "Neurosurgery", "dialysis": "Dialysis", "mri": "MRI",
         "cataract_surgery": "Cataract surgery", "institutional_delivery": "Institutional delivery",
         "cath_lab_angioplasty": "Cath lab / angioplasty", "cardiac_surgery": "Cardiac surgery",
         "surgical_oncology": "Surgical oncology", "chemotherapy": "Chemotherapy", "nicu": "NICU",
         "high_risk_pregnancy": "High-risk pregnancy", "psychiatric_care": "Psychiatric care",
         "blood_bank": "Blood bank", "orthopaedic_trauma_surgery": "Orthopaedic trauma surgery",
         "ventilator_support": "Ventilator support", "kidney_transplant": "Kidney transplant",
         "radiotherapy": "Radiotherapy", "emergency_csection": "Emergency C-section", "picu": "PICU",
         "burn_care": "Burn care", "eye_emergency": "Eye emergency", "de_addiction": "De-addiction",
         "tb_care": "TB care", "stroke_care": "Stroke care", "safe_abortion_mtp": "Safe abortion (MTP)"}


def chart_by_service(bs: pd.DataFrame, n_pop: int):
    d = bs[(bs.service_id != "ALL") & (bs.dataset_claims >= MIN_CLAIMS)].sort_values("confirm_rate").reset_index(drop=True)
    al = bs[bs.service_id == "ALL"].iloc[0]
    fig, (ax, bx) = S.new_figure(size=(12.5, 9), ncols=2, sharey=True)
    ys = np.arange(len(d))
    for axx, lab in [(ax, "confirm"), (bx, "web_only")]:
        for lev, mk, fc in [("", "o", S.CATEGORICAL[0]), ("_strict", "o", S.SURFACE)]:
            col = f"{lab}{lev}"
            axx.errorbar(d[f"{col}_rate"] * 100, ys + (0.17 if lev else -0.17),
                         xerr=[(d[f"{col}_rate"] - d[f"{col}_lo"]) * 100, (d[f"{col}_hi"] - d[f"{col}_rate"]) * 100],
                         fmt=mk, ms=7, mfc=fc, mec=S.CATEGORICAL[0], mew=1.6, color=S.CATEGORICAL[0], elinewidth=1.2,
                         capsize=0, zorder=3)
        axx.axvline(al[f"{lab}_rate"] * 100, color=S.INK_2, lw=1, ls=(0, (4, 3)))
        axx.set_xlim(0, 100)
        axx.grid(axis="y", visible=False)
    ax.set_yticks(ys, [f"{NAMES.get(s, s)} ({n:,})" for s, n in zip(d.service_id, d.dataset_claims)], fontsize=10.5)
    ax.set_ylim(-0.7, len(d) - 0.3)
    ax.set_xlabel("Dataset claims the website confirms (%)")
    bx.set_xlabel("Website services the dataset never mentions (%)")
    S.panel_title(ax, "Of dataset claims (n in brackets)")
    S.panel_title(bx, f"Of positive website pairs (all: {al.web_only_n:,})")
    ax.text(al.confirm_rate * 100 + 1, -0.6, f"all services {al.confirm_rate:.0%} (filled)", fontsize=10, color=S.INK_2)
    bx.text(al.web_only_rate * 100 + 1, -0.6, f"all services {al.web_only_rate:.0%} (filled)", fontsize=10, color=S.INK_2)
    for i, (fc, lab) in enumerate([(S.CATEGORICAL[0], "Filled: any positive quote"),
                                   (S.SURFACE, "Hollow: strict quote only")]):
        y = 0.17 - i * 0.04  # empty lower-right corner of the left panel (bottom rows all sit below 60%)
        ax.plot([0.68], [y], "o", ms=7, mfc=fc, mec=S.CATEGORICAL[0], mew=1.6, transform=ax.transAxes, clip_on=False)
        ax.text(0.70, y, lab, transform=ax.transAxes, va="center", fontsize=10, color=S.INK)
    S.fig_title(fig, f"Websites confirm {al.confirm_rate:.0%} of dataset claims and add {al.web_only_k:,} services the "
                     f"dataset never mentions; psychiatric care is confirmed least, ICU and cataract surgery most")
    S.source_note(fig, f"Sources: kb/web_evidence/out (site_identity, web_service_summary, web_services), "
                       f"{io.rel('lexicon_matches')}, {io.rel('specialty_map')}, {io.rel('facilities_raw')}.\n"
                       f"Population: {n_pop:,} records with an attributable own site. Services with {MIN_CLAIMS}+ dataset "
                       "claims; bars are 95% Wilson intervals; dashed line: all services.\nFilled dot: any positive quote "
                       "(QA precision 0.69, weighted). Hollow dot: strict quote, strong and on 2+ pages or a list item "
                       "(QA 16/16).")
    lo, hi = d.iloc[0], d.iloc[-1]
    alt = (f"Two dot plots by service for {n_pop:,} records with their own website. Left: share of dataset claims the "
           f"website confirms, from {NAMES.get(lo.service_id)} {lo.confirm_rate:.0%} ({lo.confirm_k} of "
           f"{lo.dataset_claims}) to {NAMES.get(hi.service_id)} {hi.confirm_rate:.0%}; all services "
           f"{al.confirm_rate:.0%} ({al.confirm_k:,} of {al.dataset_claims:,}), {al.confirm_strict_rate:.0%} with strict "
           f"quotes only. Right: share of positive website service pairs that the dataset never mentions, "
           f"{al.web_only_rate:.0%} overall ({al.web_only_k:,} of {al.web_only_n:,}), {al.web_only_strict_rate:.0%} with "
           f"strict quotes.")
    S.save(fig, io.chart_path("s5_web_by_service"), alt)


def within_service_gap(claims: pd.DataFrame) -> dict:
    """Is the sentence vs specialty-only gap a service-mix artefact? Compare kinds inside each service."""
    t = claims.groupby(["service_id", "kind"]).conf.agg(["sum", "size"]).unstack().dropna()
    t = t[(t[("size", "specialty_only")] >= 20) & (t[("size", "text")] >= 20)]
    gap = t[("sum", "text")] / t[("size", "text")] - t[("sum", "specialty_only")] / t[("size", "specialty_only")]
    return {"k": int((gap > 0).sum()), "n": len(t), "gap": float(gap.median() * 100)}


def chart_kind(kd: pd.DataFrame, wg: dict):
    fig, ax = S.new_figure(size=(11, 5.6))
    order = [("text", False), ("text", True), ("specialty_only", False), ("specialty_only", True)]
    labels = {("text", False): "Claim sentence,\nsite not among record's sources",
              ("text", True): "Claim sentence,\nsite among record's sources",
              ("specialty_only", False): "Specialties value only,\nsite not among sources",
              ("specialty_only", True): "Specialties value only,\nsite among sources"}
    ys = np.arange(len(order))
    for i, (lev, col) in enumerate([("any", S.CATEGORICAL[0]), ("strict", S.SEQUENTIAL[3])]):
        d = kd[kd.web_level == lev].set_index(["claim_kind", "site_in_vf_sources"]).loc[order]
        y = ys + (i - 0.5) * 0.36
        bars = ax.barh(y, d.rate * 100, height=0.34, color=col, **S.bar_style())
        S.add_interval(ax, y, d.lo * 100, d.hi * 100, horizontal=True, cap=3)
        for yy, r in zip(y, d.itertuples()):
            ax.text(r.hi * 100 + 1, yy, f"{r.rate:.0%}  ({r.k:,}/{r.n:,})", va="center", fontsize=10)
    ax.set_yticks(ys, [labels[o] for o in order], fontsize=10.5)
    ax.set_ylim(len(order) - 0.5, -0.9)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Dataset claims confirmed by the facility's own website (%, 95% Wilson)")
    ax.grid(axis="y", visible=False)
    for i, (lab, col) in enumerate([("Any positive quote", S.CATEGORICAL[0]), ("Strict quote", S.SEQUENTIAL[3])]):
        ax.add_patch(__import__("matplotlib").patches.Rectangle((60 + i * 20, -0.8), 2, 0.25, color=col))
        ax.text(63 + i * 20, -0.675, lab, va="center", fontsize=10.5)
    a = kd[(kd.web_level == "any") & (kd.claim_kind == "text") & ~kd.site_in_vf_sources].iloc[0]
    b = kd[(kd.web_level == "any") & (kd.claim_kind == "specialty_only") & ~kd.site_in_vf_sources].iloc[0]
    S.finding_title(ax, f"A website the record does not cite confirms {a.rate:.0%} of claims made in a sentence but "
                        f"only {b.rate:.0%} of claims resting on a specialties value alone", wrap=72)
    S.source_note(fig, "Sources: as for s5_web_by_service. 'Site among sources' means the record's source_urls include "
                       "the crawled host, so the dataset text may have been\nextracted from that same site: those "
                       f"confirmations are not independent evidence. The sentence-vs-specialty gap holds within services: "
                       f"higher for sentences in {wg['k']} of {wg['n']} services\nwith 20+ claims of each kind (median gap "
                       f"{wg['gap']:.0f} points). 'Any' quotes have QA precision 0.69, so some confirmations are false.")
    rows = "; ".join(f"{r.claim_kind}, site in sources {r.site_in_vf_sources}, {r.web_level}: {r.k:,} of {r.n:,} "
                     f"({r.rate:.0%})" for r in kd.itertuples())
    alt = ("Grouped bars of the share of dataset service claims that the facility's own website confirms, split by "
           f"claim kind and by whether the website is among the record's cited sources. {rows}. Within services, "
           f"sentence claims are confirmed more often in {wg['k']} of {wg['n']} services with 20 or more claims of each kind.")
    S.save(fig, io.chart_path("s5_why_unconfirmed"), alt)


def main():
    bs, kd, claims, n_pop = build()
    io.save_csv(bs, "s5_by_service")
    io.save_csv(kd, "s5_claim_kind")
    io.save_csv(claims[["unique_id", "service_id", "kind", "conf", "conf_strict", "any_web", "services_page",
                        "site_in_sources"]], "s5_claims")
    chart_by_service(bs, n_pop)
    wg = within_service_gap(claims)
    print('within-service gap', wg)
    chart_kind(kd, wg)
    print(bs[bs.service_id == "ALL"].T.to_string())
    print(kd.to_string(index=False))


if __name__ == "__main__":
    main()
