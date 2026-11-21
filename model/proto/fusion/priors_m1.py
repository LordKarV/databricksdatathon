"""Write priors_M1.json: expert prior means and sds for every term of the three heads, with the derivation of each.

Rates use Jeffreys smoothing r = (k + 0.5) / (n + 1); a log-likelihood ratio (LLR) is a difference of logits.
Disclosure (also in REPORT.md): this file was written after the fusion builder had read the v2 DEV labels (to design
the unchecked-label rule) and the marginal v2 label counts; no v2 rate enters any number below. Numbers marked
"expert" have no audit rate behind them and get sd >= 1.0.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python priors_m1.py
"""
import datetime
import json
import math

from fcommon import HERE, SERVICES, sha256_str


def lg(k, n):
    r = (k + 0.5) / (n + 1)
    return math.log(r / (1 - r))


V1_STRONG, V1_WEAK, V1_SUSPECT = lg(10, 12), lg(1, 12), lg(4, 12)
B_SVC = -2.9  # expert: about 5% of pairs with no mention would be publicly confirmed

SERVICE = {
    **{f"b_{s}": (B_SVC, 1.5, "expert: base rate about 5% for a pair with no mention (no audit rate exists before labels)") for s in SERVICES},
    "t1": (0.4, 1.0, "expert: a specialties tag or list-only mention is weak evidence"),
    "t2": (round(V1_WEAK - B_SVC - 0.4, 2), 1.0,
           f"v1 weak stratum 1/12 confirmed: logit {V1_WEAK:.2f} = b + t1 + t2, so t2 = {V1_WEAK:.2f} - ({B_SVC}) - 0.4"),
    "t3": (0.8, 1.0, f"v1 strong 10/12 vs weak 1/12: LLR {V1_STRONG - V1_WEAK:.2f} split over t3, t4, t5/2, p1, p2/2"),
    "t4": (1.0, 1.0, "same split as t3 (2+ fields is the core of the strong stratum)"),
    "t5": (0.6, 1.0, "same split as t3 (about half of strong pairs carry a unit or quantity)"),
    "p1": (0.9, 1.0, "same split as t3 (strong stratum requires a clinical prerequisite)"),
    "p2": (0.5, 1.0, "same split as t3"),
    "tb_mid": (-0.43, 0.75, "half of tb_high"),
    "tb_high": (round(math.log((1 - 0.596) / (1 - 0.042)), 2), 0.75,
                "merge audit: contamination 59.6% of records at 30+ URLs vs 4.2% at < 3 URLs; LLR log(0.404/0.958)"),
    "trunc0": (0.3, 0.75, "expert: no mention on a record whose list hit the 50-item cap says less"),
    "c1": (round(lg(17, 25) * -1 * 0.7, 2), 1.0,
           "cleaning hand check: 17/25 other-facility flags are true foreign content (logit 0.73), scaled by 0.7 because own units remain"),
    "c2": (-0.5, 1.0, "expert: foreign content with no own unit (added to c1)"),
    "n1": (round(lg(6, 40), 2), 0.75,
           "claims audit: 6/40 non-offer atoms were support for the service (logit of 6.5/41) relative to even odds"),
    "s1": (-1.5, 1.0, "expert: single-specialty name (eye, dental, IVF, lab) claiming the service; Aravind v1 contradicted"),
    "g_mid": (0.0, 1.0, "expert: no prior direction for the bucket main effect"),
    "g_high": (0.0, 1.0, "expert: no prior direction"),
    "type_clinic": (-0.5, 1.0, "expert: inpatient services less often at clinics"),
    "type_dentist": (-2.0, 1.0, "expert"), "type_other": (-1.0, 1.0, "expert"), "public": (0.0, 1.0, "expert"),
    "level_dh": (0.5, 1.0, "expert"), "level_sdh": (0.3, 1.0, "expert"), "level_chc": (0.0, 1.0, "expert"),
    "level_phc": (-1.0, 1.0, "expert"), "level_mc": (1.0, 1.0, "expert"),
    "iphs_essential": (0.5, 0.75, "IPHS 2022 marks dialysis and emergency C-section essential at district hospitals"),
    "beds_missing": (0.0, 1.0, "expert"), "beds_lt30": (-0.5, 1.0, "expert"), "beds_100p": (0.5, 1.0, "expert"),
    "doctors_missing": (0.0, 1.0, "expert"), "doctors_lt5": (-0.3, 1.0, "expert"), "doctors_20p": (0.3, 1.0, "expert"),
    "breadth_lt5": (-0.3, 1.0, "expert"), "breadth_20p": (0.3, 1.0, "expert"), "scale_contradiction": (-0.5, 1.0, "expert"),
    **{f"{t}@{s}": (0.0, 0.5, "contract: service deviation ~ N(0, 0.5^2)") for t in ("t2", "t4", "p1") for s in SERVICES},
}
PIN_RIGHT, COORD_RIGHT = lg(27, 40), lg(14, 40)
B_LOC = (COORD_RIGHT + 2.2) / 2  # listing-coordinate point: conflict -> logit(14/40), PIN agrees -> about 0.9
R_PIN = (2.2 - COORD_RIGHT) / 2
LOCATION = {
    "b_loc": (round(B_LOC, 2), 1.0, f"p1 = listing coordinates: b - r_pin = logit(14.5/41) = {COORD_RIGHT:.2f} (geo hand check, conflicts) "
              "and b + r_pin = 2.2 (expert: about 0.9 when PIN agrees)"),
    "v_pin": (round(R_PIN, 2), 0.75, "solved with b_loc from the two equations above"),
    "v_coords": (0.7, 0.75, "expert: about half the PIN vote (coordinates right 14/40 vs PIN right 27/40 in conflicts)"),
    "src_pin": (round(PIN_RIGHT + 0.7 - B_LOC, 2), 1.0, f"p1 = PIN centre with coordinates dissenting: b + src_pin - r_coords = logit(27.5/41) = {PIN_RIGHT:.2f}"),
    "src_city": (-0.5, 1.0, "expert: a city centre is a coarse point"),
    "src_map": (0.5, 1.0, "expert: name-matched map link"),
    "v_name": (round(R_PIN, 2), 0.75, "contract: the name-place vote starts equal to the PIN vote"),
    "v_city": (1.0, 0.75, "expert"), "v_state": (0.7, 0.75, "expert"),
    "f_copied_geocode": (-1.0, 0.75, "expert"), "f_coords_look_wrong": (-0.5, 0.75, "expert"),
    "f_pin_looks_wrong": (-0.5, 0.75, "expert"), "f_text_pin_elsewhere": (-0.5, 0.75, "expert"),
}
EXISTENCE = {
    "b_ex": (1.0, 1.0, f"v1 web checks: 32 of 36 exist (logit {lg(32, 36):.2f}), minus the own-domain, source and recency terms most v1 records carry"),
    "e_web_own": (0.7, 1.0, "expert"), "e_web_other": (0.0, 1.0, "expert"), "e_phone_shared3": (-0.7, 1.0, "expert: directory number"),
    "e_phone_none": (-0.7, 1.0, "expert"), "e_phone_landline": (0.0, 1.0, "expert"), "e_multi_source": (0.3, 1.0, "expert"),
    "e_recency": (0.3, 1.0, "expert"), "e_nonfacility": (-2.0, 1.0, "expert: pharmacy or veterinary"), "e_dup_member": (0.3, 1.0, "expert"),
    "e_coord_shared3": (-0.5, 1.0, "expert: coordinate shared by 3+ names"),
}


def main():
    body = {h: {k: dict(mu=v[0], sd=v[1], derivation=v[2]) for k, v in d.items()}
            for h, d in [("service", SERVICE), ("location", LOCATION), ("existence", EXISTENCE)]}
    for d in body.values():
        for k, v in d.items():
            assert v["sd"] >= (0.5 if "@" in k else 0.75), k
    text = json.dumps(body, sort_keys=True)
    out = dict(created_at=datetime.datetime.now().isoformat(timespec="seconds"), sha256=sha256_str(text),
               disclosure=("Written after the builder read v2 dev labels and marginal v2 label counts; no v2 rate is used. "
                           "v1 rates (36 pairs) were read during design and are dev data."), priors=body)
    (HERE / "priors_M1.json").write_text(json.dumps(out, indent=1))
    print("priors_M1.json", out["created_at"], out["sha256"][:12], {h: len(d) for h, d in body.items()})


if __name__ == "__main__":
    main()
