"""Draw my own random sample of finder grades (seed 11): v_sample.py GRADE N. Prints uid, service, grade."""
import sys
import pandas as pd
g = pd.read_parquet("../out/grades.parquet")
s = g[g.grade == sys.argv[1]].sample(int(sys.argv[2]), random_state=11)
for r in s.itertuples(): print(r.unique_id[:8], r.service, r.grade, r.name, "| fields", r.fields, "qty", r.has_qty, "pre", round(r.prereq_frac, 2))
