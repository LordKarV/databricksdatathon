"""Story 3: the confirmation funnel for the 7 core services of the Witness Ledger model.

Stages per (facility, service), all over the 9,959 usable records:
  inside the record (nested): mentioned (T >= 1) -> stated in 2+ fields (T >= 4) -> and a prerequisite cue (P >= 1);
  outside the record (each among the mentioned): the facility's own website has a high-precision quote (strong, and on
  2+ pages or a list item: 16/16 correct in the web QA), and a matched official list names the service.
Inputs: model/proto/evidence/pair_features.parquet (T, P), kb/web_evidence/out/{site_identity, web_service_summary,
web_services}.parquet, data/external: NABH specialty scopes, LaQshya Maternity OT, MoHFW trauma care facilities,
NMC postgraduate courses (tier "strong" only).
Outputs: charts/s3_funnel.{png,svg,txt}, data/s3_funnel.csv, data/s3_pairs.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import claims_io as io
from claims_io import S

SERVICES = {"dialysis": "Dialysis", "trauma_emergency": "Trauma and emergency", "emergency_csection": "Emergency C-section",
            "nicu": "NICU", "cardiac_surgery": "Cardiac surgery", "mri": "MRI", "burn_care": "Burn care"}
WEB_IDS = {"trauma_emergency": ["trauma_care", "emergency_24x7"]}
NMC_SVC = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "cardiac_surgery": "cardiac_surgery",
           "burn_care": "burns", "trauma_emergency": "trauma"}
NABH_CODE = {"dialysis": "DIA", "trauma_emergency": "EMD"}
LIST_NOTE = {"dialysis": "NABH DIA scope, NMC DM Nephrology", "trauma_emergency": "MoHFW trauma list, NABH EMD, NMC",
             "emergency_csection": "LaQshya Maternity OT, NMC MS OBG", "nicu": "NMC DM Neonatology",
             "cardiac_surgery": "NMC MCh CTVS", "mri": "no official list", "burn_care": "NMC MCh Plastic Surgery"}
STAGES = [("mentioned", "Mentioned"), ("fields2", "In 2+ fields"), ("prereq", "...and a prerequisite"),
          ("web", "Own website confirms*"), ("listed", "On an official list")]


def web_pairs() -> tuple[set, set]:
    """(record, web service) pairs with a high-precision positive quote, and records with an attributable site."""
    si = io.read("site_identity")
    sites = set(si[si.attributable & si.kind.isin(["site", "branch"])].unique_id)
    ss = io.read("web_service_summary")
    ss = ss[ss.web_positive & (ss.scope != "chain_home")]
    lk = io.read("web_services", ["unique_id", "service_id", "quote", "final_url", "field", "line_kind"]).drop_duplicates(
        ["unique_id", "service_id", "quote", "final_url", "field"])
    ss = ss.merge(lk, left_on=["unique_id", "service_id", "best_quote", "best_url", "best_field"],
                  right_on=["unique_id", "service_id", "quote", "final_url", "field"], how="left")
    hp = ss[ss.web_positive_strong & ((ss.n_pages_positive >= 2) | (ss.line_kind == "item"))]
    return set(zip(hp.unique_id, hp.service_id)), sites


def list_pairs() -> set:
    """(record, model service) pairs named by an official list match."""
    out = set()
    nabh = io.read("nabh_match")
    for svc, code in NABH_CODE.items():
        out |= {(u, svc) for u, sp in zip(nabh.unique_id, nabh.nabh_specs) if sp is not None and code in list(sp)}
    lq = io.read("laqshya_match").merge(io.read("laqshya_facilities")[["lq_id", "Maternity OT"]], on="lq_id")
    out |= {(u, "emergency_csection") for u in lq[lq["Maternity OT"].notna()].unique_id}
    out |= {(u, "trauma_emergency") for u in io.read("tcf_match").vf_id}
    nmc = io.read("nmc_match")[["college_id", "unique_id"]].merge(io.read("nmc_labels"), on="college_id")
    nmc = nmc[nmc.tier == "strong"]
    inv = {v: k for k, v in NMC_SVC.items()}
    out |= {(u, inv[s]) for u, s in zip(nmc.unique_id, nmc.service) if s in inv}
    return out


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    pf = io.read("pair_features", ["unique_id", "service", "T", "P"])
    pf = pf[pf.service.isin(SERVICES)].copy()
    web, sites = web_pairs()
    lists = list_pairs()
    pf["mentioned"] = pf["T"] >= 1
    pf["fields2"] = pf["T"] >= 4
    pf["prereq"] = pf.fields2 & (pf.P >= 1)
    pf["has_site"] = pf.unique_id.isin(sites)
    pf["web"] = [any((u, w) in web for w in WEB_IDS.get(s, [s])) for u, s in zip(pf.unique_id, pf.service)]
    pf["listed"] = [(u, s) in lists for u, s in zip(pf.unique_id, pf.service)]
    rows = []
    for s in SERVICES:
        g = pf[pf.service == s]
        m = g[g.mentioned]
        n = len(m)
        stage = {"mentioned": (n, n), "fields2": (int(m.fields2.sum()), n), "prereq": (int(m.prereq.sum()), n),
                 "web": (int((m.web & m.has_site).sum()), int(m.has_site.sum())), "listed": (int(m.listed.sum()), n)}
        for key, (k, d) in stage.items():
            rows.append({"service": s, "stage": key, **io.rate_row(k, d), "list_source": LIST_NOTE[s]})
        all_in = m[m.prereq]
        rows.append({"service": s, "stage": "prereq_and_outside", **io.rate_row(int((all_in.web | all_in.listed).sum()), n),
                     "list_source": LIST_NOTE[s]})
        rows.append({"service": s, "stage": "outside_not_mentioned",
                     **io.rate_row(int(((g.web & g.has_site) | g.listed)[~g.mentioned].sum()), int((~g.mentioned).sum())),
                     "list_source": LIST_NOTE[s]})
    return pd.DataFrame(rows), pf


def chart(f: pd.DataFrame):
    fig, axes = S.new_figure(size=(14, 8.2), nrows=2, ncols=4, sharex=True)
    order = list(SERVICES)
    # grey = what the record says, blue = confirmed outside the record
    colors = [S.MUTED, S.OTHER, S.AXIS, S.SEMANTIC["verified"], S.SEMANTIC["verified"]]
    ys = np.arange(len(STAGES))
    for ax, s in zip(axes.flat, order):
        d = f[f.service == s].set_index("stage")
        n_m = d.loc["mentioned"].k
        for y, (key, lab), col in zip(ys, STAGES, colors):
            r = d.loc[key]
            if s == "mri" and key == "listed":
                ax.text(1, y, "no list exists", va="center", fontsize=10, color=S.MUTED, style="italic")
                continue
            if key == "web":
                # every bar is a share of mentions; the pale bar is the part that could be checked (has a site)
                ax.barh(y, r.n / n_m * 100, color=S.GRID, height=0.66, **S.bar_style())
                ax.barh(y, r.k / n_m * 100, color=col, height=0.66, **S.bar_style())
                S.add_interval(ax, [y], [r.lo * r.n / n_m * 100], [r.hi * r.n / n_m * 100], horizontal=True, cap=2.5, lw=1.1)
                ax.text(max(r.n / n_m, r.hi * r.n / n_m) * 100 + 2, y, f"{r.k:,}/{r.n:,} with a site ({r.rate:.0%})",
                        va="center", fontsize=9.5, color=S.INK)
                continue
            ax.barh(y, r.rate * 100, color=col, height=0.66, **S.bar_style())
            if key != "mentioned":
                S.add_interval(ax, [y], [r.lo * 100], [r.hi * 100], horizontal=True, cap=2.5, lw=1.1)
            txt = f"{r.k:,}" if key == "mentioned" else f"{r.k:,} ({r.rate:.0%})"
            x = 101 if key == "mentioned" else r.hi * 100 + 2
            ax.text(min(x, 101), y, txt, va="center", fontsize=9.5, color=S.INK)
        ax.set_yticks(ys, [lab for _, lab in STAGES] if ax in (axes[0, 0], axes[1, 0]) else [])
        ax.set_ylim(len(STAGES) - 0.5, -0.5)
        ax.set_xlim(0, 135)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.axhline(2.5, color=S.AXIS, lw=0.8)
        ax.grid(axis="y", visible=False)
        n = int(f[(f.service == s) & (f.stage == "mentioned")].k.iloc[0])
        S.panel_title(ax, f"{SERVICES[s]} (n = {n:,})")
    key = axes[1, 3]
    key.axis("off")
    key.text(0, 0.98, "How to read", fontsize=12, fontweight="bold", va="top")
    key.text(0, 0.86, "Every bar: % of records that mention the\nservice, 95% Wilson interval.\n\n"
                      "Above the rule: the record's own\ntext, each stage inside the one before.\n\n"
                      "Below: outside checks, each among the\nmentioned. *Website: pale bar = has an\n"
                      "attributable site to check; dark = strong\nquote on 2+ pages or a list item\n(16/16 right in QA).\n\n"
                      "Grey: the record says so. Blue: confirmed\noutside the record.\n\n"
                      "Lists used: NABH scope DIA, EMD; LaQshya\nMaternity OT; MoHFW trauma 196; NMC\n"
                      "DM/MCh/MS courses (tier strong).\nNo list covers MRI.",
             fontsize=9.6, va="top", color=S.INK_2)
    for ax in axes[1, :3]:
        ax.set_xlabel("% of facilities mentioning it")
    tot_m = int(f[f.stage == "mentioned"].k.sum())
    tot_o = int(f[f.stage == "prereq_and_outside"].k.sum())
    d = f[f.service == "dialysis"].set_index("stage")
    tot_p = int(f[f.stage == "prereq"].k.sum())
    S.fig_title(fig, f"A mention is not a confirmation: of {tot_m:,} mentions of 7 core services, {tot_p:,} "
                     f"({tot_p / tot_m:.0%}) pass the record's own checks and {tot_o:,} ({tot_o / tot_m:.1%}) also have a "
                     "website or official-list confirmation", wrap=110)
    S.source_note(fig, f"Sources: {io.rel('pair_features')} (T text level, P prerequisites); kb/web_evidence/out "
                       "(site_identity, web_service_summary, web_services); data/external NABH, LaQshya, MoHFW trauma 196, "
                       "NMC matches\n(hand-checked precision 39/40, 17/20 + 3 plausible, 19/20, 19/20). Prerequisite = a cue such as ICU, OT, "
                       "blood bank or nephrology in a sentence not about the service.")
    rows = []
    for s in order:
        d = f[f.service == s].set_index("stage")
        rows.append(f"{SERVICES[s]}: {d.loc['mentioned'].k:,} mention it, {d.loc['fields2'].k:,} in 2+ fields, "
                    f"{d.loc['prereq'].k:,} also with a prerequisite, website confirms {d.loc['web'].k:,} of "
                    f"{d.loc['web'].n:,} with a site, official list {d.loc['listed'].k:,}.")
    alt = ("Small multiples of a confirmation funnel for 7 core services. " + " ".join(rows) +
           f" In total {tot_p:,} of {tot_m:,} facility-service mentions pass the record's own checks and {tot_o:,} of "
           f"{tot_m:,} also pass at least one outside check. Official lists cover few facilities, so a missing list "
           "match is not evidence against a claim.")
    S.save(fig, io.chart_path("s3_funnel"), alt)


def main():
    f, pf = build()
    io.save_csv(f, "s3_funnel")
    io.save_csv(pf[pf.mentioned | pf.web | pf.listed][["unique_id", "service", "T", "P", "mentioned", "fields2", "prereq",
                                                       "has_site", "web", "listed"]], "s3_pairs")
    chart(f)
    print(f.pivot(index="service", columns="stage", values="k").to_string())
    print(f[f.stage == "web"][["service", "k", "n", "rate"]].to_string(index=False))


if __name__ == "__main__":
    main()
