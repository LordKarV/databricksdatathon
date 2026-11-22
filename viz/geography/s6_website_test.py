"""Story 6: "confirmed" mostly means "has a website", and public and rural facilities rarely have one.

Confirmation rate: among records whose dataset text claims a service (common.evidence_flags), the
share a second check confirms, split by whether the crawl found the facility's own website
(kb/web_evidence/out/site_identity.parquet: attributable, kind site or branch). Website coverage:
share of the 9,959 records with such a site, by operator type (data/raw operatorTypeId) and by
settlement class (common.degree_of_urbanisation). Rates carry 95% Wilson intervals.
Outputs: charts/s6_website_test.*, data/s6_confirmation.csv, data/s6_coverage.csv, data/s6_numbers.json.
"""
import json
import re

import numpy as np
import pandas as pd

import common as C
from common import S

SERVICES = [("trauma", "Trauma / 24x7 emergency"), ("dialysis", "Dialysis"), ("csection", "Emergency C-section")]


def main():
    si = pd.read_parquet(C.ROOT / "kb/web_evidence/out/site_identity.parquet",
                         columns=["unique_id", "kind", "attributable"])
    own = set(si[si.attributable & si.kind.isin(["site", "branch"])].unique_id)
    d = C.facilities()
    d["has_site"] = d.unique_id.isin(own)
    rows = []
    for svc, lab in SERVICES:
        c = d[d[f"{svc}_claimed"]]
        for site in (True, False):
            g = c[c.has_site == site]
            k, n = int(g[f"{svc}_corroborated"].sum()), len(g)
            p, lo, hi = S.wilson(k, n)
            rows.append(dict(service=svc, label=lab, has_site=site, confirmed=k, claimed=n, rate=p, lo=lo, hi=hi))
    conf = pd.DataFrame(rows)
    C.save_csv(conf, "s6_confirmation")
    cov = []
    groups = [("Private", d.operatorTypeId == "private"), ("Public", d.operatorTypeId.isin(["public", "government"])),
              ("Operator not stated", ~d.operatorTypeId.isin(["private", "public", "government"])),
              ("Urban centre", d.degurba == 3), ("Town or semi-dense", d.degurba == 2), ("Rural", d.degurba == 1)]
    for lab, m in groups:
        k, n = int(d.has_site[m].sum()), int(m.sum())
        p, lo, hi = S.wilson(k, n)
        cov.append(dict(group=lab, with_site=k, records=n, rate=p, lo=lo, hi=hi))
    cov = pd.DataFrame(cov)
    C.save_csv(cov, "s6_coverage")
    anyc = d[[f"{s}_claimed" for s, _ in SERVICES]].any(axis=1)
    anyk = d[[f"{s}_corroborated" for s, _ in SERVICES]].any(axis=1)
    k1, n1 = int((anyk & anyc & d.has_site).sum()), int((anyc & d.has_site).sum())
    k0, n0 = int((anyk & anyc & ~d.has_site).sum()), int((anyc & ~d.has_site).sum())
    nums = dict(with_site=int(d.has_site.sum()), records=len(d),
                any_claim_site=[k1, n1, *S.wilson(k1, n1)], any_claim_nosite=[k0, n0, *S.wilson(k0, n0)],
                confirmation=conf.to_dict("records"), coverage=cov.to_dict("records"),
                web_quote_precision="21 of 22 quotes that confirm a dataset claim were right (Wilson 0.78-0.99), "
                                    "kb/web_evidence/WEB_EVIDENCE.md self-check")
    nums["web_conf_site_in_vf_sources"] = site_in_sources(d)
    C.save_numbers("s6", nums)
    chart(conf, cov, nums)
    print(json.dumps(nums, indent=1, default=float)[:2500])


def site_in_sources(d):
    """Of (record, service) web confirmations, how many come from a site the record's own source_urls list.

    Added in verification: such a confirmation re-checks a page the dataset was built from, so it shows
    the claim is really on the facility's site, not that a second, independent witness agrees."""
    raw = pd.read_parquet(C.P["raw"], columns=["unique_id", "source_urls"]).drop_duplicates("unique_id")
    host = lambda u: re.sub(r"^(www|m)\.", "", re.sub(r"^https?://", "", u.strip().lower()).split("/")[0])
    hosts = {}
    for u, src in zip(raw.unique_id, raw.source_urls):
        try:
            hosts[u] = {host(x) for x in json.loads(src) if isinstance(x, str)}
        except (TypeError, ValueError):
            hosts[u] = set()
    si = pd.read_parquet(C.ROOT / "kb/web_evidence/out/site_identity.parquet", columns=["unique_id", "site", "kind", "attributable"])
    si = si[si.attributable & si.kind.isin(["site", "branch"])]
    same = {u for u, s in zip(si.unique_id, si.site) if isinstance(s, str) and host(s) in hosts.get(u, set())}
    k = n = 0
    for svc, _ in SERVICES:
        g = d[d[f"{svc}_corroborated"] & d[f"{svc}_web"]]
        k, n = k + int(g.unique_id.isin(same).sum()), n + len(g)
    return [k, n]


def chart(conf, cov, nums):
    fig, (a, b) = S.new_figure((12, 6.4), ncols=2, gridspec_kw=dict(width_ratios=[1.1, 1]))
    y = np.arange(len(SERVICES))
    for site, off, col, lab in ((True, -0.17, S.CATEGORICAL[0], "Own website found by the crawl"),
                                (False, 0.17, S.CATEGORICAL[1], "No own website")):
        c = conf[conf.has_site == site].set_index("service").loc[[s for s, _ in SERVICES]]
        bars = a.barh(y + off, c.rate * 100, height=0.32, color=col, label=lab, **S.bar_style())
        S.add_interval(a, y + off, c.lo * 100, c.hi * 100, horizontal=True, cap=2, lw=1)
        C.label_after(a, y + off, c.hi * 100, [f"{r.confirmed:,} of {r.claimed:,}" for r in c.itertuples()])
    a.set_yticks(y, [l for _, l in SERVICES])
    a.invert_yaxis()
    a.set_xlim(0, 112)
    a.set_xlabel("Dataset claims confirmed by a second check (%, 95% Wilson)")
    a.grid(axis="y", visible=False)
    a.legend(loc="lower right", fontsize=10.5)
    S.panel_title(a, "Confirmation rate of dataset claims\n(dialysis has no non-website source, so 0% is by construction)")
    yb = np.arange(len(cov))
    bars = b.barh(yb, cov.rate * 100, color=[S.CATEGORICAL[0]] * len(cov), height=0.6, **S.bar_style())
    S.add_interval(b, yb, cov.lo * 100, cov.hi * 100, horizontal=True, cap=2, lw=1)
    C.label_after(b, yb, cov.hi * 100, [f"{r.rate * 100:.0f}%  ({r.with_site:,} of {r.records:,})" for r in cov.itertuples()])
    b.set_yticks(yb, cov.group)
    b.invert_yaxis()
    b.axhline(2.5, color=S.GRID, lw=1)
    b.set_xlim(0, 100)
    b.set_xlabel("Records with their own website (%, 95% Wilson)")
    b.grid(axis="y", visible=False)
    S.panel_title(b, "Who has a website to check")
    s1, s0 = nums["any_claim_site"], nums["any_claim_nosite"]
    pub = cov.set_index("group").loc["Public"]
    priv = cov.set_index("group").loc["Private"]
    S.fig_title(fig, f"'Confirmed' mostly means 'has a website': {s1[2] * 100:.0f}% of claims confirmed with one, "
                     f"{s0[2] * 100:.1f}% without, and only {pub.rate * 100:.0f}% of public records have one the crawl "
                     f"could check (private {priv.rate * 100:.0f}%)", wrap=92)
    C.note(fig, "Claims: dataset sentences naming the service (kb/taxonomy lexicon, non-offer, negated, other-facility, "
                "staff and directory lines removed). Second checks: the facility's own website (quote-verified, "
                "kb/web_evidence; quotes confirming a claim were right 21 of 22 times), OSM emergency=yes, the MoHFW "
                "trauma care list, NHSRC LaQshya. Website = an attributable own site or branch page in the crawl. A "
                "facility without a website cannot be confirmed here, so an unconfirmed claim is missing evidence, "
                f"not evidence against. {nums['web_conf_site_in_vf_sources'][0]:,} of "
                f"{nums['web_conf_site_in_vf_sources'][1]:,} website confirmations come from a site already in the "
                "record's own source list: a re-check of the source, not an independent witness. The crawl skipped "
                "government portals by design, which lowers public coverage.")
    S.save(fig, C.CHARTS / "s6_website_test",
           alt_text="Left: confirmation rates of dataset service claims with and without an own website. "
                    + "; ".join(f"{r.label}, {'with' if r.has_site else 'without'} site: {r.confirmed} of {r.claimed} "
                                f"({r.rate * 100:.0f}%)" for r in conf.itertuples())
                    + ". Right: share of records with an own website: "
                    + "; ".join(f"{r.group} {r.rate * 100:.0f}% ({r.with_site} of {r.records})" for r in cov.itertuples())
                    + ".")


if __name__ == "__main__":
    main()
