"""Render the three worked explanation examples (card of spec 7.1 plus the judge view of 7.2) from stored tables only.
Every number is read from pair_scores, pair_contributions, facility_contributions, weights, band_record or atoms;
nothing is recomputed by a second model. Writes examples.txt. Run: .venv/bin/python examples.py
"""
import json

import numpy as np
import pandas as pd

from fcommon import HERE, PTS, ROOT, SNAP

CASES = [("strong", "acde9be7", "dialysis"), ("uncertain", "c599e4ad", "dialysis"), ("contaminated", "3ac5ae50", "dialysis")]
LABEL = {"dialysis": "dialysis"}
VOTE = {"v_pin": "PIN centre", "v_city": "stated city", "v_name": "place in the name", "v_coords": "listing coordinates",
        "v_state": "stated state"}
REASON = {"names_other_facility": "names a different hospital", "other_state_place": "names a place in another state",
          "other_district_place": "names a place in another district", "quarantined_merge": "flagged as merged content",
          "sibling_branch": "describes another branch of the same group"}


def main():
    ps = pd.read_parquet(HERE / "pair_scores.parquet")
    pc = pd.read_parquet(HERE / "pair_contributions.parquet")
    fc = pd.read_parquet(HERE / "facility_contributions.parquet")
    w = pd.read_parquet(HERE / "weights.parquet")
    br = pd.read_parquet(HERE / "band_record.parquet")
    atoms = pd.read_parquet(HERE / "atoms.parquet").set_index("atom_id")
    ff = pd.read_parquet(HERE / "features_facility.parquet").set_index("unique_id")
    rt = pd.read_parquet(SNAP / "record_trust.parquet").set_index("unique_id")
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "address_city", "source_urls"]).drop_duplicates("unique_id").set_index("unique_id")
    ms = json.load(open(HERE / "model_selection.json"))
    tl, tu = ms["thresholds"]["t_L"], ms["thresholds"]["t_U"]
    ws = w[w["head"] == "service"].set_index("term")
    lines = []
    for kind, u8, svc in CASES:
        r = ps[ps.unique_id.str.startswith(u8) & (ps.service == svc)].iloc[0]
        u = r.unique_id
        f = ff.loc[u]
        c = pc[(pc.unique_id == u) & (pc.service == svc)]
        rec = br[(br.band == r.band) & (br.split == "test")].iloc[0]
        dev = br[(br.band == r.band) & (br.split == "dev_oof")].iloc[0]
        L = []
        head = {"Likely": "LIKELY offers", "Unverified": "Not verified: call to confirm", "Unlikely": "Little public evidence for"}[r.band]
        L.append(f"=== Example: {kind} ({r['name']}, {svc}) ===")
        L.append(f"[1] {head} {svc.replace('_', ' ')} - {r['name']}, {raw.loc[u].address_city}        [band, name]")
        L.append("    Distance and travel time come from the decision layer for a query point (not part of fusion).")
        L.append(f"[2] How sure: {r.p_s:.2f} (range {r.p_s_lo:.2f} to {r.p_s_hi:.2f}).        [p_s, p_s_lo, p_s_hi]")
        if rec.N:
            L.append(f"    Of {rec.N} checked test facilities in this band, {rec.k_confirmed} were confirmed, {rec.k_contradicted} were wrong, "
                     f"{rec.k_no_info} had no public information.        [band_record, split = test]")
        else:
            L.append(f"    No checked test facility fell in this band, so there is no track record yet. Dev out-of-fold: {dev.N} pairs, "
                     f"{dev.k_confirmed} confirmed, {dev.k_contradicted} wrong, {dev.k_no_info} no public information.        [band_record]")
        cited = [a for a in str(c.cited_atom_ids.iloc[0] or "").split("|") if a] if len(c) else []
        cited = ["|".join(cited[i:i + 2]) for i in range(0, len(cited), 2)]
        L.append(f"[3] Why we think it offers {svc.replace('_', ' ')} (from its listing):        [cited_atom_ids -> atoms.text]")
        for a in cited:
            L.append(f"    [{atoms.loc[a].field}] \"{atoms.loc[a].text}\"")
        if not cited:
            L.append("    (no sentence of its own names the service)")
        urls = json.loads(raw.loc[u].source_urls) if isinstance(raw.loc[u].source_urls, str) and raw.loc[u].source_urls.startswith("[") else []
        L.append(f"    Sources: one of these pages: {', '.join(urls[:3])}{' ...' if len(urls) > 3 else ''} ({len(urls)} pages in the record)")
        phones = rt.loc[u].display_phones
        L.append(f"[4] Is it real: website {f.web_class.replace('_', ' ')} ({rt.loc[u].website_domain}); phone {f.phone_class}. "
                 f"P_E = {r.p_e:.2f}. Existence weights are expert settings, not learned (5 dev negatives).")
        votes = [(VOTE[v], int(f[v])) for v in VOTE]
        agree = [n for n, v in votes if v == 1]
        dis = [n for n, v in votes if v == -1]
        L.append(f"[5] Where: point taken from {f.p1_src.replace('_', ' ')}. Agree within 25 km: {', '.join(agree) or 'none'}. "
                 f"Point elsewhere: {', '.join(dis) or 'none'}. P_L = {r.p_l:.2f}.")
        if f.loc_note:
            L.append(f"    Note: {f.loc_note}")
        rej = [a for a in str(c.rejected_atom_ids.iloc[0] or "").split("|") if a] if len(c) else []
        rej = ["|".join(rej[i:i + 2]) for i in range(0, len(rej), 2)]
        L.append("[6] What we ignored:" + ("" if rej else " nothing (no sentence about another facility or place)"))
        for a in rej:
            L.append(f"    \"{atoms.loc[a].text}\" - {REASON.get(atoms.loc[a].rejected_reason, atoms.loc[a].rejected_reason)}"
                     f" ({atoms.loc[a].named_entity})")
        L.append(f"[8] Call first: {', '.join(list(phones)[:2]) if phones is not None and len(phones) else 'no phone in our data'}")
        L.append("--- judge view: service head waterfall (points = 20/ln2 x logit; 20 points doubles the odds) ---")
        base = c[c.group == "base"].contribution_logit.sum()
        L.append(f"    base (intercept + calibration offset): {base:+.3f} logit = {base * PTS:+.1f} pts")
        for g in ("evidence", "context"):
            for t in c[c.group == g].sort_values("contribution_logit", key=np.abs, ascending=False).itertuples():
                wr = ws.loc[t.term] if t.term in ws.index else None
                L.append(f"    [{g}] {t.term:20s} x={t.x_value:+.0f}  {t.contribution_logit:+.3f} logit = {t.points:+6.1f} pts"
                         + (f"  (prior {wr.prior_mean:+.2f}, posterior {wr.post_mean:+.2f}, fired on {int(wr.n_fired_dev)} dev pairs)" if wr is not None else ""))
        tot = c.contribution_logit.sum()
        L.append(f"    total {tot:+.3f} logit = z_cal {r.z_cal:+.3f} -> P_S = {r.p_s:.3f} (additivity error {abs(tot - r.z_cal):.1e})")
        L.append(f"    band rule: [{'x' if r.p_s >= tl else ' '}] P_S >= t_L ({tl:.2f})  [{'x' if r.p_l >= 0.7 else ' '}] P_L >= 0.7  "
                 f"[{'x' if r.p_e >= 0.7 else ' '}] P_E >= 0.7  [{'x' if r['T'] >= 2 else ' '}] T >= 2 (T = {r['T']})  -> {r.band}: {r.band_reason}")
        L.append(f"    stored counterfactual: without the quoted sentences P_S would be {r.p_s_without_cited:.2f}")
        lc = fc[(fc.unique_id == u) & (fc["head"] == "location")]
        L.append("    location head: " + ", ".join(f"{t.term} x={t.x_value:+.0f} {t.points:+.1f} pts" for t in lc.itertuples() if abs(t.contribution_logit) > 1e-12))
        lines += L + [""]
    (HERE / "examples.txt").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
