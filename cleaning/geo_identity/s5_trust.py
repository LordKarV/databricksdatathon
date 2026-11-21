"""Step 5: record-level trust flags and cleaned contact fields. Nothing here changes a ranking score
directly; each flag carries a reason sentence the app can show, and a coarse trust_level summarises them.

Contact validity
  - phones normalised (identity audit norm_phone); a number held by records in >= 3 cities is a
    directory or call-centre number (ID5: 33 of the 45 most shared were directories) unless most of
    its holders are one chain (then 'chain helpline'). display_phones keeps up to 3 numbers held by
    no other record, official phone first.
  - emails: Cloudflare placeholder dropped; JSON lists split; '[at]'/'[dot]' de-obfuscated (ID7 verifier).
  - website class: own / directory / government / social; a chain domain on a non-brand name is flagged.
Scale plausibility: audit/scale/scale_flags.parquet, with the verifier's fixes (veterinary rule
  re-done without street-name hits; chain-wide doctor counts: >= 100 doctors and > 2x beds).
Claims everything: number of the 8 audited services with a text grade (claims audit grades.parquet);
  6+ of 8 is a merge candidate (claims-09); a <20-bed record claiming a tertiary service is flagged.
Writes record_trust.parquet and s5_stats.json.
"""
import importlib.util
import json
import re

import pandas as pd

from common import OUT, ROOT

_spec = importlib.util.spec_from_file_location("identity_common", ROOT / "audit/identity/common.py")
_ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ic)

DIRECTORY = re.compile(r"(practo|justdial|lybrate|sulekha|hexahealth|bajajfinserv|eka\.care|credihealth|medindia|skedoc|"
                       r"indiamart|placestars|quickerala|drlogy|myupchar|business\.site|g\.page|goo\.gl|google)")
SOCIAL = re.compile(r"(facebook|instagram|linkedin|twitter|x\.com|youtube|wa\.me|blogspot|wixsite|wordpress)")
GOV = re.compile(r"(\.gov\.in|\.nic\.in|gov\.in$)")
VET = re.compile(r"\b(veterinar\w*|animal|vet|pets?\s+(clinic|care|hospital)|pets)\b", re.I)
TERTIARY = {"cardiac_surgery", "burns", "nicu", "mri"}
SEVERITY = {"location_disputed": 2, "location_low": 1, "no_location": 3, "veterinary": 9, "copies_far_apart": 1,
            "claims_6plus_of_8_services": 1, "small_facility_tertiary_claim": 1, "official_phone_is_directory": 1,
            "no_direct_contact": 1, "website_may_belong_to_other_org": 1, "doctors_exceed_beds": 1}
REASON = {
    "location_disputed": "Location fields disagree and nothing settles which is right.",
    "location_low": "Location is approximate (postcode centre or a corrected point).",
    "no_location": "No usable coordinates or postcode.",
    "veterinary": "Name indicates an animal-care facility.",
    "copies_far_apart": "The source lists this facility more than once, with copies far apart.",
    "claims_6plus_of_8_services": "Claims 6 or more of the 8 audited acute services; records like this often merge several facilities.",
    "small_facility_tertiary_claim": "Fewer than 20 beds recorded, yet claims a tertiary service.",
    "official_phone_is_directory": "The listed official phone also appears on listings in 3 or more cities (likely a directory line).",
    "no_direct_contact": "No phone or website that belongs only to this facility.",
    "website_may_belong_to_other_org": "The official website is a chain domain but the name does not carry the brand.",
    "doctors_exceed_beds": "Doctor count looks chain-wide (100+ doctors and more than twice the beds).",
}


def clean_emails(raw):
    if not isinstance(raw, str) or raw.strip().lower() in {"", "null", "[]"}:
        return [], None
    if "email" in raw and "protected" in raw:
        return [], "email_placeholder"
    raw = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", raw, flags=re.I)
    raw = re.sub(r"\s*[\[\(]\s*dot\s*[\]\)]\s*", ".", raw, flags=re.I)
    parts = _ic.parse_list(raw) if raw.strip().startswith("[") else re.split(r"[,;/\s]+", raw)
    out = []
    for p in parts:
        p = p.strip().strip(".").lower()
        if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", p) and "*" not in p:
            out.append(p)
    return sorted(set(out)), None if out else "email_malformed"


def website_class(dom):
    if not isinstance(dom, str) or not dom:
        return None
    return "directory" if DIRECTORY.search(dom) else "social" if SOCIAL.search(dom) else "government" if GOV.search(dom) else "own"


def main():
    df = _ic.load().drop_duplicates("unique_id").reset_index(drop=True)
    loc = pd.read_parquet(OUT / "facility_location.parquet").set_index("unique_id")
    grp = pd.read_parquet(OUT / "facility_groups.parquet").set_index("unique_id")
    sc = pd.read_parquet(ROOT / "audit/scale/scale_flags.parquet").drop_duplicates("unique_id").set_index("unique_id")
    gr = pd.read_parquet(ROOT / "audit/claims/out/grades.parquet")
    chain = pd.read_csv(ROOT / "audit/identity/out/chain_membership.csv").set_index("unique_id")
    st = {"records": len(df)}

    # ---- phones
    df["ph"] = [[_ic.norm_phone(p) for p in ([o] if o else []) + l] for o, l in zip(df.officialPhone, df.phone_numbers_l)]
    df["ph"] = df.ph.map(lambda x: list(dict.fromkeys(d for d, k in x if k != "invalid")))
    ex = df[["unique_id", "ph", "ncity"]].explode("ph").dropna(subset=["ph"])
    ex["chain"] = ex.unique_id.map(chain.chain)
    by = ex.groupby("ph")
    n_city, n_rec = by.ncity.nunique(), by.unique_id.nunique()
    chain_share = by.chain.agg(lambda s: s.value_counts(normalize=False).max() / len(s) if s.notna().any() else 0)
    directory = set(n_city[(n_city >= 3) & (chain_share < 0.5)].index)
    helpline = set(n_city[(n_city >= 3) & (chain_share >= 0.5)].index)
    st["phones_directory_vs_chain_helpline"] = [len(directory), len(helpline)]
    df["oph"] = df.officialPhone.map(lambda p: _ic.norm_phone(p)[0] if p else None)
    df["display_phones"] = [[p for p in ([o] if o in ps else []) + ps if n_rec.get(p, 0) == 1][:3]
                            for o, ps in zip(df.oph, df.ph)]
    df["display_phones"] = df.display_phones.map(lambda x: list(dict.fromkeys(x)))
    df["chain_helplines"] = df.ph.map(lambda x: [p for p in x if p in helpline][:1])

    # ---- email and website
    em = df.email.map(clean_emails)
    df["emails_clean"], df["email_issue"] = em.str[0], em.str[1]
    df["dom"] = df.officialWebsite.map(_ic.domain)
    df["website_class"] = df.dom.map(website_class)
    chain_dom_no_name = chain.chain_by_dom.notna() & chain.chain_by_name.isna()
    st["emails_before_after"] = [int(df.email.notna().sum()), int((df.emails_clean.map(len) > 0).sum())]
    st["email_issue"] = df.email_issue.value_counts().to_dict()
    st["website_class"] = df.website_class.value_counts(dropna=False).to_dict()

    # ---- claims breadth from the claims audit's grades
    g = gr[gr.grade.isin(["strong", "medium", "weak"])]
    n_serv = g.groupby("unique_id").service.nunique()
    tert = g[g.service.isin(TERTIARY)].groupby("unique_id").service.agg(lambda s: sorted(set(s)))

    rows = []
    for r in df.itertuples():
        u = r.unique_id
        fl = []
        lc = loc.loc_conf.get(u)
        fl += ["location_disputed"] if lc == "disputed" else ["location_low"] if lc == "low" else ["no_location"] if lc == "none" else []
        if VET.search(r.name or "") and not re.search(r"\bpet[- ]?(ct|scan|mri)\b", r.name or "", re.I):
            fl.append("veterinary")
        if bool(grp.group_location_disagrees.get(u, False)):
            fl.append("copies_far_apart")
        if n_serv.get(u, 0) >= 6:
            fl.append("claims_6plus_of_8_services")
        cap = sc.capacity_clean.get(u)
        if pd.notna(cap) and cap < 20 and u in tert.index:
            fl.append("small_facility_tertiary_claim")
        nd = sc.doctors_clean.get(u)
        if pd.notna(nd) and nd >= 100 and pd.notna(cap) and nd > 2 * cap:
            fl.append("doctors_exceed_beds")
        if r.oph in directory:
            fl.append("official_phone_is_directory")
        if not r.display_phones and r.website_class != "own":
            fl.append("no_direct_contact")
        if u in chain_dom_no_name.index and chain_dom_no_name.get(u, False):
            fl.append("website_may_belong_to_other_org")
        scale = [x for x in sc.scale_flags.get(u, []) if x != "veterinary_name"]
        sev = sum(SEVERITY[x] for x in fl)
        level = "exclude_review" if "veterinary" in fl else "no_concerns" if sev == 0 else "minor" if sev == 1 else "caution"
        rows.append(dict(unique_id=u, trust_flags=fl, trust_reasons=[REASON[x] for x in fl], scale_flags=scale,
                         n_services_claimed=int(n_serv.get(u, 0)), trust_level=level))
    t = pd.DataFrame(rows)
    out = df[["unique_id", "name", "display_phones", "chain_helplines", "emails_clean", "email_issue", "dom", "website_class"]].merge(t, on="unique_id")
    out = out.rename(columns={"dom": "website_domain"})
    st["flag_counts"] = pd.Series([x for f in t.trust_flags for x in f]).value_counts().to_dict()
    st["trust_level"] = t.trust_level.value_counts().to_dict()
    st["records_with_display_phone"] = int((out.display_phones.map(len) > 0).sum())
    st["records_official_phone_directory_before_display"] = int(df.oph.isin(directory).sum())
    st["veterinary_names"] = out[out.trust_flags.map(lambda x: "veterinary" in x)].name.tolist()
    out.to_parquet(OUT / "record_trust.parquet", index=False)
    (OUT / "s5_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps(st, indent=1, default=str))


if __name__ == "__main__":
    assert clean_emails('["a@x.com","b@y.in"]')[0] == ["a@x.com", "b@y.in"]
    assert clean_emails("info [at] abc [dot] com")[0] == ["info@abc.com"]
    assert clean_emails("[email protected]")[1] == "email_placeholder"
    assert website_class("practo.com") == "directory" and website_class("aiims.edu") == "own"
    assert not VET.search("Sri Sri Holistic Hospitals Nizampet") and VET.search("SKS Veterinary Hospital")
    main()
