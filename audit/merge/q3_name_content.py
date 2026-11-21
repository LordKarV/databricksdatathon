"""Q3: single-specialty facility names carrying out-of-scope high-acuity claims.

Name classes come from the facility name; service claims from procedure/equipment/capability/
description sentences. Out-of-scope = dialysis, cardiac surgery, NICU, trauma, C-section, burn care,
excluding organ-specific uses (ocular trauma, maxillofacial trauma, ...).
Writes handcheck/q3_sample.tsv (30 seeded hits) and prints counts.
Needs out/sentences_flagged.parquet and out/sentence_decisions.parquet.
"""
import re
import pandas as pd
import common

D = "/Users/karthikvattem/projects/datathon/audit/merge"
NAME_CLASS = {
    "eye": r"\b(eye|eyes|netra|nethra|netralaya|nethralaya|nayan|drishti|vision|ophthalm\w*|lasik|retina|cataract|optical)\b",
    "dental": r"\b(dental|dentist\w*|dentistry|teeth|tooth|smile|smiles|orthodont\w*|oral|implant centre|32)\b",
    "ent": r"\b(ent|ear|hearing|nose|throat|audiology|speech)\b",
    "ivf": r"\b(ivf|fertility|infertility|test tube|reproductive)\b",
    "skin": r"\b(skin|derma\w*|hair|cosmetic|aesthetic\w*|cosmetology|trichology)\b",
    "lab": r"\b(lab|labs|laboratory|laboratories|diagnostic|diagnostics|pathology|imaging|scan|scans|path lab)\b",
    "physio": r"\b(physio\w*|rehab\w*)\b",
}
MULTI = r"\b(multi|super|general|hospital and research|medical college|institute of medical|maternity|nursing home|& hospital|and hospital)\b"
SERVICE = {
    "dialysis": r"\b(dialysis|haemodialysis|hemodialysis)\b",
    "cardiac_surgery": r"\b(cardiac surgery|heart surgery|bypass surgery|cabg|open heart|valve replacement|cardiothoracic|ctvs)\b",
    "nicu": r"\b(nicu|neonatal intensive|neonatal icu)\b",
    "trauma": r"\b(trauma|polytrauma|accident)\b",
    "c_section": r"\b(c-section|caesarean|cesarean|c section|lscs)\b",
    "burn": r"\b(burns?)\b",
}
ORGAN_OK = re.compile(r"\b(ocular|eye|orbital|corneal|globe|dental|tooth|teeth|maxillofacial|facial|jaw|oral|mandib\w*|"
                      r"ear|nasal|nose|acoustic|hair|skin|scar|acid|chemical|sun|laser|insurance|policy|cover\w*)\b", re.I)


def main():
    df = common.load()
    s = pd.read_parquet(f"{D}/out/sentences_flagged.parquet")
    dec = pd.read_parquet(f"{D}/out/sentence_decisions.parquet")
    s = s.merge(dec, on=["unique_id", "field", "idx"])
    nm = df.set_index("unique_id").name.fillna("").str.lower()
    cls = {}
    for c, rx in NAME_CLASS.items():
        hit = nm.str.contains(rx.replace("(", "(?:"), regex=True) & ~nm.str.contains(MULTI.replace("(", "(?:"), regex=True)
        for u in hit[hit].index:
            cls.setdefault(u, c)  # first class wins
    cls = pd.Series(cls, name="name_class")
    print("single-specialty-named records:", cls.value_counts().to_dict(), "total", len(cls), "of", len(df))
    s = s[s.unique_id.isin(cls.index)].copy()
    s["name_class"] = s.unique_id.map(cls)
    rows = []
    for svc, rx in SERVICE.items():
        m = s.text.str.contains(rx.replace("(", "(?:"), case=False, regex=True) & ~s.text.map(lambda t: bool(ORGAN_OK.search(t)))
        if svc in ("c_section",):  # obstetric surgery is in scope for IVF centres
            m &= s.name_class != "ivf"
        for c, g in s[m].groupby("name_class"):
            rows.append((svc, c, g.unique_id.nunique(), len(g), int(g.quarantine.sum()),
                         int((g.has_foreign | g.has_sibling | g.has_other_state | g.has_other_district).sum())))
        s.loc[m, "svc_" + svc] = True
    t = pd.DataFrame(rows, columns=["service", "name_class", "records", "sentences", "sentences_quarantined", "sentences_any_flag"])
    print(t.to_string(index=False))
    hits = s[s.filter(like="svc_").fillna(False).any(axis=1)].copy()
    hits["services"] = hits.filter(like="svc_").fillna(False).apply(lambda r: ",".join(c[4:] for c, v in r.items() if v), axis=1)
    print("records with >=1 contradiction:", hits.unique_id.nunique(), "of", len(cls), "single-specialty-named records;",
          "sentences", len(hits))
    print("  of these sentences, already quarantined by Q5 policy:", int(hits.quarantine.sum()),
          "; carrying any merge flag:", int((hits.has_foreign | hits.has_sibling | hits.has_other_state | hits.has_other_district).sum()))
    rec_hits = hits.groupby("unique_id").agg(n=("text", "size"), cls=("name_class", "first"))
    print("  by name_class (records):", rec_hits.cls.value_counts().to_dict())
    smp = hits.sample(min(30, len(hits)), random_state=2026)
    smp.assign(rec_name=smp.unique_id.map(df.set_index("unique_id").name))[
        ["unique_id", "rec_name", "name_class", "services", "field", "quarantine", "has_foreign", "has_other_district", "text"]
    ].to_csv(f"{D}/handcheck/q3_sample.tsv", sep="\t", index=False)
    hits[["unique_id", "field", "idx", "name_class", "services", "text"]].to_parquet(f"{D}/out/q3_hits.parquet")


if __name__ == "__main__":
    main()
