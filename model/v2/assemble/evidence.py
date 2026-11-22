"""Families from the record's own text for 36 services: T own text, C contamination, N non-offer, S scope,
P prerequisites. A port of model/proto/evidence/atoms.py from 7 to 36 services:

- sentence matches come from kb/taxonomy/out/lexicon_matches.parquet (the v1.1 lexicon, clause-level cues);
- ownership and echo collapse reuse proto atoms._ownership and atoms.echo_units unchanged;
- specialties values enter with their measured evidence weight (kb/taxonomy/specialty_evidence_weights.csv)
  instead of a 0/1 tag: kind 'label' is a T witness, kind 'prereq' a P witness, value = weight;
- v2 change 1: every atom stores raw_pos, its index in the untouched raw array (claims idx skips blanks);
- v2 change 2: facility focus (eye, dental, IVF, diagnostic, single-focus specialties) from name and
  specialties, so S fires without a grades row and for clinics typed 'clinic'.
"""
from __future__ import annotations

import re

import duckdb
import numpy as np
import pandas as pd

import acommon as A
import atoms as PA  # model/proto/evidence/atoms.py (read-only)

RAW = A.ROOT / "data/raw/facilities.parquet"
UUID = PA.UUID
# same filter as cleaning/claims/build_claims.EXPLODE_SQL, but pos is kept (v2 change 1)
RAWPOS_SQL = f"""
with b as (select * from read_parquet('{RAW}') where regexp_matches(unique_id, '{UUID}') and source = 'kie'
           qualify row_number() over (partition by unique_id order by unique_id) = 1),
arr as (select unique_id, 'procedure' field, procedure j from b union all
        select unique_id, 'equipment', equipment from b union all select unique_id, 'capability', capability from b),
lists as (select unique_id, field, from_json(j, '["VARCHAR"]') l from arr where json_valid(j) and json_type(j) = 'ARRAY'),
items as (select unique_id, field, unnest(l) item, generate_subscripts(l, 1) pos from lists),
desc_s as (select unique_id, 'description' field,
           string_split(regexp_replace(description, '([.!?])\\s+', '\\1' || chr(31), 'g'), chr(31)) l
           from b where description is not null and description <> 'null'),
ditems as (select unique_id, field, unnest(l) item, generate_subscripts(l, 1) pos from desc_s),
allitems as (select * from items union all select * from ditems)
select unique_id, field, row_number() over (partition by unique_id, field order by pos) - 1 idx, pos - 1 raw_pos,
       item raw_item
from allitems where item is not null and regexp_replace(item, '^\\s+|\\s+$', '', 'g') <> ''
"""

# facility focus words (audit/claims SCOPE_NAME split by focus) and the services each focus may claim
FOCUS_RX = {
    "eye": r"\beye\b|netra|nethra|\bnayan\b|ophthal|lasik|retina",
    "dental": r"dental|\bdent\b|\bdentist|teeth|tooth|smile|orthodont",
    "ivf": r"\bivf\b|fertility|test tube",
    "skin_hair": r"\bskin\b|derma|\bhair\b|cosmetic|aesthetic",
    "ent": r"\bent\b",
    "physio_rehab": r"physio|rehab",
    "ayush": r"homoeo|homeo|ayurved|unani|\bsiddha\b|naturopath",
    "diagnostic": r"\bdiagnostics?\b|\bimaging\b|\bscans?\b|\bpath(o)? ?labs?\b|\blaborator(y|ies)\b|\blabs?\b",
}
FOCUS_EXEMPT = re.compile(r"general|multi|super|medical college|institute of medical|nursing home|maternity|child|women"
                          r"|mother|medical cent", re.I)
NOT_DIAGNOSTIC = re.compile(r"hospital|nursing home|clinic|medical college", re.I)
FOCUS_OK = {"eye": {"cataract_surgery", "eye_emergency"},
            "ivf": {"emergency_csection", "nicu", "institutional_delivery", "high_risk_pregnancy", "ultrasound",
                    "safe_abortion_mtp"},
            "diagnostic": {"mri", "ct_scan", "ultrasound"}}
SPEC_FOCUS = {"dental": re.compile(r"dent|orthodont|periodont|endodont|prosthodont|oral|maxillofacial|implant", re.I),
              "eye": re.compile(r"ophthal|retina|cornea|glaucoma|cataract|oculo|optometr|squint|lasik|eye", re.I)}


def facility_focus(name: str, ftype: str | None, specs: list[str]) -> tuple[str | None, str]:
    """(focus, source). source = facilityTypeId | name | specialties. Dentist type or a dental name -> dental."""
    n = name or ""
    if ftype == "dentist":
        return "dental", "facilityTypeId"
    if not FOCUS_EXEMPT.search(n):
        for f, rx in FOCUS_RX.items():
            if re.search(rx, n, re.I) and not (f == "diagnostic" and NOT_DIAGNOSTIC.search(n)):
                return f, "name"
    specs = [s for s in specs if isinstance(s, str) and s.strip()]
    if specs and not FOCUS_EXEMPT.search(n):
        for f, rx in SPEC_FOCUS.items():
            if sum(bool(rx.search(s)) for s in specs) / len(specs) >= 0.8:
                return f, "specialties"
    return None, "none"


def scope_conflict(focus: str | None, service: str, name: str) -> bool:
    if not isinstance(focus, str) or service in FOCUS_OK.get(focus, set()):
        return False
    # cleaning/claims scope rule: plastic / ortho / rehab names legitimately see burns and trauma
    return not (service in ("burn_care", "trauma_care", "orthopaedic_trauma_surgery")
                and re.search(r"plastic|aesthetic|ortho|rehab", name or "", re.I))


def _role(nonoffer: bool, kind: str, hedge: bool, field: str, spec: str) -> str:
    """proto atoms._role with the clause-level kb cue in place of the sentence-level claims cues."""
    if nonoffer:
        return "nonoffer"
    if kind in ("research", "template"):
        return "research_or_template"
    if kind in ("directory", "list", "staff"):
        return kind
    if kind == "qualified" and hedge:
        return "hedge"
    if spec == "quantity":
        return "quantity"
    if field == "equipment" or spec == "unit":
        return "unit_or_equipment"
    return "offer"


def sentence_atoms(names: pd.DataFrame) -> pd.DataFrame:
    m = pd.read_parquet(A.TAX / "out/lexicon_matches.parquet")
    m = m[m.service.isin(A.SERVICES)]
    c = pd.read_parquet(A.ROOT / "derived/v1/claims.parquet",
                        columns=["claim_id", "idx", "text", "attribution", "foreign_names", "sibling_names",
                                 "places_other_state", "places_other_district", "cue_hedge", "qty_value", "qty_unit"])
    a = m.drop(columns=["attribution"]).merge(c, on="claim_id", how="left", validate="many_to_one")
    assert a.text.notna().all()
    sd = pd.read_parquet(A.ROOT / "audit/merge/out/sentence_decisions.parquet", columns=["unique_id", "field", "idx", "quarantine"])
    a = a.merge(sd, on=["unique_id", "field", "idx"], how="left").merge(names, on="unique_id", how="left")
    rawpos = duckdb.sql(RAWPOS_SQL).df()
    a = a.merge(rawpos, on=["unique_id", "field", "idx"], how="left", validate="many_to_one")
    assert a.raw_pos.notna().all(), "every claim must locate its raw item"
    assert all(t in r for t, r in zip(a.text, a.raw_item)), "claim text must be inside its raw item"
    for col in ["foreign_names", "sibling_names", "places_other_state", "places_other_district"]:
        a[col] = a[col].fillna("")
    own = [PA._ownership(r) for r in a.itertuples(index=False)]
    a["ownership"], a["own_rej"], a["named_entity"] = zip(*own)
    a["specificity"] = np.where(a.text.map(lambda t: bool(PA.UNIT_RX.search(t))), "unit",
                                np.where(a.qty_value.notna() | (a.quantity_text.fillna("") != ""), "quantity", "generic"))
    nonoffer = (a.nonoffer_cue.fillna("") != "") | a.negation_extra.fillna(False)
    a["role"] = [_role(n, k, bool(h), f, s) for n, k, h, f, s in
                 zip(nonoffer, a.kind, a.cue_hedge.fillna(False), a.field, a.specificity)]
    a["counts_as_own"] = a.ownership.isin(PA.OWN_CLASSES) & a.role.isin(PA.COUNTING_ROLES)
    a["rejected_reason"] = np.where(a.counts_as_own, None, a.own_rej.where(a.own_rej.notna(), a.role.map(PA.ROLE_REJECT)))
    a["atom_id"] = a.claim_id + "|" + a.service
    a["weight"] = np.nan
    return a


def specialty_atoms(raw_specs: dict) -> pd.DataFrame:
    """One atom per (raw specialties item, service) with a measured weight. kind label -> T, prereq -> P."""
    w = pd.read_csv(A.TAX / "specialty_evidence_weights.csv")
    w = w[w.service.isin(A.SERVICES)]
    look = {}
    for r in w.itertuples(index=False):
        look.setdefault(r.specialty, []).append((r.service, r.kind, float(r.weight)))
    rows = []
    for u, items in raw_specs.items():
        seen = set()
        for pos, x in enumerate(items):
            if not isinstance(x, str) or x not in look:
                continue
            for s, kind, wt in look[x]:
                if (s, x) in seen:
                    continue
                seen.add((s, x))
                cid = f"{u[:8]}:spec:{pos}"
                rows.append(dict(atom_id=f"{cid}|{s}", claim_id=cid, unique_id=u, field="specialties", idx=pos, raw_pos=pos,
                                 text=x, raw_item=x, service=s, ownership="unanchored", role="list", specificity="generic",
                                 counts_as_own=False, rejected_reason="directory_or_list", named_entity=None,
                                 spec_kind=kind, weight=wt, quarantine=False, qty_value=np.nan))
    return pd.DataFrame(rows)


def prereq_witnesses(claims_own: pd.DataFrame, sentence_svc: set, spec_df: pd.DataFrame, norm_specs: pd.DataFrame) -> pd.DataFrame:
    """P witnesses: lexicon prerequisite patterns in own sentences that are not themselves atoms of the service,
    the lexicon's prerequisite specialty tags, and prereq-kind specialty weights (named 'related_specialty'
    unless the value is one of the lexicon tags)."""
    lex = __import__("json").loads((A.TAX / "lexicon.json").read_text())["services"]
    rows = []
    for s in A.SERVICES:
        for pname, p in lex.get(s, {}).get("prereqs", {}).items():
            if p.get("text"):
                rx = re.compile(p["text"], re.I)
                hit = claims_own[claims_own.text.map(lambda t: bool(rx.search(t)))]
                hit = hit[[(cid, s) not in sentence_svc for cid in hit.claim_id]]
                first = hit.drop_duplicates("unique_id")
                rows.append(pd.DataFrame(dict(unique_id=first.unique_id, service=s, prereq=pname, evidence_id=first.claim_id,
                                              quote=first.text, field=first.field, raw_pos=first.raw_pos, value=1.0,
                                              source_key="prereq_text", how="text")))
            tags = set(p.get("specialty_tags", []))
            if tags:
                t = norm_specs[norm_specs.spec.isin(tags)].drop_duplicates("unique_id")
                rows.append(pd.DataFrame(dict(unique_id=t.unique_id, service=s, prereq=pname, evidence_id=t.claim_id,
                                              quote=t.text, field="specialties", raw_pos=t.raw_pos, value=1.0,
                                              source_key="vf_specialty", how="specialty_tag")))
    pw = spec_df[spec_df.spec_kind == "prereq"].copy()
    pw["norm"] = pw.text.str.lower().str.replace(r"[^a-z]", "", regex=True)
    tagmap = {(s, t): pn for s in A.SERVICES for pn, p in lex.get(s, {}).get("prereqs", {}).items() for t in p.get("specialty_tags", [])}
    pw["prereq"] = [tagmap.get((s, n), "related_specialty") for s, n in zip(pw.service, pw.norm)]
    pw = pw.sort_values("weight", ascending=False).drop_duplicates(["unique_id", "service", "prereq"])
    rows.append(pd.DataFrame(dict(unique_id=pw.unique_id, service=pw.service, prereq=pw.prereq, evidence_id=pw.claim_id,
                                  quote=pw.text, field="specialties", raw_pos=pw.raw_pos, value=pw.weight,
                                  source_key="vf_specialty", how="specialty_weight")))
    out = pd.concat(rows, ignore_index=True)
    # one row per (pair, prerequisite): text beats a tag; a tag keeps the larger weight
    out["_o"] = out.how.map({"text": 0, "specialty_tag": 1, "specialty_weight": 2})
    return out.sort_values(["_o", "value"], ascending=[True, False]).drop_duplicates(["unique_id", "service", "prereq"]).drop(columns="_o")


def build(rec: pd.DataFrame, raw_specs: dict) -> dict:
    """rec: unique_id, name, facilityTypeId. Returns dict of DataFrames: atoms, pairs (T C N S P per pair), prereqs,
    focus (per facility)."""
    names = rec[["unique_id", "name"]]
    sa = sentence_atoms(names)
    spa = specialty_atoms(raw_specs)
    t_spec = spa[spa.spec_kind == "label"]
    atoms = pd.concat([sa, t_spec], ignore_index=True)
    rates = pd.read_csv(A.PROTO_EV / "attribution_rates.csv").set_index("class")
    atoms["support_score"] = ("role:" + atoms.role).map((rates.k / rates.n).round(4))  # display / citation order only
    atoms = PA.echo_units(atoms)
    PA.GOLD_SERVICES = A.SERVICES                       # proto grid -> 36 services
    fam = PA.pair_families(atoms, pd.Series(sorted(rec.unique_id)))
    assert len(fam) == len(rec) * 36
    # specialty weight per pair (max over label specialties); 0 when none
    sw = t_spec.groupby(["unique_id", "service"]).weight.max().rename("a_spec_weight").reset_index()
    fam = fam.merge(sw, on=["unique_id", "service"], how="left")
    fam["a_spec_weight"] = fam.a_spec_weight.fillna(0.0)

    claims = pd.read_parquet(A.ROOT / "derived/v1/claims.parquet", columns=["claim_id", "unique_id", "field", "idx", "text", "attribution"])
    claims = claims[claims.attribution.isin(PA.OWN_CLASSES)]
    rawpos = duckdb.sql(RAWPOS_SQL).df()[["unique_id", "field", "idx", "raw_pos"]]
    claims = claims.merge(rawpos, on=["unique_id", "field", "idx"], how="left")
    norm_specs = pd.DataFrame([(u, re.sub(r"[^a-z]", "", x.lower()), x, i, f"{u[:8]}:spec:{i}")
                               for u, items in raw_specs.items() for i, x in enumerate(items) if isinstance(x, str)],
                              columns=["unique_id", "spec", "text", "raw_pos", "claim_id"])
    pre = prereq_witnesses(claims, set(zip(sa.claim_id, sa.service)), spa, norm_specs)
    pcount = pre.groupby(["unique_id", "service"]).prereq.nunique().clip(upper=2).rename("P").reset_index()
    fam = fam.merge(pcount, on=["unique_id", "service"], how="left")
    fam["P"] = fam.P.fillna(0).astype(int)

    foc = [facility_focus(n, t, raw_specs.get(u, [])) for u, n, t in zip(rec.unique_id, rec.name, rec.facilityTypeId)]
    focus = pd.DataFrame({"unique_id": rec.unique_id, "focus": [f for f, _ in foc], "focus_src": [s for _, s in foc],
                          "name": rec.name})
    fam = fam.merge(focus, on="unique_id", how="left")
    fam["S"] = [int(scope_conflict(f, s, n)) for f, s, n in zip(fam.focus, fam.service, fam.name)]
    return dict(atoms=atoms, pairs=fam.drop(columns=["name"]), prereqs=pre, focus=focus, spec_prereq=spa[spa.spec_kind == "prereq"])


if __name__ == "__main__":
    assert facility_focus("Smile Kraft Dental Clinic", "clinic", [])[0] == "dental"
    assert scope_conflict("dental", "trauma_care", "Smile Kraft Dental Clinic")
    assert facility_focus("Nayan Jyoti Eye Hospital", "hospital", [])[0] == "eye"
    assert scope_conflict("eye", "emergency_csection", "Nayan Jyoti Eye Hospital")
    assert not scope_conflict("eye", "cataract_surgery", "Nayan Jyoti Eye Hospital")
    assert facility_focus("Siddharth Multispeciality Hospital", "hospital", [])[0] is None
    assert facility_focus("Dr Rao Clinic", "clinic", ["dentistry", "orthodontics"]) == ("dental", "specialties")
    assert facility_focus("City Diagnostics", "clinic", [])[0] == "diagnostic"
    assert facility_focus("City Hospital and Diagnostics", "hospital", [])[0] is None
    print("evidence self-check ok")
