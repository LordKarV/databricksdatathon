"""Aggregates for Q1, Q2, Q4, Q5 and Q6 from out/sentences_flagged.parquet (run detect.py first).

Writes out/record_scores.parquet (one row per record: flags, provenance, quarantine share) and
prints every number quoted in FINDINGS.md.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python analyze.py
"""
import os, re, json
from collections import Counter
from urllib.parse import urlparse
import pandas as pd
from rapidfuzz import fuzz
import common, detect

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")

CHAIN = re.compile(r"\b(operates|centres|centers|branches|locations|network|group|chain|presence|across|"
                   r"cities|units|hospitals in)\b", re.I)
LOC_ASSERT = re.compile(r"\b(located|location|situated|based in|address|is a (\w+\s){0,3}(hospital|clinic|centre|center|"
                        r"nursing home)\b[^.]*\bin\b|listed (as|among|in|under)|is in\b|in the city of)", re.I)
INSURE = ("policyx", "zurichkotak", "policybazaar", "bajajfinservhealth", "healthinsuranceindia", "policy.online",
          "insurancedekho", "iffcotokio", "newindia.co.in", "cashlesshospitalindia", "starhealth", "nivabupa",
          "careinsurance", "carehealthinsurance", "icicilombard", "hdfcergo", "tataaig", "sbigeneral", "reliancegeneral",
          "godigit", "cholainsurance", "adityabirlacapital", "manipalcigna", "futuregenerali", "universalsompo",
          "royalsundaram", "libertyinsurance", "kotakgeneral", "acko", "bajajallianz", "uiic", "orientalinsurance",
          "medi-assist", "mediassist", "paramounttpa", "fhpl", "vidalhealth", "mdindia", "raksha")
EMPANEL_PATH = re.compile(r"empanel|network[-_]?hospital|cashless|cghs|echs|pmjay|pm-jay|ayushman|tpa|hospital[-_]?list|"
                          r"list[-_]?of[-_]?hospital", re.I)
RESEARCH = ("ncbi.nlm.nih.gov", "researchgate", "sciencedirect", "springer", "doi.org", "wiley", "nature.com", "bmj",
            "thelancet", "academia.edu", "semanticscholar", "frontiersin", "mdpi", "cureus", "plos", "tandfonline",
            "jamanetwork", "europepmc", "ijcrt", "ijsr", "journal", "medrxiv", "biorxiv", "elsevier", "sagepub",
            "lww.com", "scielo", "ijmr", "ejmanager", "ijcmph", "msjonline", "ijrcog", "ijpediatrics")
DIRECTORY = ("practo", "justdial", "medindia", "onefivenine", "hexahealth", "mappls", "docindia", "lybrate", "latlong",
             "healthfrog", "medicineindia", "sulekha", "chotu", "watchdoq", "drlogy", "grotal", "clinicspots", "skedoc",
             "bdir", "whatclinic", "diagnosticcentres", "myupchar", "sehat", "joonsquare", "mapcarta", "indiamart",
             "proptiger", "medicalkerala", "quickerala", "zoominfo", "tracxn", "zaubacorp", "rajasthanlink",
             "5bestincity", "weenear", "bharatibiz", "doctorsgallery", "credihealth", "myhospitalnow", "mediyaar",
             "kivihealth", "banodoctor", "eka.care", "apollo247", "1mg", "medsurgeindia")


def url_cats(urls):
    cats = set()
    for u in urls:
        try:
            p = urlparse(u)
        except ValueError:
            continue
        host, path = p.netloc.lower().removeprefix("www."), (p.path + "?" + p.query)
        full = host + path
        if host.endswith(".gov.in") or host.endswith(".nic.in") or host.endswith("gov.in"):
            cats.add("gov")
        if "railway" in full.lower() or "indianrailways" in host:
            cats.add("railway")
        if "wikipedia.org" in host:
            cats.add("wikipedia")
            if re.search(r"/List_of", path):
                cats.add("wikipedia_list")
        if any(k in host for k in INSURE) or EMPANEL_PATH.search(full):
            cats.add("empanelment_insurance")
        if any(k in host for k in RESEARCH) or path.lower().endswith(".pdf") or "scribd.com" in host:
            cats.add("research_or_document")
        if any(k in host for k in DIRECTORY):
            cats.add("directory")
    return cats


def near_name(foreign, rec_name):
    """Foreign mention whose distinctive part is a near-spelling of the record's own name (Vedanta/Medanta)."""
    rd = "".join(t for t in detect.toks(rec_name) if t not in detect.GENERIC)
    best = 0
    for m in foreign.split("; "):
        md = "".join(t for t in detect.toks(m) if t not in detect.GENERIC)
        if rd and md:
            best = max(best, fuzz.ratio(md, rd))
    return best


def main():
    df = common.load()
    s = pd.read_parquet(f"{OUT}/sentences_flagged.parquet")
    n, ns = len(df), len(s)
    name = df.set_index("unique_id").name
    pr = lambda k, v, d: print(f"{k}: {v}/{d} ({100 * v / d:.1f}%)")

    print("== Q1 foreign facility names")
    f = s[s.has_foreign]
    pr("sentences with foreign name", len(f), ns)
    pr("records with >=1 foreign-name sentence", f.unique_id.nunique(), n)
    for c, g in f.groupby("context"):
        pr(f"  context={c} sentences", len(g), len(f)); pr(f"  context={c} records", g.unique_id.nunique(), n)
    print("  by field (sentences):", f.field.value_counts().to_dict())
    sib = s[s.has_sibling]
    pr("sentences naming a same-brand other branch (sibling)", len(sib), ns)
    pr("records with sibling-branch sentence", sib.unique_id.nunique(), n)
    nn = f.assign(sim=[near_name(x, name[u]) for x, u in zip(f.foreign_names, f.unique_id)])
    nn = nn[nn.sim >= 75]
    pr("sentences whose foreign name is a near-spelling of own name (ratio>=75)", len(nn), ns)
    pr("records with near-spelling foreign name", nn.unique_id.nunique(), n)
    print("  examples:", [(u, name[u], x) for u, x in nn.drop_duplicates("unique_id")[["unique_id", "foreign_names"]].head(8).values])
    perf_by = s[s.text.str.contains(r"\b(?:performed|offered|done|provided) by Dr\b", regex=True)]
    heavy = perf_by.groupby("unique_id").size()
    pr("records with >=5 'performed/offered by Dr X' sentences (doctor-profile aggregation)", int((heavy >= 5).sum()), n)

    print("== Q2 places in claims")
    for col in ("has_other_state", "has_other_district"):
        g = s[s[col]]
        pr(f"sentences {col}", len(g), ns); pr(f"records {col}", g.unique_id.nunique(), n)
    anyp = s[s.has_other_state | s.has_other_district].copy()
    anyp["kind"] = ["credential" if detect.CREDENTIAL.search(t) else "chain" if CHAIN.search(t)
                    else "location_assertion" if LOC_ASSERT.search(t) else "other" for t in anyp.text]
    for k, g in anyp.groupby("kind"):
        pr(f"  other-place kind={k} sentences", len(g), len(anyp)); pr(f"  other-place kind={k} records", g.unique_id.nunique(), n)
    la = anyp[anyp.kind == "location_assertion"]
    pr("records asserting a location elsewhere (other state)", la[la.has_other_state].unique_id.nunique(), n)

    print("== Q5 quarantine policy")
    # quarantine: names a foreign facility in a direct context, or a sibling branch, or asserts a
    # location / listing elsewhere; keep credential/relation sentences but tag them
    q = (s.has_foreign & (s.context == "direct")) | s.has_sibling | \
        ((s.has_other_state | s.has_other_district) & s.text.map(lambda t: bool(LOC_ASSERT.search(t)) and not detect.CREDENTIAL.search(t)))
    s["quarantine"] = q
    tag = (s.has_foreign | s.has_other_state | s.has_other_district) & ~q
    s["tag_only"] = tag
    pr("claim sentences quarantined", int(q.sum()), ns)
    pr("claim sentences tagged (credential/relation/chain; kept)", int(tag.sum()), ns)
    for fld, g in s.groupby("field"):
        pr(f"  quarantined in {fld}", int(g.quarantine.sum()), len(g))
    rec = s.groupby("unique_id").agg(n_sent=("text", "size"), n_q=("quarantine", "sum"), n_tag=("tag_only", "sum"),
                                     n_foreign=("has_foreign", "sum"), n_os=("has_other_state", "sum"),
                                     n_od=("has_other_district", "sum"), n_sib=("has_sibling", "sum"))
    rec["q_share"] = rec.n_q / rec.n_sent
    pr("records with >=1 quarantined sentence", int((rec.n_q > 0).sum()), n)
    pr("records with >=25% of sentences quarantined", int((rec.q_share >= 0.25).sum()), n)
    s[["unique_id", "field", "idx", "quarantine", "tag_only"]].to_parquet(f"{OUT}/sentence_decisions.parquet")

    print("== Q4 provenance")
    df["cats"] = df.source_urls_l.map(url_cats)
    df = df.join(rec, on="unique_id")
    df["any_contam"] = df.n_q.fillna(0) > 0
    base = df.any_contam.mean()
    print(f"baseline: records with >=1 quarantined sentence {int(df.any_contam.sum())}/{n} ({100 * base:.1f}%)")
    rows = []
    for cat in ["gov", "railway", "wikipedia", "wikipedia_list", "empanelment_insurance", "research_or_document", "directory"]:
        m = df.cats.map(lambda c: cat in c)
        a, b = df[m], df[~m]
        rows.append((cat, len(a), int(a.any_contam.sum()), a.any_contam.mean(), b.any_contam.mean(),
                     a.q_share.mean(), b.q_share.mean(), (a.n_foreign > 0).mean(), (b.n_foreign > 0).mean()))
    t = pd.DataFrame(rows, columns=["category", "records", "contam_records", "contam_rate", "contam_rate_without",
                                    "mean_q_share", "mean_q_share_without", "foreign_rate", "foreign_rate_without"])
    print(t.round(3).to_string(index=False))
    nurl = df.source_urls_l.map(lambda l: len(set(l)))
    for lo, hi in [(0, 3), (3, 8), (8, 15), (15, 30), (30, 10 ** 6)]:
        m = (nurl >= lo) & (nurl < hi)
        print(f"  distinct urls [{lo},{hi}): records {int(m.sum())}, contam rate {df[m].any_contam.mean():.3f}, mean q_share {df[m].q_share.mean():.4f}")

    print("== Q6 cluster / source ids")
    sc = df.groupby("source_content_id").unique_id.transform("size")
    df["shared_content"] = sc > 1
    pr("records whose source_content_id is shared with another record", int(df.shared_content.sum()), n)
    print("  max records per source_content_id", int(sc.max()))
    for v in (False, True):
        g = df[df.shared_content == v]
        print(f"  shared_content={v}: records {len(g)}, contam rate {g.any_contam.mean():.3f}, foreign rate {(g.n_foreign > 0).mean():.3f}")
    sid = df.source_ids.map(lambda x: len(set(common.parse_list(x))))
    for lo, hi in [(0, 1), (1, 2), (2, 5), (5, 10), (10, 100)]:
        m = (sid >= lo) & (sid < hi)
        print(f"  distinct source_ids [{lo},{hi}): records {int(m.sum())}, contam rate {df[m].any_contam.mean():.3f}")
    df.drop(columns=[c for c in df.columns if c.endswith("_l")]).assign(cats=df.cats.map(sorted)).to_parquet(f"{OUT}/record_scores.parquet")


if __name__ == "__main__":
    main()
