"""Claim atoms (spec 4.2), evidence units by echo collapse (4.3) and per-pair family values (4.4).

build_atoms()  -> one row per (claim sentence, service) plus one per specialties-enum hit
pair_families(atoms, ...) -> one row per (unique_id, service) for every facility x 7 services;
                             the keyword switches reproduce the ablations of spec section 8.
"""
import re

import duckdb
import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from common import (COUNTING_ROLES, GOLD_SERVICES, INPUTS, LEX, LEX_KEY, OWN_CLASSES, OWNERSHIP_REJECT, RAW, SVC_MAP,
                    jlist, norm_text, split_cell)

UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
# "names a unit, centre, department or theatre for the service" (spec 4.2 specificity = unit)
UNIT_RX = re.compile(r"\b(units?|cent(re|er)s?|departments?|dept\b|theat(re|er)s?|wards?|wings?|suites?|cath ?labs?"
                     r"|machines?|stations?|chairs?|scanners?|bays?|beds?|bedded)\b", re.I)
NONOFFER_CUES = ["cue_negation", "cue_referral", "cue_future", "cue_camp", "cue_past"]
SPEC_RANK = {"unit": 0, "quantity": 1, "generic": 2}
FIELD_ORDER = {"procedure": 0, "capability": 1, "equipment": 2, "description": 3, "specialties": 4}
ECHO_RATIO = 85


def bucket_of(q_share: pd.Series, n_urls: pd.Series, shared: pd.Series) -> pd.Series:
    """Merge-risk bucket g (spec 4.4)."""
    high = (q_share >= 0.10) | (n_urls >= 30) | shared.astype(bool)
    low = (q_share == 0) & (n_urls < 8)
    return pd.Series(np.where(high, "high", np.where(low, "low", "mid")), index=q_share.index)


def record_table() -> pd.DataFrame:
    """Per record: merge stats, bucket, truncation and the context columns used by pair_features."""
    rs = pd.read_parquet(INPUTS["record_scores"], columns=[
        "unique_id", "name", "facilityTypeId", "operatorTypeId", "capacity", "numberDoctors", "q_share",
        "shared_content", "source_urls", "source_content_id", "n_sent", "n_q"])
    rs["n_urls"] = rs.source_urls.map(lambda s: len(jlist(s)))
    rs["bucket"] = bucket_of(rs.q_share.fillna(0), rs.n_urls, rs.shared_content.fillna(False))
    tr = duckdb.sql(f"""select unique_id, max(greatest(
          coalesce(json_array_length(case when json_valid(procedure) then procedure end),0),
          coalesce(json_array_length(case when json_valid(capability) then capability end),0),
          coalesce(json_array_length(case when json_valid(equipment) then equipment end),0))) >= 50 list_truncated
        from read_parquet('{RAW}') where source='kie' group by 1""").df()   # same rule as cleaning/claims/grade.py
    return rs.drop(columns=["source_urls"]).merge(tr, on="unique_id", how="left")


def _ownership(r) -> tuple:
    """(ownership, rejected_reason_if_ownership, named_entity) for one claim row."""
    if r.attribution == "other_facility":
        if r.foreign_names:
            return "other_facility", "names_other_facility", r.foreign_names
        if r.sibling_names:
            return "sibling", "sibling_branch", r.sibling_names
        if r.places_other_state:
            return "other_place", "other_state_place", r.places_other_state
        if r.places_other_district:
            return "other_place", "other_district_place", r.places_other_district
        return "quarantined", "quarantined_merge", None
    if r.attribution == "ambiguous":
        ent = r.foreign_names or r.places_other_state or r.places_other_district or r.sibling_names or None
        return "ambiguous", "ambiguous_reference", ent
    return r.attribution, None, None


def _role(r, specificity: str) -> str:
    if r.nonoffer or any(getattr(r, c) for c in NONOFFER_CUES):
        return "nonoffer"
    if r.kind in ("research", "template"):
        return "research_or_template"
    if r.kind in ("directory", "list", "staff"):
        return r.kind
    if r.kind == "qualified" and r.cue_hedge:
        return "hedge"
    if specificity == "quantity":
        return "quantity"
    if r.field == "equipment" or specificity == "unit":
        return "unit_or_equipment"
    return "offer"


ROLE_REJECT = {"nonoffer": "nonoffer_cue", "directory": "directory_or_list", "list": "directory_or_list",
               "staff": "staff_only", "hedge": "hedge", "research_or_template": "research_or_template"}


def claim_atoms_from_claims() -> pd.DataFrame:
    c = pd.read_parquet(INPUTS["claims"])
    c = c[c.services.str.len() > 0].copy()
    sd = pd.read_parquet(INPUTS["sentence_decisions"], columns=["unique_id", "field", "idx", "quarantine"])
    c = c.merge(sd, on=["unique_id", "field", "idx"], how="left", validate="one_to_one")
    for col in ["foreign_names", "sibling_names", "places_other_state", "places_other_district"]:
        c[col] = c[col].fillna("")
    rows = []
    for r in c.itertuples(index=False):
        svcs = [SVC_MAP[s] for s in split_cell(r.services) if s in SVC_MAP]
        if not svcs:
            continue
        own, own_rej, ent = _ownership(r)
        spec = "unit" if UNIT_RX.search(r.text) else ("quantity" if pd.notna(r.qty_value) else "generic")
        role = _role(r, spec)
        counts = own in OWN_CLASSES and role in COUNTING_ROLES
        rej = None if counts else (own_rej or ROLE_REJECT.get(role))
        for s in svcs:
            rows.append(dict(atom_id=f"{r.claim_id}|{s}", claim_id=r.claim_id, unique_id=r.unique_id, field=r.field,
                             idx=int(r.idx), text=r.text, service=s, ownership=own, role=role, specificity=spec,
                             quarantined=bool(r.quarantine), counts_as_own=counts, rejected_reason=rej,
                             named_entity=ent, qty_value=r.qty_value, qty_unit=r.qty_unit))
    return pd.DataFrame(rows)


def raw_specialties() -> dict:
    """unique_id -> raw specialties list, same row filter as cleaning/claims/build_claims.py."""
    r = duckdb.sql(f"""select unique_id, specialties from read_parquet('{RAW}')
        where regexp_matches(unique_id, '{UUID}') and source='kie'
        qualify row_number() over (partition by unique_id order by unique_id) = 1""").df()
    return {u: jlist(s) for u, s in zip(r.unique_id, r.specialties)}


def specialty_atoms() -> pd.DataFrame:
    """One atom per specialties-enum hit. Deviation from spec 4.9: idx is the position of the first raw array
    item with that normalised value (not the specialties.parquet row), so (unique_id, field, idx) still locates
    the verbatim raw item and the faithfulness test covers these atoms too."""
    sp = pd.read_parquet(INPUTS["specialties"])
    raw = raw_specialties()
    rows = []
    for s in GOLD_SERVICES:
        core = LEX.SERVICES[LEX_KEY[s]]["spec_core"]
        for r in sp[sp.spec.isin(core)].itertuples(index=False):
            items = raw.get(r.unique_id, [])
            pos = next(i for i, x in enumerate(items) if isinstance(x, str) and re.sub(r"[^a-z]", "", x.lower()) == r.spec)
            cid = f"{r.unique_id[:8]}:spec:{pos}"
            rows.append(dict(atom_id=f"{cid}|{s}", claim_id=cid, unique_id=r.unique_id, field="specialties", idx=pos,
                             text=items[pos], service=s, ownership="unanchored", role="list", specificity="generic",
                             quarantined=False, counts_as_own=False, rejected_reason="directory_or_list",
                             named_entity=None, qty_value=np.nan, qty_unit=None))
    return pd.DataFrame(rows)


def echo_units(atoms: pd.DataFrame, ratio: int = ECHO_RATIO) -> pd.DataFrame:
    """Single-link clusters of counts_as_own atoms within (unique_id, service): equal normalised text or
    rapidfuzz ratio >= `ratio`. Representative: most specific, then longest text, then field order and idx."""
    a = atoms.copy()
    a["unit_id"] = a.atom_id
    a["is_unit_rep"] = a.counts_as_own
    own = a[a.counts_as_own]
    for (uid, s), g in own.groupby(["unique_id", "service"], sort=False):
        ids, texts = g.index.to_list(), [norm_text(t) for t in g.text]
        parent = list(range(len(ids)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if texts[i] == texts[j] or fuzz.ratio(texts[i], texts[j]) >= ratio:
                    parent[find(i)] = find(j)
        clusters = {}
        for i in range(len(ids)):
            clusters.setdefault(find(i), []).append(ids[i])
        for members in clusters.values():
            m = a.loc[members]
            rep = m.assign(_s=m.specificity.map(SPEC_RANK), _l=-m.text.str.len(), _f=m.field.map(FIELD_ORDER)) \
                   .sort_values(["_s", "_l", "_f", "idx"]).index[0]
            uid_ = f"{a.at[rep, 'claim_id']}|{s}"
            a.loc[members, "unit_id"] = uid_
            a.loc[members, "is_unit_rep"] = False
            a.at[rep, "is_unit_rep"] = True
    a.loc[~a.counts_as_own, "is_unit_rep"] = False
    return a


def t_level(rep_fields: list, rep_specific: list, weak: bool) -> int:
    """T family (spec 4.4). Deviation: level 1 also covers own-ownership staff/hedge/research mentions."""
    n = len(rep_fields)
    if n == 0:
        return 1 if weak else 0
    if len(set(rep_fields)) >= 2:
        return 5 if any(rep_specific) else 4
    return 3 if n >= 2 else 2


def prereq_counts() -> pd.DataFrame:
    """P family input: distinct prerequisite flags per (unique_id, service) from own-ownership sentences that are
    not themselves atoms of the service, plus specialties tags listed for the prerequisite in the lexicon."""
    c = duckdb.sql(f"""select unique_id, services, prereqs, attribution from read_parquet('{INPUTS['claims']}')
                       where prereqs <> ''""").df()
    c = c[c.attribution.isin(OWN_CLASSES)]
    hits = set()
    for u, svcs, pre in zip(c.unique_id, c.services, c.prereqs):
        own_svcs = set(split_cell(svcs))
        for p in split_cell(pre):
            lk, name = p.split(".", 1)
            if lk in SVC_MAP and lk not in own_svcs:
                hits.add((u, SVC_MAP[lk], name))
    sp = pd.read_parquet(INPUTS["specialties"])
    for s in GOLD_SERVICES:
        for name, (_, tags) in LEX.SERVICES[LEX_KEY[s]]["prereqs"].items():
            for u in sp[sp.spec.isin(tags)].unique_id:
                hits.add((u, s, name))
    df = pd.DataFrame(sorted(hits), columns=["unique_id", "service", "prereq"])
    return df.groupby(["unique_id", "service"]).prereq.agg(lambda x: "|".join(sorted(x))).rename("prereqs").reset_index()


def _cite(units: pd.DataFrame) -> list:
    """Up to 3 unit representatives: specificity first, then a field not yet cited, then support_score, length."""
    pool = units.assign(_s=units.specificity.map(SPEC_RANK), _sup=-units.support_score.fillna(0), _l=-units.text.str.len())
    pool = pool.sort_values(["_s", "_sup", "_l", "idx"])
    picked, fields = [], set()
    while len(picked) < 3 and len(pool):
        cand = pool.assign(_new=~pool.field.isin(fields)).sort_values(["_s", "_new", "_sup", "_l"], ascending=[True, False, True, True])
        i = cand.index[0]
        picked.append(i)
        fields.add(pool.at[i, "field"])
        pool = pool.drop(i)
    return picked


def pair_families(atoms: pd.DataFrame, facilities: pd.Series, ownership_filter: bool = True,
                  echo: bool = True) -> pd.DataFrame:
    """Family values T, C, N for every facility x 7 services. `atoms` must carry unit_id/is_unit_rep (echo_units)
    and support_score. ownership_filter=False counts ownership-rejected offer atoms as own (ablation);
    echo=False makes every counting atom its own unit (ablation)."""
    a = atoms.copy()
    rej_own = a.rejected_reason.isin(OWNERSHIP_REJECT + ("ambiguous_reference",))
    if not ownership_filter:
        flip = rej_own & a.role.isin(COUNTING_ROLES)
        a.loc[flip, "counts_as_own"] = True
        a = echo_units(a.drop(columns=["unit_id", "is_unit_rep"]))
    if not echo:
        a["is_unit_rep"] = a.counts_as_own
        a["unit_id"] = a.atom_id
    a["spec_rank"] = a.specificity.map(SPEC_RANK)
    out = []
    for (u, s), g in a.groupby(["unique_id", "service"], sort=False):
        reps = g[g.is_unit_rep]
        own_cls = g.ownership.isin(OWN_CLASSES)
        weak = bool((own_cls & ~g.counts_as_own & (g.role != "nonoffer")).any())
        rejected = g[g.rejected_reason.isin(OWNERSHIP_REJECT)] if ownership_filter else g.iloc[0:0]
        T = t_level(reps.field.to_list(), (reps.specificity != "generic").to_list(), weak)
        cited = _cite(reps) if len(reps) else []
        rest = reps.drop(cited)
        t_wo = t_level(rest.field.to_list(), (rest.specificity != "generic").to_list(), weak)
        nC = len(rejected)
        out.append(dict(unique_id=u, service=s, T=T, C=0 if nC == 0 else (1 if T >= 2 else 2),
                        N=int(((g.role == "nonoffer") & own_cls).any()), n_atoms=len(g), n_units_own=len(reps),
                        n_fields_own=reps.field.nunique(), n_rejected=int(g.rejected_reason.notna().sum()),
                        n_rejected_ownership=nC, n_tagged_sentences=int((g.field != "specialties").sum()),
                        cited_atom_ids="|".join(g.loc[cited, "atom_id"]),
                        rejected_atom_ids="|".join(g[g.rejected_reason.notna()].sort_values("spec_rank").atom_id),
                        t_without_cited=t_wo))
    fam = pd.DataFrame(out)
    grid = pd.MultiIndex.from_product([facilities, GOLD_SERVICES], names=["unique_id", "service"]).to_frame(index=False)
    fam = grid.merge(fam, on=["unique_id", "service"], how="left")
    zero_cols = ["T", "C", "N", "n_atoms", "n_units_own", "n_fields_own", "n_rejected", "n_rejected_ownership",
                 "n_tagged_sentences", "t_without_cited"]
    fam[zero_cols] = fam[zero_cols].fillna(0).astype(int)
    fam[["cited_atom_ids", "rejected_atom_ids"]] = fam[["cited_atom_ids", "rejected_atom_ids"]].fillna("")
    return fam
