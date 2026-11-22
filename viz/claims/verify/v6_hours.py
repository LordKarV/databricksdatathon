"""Independent recomputation of story 6 (hours evidence by source)."""
import pandas as pd
from vcommon import R, OK, wil

W = R + "kb/web_evidence/out/"
si = pd.read_parquet(W + "site_identity.parquet")
sites = set(si.unique_id[si.attributable & si.kind.isin(["site", "branch"])]) & OK


def sets(d):
    d = d[(d.n_usable > 0) & d.unique_id.isin(OK)]
    a24 = d[(d.fact_type == "hours_24x7") & ~d.attribute.isin(["helpline", "home_care"])]
    sch = d[d.fact_type.isin(["opd_hours", "hours_dialysis_shifts"]) & ~d.attribute.isin(["helpline", "visiting"])]
    e = set(a24.unique_id[a24.attribute == "emergency"])
    return dict(any24=set(a24.unique_id), emerg24=e, schedule=set(sch.unique_id), any_hours=set(a24.unique_id) | set(sch.unique_id))


ds = sets(pd.read_parquet(R + "kb/vf_details/out/facility_details.parquet"))
wd = pd.read_parquet(W + "web_facility_details.parquet")
print("web facts on records without an attributable own site:", (~wd.unique_id.isin(sites)).sum(), "of", len(wd))
wb = sets(wd)
o = pd.read_parquet(R + "kb/opendata/vf_opendata_facts.parquet")
o = o[(o.source == "osm") & o.unique_id.isin(OK)]
t24 = set(o.unique_id[(o.field == "is_24x7") & (o.value == "True")])
sch = set(o.unique_id[((o.field == "is_24x7") & (o.value == "False")) | (o.field == "opening_hours_unparsed")])
osm = dict(any24=t24, emerg24=set(o.unique_id[(o.field == "emergency") & (o.value == "yes")]), schedule=sch, any_hours=t24 | sch)
N = len(OK)
for m in ["any_hours", "any24", "emerg24", "schedule"]:
    a = ds[m] | wb[m] | osm[m]
    print(m, "dataset", len(ds[m]), "web", len(wb[m]), "osm", len(osm[m]), "any", len(a), wil(len(a), N),
          "| web among sites", wil(len(wb[m]), len(sites)))
print("no hours evidence", N - len(ds["any_hours"] | wb["any_hours"] | osm["any_hours"]), "of", N)
print("dataset schedule", wil(len(ds["schedule"]), N), "web schedule", wil(len(wb["schedule"]), N))
d, w = ds["emerg24"] & sites, wb["emerg24"] & sites
print("sites", len(sites), "both", len(d & w), "dataset only", len(d - w), "web only", len(w - d), "union", len(d | w),
      "agreement among union", wil(len(d & w), len(d | w)))
# what does the 'A 24x7 statement' row include?
v = pd.read_parquet(R + "kb/vf_details/out/facility_details.parquet")
v = v[(v.n_usable > 0) & (v.fact_type == "hours_24x7") & v.unique_id.isin(OK)]
only_nonfac = set(v.unique_id) - set(v.unique_id[v.attribute.isin(["facility", "emergency"])]) - set(v.unique_id[v.attribute.isin(["helpline","home_care"])])
print("dataset 24x7 records whose only 24x7 scope is a unit (pharmacy, ambulance, lab...):", len(only_nonfac & ds["any24"]))
# clock-time records with ALL days? (schedule) not checked: values are free text
