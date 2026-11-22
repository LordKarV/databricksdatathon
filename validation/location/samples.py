"""Draw the fixed-seed samples that the hand judgments in judgments/*.csv refer to. Re-running gives the same ids."""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import SEED, hav_km, loc, raw  # noqa: E402


def moved_sample(n=30):
    L = loc()
    d = hav_km(L.raw_lat, L.raw_lon, L.loc_lat, L.loc_lon)
    m = L[(d > 25) & L.raw_lat.notna()].assign(moved_km=d[(d > 25) & L.raw_lat.notna()])
    return m.sample(n, random_state=SEED).sort_values("unique_id"), len(m)


def district_sample(n=30):
    L = loc()
    return L[L.district.notna()].sample(n, random_state=SEED + 1).sort_values("unique_id")


def record_text(uid, n=300):
    r = raw().drop_duplicates("unique_id").set_index("unique_id").loc[uid]
    addr = " | ".join(str(x) for x in [r.address_line1, r.address_line2, r.address_line3, r.address_city,
                                        r.address_stateOrRegion, r.address_zipOrPostcode] if isinstance(x, str))
    return f"{r['name']} || {addr} || {str(r.description)[:n]}"


if __name__ == "__main__":
    which = sys.argv[1]
    pd.set_option("display.width", 250, "display.max_colwidth", 400)
    if which == "moved":
        s, tot = moved_sample()
        pr = pd.read_parquet("out/pip_raw.parquet").set_index("unique_id")
        pc = pd.read_parquet("out/pip_chosen.parquet").set_index("unique_id")
        print("population", tot)
        for r in s.itertuples():
            print(f"\n## {r.unique_id} moved {r.moved_km:.0f} km src={r.loc_src} conf={r.loc_conf}")
            print("  TEXT:", record_text(r.unique_id))
            print(f"  raw point in: {pr.dtname.get(r.unique_id)}, {pr.stname.get(r.unique_id)} | chosen in: {pc.dtname.get(r.unique_id)}, {pc.stname.get(r.unique_id)} | district={r.district}")
            print("  NOTE:", r.loc_note)
