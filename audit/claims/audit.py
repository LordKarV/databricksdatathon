"""Service-claim evidence audit. Local snapshot only.

Outputs (in this directory):
  out/mentions.parquet  one row per (facility, service, field, sentence) core mention, with cue flags
  out/grades.parquet    one row per (facility, service) with any core or enum mention, with grade
  out/stats.json        all counts quoted in FINDINGS.md
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python audit.py
"""
import json, os, re
from collections import Counter
import pandas as pd
from rapidfuzz import fuzz, utils
from common import load, TEXT_FIELDS
from services import (SERVICES, ICU_STRIP, CUES, CUES_V1, STAFF, DIRECTORY, FACILITY_NAME, is_list, norm_spec, scope_conflict)
from place import record_states, cross_state_places

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)
FIELDS = TEXT_FIELDS + ["description"]
NONOFFER = ["negation", "referral", "future", "partner", "camp", "past", "hedge"]  # parttime is reported, not disqualifying
# Words that make up department / unit names ("Advanced Trauma Care Centre"), not proper names.
GENERIC_WORDS = set("""the a an our this its and of for in at with new main
hospital hospitals clinic clinics centre center centres centers medical college institute nursing home medicity
dialysis kidney renal nephrology trauma care critical emergency accident casualty mri ct scan scanning imaging diagnostic diagnostics
cardiac heart cardiology cancer oncology mother baby child children women maternity neonatal newborn burns burn treatment
poison control blood bank pain infertility ivf fertility laparoscopy laparoscopic research development eye dental
super superspeciality superspecialty speciality specialty multi multispeciality multispecialty multi-speciality multi-specialty
advanced modern comprehensive integrated excellence of district general government state civil community primary health
hours hour open day wellness rehabilitation physiotherapy surgical surgery icu nicu unit units""".split())


def sentences(r):
    for f in TEXT_FIELDS:
        for s in getattr(r, f + "_l"):
            yield f, s
    for s in re.split(r"(?<=[.!?])\s+", r.description_s):
        if s.strip():
            yield "description", s.strip()


def foreign_names(s, own):
    """Named facilities in s that do not resemble the record's own name."""
    out = []
    for m in FACILITY_NAME.findall(s):
        m = m.strip()
        toks = [t for t in utils.default_process(m).split() if t not in GENERIC_WORDS]
        if not toks:
            continue
        # Distinctive tokens only: "Nair Hospital" vs "Wockhardt Hospital Nagpur" shares just "hospital",
        # which token_set_ratio scored above 70 in round 1, hiding the cross-facility claim.
        own_toks = utils.default_process(own).split()
        if not any(fuzz.ratio(t, o) >= 85 for t in toks for o in own_toks):
            out.append(m)
    return out


def text_for(svc, s):
    return ICU_STRIP.sub(" ", s) if svc == "icu" else s


def grade(g):
    """Deterministic grader. Inputs are per-(facility, service) aggregates, see build()."""
    if g["n_clean"] == 0 and g["n_core"] > 0:
        return "non_offer_only"
    if g["n_core"] == 0:
        return "enum_only"
    if g["n_own"] == 0:
        return "other_facility_only"
    full = g["prereq_frac"] == 1.0
    corroborated = g["n_fields_own"] >= 2 or g["has_qty"]
    if g["n_specific"] >= 1 and full and corroborated:
        return "strong"
    if g["n_specific"] >= 1 and (g["prereq_frac"] >= 0.5 or g["n_fields_own"] >= 2):
        return "medium"
    return "weak"


def build():
    df = load()
    rows, grades = [], []
    for r in df.itertuples():
        spec = {norm_spec(x) for x in r.specialties_l}
        sents = list(sentences(r))
        rstates = record_states(r.address_stateOrRegion, r.address_city, r.address_zipOrPostcode)
        for svc, d in SERVICES.items():
            core = []
            for f, s in sents:
                t = text_for(svc, s)
                if d["core"].search(t) and not d["exclude"].search(t):
                    cues = {k: bool(v.search(s)) for k, v in CUES.items()}
                    fn = foreign_names(s, r.name or "")  # reported only: hand-check precision too low to grade on
                    fp = cross_state_places(s, rstates)
                    lst, staff, direc = is_list(s), bool(STAFF.search(s)), bool(DIRECTORY.search(s))
                    nonoffer = any(cues[k] for k in NONOFFER)
                    nonoffer_v1 = any(v.search(s) for v in CUES_V1.values())
                    core.append(dict(unique_id=r.unique_id, service=svc, field=f, sentence=s, **cues,
                                     named_other=bool(fn), named_other_names="; ".join(fn),
                                     foreign=bool(fp), foreign_places="; ".join(fp), is_list=lst, staff=staff,
                                     directory=direc, qty=bool(d["qty"].search(s)), nonoffer=nonoffer,
                                     nonoffer_v1=nonoffer_v1, specific=not (nonoffer or fp or lst or staff or direc)))
            enum_hit = bool(spec & d["spec_core"])
            if not core and not enum_hit:
                continue
            pre = {}
            for name, (prx, pset) in d["prereqs"].items():
                in_text = any(prx.search(s) for _, s in sents)
                pre[name] = bool(in_text or (spec & pset))
            clean = [c for c in core if not c["nonoffer"]]
            own = [c for c in clean if not c["foreign"]]
            g = dict(unique_id=r.unique_id, service=svc, name=r.name, facilityTypeId=r.facilityTypeId, n_rec_states=len(rstates),
                     beds=r.beds, ndoc=r.ndoc, enum_hit=enum_hit,
                     n_core=len(core), n_clean=len(clean), n_specific=sum(c["specific"] for c in core),
                     n_fields=len({c["field"] for c in core}), n_fields_clean=len({c["field"] for c in clean}),
                     n_own=len(own), n_fields_own=len({c["field"] for c in own}),
                     fields="|".join(sorted({c["field"] for c in core})),
                     has_qty=any(c["qty"] for c in own), any_foreign=any(c["foreign"] for c in core),
                     related=any(d["related"].search(s) for _, s in sents),
                     prereq_frac=sum(pre.values()) / len(pre), **{"pre_" + k: v for k, v in pre.items()})
            g["scope_conflict"] = scope_conflict(r.name, r.facilityTypeId, svc)
            g["any_named_other"] = any(c["named_other"] for c in own)
            g["grade_text"] = grade(g)
            # cap: a single-specialty record cannot be the strongest answer for an out-of-scope service
            g["grade"] = "weak" if g["scope_conflict"] and g["grade_text"] in ("strong", "medium") else g["grade_text"]
            grades.append(g)
            rows.extend(core)
    m, g = pd.DataFrame(rows), pd.DataFrame(grades)
    m.to_parquet(f"{OUT}/mentions.parquet")
    g.to_parquet(f"{OUT}/grades.parquet")
    return df, m, g


def stats(df, m, g):
    N = len(df)
    st = {"denominator_wellformed_rows": N}
    # array truncation: lists capped at 50 items
    st["rows_with_field_at_50_items"] = {f: int((df[f + "_l"].map(len) >= 50).sum()) for f in TEXT_FIELDS + ["specialties"]}
    st["rows_any_text_field_at_50"] = int(df[[f + "_l" for f in TEXT_FIELDS]].map(len).ge(50).any(axis=1).sum())
    per = {}
    for svc in SERVICES:
        gs, ms = g[g.service == svc], m[m.service == svc] if len(m) else m
        text_fac = gs[gs.n_core > 0]
        d = dict(
            facilities_any_mention_text_or_enum=len(gs),
            facilities_text_mention=len(text_fac),
            facilities_enum_only=int((gs.grade == "enum_only").sum()),
            facilities_enum_hit=int(gs.enum_hit.sum()),
            facilities_by_field={f: int(ms[ms.field == f].unique_id.nunique()) for f in FIELDS},
            mention_sentences=len(ms),
            sentences_by_field={f: int((ms.field == f).sum()) for f in FIELDS},
            sentence_cues={k: int(ms[k].sum()) for k in list(CUES) + ["named_other", "foreign", "is_list", "staff", "directory", "qty", "nonoffer_v1", "nonoffer", "specific"]},
            facilities_with_any_nonoffer_sentence=int(ms[ms.nonoffer].unique_id.nunique()),
            facilities_non_offer_only=int((gs.grade == "non_offer_only").sum()),
            facilities_2plus_fields_clean=int((text_fac.n_fields_clean >= 2).sum()),
            facilities_2plus_fields_own=int((text_fac.n_fields_own >= 2).sum()),
            facilities_with_any_foreign_sentence=int(ms[ms.foreign].unique_id.nunique()),
            facilities_other_facility_only=int((gs.grade == "other_facility_only").sum()),
            facilities_with_qty=int(text_fac.has_qty.sum()),
            prereq_rates_among_text_mentions={c[4:]: int(text_fac[c].sum()) for c in gs.columns if c.startswith("pre_") and gs[c].notna().any()},
            facilities_all_prereqs=int((text_fac.prereq_frac == 1).sum()),
            grades=gs.grade.value_counts().to_dict(),
            grades_before_scope_cap=gs.grade_text.value_counts().to_dict(),
            strong_if_no_corroboration_rule=int(((gs.n_own > 0) & (gs.n_specific >= 1) & (gs.prereq_frac == 1) & ~gs.scope_conflict & (gs.n_clean > 0)).sum()),
            strong_with_named_other_sentence=int(((gs.grade == "strong") & gs.any_named_other).sum()),
            scope_conflict_capped=int((gs.scope_conflict & gs.grade_text.isin(["strong", "medium"])).sum()),
        )
        per[svc] = d
    st["services"] = per
    # cross-field echo: are multi-field mentions the same sentence restated?
    echo = {}
    for svc in SERVICES:
        ms = m[(m.service == svc) & ~m.nonoffer & ~m.foreign]
        tot = near = 0
        for uid, grp in ms.groupby("unique_id"):
            fs = grp.field.unique()
            if len(fs) < 2:
                continue
            tot += 1
            a = grp[grp.field == fs[0]].sentence.tolist()
            b = grp[grp.field != fs[0]].sentence.tolist()
            if max(fuzz.token_set_ratio(x, y) for x in a for y in b) >= 85:
                near += 1
        echo[svc] = {"facilities_2plus_fields": tot, "with_near_duplicate_sentence_across_fields_ratio85": near}
    st["cross_field_echo"] = echo
    # specialties vocabulary
    raw, fac = Counter(), Counter()
    for l in df.specialties_l:
        raw.update(l)
        fac.update(set(l))
    normed = Counter()
    for l in df.specialties_l:
        normed.update({norm_spec(x) for x in l})
    dup_rows = int(df.specialties_l.map(lambda l: len(l) != len(set(l))).sum())
    st["specialties"] = dict(distinct_raw=len(fac), distinct_normalised=len(normed),
                             singletons_raw=sum(1 for v in fac.values() if v == 1),
                             values_used_by_10plus_facilities=sum(1 for v in fac.values() if v >= 10),
                             rows_with_duplicate_values=dup_rows,
                             rows_nonempty=int((df.specialties_l.map(len) > 0).sum()),
                             camelcase_share_of_facility_uses=round(sum(v for k, v in fac.items() if re.fullmatch(r"[a-z]+([A-Z][a-z]+)*", k)) / sum(fac.values()), 4),
                             mean_items=round(df.specialties_l.map(len).mean(), 2),
                             mean_distinct_items=round(df.specialties_l.map(lambda l: len(set(l))).mean(), 2))
    pd.DataFrame(fac.most_common(), columns=["specialty", "facilities"]).to_csv(f"{OUT}/specialties_vocab.csv", index=False)
    # inflation by type and size
    df2 = df.assign(size=pd.cut(df.beds, [-1, 0, 9, 49, 199, 1e9], labels=["0", "1-9", "10-49", "50-199", "200+"]).astype(str).replace("nan", "unknown"))
    gm = g.merge(df2[["unique_id", "size"]], on="unique_id")
    tm = gm[gm.n_core > 0]
    inf = {}
    for key in ["facilityTypeId", "size"]:
        base = df2[key].fillna("NA").value_counts()
        out = {}
        for grp_val, n in base.items():
            if n < 20:
                continue
            sub = tm[tm[key].fillna("NA") == grp_val]
            per_fac = sub.groupby("unique_id").service.nunique()
            out[grp_val] = dict(
                facilities=int(n),
                share_claiming={svc: round(sub[sub.service == svc].unique_id.nunique() / n, 4) for svc in SERVICES},
                strong_share_of_claims={svc: round((sub[sub.service == svc].grade == "strong").mean(), 3) if (sub.service == svc).any() else None for svc in SERVICES},
                mean_services_claimed=round(per_fac.reindex(df2[df2[key].fillna("NA") == grp_val].unique_id, fill_value=0).mean(), 3),
                claim_6plus_of_8=int((per_fac >= 6).sum()))
        inf[key] = out
    st["inflation"] = inf
    small = df2[(df2.beds > 0) & (df2.beds < 20)].unique_id
    hi = tm[tm.unique_id.isin(small) & tm.service.isin(["cardiac_surgery", "mri", "nicu", "burns"])]
    st["small_lt20_beds_claiming_tertiary"] = {svc: int(hi[hi.service == svc].unique_id.nunique()) for svc in ["cardiac_surgery", "mri", "nicu", "burns"]}
    st["small_lt20_beds_denominator"] = int(len(small))
    json.dump(st, open(f"{OUT}/stats.json", "w"), indent=1, default=int)
    return st


if __name__ == "__main__":
    df, m, g = build()
    st = stats(df, m, g)
    for svc, d in st["services"].items():
        print(svc, d["facilities_text_mention"], d["grades"])
