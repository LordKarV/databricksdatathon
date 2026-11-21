"""Write lexicon.json, test it on cleaning/claims/out/claims.parquet, and measure per-service coverage.

Outputs (kb/taxonomy/): lexicon.json; out/lexicon_matches.parquet (claim_id, service, nonoffer cue flags) for the
sentences that match; out/coverage.csv and the 'coverage' block of services.json (rewritten in place, other fields kept);
out/lexicon_stats.json.
Coverage counts are over the 9,959 usable records: a facility 'mentions' a service when one of its claim sentences
matches (procedure, capability, equipment, description) or one of its specialties values maps to it in specialty_map.csv.
'2+ fields' counts distinct fields after dropping exact in-record echoes (claims.dup_in_record).

Run: /Users/karthikvattem/projects/datathon/.venv/bin/python build_lexicon.py
"""
from __future__ import annotations

import json
import os
import re

import duckdb
import pandas as pd

import attributes_src as AS
import lexicon_src as LS

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
CLAIMS = "/Users/karthikvattem/projects/datathon/cleaning/claims/out/claims.parquet"
RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
LOC = "/Users/karthikvattem/projects/datathon/cleaning/geo_identity/facility_location.parquet"
MIN_INCLUDE = 20      # facilities with any mention; below this a candidate is not added to the taxonomy
LOW_ANY, LOW_2F = 100, 100  # below either -> low_coverage (v1.1: on positive text only; review issue 16 lists services up to 99)
OFFER_KINDS_DROPPED = ("staff", "directory")  # v1.1 (review issue 27): staff and directory sentences are not offer evidence


def split_ids(x: str) -> list[str]:
    return [t for t in str(x).split(";") if t]


def taxonomy() -> dict:
    return json.load(open(os.path.join(D, "services.json")))


def lexicon_json(specs: dict, smap: pd.DataFrame, ids: list[str]) -> dict:
    cues = LS.shared_cues()
    svc = {}
    for sid in ids + [s for s in specs if s not in ids]:
        d = {k: v for k, v in specs[sid].items() if v}
        rows = smap[smap.service_id.map(lambda x: sid in split_ids(x))].sort_values("n_facilities", ascending=False)
        d["specialty_values"] = rows.specialty.tolist()
        pre = smap[smap.prereq_for.fillna("").str.split(";").map(lambda x: sid in x)]
        d["prerequisite_specialty_values"] = pre.sort_values("n_facilities", ascending=False).specialty.tolist()
        d["in_taxonomy"] = sid in ids
        if sid in AS.SERVICE_ATTRIBUTES:
            d["attribute_patterns"] = AS.SERVICE_ATTRIBUTES[sid]
        svc[sid] = d
    return {
        "about": "Per-service sentence patterns for the facility x service knowledge base. A sentence matches a service when "
                 "'include' hits, 'exclude' does not, and (where 'exclude_clause' is set) some clause that carries the include hit has no "
                 "'exclude_clause' hit; clauses are split on 'clause_split' (after 'strip_before_match' is removed, icu only). Shared non-offer cues "
                 "remove a match from positive evidence; weakening cues keep it but mark it qualified. 'quantity' extracts counts "
                 "or sizes (beds, machines, tesla, slices). Patterns of the 8 cleaning/claims services are copied from "
                 "cleaning/claims/lexicon.py unchanged; the others are new (lexicon_src.py comments give each exclusion's reason).",
        "regex_flavor": "Python re, case-insensitive, one sentence at a time; uses \\b and (?!...) lookahead (Java/Spark ok, RE2/DuckDB not).",
        "shared_cues": {"nonoffer": {k: cues[k] for k in LS.L.NONOFFER}, "weakening": {k: cues[k] for k in LS.L.WEAKENING}},
        "sentence_kinds": {"template": LS.L.TEMPLATE.pattern, "research": LS.L.RESEARCH.pattern, "directory": LS.L.DIRECTORY.pattern,
                           "staff": LS.L.STAFF.pattern},
        "attribute_scope": AS.__doc__.strip(),
        "facility_attributes": AS.FACILITY_ATTRIBUTES,
        "clause_split": LS.CLAUSE_SPLIT.pattern,
        "services": svc,
    }


def tag_claims(comp: dict) -> pd.DataFrame:
    c = pd.read_parquet(CLAIMS, columns=["claim_id", "unique_id", "field", "text", "attribution", "dup_in_record", "kind"])
    hits = [(i, s) for i, t in zip(c.index, c.text) for s in LS.match(t, comp)]
    m = pd.DataFrame(hits, columns=["row", "service"]).join(c, on="row").drop(columns="row")
    nonoffer = {k: re.compile(p, re.I) for k, p in LS.shared_cues().items() if k in LS.L.NONOFFER}
    m["nonoffer_cue"] = [next((k for k, r in nonoffer.items() if r.search(t)), "") for t in m.text]
    neg = {s: c2["negation_extra"] for s, c2 in comp.items() if c2["negation_extra"]}
    m["negation_extra"] = [bool(neg.get(s) and neg[s].search(t)) for s, t in zip(m.service, m.text)]
    qty = {s: c2["quantity"] for s, c2 in comp.items() if c2["quantity"]}
    m["quantity_text"] = [(lambda h: h.group(0) if h else "")(qty[s].search(t)) if s in qty else "" for s, t in zip(m.service, m.text)]
    return m


def coverage(m: pd.DataFrame, smap: pd.DataFrame, ids: list[str]) -> pd.DataFrame:
    usable = set(pd.read_parquet(LOC, columns=["unique_id"]).unique_id)
    sp = duckdb.sql(f"""select distinct unique_id, s as specialty from
        (select unique_id, unnest(from_json(specialties, '["VARCHAR"]')) s from read_parquet('{RAW}') where json_valid(specialties))""").df()
    sm = smap[["specialty", "service_id"]].assign(service_id=lambda d: d.service_id.map(split_ids)).explode("service_id")
    sp = sp[sp.unique_id.isin(usable)].merge(sm, on="specialty")
    sp = sp.rename(columns={"service_id": "service"}).assign(field="specialties")[["unique_id", "service", "field"]]
    tx = m[~m.dup_in_record][["unique_id", "service", "field"]]
    allm = pd.concat([tx, sp]).drop_duplicates()
    state = pd.read_parquet(LOC, columns=["unique_id", "state_final"])
    per = allm.groupby(["service", "unique_id"]).field.nunique().rename("n_fields").reset_index().merge(state, on="unique_id", how="left")
    pos = positive(m)
    pos_nodup = pos[~pos.dup_in_record]
    t2 = pos_nodup.groupby(["service", "unique_id"]).field.nunique()
    t2 = t2[t2 >= 2].reset_index().groupby("service").unique_id.nunique()
    rows = []
    for sid in sorted(set(m.service) | set(ids)):
        p = per[per.service == sid]
        rows.append(dict(
            service=sid, in_taxonomy=sid in ids,
            sentences=int((m.service == sid).sum()),
            facilities_any=int(p.unique_id.nunique()),
            facilities_2plus_fields=int((p.n_fields >= 2).sum()),
            states_any=int(p.state_final.dropna().nunique()),
            facilities_text=int(tx[tx.service == sid].unique_id.nunique()),
            facilities_specialty_only=int(len(set(sp[sp.service == sid].unique_id) - set(tx[tx.service == sid].unique_id))),
            facilities_text_positive=int(pos[pos.service == sid].unique_id.nunique()),
            facilities_text_2plus_fields=int(t2.get(sid, 0)),
            sentences_nonoffer_cue=int(((m.service == sid) & ((m.nonoffer_cue != "") | m.negation_extra)).sum()),
            sentences_other_facility=int(((m.service == sid) & (m.attribution == "other_facility")).sum()),
            sentences_with_quantity=int(((m.service == sid) & (m.quantity_text != "")).sum()),
        ))
    cov = pd.DataFrame(rows).sort_values("facilities_any", ascending=False)
    cov["low_coverage"] = (cov.facilities_text_positive < LOW_ANY) | (cov.facilities_text_2plus_fields < LOW_2F)
    return cov


def positive(m: pd.DataFrame) -> pd.DataFrame:
    """Offer evidence: no non-offer cue, not attributed to another facility, not a staff or directory sentence."""
    return m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility") & ~m.kind.isin(OFFER_KINDS_DROPPED)]


def attribute_counts(m: pd.DataFrame) -> pd.DataFrame:
    """How often each attribute pattern fires: service attributes inside positive matched sentences of that service,
    facility attributes over all own-facility claim sentences of usable records. from_service attributes count
    facilities that have positive evidence for both services."""
    c = pd.read_parquet(CLAIMS, columns=["claim_id", "unique_id", "text", "attribution"])
    usable = set(pd.read_parquet(LOC, columns=["unique_id"]).unique_id)
    pos = positive(m)  # m already carries the sentence text
    fac_by_svc = pos.groupby("service").unique_id.apply(set)
    rows = []
    for sid, attrs in AS.SERVICE_ATTRIBUTES.items():
        t = pos[pos.service == sid]
        for name, d in attrs.items():
            if "from_service" in d:
                both = fac_by_svc.get(sid, set()) & fac_by_svc.get(d["from_service"], set())
                rows.append(dict(scope="service", service=sid, attribute=name, value="", sentences=0, facilities=len(both)))
                continue
            for val, rx in AS.compiled({name: d})[name]:
                hit = t.text.str.contains(rx)
                rows.append(dict(scope="service", service=sid, attribute=name, value=val, sentences=int(hit.sum()),
                                 facilities=int(t[hit].unique_id.nunique())))
    own = c[c.unique_id.isin(usable) & (c.attribution != "other_facility")]
    for name, pats in AS.compiled(AS.FACILITY_ATTRIBUTES).items():
        for val, rx in pats:
            hit = own.text.str.contains(rx)
            rows.append(dict(scope="facility", service="", attribute=name, value=val, sentences=int(hit.sum()),
                             facilities=int(own[hit].unique_id.nunique())))
    return pd.DataFrame(rows)


def write_coverage(tax: dict, cov: pd.DataFrame) -> None:
    c = cov.set_index("service")
    for s in [s for cat in tax["categories"] for s in cat["services"]] + tax.get("candidates_not_included", []):
        r = c.loc[s["id"]]
        s["coverage"] = {k: (bool(r[k]) if k == "low_coverage" else int(r[k])) for k in
                         ["facilities_any", "facilities_2plus_fields", "states_any", "facilities_text", "facilities_specialty_only",
                          "facilities_text_positive", "facilities_text_2plus_fields", "sentences", "low_coverage"]}
        if s["id"] in AS.SERVICE_ATTRIBUTES:
            s["attributes"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("pattern", "values")} | (
                {"values": list(v["values"])} if "values" in v else {}) for k, v in AS.SERVICE_ATTRIBUTES[s["id"]].items()}
    tax["facility_attributes"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("pattern", "values")} | (
        {"values": list(v["values"])} if "values" in v else {}) for k, v in AS.FACILITY_ATTRIBUTES.items()}
    tax["coverage_definition"] = (f"facilities_any: usable records (of 9,959) with a matching claim sentence or a specialties value mapped to the "
                                  f"service; facilities_2plus_fields: distinct fields among procedure, capability, equipment, description, specialties "
                                  f"after dropping in-record echoes; states_any: distinct state_final; facilities_text_positive: text matches without "
                                  f"a non-offer cue, not attributed to another facility and not a staff or directory sentence; "
                                  f"facilities_text_2plus_fields: the same, in 2+ distinct text fields after dropping echoes; low_coverage: "
                                  f"facilities_text_positive < {LOW_ANY} or facilities_text_2plus_fields < {LOW_2F}. Mentions are claims, not verified offers.")
    json.dump(tax, open(os.path.join(D, "services.json"), "w"), indent=2, ensure_ascii=False)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    tax = taxonomy()
    ids = [s["id"] for c in tax["categories"] for s in c["services"]]
    specs = LS.all_specs()
    assert set(ids) <= set(specs), set(ids) - set(specs)
    smap = pd.read_csv(os.path.join(D, "specialty_map.csv"), keep_default_na=False)
    json.dump(lexicon_json(specs, smap, ids), open(os.path.join(D, "lexicon.json"), "w"), indent=1, ensure_ascii=False)
    comp = LS.compile_specs(json.load(open(os.path.join(D, "lexicon.json")))["services"])  # test what was written
    m = tag_claims(comp)
    m[["claim_id", "unique_id", "field", "service", "attribution", "kind", "dup_in_record", "nonoffer_cue", "negation_extra", "quantity_text"]].to_parquet(
        os.path.join(OUT, "lexicon_matches.parquet"), index=False)
    cov = coverage(m, smap, ids)
    prior_only = {s["id"] for c in tax["categories"] for s in c["services"] if s.get("answer_mode") == "prior"}
    thin = cov[cov.in_taxonomy & (cov.facilities_any < MIN_INCLUDE) & ~cov.service.isin(prior_only)].service.tolist()
    assert not thin, f"taxonomy services below the inclusion rule: {thin}"
    cov.to_csv(os.path.join(OUT, "coverage.csv"), index=False)
    attribute_counts(m).to_csv(os.path.join(OUT, "attribute_counts.csv"), index=False)
    write_coverage(tax, cov)
    old = pd.read_parquet(CLAIMS, columns=["claim_id", "services"])
    old = old[old.services != ""].assign(service=lambda d: d.services.str.split("|")).explode("service")
    old["service"] = old.service.map(LS.CORE_IDS)
    new = m[m.service.isin(LS.CORE_IDS.values())][["claim_id", "service"]]
    j = old[["claim_id", "service"]].merge(new, how="outer", indicator=True)
    diff = j.groupby(["service", "_merge"], observed=True).size().unstack(fill_value=0)
    diff.to_csv(os.path.join(OUT, "diff_vs_claims_tags.csv"))
    st = {"core_tag_diff_vs_claims_parquet": {s: {"only_claims_parquet": int(r.get("left_only", 0)), "only_kb": int(r.get("right_only", 0)),
                                                  "both": int(r.get("both", 0))} for s, r in diff.iterrows()},
          "claims": int(pd.read_parquet(CLAIMS, columns=["claim_id"]).shape[0]), "matched_sentence_service_pairs": len(m),
          "sentences_with_any_match": int(m.claim_id.nunique()), "services_in_taxonomy": len(ids),
          "candidates_not_included": cov[~cov.in_taxonomy].service.tolist()}
    json.dump(st, open(os.path.join(OUT, "lexicon_stats.json"), "w"), indent=1)
    print(json.dumps(st, indent=1))
    print(cov.to_string(index=False))


if __name__ == "__main__":
    main()
