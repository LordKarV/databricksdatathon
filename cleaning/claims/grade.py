"""Facility x service evidence grade, with the rule that fired and the cited claims.

Reads out/claims.parquet, out/specialties.parquet (build_claims.py), the geo audit's facility_geo.parquet
and raw facility fields. Writes out/grades.parquet and out/grade_stats.json.

Rule order (first match wins). P_own = positive service claims attributed to this facility (anchored or
unanchored), P_amb = ambiguous attribution, P_oth = names another facility (quarantined), N = non-offer.
  G_tag      tag_only              no service sentence, only a specialty tag
  G_no       counter_evidence      only non-offer sentences (not available, referred out, planned, closed)
  G_else     attributed_elsewhere  every positive sentence is about another facility
  G_amb      weak                  only ambiguous sentences (credential / relation / chain context)
  G_scope    weak                  single-specialty name claiming an out-of-scope service
  G_nonspec  weak                  own sentences are only lists, staff bios, directory lines, hedged or third-party
  G_strong   strong                a specific own sentence + independent corroboration + no risk flag
  G_mod      moderate              a specific own sentence, but uncorroborated or with a risk flag
Corroboration (any one): all clinical prerequisites met by OTHER sentences or tags; a service quantity;
a sentence that names this facility itself. Risk flags: location conflict (geo audit), near-name merge,
this service also claimed for another facility in the record, a non-offer sentence, unit beds > capacity.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python grade.py
"""
import json, os, sys
import pandas as pd
from rapidfuzz import fuzz
import lexicon as L

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
_ROOT = os.environ.get("DATATHON_ROOT", os.path.abspath(os.path.join(D, "../..")))
_DATA = os.environ.get("DATATHON_DATA_ROOT", os.path.join(_ROOT, "data"))
RAW = os.path.join(_DATA, "raw/facilities.parquet")
GEO = os.path.join(_ROOT, "audit/geo/facility_geo.parquet")
sys.path.insert(0, os.path.join(_ROOT, "audit/merge"))
import analyze  # noqa: E402  (near_name)
import detect  # noqa: E402  (toks, GENERIC)
import re

INPATIENT = {"csection", "nicu", "icu", "cardiac_surgery", "burns", "trauma"}
OUTPATIENT_TYPES = {"clinic", "dentist", "doctor", "farmacy", "pharmacy"}
AYUSH = re.compile(r"homoeo|homeo|ayurved|unani|\bsiddha\b|naturopath", re.I)
SEP = re.compile(r",|;|&|/|\band\b")


def service_item_short(text, core):
    """v2 list rule: the sentence is a list of services only if the item holding the service
    word is <= 3 words in a 5+ item enumeration ('Cardiology, Nephrology, Dialysis, ...').
    A sentence enumerating MRI protocols or dialysis features stays specific."""
    items = [i.strip() for i in SEP.split(text) if i.strip()]
    hit = [i for i in items if core.search(i)]
    return len(items) >= 5 and bool(hit) and len(hit[0].split()) <= 3


def distinctive_self(self_names, rec_name, places):
    """v2 self-anchor: the self mention must share a distinctive (non-generic, non-place) token with
    the record name. 'Gauhati Medical College & Hospital' does not anchor 'Govt. Homoeo Medical College'."""
    own = {t for t in detect.toks(rec_name) if t not in detect.GENERIC and t not in places and len(t) > 2}
    for m in self_names.split("; "):
        mt = {t for t in detect.toks(m) if t not in detect.GENERIC and t not in places and len(t) > 2}
        if mt & own or any(fuzz.ratio(a, b) >= 85 for a in mt for b in own):
            return True
    return False

QTY_UNITS = {"dialysis": {"machines", "beds", "sessions"}, "nicu": {"beds", "incubators", "warmers", "ventilators"},
             "icu": {"beds", "ventilators"}, "mri": {"tesla"}, "trauma": {"ct_slices", "beds"},
             "csection": {"deliveries", "ots", "beds"}, "cardiac_surgery": {"procedures", "cath_labs"}, "burns": {"beds"}}
UNIT_BED_SVCS = {"icu", "nicu", "dialysis", "burns"}
OWN = ("own_anchored", "unanchored")
RANK = {"strong": 5, "moderate": 4, "weak": 3, "tag_only": 2, "attributed_elsewhere": 1, "counter_evidence": 0}
RISKS = ["risk_location", "risk_name_collision", "risk_service_elsewhere", "risk_counter", "risk_unit_gt_capacity", "risk_outpatient_type"]


def distinct_claims(texts, thr=85):
    """Greedy near-duplicate collapse (token_set_ratio >= thr); returns the representatives."""
    reps = []
    for t in texts:
        if not any(fuzz.token_set_ratio(t, r) >= thr for r in reps):
            reps.append(t)
    return reps


def cite(df, n=3):
    return [dict(claim_id=r.claim_id, field=r.field, text=r.text) for r in df.head(n).itertuples()]


def record_table():
    import duckdb
    r = duckdb.sql(f"""select unique_id, any_value(name) name, any_value(facilityTypeId) ftype,
        any_value(try_cast(capacity as double)) beds,
        max(greatest(coalesce(json_array_length(case when json_valid(procedure) then procedure end),0),
                     coalesce(json_array_length(case when json_valid(capability) then capability end),0),
                     coalesce(json_array_length(case when json_valid(equipment) then equipment end),0))) >= 50 truncated,
        any_value(coalesce(json_array_length(case when json_valid(source_ids) then source_ids end),0)) n_source_ids
        from read_parquet('{RAW}') where source='kie' group by 1""").df()
    g = pd.read_parquet(GEO, columns=["unique_id", "geo_conflict", "d_pin_km"]).drop_duplicates("unique_id")
    return r.merge(g, on="unique_id", how="left").set_index("unique_id")


def main(quarantine=True, name="grades", version=1):
    """quarantine=False is the ablation: 'names another facility' sentences count as own evidence.
    version=2 adds the post-hoc rules marked v2 (written after reading the ground-truth errors)."""
    c = pd.read_parquet(f"{OUT}/claims.parquet")
    if not quarantine:
        c["attribution"] = c.attribution.replace({"other_facility": "unanchored"})
    c["services"] = c.services.str.split("|").map(lambda l: [x for x in l if x])
    sp = pd.read_parquet(f"{OUT}/specialties.parquet")
    tags = sp.groupby("unique_id").spec.agg(set).to_dict()
    rec = record_table()
    # near-name merge flag per record (merge audit F2 rule: foreign name ratio >= 75 to own name)
    fo = c[c.foreign_names != ""]
    nn = {u for u, x in zip(fo.unique_id, fo.foreign_names) if analyze.near_name(x, rec.name.get(u) or "") >= 75}

    core = c[c.services.map(len) > 0].explode("services").rename(columns={"services": "service"})
    core = core[~core.dup_in_record]
    if version >= 2:
        import gazetteer, common as mcommon
        places = set(w for k in gazetteer.build(mcommon.load())[0] for w in k.split())
        names = rec.name.to_dict()
        lst = core.kind == "list"
        core.loc[lst, "kind"] = ["list" if service_item_short(t, L.SERVICES[v]["core"]) else "specific"
                                 for t, v in zip(core.loc[lst, "text"], core.loc[lst, "service"])]
        anc = core.attribution == "own_anchored"
        core.loc[anc, "attribution"] = ["own_anchored" if distinctive_self(sn, names.get(u) or "", places) else "unanchored"
                                        for sn, u in zip(core.loc[anc, "self_names"], core.loc[anc, "unique_id"])]
    # a duplicate copy of a mention sentence is not independent evidence (hand check E15)
    pre = c[(c.prereqs != "") & (c.attribution != "other_facility") & ~c.dup_in_record]
    pre_rows = [(u, p.split(".")[0], p.split(".")[1], cid, t) for u, ps, cid, t in zip(pre.unique_id, pre.prereqs, pre.claim_id, pre.text)
                for p in ps.split("|")]
    pre = pd.DataFrame(pre_rows, columns=["unique_id", "service", "prereq", "claim_id", "text"])
    core_ids = set(zip(core.unique_id, core.service, core.claim_id))
    pre["is_mention"] = [(u, s, cid) in core_ids for u, s, cid in zip(pre.unique_id, pre.service, pre.claim_id)]
    pre_g = {k: g for k, g in pre.groupby(["unique_id", "service"])}
    core_g = {k: g for k, g in core.groupby(["unique_id", "service"])}

    keys = set(core_g)
    for u, ts in tags.items():
        for svc, d in L.SERVICES.items():
            if ts & d["spec_core"]:
                keys.add((u, svc))
    rows = []
    for u, svc in sorted(keys):
        d = L.SERVICES[svc]
        g = core_g.get((u, svc), core.iloc[:0])
        r = rec.loc[u]
        pos = g[~g.nonoffer & (g.kind != "template")]
        own, amb, oth = pos[pos.attribution.isin(OWN)], pos[pos.attribution == "ambiguous"], pos[pos.attribution == "other_facility"]
        spec = own[own.kind == "specific"]
        neg = g[g.nonoffer]
        ts = tags.get(u, set())
        # prerequisites: from sentences that are not this service's own mention, or from tags
        pg = pre_g.get((u, svc))
        met, met_cite = {}, {}
        for k, (_, ptags) in d["prereqs"].items():
            scope = d.get("prereq_scope", {}).get(k)
            hit = None
            if pg is not None:
                h = pg[(pg.prereq == k) & (pg.is_mention if scope == "same_service_sentence" else ~pg.is_mention)]
                if scope == "same_service_sentence":
                    h = h[h.claim_id.isin(set(own.claim_id))]
                if len(h):
                    hit = dict(claim_id=h.claim_id.iloc[0], text=h.text.iloc[0])
            if hit is None and ts & ptags:
                hit = dict(tag=sorted(ts & ptags)[0])
            met[k] = hit is not None
            if hit:
                met_cite[k] = hit
        qty = own[own.qty_unit.isin(QTY_UNITS[svc])]
        unit_beds = own[(own.qty_unit == "beds")].qty_value.max() if svc in UNIT_BED_SVCS else None
        f = dict(
            risk_location=bool(r.geo_conflict) if pd.notna(r.geo_conflict) else False,
            risk_name_collision=u in nn,
            risk_service_elsewhere=len(oth) > 0,
            risk_counter=len(neg) > 0,
            risk_unit_gt_capacity=bool(unit_beds and r.beds and r.beds > 0 and unit_beds > r.beds),
            risk_outpatient_type=version >= 2 and svc in INPATIENT and r.ftype in OUTPATIENT_TYPES,
        )
        need = (len(met) + 1) // 2 if version >= 2 else len(met)  # v2: at least half the prerequisites
        corr = dict(corr_prereqs=sum(met.values()) >= need, corr_quantity=len(qty) > 0, corr_self_anchored=(own.attribution == "own_anchored").any())
        # corroborated only by specialty tags (no sentence, quantity or self-name): shown as such in the UI
        corr["corr_tags_only"] = (corr["corr_prereqs"] and not corr["corr_quantity"] and not corr["corr_self_anchored"]
                                  and all("tag" in v for v in met_cite.values()))
        scope = L.scope_conflict(r["name"], r.ftype, svc) or (version >= 2 and bool(AYUSH.search(r["name"] or "")))
        risks = [k[5:] for k in RISKS if f[k]]
        if len(g) == 0:
            grade, rule = "tag_only", "G_tag"
        elif len(own) == 0 and len(amb) == 0 and len(oth) == 0:
            grade, rule = "counter_evidence", "G_no"
        elif len(own) == 0 and len(amb) == 0:
            grade, rule = "attributed_elsewhere", "G_else"
        elif len(own) == 0:
            grade, rule = "weak", "G_amb"
        elif scope:
            grade, rule = "weak", "G_scope"
        elif len(spec) == 0:
            grade, rule = "weak", "G_nonspec"
        elif (corr["corr_prereqs"] or corr["corr_quantity"] or corr["corr_self_anchored"]) and not risks and not (version >= 2 and svc == "trauma" and not spec.text.str.contains(L.TRAUMA_EXPLICIT).any()):
            grade, rule = "strong", "G_strong"
        else:
            grade, rule = "moderate", "G_mod"
        order = own.assign(o=(own.attribution != "own_anchored").astype(int) * 4 + (own.kind != "specific").astype(int) * 2
                           + own.qty_unit.isna().astype(int)).sort_values("o")
        rows.append(dict(
            unique_id=u, service=svc, name=r["name"], facilityTypeId=r.ftype, grade=grade, rule=rule, rank=RANK[grade],
            n_mentions=len(g), n_own=len(own), n_own_distinct=len(distinct_claims(own.text.tolist())), n_specific=len(spec),
            n_ambiguous=len(amb), n_other_facility=len(oth), n_nonoffer=len(neg), own_fields="|".join(sorted(set(own.field))),
            tag_hit=bool(ts & d["spec_core"]), scope_conflict=scope, **corr, **f, risks="|".join(risks),
            **{"pre_" + k: v for k, v in met.items()},
            qty=(f"{qty.qty_value.iloc[0]:g} {qty.qty_unit.iloc[0]}" if len(qty) else None),
            truncated=bool(r.truncated), n_source_ids=int(r.n_source_ids),
            cite_evidence=json.dumps(cite(order)), cite_prereqs=json.dumps(met_cite),
            cite_counter=json.dumps(cite(neg, 2)),
            cite_elsewhere=json.dumps([dict(**x, names=n) for x, n in zip(cite(oth, 2), oth.foreign_names.head(2).tolist() or [""])]),
        ))
    out = pd.DataFrame(rows)
    out.to_parquet(f"{OUT}/{name}.parquet", index=False)
    st = {svc: dict(pairs=int(len(g)), grades=g.grade.value_counts().to_dict(), rules=g.rule.value_counts().to_dict(),
                    strong_if_risk_ignored=int(((g.grade == "strong") | ((g.rule == "G_mod") & g[["corr_prereqs", "corr_quantity", "corr_self_anchored"]].any(axis=1))).sum()),
                    risk_counts={k: int(g[k].sum()) for k in RISKS},
                    truncated_pairs=int(g.truncated.sum()))
          for svc, g in out.groupby("service")}
    json.dump(st, open(f"{OUT}/{name}_stats.json", "w"), indent=1)
    for svc, s in st.items():
        print(svc, s["pairs"], s["grades"])
    return out


if __name__ == "__main__":
    main(name="grades_v1")
    main(quarantine=False, name="grades_v1_noquarantine")
    main(version=2, name="grades")
    main(quarantine=False, version=2, name="grades_noquarantine")
