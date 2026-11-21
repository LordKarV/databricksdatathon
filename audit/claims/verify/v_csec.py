"""C-section field spread: how many facilities mention it ONLY in procedure (finding says 439 of 462)."""
import pandas as pd
g = pd.read_parquet("../out/grades.parquet")
c = g[(g.service == "csection") & (g.n_core > 0)]
print({"facilities": len(c), "any_procedure": int(c.fields.str.contains("procedure").sum()),
       "only_procedure": int((c.fields == "procedure").sum()), "two_plus_fields": int((c.n_fields >= 2).sum()),
       "strong_if_2field_rule_dropped_and_all_prereqs": int(((c.prereq_frac == 1) & (c.n_specific >= 1) & ~c.scope_conflict & (c.n_own > 0)).sum())})
