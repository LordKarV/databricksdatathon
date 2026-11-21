"""Three worked explanation cards built only from this layer's tables (strong, uncertain, contaminated).
Every line is a template filled from a stored row; the provisional score is the prior scorecard (B4e), since
P_S, bands and track records belong to the fusion layer. Writes examples.json and examples.txt.
"""
import json
import math

import pandas as pd

from common import HERE
from evaluate import design

CASES = [("strong", "c599e4ad", "dialysis"), ("uncertain", None, None), ("contaminated", "3ac5ae50", "dialysis")]
W_LABEL = {"coords": "map point (listing coordinates)", "pin": "PIN centre", "city": "stated city",
           "name_place": "place in the name", "state": "stated state", "text_pin": "PIN written in the text",
           "map_link": "map link for this name"}
REASON = {"names_other_facility": "names a different hospital", "other_state_place": "places it in another state",
          "quarantined_merge": "copied from a merged web page", "sibling_branch": "describes another branch of the same group",
          "ambiguous_reference": "refers to another facility or place; unclear", "nonoffer_cue": "says not offered, planned, referred or a camp",
          "directory_or_list": "only a list or directory entry", "staff_only": "describes a doctor, not a service",
          "hedge": "hedged wording", "research_or_template": "research or template text"}
PTS = 20 / math.log(2)


def card(pair: pd.Series, fac: pd.Series, atoms: pd.DataFrame) -> dict:
    a = atoms.set_index("atom_id")
    pc = json.load(open(HERE / "prior_scorecard.json"))
    x = design(pair.to_frame().T.astype({"T": int, "C": int, "N": int, "S": int, "P": int})).iloc[0]
    terms = [(c, float(x[c]), pc["weights"][c]["w"]) for c in x.index if x[c]]
    z = pc["intercept"] + sum(v * w for _, v, w in terms)
    p = 1 / (1 + math.exp(-z))
    xw = design(pair.to_frame().T.assign(T=pair.t_without_cited).astype({"T": int, "C": int, "N": int, "S": int, "P": int})).iloc[0]
    z0 = pc["intercept"] + sum(pc["weights"][c]["w"] * xw[c] for c in xw.index)
    cited = [i for i in pair.cited_atom_ids.split(";") if i]
    rejected = [i for i in pair.rejected_atom_ids.split(";") if i and a.at[i, "field"] != "specialties"]
    agree = [W_LABEL[w] for w in W_LABEL if fac[f"vote_{w}"] == 1]
    against = [W_LABEL[w] for w in W_LABEL if fac[f"vote_{w}"] == -1]
    p2_agree = [W_LABEL[w] for w in W_LABEL if fac.get(f"vote_{w}_p2") == 1]
    lines = [f"[1] {fac['name']}, {fac.address_city} ({fac.state_final}) - {pair.service}",
             f"[2] Evidence-only preview score {p:.2f} ({z * PTS:+.0f} points from base {pc['intercept'] * PTS:+.0f}); "
             f"without the quoted sentences it would be {1 / (1 + math.exp(-z0)):.2f}. Final P_S and its band come from fusion.",
             "[3] Why we think it offers the service (from its listing):"]
    for i in cited:
        r = a.loc[i]
        lines.append(f"    [{r.field}] \"{r.text}\"  (sentences of this kind were about this facility in "
                     f"{'n/a' if pd.isna(r.attribution_score) else f'{r.attribution_score:.0%} of {int(r.attribution_n)} checked'})")
    if not cited:
        lines.append("    No sentence in the listing counts as this facility's own evidence.")
    lines.append(f"    Sources: one of these pages: {int(fac.n_source_ids)} distinct source ids (no sentence-to-URL map exists)")
    lines.append(f"[4] Is it real: website {fac.website_class}{' ' + fac.website if isinstance(fac.website, str) else ''}; "
                 f"phone {fac.phone_class}{' (may be a directory number)' if fac.phone_class == 'shared_3plus' else ''}.")
    if not against:
        lines.append(f"[5] Where: {', '.join(agree)} agree (within 25 km of the point we use).")
    else:
        lines.append(f"[5] Where: not sure. {', '.join(against)} point elsewhere; {', '.join(agree) or 'nothing'} support the point we use"
                     f" ({fac.p1_district}). " + (f"The alternative point ({fac.p2_district}) is backed by {', '.join(p2_agree)}." if p2_agree else ""))
    if rejected:
        lines.append("[6] What we ignored:")
        for i in rejected:
            r = a.loc[i]
            lines.append(f"    \"{r.text}\" - {REASON.get(r.rejected_reason, r.rejected_reason)}"
                         + (f" ({r.named_entity})" if isinstance(r.named_entity, str) else ""))
    flags = []
    if pair.S:
        flags.append("the facility's name suggests a scope that does not include this service")
    if pair.bucket == "high":
        flags.append(f"this record merges many web sources (q_share {pair.q_share:.2f}, {int(pair.n_urls)} URLs), so its text earns less weight")
    if flags:
        lines.append("[7] Cautions: " + "; ".join(flags) + ".")
    return dict(unique_id=pair.unique_id, service=pair.service, families={k: int(pair[k]) for k in ["T", "C", "N", "S", "P"]},
                bucket=pair.bucket, preview_p=round(p, 4), preview_terms=[dict(term=c, x=v, weight=w, points=round(v * w * PTS, 1)) for c, v, w in terms],
                preview_p_without_cited=round(1 / (1 + math.exp(-z0)), 4), cited_atom_ids=cited, rejected_atom_ids=rejected,
                location_votes={w: int(fac[f"vote_{w}"]) for w in W_LABEL}, card_text=lines)


def main():
    pf = pd.read_parquet(HERE / "pair_features.parquet")
    ff = pd.read_parquet(HERE / "facility_features.parquet").set_index("unique_id")
    atoms = pd.read_parquet(HERE / "claim_atoms.parquet")
    ev = pd.read_csv(HERE / "eval_pairs.csv")
    out = []
    for kind, u8, svc in CASES:
        if kind == "uncertain":   # a dev gold pair with one own unit and an unresolved label
            row = ev[(ev.split == "dev") & (ev["T"] == 2) & (ev.service_label == "no_info") & (ev.C == 0)].iloc[0]
            u8, svc = row.unique_id[:8], row.service
        pair = pf[pf.unique_id.str.startswith(u8) & (pf.service == svc)].iloc[0]
        c = card(pair, ff.loc[pair.unique_id], atoms)
        g = ev[(ev.unique_id == pair.unique_id) & (ev.service == svc)]
        c["kind"] = kind
        c["gold"] = g[["pair_id", "split", "service_label"]].to_dict("records")
        out.append(c)
    (HERE / "examples.json").write_text(json.dumps(out, indent=1, default=str))
    with open(HERE / "examples.txt", "w") as f:
        for c in out:
            f.write(f"== {c['kind']} (gold: {c['gold']})\n" + "\n".join(c["card_text"]) + "\n\n")
    print(open(HERE / "examples.txt").read())


if __name__ == "__main__":
    main()
