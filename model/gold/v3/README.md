# Gold v3: 300 DEV pairs labelled from the web, and a sealed TEST (issue #51)

Custodian: tm-AA2026. The custodian does not work on #11's model fit.

| File | What | Committed |
| --- | --- | --- |
| `build_sample_v3.py` | stratified sample, seed 20261121 | yes |
| `dev_sample.json` | 300 DEV pairs, with what a labeller needs (name, place, own website domain) | yes |
| `test_sample.json` | 150 TEST pair ids only | yes |
| `overlap.json` | the 25% of each split labelled twice (75 DEV, 38 TEST) | yes |
| `sample_stats.json` | frame size, pool sizes and inclusion probability per cell | yes |
| `dev_labels.json` | DEV labels plus the report below (`report`) | yes |
| `merge_labels.py` | merges labelling batches, computes kappa and the no_info rates | yes |
| `seal.py` | commitment scheme for the TEST labels | yes |
| `test_labels.sha256` | SHA-256 of the TEST labels file | when TEST is labelled |
| `test_labels.json` | TEST labels | **no**: kept by the custodian until "[type: update] model frozen" on #11 |

## Sample

- **Services:** the 7 core app services, plus `emergency_24x7` and `stemi_thrombolysis` (scored by the planner as
  `emergency_24x7` and `thrombolysis`).
- **Strata per service:**
  - **strong:** grade "strong"; for the two extra services, 2+ evidence sentences.
  - **weak:** a moderate, weak or tag-only grade; or exactly 1 sentence.
  - **suspect:** a positive claim plus a risk:
    - the claim is attributed elsewhere, or contradicted by other text;
    - a location, name-collision or service-elsewhere flag;
    - or the map point is more than 50 km from its own PIN.
  - **no_mention:** no claim at all, at a public facility (by name) or a large one (6+ services claimed).
- **Frame:** a verdict must be reachable. The record's own website domain (`record_trust.website_class` own or
  government) must match the facility's name (a distinctive name word, or the initials) and be shared by at most
  3 records. That leaves 6,389 of 9,947 facilities.
  - **Why:** a 20-pair pilot on a looser frame (any own site or a public name, with the "best source URL")
    reached 60% no_info. In 9 of the 20 pilot pairs the URL belonged to another facility or a directory. The pilot
    labels are not used.
- **Excluded:** every facility in `model/gold/` (any file) or `derived/v1/gold_pairs`, plus their duplicate groups.
  One pair per facility across DEV and TEST.
- **Draw:** each (service, stratum) cell is split into the focus states (Bihar, UP, Jharkhand, Odisha, Assam) and
  the rest, and each sub-cell is a simple random sample.
  - The scarcest cells are drawn first.
  - The inclusion probability is k/N per sub-cell. It is approximate where one facility sits in several pools.
  - TEST is every third pick within each cell, after a shuffle.
  - Focus-state share: 40% of DEV, 41% of TEST.
- **Thin cell:** `stemi_thrombolysis` has small strong and suspect pools.

## Rubric (applied exactly; full text in `RUBRIC.md` and `FETCH_ONLY.md`)

Labellers see the name, place and website, never the dataset's claims or the stratum.

- **exists:** yes / no / unclear.
- **location_ok:** yes / no / unclear.
- **service:**
  - **confirmed:** the facility's own site, a government list or scheme page, or a reputable page with
    facility-specific detail that is not a copy of a directory listing, dated within about 5 years.
  - **contradicted:** any of:
    - credible evidence it does not offer the service;
    - an unrelated single-specialty facility;
    - the facility is closed;
    - the claim belongs to another facility;
    - an exhaustive official list omits it.
  - **no_info:** neither.
- **Also recorded:** confidence; up to 3 URLs that were read; a verbatim quote of 25 words or fewer; notes;
  searches used.
- **Limits:** at most 5 web searches per pair. Directories can support "exists" only. Public pages only,
  respect robots.txt, no personal data. One doctor-named clinic in a note was made generic before commit.
- **Process:** each pair was labelled by an independent agent working alone on its batch of 25 (labeller A). The
  overlap pairs were labelled again by separate agents that could not see A's files (labeller B).

## DEV results (300 pairs)

| | confirmed | contradicted | no_info |
| --- | --- | --- | --- |
| all | 107 | 27 | 166 (55.3%) |
| strong | 38 | 3 | 36 |
| weak | 25 | 11 | 41 |
| suspect | 18 | 3 | 47 |
| no_mention | 26 | 10 | 42 |

- **Agreement:** on the 75 double-labelled pairs, raw agreement is 90.7%.
  - Cohen's kappa is **0.834** on the 3-way verdict and **0.840** on decided vs no_info. v2 had 0.38.
  - Disagreements: 3 no_info vs confirmed, 2 confirmed vs no_info, 1 confirmed vs contradicted, 1 no_info vs
    contradicted.
  - Both labellers often met the same dead site. Agreement on "no_info" is the largest cell (36 of 75), so kappa
    partly measures shared access, not only shared judgement.
- **no_info is 55%**, above the 40% target. Most no_info pairs have a dead, parked, hijacked or wrong-facility
  website. That is a finding about the dataset's `websites` field, and it limits what web labels can reach.
- **Search budget:** the session's shared web-search budget (200 searches) ran out after 191 counted searches.
  - 100 primary labels were made **fetch-only**: the facility's own pages plus reachable official pages, no
    search. They are tagged `method: "fetch_only"`.
  - Their no_info rate is 54%, against 56% for searched labels. Search was used mostly to find a facility's real
    site once the given one failed.
  - Fetch-only no_info pairs are the first to relabel when search is available.
- **Use for #11:** DEV only. Weight by 1 / `inclusion_prob` for frame-level estimates, and report precision per
  stratum.

## Sealing protocol (TEST)

1. Label `test_sample.json` and keep `test_labels.json` outside the repo
   (`~/.cache/referral-saathi-gold-v3/test_labels.json`):
   `merge_labels.py test <batches> --out <that path>` refuses a path inside the repo.
2. `python model/gold/v3/seal.py commit` checks that the labels cover exactly the TEST ids, then writes
   `test_labels.sha256`. Commit that file.
3. After the lead posts "[type: update] model frozen" with a model hash on #11, publish `test_labels.json`
   unchanged. Anyone can then run `python model/gold/v3/seal.py verify --labels model/gold/v3/test_labels.json`.

Status: TEST is not labelled yet. It needs the web-search budget, which this session has used up.
