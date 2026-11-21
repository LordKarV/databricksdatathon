"""Claim-level cleaning: one row per claim with field, attribution, service tags, cues, kind and quantity.

Step 1 (explode) is DuckDB SQL written to port to Spark SQL; Spark equivalents are noted inline.
Steps 2-4 are pandas + Python `re` (on Databricks: run on the driver, 470k rows, or applyInPandas).
Attribution reuses the merge audit's sentence detector output (audit/merge/out/sentences_flagged.parquet,
sentence_decisions.parquet), joined on (unique_id, field, idx) after checking the texts are identical.

Writes out/claims.parquet (text fields), out/specialties.parquet, out/service_lexicon.csv, out/build_stats.json.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python build_claims.py
"""
import json, os, re, sys
import duckdb, pandas as pd
import lexicon as L

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
MERGE = "/Users/karthikvattem/projects/datathon/audit/merge/out"
sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/merge")
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# Spark: from_json(col,'array<string>') + posexplode; QUALIFY -> row_number() in a subquery;
# regexp_replace(..., '([.!?])\\s+', '$1\u001f') + split(..., '\u001f'); json_valid -> from_json returns NULL.
EXPLODE_SQL = f"""
with b as (
  select * from read_parquet('{RAW}')
  where regexp_matches(unique_id, '{UUID}') and source = 'kie'
  qualify row_number() over (partition by unique_id order by unique_id) = 1          -- 11 byte-identical duplicate rows
),
arr as (
  select unique_id, 'procedure' field, procedure j from b union all
  select unique_id, 'equipment', equipment from b union all
  select unique_id, 'capability', capability from b
),
lists as (
  select unique_id, field, from_json(j, '["VARCHAR"]') l from arr
  where json_valid(j) and json_type(j) = 'ARRAY'
),
items as (
  select unique_id, field, unnest(l) item, generate_subscripts(l, 1) pos from lists
),
desc_s as (
  select unique_id, 'description' field,
         string_split(regexp_replace(description, '([.!?])\\s+', '\\1' || chr(31), 'g'), chr(31)) l
  from b where description is not null and description <> 'null'
),
ditems as (select unique_id, field, unnest(l) item, generate_subscripts(l, 1) pos from desc_s),
allitems as (select * from items union all select * from ditems)
select unique_id, field,
       row_number() over (partition by unique_id, field order by pos) - 1 idx,
       regexp_replace(item, '^\\s+|\\s+$', '', 'g') text          -- trim() strips spaces only, items end in \r\n
from allitems where item is not null and regexp_replace(item, '^\\s+|\\s+$', '', 'g') <> ''
"""
SPEC_SQL = f"""
with b as (select unique_id, specialties from read_parquet('{RAW}')
           where regexp_matches(unique_id, '{UUID}') and source = 'kie' and json_valid(specialties))
select unique_id, regexp_replace(lower(s), '[^a-z]', '', 'g') spec, count(*) n_raw
from (select unique_id, unnest(from_json(specialties, '["VARCHAR"]')) s from b)
where s is not null and trim(s) <> ''
group by 1, 2
"""
FIELD_ORDER = {"procedure": 0, "capability": 1, "equipment": 2, "description": 3}


def attribution(m):
    """own_anchored | unanchored | ambiguous | other_facility, from the merge detector columns.
    other_facility = the merge quarantine rule (direct foreign name, same-brand other branch, or a
    non-credential location assertion elsewhere). ambiguous = names another facility or place in a
    credential / relation / chain context (merge tag_only)."""
    return pd.Series(
        pd.Categorical.from_codes(
            (m.quarantine * 3 + (~m.quarantine & m.tag_only) * 2 + (~m.quarantine & ~m.tag_only & (m.self_names != "")) * 1).astype(int),
            ["unanchored", "own_anchored", "ambiguous", "other_facility"]), index=m.index).astype(str)


def tag(texts):
    """Per sentence: list of services whose core synonym matches (exclusions applied)."""
    out = []
    for s in texts:
        hits = []
        for svc, d in L.SERVICES.items():
            t = L.ICU_STRIP.sub(" ", s) if svc == "icu" else s
            if d["core"].search(t) and not d["exclude"].search(t):
                hits.append(svc)
        out.append(hits)
    return out


def prereq_hits(texts):
    """Per sentence: set of 'service.prereq' names whose text regex matches."""
    keys = [(svc, k, p) for svc, d in L.SERVICES.items() for k, (p, _) in d["prereqs"].items()]
    return ["|".join(f"{svc}.{k}" for svc, k, p in keys if p.search(s)) for s in texts]


def kind(s, cues):
    if L.TEMPLATE.search(s):
        return "template"
    if L.RESEARCH.search(s):
        return "research"
    if L.DIRECTORY.search(s):
        return "directory"
    if L.STAFF.search(s):
        return "staff"
    if L.is_list(s):
        return "list"
    if any(cues.get(k) for k in L.WEAKENING):
        return "qualified"
    return "specific"


def main():
    os.makedirs(OUT, exist_ok=True)
    c = duckdb.sql(EXPLODE_SQL).df()
    sf = pd.read_parquet(f"{MERGE}/sentences_flagged.parquet")
    sd = pd.read_parquet(f"{MERGE}/sentence_decisions.parquet")
    st = {"claims_exploded": len(c), "merge_sentence_rows": len(sf)}
    m = c.merge(sf, on=["unique_id", "field", "idx"], how="outer", suffixes=("", "_merge"), indicator=True)
    st["join_status"] = m._merge.value_counts().to_dict()
    both = m._merge == "both"
    st["text_mismatch_on_join"] = int((both & (m.text != m.text_merge)).sum())
    m = m[both].drop(columns=["_merge", "text_merge"]).merge(sd, on=["unique_id", "field", "idx"], how="left")
    m["attribution"] = attribution(m)

    m["norm"] = m.text.str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()
    m["forder"] = m.field.map(FIELD_ORDER)
    m = m.sort_values(["unique_id", "forder", "idx"]).reset_index(drop=True)
    m["dup_in_record"] = m.duplicated(["unique_id", "norm"])  # Spark: row_number() over (partition by uid, norm order by forder, idx) > 1

    m["services"] = tag(m.text)
    m["prereqs"] = prereq_hits(m.text)
    svc_rows = m.services.map(len) > 0
    cue_cols = list(L.CUES)
    for k in cue_cols:
        m["cue_" + k] = False
        m.loc[svc_rows, "cue_" + k] = m.loc[svc_rows, "text"].map(lambda s, r=L.CUES[k]: bool(r.search(s)))
    m["nonoffer"] = m[["cue_" + k for k in L.NONOFFER]].any(axis=1)
    m["kind"] = [kind(s, {k: r["cue_" + k] for k in L.WEAKENING}) for s, (_, r) in zip(m.text, m[["cue_" + k for k in L.WEAKENING]].iterrows())]
    q = m.text.map(L.quantity)
    m["qty_value"] = q.map(lambda x: x[0])
    m["qty_unit"] = q.map(lambda x: x[1])
    m["claim_id"] = m.unique_id.str[:8] + ":" + m.field.str[:4] + ":" + m.idx.astype(str)
    keep = ["claim_id", "unique_id", "field", "idx", "text", "attribution", "foreign_names", "sibling_names", "self_names",
            "places_other_state", "places_other_district", "context", "dup_in_record", "services", "prereqs", "kind",
            "nonoffer", *["cue_" + k for k in cue_cols], "qty_value", "qty_unit"]
    m = m[keep]
    m.assign(services=m.services.map("|".join)).to_parquet(f"{OUT}/claims.parquet", index=False)

    sp = duckdb.sql(SPEC_SQL).df()
    sp.to_parquet(f"{OUT}/specialties.parquet", index=False)
    lex = [(svc, part, d[part].pattern) for svc, d in L.SERVICES.items() for part in ("core", "exclude", "related")]
    lex += [(svc, "prereq:" + k, p.pattern + (" | tags: " + ",".join(sorted(tags)) if tags else ""))
            for svc, d in L.SERVICES.items() for k, (p, tags) in d["prereqs"].items()]
    lex += [("all", "spec_core_tags:" + svc, ",".join(sorted(d["spec_core"]))) for svc, d in L.SERVICES.items()]
    lex += [("all", "cue:" + k, r.pattern) for k, r in L.CUES.items()]
    pd.DataFrame(lex, columns=["service", "part", "pattern"]).to_csv(f"{OUT}/service_lexicon.csv", index=False)

    st.update(
        records=int(m.unique_id.nunique()), claims=len(m),
        claims_by_field=m.field.value_counts().to_dict(),
        exact_duplicate_claims_in_record=int(m.dup_in_record.sum()),
        attribution=m.attribution.value_counts().to_dict(),
        claims_with_service=int((m.services.map(len) > 0).sum()),
        service_claims_by_attribution=m[m.services.map(len) > 0].attribution.value_counts().to_dict(),
        service_claims_nonoffer=int(m.nonoffer.sum()),
        kind_all=m.kind.value_counts().to_dict(),
        kind_service_claims=m[m.services.map(len) > 0].kind.value_counts().to_dict(),
        claims_with_quantity=int(m.qty_unit.notna().sum()),
        quantity_units=m.qty_unit.value_counts().to_dict(),
        specialty_rows_raw=int(sp.n_raw.sum()), specialty_rows_distinct=len(sp),
    )
    json.dump(st, open(f"{OUT}/build_stats.json", "w"), indent=1, default=int)
    print(json.dumps(st, indent=1, default=int))


if __name__ == "__main__":
    main()
