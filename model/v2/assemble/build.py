"""Assemble the v2 witness knowledge base for 9,959 facilities x 36 services. Writes to derived/v2/:

  witnesses.parquet           one row per (facility, service, witness); service '*' = facility-level witness.
                              Every (pair, family) with no present witness gets one 'absent' or 'not_observable' row.
  facility_features.parquet   one row per (facility, service): catalogue-named features, observability per family,
                              location votes and existence witnesses per facility.
  facility_attributes.parquet one row per facility: operator, level, type, hours, beds, empanelment, accreditation,
                              website state, each with its source and date.
  build_stats.json            counts behind ASSEMBLE.md.

Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python build.py   (about 6 minutes)
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

import acommon as A
import atoms as PA
import evidence as EV
import external as XT
import facloc as PL

FAM_ORDER = list(A.FAMILIES)


def record() -> pd.DataFrame:
    rs = pd.read_parquet(A.ROOT / "audit/merge/out/record_scores.parquet",
                         columns=["unique_id", "name", "facilityTypeId", "operatorTypeId", "capacity", "recency_of_page_update"])
    fl = pd.read_parquet(A.ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "state_final"])
    rec = rs.merge(fl, on="unique_id", how="left")
    assert len(rec) == 9959 and rec.unique_id.is_unique
    return rec


def web_state(uids: pd.Series) -> pd.DataFrame:
    """PATTERNS finding 3: alive (a crawl target answered), dead (a target exists, nothing usable), none."""
    tg = pd.read_parquet(A.ROOT / "kb/crawl/targets.parquet").explode("unique_ids")
    st = pd.read_parquet(A.ROOT / "kb/crawl/sites.parquet", columns=["target_id", "site_status", "finished_at"])
    t = tg.merge(st, on="target_id", how="left")
    alive = set(t[t.site_status.isin(["ok", "ok_thin"])].unique_ids)
    has = set(t.unique_ids)
    d = pd.DataFrame({"unique_id": uids})
    d["web_state"] = np.where(d.unique_id.isin(alive), "alive", np.where(d.unique_id.isin(has), "dead", "none"))
    d["web_state_date"] = d.unique_id.map(t.groupby("unique_ids").finished_at.max().astype(str).str[:10])
    d["web_state_src"] = "kb/crawl/sites.parquet"
    return d


def text_rows(ev: dict, rec: pd.DataFrame) -> pd.DataFrame:
    """T, C, N, S, P witness rows from the evidence layer."""
    a = ev["atoms"]
    own = a.ownership.isin(PA.OWN_CLASSES)
    units = a[a.is_unit_rep].assign(witness="vf_text_unit", value=1.0)
    weak = a[own & ~a.counts_as_own & (a.role != "nonoffer")]
    weak = weak.assign(witness=np.where(weak.field == "specialties", "vf_specialty", "vf_text_" + weak.role),
                       value=weak.weight.where(weak.field == "specialties", 1.0))
    T = pd.concat([units, weak])
    T = T.assign(source_key=np.where(T.field == "specialties", "vf_specialty", "vf_text:" + T.role),
                 note=np.where(T.field == "specialties", "value = specialty evidence weight",
                               "echo unit " + T.unit_id.astype(str)))
    rej = a[a.rejected_reason.isin(PA.OWNERSHIP_REJECT)]
    C = rej.assign(witness="vf_rejected_" + rej.rejected_reason, value=1.0, source_key="vf_reject:" + rej.rejected_reason,
                   note="names: " + rej.named_entity.fillna("").astype(str))
    N = a[(a.role == "nonoffer") & own].assign(witness="vf_nonoffer", value=1.0, source_key="vf_nonoffer")
    out = []
    for fam, d in (("T", T), ("C", C), ("N", N)):
        d = d.assign(role=d.role, evidence_id=d.claim_id, quote=d.text, value_text=d.ownership + "/" + d.role,
                     source="provided dataset text (derived/v1/claims.parquet)")
        out.append(XT.rows(d, family=fam))
    p = ev["pairs"]
    s1 = p[p.S == 1].merge(ev["focus"], on="unique_id", suffixes=("", "_f"))
    S = s1.assign(witness="scope_" + s1.focus.astype(str), role="scope", value=1.0, value_text="focus " + s1.focus.astype(str),
                  evidence_id="record:" + s1.focus_src, field=s1.focus_src, quote=s1.name, source_key="scope_rule",
                  source="record name, facilityTypeId and specialties")
    out.append(XT.rows(S, family="S"))
    pr = ev["prereqs"]
    P = pr.assign(witness="prereq_" + pr.prereq, role="prerequisite", value_text=pr.how,
                  source="provided dataset text and specialties", quote=pr.quote)
    out.append(XT.rows(P, family="P"))
    return pd.concat(out, ignore_index=True)


def placeholders(present: pd.DataFrame, obs: dict, uids: pd.Series) -> pd.DataFrame:
    """One absent / not_observable row per (pair, family) without a present witness. obs[fam] is a frame of
    (unique_id, service, observability) for families that can be unobservable; others default to absent."""
    grid = pd.MultiIndex.from_product([uids, A.SERVICES], names=["unique_id", "service"]).to_frame(index=False)
    pres = present[(present.observability == "present") & (present.service != XT.ALL)][["unique_id", "service", "family"]].drop_duplicates()
    out = []
    for fam in FAM_ORDER:
        g = grid.copy()
        if fam in obs:
            g = g.merge(obs[fam], on=["unique_id", "service"], how="left")
            g["observability"] = g.observability.fillna("not_observable")
        else:
            g["observability"] = "absent"
        hit = pres[pres.family == fam][["unique_id", "service"]].assign(_p=True)
        g = g.merge(hit, on=["unique_id", "service"], how="left")
        g = g[g._p.isna()]
        g.loc[g.observability == "present", "observability"] = "absent"   # obs said present for a non-service-level reason
        out.append(g.assign(family=fam, witness="none", value=0.0)[["unique_id", "service", "family", "witness", "observability", "value"]])
    ph = pd.concat(out, ignore_index=True)
    return XT.rows(ph)


def pair_obs(fam_obs: pd.DataFrame) -> pd.DataFrame:
    """Collapse a multi-list obs frame: present > absent > not_observable."""
    rank = {"present": 0, "absent": 1, "not_observable": 2}
    f = fam_obs.assign(_r=fam_obs.observability.map(rank)).sort_values("_r").drop_duplicates(["unique_id", "service"])
    return f[["unique_id", "service", "observability"]]


def main() -> None:
    t0 = time.time()
    A.OUT.mkdir(parents=True, exist_ok=True)
    rec = record()
    uids = pd.Series(sorted(rec.unique_id), name="unique_id")
    raw_specs = PA.raw_specialties()
    ev = EV.build(rec, raw_specs)
    print(f"evidence {time.time() - t0:.0f}s")

    nabh = pd.read_parquet(A.EXT / "nabh_accredited/nabh_vf_match.parquet")
    attrs = PL.attributes(rec, ev["focus"], web_state(uids), nabh[nabh.accept])
    claims_text = pd.read_parquet(A.ROOT / "derived/v1/claims.parquet", columns=["unique_id", "text"])
    loc = PL.location_existence(claims_text)
    print(f"place {time.time() - t0:.0f}s")

    xr, xobs, xf = XT.x_lists(rec, attrs)
    wr, wobs, wf = XT.w_web(uids)
    orr, oobs, of = XT.o_open(uids)
    dr = XT.d_details()
    kr, kobs = XT.k_iphs(attrs)
    rr, reader = XT.r_reader(ev["atoms"])
    tr = text_rows(ev, rec)
    present = pd.concat([tr, xr, wr, orr, dr, kr, rr], ignore_index=True)
    obs = {"X": pair_obs(xobs), "W": wobs, "O": oobs, "K": kobs,
           "R": pd.DataFrame(columns=["unique_id", "service", "observability"])}
    W = pd.concat([present, placeholders(present, obs, uids)], ignore_index=True)

    # precision per row
    rates = pd.read_csv(A.PROTO_EV / "attribution_rates.csv").set_index("class")
    prec = {k: (v[0], v[1]) for k, v in A.PRECISION.items()}
    prec.update({f"vf_text:{c.split(':', 1)[1]}": (int(r.k), int(r.n)) for c, r in rates.iterrows() if c.startswith("role:")})
    prec.update({f"vf_details:{k}": v for k, v in A.VF_DETAILS_BY_TYPE.items()})
    pk = W.source_key.map(lambda k: prec.get(k, (None, None)))
    W["precision_k"] = pk.map(lambda x: x[0]).astype("Float64")
    W["precision_n"] = pk.map(lambda x: x[1]).astype("Float64")
    W["precision"] = (W.precision_k / W.precision_n).round(4)
    W["precision_basis"] = W.source_key.map(lambda k: A.PRECISION.get(k, (None, None, None, None))[2] if k in A.PRECISION else
                                            ("sentence support by role, model/proto/evidence/attribution_rates.csv" if isinstance(k, str) and k.startswith("vf_text:")
                                             else ("kb/vf_details/out/handcheck.json by type" if isinstance(k, str) and k.startswith("vf_details:") else None)))
    W["raw_pos"] = pd.to_numeric(W.raw_pos, errors="coerce").astype("Int64")
    W["value"] = pd.to_numeric(W.value, errors="coerce")
    for c in ["value_text", "evidence_id", "evidence_url", "fetched_date", "field", "quote", "source", "source_key", "note", "role"]:
        W[c] = W[c].astype("string")
    W = W.sort_values(["service", "unique_id", "family", "witness"]).reset_index(drop=True)
    W["witness_id"] = "w" + W.index.astype(str)
    assert W.observability.isin(["present", "absent", "not_observable"]).all()
    assert set(W.family) <= set(A.FAMILIES)
    # every pair x family has at least one row
    cov = W[W.service != XT.ALL].groupby(["unique_id", "service", "family"]).size()
    assert len(cov) == 9959 * 36 * len(FAM_ORDER), len(cov)
    # absence never coded as negative: absent / not_observable rows carry value 0
    assert (W.loc[W.observability != "present", "value"] == 0).all()

    ff = features(ev, attrs, loc, W, xf, wf, of, rec, reader)
    W.to_parquet(A.OUT / "witnesses.parquet", index=False, compression="zstd")
    ff.to_parquet(A.OUT / "facility_features.parquet", index=False, compression="zstd")
    attrs.to_parquet(A.OUT / "facility_attributes.parquet", index=False, compression="zstd")
    ev["atoms"].drop(columns=["raw_item"], errors="ignore").to_parquet(A.OUT / "claim_atoms.parquet", index=False, compression="zstd")
    stats = dict(rows_witnesses=len(W), rows_present=int((W.observability == "present").sum()),
                 rows_features=len(ff), rows_attributes=len(attrs), atoms=len(ev["atoms"]),
                 units=int(ev["atoms"].is_unit_rep.sum()), reader_present=reader,
                 T=ev["pairs"]["T"].value_counts().sort_index().to_dict(), C=ev["pairs"].C.value_counts().to_dict(),
                 N=int(ev["pairs"].N.sum()), S=int(ev["pairs"].S.sum()), P=ev["pairs"].P.value_counts().to_dict(),
                 votes={w: loc[f"vote_{w}"].value_counts().to_dict() for w in PL.PF.WITNESSES},
                 city_resolve=loc.city_resolve_status.value_counts().to_dict(),
                 vote_city_changed=int((loc.vote_city != loc.vote_city_v1).sum()),
                 vote_pin_changed=int((loc.vote_pin != loc.vote_pin_v1).sum()),
                 phone_class=loc.phone_class.value_counts().to_dict(),
                 phone_class_changed=int((loc.phone_class != loc.phone_class_v1.replace({"mobile": "listed", "landline": "listed", "tollfree": "listed", "invalid": "none"})).sum()),
                 operator=attrs.operator.value_counts().to_dict(), operator_src=attrs.operator_src.value_counts().to_dict(),
                 web_state=attrs.web_state.value_counts().to_dict(), focus=ev["focus"].focus.value_counts().to_dict(),
                 seconds=round(time.time() - t0))
    (A.OUT / "build_stats.json").write_text(json.dumps(stats, indent=1, default=int))
    print(json.dumps(stats, indent=1, default=int))


def features(ev: dict, attrs: pd.DataFrame, loc: pd.DataFrame, W: pd.DataFrame, xf: dict, wf: dict, of: dict,
             rec: pd.DataFrame, reader: bool) -> pd.DataFrame:
    p = ev["pairs"].copy()
    key = ["unique_id", "service"]
    a = ev["atoms"]
    at = attrs.set_index("unique_id")
    u = p.unique_id
    f = pd.DataFrame({"unique_id": u, "service": p.service})
    # dataset claims
    rt = pd.read_parquet(A.PROTO_EV / "pair_features.parquet", columns=["unique_id", "list_truncated"]).drop_duplicates("unique_id")
    f["a_T"] = p["T"].astype(float)
    f["a_prereq"] = p.P.astype(float)
    f["a_list_truncated"] = u.map(rt.set_index("unique_id").list_truncated).astype(float)
    f["a_contamination"] = p.C.astype(float)
    f["a_scope_conflict"] = p.S.astype(float)
    f["a_negation"] = p.N.astype(float)
    f["a_rejected_ownership"] = p.n_rejected_ownership.astype(float)
    f["a_spec_weight"] = p.a_spec_weight
    pf = a[a.field != "specialties"].pivot_table(index=key, columns="field", values="atom_id", aggfunc="count", fill_value=0)
    for fld in ["procedure", "capability", "equipment", "description"]:
        f[f"a_m_{fld}"] = f.set_index(key).index.map(pf[fld] if fld in pf else pd.Series(dtype=float)).fillna(0).astype(float).values
    nown = a[a.counts_as_own].groupby(key).size()
    f["a_echo_dupes"] = (f.set_index(key).index.map(nown).fillna(0).values - p.n_units_own.values).clip(min=0).astype(float)

    # facility-level features reused from the feature study (same inputs, unchanged by v2)
    vz = pd.read_parquet(A.ROOT / "viz/features/out/features_pairs.parquet").drop_duplicates("unique_id").set_index("unique_id")
    reuse = ["a_quarantine_share", "k_text_24x7_any", "k_text_nabh", "k_text_pmjay", "k_text_cghs_echs", "c_n_urls",
             "c_share_social", "b_coord_pin_km", "b_loc_conf", "b_city_points_elsewhere", "b_copied_geocode",
             "b_website_other_org", "b_dup_group", "b_email_placeholder", "e_site_alive", "e_identity_conf",
             "e_web_hours_found", "f_osm_match", "f_osm_conflict", "f_osm_24x7", "f_osm_emergency_yes",
             "f_osm_opening_hours", "d_nabh_full_accreditation", "d_erk_nearest_km",
             "h_nfhs_institutional_birth_pct", "h_nfhs_csection_pct", "h_nfhs_insurance_pct", "h_nfhs_women_high_sugar_pct",
             "h_tt_motor_min", "h_log_pop_25km", "h_vf_records_25km"]
    for c in reuse:
        f[c] = u.map(vz[c]).values
    f["c_log2_n_urls"] = np.log2(f.c_n_urls.fillna(0) + 1)

    # type, operator, IPHS (v2)
    op = u.map(at.operator)
    f["operator_public"] = np.where(op == "public", 1.0, np.where(op == "private", 0.0, np.nan))
    f["g_type_hospital"] = (u.map(at.facility_type) == "hospital").astype(float).values
    f["g_type_dentist"] = (u.map(at.facility_type) == "dentist").astype(float).values
    f["g_n_specialties"] = u.map(vz.g_n_specialties).values
    f["g_log_beds"] = u.map(vz.g_log_beds).values
    lvl = u.map(at.facility_level)
    f["g_public_level"] = np.where(op == "public", lvl.map({"phc": 1, "chc": 2, "sdh": 3, "dh": 4, "mc": 5}), np.nan).astype(float)
    k = W[(W.family == "K") & (W.service != XT.ALL)].drop_duplicates(key).set_index(key)
    kv = f.set_index(key).index.map(k.value.where(k.observability != "not_observable"))
    f["g_iphs_prior"] = np.asarray(kv, dtype=float)
    f["g_iphs_essential"] = (f.g_iphs_prior >= 1).astype(float)
    beds = u.map(at.beds)
    f["b_scale_contradiction"] = ((u.map(at.facility_type) == "clinic") & (beds >= 100)).astype(float).values

    # observability per family
    for fam in A.FAMILIES:
        o = W[(W.family == fam) & (W.service != XT.ALL)]
        o = o.assign(_r=o.observability.map({"present": 0, "absent": 1, "not_observable": 2})).sort_values("_r").drop_duplicates(key).set_index(key)
        f[f"obs_{fam}"] = f.set_index(key).index.map(o.observability).values

    def pair_val(fam: str, witness_prefix: str, agg: str = "max") -> np.ndarray:
        w = W[(W.family == fam) & W.witness.str.startswith(witness_prefix) & (W.observability == "present")]
        s = w.groupby(key).value.agg(agg)
        return np.asarray(f.set_index(key).index.map(s), dtype=float)

    def gated(vals: np.ndarray, observable: np.ndarray) -> np.ndarray:
        return np.where(observable, np.nan_to_num(vals, nan=0.0), np.nan)

    # official lists, NaN where the list cannot see the pair (fairness coding)
    nb = xf["nabh"]
    coded = set(nb.unique_id[nb.nabh_specs.map(lambda x: x is not None and len(x) > 0)])
    nabh_svcs = {s for v, _ in XT.NABH_CODE_SVC.values() for s in v}
    f["d_nabh_service_code"] = gated(pair_val("X", "nabh_code_"), u.isin(coded).values & f.service.isin(nabh_svcs).values)
    listed = u.isin(set(nb.unique_id)).values
    f["d_nabh_listed"] = np.where(listed, 1.0, np.where(f.operator_public.values == 1, np.nan, 0.0))
    nmc_matched = u.isin(set(pd.read_parquet(A.EXT / "nmc_colleges/nmc_vf_matches.parquet").unique_id)).values
    strong = W[(W.family == "X") & (W.witness == "nmc_course_strong")].assign(v=1.0).groupby(key).v.max()
    f["d_nmc_course_strong"] = gated(np.asarray(f.set_index(key).index.map(strong), dtype=float), nmc_matched & f.service.isin(XT.NMC_COURSES).values)
    lq_cs = f.service.eq("emergency_csection").values
    pub_lvl = (f.operator_public.values == 1) & lvl.isin(["chc", "sdh", "dh", "mc"]).values
    lq_m = u.isin(set(pd.read_parquet(A.EXT / "laqshya_master/laqshya_vf_matches.parquet").unique_id)).values
    lqv = pair_val("X", "laqshya_")
    f["d_laqshya_ot_valid"] = gated((lqv >= 1).astype(float), lq_cs & (pub_lvl | lq_m))
    f["d_laqshya_ot_ever"] = gated((lqv > 0).astype(float), lq_cs & (pub_lvl | lq_m))
    f["d_laqshya_labour_room"] = gated((lqv > 0).astype(float), f.service.eq("institutional_delivery").values & (pub_lvl | lq_m))
    tcf_m = u.isin(set(pd.read_csv(A.EXT / "mohfw_trauma_196/tcf_vf_matches.csv").vf_id)).values
    pub_hosp = (f.operator_public.values == 1) & (f.g_type_hospital.values == 1)
    f["d_mohfw_trauma_centre"] = gated(pair_val("X", "mohfw_tcf"), f.service.eq("trauma_care").values & (pub_hosp | tcf_m))
    erk_m = u.isin(set(xf["erk"].unique_id)).values
    f["d_erk_blood_centre_on_site"] = gated(pair_val("X", "eraktkosh"), f.service.isin(["blood_bank"] + XT.ERK_PREREQ).values
                                            & ((f.g_type_hospital.values == 1) | erk_m))
    f["x_any_list"] = (f.obs_X == "present").astype(float)

    # website (W): NaN when the facility has no attributable site
    att = u.isin(wf["attributable"]).values
    f["e_web_service"] = gated(pair_val("W", "web_service_"), att)
    cell = wf["positive"].drop_duplicates(key).set_index(key).cell
    f["e_web_cell"] = f.set_index(key).index.map(cell).values
    neg = wf["negated"].assign(v=1.0).drop_duplicates(key).set_index(key).v
    f["e_web_negated"] = gated(np.asarray(f.set_index(key).index.map(neg), dtype=float), att)
    f["e_web_24x7_emergency"] = gated(u.isin(wf["em_uids"]).astype(float).values, att)
    f["web_state"] = u.map(at.web_state).values

    # dataset details per service (k_text_service_24x7: 24x7 stated for this service's unit)
    h24 = W[(W.family == "D") & W.witness.str.startswith("vf_hours_24x7:") & (W.service != XT.ALL)].assign(v=1.0).groupby(key).v.max()
    f["k_text_service_24x7"] = np.asarray(f.set_index(key).index.map(h24), dtype=float)
    has_h24_slot = f.service.isin([s for (ft, _), ss in XT.D_MAP.items() if ft == "hours_24x7" for s in ss]).values
    f["k_text_service_24x7"] = np.where(has_h24_slot, np.nan_to_num(f.k_text_service_24x7, nan=0.0), np.nan)
    f["d_any_detail"] = (f.obs_D == "present").astype(float)

    # reader slot (issue #50)
    rv = pair_val("R", "reader_") if reader else np.full(len(f), np.nan)
    f["r_reader_p_offers"] = rv

    # location votes and existence witnesses per facility (fusion inputs)
    lcols = ["p1_lat", "p1_lon", "p1_src", "p2_lat", "p2_lon", "loc_radius_km", "loc_conf", "loc_flags",
             "vote_coords", "vote_pin", "vote_city", "vote_name_place", "vote_state", "vote_text_pin", "vote_map_link",
             "vote_coords_p2", "vote_pin_p2", "vote_city_p2", "vote_name_place_p2", "vote_state_p2", "vote_text_pin_p2",
             "vote_map_link_p2", "n_votes_for", "n_votes_against", "city_resolve_status", "pin_in_india_post",
             "d_coords_km", "d_pin_km", "d_city_km", "d_name_place_km", "name_place_text", "copied_geocode",
             "coords_look_wrong", "pin_looks_wrong", "phone", "phone_class", "phone_n_cities", "website", "website_class",
             "n_source_ids", "source_ids_bin", "page_recency_present", "coord_shared_3plus_names", "non_facility_type",
             "strong_dup_member", "leakage_group_id", "group_size", "loc_note"]
    L = loc.set_index("unique_id")
    for c in lcols:
        f[c] = u.map(L[c]).values
    # p2 supported only by a witness other than the raw pin (MODEL_SPEC 3.3)
    p2w = ["vote_pin_p2", "vote_city_p2", "vote_name_place_p2", "vote_text_pin_p2", "vote_map_link_p2"]
    f["p2_supported"] = (f.p2_lat.notna() & (f[p2w] == 1).any(axis=1)).values
    f["b_votes_against"] = f.n_votes_against.astype(float)
    f["b_directory_phone"] = (f.phone_class == "shared_3plus").astype(float)
    f["b_no_phone"] = (f.phone_class == "none").astype(float)
    f["focus"] = u.map(ev["focus"].set_index("unique_id").focus).values
    assert len(f) == 9959 * 36 and not f.duplicated(key).any()
    return f


if __name__ == "__main__":
    main()
