"""Ground-truth evaluation of the grader (36 web-checked pairs; 22 with a confirmed/contradicted verdict).

Compares: the sample's own strata (build_sample.py rule), the earlier audit grader (audit/claims/out/grades.parquet),
grader v1 (rules frozen before reading the web verdicts), v2 (post-hoc fixes), and each with quarantine off.
Writes out/eval.json and out/eval_pairs.csv.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python evaluate.py
"""
import json, math, os
import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
_ROOT = os.environ.get("DATATHON_ROOT", os.path.abspath(os.path.join(D, "../..")))
GT = os.path.join(_ROOT, "audit/ground_truth")
AUDIT = os.path.join(_ROOT, "audit/claims/out/grades.parquet")
SVC = {"emergency_csection": "csection", "trauma_emergency": "trauma"}
POS = {"strong", "moderate", "medium"}  # recommendable grades (audit grader used 'medium')


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 2), round((c + h) / d, 2)]


def pr(df, col, positive):
    v = df[df.verdict.isin(["confirmed", "contradicted"])]
    pos = v[v[col].isin(positive)]
    tp = int((pos.verdict == "confirmed").sum())
    conf = int((v.verdict == "confirmed").sum())
    return dict(predicted_positive=len(pos), true_positive=tp, precision=round(tp / len(pos), 3) if len(pos) else None,
                precision_ci95=wilson(tp, len(pos)), confirmed=conf, recall=round(tp / conf, 3), recall_ci95=wilson(tp, conf),
                contradicted_predicted_positive=int((pos.verdict == "contradicted").sum()))


def table(df, col):
    v = df[df.verdict.isin(["confirmed", "contradicted", "no_info"])]
    return pd.crosstab(v[col].fillna("no_mention"), v.verdict).to_dict(orient="index")


def main():
    s = pd.DataFrame(json.load(open(f"{GT}/sample.json")))
    w = pd.concat([pd.DataFrame(json.load(open(f"{GT}/web_{i}.json"))["results"]) for i in (1, 2, 3)])
    x = s.merge(w[["pair_id", "exists", "location_matches", "service", "confidence", "notes"]].rename(columns={"service": "verdict"}), on="pair_id")
    x["svc"] = x.service.replace(SVC)
    a = pd.read_parquet(AUDIT)[["unique_id", "service", "grade"]].drop_duplicates(["unique_id", "service"])
    x = x.merge(a.rename(columns={"service": "svc", "grade": "audit_grade"}), on=["unique_id", "svc"], how="left")
    for name in ["grades_v1", "grades_v1_noquarantine", "grades", "grades_noquarantine"]:
        g = pd.read_parquet(f"{OUT}/{name}.parquet")
        cols = ["grade", "rule", "risks"] if name in ("grades_v1", "grades") else ["grade"]
        g = g[["unique_id", "service"] + cols].rename(columns={"service": "svc", **{c: f"{c}_{name}" for c in cols}})
        x = x.merge(g, on=["unique_id", "svc"], how="left")
    x["stratum_pos"] = x.stratum.map({"strong": "strong", "weak": "weak", "suspect": "suspect"})
    res = {"pairs": len(x), "verdicts": x.verdict.value_counts().to_dict(),
           "usable_pairs_confirmed_or_contradicted": int(x.verdict.isin(["confirmed", "contradicted"]).sum())}
    graders = {"sample_stratum": "stratum_pos", "audit_grader": "audit_grade", "v1": "grade_grades_v1",
               "v1_no_quarantine": "grade_grades_v1_noquarantine", "v2": "grade_grades", "v2_no_quarantine": "grade_grades_noquarantine"}
    res["grade_by_verdict"] = {k: table(x, c) for k, c in graders.items()}
    res["recommendable_strong_or_moderate"] = {k: pr(x, c, POS) for k, c in graders.items() if k != "sample_stratum"}
    res["strong_only"] = {k: pr(x, c, {"strong"}) for k, c in graders.items()}
    # quarantine ablation: which pairs change grade when 'names another facility' sentences count as own
    for v, a_, b_ in [("v1", "grade_grades_v1", "grade_grades_v1_noquarantine"), ("v2", "grade_grades", "grade_grades_noquarantine")]:
        ch = x[x[a_].fillna("none") != x[b_].fillna("none")]
        res[f"quarantine_changes_{v}"] = ch[["pair_id", "verdict", b_, a_]].rename(columns={b_: "without_quarantine", a_: "with_quarantine"}).to_dict("records")
    # location risk flag vs the web's location verdict
    lm = x[x.location_matches.isin(["yes", "no"])]
    flag = lm.risks_grades.fillna("").str.contains("location")
    res["location_flag_vs_web"] = {"web_no": int((lm.location_matches == "no").sum()), "web_no_flagged": int((flag & (lm.location_matches == "no")).sum()),
                                   "web_yes": int((lm.location_matches == "yes").sum()), "web_yes_flagged": int((flag & (lm.location_matches == "yes")).sum())}
    x.drop(columns=["claim_quotes"]).to_csv(f"{OUT}/eval_pairs.csv", index=False)
    json.dump(res, open(f"{OUT}/eval.json", "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
