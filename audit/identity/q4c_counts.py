"""Q4c: exact numerator/denominator for the headline existence-signal comparisons."""
import pandas as pd
from common import OUT
E = pd.read_csv(OUT + "existence_signals.csv", dtype={"officialPhone": str})
E["has_web"] = E.officialWebsite.notna()
E["has_phone"] = E.officialPhone.notna()
for g in ["has_web", "has_phone"]:
    for a in ["a_pin_far", "a_pin_state", "a_foreign", "any_anom"]:
        t = E[E[a].notna()].groupby(g)[a].agg(["sum", "count"])
        print(g, a, {bool(k): f"{int(v['sum'])}/{int(v['count'])} ({v['sum'] / v['count']:.1%})" for k, v in t.iterrows()})
print("neither website nor phone:", int((~E.has_web & ~E.has_phone).sum()), "| both:", int((E.has_web & E.has_phone).sum()))
