"""Independent service-mention detector (my own regexes, written without the finder's lists) and a
comparison of facility sets against the finder's out/grades.parquet. Writes out/v_mentions.parquet, out/v_mentions.json."""
import json, re
import pandas as pd
from v_common import load

I = re.I
MINE = {
    "dialysis": (r"dialys|dialyz|haemodial|hemodial|\bcapd\b|\bcrrt\b|renal replacement", r"fistula|dialysis profile|without dialysis"),
    "csection_strict": (r"caesar|cesar|c[- ]?section|\blscs\b", r"after (c|caes|ces)\w*[- ]?section|\bvbac\b|scar"),
    "nicu": (r"\bnicu|\bniccu|\bsncu|neonatal (intensive|icu|critical)|newborn intensive|special newborn care", r"ambulance"),
    "cardiac_surgery": (r"\bcabg\b|coronary artery bypass|open[- ]heart|cardiac surg|heart surg|cardio[- ]?thoracic|\bctvs\b|\bcvts\b|valve (replacement|repair)|heart transplant",
                        r"transcatheter|\btavi|\btavr|an(a)?esthe|radiolog|imaging|non[- ]surgical|without surgery"),
    "mri": (r"\bmri\b|\bmris\b|magnetic resonance|\bmra\b", r"mri[- ](compatible|guided|safe)"),
    "burns": (r"\bburns?\b", r"heart ?burn|sun ?burn|burn ?out|burning|\bfat\b|calorie"),
    "trauma_explicit": (r"trauma|casualty|accident", r"atraumatic|dental|tooth|teeth|\beye\b|ophthal|psycholog|emotional|ptsd|childhood trauma|trauma[- ]informed|maxillofacial|facial trauma"),
    "emergency_any": (r"emergenc|\bcasualty|trauma", r"dental|dentist|tooth|teeth|\beye\b|ophthal|psychiatr|veterinar|contracept"),
    "icu": (r"\bicus?\b|intensive care|critical care|\bmicu\b|\bsicu\b|\biccu\b|\bccu\b|\bhdu\b|high dependency", r"ambulance|transport"),
}
STRIP_ICU = re.compile(r"neonatal intensive care|p(a)?ediatric intensive care|newborn intensive care|neonatal icu|p(a)?ediatric icu|\bpicu\b|\bnicu\b", I)
CX = {k: (re.compile(a, I), re.compile(b, I)) for k, (a, b) in MINE.items()}


def sents(r):
    for f in ["procedure", "equipment", "capability"]:
        for s in r[f]:
            yield f, s
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", r["description"]):
        if s.strip():
            yield "description", s.strip()


if __name__ == "__main__":
    df = load()
    rows = []
    for r in df.to_dict("records"):
        for f, s in sents(r):
            for k, (c, x) in CX.items():
                t = STRIP_ICU.sub(" ", s) if k == "icu" else s
                if c.search(t) and not x.search(t):
                    rows.append((r["unique_id"], k, f, s))
    m = pd.DataFrame(rows, columns=["unique_id", "service", "field", "sentence"])
    m.to_parquet("out/v_mentions.parquet")
    g = pd.read_parquet("../out/grades.parquet")
    fm = pd.read_parquet("../out/mentions.parquet")
    res = {}
    pairs = {"dialysis": "dialysis", "csection_strict": "csection", "nicu": "nicu", "cardiac_surgery": "cardiac_surgery",
             "mri": "mri", "burns": "burns", "trauma_explicit": "trauma", "emergency_any": "trauma", "icu": "icu"}
    for k, fs in pairs.items():
        mine = set(m[m.service == k].unique_id)
        theirs = set(g[(g.service == fs) & (g.n_core > 0)].unique_id)
        res[k] = dict(mine=len(mine), theirs=len(theirs), both=len(mine & theirs), only_mine=len(mine - theirs),
                      only_theirs=len(theirs - mine), sentences_mine=int((m.service == k).sum()),
                      sentences_theirs=int((fm.service == fs).sum()))
    res["total_sentences_theirs"] = len(fm)
    res["total_distinct_sentence_rows_theirs"] = int(fm.drop_duplicates(["unique_id", "field", "sentence"]).shape[0])
    json.dump(res, open("out/v_mentions.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
