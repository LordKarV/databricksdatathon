"""Hand-check samples (seed 7). `python handcheck.py dump` prints items to label; labels live in
handcheck_labels.csv (sample,item,label,note); `python handcheck.py score` counts them into out/handcheck.json."""
import json, os, sys
import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
MERGE = "/Users/karthikvattem/projects/datathon/audit/merge/out"
SEED = 7


def samples():
    c = pd.read_parquet(f"{OUT}/claims.parquet")
    g = pd.read_parquet(f"{OUT}/grades.parquet")
    names = g.drop_duplicates("unique_id").set_index("unique_id")[["name", "facilityTypeId"]]
    rs = pd.read_parquet(f"{MERGE}/record_scores.parquet", columns=["unique_id", "n_q", "address_city"]).set_index("unique_id")
    sv = c[(c.services != "") & ~c.dup_in_record].join(names, on="unique_id").join(rs, on="unique_id")
    out = {
        "A_other_facility": sv[sv.attribution == "other_facility"].sample(25, random_state=SEED),
        "B_ambiguous": sv[sv.attribution == "ambiguous"].sample(15, random_state=SEED),
        "C_unanchored_in_contaminated_record": sv[(sv.attribution == "unanchored") & (sv.n_q > 0) & ~sv.nonoffer].sample(20, random_state=SEED),
        "D_nonoffer": sv[sv.nonoffer].sample(15, random_state=SEED),
    }
    st = g[g.grade == "strong"].groupby("service").sample(3, random_state=SEED)
    out["E_v2_strong"] = st.join(rs, on="unique_id")
    return out


def dump():
    for k, df in samples().items():
        print(f"\n######## {k}")
        for i, r in enumerate(df.itertuples(), 1):
            if k == "E_v2_strong":
                ev = " || ".join(e["text"][:140] for e in json.loads(r.cite_evidence))
                print(f"{i}. [{r.service}] {r.name} ({r.facilityTypeId}, {r.address_city}) corr={r.corr_prereqs},{r.corr_quantity},{r.corr_self_anchored} pre={r.cite_prereqs[:160]}\n   EV: {ev}")
            else:
                print(f"{i}. [{r.services}] {r.name} ({r.facilityTypeId}, {r.address_city}) {r.field}: {r.text[:260]}\n   foreign={r.foreign_names} sib={r.sibling_names} self={r.self_names} ctx={r.context} os={r.places_other_state} od={r.places_other_district}")


def score():
    lab = pd.read_csv(os.path.join(D, "handcheck_labels.csv"))
    res = {k: g.label.value_counts().to_dict() | {"n": len(g)} for k, g in lab.groupby("sample")}
    json.dump(res, open(f"{OUT}/handcheck.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    dump() if sys.argv[1:] == ["dump"] else score()
