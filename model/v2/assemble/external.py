"""Witnesses not written by the record's own sentences: X official lists, W own website, O open data,
D dataset details, K context (IPHS level prior), R reader slot.

Every builder returns present witness rows in the common schema (see ROW_COLS) plus, where the family can be
unobservable, an observability frame (unique_id, service, observability) over the pairs it can see. Pairs a
family cannot see are not_observable; build.py fills them. Absence from a list is recorded as 'absent' only
where the list covers that kind of facility, and it is never coded as negative evidence.

Entity matches are the accepted outputs of the external/<slug> match scripts (their thresholds, unchanged);
each row carries that list's hand-checked match precision via source_key (acommon.PRECISION).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

import acommon as A

ROW_COLS = ["unique_id", "service", "family", "witness", "role", "value", "value_text", "observability",
            "evidence_id", "evidence_url", "fetched_date", "field", "raw_pos", "quote", "source", "source_key", "note"]
ALL = "*"   # facility-level witness, applies to every service


def rows(df: pd.DataFrame, **const) -> pd.DataFrame:
    d = df.copy()
    for k, v in const.items():
        d[k] = v
    for c in ROW_COLS:
        if c not in d:
            d[c] = None
    d["observability"] = d.observability.fillna("present")
    return d[ROW_COLS]


def obs_frame(uids: pd.Series, services: list[str], present: set, observable_uids: set) -> pd.DataFrame:
    """present: set of (uid, service). observable_uids: facilities the source covers for these services."""
    g = pd.MultiIndex.from_product([uids, services], names=["unique_id", "service"]).to_frame(index=False)
    key = list(zip(g.unique_id, g.service))
    g["observability"] = np.where([k in present for k in key], "present",
                                  np.where(g.unique_id.isin(observable_uids), "absent", "not_observable"))
    return g


# ---------------------------------------------------------------- X official lists
NABH_CODE_SVC = {  # NABH specialty code -> (services, role). Codes are self-declared departments (FEATURES.md).
    "DIA": (["dialysis"], "service_code"), "NPH": (["dialysis", "kidney_transplant"], "department"),
    "TRN": (["kidney_transplant"], "department"),
    "OBG": (["emergency_csection", "institutional_delivery", "high_risk_pregnancy"], "department"),
    "EMD": (["emergency_24x7", "trauma_care"], "department"),
    "CAR": (["cardiac_surgery", "cath_lab_angioplasty", "stemi_thrombolysis"], "department_proxy"),
    "ONC": (["chemotherapy", "radiotherapy", "surgical_oncology"], "department"),
}
# NMC course -> service, (strong, support). The 8 services of external/nmc_colleges/join.py COURSE_SERVICE keep
# its patterns; the other rows extend it to the 36 taxonomy services (my mapping, not hand-checked).
NMC_COURSES = {
    "dialysis": (r"D\.M\. Nephrology", None), "kidney_transplant": (None, r"Nephrology|M\.Ch\. Urology"),
    "cardiac_surgery": (r"Cardio ?(?:Vascular|Thoracic)", r"D\.M\. Cardiology"),
    "cath_lab_angioplasty": (r"D\.M\. Cardiology", None), "stemi_thrombolysis": (None, r"D\.M\. Cardiology|Emergency Medicine"),
    "nicu": (r"Neonatology", r"M\.D\. Paediatrics"), "picu": (None, r"M\.D\. Paediatrics"),
    "paediatric_inpatient": (r"M\.D\. Paediatrics", None),
    "emergency_csection": (r"Obstetrics and Gynaecology", None), "institutional_delivery": (r"Obstetrics and Gynaecology", None),
    "high_risk_pregnancy": (None, r"Obstetrics and Gynaecology"), "safe_abortion_mtp": (None, r"Obstetrics and Gynaecology"),
    "trauma_care": (r"Emergency Medicine|M\.Ch\. Neurosurgery", r"M\.S\. Orthopaedics"),
    "emergency_24x7": (r"Emergency Medicine", None), "orthopaedic_trauma_surgery": (r"M\.S\. Orthopaedics|Traumatology", None),
    "neurosurgery": (r"M\.Ch\. Neurosurgery", None), "stroke_care": (None, r"D\.M\. Neurology"),
    "mri": (None, r"Radio-?diagnosis"), "ct_scan": (None, r"Radio-?diagnosis"), "ultrasound": (None, r"Radio-?diagnosis"),
    "burn_care": (r"Plastic", None), "icu": (r"Critical Care", r"Anaesthesiology"),
    "ventilator_support": (None, r"Critical Care|Anaesthesiology"),
    "radiotherapy": (r"Radiation Oncology|Radiotherapy", None), "chemotherapy": (r"Medical Oncology", None),
    "surgical_oncology": (r"Surgical Oncology|Gynaecological Oncology", None), "blood_bank": (r"Transfusion", None),
    "psychiatric_care": (r"M\.D\. Psychiatry", None), "de_addiction": (None, r"Psychiatry"),
    "cataract_surgery": (r"Ophthalmology", None), "eye_emergency": (None, r"Ophthalmology"),
    "tb_care": (r"Tuberculosis|Respiratory Medicine|Pulmonary Medicine", None),
}
ERK_PREREQ = ["emergency_csection", "trauma_care", "burn_care", "cardiac_surgery"]  # FEATURES.md d_erk_blood_centre_on_site


def x_lists(rec: pd.DataFrame, attrs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """rec/attrs: unique_id plus operator, facility_level, facility_type. Returns (rows, obs, facility facts)."""
    uids = rec.unique_id
    at = attrs.set_index("unique_id")
    public = set(at.index[at.operator == "public"])
    hospital = set(at.index[at.facility_type == "hospital"])
    out, obs, facts = [], [], {}

    # NABH
    nb = pd.read_parquet(A.EXT / "nabh_accredited/nabh_vf_match.parquet")
    nb = nb[nb.accept].drop_duplicates("unique_id")
    facts["nabh"] = nb
    r = []
    for u, acc, st, url, specs in zip(nb.unique_id, nb.acc_no, nb.status, nb.cert_url, nb.nabh_specs):
        for code in (list(specs) if specs is not None else []):
            for s in NABH_CODE_SVC.get(code, ([], ""))[0]:
                r.append(dict(unique_id=u, service=s, witness=f"nabh_code_{code}", role=NABH_CODE_SVC[code][1], value=1.0,
                              value_text=f"{code}; {st}", evidence_id=acc, evidence_url=url, quote=code,
                              note="NABH specialty codes are self-declared departments, not proof the service runs"))
    nr = pd.DataFrame(r)
    out.append(rows(nr, family="X", source="NABH accredited list (nabh.co), fetched 2026-11-21", source_key="nabh",
                    fetched_date="2026-11-21"))
    coded = set(nb.unique_id[nb.nabh_specs.map(lambda x: x is not None and len(x) > 0)])
    nabh_svcs = sorted({s for v, _ in NABH_CODE_SVC.values() for s in v})
    obs.append(obs_frame(uids, nabh_svcs, set(zip(nr.unique_id, nr.service)), coded).assign(list="nabh"))

    # NMC
    mt = pd.read_parquet(A.EXT / "nmc_colleges/nmc_vf_matches.parquet")
    co = pd.read_parquet(A.EXT / "nmc_colleges/nmc_courses.parquet")
    cl = pd.read_parquet(A.EXT / "nmc_colleges/nmc_colleges.parquet")[["college_id", "college_name", "updated_date"]]
    co = co[co.college_id.isin(mt.college_id)].merge(cl, on="college_id")
    r = []
    for s, (strong, support) in NMC_COURSES.items():
        for tier, pat, val in (("strong", strong, 1.0), ("support", support, 0.5)):
            if not pat:
                continue
            h = co[co.course_name.str.contains(pat, regex=True, na=False)]
            h = h.sort_values("approved_seat", ascending=False).drop_duplicates("college_id")
            r.append(h.assign(service=s, tier=tier, value=val))
    nm = pd.concat(r).merge(mt[["college_id", "unique_id"]], on="college_id")
    nm = nm.sort_values("value", ascending=False).drop_duplicates(["unique_id", "service"])
    nm = nm.assign(witness="nmc_course_" + nm.tier, role=np.where(nm.tier == "strong", "department", "department_support"),
                   value_text=nm.course_name + " (" + nm.approved_seat.astype(str) + " seats), " + nm.college_name,
                   evidence_id="nmc:college:" + nm.college_id.astype(str), evidence_url="https://nmc.org.in/college-courses/list",
                   fetched_date=nm.updated_date.astype(str).str[:10], quote=nm.course_name,
                   note="a PG course shows a department exists, not that the service runs today")
    out.append(rows(nm, family="X", source="NMC medical colleges and courses (nmc.org.in)", source_key="nmc"))
    obs.append(obs_frame(uids, list(NMC_COURSES), set(zip(nm.unique_id, nm.service)), set(mt.unique_id)).assign(list="nmc"))
    facts["nmc"] = nm

    # LaQshya (public facilities; Maternity OT -> C-section, Labour Room -> delivery). Value 1 valid, 0.5 expired.
    lq = pd.read_parquet(A.EXT / "laqshya_master/laqshya_vf_matches.parquet")
    lf = pd.read_parquet(A.EXT / "laqshya_master/laqshya_facilities.parquet")
    lq = lq.merge(lf[["lq_id", "name", "Maternity OT", "Labour Room"]], on="lq_id", how="left")
    r = []
    for dept, s in (("Maternity OT", "emergency_csection"), ("Labour Room", "institutional_delivery")):
        h = lq[lq[dept].notna()].sort_values(dept, ascending=False).drop_duplicates("unique_id")
        valid = h[dept] >= A.TODAY
        r.append(pd.DataFrame(dict(unique_id=h.unique_id, service=s, witness=np.where(valid, "laqshya_valid", "laqshya_expired"),
                                   role="certificate", value=np.where(valid, 1.0, 0.5),
                                   value_text=dept + " certificate valid to " + h[dept].dt.strftime("%Y-%m-%d"),
                                   evidence_id="laqshya:" + h.lq_id.astype(str), quote=h["name"],
                                   fetched_date=h[dept].dt.strftime("%Y-%m-%d"))))
    lr = pd.concat(r)
    out.append(rows(lr, family="X", source="NHSRC LaQshya master data 08-04-2026", source_key="laqshya",
                    evidence_url="https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf",
                    note="fetched_date holds the certificate validity date"))
    lq_cover = {u for u in public if at.at[u, "facility_level"] in ("chc", "sdh", "dh", "mc")} | set(lq.unique_id)
    obs.append(obs_frame(uids, ["emergency_csection", "institutional_delivery"], set(zip(lr.unique_id, lr.service)), lq_cover).assign(list="laqshya"))
    facts["laqshya"] = lr

    # MoHFW trauma care facilities (public hospitals)
    tc = pd.read_csv(A.EXT / "mohfw_trauma_196/tcf_vf_matches.csv")
    tr = pd.DataFrame(dict(unique_id=tc.vf_id, service="trauma_care", witness="mohfw_tcf", role="designation", value=1.0,
                           value_text="Level " + tc.level.astype(str) + " TCF, " + tc.status.astype(str),
                           evidence_id="tcf:" + tc.sno.astype(str), quote=tc.tcf_name))
    out.append(rows(tr, family="X", source="MoHFW List of 196 Trauma Care Facilities (Wayback, PDF created 2023-02-08)",
                    source_key="mohfw_tcf", fetched_date="2023-02-08",
                    evidence_url="https://web.archive.org/web/20231215043518id_/https://main.mohfw.gov.in/sites/default/files/List%20of%20Trauma%20Care.pdf",
                    note="funded is not functional; status from the 2019 programme brief"))
    obs.append(obs_frame(uids, ["trauma_care"], set(zip(tr.unique_id, tr.service)), (public & hospital) | set(tc.vf_id)).assign(list="mohfw_tcf"))

    # e-RaktKosh blood centres: blood_bank itself, and a prerequisite for four services
    er = pd.read_parquet(A.EXT / "eraktkosh_blood_centres/erk_vf_matches.parquet").drop_duplicates("unique_id")
    r = [pd.DataFrame(dict(unique_id=er.unique_id, service=s, witness="eraktkosh_centre", role=role, value=1.0,
                           value_text=er.erk_type + ", " + er.erk_category, quote=er.erk_name,
                           evidence_id="erk:" + er.hospital_code.astype("Int64").astype(str)))
         for s, role in [("blood_bank", "service")] + [(s, "prerequisite") for s in ERK_PREREQ]]
    err = pd.concat(r)
    out.append(rows(err, family="X", source="e-RaktKosh blood centre directory (MoHFW / C-DAC), pulled 2026-11-21",
                    source_key="eraktkosh", fetched_date="2026-11-21", evidence_url="https://eraktkosh.mohfw.gov.in/"))
    obs.append(obs_frame(uids, ["blood_bank"] + ERK_PREREQ, set(zip(err.unique_id, err.service)), hospital | set(er.unique_id)).assign(list="eraktkosh"))
    facts["erk"] = er

    # PMNDP Goa centre list (the only state list with facility rows)
    gm = pd.read_csv(A.EXT / "pmndp_counts_and_state_lists/goa_matches.csv")
    gm = gm[gm.matched.astype(str).str.lower() == "true"]
    gr = pd.DataFrame(dict(unique_id=gm.vf_unique_id, service="dialysis", witness="pmndp_centre", role="service", value=1.0,
                           value_text="PMNDP haemodialysis centre (Goa list, status as on 29/06/2020)", quote=gm.pmndp_name,
                           evidence_id="pmndp_goa:" + gm.pmndp_pin.astype(str)))
    out.append(rows(gr, family="X", source="Goa NHM PMNDP list of centres (2020)", source_key="pmndp_goa", fetched_date="2020-06-29",
                    evidence_url="https://nhm.goa.gov.in/wp-content/uploads/2020/07/PMNDP-List-of-centres.pdf"))
    goa = set(rec.unique_id[rec.state_final.eq("GOA")]) & public
    obs.append(obs_frame(uids, ["dialysis"], set(zip(gr.unique_id, gr.service)), goa).assign(list="pmndp_goa"))

    return pd.concat(out, ignore_index=True), pd.concat(obs, ignore_index=True), facts


# ---------------------------------------------------------------- W own website
def w_web(uids: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    si = pd.read_parquet(A.ROOT / "kb/web_evidence/out/site_identity.parquet")
    attributable = set(si[si.attributable].unique_id)
    conf = si.assign(c=si.confidence.map({"high": 3, "medium": 2, "low": 1, "none": 0})).groupby("unique_id").c.max()
    ws = pd.read_parquet(A.ROOT / "kb/web_evidence/out/web_service_summary.parquet")
    ws = ws[ws.unique_id.isin(attributable) & ws.service_id.isin(A.SERVICES)]
    wl = pd.read_parquet(A.ROOT / "kb/web_evidence/out/web_services.parquet",
                         columns=["unique_id", "service_id", "quote", "url", "line_kind", "path", "field"])
    best = ws.merge(wl.drop_duplicates(["unique_id", "service_id", "quote", "url"]),
                    left_on=["unique_id", "service_id", "best_quote", "best_url"],
                    right_on=["unique_id", "service_id", "quote", "url"], how="left")
    # the best quote's own line may sit on another URL of the same site: fall back to any row with that quote
    alt = wl.drop_duplicates(["unique_id", "service_id", "quote"]).set_index(["unique_id", "service_id", "quote"])
    miss = best.path.isna()
    k = pd.MultiIndex.from_frame(best.loc[miss, ["unique_id", "service_id", "best_quote"]])
    for c in ("path", "line_kind", "field", "url"):
        best.loc[miss, c] = alt[c].reindex(k).to_numpy()
    pos = best[best.web_positive].copy()
    strong, two = pos.web_positive_strong, pos.n_pages_positive >= 2
    pos["cell"] = np.select([strong & two, strong & pos.line_kind.eq("item"), strong, two], ["A", "B", "C", "D"], default="E")
    pos = pos.assign(service=pos.service_id, witness="web_service_" + pos.cell, role="offer", value=1.0,
                     value_text=pos.n_pages_positive.astype(str) + " page(s), " + np.where(strong, "strong", "weak"),
                     evidence_id=pos.path, evidence_url=pos.url.fillna(pos.best_url), fetched_date=pos.best_fetched_at.astype(str).str[:10],
                     field=pos.best_field, quote=pos.best_quote, source_key="web:" + pos.cell,
                     note="identity " + pos.identity_conf.astype(str) + "; medium identity was 2/5 correct in QA")
    neg = best[best.n_negated_rows > 0].assign(service=lambda d: d.service_id, witness="web_negated", role="nonoffer",
                                               value=1.0, evidence_url=lambda d: d.best_url, source_key="web:negated",
                                               note="a negated line is excluded, not evidence of absence")
    wh = pd.read_parquet(A.ROOT / "kb/web_evidence/out/web_hours.parquet")
    wh = wh[wh.attributable & wh.status.isin(["ok", "flagged"]) & (wh.polarity == "positive") &
            (wh.fact_type == "hours_24x7") & (wh.attribute == "emergency")].drop_duplicates("unique_id")
    em = pd.concat([wh.assign(service=s) for s in ("emergency_24x7", "trauma_care", "emergency_csection")])
    em = em.assign(witness="web_24x7_emergency", role="hours", value=1.0, value_text="24x7 emergency", evidence_id=em.path,
                   evidence_url=em.url, fetched_date=em.fetched_at.astype(str).str[:10], source_key="web:hours_24x7_emergency")
    src = "facility's own website (kb/web_evidence, crawl 2026-11-21)"
    r = pd.concat([rows(pos, family="W", source=src), rows(neg, family="W", source=src), rows(em, family="W", source=src)],
                  ignore_index=True)
    present = set(zip(pos.unique_id, pos.service)) | set(zip(em.unique_id, em.service))
    obs = obs_frame(uids, A.SERVICES, present, attributable)
    return r, obs, dict(attributable=attributable, identity_conf=conf, positive=pos, negated=neg, em_uids=set(wh.unique_id))


# ---------------------------------------------------------------- O open data
OSM_SPEC = {"dialysis": ["nephrology", "dialysis"], "emergency_csection": ["gynaecology", "obstetrics", "maternity", "gynecolog"],
            "institutional_delivery": ["gynaecology", "obstetrics", "maternity", "gynecolog"],
            "nicu": ["neonatology"], "paediatric_inpatient": ["paediatrics", "pediatrics"],
            "cardiac_surgery": ["cardiac surgery", "cardiothoracic"], "cath_lab_angioplasty": ["cardiology"],
            "mri": ["radiology", "mri"], "ct_scan": ["radiology"], "ultrasound": ["radiology", "ultrasound"],
            "burn_care": ["plastic surgery", "burn"], "emergency_24x7": ["emergency"], "trauma_care": ["trauma"],
            "orthopaedic_trauma_surgery": ["orthopaedics", "orthopedics"], "stroke_care": ["neurology"],
            "neurosurgery": ["neurosurgery"], "chemotherapy": ["oncology"], "surgical_oncology": ["oncology"],
            "radiotherapy": ["radiotherapy"], "psychiatric_care": ["psychiatry"], "cataract_surgery": ["ophthalmology"],
            "eye_emergency": ["ophthalmology"], "kidney_transplant": ["transplant"], "tb_care": ["pulmonology", "tuberculosis"]}


def o_open(uids: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    m = pd.read_parquet(A.ROOT / "kb/opendata/vf_opendata_match.parquet")
    m = m[m.tier.isin(["high", "medium", "conflict"])].copy()
    m["_o"] = m.tier.map({"high": 0, "medium": 1, "conflict": 2})
    m = m.sort_values(["unique_id", "_o"])
    ex = m.drop_duplicates(["unique_id", "source"])
    ex = ex.assign(service=ALL, witness=np.where(ex.tier == "conflict", "osm_conflict", ex.source + "_match_" + ex.tier),
                   role=np.where(ex.tier == "conflict", "location_warning", "existence"), value=1.0,
                   value_text=ex.source + " " + ex.tier + ", " + ex.km.round(2).astype(str) + " km",
                   evidence_id=ex.source + ":" + ex.source_id, evidence_url=ex.source_url,
                   fetched_date=ex.last_edit.astype(str).str[:10], quote=ex.cand_name,
                   source_key="osm:" + ex.tier, source=np.where(ex.source == "osm", "OpenStreetMap (c) contributors, ODbL", "Wikidata (CC0)"),
                   note=np.where(ex.tier == "conflict", "same name more than 25 km from the record's PIN: never evidence", None))
    matched = set(m[m.tier.isin(["high", "medium"])].unique_id)
    f = pd.read_parquet(A.ROOT / "kb/opendata/vf_opendata_facts.parquet")
    f = f[f.match_tier.isin(["high", "medium"])]
    r = []
    sp = f[f.field == "speciality"]
    for s, words in OSM_SPEC.items():
        h = sp[sp.value.str.lower().map(lambda v: any(w in v for w in words))].drop_duplicates("unique_id")
        r.append(h.assign(service=s, witness="osm_speciality", role="service_tag"))
    e = f[(f.field == "emergency") & (f.value.astype(str).str.lower() == "yes")].drop_duplicates("unique_id")
    r.append(e.assign(service="emergency_24x7", witness="osm_emergency_yes", role="service_tag"))
    sv = pd.concat(r)
    sv = sv.assign(value=1.0, value_text=sv.field + "=" + sv.value.astype(str), evidence_id=sv.source + ":" + sv.source_id,
                   evidence_url=sv.source_url, fetched_date=sv.observed_at.astype(str).str[:10], quote=sv.value.astype(str),
                   source_key="osm:" + sv.match_tier, source="OpenStreetMap (c) contributors, ODbL",
                   note="OSM tags are sparse; match precision is identity only")
    out = pd.concat([rows(ex, family="O"), rows(sv, family="O")], ignore_index=True)
    obs = obs_frame(uids, A.SERVICES, set(zip(sv.unique_id, sv.service)), matched)
    return out, obs, dict(matched=matched, conflict=set(m[m.tier == "conflict"].unique_id), facts=f)


# ---------------------------------------------------------------- D dataset details
D_MAP = {("hours_24x7", "emergency"): ["emergency_24x7"], ("hours_24x7", "dialysis"): ["dialysis"],
         ("hours_24x7", "labour_room"): ["institutional_delivery", "emergency_csection"], ("hours_24x7", "icu"): ["icu"],
         ("hours_24x7", "blood_bank"): ["blood_bank"], ("equipment_count", "dialysis_machines"): ["dialysis"],
         ("equipment_count", "mri_tesla"): ["mri"], ("equipment_count", "ct_slices"): ["ct_scan"],
         ("equipment_count", "cath_labs"): ["cath_lab_angioplasty"], ("equipment_count", "ventilators"): ["ventilator_support"],
         ("unit_beds", "icu"): ["icu"], ("unit_beds", "nicu"): ["nicu"], ("unit_beds", "picu"): ["picu"],
         ("unit_beds", "dialysis"): ["dialysis"], ("unit_beds", "emergency"): ["emergency_24x7"],
         ("blood_centre", "blood_bank"): ["blood_bank"], ("blood_centre", "blood_storage_unit"): ["blood_bank"],
         ("hours_dialysis_shifts", "dialysis_shifts"): ["dialysis"], ("opd_hours", "dialysis"): ["dialysis"]}
D_FACILITY = {("hours_24x7", "facility"), ("accreditation", "NABH"), ("accreditation", "NABL"), ("accreditation", "JCI"),
              ("empanelment", "pmjay"), ("empanelment", "cghs"), ("empanelment", "echs"), ("empanelment", "esic"),
              ("ambulance", "ambulance_service"), ("unit_beds", "total")}


def d_details() -> pd.DataFrame:
    fd = pd.read_parquet(A.ROOT / "kb/vf_details/out/facility_details.parquet")
    fd = fd[fd.n_usable > 0]
    r = []
    for (ft, at), svcs in D_MAP.items():
        h = fd[(fd.fact_type == ft) & (fd.attribute == at)]
        val = 0.5 if at == "blood_storage_unit" else 1.0
        r += [h.assign(service=s, value=val, role="service_detail") for s in svcs]
    for ft, at in D_FACILITY:
        h = fd[(fd.fact_type == ft) & (fd.attribute == at)]
        r.append(h.assign(service=ALL, value=h.value_num if ft == "unit_beds" else 1.0, role="facility_detail"))
    d = pd.concat(r)
    d = d.assign(witness="vf_" + d.fact_type + ":" + d.attribute,
                 value_text=d.value_text.fillna(d.value_num.astype(str)),
                 evidence_id=d.best_claim_id.fillna("record:" + d.fields.astype(str)),
                 field=d.fields, quote=d.best_quote, source_key="vf_details:" + d.fact_type,
                 source="provided dataset text (kb/vf_details)",
                 note="same extraction as the record text (family T); not an independent source")
    return rows(d, family="D")


# ---------------------------------------------------------------- K context: IPHS level prior (public only)
def k_iphs(attrs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    a = attrs[["unique_id", "operator", "facility_level"]]
    g = pd.MultiIndex.from_product([a.unique_id, A.SERVICES], names=["unique_id", "service"]).to_frame(index=False)
    g = g.merge(a, on="unique_id")
    known = (g.operator == "public") & g.facility_level.isin(A.IPHS_LEVELS)
    g["value"] = [A.IPHS[s][lv] if k else np.nan for s, lv, k in zip(g.service, g.facility_level, known)]
    g["observability"] = np.where(~known, "not_observable", np.where(g.value > 0, "present", "absent"))
    p = g[g.observability == "present"]
    p = p.assign(witness="iphs_expected", role="level_prior",
                 value_text=np.where(p.value >= 1, "essential", "desirable or size-dependent") + " at " + p.facility_level.str.upper(),
                 quote=p.service.map(A.IPHS_TEXT), evidence_id="iphs2022:" + p.service, source="IPHS 2022 (NHSRC), via kb/taxonomy/services.json",
                 source_key="iphs_reading", note="level from the name; prior, not evidence about this facility")
    return rows(p, family="K"), g[["unique_id", "service", "observability"]]


# ---------------------------------------------------------------- R reader slot
READER = A.OUT / "reader_scores.parquet"


def r_reader(atoms: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Soft T-family input from the transformer reader (issue #50) when its file exists; else an empty slot."""
    if not READER.exists():
        return pd.DataFrame(columns=ROW_COLS), False
    rd = pd.read_parquet(READER)
    rd = rd.merge(atoms[["claim_id", "service", "unique_id", "text", "field", "raw_pos"]].drop_duplicates(["claim_id", "service"]),
                  left_on=["claim_id", "service_id"], right_on=["claim_id", "service"], how="inner")
    rd = rd.assign(witness="reader_p_offers", role="offer", value=rd.p_offers, value_text="p_about_this=" + rd.p_about_this.round(3).astype(str),
                   evidence_id=rd.claim_id, quote=rd.text, source="transformer reader (issue #50)", source_key="reader")
    return rows(rd, family="R"), True
