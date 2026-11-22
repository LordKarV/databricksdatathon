"""Build the 'How this works' page data (issue #45): app/howto/out/how.json. No hand-typed numbers.

Every number on the page comes from here, and every entry names the repo file it came from:
- counts are computed from derived/v1, the facts export and kb/pathways;
- the model section is computed from derived/v2/model_card.json; the earlier prototype's tables are history only;
- the sealed TEST record of Likely comes from the facts export, which copies model/gold/v3/test_eval/results.json
  and the hashes in model/gold/v3/OPENING_LOG.md;
- tables and lists are copied verbatim (only backticks and bold markers stripped) from REPORT.md,
  model/MODEL_SPEC.md and research/DATASETS.md, found by their heading; a missing heading or table fails the build;
- drift check (validation H6): the REPORT.md cells the page shows for findings 1 and 2, the far-from-PIN Flagged row
  and the NFHS Fixed row are parsed and compared with counts computed from derived/v1; a mismatch fails the build;
- ranking constants are read from app/facts/engine.py, so the page cannot drift from the code.
Run from the repo root after app/facts/build.py:
    .venv-app/bin/python app/howto/build.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
OUT = Path(__file__).resolve().parent / "out"
V1 = "derived/v1"
V2CARD = "derived/v2/model_card.json"
REPORT, SPEC, DATASETS = "REPORT.md", "model/MODEL_SPEC.md", "research/DATASETS.md"
EVAL = SPEC  # the earlier prototype's evaluation, shown on the page as history only
REPO_URL = "https://github.com/LordKarV/databricksdatathon/blob/dev/"
FAR_KM = 50  # the report's threshold for "far from its own PIN"; shown on the page as a fact
FAR2_KM = 100  # the report's second threshold
HOURS = re.compile(r"\b24 ?(?:x|/|\*|hrs?|hours) ?7?\b|round the clock|\bopen(?:s)? (?:from|daily|on|till)|"
                   r"\b\d{1,2}(?::\d{2})? ?(?:am|pm)\b|opening hours|timings?\b", re.I)
# Rows of the v2 selection table the page shows; the selected model is listed first. how.js describes SELECTED.
SELECTED = "A_platt"
V2_ROWS = {"A_platt": "expert scorecard plus one calibration step", "A": "expert scorecard, nothing fitted",
           "base_rate": "the same chance for every pair"}
# (table, first cell starts with, column, pattern, count keys): the numbers a REPORT.md cell shows, group by group.
DRIFT = [
    ("findings", "Records hold text about another facility", "Verified count / denominator",
     r"^([\d,]+) / ([\d,]+) records have a sentence that names another facility \(([\d.]+)%\); in ([\d,]+) of them",
     ("other_facility", "records", "other_facility_pct", "other_facility_direct")),
    ("findings", "Listing coordinates", "Verified count / denominator",
     r"^([\d,]+) / ([\d,]+) more than (\d+) km from their own PIN \(([\d,]+) more than (\d+) km\); "
     r"([\d,]+) of the ([\d,]+) stay in the same state",
     ("coords_far", "coords_known", "far_km", "coords_far2", "far2_km", "coords_same_state", "coords_far")),
    ("flagged", "Coordinates more than 50 km from PIN", "Count after cleaning", r"^([\d,]+) of ([\d,]+) conflict",
     ("coords_far", "coords_known")),
    ("fixed", "District and NFHS join", "After", r"^([\d,]+) districts; ([\d,]+) NFHS joins", ("districts", "nfhs")),
]


def clean(cell: str) -> str:
    return re.sub(r"\*\*|`", "", cell).strip()


def section(path: str, heading: str) -> list[str]:
    """Lines under the heading that starts with `heading`, up to the next heading of the same or higher level."""
    lines = (ROOT / path).read_text().splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("#") and ln.lstrip("#").strip().startswith(heading)),
                 None)
    if start is None:
        raise SystemExit(f"{path}: heading {heading!r} not found")
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("#") and len(ln) - len(ln.lstrip("#")) <= level:
            break
        out.append(ln)
    return out


def table(path: str, heading: str, keep: list[str] | None = None) -> dict:
    rows = [ln for ln in section(path, heading) if ln.startswith("|")]
    if len(rows) < 3:
        raise SystemExit(f"{path} / {heading}: no table")
    split = lambda ln: [clean(c) for c in ln.strip().strip("|").split("|")]  # noqa: E731
    head, body = split(rows[0]), [split(r) for r in rows[2:]]
    idx = list(range(len(head))) if keep is None else [head.index(k) for k in keep]
    return {"source": path, "heading": heading, "columns": [head[i] for i in idx],
            "rows": [[r[i] for i in idx] for r in body]}


def bullets(path: str, heading: str) -> dict:
    items: list[str] = []
    for ln in section(path, heading):
        if ln.startswith("- "):
            items.append(clean(ln[2:]))
        elif ln.startswith("  ") and items:
            items[-1] += " " + clean(ln)
    if not items:
        raise SystemExit(f"{path} / {heading}: no list")
    return {"source": path, "heading": heading, "items": items}


def fact(value, source: str, how: str, of=None) -> dict:
    d = {"value": value, "source": source, "how": how}
    if of is not None:
        d["of"] = of
    return d


# ---------- counts from derived/v1 (shown on the page and compared with REPORT.md) ----------
def nearest_state(lat: np.ndarray, lon: np.ndarray, gaz: pd.DataFrame) -> np.ndarray:
    """State of the PIN centre nearest to each point (haversine)."""
    la1, lo1 = np.radians(lat)[:, None], np.radians(lon)[:, None]
    la2, lo2 = np.radians(gaz.lat.to_numpy())[None, :], np.radians(gaz.lon.to_numpy())[None, :]
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return gaz.state.to_numpy()[h.argmin(axis=1)]


def location_counts(loc: pd.DataFrame) -> dict[str, int]:
    """Far-from-PIN counts. 'Same state': the PIN centre nearest the listed point is in the state of the record's own
    PIN, both from the cleaned PIN gazetteer that raw_coords_to_pin_km is measured to."""
    gaz = pd.read_parquet(ROOT / V1 / "pin_gazetteer.parquet", columns=["pin", "state", "lat", "lon"]).dropna()
    d = loc.raw_coords_to_pin_km
    far = loc[d > FAR_KM]
    own = far.pin.map(gaz.set_index("pin").state)
    if own.isna().any():
        raise SystemExit(f"{int(own.isna().sum())} far records have a PIN missing from pin_gazetteer")
    near = nearest_state(far.raw_lat.to_numpy(), far.raw_lon.to_numpy(), gaz)
    return {"coords_known": int(d.notna().sum()), "coords_far": len(far), "coords_far2": int((d > FAR2_KM).sum()),
            "coords_same_state": int((near == own.to_numpy()).sum()),
            "districts": int(loc.district.fillna("").str.len().gt(0).sum()),
            "nfhs": int(loc.nfhs_district_name.fillna("").str.len().gt(0).sum())}


def other_facility_counts(claims: pd.DataFrame, n_records: int) -> dict[str, float]:
    """'Names another facility' = at least one claim sentence with attribution other_facility (the cleaning's own
    attribution; equal to facility_trust.n_sentences_other_facility > 0). 'Direct' = such a sentence written as if
    about the record itself, which cleaning quarantines as evidence."""
    other = claims[claims.attribution == "other_facility"]
    n = other.unique_id.nunique()
    return {"other_facility": n, "other_facility_direct": other[other.context == "direct"].unique_id.nunique(),
            "other_facility_pct": round(100 * n / n_records, 1)}


def counts() -> dict[str, float]:
    loc = pd.read_parquet(ROOT / V1 / "facility_location.parquet", columns=[
        "pin", "raw_lat", "raw_lon", "raw_coords_to_pin_km", "district", "nfhs_district_name"])
    claims = pd.read_parquet(ROOT / V1 / "claims.parquet", columns=["unique_id", "attribution", "context"])
    return {"records": len(loc), "far_km": FAR_KM, "far2_km": FAR2_KM, **location_counts(loc),
            **other_facility_counts(claims, len(loc))}


def drift_check(tables: dict, c: dict[str, float]) -> int:
    """Fail when a number REPORT.md shows on the page differs from derived/v1. Returns how many numbers were checked."""
    n = 0
    for key, first, col, pattern, keys in DRIFT:
        t = tables[key]
        row = next((r for r in t["rows"] if r[0].startswith(first)), None)
        if row is None:
            raise SystemExit(f"{REPORT} / {t['heading']}: no row starting {first!r}")
        m = re.search(pattern, row[t["columns"].index(col)])
        if m is None:
            raise SystemExit(f"{REPORT} / {t['heading']} / {first!r}: the cell no longer matches {pattern!r}")
        for shown, k in zip(m.groups(), keys, strict=True):
            if float(shown.replace(",", "")) != c[k]:
                raise SystemExit(f"{REPORT} / {t['heading']} / {first!r}: shows {shown} for {k}, derived/v1 gives "
                                 f"{c[k]:,}. Update REPORT.md and rebuild.")
            n += 1
    return n


# ---------- the app's labels today ----------
def app_bands(eng) -> Counter:
    """Pairs the app serves, by the label it shows: likely, not_verified, no_service_text, unlikely."""
    out: Counter = Counter()
    for svc, rows in eng.pairs.items():
        for p in rows:
            if p.model is None:
                raise SystemExit(f"{svc}: a pair without a derived/v2 score; the page's Labels copy describes v2 bands")
            band = eng.score(eng.fac["id"][p.fi], svc)[0]
            out["no_service_text" if eng.model_band(p) == "NO_SERVICE_TEXT" else band] += 1
    return out


def facts(c: dict[str, float]) -> dict:
    loc = pd.read_parquet(ROOT / V1 / "facility_location.parquet", columns=["unique_id", "state_final"])
    claims = pd.read_parquet(ROOT / V1 / "claims.parquet", columns=["unique_id", "text"])
    hours = claims[claims.text.str.contains(HOURS, na=False)].unique_id.nunique()
    rules = pd.read_parquet(ROOT / V1 / "evidence_rules.parquet")
    pathways = json.loads((ROOT / "kb/pathways/care_pathways.json").read_text())
    pw = pathways["pathways"] if isinstance(pathways, dict) and "pathways" in pathways else pathways
    names = [str(p.get("name") or p.get("id")).split(":")[0] for p in (pw.values() if isinstance(pw, dict) else pw)]
    sys.path.insert(0, str(APP))
    from facts import engine  # noqa: PLC0415
    eng = engine.Engine.load()
    if eng is None:
        raise SystemExit("run app/facts/build.py first")
    if "capability_p=" in (APP / "itinerary.py").read_text():  # the planner runs on stub chances until it gets one
        raise SystemExit("app/itinerary.py now passes model scores to the planner: update 'Several stops' in how.js")
    app_pairs = sum(len(v) for v in eng.pairs.values())
    bands = app_bands(eng)
    if sum(bands.values()) != app_pairs:
        raise SystemExit(f"band counts {dict(bands)} do not add up to {app_pairs} pairs")
    bihar = int((loc.state_final.str.upper() == "BIHAR").sum())
    test = sealed_test_facts(eng.test_record)
    floc, claims_src, eng_src = f"{V1}/facility_location.parquet", f"{V1}/claims.parquet", "app/facts/engine.py"
    return {
        "records": fact(len(loc), floc, "rows"),
        "far_km": fact(FAR_KM, REPORT, "threshold used in the report's location findings"),
        "far2_km": fact(FAR2_KM, REPORT, "second threshold used in the report's location findings"),
        "coords_far": fact(c["coords_far"], floc, f"raw_coords_to_pin_km > {FAR_KM}", of=c["coords_known"]),
        "coords_far2": fact(c["coords_far2"], floc, f"raw_coords_to_pin_km > {FAR2_KM}", of=c["coords_known"]),
        "coords_same_state": fact(c["coords_same_state"], f"{V1}/pin_gazetteer.parquet",
                                  "far records whose nearest PIN centre is in their own PIN's state",
                                  of=c["coords_far"]),
        "other_facility": fact(c["other_facility"], claims_src,
                               "records with a sentence whose attribution is other_facility", of=len(loc)),
        "other_facility_direct": fact(c["other_facility_direct"], claims_src,
                                      "of those, records with such a sentence in direct context",
                                      of=c["other_facility"]),
        "scores_source": fact(eng.meta["scores"], "app/facts/build.py", "which scores the app serves (meta.scores)"),
        "app_pairs": fact(app_pairs, "app/facts/build.py", "pairs for the app's services"),
        "app_likely": fact(bands["likely"], eng_src, "pairs the app labels Likely (derived/v2 band LIKELY)"),
        "app_not_verified": fact(bands["not_verified"], eng_src, "pairs labelled Not verified (band CALL_FIRST)"),
        "app_no_service_text": fact(bands["no_service_text"], eng_src,
                                    "pairs labelled No service text (band NO_SERVICE_TEXT)"),
        "app_unlikely": fact(bands["unlikely"], eng_src, "pairs labelled Unlikely (band UNLIKELY)"),
        "evidence_rules": fact(len(rules), f"{V1}/evidence_rules.parquet", "rules"),
        "handchecked": fact(int((rules.handcheck_true + rules.handcheck_false).sum()), f"{V1}/evidence_rules.parquet",
                            "hand-checked cases behind the rules"),
        "radius_km": fact(engine.RADIUS_KM, eng_src, "RADIUS_KM"),
        "tie_min": fact(engine.TIE_MIN, eng_src, "TIE_MIN: emergency order, nearest plausible first"),
        "scale_planned": fact(engine.TIME_SCALE["planned"], eng_src, "TIME_SCALE planned"),
        "n_options": fact(engine.N_OPTIONS, eng_src, "N_OPTIONS"),
        "pathways": fact(len(names), "kb/pathways/care_pathways.json", "pathways"),
        "pathway_names": fact(", ".join(str(n) for n in names), "kb/pathways/care_pathways.json", "names"),
        "bihar_records": fact(bihar, floc, "state_final = Bihar", of=len(loc)),
        "hours_records": fact(int(hours), claims_src,
                              "records with any sentence about opening hours or 24/7", of=len(loc)),
    } | site_facts(eng.site_check) | test


def site_facts(sc: dict) -> dict:
    """Listed websites the crawl flags unreliable (#117 A): the app stops citing them, the frozen model does not."""
    if not sc:
        return {}
    src = "app/facts/build.py"
    return {"sites_unreliable": fact(sc["n_unreliable"], src, "site_flags: facilities whose listed website is "
                                     "flagged, of those with a crawled website", of=sc["n_with_site"])}


def sealed_test_facts(tr: dict | None) -> dict:
    """The sealed gold v3 TEST record of LIKELY (#86, #66), as app/facts/build.py exported it from
    model/gold/v3/test_eval/results.json (hashes from OPENING_LOG.md). Empty when the app serves interim scores."""
    if not tr:
        return {}
    src, log = tr["source"], tr["log"]
    lk = "headline_decided.LIKELY_confirmed"
    return {
        "test_likely": fact(tr["k"], src, f"{lk}.k: LIKELY TEST pairs confirmed, of those with a verdict", of=tr["n"]),
        "test_likely_pct": fact(tr["pct"], src, f"{lk}.rate, as a whole percent"),
        "test_likely_lo": fact(tr["lo_pct"], src, f"{lk}.ci95 low, as a whole percent"),
        "test_likely_hi": fact(tr["hi_pct"], src, f"{lk}.ci95 high, as a whole percent"),
        "test_public_n": fact(tr["public_n"], src, "by_operator_decided.public.n"),
        "test_opened": fact(tr["opened"], log, "the one 'opened' row, UTC"),
        "test_model_version": fact(tr["model_version"], src, "model_version (equals derived/v2/model_card.json)"),
        "test_predictions_sha": fact(tr["predictions_sha256"], log, "model predictions sha256"),
        "test_labels_sha": fact(tr["labels_sha256"], log, "labels sha256 (full)"),
    }


# ---------- the model (derived/v2/model_card.json) ----------
def load_card() -> dict:
    card = json.loads((ROOT / V2CARD).read_text())
    prov = card["label_provenance"]
    # The page says these in words; stop the build if the card stops saying them.
    if "not human-checked" not in prov["wording"] or "never opened" not in prov["test_exclusion"]["note"]:
        raise SystemExit(f"{V2CARD}: label wording or TEST status changed; update 'How good it is' in how.js")
    bt = card["band_thresholds"]
    if "T >= 2" not in bt["rule"]:
        raise SystemExit(f"{V2CARD}: the LIKELY rule changed; update the Labels bullet in how.js")
    # The page quotes the rule word for word and shows the thresholds as numbers: the two must say the same (#121).
    if f"P_L and P_E >= {bt['likely']['p_location']:g}" not in bt["rule"] or \
            bt["likely"]["p_location"] != bt["likely"]["p_exists"] or "p >= t_L" not in bt["rule"]:
        raise SystemExit(f"{V2CARD}: band_thresholds.rule and band_thresholds.likely disagree; update how.js")
    if card["selected"] != SELECTED:
        raise SystemExit(f"{V2CARD}: selected model is {card['selected']!r}; update V2_ROWS and 'How good it is'")
    return card


def ci(v: list[float]) -> str:
    return f"{v[0]:.3f} [{v[1]:.3f} to {v[2]:.3f}]"


def v2_eval(card: dict) -> dict:
    """The selection table: the selected model, the unfitted scorecard and the base rate, with 95% intervals."""
    t, sel = card["selection_headline"]["table"], card["selected"]
    order = [sel, *(k for k in V2_ROWS if k != sel)]
    return {"source": V2CARD, "heading": "selection_headline.table",
            "columns": ["Model", "DEV pairs (confirmed)", "Log loss, lower is better [95% interval]",
                        "AUROC [95% interval]", "Calibration error, ECE [95% interval]"],
            "rows": [[f"{k}: {V2_ROWS[k]}" + (" (selected)" if k == sel else ""),
                      f"{t[k]['n']} ({t[k]['n_pos']})", ci(t[k]["log_loss"]), ci(t[k]["auroc"]), ci(t[k]["ece"])]
                     for k in order]}


def v2_facts(card: dict) -> dict:
    lk, band = card["thresholds"]["likely"], card["band_thresholds"]["likely"]
    em, pl = card["conformal"]["emergency"], card["conformal"]["planned"]
    pub = card["public_vs_private"]["public"]
    v1_note = next((c for c in card["caveats"] if c.startswith("v1 numbers")), None)
    if v1_note is None:
        raise SystemExit(f"{V2CARD}: caveat about v1 numbers not found")
    src = V2CARD
    return {
        "v2_model": fact(card["selected"], src, "selected"),
        "v2_meaning": fact(card["selected_meaning"], src, "selected_meaning"),
        "likely_p": fact(band["p"], src, "band_thresholds.likely.p (t_L)"),
        "likely_p_location": fact(band["p_location"], src, "band_thresholds.likely.p_location"),
        "likely_p_exists": fact(band["p_exists"], src, "band_thresholds.likely.p_exists"),
        "band_rule": fact(card["band_thresholds"]["rule"], src, "band_thresholds.rule, word for word"),
        "likely_dev": fact(lk["k_correct"], src, "thresholds.likely: LIKELY DEV pairs confirmed", of=lk["n"]),
        "likely_dev_lo": fact(lk["wilson95"][0], src, "thresholds.likely.wilson95 low"),
        "likely_dev_hi": fact(lk["wilson95"][1], src, "thresholds.likely.wilson95 high"),
        "conf_em_k": fact(em["k"], src, "conformal.emergency.k"),
        "conf_em": fact(em["coverage_k"], src, "conformal.emergency.coverage_k", of=em["n_queries"]),
        "conf_em_random": fact(em["random_order_coverage"], src, "conformal.emergency.random_order_coverage"),
        "conf_pl_k": fact(pl["k"], src, "conformal.planned.k"),
        "conf_pl": fact(pl["coverage_k"], src, "conformal.planned.coverage_k", of=pl["n_queries"]),
        "conf_pl_random": fact(pl["random_order_coverage"], src, "conformal.planned.random_order_coverage"),
        "conformal_note": fact(card["conformal_note"], src, "conformal_note"),
        "public_pairs": fact(pub["n"], src, "public_vs_private.public.n"),
        "public_contradicted": fact(pub["contradicted"], src, "public_vs_private.public.contradicted"),
        "v1_note": fact(v1_note, src, "caveats"),
    }


def source_classes() -> dict:
    with open(ROOT / V1 / "source_classes.csv") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: -int(r["n_urls"]))
    return {"source": f"{V1}/source_classes.csv", "heading": "source classes", "columns":
            ["Source class", "URLs", "Reliability", "90% interval"],
            "rows": [[r["source_class"].replace("_", " "), f"{int(r['n_urls']):,}", f"{float(r['reliability']):.2f}",
                      f"{float(r['ci05']):.2f} to {float(r['ci95']):.2f}"] for r in rows]}


def main() -> None:
    card = load_card()
    c = counts()
    how = {
        "built_at": time.strftime("%Y-%m-%d", time.gmtime()),
        "repo_url": REPO_URL,
        "facts": facts(c) | v2_facts(card),
        "tables": {
            "findings": table(REPORT, "1.1 The 5 findings",
                              ["Finding", "Verified count / denominator", "What goes wrong for a patient"]),
            "fixed": table(REPORT, "Fixed"),
            "flagged": table(REPORT, "Flagged"),
            "cannot": table(REPORT, "Cannot be handled by cleaning"),
            "v2_eval": v2_eval(card),
            "labels": table(EVAL, "4.1 What the labels are"),
            "auroc": table(EVAL, "4.2 Pair-level discrimination",
                           ["system", "all 71 test", "searched only (39, 17 pos)"]),
            "top1": table(EVAL, "4.6 End-to-end top-1", ["system", "confirmed top-1 [Wilson]",
                                                       "contradicted, wrong place or nonexistent (Unsafe@1)"]),
            "sources": source_classes(),
            "datasets": table(DATASETS, "Summary", ["Dataset", "Role", "Licence for a public demo"]),
        },
        "lists": {"did_not_work": bullets(EVAL, "4.11 Claims that did not survive review")},
    }
    t = how["tables"]
    n_checked = drift_check(t, c)
    for k, n in {"n_fixed": "fixed", "n_flagged": "flagged", "n_cannot": "cannot"}.items():
        how["facts"][k] = fact(len(t[n]["rows"]), t[n]["source"], f"rows in the '{t[n]['heading']}' table")
    OUT.mkdir(exist_ok=True)
    (OUT / "how.json").write_text(json.dumps(how, indent=1, ensure_ascii=False))
    size = (OUT / "how.json").stat().st_size
    print(f"how.json: {len(how['facts'])} facts, {len(how['tables'])} tables, {size / 1000:.1f} KB; "
          f"drift check: {n_checked} REPORT.md numbers match derived/v1")


if __name__ == "__main__":
    main()
