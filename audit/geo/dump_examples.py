"""Dump full text for hand-judged samples into hand_check_*.txt (read by a human; verdicts in hand_check_verdicts.csv)."""
import json
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from geo_common import GEO, load_facilities

f = load_facilities().set_index("unique_id")
g = pd.read_parquet(GEO / "facility_geo.parquet")


def dump(rows, path):
    out = []
    for _, r in rows.iterrows():
        x = f.loc[r.unique_id]
        urls = json.loads(x.source_urls) if x.source_urls and x.source_urls.startswith("[") else []
        out.append(f"=== {r.unique_id} | {x['name']}\n addr: {x.address_line1} | {x.address_line2} | {x.address_line3}\n"
                   f" city={x.address_city} state={x.address_stateOrRegion} zip={x.address_zipOrPostcode} lat,lon={x.latitude:.4f},{x.longitude:.4f}\n"
                   f" PIN->{r.pin_state}/{r.pin_district}  coords->{r.near_state}/{r.near_district} (near {r.near_km:.1f} km)  d_pin={r.d_pin_km:.0f} km  verdict={r.state_verdict} city_match_pin={r.city_match_pin} city_match_near={r.city_match_near}\n"
                   f" desc: {str(x.description)[:500]}\n urls: {urls[:4]}\n phones: {x.phone_numbers}\n")
    (GEO / path).write_text("\n".join(out))


if __name__ == "__main__":
    # the samples were drawn at random (sample(n, random_state)) during the audit; the judged ids are
    # frozen in hand_check_verdicts.csv so the dump is reproducible even after the pipeline changes
    v = pd.read_csv(GEO / "hand_check_verdicts.csv")
    for name, grp in v.groupby("sample"):
        dump(g.set_index("unique_id").loc[grp.unique_id].reset_index(), f"hand_check_{name}.txt")
    print(v.groupby("sample").verdict.value_counts().to_string())
    print(v[["stated_state_ok", "pin_ok", "coords_ok"]].apply(lambda c: c.value_counts()).fillna(0).astype(int).to_string())
