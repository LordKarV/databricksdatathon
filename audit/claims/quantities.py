"""Quantities inside service sentences: machine counts, unit bed counts, MRI field strength, CT slices.
Checks unit size against the record's total capacity. Writes out/quantities.json and out/quantity_rows.parquet."""
import json, re
import pandas as pd

m = pd.read_parquet("out/mentions.parquet")
g = pd.read_parquet("out/grades.parquet")[["unique_id", "beds"]].drop_duplicates("unique_id")
m = m[~m.nonoffer].merge(g, on="unique_id", how="left")

# 1-3 digits, not part of "24/7", "24x7", a year or a model number ("Fresenius 4008S", "Sundial 55", "Toray 8000")
NUM = r"(?<![\w/×.])(?<!sundial )(?<!toray )(?<!fresenius )(\d{1,3})(?![\d/x×])"
PATS = {
    ("dialysis", "machines"): [rf"{NUM}\s*(?:\w+\s){{0,3}}(?:haemo|hemo)?dialy\w*\s*(?:machines?|units?|stations?|chairs?)",
                               rf"dialy\w*\s*machines?\s*[:=-]?\s*{NUM}\b", rf"{NUM}\s*machines?"],
    ("dialysis", "beds"): [rf"{NUM}\s*-?\s*bed(?:ded|s)?\s*(?:\w+\s){{0,2}}(?:haemo|hemo)?dialy", rf"dialy\w*\s*(?:unit|centre|center|ward)?\s*(?:with|of|has)?\s*{NUM}\s*-?\s*beds?"],
    ("nicu", "beds"): [rf"{NUM}\s*-?\s*bed(?:ded|s)?\s*(?:[a-z]+\s)?(?:NICU|neonatal|SNCU|newborn)", rf"(?:NICU|SNCU|neonatal \w+ unit)\s*(?:with|of|has)\s*{NUM}\s*-?\s*(?:beds?|cots?)"],
    ("icu", "beds"): [rf"{NUM}\s*-?\s*bed(?:ded|s)?\s*(?:[a-z]+\s)?(?:ICU|intensive|critical|CCU|ICCU|MICU|SICU|HDU)",
                      rf"(?:ICU|intensive care unit|critical care unit|ICCU|CCU)\s*(?:beds?)?\s*(?:with|of|has|:)?\s*{NUM}\s*-?\s*beds?"],
    ("burns", "beds"): [rf"{NUM}\s*-?\s*bed(?:ded|s)?\s*(?:\w+\s){{0,2}}burns?", rf"burns?\s*(?:unit|ward|icu)\s*(?:with|of|has)\s*{NUM}\s*-?\s*beds?"],
    ("mri", "tesla"): [r"(\d(?:\.\d)?)\s*-?\s*T(?:esla)?\b"],
    ("trauma", "ct_slices"): [rf"{NUM}\s*-?\s*slices?"],
    ("csection", "deliveries"): [r"(\d[\d,]*)\+?\s*(?:deliveries|births|c-?sections|caesarean|cesarean)"],
    ("cardiac_surgery", "procedures"): [r"(\d[\d,]*)\+?\s*(?:open[- ]heart|cardiac surg|heart surg|CABG|bypass)"],
}
rows = []
for (svc, kind), pats in PATS.items():
    src = m if svc != "trauma" else m[m.service.isin(["trauma", "icu", "mri"])]  # CT sentences are not trauma-core
    if svc == "trauma":
        from common import load, TEXT_FIELDS
        df = load()
        lines = [(r.unique_id, s, r.beds) for r in df.itertuples() for f in TEXT_FIELDS for s in getattr(r, f + "_l")
                 if re.search(r"\bCT\b|computed tomograph", s)]
        it = lines
    else:
        it = [(r.unique_id, r.sentence, r.beds) for r in src[src.service == svc].itertuples()]
    for uid, s, beds in it:
        for p in pats:
            x = re.search(p, s, re.I)
            if x:
                v = float(x.group(1).replace(",", ""))
                rows.append(dict(unique_id=uid, service=svc, kind=kind, value=v, beds=beds, sentence=s))
                break
q = pd.DataFrame(rows).drop_duplicates(["unique_id", "service", "kind", "value"])
q.to_parquet("out/quantity_rows.parquet")
res = {}
for (svc, kind), grp in q.groupby(["service", "kind"]):
    d = dict(facilities=int(grp.unique_id.nunique()), rows=len(grp), median=float(grp.value.median()),
             p10=float(grp.value.quantile(.1)), p90=float(grp.value.quantile(.9)), max=float(grp.value.max()))
    if kind == "beds":
        known = grp[grp.beds > 0]
        d["with_total_capacity"] = int(known.unique_id.nunique())
        d["unit_beds_exceed_total_capacity"] = int(known[known.value > known.beds].unique_id.nunique())
        d["exceed_examples"] = known[known.value > known.beds][["unique_id", "value", "beds", "sentence"]].head(4).to_dict("records")
    if kind == "tesla":
        d["value_counts"] = {str(k): int(v) for k, v in grp.value.value_counts().items()}
        d["implausible_outside_0.2_to_7T"] = int(((grp.value < 0.2) | (grp.value > 7)).sum())
    if kind == "ct_slices":
        d["value_counts_top"] = {str(k): int(v) for k, v in grp.value.value_counts().head(10).items()}
    res[f"{svc}.{kind}"] = d
json.dump(res, open("out/quantities.json", "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str)[:6000])
