"""Print 12 random 'strong' grades (seed 23) with record identity and their mention sentences, for my own precision read."""
import pandas as pd
from v_common import load
g = pd.read_parquet("../out/grades.parquet"); m = pd.read_parquet("../out/mentions.parquet")
df = load().drop_duplicates("unique_id").set_index("unique_id")
s = g[g.grade == "strong"].drop_duplicates(["unique_id", "service"]).sample(12, random_state=23)
for r in s.itertuples():
    x = df.loc[r.unique_id]
    pre = {c[4:]: getattr(r, c) for c in g.columns if c.startswith("pre_") and pd.notna(getattr(r, c))}
    print(f"## {r.unique_id[:8]} {r.service} | {x['name']} | {x.address_city} | type={x.facilityTypeId} cap={x.capacity} | fields={r.fields} qty={r.has_qty} pre={pre}")
    for y in m[(m.unique_id == r.unique_id) & (m.service == r.service)].drop_duplicates("sentence").head(5).itertuples():
        print(f"     [{y.field[:4]}] {y.sentence[:150]}")
