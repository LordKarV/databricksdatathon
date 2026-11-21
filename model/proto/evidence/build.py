"""Evidence-layer builder (MODEL_SPEC_v1 section 4). Writes, in this folder:

claim_atoms.parquet, pair_features.parquet, facility_features.parquet, lexicon_used.csv, FROZEN.json.
attribution_rates.csv is an input here (written by measure_sentences.py from the hand-labelled sentence set);
when it is absent the two score columns are null.

Run: /Users/karthikvattem/projects/datathon/.venv/bin/python build.py
"""
import datetime as dt
import json
import re
import shutil

import numpy as np
import pandas as pd

from atoms import claim_atoms_from_claims, echo_units, pair_families, prereq_counts, record_table, specialty_atoms
from common import GOLD_SERVICES, HERE, INPUTS, LEX, LEX_KEY, SVC_MAP, sha256_file
from facility import existence, leakage_groups, location_votes

LEVEL_RX = [  # public level from name patterns (spec 4.4); first match wins
    ("mc", r"medical college|\bAIIMS\b|institute of medical sciences|\bGMCH?\b|government medical"),
    ("dh", r"\b(district|dist\.?|zila|zilla|jilla)\b.{0,20}\bhospital|district (headquarters?|hq)|civil hospital|sadar hospital|\bDH\b"),
    ("sdh", r"sub[- ]?divisional|\bSDH\b|sub[- ]?district hospital|taluk[a]? (general )?hospital|tehsil hospital|rural hospital"),
    ("chc", r"community health (centre|center)|\bCHC\b"),
    ("phc", r"primary health (centre|center)|\bU?PHC\b|health (and|&) wellness"),
]
IPHS_DH_ESSENTIAL = {"dialysis", "emergency_csection"}   # IPHS 2022, DH level (spec 4.4)


def public_level(name: str) -> str:
    for lv, rx in LEVEL_RX:
        if re.search(rx, str(name or ""), re.I):
            return lv
    return "none"


def num(s):
    try:
        v = float(str(s).replace(",", ""))
        return v if np.isfinite(v) and v >= 0 else np.nan
    except ValueError:
        return np.nan


def bins(x: pd.Series, edges: list, labels: list) -> pd.Series:
    return pd.cut(x, edges, labels=labels, right=False).astype(str).replace("nan", "missing")


def context(rec: pd.DataFrame) -> pd.DataFrame:
    sp = pd.read_parquet(INPUTS["specialties"]).groupby("unique_id").size()
    c = pd.DataFrame({"unique_id": rec.unique_id, "name": rec.name})
    ft = rec.facilityTypeId.fillna("null")
    c["facility_type"] = np.where(ft.isin(["hospital", "clinic", "dentist"]), ft, "other")
    c["operator_public"] = rec.operatorTypeId.isin(["public", "government"])
    c["public_level"] = rec.name.map(public_level)
    beds, docs = rec.capacity.map(num), rec.numberDoctors.map(num)
    c["beds"], c["doctors"] = beds, docs
    c["beds_bin"] = bins(beds, [0, 30, 100, np.inf], ["<30", "30-99", "100+"])
    c["doctors_bin"] = bins(docs, [0, 5, 20, np.inf], ["<5", "5-19", "20+"])
    c["n_specialties"] = rec.unique_id.map(sp).fillna(0).astype(int)
    c["breadth_bin"] = bins(c.n_specialties, [0, 5, 20, np.inf], ["<5", "5-19", "20+"])
    c["scale_contradiction"] = (c.facility_type == "clinic") & (beds >= 100)
    c["ftype_raw"] = rec.facilityTypeId
    return c


def attach_scores(atoms: pd.DataFrame, rec: pd.DataFrame) -> pd.DataFrame:
    """attribution_score / support_score lookups (display and ordering only, never in a logit)."""
    p = HERE / "attribution_rates.csv"
    a = atoms.copy()
    b = a.unique_id.map(dict(zip(rec.unique_id, rec.bucket)))
    a["attr_class"] = np.where(a.ownership == "unanchored", "ownership:unanchored|" + b, "ownership:" + a.ownership)
    a["support_class"] = "role:" + a.role
    for col in ["attribution_score", "support_score"]:
        a[col] = np.nan
    a["attribution_n"] = pd.NA
    a["support_n"] = pd.NA
    if p.exists():
        r = pd.read_csv(p)
        r = r[r.use_for_display].set_index("class")
        p_hat = (r.k / r.n).round(4)
        a["attribution_score"] = a.attr_class.map(p_hat)
        a["attribution_n"] = a.attr_class.map(r.n).astype("Int64")
        a["support_score"] = a.support_class.map(p_hat)
        a["support_n"] = a.support_class.map(r.n).astype("Int64")
    return a


def main():
    missing = [k for k, v in INPUTS.items() if not v.exists()]
    if missing:
        raise SystemExit(f"missing inputs: {missing}")
    rec = record_table()
    facilities = pd.Series(sorted(rec.unique_id), name="unique_id")
    assert len(facilities) == 9959 and rec.unique_id.is_unique

    atoms = pd.concat([claim_atoms_from_claims(), specialty_atoms()], ignore_index=True)
    atoms = attach_scores(atoms, rec)
    atoms = echo_units(atoms)
    cols = ["atom_id", "claim_id", "unique_id", "field", "idx", "text", "service", "ownership", "role", "specificity",
            "quarantined", "counts_as_own", "rejected_reason", "named_entity", "unit_id", "is_unit_rep", "qty_value",
            "qty_unit", "attribution_score", "support_score", "attribution_n", "support_n", "attr_class", "support_class"]
    atoms = atoms[cols].sort_values(["unique_id", "service", "field", "idx"]).reset_index(drop=True)
    assert atoms.atom_id.is_unique

    fam = pair_families(atoms, facilities)
    pre = prereq_counts()
    fam = fam.merge(pre, on=["unique_id", "service"], how="left")
    fam["prereqs"] = fam.prereqs.fillna("")
    fam["P"] = fam.prereqs.map(lambda s: min(2, len([x for x in s.split("|") if x])))
    ctx = context(rec)
    fam = fam.merge(ctx, on="unique_id", how="left")
    fam["S"] = [int(LEX.scope_conflict(n, ft, LEX_KEY[s])) for n, ft, s in zip(fam.name, fam.ftype_raw, fam.service)]
    fam["X"] = pd.array([pd.NA] * len(fam), dtype="Int64")     # no external list yet: abstain everywhere
    fam["R"] = pd.array([pd.NA] * len(fam), dtype="Int64")     # optional role classifier not run over the corpus
    g = pd.read_parquet(INPUTS["grades"], columns=["unique_id", "service", "grade", "scope_conflict"])
    g["service"] = g.service.map(SVC_MAP)
    g = g.dropna(subset=["service"])
    fam = fam.merge(g.rename(columns={"scope_conflict": "grades_scope_conflict"}), on=["unique_id", "service"], how="left")
    fam["grade"] = fam.grade.fillna("no_mention")
    fam = fam.merge(rec[["unique_id", "bucket", "list_truncated", "q_share", "n_urls", "shared_content"]], on="unique_id", how="left")
    fam["iphs_essential"] = (fam.public_level == "dh") & fam.service.isin(IPHS_DH_ESSENTIAL)
    fam = fam.drop(columns=["ftype_raw"])
    assert len(fam) == 69713, len(fam)

    rs = pd.read_parquet(INPUTS["record_scores"])
    fl = pd.read_parquet(INPUTS["facility_location"])
    fg = pd.read_parquet(INPUTS["facility_geo"]).drop_duplicates("unique_id")
    claims = pd.read_parquet(INPUTS["claims"], columns=["unique_id", "text"])
    loc = location_votes(fl, fg, rs, claims)
    ex = existence(rs, fg)
    lg = leakage_groups(rs, ex)
    ff = (fl[["unique_id", "name", "address_city", "address_stateOrRegion", "pin", "state_final", "district",
              "nfhs_state_ut", "nfhs_district_name"]]
          .merge(loc, on="unique_id").merge(ex, on="unique_id").merge(lg, on="unique_id")
          .merge(ctx[["unique_id", "facility_type", "operator_public", "public_level", "beds_bin", "doctors_bin"]], on="unique_id"))
    assert len(ff) == 9959 and ff.unique_id.is_unique

    atoms.to_parquet(HERE / "claim_atoms.parquet", index=False)
    fam.to_parquet(HERE / "pair_features.parquet", index=False)
    ff.to_parquet(HERE / "facility_features.parquet", index=False)
    shutil.copy(INPUTS["lexicon"], HERE / "lexicon_used.csv")
    stats = dict(atoms=len(atoms), atoms_counting=int(atoms.counts_as_own.sum()), units=int(atoms.is_unit_rep.sum()),
                 ownership=atoms.ownership.value_counts().to_dict(), role=atoms.role.value_counts().to_dict(),
                 rejected=atoms.rejected_reason.value_counts().to_dict(),
                 T=fam["T"].value_counts().sort_index().to_dict(), C=fam.C.value_counts().sort_index().to_dict(),
                 N=int(fam.N.sum()), S=int(fam.S.sum()), P=fam.P.value_counts().sort_index().to_dict(),
                 bucket=rec.bucket.value_counts().to_dict(),
                 S_vs_grades_agree=int((fam.grades_scope_conflict.dropna().astype(int) == fam.S[fam.grades_scope_conflict.notna()]).sum()),
                 S_vs_grades_n=int(fam.grades_scope_conflict.notna().sum()),
                 leakage_groups=int(ff.leakage_group_id.nunique()), largest_group=int(ff.group_size.max()),
                 name_place_witness=int((ff.vote_name_place != 0).sum()),
                 votes={w: ff[f"vote_{w}"].value_counts().to_dict() for w in ["coords", "pin", "city", "name_place", "state", "text_pin", "map_link"]})
    (HERE / "build_stats.json").write_text(json.dumps(stats, indent=1, default=int))
    frozen = dict(created_at=dt.datetime.now().isoformat(timespec="seconds"),
                  code_sha256={p.name: sha256_file(p) for p in sorted(HERE.glob("*.py"))},
                  input_sha256={k: sha256_file(v) for k, v in INPUTS.items()},
                  derived_input_sha256={"attribution_rates.csv": sha256_file(HERE / "attribution_rates.csv")
                                        if (HERE / "attribution_rates.csv").exists() else None},
                  output_sha256={n: sha256_file(HERE / n) for n in ["claim_atoms.parquet", "pair_features.parquet",
                                                                     "facility_features.parquet", "lexicon_used.csv"]},
                  note="Any change to families or lexicon gets a new hash; gold labels read before the change move to dev.")
    (HERE / "FROZEN.json").write_text(json.dumps(frozen, indent=1))
    print(json.dumps(stats, indent=1, default=int))


if __name__ == "__main__":
    main()
