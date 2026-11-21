"""Q4: assign every facility a district and join it to NFHS-5.

District rule (first that applies; the hand checks showed PIN beats coordinates when they disagree):
  1 pin           PIN in directory, coords within 50 km of the PIN point (or no usable coords)
  2 pin_conflict  PIN in directory but coords > 50 km away: keep the PIN district unless the city
                  matches the coordinate district and not the PIN district (then 'coords_city')
  3 coords        no directory PIN: district of the nearest PIN centroid if within 25 km
  4 none
NFHS join: directory district -> NFHS district by normalised name within state (+ aliases, fuzzy
>= 88). Directory districts created after NFHS-5 fall back to the majority NFHS district of the 10
nearest matched PIN centroids in the same state ('spatial_parent', approximate).
Writes facility_district.parquet, district_nfhs_map.csv, district_assign_stats.json.
"""
import json
import sys

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from geo_common import GEO, NFHS, nearest, norm

NFHS_STATE = {"MAHARASTRA": "MAHARASHTRA", "JAMMU AND KASHMIR": "JAMMU AND KASHMIR", "NCT OF DELHI": "DELHI",
              "ANDAMAN AND NICOBAR ISLANDS": "ANDAMAN AND NICOBAR ISLANDS",
              "DADRA AND NAGAR HAVELI AND DAMAN AND DIU": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"}
# directory name -> NFHS name (both normalised) where spelling differs beyond fuzzy reach
DIST_ALIAS = {"bengaluru urban": "bangalore", "bengaluru rural": "bangalore rural", "mysuru": "mysore",
              "belagavi": "belgaum", "kalaburagi": "gulbarga", "vijayapura": "bijapur", "shivamogga": "shimoga",
              "tumakuru": "tumkur", "ballari": "bellary", "chikkamagaluru": "chikmagalur",
              "prayagraj": "allahabad", "ayodhya": "faizabad", "gurugram": "gurgaon", "nuh": "mewat",
              "24 paraganas north": "north twenty four parganas", "24 paraganas south": "south twenty four parganas",
              "s a s nagar": "sahibzada ajit singh nagar", "spsr nellore": "sri potti sriramulu nello",
              "y s r": "y s r", "kanniyakumari": "kanniyakumari", "kamrup metro": "kamrup metropolitan",
              "hanumakonda": "warangal urban", "medchal malkajgiri": "medchal malkajgiri",
              "kancheepuram": "kancheepuram", "tiruvallur": "thiruvallur",
              "marigaon": "morigaon", "kabirdham": "kabeerdham", "kanker": "uttar bastar kanker", "korea": "koriya",
              "arvalli": "aravali", "chhotaudepur": "chhota udaipur", "dang": "the dangs", "budgam": "badgam",
              "poonch": "punch", "shopian": "shupiyan", "east singhbum": "purbi singhbhum",
              "west singhbhum": "pashchimi singhbhum", "koderma": "kodarma", "east nimar": "khandwa east nimar",
              "khargone": "khargone west nimar", "narsinghpur": "narsimhapur", "beed": "bid", "raigad": "raigarh",
              "boudh": "baudh", "deogarh": "debagarh", "sonepur": "subarnapur", "pondicherry": "puducherry",
              "sri muktsar sahib": "muktsar", "chittorgarh": "chittaurgarh", "dholpur": "dhaulpur",
              "kanchipuram": "kancheepuram", "tuticorin": "thoothukkudi", "warangal": "warangal rural",
              "coochbehar": "koch bihar", "darjeeling": "darjiling", "dinajpur dakshin": "dakshin dinajpur",
              "dinajpur uttar": "uttar dinajpur", "hooghly": "hugli", "howrah": "haora",
              "medinipur east": "purba medinipur", "medinipur west": "paschim medinipur",
              "purba bardhaman": "purba barddhaman", "amroha": "jyotiba phule nagar",
              "bhadohi": "sant ravidas nagar bhadohi", "hathras": "mahamaya nagar", "kasganj": "kanshiram nagar",
              "pauri garhwal": "garhwal", "lakshadweep district": "lakshadweep"}


# districts created after NFHS-5 -> the NFHS district they were carved from (main parent).
# Hand-written from the state notifications; the kNN vote is only the last resort, it picked the
# wrong parent for 18 of 41 such districts during the audit (e.g. NTR -> guntur, should be krishna).
PARENT = {"alluri sitharama raju": "visakhapatnam", "anakapalli": "visakhapatnam", "annamayya": "y s r",
          "bapatla": "guntur", "eluru": "west godavari", "kakinada": "east godavari", "konaseema": "east godavari",
          "ntr": "krishna", "nandyal": "kurnool", "palnadu": "guntur", "parvathipuram manyam": "vizianagaram",
          "sri sathya sai": "anantapur", "tirupati": "chittoor", "lower siang": "west siang",
          "pakke kessang": "east kameng", "shi yomi": "west siang", "bajali": "barpeta",
          "gaurella pendra marwahi": "bilaspur", "vijaynagar": "bellary", "niwari": "tikamgarh",
          "jiribam": "imphal east", "kakching": "thoubal", "kangpokpi": "senapati", "noney": "tamenglong",
          "pherzawl": "churachandpur", "tengnoupal": "chandel", "hnahthial": "lunglei", "khawzawl": "champhai",
          "saiha": "chandel",  # NFHS table lists 'Chandel' under Mizoram where Saiha belongs
          "saitual": "aizawl", "malerkotla": "sangrur", "pakyong": "east district",
          "chengalpattu": "kancheepuram", "kallakurichi": "viluppuram", "mayiladuthurai": "nagapattinam",
          "ranipet": "vellore", "tenkasi": "tirunelveli", "tirupathur": "vellore", "mulugu": "jayashankar bhupalapally",
          "narayanpet": "mahabubnagar", "alipurduar": "jalpaiguri", "jhargram": "paschim medinipur",
          "kalimpong": "darjiling",
          "purba bardhaman": "paschim barddhaman"}  # NFHS table has no Purba Barddhaman row; sibling, approximate


def nfhs_table():
    n = pd.read_parquet(NFHS)[["district_name", "state_ut"]].copy()
    n["state"] = n.state_ut.map(norm).str.upper().map(lambda s: NFHS_STATE.get(s, s))
    n["dn"] = n.district_name.map(norm)
    return n


def match_districts(cen, n):
    pairs = cen.dropna(subset=["state", "district"]).groupby(["state", "district"]).size().rename("n_pins").reset_index()
    out = []
    for r in pairs.itertuples():
        cands = n[n.state == r.state]
        dn = norm(r.district)
        dn = DIST_ALIAS.get(dn, dn)
        hit, how = None, None
        if dn in set(cands.dn):
            hit, how = dn, "exact"
        elif len(cands):
            best = process.extractOne(dn, cands.dn.tolist(), scorer=fuzz.ratio)
            if best and best[1] >= 88:
                hit, how = best[0], "fuzzy"
        out.append((r.state, r.district, r.n_pins, hit, how))
    return pd.DataFrame(out, columns=["state", "district", "n_pins", "nfhs_dn", "how"])


def main():
    g = pd.read_parquet(GEO / "facility_geo.parquet")
    cen = pd.read_parquet(GEO / "pin_centroids.parquet")
    n = nfhs_table()
    st = {"facilities": len(g)}

    # ---- facility district
    coords_ok = ~g.coord_outside
    conflict = g.pin_in_dir & coords_ok & (g.d_pin_km > 50)
    use_coords = conflict & g.city_match_near & ~g.city_match_pin
    near_ok = coords_ok & (g.near_km <= 25)
    g["district_src"] = np.select(
        [g.pin_in_dir & ~conflict, conflict & ~use_coords, use_coords, ~g.pin_in_dir & near_ok],
        ["pin", "pin_conflict", "coords_city", "coords"], "none")
    g["district"] = np.select([g.district_src.isin(["pin", "pin_conflict"]), g.district_src.isin(["coords_city", "coords"])],
                              [g.pin_district, g.near_district], None)
    g["dstate"] = np.select([g.district_src.isin(["pin", "pin_conflict"]), g.district_src.isin(["coords_city", "coords"])],
                            [g.pin_state, g.near_state], None)
    g.loc[g.district.isna(), "district_src"] = "none"
    st["district_src"] = g.district_src.value_counts().to_dict()
    st["district_assigned"] = int(g.district.notna().sum())

    # ---- directory district -> NFHS
    m = match_districts(cen, n)
    st["directory_districts"] = len(m)
    st["directory_districts_matched_by_name"] = int(m.nfhs_dn.notna().sum())
    st["nfhs_districts"] = len(n)
    st["nfhs_districts_hit"] = int(m.dropna(subset=["nfhs_dn"]).drop_duplicates(["state", "nfhs_dn"]).shape[0])

    # spatial parent for unmatched districts: kNN vote among matched PIN centroids of the same state
    cm = cen.merge(m[["state", "district", "nfhs_dn"]], on=["state", "district"], how="left")
    cm = cm.dropna(subset=["best_lat"])
    parent = {}
    for (s, d), grp in cm[cm.nfhs_dn.isna() & cm.state.notna()].groupby(["state", "district"]):
        ref = cm[(cm.state == s) & cm.nfhs_dn.notna()].reset_index(drop=True)
        if ref.empty:
            continue
        votes = []
        for la, lo in zip(grp.best_lat, grp.best_lon):
            dd = (ref.best_lat - la) ** 2 + (ref.best_lon - lo) ** 2
            votes += ref.nfhs_dn.values[np.argsort(dd.values)[:10]].tolist()
        parent[(s, d)] = pd.Series(votes).mode().iloc[0]
    m["knn_parent_dn"] = [parent.get((s, d)) for s, d in zip(m.state, m.district)]
    m["table_parent_dn"] = m.district.map(norm).map(PARENT)
    m["final_dn"] = m.nfhs_dn.fillna(m.table_parent_dn).fillna(m.knn_parent_dn)
    m["how"] = m.how.fillna(pd.Series(np.select([m.table_parent_dn.notna(), m.knn_parent_dn.notna()],
                                                ["parent_table", "spatial_parent"], "unmatched"), index=m.index))
    tbl = m[m.table_parent_dn.notna() & m.knn_parent_dn.notna()]
    st["knn_parent_agrees_with_table"] = [int((tbl.knn_parent_dn == tbl.table_parent_dn).sum()), len(tbl)]
    m.to_csv(GEO / "district_nfhs_map.csv", index=False)
    st["directory_districts_by_how"] = m.how.value_counts().to_dict()
    st["unmatched_directory_districts"] = m[m.how == "unmatched"][["state", "district"]].astype(str).values.tolist()
    st["spatial_parent_rows"] = m[m.how == "spatial_parent"][["state", "district", "knn_parent_dn"]].astype(str).values.tolist()

    # ---- facility -> NFHS
    g = g.merge(m[["state", "district", "final_dn", "how"]].rename(columns={"state": "dstate", "how": "nfhs_how"}),
                on=["dstate", "district"], how="left")
    st["facility_nfhs_how"] = g.nfhs_how.fillna("no_district").value_counts().to_dict()
    st["facility_nfhs_joined"] = int(g.final_dn.notna().sum())
    g[["unique_id", "district", "dstate", "district_src", "final_dn", "nfhs_how"]].rename(
        columns={"final_dn": "nfhs_district_norm"}).to_parquet(GEO / "facility_district.parquet", index=False)
    (GEO / "district_assign_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps(st, indent=1, default=str))


if __name__ == "__main__":
    main()
