"""Independent recomputation of story 4 (official lists vs dataset; PMNDP by state)."""
import pandas as pd
from vcommon import R, OK, wil, claims, raw

E = R + "data/external/"
c = claims()
cl = c[c.text_pos | c.spec]
claim = lambda svcs: set(cl.unique_id[cl.service.isin(svcs)])
pf = pd.read_parquet(R + "model/proto/evidence/pair_features.parquet", columns=["unique_id", "operator_public"]).drop_duplicates("unique_id")
public = set(pf.unique_id[pf.operator_public])
rw = raw()
print("public (pf)", len(public), "raw operatorTypeId", rw.operatorTypeId.value_counts().to_dict())
vd = pd.read_parquet(R + "kb/vf_details/out/facility_details.parquet")
print("accreditation attrs", vd[vd.fact_type == "accreditation"].attribute.value_counts().head(8).to_dict())
nabh_claim = set(vd.unique_id[(vd.fact_type == "accreditation") & (vd.attribute == "NABH") & (vd.n_usable > 0)]) & OK
# alt: raw text mentions NABH anywhere
txtcols = ["description", "capability", "procedure", "specialties", "equipment"]
nabh_txt = set(rw.unique_id[rw[txtcols].fillna("").agg(" ".join, axis=1).str.contains(r"\bNABH\b", case=False)])
nabh = pd.read_parquet(E + "nabh_accredited/nabh_vf_match.parquet")
nb = set(nabh.unique_id) & OK
print("NABH claim", len(nabh_claim), "only", len(nabh_claim - nb), wil(len(nabh_claim - nb), len(nabh_claim)), "both", len(nabh_claim & nb),
      "list only", len(nb - nabh_claim), "list rows", nabh.nabh_id.nunique())
print("  raw-text NABH mention", len(nabh_txt), "of which matched", len(nabh_txt & nb), "list-only vs raw text", len(nb - nabh_txt))
print("  'both' status", nabh[nabh.unique_id.isin(nabh_claim & nb)].drop_duplicates("unique_id").status.value_counts().to_dict())
# types of list-only matched records
ty = pd.read_parquet(R + "model/proto/evidence/pair_features.parquet", columns=["unique_id", "facility_type"]).drop_duplicates("unique_id").set_index("unique_id").facility_type
print("  list-only by type", pd.Series([ty[u] for u in nb - nabh_claim]).value_counts().to_dict())
erk = pd.read_parquet(E + "eraktkosh_blood_centres/erk_vf_matches.parquet")
eb = set(erk.unique_id) & OK; bc = claim(["blood_bank"])
print("ERK claim", len(bc), "only", len(bc - eb), "both", len(bc & eb), "list only", len(eb - bc), "matched centres", len(erk))
lq = pd.read_parquet(E + "laqshya_master/laqshya_vf_matches.parquet"); lqf = pd.read_parquet(E + "laqshya_master/laqshya_facilities.parquet")
mot = set(lqf.lq_id[lqf["Maternity OT"].notna()])
lqs = {u for u, i in zip(lq.unique_id, lq.lq_id) if i in mot} & public
cs = claim(["emergency_csection"]) & public
print("LQ MOT list", len(mot), "claim", len(cs), "only", len(cs - lqs), "both", len(cs & lqs), "list only", len(lqs - cs),
      "matched MOT entries", len(set(lq.lq_id) & mot))
tcf = pd.read_csv(E + "mohfw_trauma_196/tcf_vf_matches.csv")
ts = set(tcf.vf_id) & public; tc = claim(["trauma_care", "emergency_24x7"]) & public
print("TCF claim", len(tc), "only", len(tc - ts), "both", len(tc & ts), "list only", len(ts - tc), "matched", tcf.sno.nunique(),
      "matches >50 km", (tcf.km_tcf_to_vf > 50).sum())
# PMNDP
p = pd.read_csv(E + "pmndp_counts_and_state_lists/pmndp_state_counts.csv")
loc = pd.read_parquet(R + "derived/v1/facility_location.parquet", columns=["unique_id", "state_final"])
d = claim(["dialysis"])
loc = loc.assign(st=loc.state_final.str.lower(), dial=loc.unique_id.isin(d), pub=loc.unique_id.isin(public))
g = loc[loc.dial & loc.pub].groupby("st").size()
print("PMNDP total", p.nhsrc_functional_centres.sum(), "public dialysis records", (loc.dial & loc.pub).sum(), "public", loc.pub.sum(),
      "any dialysis", loc.dial.sum())
for s in ["bihar", "uttar pradesh", "gujarat"]:
    print(" ", s, g.get(s, 0), int(p.nhsrc_functional_centres[p.state_key == s].iloc[0]))
print("states in pmndp not matched in loc:", sorted(set(p.state_key) - set(loc.st)))
