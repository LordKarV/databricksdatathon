"""Hand-check labels (read by a human, recorded here) and the precision they imply.
Labels refer to the frozen sample files in out/ (handcheck_core.tsv, handcheck_nonoffer.tsv, handcheck2_nonoffer.tsv,
handcheck_foreign.tsv, handcheck2_foreign.tsv, handcheck3_named.tsv, grade_examples.json).
Run: .venv/bin/python labels.py   (prints precision, and the CURRENT grade of each grade-sample record)"""
import json
import pandas as pd

# Round 1, core mention detector: is the sentence about the target service at all? (25 per service, seed 42)
CORE_FP = {"burns": [11578, 12504], "icu": [1126], "trauma": [19465]}  # all other sampled rows judged on-topic
CORE_NOTES = {11578: "'no burns and no scars' (VenaSeal)", 12504: "burn scar cosmetic treatment, not burn care",
              1126: "paediatric critical care fellowship, not adult ICU", 19465: "'atraumatic' extraction, dental"}
# Round 1, non-offer cues v1 (8 per service, seed 42): 1 = sentence really is not an on-site, current offer
NONOFFER_V1 = dict(burns=[0, 0, 0, 0, 1, 0, 0, 0], cardiac_surgery=[1, 0, 1, 1, 0, 0, 0, 0], csection=[0, 1, 1, 0],
                   dialysis=[1, 0, 1, 0, 0, 1, 0, 0], icu=[0, 0, 0, 0, 0, 0, 0, 1], mri=[1, 1, 1, 0, 0, 0, 0, 1],
                   nicu=[0] * 8, trauma=[0, 1, 1, 0, 1, 0, 0, 0])
# Round 2, non-offer cues v2 (40 distinct sentences, seed 7): row indices judged WRONG
NONOFFER_V2_WRONG = {6335: "blood donation camp", 3876: "HDU until transfer to ICU", 24648: "'used to measure'",
                     20585: "'Upcoming Services' list item", 7017: "referral to a senior doctor", 11495: "epilepsy camps"}
NONOFFER_V2_N = 40
# Named-other-facility detector. Round 1 (token_set_ratio < 70), 40 rows seed 42: really another facility's claim
NAMED_V1_TRUE, NAMED_V1_N = 3, 40       # KCGMC referral (e5cd0285), Aadhar Madanapalle (66d812eb), Shivaleela Hubli (91b1e99f)
# Round 3 (distinctive-token rule), 40 rows seed 3
NAMED_V3_TRUE = [16818, 4501, 12946, 16424, 2684, 22655, 3006, 10122, 8293]
NAMED_V3_N = 40
# Cross-state place flag. Round A (no locative rule): 9 of 40 truly other-facility, 5 of them for the right reason.
PLACE_A = dict(true=9, right_reason=5, n=40)
# Round B (locative rule): whole population of 14 flagged sentences reviewed
PLACE_B_TRUE = [11053, 7195, 7184, 19846, 25427, 11051, 11066, 4138]
PLACE_B_N = 14
# Grade sample (grade_examples.json, 72 records = 3 per service x grade): judged grade vs the grader's grade
GRADE_TOO_HIGH = {5: "two fields restate one sentence, no nephrology", 9: "SNCU is at the District Women's Hospital",
                  10: "only generic 'NICU' list mentions", 13: "sentence names 'SSD Hospital', record is 'SMS Hospital'",
                  47: "extractor hedge 'MRI scanner (if applicable)'"}
GRADE_TOO_LOW = {15: "'Child Care and Dental' capped by scope rule", 51: "diagnostic centre with full MRI menu",
                 69: "skin bank for burn treatment"}

if __name__ == "__main__":
    out = {}
    out["core_topic_precision"] = {s: f"{25 - len(CORE_FP.get(s, []))}/25" for s in
                                   ["dialysis", "csection", "nicu", "cardiac_surgery", "mri", "burns", "trauma", "icu"]}
    out["core_topic_precision_all"] = f"{200 - sum(map(len, CORE_FP.values()))}/200"
    v1 = sum(map(sum, NONOFFER_V1.values())), sum(map(len, NONOFFER_V1.values()))
    out["nonoffer_v1_precision"] = f"{v1[0]}/{v1[1]}"
    out["nonoffer_v2_precision"] = f"{NONOFFER_V2_N - len(NONOFFER_V2_WRONG)}/{NONOFFER_V2_N}"
    out["named_other_v1_precision"] = f"{NAMED_V1_TRUE}/{NAMED_V1_N}"
    out["named_other_v3_precision"] = f"{len(NAMED_V3_TRUE)}/{NAMED_V3_N}"
    out["cross_state_place_A"] = PLACE_A
    out["cross_state_place_B_precision"] = f"{len(PLACE_B_TRUE)}/{PLACE_B_N}"
    out["grade_agreement"] = f"{72 - len(GRADE_TOO_HIGH) - len(GRADE_TOO_LOW)}/72"
    print(json.dumps(out, indent=1))
    ex = json.load(open("out/grade_examples.json"))
    g = pd.read_parquet("out/grades.parquet")
    cur = dict(zip(zip(g.unique_id, g.service), g.grade))
    changed = [(i, e["unique_id"][:8], e["service"], e["grade"], cur.get((e["unique_id"], e["service"]), "no_mention"))
               for i, e in enumerate(ex) if cur.get((e["unique_id"], e["service"]), "no_mention") != e["grade"]]
    print("grade-sample records whose grade changed after the final fixes:", changed)
    json.dump(dict(out, changed_after_fixes=changed), open("out/handcheck_summary.json", "w"), indent=1)
