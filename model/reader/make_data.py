"""Build the weak-label training set for the evidence reader from derived/v1/claims.parquet.

Held out completely (never in train or validation):
  - every facility in the gold TEST split (model/gold/splits.json), plus the other records of its
    duplicate group in derived/v1/facility_groups.parquet when that table has a group column;
  - every facility that has a row in the hand-labelled eval set (model/reader/eval/eval_set.csv).
Validation: 10% of the remaining facilities, chosen by a hash of unique_id (grouped by facility).

Examples (context = "name, city | service", sentence). A label of -1 means "no label for this head".

  about_this
    other     attribution other_facility                              -> 0
    own       attribution own_anchored                                -> 1
    unanch    attribution unanchored (sample)                         -> 1, weight 0.5 (weakest label)
    swap      an own_anchored sentence shown with ANOTHER facility's name and city -> 0
              (synthetic: teaches name mismatch without the rule's keyword lists)
  offers, for a (sentence, service) pair
    pos       lexicon match, no non-offer cue, kind specific/list/qualified, not other_facility -> 1
    cue       lexicon match with a non-offer cue (negation, referral, future, past, camp)   -> 0
    veto      include pattern hits but exclude / clause veto rejects it                      -> 0
    kind      lexicon match in a template, research, directory or staff sentence             -> 0
    foreign   lexicon match in a sentence attributed to another facility                     -> 0
    related   only the 'related' pattern hits (e.g. nephrology for dialysis)                 -> 0
    random    a service the sentence does not mention at all                                 -> 0

Output: model/reader/data/train.parquet (git-ignored) and model/reader/data/data_stats.json
Run: .venv/bin/python model/reader/make_data.py
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import NON_OFFER_KINDS, ROOT, Lexicon, context  # noqa: E402

OUT = Path(__file__).resolve().parent / "data"
SEED = 7
CAP = {"pos_per_service": 2500, "related_per_service": 600, "random": 15000, "own": 20000, "unanch": 15000, "swap": 15000}


def held_out_facilities():
    splits = json.loads((ROOT / "model/gold/splits.json").read_text())
    test = {p["unique_id"] for p in splits["pairs"] if p.get("split") == "test"}
    groups = pd.read_parquet(ROOT / "derived/v1/facility_groups.parquet")
    gcol = next((c for c in ("dup_group_id", "grp_strong", "group_id") if c in groups.columns), None)
    extra = set()
    if gcol:
        g = groups[groups[gcol].notna()]
        in_test = set(g[g.unique_id.isin(test)][gcol])
        extra = set(g[g[gcol].isin(in_test)].unique_id) - test
    ev = pd.read_csv(Path(__file__).resolve().parent / "eval" / "eval_set.csv")
    eval_fac = set(ev.unique_id.dropna())
    return test, extra, eval_fac, gcol


def is_val(uid):
    return int(hashlib.sha256(("reader-val:" + uid).encode()).hexdigest(), 16) % 10 == 0


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    lex = Lexicon()
    test, extra, eval_fac, gcol = held_out_facilities()
    held = test | extra | eval_fac
    c = pd.read_parquet(ROOT / "derived/v1/claims.parquet", columns=["claim_id", "unique_id", "text", "attribution", "kind"])
    n_all = len(c)
    c = c[~c.unique_id.isin(held) & c.text.notna() & (c.text.str.len() >= 8)].reset_index(drop=True)
    fac = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "name", "address_city"]).fillna("")
    c = c.merge(fac, on="unique_id", how="inner")
    import warnings
    warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
    kind_bad = c.kind.isin(NON_OFFER_KINDS).values
    foreign = (c.attribution == "other_facility").values

    parts = []

    def emit(rows, service, y_about, y_offers, tag, weight=1.0, name=None, city=None):
        if len(rows) == 0:
            return
        d = pd.DataFrame({"claim_id": rows.claim_id.values, "unique_id": rows.unique_id.values,
                          "a": [context(n, ci, lex.label.get(service, "")) for n, ci in
                                zip(rows.name if name is None else name, rows.address_city if city is None else city)],
                          "b": rows.text.values, "service_id": service, "y_about": y_about, "y_offers": y_offers,
                          "w": weight, "tag": tag})
        parts.append(d)

    def about_of(rows):
        return np.where(rows.attribution == "other_facility", 0, np.where(rows.attribution == "own_anchored", 1, -1))

    def sample(rows, n):
        return rows if len(rows) <= n else rows.iloc[rng.choice(len(rows), n, replace=False)]

    any_hit = np.zeros(len(c), dtype=bool)
    counts = {}
    for s in lex.services:
        inc = c.text.str.contains(lex.rx[s]["include"], na=False).values
        any_hit |= inc
        hit_rows = c[inc]
        res = [lex.match(t, s) for t in hit_rows.text]
        m = np.array([r[0] for r in res], dtype=bool)
        q = np.array([r[1] for r in res], dtype=bool)
        kb, fo = kind_bad[inc], foreign[inc]
        pos = hit_rows[m & ~q & ~kb & ~fo]
        groups = {"pos": sample(pos, CAP["pos_per_service"]), "cue": hit_rows[m & q], "veto": hit_rows[~m],
                  "kind": hit_rows[m & ~q & kb & ~fo], "foreign": hit_rows[m & fo]}
        rel = c[c.text.str.contains(lex.rx[s]["related"], na=False).values & ~inc]
        groups["related"] = sample(rel, CAP["related_per_service"])
        for tag, rows in groups.items():
            emit(rows, s, about_of(rows), 1 if tag == "pos" else 0, tag)
        counts[s] = {k: int(len(v)) for k, v in groups.items()} | {"pos_available": int(len(pos))}

    # a service the sentence does not mention
    none = sample(c[~any_hit], CAP["random"])
    for s, rows in none.groupby(rng.choice(lex.services, len(none))):
        emit(rows, s, about_of(rows), 0, "random")

    # about_this only (no service)
    emit(c[foreign], "", 0, -1, "other")
    own = sample(c[c.attribution == "own_anchored"], CAP["own"])
    emit(own, "", 1, -1, "own")
    emit(sample(c[c.attribution == "unanchored"], CAP["unanch"]), "", 1, -1, "unanch", weight=0.5)
    sw = sample(c[c.attribution == "own_anchored"], CAP["swap"])
    other = fac[~fac.unique_id.isin(held)].sample(len(sw), replace=True, random_state=SEED)
    keep = other.name.values != sw.name.values
    emit(sw[keep], "", 0, -1, "swap", name=other.name.values[keep], city=other.address_city.values[keep])

    d = pd.concat(parts, ignore_index=True)
    d["split"] = np.where(d.unique_id.map(is_val), "val", "train")
    d = d.sample(frac=1.0, random_state=SEED).reset_index(drop=True)
    d.to_parquet(OUT / "train.parquet", index=False)
    assert not set(d.unique_id) & held
    stats = {"claims_total": int(n_all), "claims_after_holdout": int(len(c)),
             "held_out": {"gold_test_facilities": len(test), "same_duplicate_group": len(extra), "group_column": gcol,
                          "eval_set_facilities": len(eval_fac), "total": len(held)},
             "examples": int(len(d)), "by_split": d.split.value_counts().to_dict(),
             "facilities": {"train": int(d[d.split == "train"].unique_id.nunique()), "val": int(d[d.split == "val"].unique_id.nunique())},
             "by_tag": d.tag.value_counts().to_dict(),
             "about_labels": {str(k): int(v) for k, v in d.y_about.value_counts().items()},
             "offers_labels": {str(k): int(v) for k, v in d.y_offers.value_counts().items()},
             "per_service": counts, "caps": CAP, "seed": SEED}
    (OUT / "data_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps({k: v for k, v in stats.items() if k != "per_service"}, indent=1))
    tot = {k: sum(v[k] for v in counts.values()) for k in ("pos_available", "cue", "veto", "kind", "foreign")}
    print("lexicon totals over all services:", tot)


if __name__ == "__main__":
    main()
