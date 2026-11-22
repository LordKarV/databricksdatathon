"""Per-facility witnesses: location votes (v2 change 3), existence witnesses (single phone source), leakage
groups, and the facility_attributes table.

Reuses model/proto/evidence/facility.py (location_votes, existence, leakage_groups) unchanged and then applies
the v2 rules on top:
- the city vote uses the decision layer's place layers (model/proto/decision/resolve.py, which wraps
  audit/geo/resolve_input.py), so query resolution and the city vote read one gazetteer; a stated city that
  cannot be placed is a dissent (-1), not an abstention;
- a stated PIN missing from the India Post directory is a dissent on the PIN vote;
- phone_class comes from the same cleaned phone the card displays (derived/v1/record_trust.display_phones).
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import acommon as A
import facility as PF  # model/proto/evidence/facility.py (read-only)

sys.path.insert(0, str(A.ROOT / "model/proto/decision"))
from resolve import Resolver  # noqa: E402

VOTE_KM = PF.VOTE_KM


def location_existence(claims_text: pd.DataFrame) -> pd.DataFrame:
    """One row per facility: p1/p2, 7 votes against p1 (v2 rules), flags, existence witnesses, leakage group."""
    I = PF.INPUTS
    rs = pd.read_parquet(I["record_scores"])
    fl = pd.read_parquet(I["facility_location"])
    fg = pd.read_parquet(I["facility_geo"]).drop_duplicates("unique_id")
    loc = PF.location_votes(fl, fg, rs, claims_text)
    loc = loc.merge(fl[["unique_id", "address_city", "state_final", "pin"]], on="unique_id", how="left")

    # v2 city vote: one set of place layers, unplaceable = dissent
    R = Resolver()
    cache: dict = {}
    pts, notes = [], []
    for c, s in zip(loc.address_city, loc.state_final):
        key = (str(c or "").strip(), str(s or ""))
        if key not in cache:
            cache[key] = R._name(key[0], key[1] or None) if key[0] and key[0].lower() not in ("null", "nan") else None
        r = cache[key]
        pts.append((r["lat"], r["lon"]) if r and r["status"] == "ok" else (np.nan, np.nan))
        notes.append(None if r is None else r["status"])
    lat = np.array([p[0] for p in pts], float)
    lon = np.array([p[1] for p in pts], float)
    d = A_hav(loc.p1_lat.to_numpy(float), loc.p1_lon.to_numpy(float), lat, lon)
    has_p1 = np.isfinite(loc.p1_lat.to_numpy(float))
    status = pd.Series(notes, index=loc.index)
    loc["city_resolve_status"] = status.fillna("no_city_stated")
    v = np.where(np.isfinite(d), np.where(d <= VOTE_KM, 1, -1), 0)
    v = np.where(status.eq("not_found").to_numpy(), -1, v)   # stated, cannot be placed: dissent
    loc["vote_city_v1"] = loc.vote_city
    loc["vote_city"] = np.where(has_p1, v, 0).astype(int)
    loc["d_city_km"] = np.round(np.where(np.isfinite(d), d, np.nan), 1)

    # v2 PIN vote: stated PIN missing from India Post = dissent
    pdir = set(pd.read_parquet(A.ROOT / "data/raw/india_post_pincode_directory.parquet", columns=["pincode"]).pincode.astype(int))
    pin = pd.to_numeric(loc.pin, errors="coerce")
    stated = pin.between(100000, 999999)
    loc["pin_in_india_post"] = np.where(stated, pin.fillna(0).astype(int).isin(pdir), np.nan)
    loc["vote_pin_v1"] = loc.vote_pin
    loc["vote_pin"] = np.where(stated & ~pin.fillna(0).astype(int).isin(pdir), -1, loc.vote_pin).astype(int)
    loc["n_votes_for"] = sum((loc[f"vote_{w}"] == 1).astype(int) for w in PF.WITNESSES)
    loc["n_votes_against"] = sum((loc[f"vote_{w}"] == -1).astype(int) for w in PF.WITNESSES)

    ex = PF.existence(rs, fg)
    # v2: one phone source for the class and the display
    rt = pd.read_parquet(A.ROOT / "derived/v1/record_trust.parquet", columns=["unique_id", "display_phones"])
    disp = rt.set_index("unique_id").display_phones.map(lambda x: PF.phone10(list(x)[0]) if x is not None and len(x) else None)
    sp = pd.read_csv(I["shared_phones"], dtype={"phone": str})
    ncity = dict(zip(sp.phone.map(PF.phone10), sp.n_city))
    ex["phone_v1"], ex["phone_class_v1"] = ex.phone, ex.phone_class
    ex["phone"] = ex.unique_id.map(disp)
    ex["phone_n_cities"] = ex.phone.map(ncity).fillna(1).astype(int)
    ex["phone_class"] = np.where(ex.phone.isna(), "none", np.where(ex.phone_n_cities >= 3, "shared_3plus", "listed"))
    lg = PF.leakage_groups(rs, ex)
    out = loc.drop(columns=["address_city", "state_final", "pin"]).merge(ex, on="unique_id").merge(lg, on="unique_id")
    assert len(out) == 9959 and out.unique_id.is_unique
    return out


def A_hav(lat1, lon1, lat2, lon2):
    return PF.hav_km(lat1, lon1, lat2, lon2)


def _first(df: pd.DataFrame, key: str = "unique_id") -> pd.DataFrame:
    return df.drop_duplicates(key).set_index(key)


H24_SCOPES = ["emergency", "facility", "icu", "dialysis", "labour_room", "blood_bank", "pharmacy", "lab_imaging",
              "ambulance", "operation_theatre"]


def attributes(rec: pd.DataFrame, focus: pd.DataFrame, web_state: pd.DataFrame, nabh: pd.DataFrame) -> pd.DataFrame:
    """facility_attributes: one row per facility. rec carries unique_id, name, facilityTypeId, operatorTypeId,
    recency_of_page_update. Every value has a *_src column; web values carry the fetch date."""
    a = rec[["unique_id", "name", "facilityTypeId", "operatorTypeId"]].copy()
    op = [A.operator(o, n) for o, n in zip(a.operatorTypeId, a.name)]
    a["operator"], a["operator_src"] = [x for x, _ in op], [y for _, y in op]
    a["facility_level"] = a.name.map(A.public_level)
    a["facility_level_src"] = np.where(a.facility_level == "unknown", "none", "name_pattern")
    f = focus.set_index("unique_id")
    a["focus"] = a.unique_id.map(f.focus)
    hosp_name = a.name.str.contains(r"hospital|nursing home|medical college", case=False, na=False)
    a["facility_type"] = np.where(a.focus.eq("dental"), "dentist",
                                  np.where(a.facilityTypeId.eq("clinic") & hosp_name & a.focus.isna(), "hospital",
                                           a.facilityTypeId.fillna("unknown")))
    a["facility_type_src"] = np.where(a.facility_type != a.facilityTypeId.fillna("unknown"), "name_or_specialties", "facilityTypeId")
    a["vf_record_recency"] = rec.recency_of_page_update.where(~rec.recency_of_page_update.isin(["", "null"])).values

    vf = pd.read_parquet(A.ROOT / "kb/vf_details/out/facility_details.parquet")
    vf = vf[vf.n_usable > 0]
    wf = pd.read_parquet(A.ROOT / "kb/web_evidence/out/web_facility_details.parquet")
    wf = wf[wf.n_usable > 0]

    def fact(ft: str, at: str):
        return (_first(vf[(vf.fact_type == ft) & (vf.attribute == at)]), _first(wf[(wf.fact_type == ft) & (wf.attribute == at)]))

    for sc in H24_SCOPES:
        v, w = fact("hours_24x7", sc)
        inv, inw = a.unique_id.isin(v.index), a.unique_id.isin(w.index)
        a[f"is_24x7_{sc}"] = (inv | inw)
        a[f"is_24x7_{sc}_src"] = np.select([inv & inw, inw, inv], ["web+vf_text", "web", "vf_text"], default=None)
        a[f"is_24x7_{sc}_date"] = a.unique_id.map(w.fetched_at)
    # OPD hours: web (opd, then general) before the dataset text
    for col, srcs in [("opd_hours", [("web", "opd"), ("web", "general"), ("vf_text", "opd"), ("vf_text", "general")])]:
        val, src, quote, url, date = ([None] * len(a) for _ in range(5))
        for s, at in reversed(srcs):  # later assignments win -> first in list has priority
            tbl = wf if s == "web" else vf
            t = _first(tbl[(tbl.fact_type == "opd_hours") & (tbl.attribute == at)])
            for i, u in enumerate(a.unique_id):
                if u in t.index:
                    r = t.loc[u]
                    val[i], src[i], quote[i] = r.value_text, f"{s}:{at}", r.best_quote
                    url[i] = r.best_url if s == "web" else r.best_claim_id
                    date[i] = r.fetched_at if s == "web" else None
        a[col], a[f"{col}_src"], a[f"{col}_quote"], a[f"{col}_evidence"], a[f"{col}_date"] = val, src, quote, url, date

    v, w = fact("unit_beds", "total")
    a["beds"] = a.unique_id.map(v.value_num)
    a["beds_src"] = np.where(a.beds.notna(), "vf:" + a.unique_id.map(v.fields).fillna(""), None)
    wb = a.unique_id.map(w.value_num)
    a["beds_web"], a["beds_web_url"], a["beds_web_date"] = wb, a.unique_id.map(w.best_url), a.unique_id.map(w.fetched_at)

    schemes = sorted(set(vf[vf.fact_type == "empanelment"].attribute) | set(wf[wf.fact_type == "empanelment"].attribute))
    emp_v = vf[vf.fact_type == "empanelment"].groupby("unique_id").attribute.agg(lambda x: sorted(set(x)))
    emp_w = wf[wf.fact_type == "empanelment"].groupby("unique_id").attribute.agg(lambda x: sorted(set(x)))
    a["empanelment_vf_text"] = a.unique_id.map(emp_v).map(lambda x: "|".join(x) if isinstance(x, list) else None)
    a["empanelment_web"] = a.unique_id.map(emp_w).map(lambda x: "|".join(x) if isinstance(x, list) else None)
    for sch in ["pmjay", "cghs", "echs", "esic"]:
        a[f"empanel_{sch}"] = a.empanelment_vf_text.fillna("").str.contains(sch) | a.empanelment_web.fillna("").str.contains(sch)
    assert schemes  # sanity: the tables carry empanelment facts

    acc_v = vf[vf.fact_type == "accreditation"].groupby("unique_id").attribute.agg(lambda x: "|".join(sorted(set(x))))
    acc_w = wf[wf.fact_type == "accreditation"].groupby("unique_id").attribute.agg(lambda x: "|".join(sorted(set(x))))
    a["accreditation_vf_text"], a["accreditation_web"] = a.unique_id.map(acc_v), a.unique_id.map(acc_w)
    nb = nabh.drop_duplicates("unique_id").set_index("unique_id")
    a["nabh_list_status"], a["nabh_acc_no"] = a.unique_id.map(nb.status), a.unique_id.map(nb.acc_no)
    a["nabh_list_prefix"], a["nabh_cert_url"] = a.unique_id.map(nb.prefix), a.unique_id.map(nb.cert_url)
    a["nabh_tier"] = a.nabh_list_prefix.map(lambda p: "full_accreditation" if p in ("H", "SHCO") else
                                            ("cghs_echs_empanelment" if p == "HOS" else ("entry_level" if isinstance(p, str) else None)))
    a = a.merge(web_state, on="unique_id", how="left")
    return a
