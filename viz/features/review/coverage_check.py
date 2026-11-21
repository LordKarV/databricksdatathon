"""Coverage / denominator checks for FEATURES.md claims. Reads out/features_pairs.parquet plus raw inputs.
Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python viz/features/review/coverage_check.py"""
import json
from pathlib import Path
import pandas as pd

R = Path("/Users/karthikvattem/projects/datathon")
f = pd.read_parquet(R / "viz/features/out/features_pairs.parquet")
n = len(f)
cov = lambda c: round(float(f[c].notna().mean()), 4)
nz = lambda c: round(float((f[c].fillna(0) != 0).mean()), 4)
out = {"pairs": n, "facilities": int(f.unique_id.nunique())}
for c in ["e_web_service", "e_has_website", "e_site_alive", "g_log_beds", "k_text_nabh", "a_prereq", "a_T",
          "d_nabh_service_code", "b_votes_against", "c_share_social", "c_n_urls", "g_n_specialties"]:
    out[c] = dict(coverage=cov(c), nonzero=nz(c))
# d_nabh_service_code: share of pairs where NABH can actually speak (facility has >= 1 fetched code)
four = f.d_nabh_service_code.notna()
out["d_nabh_service_code_pairs_with_code_known"] = [int((four & (f.d_nabh_code_known == 1)).sum()), int(four.sum())]
# 'fires on fewer than 1 in 1,000 pairs'
meta = __import__("sys").path.insert(0, str(R / "viz/features")) or __import__("catalogue_meta").META
feats = [c for c in f.columns if c in meta]
out["n_features"] = len(feats)
out["features_nonzero_below_0.001"] = sorted(c for c in feats if nz(c) < 0.001)
# chart 01 C-section split, own computation from the raw definition in charts.service_sources
cs = f[f.service == "emergency_csection"]
txt = cs.a_T >= 1
lists = (cs.d_nabh_service_code == 1) | (cs.d_nmc_course_strong == 1) | (cs.d_laqshya_ot_ever == 1)
ind = lists | (cs.e_web_service == 1) | (cs.f_osm_speciality_service == 1)
out["csection_indep_only"] = int((ind & ~txt).sum())
out["csection_indep_only_via_nabh_obg_only"] = int(((cs.d_nabh_service_code == 1) & ~txt & ~(cs.e_web_service == 1)
                                                    & ~(cs.d_nmc_course_strong == 1) & ~(cs.d_laqshya_ot_ever == 1)
                                                    & ~(cs.f_osm_speciality_service == 1)).sum())
out["csection_text_only"] = int((txt & ~ind).sum())
print(json.dumps(out, indent=1))
(Path(__file__).parent / "coverage_check.json").write_text(json.dumps(out, indent=1))
