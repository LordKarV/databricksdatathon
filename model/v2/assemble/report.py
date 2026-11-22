"""Coverage and sanity report for derived/v2. Writes out/coverage_by_service.csv, out/spotcheck.csv and
out/report.json, and prints the markdown tables used in ASSEMBLE.md.

- coverage: per service and family, facilities with a present / absent / not_observable witness;
- full quote test: every present dataset-text witness (T, C, N, P from text) string-matches its raw item at
  (unique_id, field, raw_pos) in data/raw/facilities.parquet;
- spot check: 15 witnesses drawn with a fixed seed across families and sources, each re-read from its own
  source file (the raw record, the stored web page, the list file, the gazetteer of services).

Run after build.py: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python report.py
"""
from __future__ import annotations

import gzip
import json

import duckdb
import numpy as np
import pandas as pd

import acommon as A
import evidence as EV

OUTD = A.HERE / "out"
SEED = 20261121
SPOT = [("T", "vf_text_unit", 2), ("T", "vf_specialty", 1), ("C", "vf_rejected", 1), ("N", "vf_nonoffer", 1),
        ("S", "scope", 1), ("P", "prereq", 1), ("X", "nabh_code", 1), ("X", "laqshya", 1), ("X", "eraktkosh", 1),
        ("W", "web_service_A", 1), ("W", "web_service_E", 1), ("O", "osm_match", 1), ("D", "vf_", 1), ("K", "iphs", 1)]


def raw_lookup() -> tuple[pd.DataFrame, dict]:
    items = duckdb.sql(EV.RAWPOS_SQL).df()[["unique_id", "field", "raw_pos", "raw_item"]]
    specs = {u: v for u, v in __import__("atoms").raw_specialties().items()}
    return items, specs


def check_quote(r: pd.Series, items: pd.DataFrame, specs: dict, cache: dict) -> tuple[bool, str]:
    """Re-read the witness's own source and test that the quote is in it. Returns (match, what was read)."""
    fam, q = r.family, str(r.quote)
    if fam in ("T", "C", "N", "P") and r.field == "specialties":
        it = specs.get(r.unique_id, [])
        src = it[int(r.raw_pos)] if r.raw_pos is not pd.NA and int(r.raw_pos) < len(it) else ""
        return q == src, f"raw specialties[{r.raw_pos}] = {src!r}"
    if fam in ("T", "C", "N", "P"):
        m = items[(items.unique_id == r.unique_id) & (items.field == r.field) & (items.raw_pos == r.raw_pos)]
        src = m.raw_item.iloc[0] if len(m) else ""
        return q in src, f"raw {r.field}[{r.raw_pos}] = {src[:120]!r}"
    if fam == "S":
        nm = cache.setdefault("names", pd.read_parquet(A.ROOT / "audit/merge/out/record_scores.parquet", columns=["unique_id", "name"]).set_index("unique_id").name)
        return q == nm[r.unique_id], f"record name = {nm[r.unique_id]!r}"
    if fam == "W":
        page = json.loads(gzip.open(A.ROOT / str(r.evidence_id)).read())
        fld = str(r.field) if str(r.field) in page else "text"
        return q in (page.get(fld) or ""), f"page {r.evidence_id} field {fld}"
    if fam == "X":
        if str(r.source_key) == "nabh":
            sp = pd.read_parquet(A.EXT / "nabh_accredited/nabh_hco_specialty.parquet")
            ok = ((sp.acc_no == r.evidence_id) & (sp.spec_code == q)).any()
            return bool(ok), f"nabh_hco_specialty rows for {r.evidence_id} include code {q}: {ok}"
        if str(r.source_key) == "laqshya":
            lf = pd.read_parquet(A.EXT / "laqshya_master/laqshya_facilities.parquet").set_index("lq_id")
            src = lf.name[int(str(r.evidence_id).split(":")[1])]
            return q == src, f"laqshya_facilities name = {src!r}"
        if str(r.source_key) == "eraktkosh":
            ec = pd.read_parquet(A.EXT / "eraktkosh_blood_centres/erk_centres.parquet")
            code = float(str(r.evidence_id).split(":")[1])
            src = ec[ec.hospital_code == code].name.tolist()
            return q in src, f"erk_centres name for {code:.0f} = {src}"
    if fam == "O":
        m = pd.read_parquet(A.ROOT / "kb/opendata/vf_opendata_match.parquet", columns=["unique_id", "source", "source_id", "cand_name"])
        s, sid = str(r.evidence_id).split(":", 1)
        src = m[(m.unique_id == r.unique_id) & (m.source == s) & (m.source_id == sid)].cand_name.tolist()
        return q in src, f"vf_opendata_match cand_name = {src}"
    if fam == "D":
        c = cache.setdefault("claims", pd.read_parquet(A.ROOT / "derived/v1/claims.parquet", columns=["claim_id", "text"]).set_index("claim_id").text)
        src = c.get(str(r.evidence_id), "")
        return q in src, f"claim {r.evidence_id} = {src[:120]!r}"
    if fam == "K":
        return q == A.IPHS_TEXT[r.service], "services.json iphs.expected_from"
    return False, "no reader for this source"


def main() -> None:
    OUTD.mkdir(exist_ok=True)
    W = pd.read_parquet(A.OUT / "witnesses.parquet")
    F = pd.read_parquet(A.OUT / "facility_features.parquet")
    # coverage per service x family (facilities; one row per pair in facility_features)
    rows = []
    for fam in A.FAMILIES:
        ct = F.groupby("service")[f"obs_{fam}"].value_counts().unstack(fill_value=0)
        for s, r in ct.iterrows():
            rows.append(dict(service=s, family=fam, present=int(r.get("present", 0)), absent=int(r.get("absent", 0)),
                             not_observable=int(r.get("not_observable", 0))))
    cov = pd.DataFrame(rows)
    assert (cov[["present", "absent", "not_observable"]].sum(axis=1) == 9959).all()
    cov.to_csv(OUTD / "coverage_by_service.csv", index=False)

    items, specs = raw_lookup()
    # full quote test on dataset-text witnesses
    t = W[(W.observability == "present") & W.family.isin(["T", "C", "N", "P"]) & (W.field != "specialties") & W.quote.notna()]
    j = t.merge(items, on=["unique_id", "field", "raw_pos"], how="left")
    ok = [isinstance(r, str) and q in r for q, r in zip(j.quote, j.raw_item)]
    full = dict(n=len(j), matched=int(sum(ok)))
    s = W[(W.observability == "present") & W.family.isin(["T", "C", "N", "P"]) & (W.field == "specialties")]
    oks = [int(p) < len(specs.get(u, [])) and specs[u][int(p)] == q for u, p, q in zip(s.unique_id, s.raw_pos, s.quote)]
    full_spec = dict(n=len(s), matched=int(sum(oks)))
    # raw_pos differs from claims idx (v2 change 1)
    a = pd.read_parquet(A.OUT / "claim_atoms.parquet", columns=["field", "idx", "raw_pos"])
    lists = a[a.field.isin(["procedure", "capability", "equipment"])]
    shift = dict(list_atoms=len(lists), raw_pos_ne_idx=int((lists.idx != lists.raw_pos).sum()))

    # spot check of 15
    rng = np.random.default_rng(SEED)
    P = W[(W.observability == "present") & W.quote.notna()]
    picks = []
    for fam, prefix, n in SPOT:
        pool = P[(P.family == fam) & P.witness.str.startswith(prefix)]
        if fam == "P":
            pool = pool[pool.value_text == "text"]
        picks.append(pool.iloc[rng.choice(len(pool), n, replace=False)])
    sp = pd.concat(picks)
    cache: dict = {}
    res = [check_quote(r, items, specs, cache) for _, r in sp.iterrows()]
    sp = sp.assign(quote_matches=[x for x, _ in res], source_read=[y for _, y in res])
    sp[["witness_id", "unique_id", "service", "family", "witness", "source_key", "evidence_id", "raw_pos", "quote",
        "quote_matches", "source_read", "precision_k", "precision_n"]].to_csv(OUTD / "spotcheck.csv", index=False)

    rep = dict(full_quote_test_text=full, full_quote_test_specialties=full_spec, raw_pos_shift=shift,
               spotcheck_matched=int(sp.quote_matches.sum()), spotcheck_n=len(sp),
               spotcheck_wilson=A.wilson(int(sp.quote_matches.sum()), len(sp)),
               witness_rows=len(W), present_rows=int((W.observability == "present").sum()),
               present_by_family=W[W.observability == "present"].family.value_counts().to_dict(),
               facility_level_rows=int((W.service == "*").sum()),
               sizes_mb={p.name: round(p.stat().st_size / 2**20, 1) for p in A.OUT.glob("*.parquet")})
    (OUTD / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str))
    # markdown: present / absent / not_observable per service, families as columns
    piv = cov.assign(cell=cov.present.astype(str) + " / " + cov.absent.astype(str) + " / " + cov.not_observable.astype(str))
    piv = piv.pivot(index="service", columns="family", values="cell")[list(A.FAMILIES)].reindex(A.SERVICES)
    print("| service | " + " | ".join(A.FAMILIES) + " |")
    print("|---" * (len(A.FAMILIES) + 1) + "|")
    for s, r in piv.iterrows():
        print(f"| {s} | " + " | ".join(r.values) + " |")
    print()
    for _, r in sp.iterrows():
        print(f"| {r.witness_id} | {r.family} | {r.witness} | {r.service} | {str(r.quote)[:70]!r} | {r.quote_matches} |")


if __name__ == "__main__":
    main()
