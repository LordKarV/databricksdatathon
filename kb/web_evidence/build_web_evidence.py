"""Quote-verified facts from the crawled facility websites: site identity, services, hours and details.

Inputs (read-only): kb/crawl/pages.parquet, kb/crawl/sites.parquet, data/crawl/pages/*.json.gz, kb/taxonomy/lexicon.json,
data/raw/facilities.parquet (name, city), cleaning/geo_identity/facility_location.parquet (usable records, PIN, district),
audit/scale/scale_flags.parquet (capacity and type, for plausibility). Optional: out/llm_hours.parquet from web_llm_hours.py.

Reused, not copied: the taxonomy matcher (kb/taxonomy/lexicon_src.match, clause-level exclusions), the operational-detail
extractors and their cue, plausibility and status rules (kb/vf_details/patterns.py and extract.py), and the sentence-kind
patterns of cleaning/claims/lexicon.py. That keeps web facts in the same schema as the VF facts.

Writes (kb/web_evidence/out/): page_identity.parquet, site_identity.parquet, web_services.parquet, web_hours.parquet,
web_details.parquet, hour_candidates.parquet, stats_build.json. Every fact row carries a quote that is asserted to be an
exact substring of the stored page field (title, text or chrome_text) named in the row.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python build_web_evidence.py
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

import pandas as pd
from rapidfuzz import fuzz

ROOT = "/Users/karthikvattem/projects/datathon"
D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
sys.path.insert(0, f"{ROOT}/kb/vf_details")
import patterns as P  # noqa: E402  (also puts cleaning/claims on sys.path and imports its lexicon as P.L)

sys.path.insert(0, f"{ROOT}/kb/taxonomy")
import lexicon_src as LS  # noqa: E402

_spec = importlib.util.spec_from_file_location("vf_extract", f"{ROOT}/kb/vf_details/extract.py")
VE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VE)
sys.path.insert(0, f"{ROOT}/audit/provenance")
from domains import GENERIC_NAME_TOKENS  # noqa: E402

L = P.L
OK_STATUS = ("ok", "ok_thin")
FIELDS = ("title", "text", "chrome_text")
LEX = json.load(open(f"{ROOT}/kb/taxonomy/lexicon.json"))
COMP = LS.compile_specs({k: v for k, v in LEX["services"].items() if v.get("in_taxonomy")})
ANY_INCLUDE = re.compile("|".join(f"(?:{c['include'].pattern})" for c in COMP.values()), re.I)
NONOFFER = {k: re.compile(p, re.I) for k, p in LEX["shared_cues"]["nonoffer"].items()}
# "non-surgical" negates only a surgery; on the web it mostly describes cath lab, chemotherapy or medical abortion as non-surgical
SURGICAL = {"cardiac_surgery", "neurosurgery", "surgical_oncology", "orthopaedic_trauma_surgery", "cataract_surgery", "kidney_transplant", "emergency_csection"}
NEG_NONSURG = re.compile(NONOFFER["negation"].pattern.replace("|non[- ]surgical", ""), re.I)
assert NEG_NONSURG.pattern != NONOFFER["negation"].pattern
WEAK = {k: re.compile(p, re.I) for k, p in LEX["shared_cues"]["weakening"].items()}

MAX_SEG = 400          # longer lines are split into sentences before matching
QUOTE_CAP = 300        # a longer segment is quoted as a word-snapped window around the hit
EDU_URL = re.compile(r"/(blogs?|news|articles?|health-?tips|tips|faqs?|posts?|knowledge|patient-education|diseases?|conditions?|symptoms?|awareness)(/|-|$)|/20\d\d/", re.I)
EDU_SEG = re.compile(r"\?\s*$|^\s*(what|why|how|when|who|which|can|does|do|is|are)\b[^.]*\?|symptoms of|causes of|risk factors|signs of|"
                     r"\bis an? (procedure|treatment|condition|test|disease|disorder|technique)\b|\b(may|might|can) be (needed|required|recommended)\b", re.I)
JOB = re.compile(r"vacanc|\bhiring\b|\bjobs?\b|careers?\b|recruit|walk-?in interview|apply now", re.I)
SERVICE_PAGE_URL = re.compile(r"servic|department|speciali|specialit|facilit|centre-of-excellence|center-of-excellence|treatment", re.I)
SERVICE_PAGE_ROLES = ("link:services", "link:specialty", "link:facilities")
HEAD = re.compile(r":\s*$|timing|hours|\bopd\b|\bopen|\b(mon|tue|wed|thu|fri|sat|sun)", re.I)
TIME_LINE = re.compile(P.TIME_ANY.pattern + r"|24\s*[x/*]\s*7|24\s*hours?|round[- ]the[- ]clock", re.I)
EMERG_PHONE = re.compile(r"\b(emergenc\w*|casualty|ambulance|help ?line|24\s*[x/*]\s*7)\b[^\n\[]{0,40}\[phone\]", re.I)
PIN_ANY = re.compile(r"(?:pin(?:\s*code)?|[A-Za-z]{3,})\s*[-:,.]?\s*([1-8]\d{2}\s?\d{3})(?!\d)", re.I)
PARKED = re.compile(r"domain (?:name )?(?:is |may be )?for sale|buy this domain|this domain (?:has )?expired|domain has expired|domain is parked|"
                    r"parked (?:free|domain)|is available for (?:purchase|registration)|hugedomains|sedo\b|dan\.com|spaceship\.com|account (?:has been )?suspended", re.I)
STAFF_TITLE = re.compile(r"^\W*(?:dr\b|consultant|senior|sr\.?|associate|assistant|junior|head|hod|chief|director|visiting)\b.{0,80}"
                         r"(?:consultant|surgeon|specialist|physician|\w+ologist|\w+iatrist|\w+ician)\b", re.I)
# The line itself says the facility has it: a first-person or unit word, a 24x7 badge, or a list item on a services page.
# Educational lines ("dialysis for advanced kidney failure", "after childbirth") have none of these.
OFFER_CUE = re.compile(r"\b(?:we|our|ours)\b|\bavailable\b|\bdepartments?\b|\bdept\b|\bunits?\b|\bwing\b|\bfacilit\w*|\bservices?\b|\bclinics?\b"
                       r"|\bcent(?:re|er)s?\b|24\s*[x/*\u00d7]\s*7|24\s*hours?|round[- ]the[- ]clock", re.I)
SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
HOUR_TYPES = {"hours_24x7", "opd_hours", "hours_dialysis_shifts"}
BAD_SCHED = {"no_meridiem", "close_before_open", "odd_open_time", "days_unparsed", "meridiem_guessed"}


# ---------------------------------------------------------------- text helpers
def segments(t: str) -> list[tuple[int, int]]:
    """Line spans, with lines over MAX_SEG characters split at sentence ends; leading/trailing blanks trimmed."""
    out = []
    for m in re.finditer(r"[^\n]+", t):
        a, b = m.span()
        cuts = [a] + ([a + x.end() for x in SENT_END.finditer(m.group())] if b - a > MAX_SEG else []) + [b]
        for s, e in zip(cuts, cuts[1:]):
            seg = t[s:e]
            s2 = s + len(seg) - len(seg.lstrip())
            e2 = e - (len(seg) - len(seg.rstrip()))
            if e2 > s2:
                out.append((s2, e2))
    return out


def detail_segments(t: str, segs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Like segments(), but a short heading line ("Opening Hours:", "OPD Timings") is joined to the next line when that
    line carries a time, so the scope word stays with the hours. The joined span is still an exact substring of t."""
    out = []
    for i, (a, b) in enumerate(segs):
        if i and TIME_LINE.search(t[a:b]):
            pa, pb = segs[i - 1]
            if pb - pa <= 60 and "\n" in t[pb:a + 1] and t[pb:a].strip() == "" and HEAD.search(t[pa:pb]) and not TIME_LINE.search(t[pa:pb]):
                out.append((pa, b))
                continue
        out.append((a, b))
    return out


def window(s: str, a: int, b: int, cap: int = QUOTE_CAP) -> str:
    """Exact substring of s: s itself when short, else a word-snapped window around [a, b)."""
    if len(s) <= cap:
        return s
    lo, hi = max(0, a - (cap - (b - a)) // 2), min(len(s), b + (cap - (b - a)) // 2)
    while lo > 0 and s[lo - 1] not in " ,;(\n":
        lo -= 1
    while hi < len(s) and s[hi] not in " ,;)\n":
        hi += 1
    return s[lo:hi].strip()


def line_quote(t: str, a: int, b: int, cap: int = 200) -> str:
    lo = t.rfind("\n", 0, a) + 1
    hi = t.find("\n", b)
    hi = len(t) if hi < 0 else hi
    return window(t[lo:hi], a - lo, b - lo, cap)


def sentence_kind(s: str) -> str:
    """Same order as cleaning/claims/build_claims.kind, plus a web-only staff case: a short doctor-card line such as
    'Consultant Interventional Cardiologist' names a job title, not a unit."""
    if len(s) <= 120 and STAFF_TITLE.search(s):
        return "staff"
    for k, rx in (("template", L.TEMPLATE), ("research", L.RESEARCH), ("directory", L.DIRECTORY), ("staff", L.STAFF)):
        if rx.search(s):
            return k
    return "list" if L.is_list(s) else "specific"


# ---------------------------------------------------------------- identity
def name_rx(tokens: list[str]) -> re.Pattern | None:
    return re.compile(r"(?<![a-z0-9])" + r"[\W_]*".join(map(re.escape, tokens)) + r"(?![a-z0-9])", re.I) if tokens else None


GENERIC_FOLLOW = r"(?:[\W_]*[a-z0-9]+){0,1}?[\W_]*(?:hospitals?|clinics?|dental|eye|nursing|care|cent(?:re|er)|health|medical|diagnostics?|dentistry|smile)"
CORE_CUT = re.compile(r",|\s[-|]\s|\(|\s(?:in|near|at|opp\.?|opposite)\s", re.I)


def facility_keys(fac: dict) -> dict:
    """Name patterns for one record, built from the core name (text before the first comma, dash, bracket or ' in ').
    The distinctive part drops generic words and the record's own city/district words, so 'Amritsar Eye Hospital' does
    not count a city mention as a name match. 'head' is the weaker fallback: the first two distinctive words, or the
    first one (6+ letters) followed by a facility word ('Dingra Dental' for 'Dingra Dental and Facial Cosmetic Clinic')."""
    core = CORE_CUT.split(fac["name"] or "")[0]
    toks = re.findall(r"[a-z0-9]+", core.lower())
    loc = set(re.findall(r"[a-z0-9]+", f"{fac['city'] or ''} {fac['district'] or ''}".lower()))
    dist = [t for t in toks if t not in GENERIC_NAME_TOKENS and t not in loc]
    key = "".join(dist)
    head = None
    if len(dist) >= 2:  # with one distinctive word, 'dist' already is that word
        alts = [r"[\W_]*".join(map(re.escape, dist[:2]))] if len(dist) >= 3 and len(dist[0] + dist[1]) >= 6 else []
        alts += [re.escape(dist[0]) + GENERIC_FOLLOW] if len(dist[0]) >= 5 else []
        head = re.compile(r"(?<![a-z0-9])(?:" + "|".join(alts) + r")(?![a-z0-9])", re.I) if alts else None
    locs = [x for x in dict.fromkeys([fac["city"], fac["district"]]) if x and len(x) >= 3]
    return {"full": name_rx(toks) if len(toks) >= 2 or len("".join(toks)) >= 5 else None,
            "dist": name_rx(dist) if len(key) >= 5 else None,
            "fuzzy": " ".join(dist) if len(key) >= 6 else None,
            "head": head,
            "pin": re.compile(rf"(?<!\d){fac['pin'][:3]}\s?{fac['pin'][3:]}(?!\d)") if fac["pin"] else None,
            "loc": re.compile(r"(?<![a-z])(" + "|".join(re.escape(x) for x in locs) + r")(?![a-z])", re.I) if locs else None,
            "pin_str": fac["pin"]}


def page_identity(doc: dict, k: dict) -> dict:
    """Name, PIN and locality evidence on one stored page, each with an exact quote and the field it sits in."""
    r = {"parked": bool(PARKED.search(f"{doc['title']} {doc['text'][:3000]}")), "name_how": "none", "name_quote": None, "name_field": None, "pin_quote": None, "pin_field": None,
         "loc_quote": None, "loc_field": None, "other_pins": []}
    for how in ("full", "dist"):
        if r["name_how"] == "none" and k[how]:
            for f in FIELDS:
                m = k[how].search(doc[f] or "")
                if m:
                    r.update(name_how=how, name_quote=line_quote(doc[f], *m.span()), name_field=f)
                    break
    if r["name_how"] == "none" and k["fuzzy"]:
        for f in FIELDS:
            t = (doc[f] or "")[:60000]
            al = fuzz.partial_ratio_alignment(k["fuzzy"], t.lower(), score_cutoff=90) if t else None
            if al and al.dest_end - al.dest_start >= 0.8 * len(k["fuzzy"]):
                r.update(name_how="fuzzy", name_quote=line_quote(t, al.dest_start, al.dest_end), name_field=f)
                break
    if r["name_how"] == "none" and k["head"]:
        for f in FIELDS:
            m = k["head"].search(doc[f] or "")
            if m:
                r.update(name_how="head", name_quote=line_quote(doc[f], *m.span()), name_field=f)
                break
    for f in FIELDS:
        t = doc[f] or ""
        if k["pin"] and r["pin_quote"] is None and (m := k["pin"].search(t)):
            r.update(pin_quote=line_quote(t, *m.span()), pin_field=f)
        if k["loc"] and r["loc_quote"] is None and (m := k["loc"].search(t)):
            r.update(loc_quote=line_quote(t, *m.span()), loc_field=f)
        r["other_pins"] += [p.replace(" ", "") for p in PIN_ANY.findall(t) if p.replace(" ", "") != k["pin_str"]]
    r["other_pins"] = sorted(set(r["other_pins"]))[:10]
    return r


# ---------------------------------------------------------------- facts on one file
def service_hits(t: str, segs: list[tuple[int, int]]) -> list[dict]:
    rows = []
    for a, b in segs:
        s = t[a:b]
        if not ANY_INCLUDE.search(s):
            continue
        hits = LS.match(s, COMP)
        if not hits:
            continue
        weak = next((k for k, rx in WEAK.items() if rx.search(s)), "")
        kind = sentence_kind(s)
        for sid in hits:
            m = COMP[sid]["include"].search(s)
            q = window(s, *(m.span() if m else (0, min(len(s), QUOTE_CAP))))
            # cues count only in the clause that carries the hit: "Dialysis unit; no ICU facility" is not a dialysis negation
            clauses = [c for c in LS.CLAUSE_SPLIT.split(s) if COMP[sid]["include"].search(c)] or [s]
            neg_extra = COMP[sid]["negation_extra"]
            neg = NONOFFER["negation"] if sid in SURGICAL else NEG_NONSURG
            negated = all(neg.search(c) or (neg_extra and neg_extra.search(c)) for c in clauses)
            nonoffer = "negation" if negated else next((k for k, rx in NONOFFER.items() if k != "negation" and all(rx.search(c) for c in clauses)), "")
            rows.append({"service_id": sid, "seg_start": a, "segment": s, "quote": q, "match": m.group(0) if m else "",
                         "negated": bool(negated), "nonoffer_cue": nonoffer,
                         "weak_cue": weak, "kind": kind, "edu_seg": bool(EDU_SEG.search(s)), "job_seg": bool(JOB.search(s)),
                         "line_kind": "item" if len(s.split()) <= 6 and not re.search(r"[.!?]$", s) else "sentence"})
    return rows


def detail_hits(t: str, segs: list[tuple[int, int]], names: str) -> tuple[list[dict], list[dict]]:
    rows, cands = [], []
    for a, b in detail_segments(t, segs):
        s = t[a:b]
        if EMERG_PHONE.search(s):
            m = EMERG_PHONE.search(s)
            sc = "ambulance" if "ambul" in m.group(1).lower() else ("helpline" if "help" in m.group(1).lower() else "emergency")
            rows.append({"fact_type": "emergency_phone", "attribute": sc, "value_num": None, "value_text": "number_redacted_in_crawl",
                         "quote": window(s, *m.span()), "match": m.group(0), "seg_start": a, "segment": s})
        if not VE.PREFILTER.search(s):
            continue
        for h in P.all_hits(s, names):
            rows.append({"fact_type": h.fact_type, "attribute": h.attribute, "value_num": h.value_num, "value_text": h.value_text,
                         "quote": P.clause_quote(s, h.start, h.end, cap=QUOTE_CAP), "match": s[h.start:h.end], "seg_start": a, "segment": s})
        if P.is_hour_candidate(s) and len(s) <= 500:
            p = P.parse_schedule(s)
            if p is None or "dated_event" not in p["problems"]:
                reason = "no_parse" if p is None else ",".join(sorted(BAD_SCHED & set(p["problems"])))
                if reason:
                    cands.append({"seg_start": a, "text": s, "reason": reason})
    return rows, cands


def process_file(job: tuple[str, list[dict], str]) -> dict:
    path, facs, names = job
    doc = json.load(gzip.open(os.path.join(ROOT, path)))
    doc = {f: doc.get(f) or "" for f in FIELDS} | {"url_final": doc.get("url_final")}
    ident = [{"unique_id": f["unique_id"], **page_identity(doc, facility_keys(f))} for f in facs]
    svc, det, cand = [], [], []
    for field in ("text", "chrome_text"):
        t = doc[field]
        segs = segments(t)
        svc += [{**r, "field": field} for r in service_hits(t, segs)]
        d, c = detail_hits(t, segs, names)
        det += [{**r, "field": field} for r in d]
        cand += [{**r, "field": field} for r in c]
    for r in svc + det:
        assert r["quote"] and r["quote"] in doc[r["field"]], (path, r["quote"])
    return {"path": path, "ident": ident, "svc": svc, "det": det, "cand": cand}


# ---------------------------------------------------------------- tables
def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict]]:
    pages = pd.read_parquet(f"{ROOT}/kb/crawl/pages.parquet")
    sites = pd.read_parquet(f"{ROOT}/kb/crawl/sites.parquet")
    pages = pages[pages.path.notna()].merge(sites[["target_id", "kind", "site", "domain", "site_status", "site_spam_injected"]], on="target_id")
    pages = pages[pages.site_status.isin(OK_STATUS)].reset_index(drop=True)
    loc = pd.read_parquet(f"{ROOT}/cleaning/geo_identity/facility_location.parquet", columns=["unique_id", "name", "address_city", "pin", "district"])
    loc = loc.drop_duplicates("unique_id")
    facs = {r.unique_id: {"unique_id": r.unique_id, "name": r.name, "city": r.address_city if isinstance(r.address_city, str) else None,
                          "district": r.district if isinstance(r.district, str) else None,
                          "pin": f"{int(r.pin):06d}" if pd.notna(r.pin) and 100000 <= r.pin <= 999999 else None}
            for r in loc.itertuples(index=False)}
    pages["unique_ids"] = pages.unique_ids.map(lambda x: [u for u in x if u in facs])
    pages = pages[pages.unique_ids.map(len) > 0].reset_index(drop=True)
    pages["page_id"] = pages.index.astype(int)
    host = pages.final_url.fillna(pages.url).str.lower().str.replace(r"^https?://", "", regex=True).str.split("/").str[0]
    host = host.str.replace(r":\d+$", "", regex=True).str.replace(r"^(www|m)\.", "", regex=True)
    same_org = pages.target_id.map(sites.set_index("target_id").site_redirect_same_org).fillna(False).astype(bool)
    pages["off_site"] = pd.Series([not (h == st or h.endswith("." + st)) for h, st in zip(host, pages.site)], index=pages.index) & ~same_org
    pages["edu_url"] = pages.final_url.fillna(pages.url).str.contains(EDU_URL.pattern.replace("(", "(?:").replace("(?:?:", "(?:"), case=False)
    pages["services_page"] = pages.role.isin(SERVICE_PAGE_ROLES) | pages.final_url.fillna("").str.replace(r"^https?://[^/]+", "", regex=True).str.contains(SERVICE_PAGE_URL)
    return pages, sites, facs


def domain_matches(site: str, name: str) -> bool:
    label = re.sub(r"[^a-z0-9]", "", site.split(".")[0])
    key = "".join(t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in GENERIC_NAME_TOKENS)
    return len(key) >= 4 and fuzz.partial_ratio(key, label) >= 85


def place_names() -> set[str]:
    g = pd.read_parquet(f"{ROOT}/derived/v1/place_gazetteer.parquet", columns=["name", "kind"])
    return {re.sub(r"[^a-z]", "", n) for n in g[g.kind.isin(["district", "city"])].name.str.lower()} - {""}


def domain_other_place(site: str, fac: dict, places: set[str]) -> str:
    """A district or city name (5+ letters) in the site's host label that is not the record's own place or part of its
    name: guptahospitalbathinda.com for a Gupta Hospital in Amritsar. Empty string when none."""
    label = re.sub(r"[^a-z]", "", site.split(".")[0])
    own = re.sub(r"[^a-z]", "", f"{fac['name']} {fac['city']} {fac['district']}".lower())
    hits = [p for p in places if len(p) >= 5 and p in label and p not in own]
    return max(hits, key=len) if hits else ""


def quote_other_place(q: str, fac: dict, places: set[str]) -> str:
    """A district or city word (5+ letters) after 'in' or 'at' in the name line, other than the record's own place:
    'Best Multi-Specialty Hospital in Hyderabad | Medistar Hospitals' for a Medistar record in Vadodara."""
    own = re.sub(r"[^a-z]", "", f"{fac['name']} {fac['city']} {fac['district']}".lower())
    for m in re.finditer(r"\b(?:in|at)\s+([A-Za-z]+(?:\s[A-Za-z]+)?)", q or ""):
        for cand in (m.group(1), m.group(1).split()[0]):
            c = re.sub(r"[^a-z]", "", cand.lower())
            if len(c) >= 5 and c in places and c not in own:
                return c
    return ""


def site_identity(pi: pd.DataFrame, pages: pd.DataFrame, facs: dict) -> pd.DataFrame:
    """One row per (target, record). Confidence:
    high   = facility name and (own PIN or own city/district) on the site's pages;
    medium = full/distinctive/fuzzy name, or the weaker head name with a domain that spells the name, in both cases with no
             conflict (only other PINs on the site, or another place in the host name); or own PIN plus such a domain;
    low    = locality, PIN or domain only, or a name with a conflict;
    none   = nothing. Branch pages need name and locality (the chain brand alone names every branch).
    attributable = high or medium, and not a chain homepage."""
    pi = pi.merge(pages[["page_id", "target_id", "kind", "site", "final_url", "fetched_at", "services_page", "site_spam_injected", "site_status"]], on="page_id")
    rows = []
    rank = {"full": 0, "dist": 1, "fuzzy": 2, "head": 3, "none": 9}
    places = place_names()
    for (tid, uid), g in pi.groupby(["target_id", "unique_id"], sort=False):
        g = g.assign(r=g.name_how.map(rank)).sort_values("r")
        best = g.iloc[0]
        name = best.name_how != "none"
        strong = best.name_how in ("full", "dist", "fuzzy")
        pin_g, loc_g = g[g.pin_quote.notna()], g[g.loc_quote.notna()]
        pin, locality = len(pin_g) > 0, len(loc_g) > 0
        other_pin_only = not pin and not locality and any(len(x) for x in g.other_pins)
        kind = best.kind
        dm = domain_matches(best.site, facs[uid]["name"])
        other_place = domain_other_place(best.site, facs[uid], places) or (quote_other_place(best.name_quote, facs[uid], places) if name and not (pin or locality) else "")
        parked = bool(g.parked.any())  # a for-sale or expired page that spells the name in its host is not the facility
        conflict = other_pin_only or bool(other_place)
        if parked:
            conf = "none"
        elif kind == "branch":
            conf = "high" if name and (pin or locality) else ("low" if name or pin or locality else "none")
        elif name and (pin or locality):
            conf = "high"
        elif (strong and not conflict) or (name and dm and not conflict) or (pin and dm):
            conf = "medium"
        elif name or pin or locality or dm:
            conf = "low"
        else:
            conf = "none"
        rows.append({"target_id": tid, "unique_id": uid, "kind": kind, "site": best.site, "site_status": best.site_status,
                     "site_spam_injected": bool(best.site_spam_injected) if pd.notna(best.site_spam_injected) else False,
                     "n_pages": len(g), "has_services_page": bool(g.services_page.any()),
                     "name_how": best.name_how, "name_quote": best.name_quote, "name_field": best.name_field,
                     "name_url": best.final_url if name else None,
                     "pin_found": pin, "pin_quote": pin_g.pin_quote.iloc[0] if pin else None, "pin_field": pin_g.pin_field.iloc[0] if pin else None,
                     "pin_url": pin_g.final_url.iloc[0] if pin else None, "pin_page_id": int(pin_g.page_id.iloc[0]) if pin else -1,
                     "locality_found": locality, "locality_quote": loc_g.loc_quote.iloc[0] if locality else None,
                     "locality_field": loc_g.loc_field.iloc[0] if locality else None, "locality_url": loc_g.final_url.iloc[0] if locality else None,
                     "locality_page_id": int(loc_g.page_id.iloc[0]) if locality else -1, "name_page_id": int(best.page_id) if name else -1,
                     "parked_page": parked, "other_pin_only": other_pin_only, "domain_other_place": other_place, "domain_matches_name": dm, "confidence": conf,
                     "attributable": conf in ("high", "medium") and kind != "shared_home"})
    return pd.DataFrame(rows)


def attach(rows: pd.DataFrame, pages: pd.DataFrame, si: pd.DataFrame, page_ok: set) -> pd.DataFrame:
    """File-level hits -> one row per (record, page) that passes identity; chain homepages kept but not attributable.
    A page on another host (a record-given deep URL off the site, not a same-organisation redirect) must itself show the
    name and the PIN or locality. Identity-failed rows are dropped here and only counted."""
    pg = pages[["page_id", "path", "target_id", "unique_ids", "off_site", "url", "final_url", "fetched_at", "role", "edu_url", "services_page"]]
    x = rows.merge(pg.assign(target_kind=pages.kind), on="path").explode("unique_ids").rename(columns={"unique_ids": "unique_id"})
    x = x.merge(si[["target_id", "unique_id", "confidence", "attributable"]].rename(columns={"confidence": "identity_conf"}), on=["target_id", "unique_id"])
    on_page = pd.Series([(p, u) in page_ok for p, u in zip(x.page_id, x.unique_id)], index=x.index, dtype=bool)
    x["attributable"] = x.attributable & (~x.off_site | on_page)
    keep = x.attributable | ((x.target_kind == "shared_home") & ~x.off_site)
    x["scope"] = x.target_kind.map({"site": "own_site", "branch": "branch_page", "shared_home": "chain_home"})
    return x[keep].reset_index(drop=True), int((~keep).sum())


def finalize_details(det: pd.DataFrame) -> pd.DataFrame:
    """VF-details cue, plausibility and status rules on web facts (attribution 'own_site'; kind from the sentence)."""
    sc = pd.read_parquet(f"{ROOT}/audit/scale/scale_flags.parquet", columns=["unique_id", "doctors_clean", "capacity_clean", "facility_type_norm"]).drop_duplicates("unique_id")
    f = det.assign(attribution="own_anchored", context="", dup_in_record=False, source_text=det.segment,
                   kind=det.segment.map(lambda s: {"directory": "list"}.get(sentence_kind(s), sentence_kind(s))),
                   claim_id=[f"{u[:8]}:{os.path.basename(p)[:12]}:{fl[0]}{s}" for u, p, fl, s in zip(det.unique_id, det.path, det.field, det.seg_start)])
    f["field_web"] = f.field
    f["flags"] = VE.cue_flags(f)
    f["flags"] = [fl + (["edu_page"] if e else []) for fl, e in zip(f["flags"], f.edu_url)]
    f["plaus"] = VE.plausibility(f, sc)
    extra = f.copy()
    fin = VE.finalize(f)
    keep_cols = ["target_id", "scope", "identity_conf", "attributable", "page_id", "path", "url", "final_url", "fetched_at", "role", "field_web", "seg_start", "edu_url"]
    out = fin.join(extra[keep_cols]).drop(columns=["field", "attribution", "context", "dup_in_record"]).rename(columns={"field_web": "field", "claim_id": "segment_id"})
    return out


def fix_detail_values(fin: pd.DataFrame) -> pd.DataFrame:
    """Two web fixes from the self-check: 'Chief Minister's Comprehensive Health Insurance Scheme' is a government
    scheme, not private insurance; 'NABH ... Pre Entry Level' is pre-entry, not entry level."""
    scheme_ins = (fin.attribute == "private_insurance") & fin.match.str.lower().str.fullmatch(r"health insurance") & fin.source_text.str.contains(r"scheme|yojana|government|chief minister", case=False)
    pre = (fin.fact_type == "accreditation") & fin.source_text.str.contains(r"pre[- ]?entry", case=False)
    flags = [(fl + "|scheme_name_not_private").strip("|") if x else fl for fl, x in zip(fin["flags"], scheme_ins)]
    return fin.assign(status=fin.status.where(~scheme_ins, "excluded"), flags=flags, value_text=fin.value_text.where(~pre, "pre_entry_level"))


def rescope_24x7(fin: pd.DataFrame) -> pd.DataFrame:
    """Web-specific fixes to the VF 24x7 scope: 'Emergency Care (24/7)' is cut at the bracket and comes back as
    'facility'; on a short line an emergency word decides. A bare '24 Hours' or '24*7' line is flagged, since a header
    badge does not say what is open."""
    phone_hours = (fin.fact_type == "opd_hours") & (fin.attribute == "general") & fin.source_text.str.contains(
        r"\bcall\b|whats ?app|\bphone\b|help ?line|reach us|enquir", case=False)
    fin = fin.assign(attribute=fin.attribute.where(~phone_hours, "helpline"))  # "call between 9 am and 8 pm" is not OPD
    is24 = fin.fact_type == "hours_24x7"
    short = fin.source_text.str.len() <= 80
    fix = is24 & (fin.attribute == "facility") & short & fin.source_text.str.contains(r"emergenc|casualty|trauma", case=False)
    bare = is24 & (fin.attribute == "facility") & (fin.source_text.str.split().str.len() <= 3)
    add = lambda fl, x: (fl + "|" + x).strip("|")
    flags = [add(fl, "scope_from_short_line") if f else (add(fl, "bare_24x7_line") if b else fl) for fl, f, b in zip(fin["flags"], fix, bare)]
    status = ["flagged" if (b and st == "ok") else st for st, b in zip(fin.status, bare)]
    return fin.assign(attribute=fin.attribute.where(~fix, "emergency"), flags=flags, status=status)


def add_llm_rows(det: pd.DataFrame) -> pd.DataFrame:
    """File-level detail hits plus the LLM hour readings kept by web_llm_hours.py. A kept reading replaces the regex
    opd_hours hit of the same line; its quote was string-matched to the line there and is asserted again here."""
    det = det.assign(method="regex")
    path = os.path.join(OUT, "llm_hours.parquet")
    if not os.path.exists(path):
        return det
    lh = pd.read_parquet(path)
    hc = pd.read_parquet(os.path.join(OUT, "hour_candidates.parquet"))[["cand_key", "path", "field", "seg_start", "text"]]
    lh = lh[lh.keep].merge(hc[["cand_key", "text"]], on="cand_key")[["text", "scope", "schedule_text", "quote"]]
    lh = lh.merge(hc, on="text")  # the same line on other pages gets the same reading
    assert all(q in t for q, t in zip(lh.quote, lh.text))
    key = det.path + "|" + det.field + "|" + det.seg_start.astype(str)
    det = det[~((det.fact_type == "opd_hours") & key.isin(set(lh.cand_key)))]
    new = pd.DataFrame({"path": lh.path, "field": lh.field, "seg_start": lh.seg_start, "segment": lh.text, "fact_type": "opd_hours",
                        "attribute": lh.scope, "value_num": None, "value_text": lh.schedule_text, "quote": lh.quote, "match": lh.quote, "method": "llm"})
    return pd.concat([det, new], ignore_index=True)


def verify_quotes(tables: dict[str, pd.DataFrame]) -> int:
    """Re-open every cited file and assert each quote is an exact substring of the field it names."""
    need: dict[str, set] = {}
    for t in tables.values():
        for p, f, q in zip(t.path, t.field, t.quote):
            need.setdefault(p, set()).add((f, q))
    n = 0
    for p, items in need.items():
        doc = json.load(gzip.open(os.path.join(ROOT, p)))
        for f, q in items:
            assert isinstance(q, str) and q and q in (doc.get(f) or ""), (p, f, q)
            n += 1
    return n


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    pages, sites, facs = load_inputs()
    files = pages.groupby("path").unique_ids.agg(lambda s: sorted({u for x in s for u in x}))
    jobs = [(p, [facs[u] for u in us], " | ".join(facs[u]["name"] or "" for u in us)) for p, us in files.items()]
    cache = os.environ.get("WEB_EVIDENCE_CACHE")  # optional pickle of the per-file pass, for reruns of the table steps
    if cache and os.path.exists(cache):
        res = pd.read_pickle(cache)
    else:
        with ProcessPoolExecutor(max_workers=8) as ex:
            res = list(ex.map(process_file, jobs, chunksize=64))
        if cache:
            pd.to_pickle(res, cache)
    print(f"files processed: {len(res)}")
    # page identity: one row per (page row, record); a file read for several page rows gets the same evidence
    ident = pd.DataFrame([{"path": r["path"], **i} for r in res for i in r["ident"]])
    pe = pages[["page_id", "path", "unique_ids"]].explode("unique_ids").rename(columns={"unique_ids": "unique_id"})
    pi = pe.merge(ident, on=["path", "unique_id"])
    si = site_identity(pi, pages, facs)
    pi.merge(pages[["page_id", "target_id", "final_url", "role"]], on="page_id").to_parquet(os.path.join(OUT, "page_identity.parquet"), index=False)
    si.to_parquet(os.path.join(OUT, "site_identity.parquet"), index=False)

    svc = pd.DataFrame([{"path": r["path"], **s} for r in res for s in r["svc"]])
    page_ok = set(zip(pi[(pi.name_how != "none") & (pi.pin_quote.notna() | pi.loc_quote.notna())].page_id, pi[(pi.name_how != "none") & (pi.pin_quote.notna() | pi.loc_quote.notna())].unique_id))
    svc, svc_dropped = attach(svc, pages, si, page_ok)
    svc["edu"] = svc.edu_seg | svc.edu_url
    svc["positive"] = ~svc.negated & (svc.nonoffer_cue == "") & ~svc.kind.isin(["staff", "directory", "research", "template"]) & ~svc.edu
    svc["offer_cue"] = svc.segment.str.contains(OFFER_CUE) | ((svc.line_kind == "item") & svc.services_page)
    svc["strength"] = (svc.positive & svc.offer_cue).map({True: "strong", False: "weak"}).where(svc.positive, "none")
    svc = svc.drop_duplicates(["unique_id", "page_id", "field", "seg_start", "service_id"])
    svc_cols = ["unique_id", "service_id", "quote", "url", "final_url", "fetched_at", "role", "field", "line_kind", "negated", "nonoffer_cue", "weak_cue",
                "kind", "edu", "job_seg", "positive", "offer_cue", "strength", "match", "segment", "seg_start", "scope", "identity_conf", "attributable", "target_id", "page_id", "path", "services_page"]
    svc[svc_cols].to_parquet(os.path.join(OUT, "web_services.parquet"), index=False)

    det = add_llm_rows(pd.DataFrame([{"path": r["path"], **d} for r in res for d in r["det"]]))
    det, det_dropped = attach(det, pages, si, page_ok)
    det = det.drop_duplicates(["unique_id", "page_id", "field", "seg_start", "fact_type", "attribute", "quote"])
    fin = fix_detail_values(rescope_24x7(finalize_details(det)))
    is_hour = fin.fact_type.isin(HOUR_TYPES) | (fin.attribute == "doctor_24x7")
    hours = fin[is_hour].reset_index(drop=True)
    details = fin[~is_hour].reset_index(drop=True)
    hours.to_parquet(os.path.join(OUT, "web_hours.parquet"), index=False)
    details.to_parquet(os.path.join(OUT, "web_details.parquet"), index=False)

    cand = pd.DataFrame([{"path": r["path"], **c} for r in res for c in r["cand"]])
    cand["cand_key"] = cand.path + "|" + cand.field + "|" + cand.seg_start.astype(str)
    att_paths = set(pages[pages.page_id.isin(svc.page_id) | pages.page_id.isin(fin.page_id)].path) | set(
        pages.merge(si[si.attributable], on="target_id").path)
    cand = cand[cand.path.isin(att_paths)].drop_duplicates("cand_key")  # web_llm_hours.py sends each distinct text once
    cand.to_parquet(os.path.join(OUT, "hour_candidates.parquet"), index=False)

    n_checked = verify_quotes({"services": svc, "hours": hours, "details": details})
    for col, fcol in (("name_quote", "name_field"), ("pin_quote", "pin_field"), ("locality_quote", "locality_field")):
        sub = pi[pi[col].notna()] if col == "name_quote" else pi.rename(columns={"loc_quote": "locality_quote", "loc_field": "locality_field"})
        sub = sub[sub[col].notna()]
        n_checked += verify_quotes({col: sub.rename(columns={col: "quote", fcol: "field"})[["path", "field", "quote"]]})
    stats = {"pages_used": int(len(pages)), "files_used": int(len(files)), "site_identity_rows": int(len(si)),
             "identity_conf": si.groupby(["kind", "confidence"]).size().unstack(fill_value=0).to_dict(),
             "service_rows": int(len(svc)), "service_rows_dropped_identity": svc_dropped, "hour_rows": int(len(hours)), "detail_rows": int(len(details)),
             "detail_rows_dropped_identity": det_dropped, "hour_candidates": int(len(cand)), "quotes_verified": n_checked}
    json.dump(stats, open(os.path.join(OUT, "stats_build.json"), "w"), indent=1, default=str)
    print(json.dumps(stats, indent=1, default=str))


def self_check() -> None:
    t = "Opening Hours:\nMon-Sun: 24 X 7\nServices\nDialysis unit with 10 machines; no ICU facility"
    segs = segments(t)
    assert [t[a:b] for a, b in segs][:2] == ["Opening Hours:", "Mon-Sun: 24 X 7"]
    assert t[slice(*detail_segments(t, segs)[1])] == "Opening Hours:\nMon-Sun: 24 X 7"
    svc = service_hits(t, segs)
    assert any(r["service_id"] == "dialysis" and not r["negated"] for r in svc)
    t2 = "We do not have dialysis facility."
    assert all(r["negated"] for r in service_hits(t2, segments(t2)) if r["service_id"] == "dialysis")
    long = "x " * 300 + "Dialysis" + " y" * 300
    q = window(long, 600, 608)
    assert "Dialysis" in q and q in long and len(q) <= QUOTE_CAP + 20
    k = facility_keys({"unique_id": "u", "name": "Amal Hospital", "city": "Thrissur", "district": None, "pin": "680001"})
    r = page_identity({"title": "Amal Hospital", "text": "Address: Main Rd, Thrissur - 680 001", "chrome_text": ""}, k)
    assert r["name_how"] == "full" and r["pin_quote"] and r["loc_quote"]
    k = facility_keys({"unique_id": "u", "name": "Thrissur Eye Hospital", "city": "Thrissur", "district": None, "pin": None})
    assert k["dist"] is None and k["full"] is not None  # the city word alone is not a distinctive name
    k = facility_keys({"unique_id": "u", "name": "Dingra Dental and Facial Cosmetic Clinic", "city": "New Delhi", "district": None, "pin": None})
    assert page_identity({"title": "", "text": "Dingra Dental Clinic, Bijwasan", "chrome_text": ""}, k)["name_how"] == "head"
    k = facility_keys({"unique_id": "u", "name": "St. Isabel Hospital, Mylapore, Chennai", "city": "Chennai", "district": None, "pin": None})
    assert page_identity({"title": "", "text": "Welcome to St. Isabel Hospital", "chrome_text": ""}, k)["name_how"] == "full"
    fac = {"name": "Gupta Hospital", "city": "Amritsar", "district": "Amritsar"}
    assert domain_other_place("guptahospitalbathinda.com", fac, {"bathinda", "amritsar"}) == "bathinda"
    assert sentence_kind("Consultant Pediatric & Adult Structural Interventional Cardiologist") == "staff"
    assert sentence_kind("Cath lab with 24x7 primary angioplasty") != "staff"
    assert page_identity({"title": "uniquehospital.com for sale | Spaceship.com", "text": "", "chrome_text": ""}, k)["parked"]
    assert not service_hits("Interventional procedures are non-surgical cardiac interventions in the cath lab", segments("x"))  # empty segs
    t3 = "Interventional procedures are non-surgical cardiac interventions performed in the cardiac catheterization laboratory"
    assert all(not r["negated"] for r in service_hits(t3, segments(t3)) if r["service_id"] == "cath_lab_angioplasty")
    assert quote_other_place("Best Multi-Specialty Hospital in Hyderabad | Medistar Hospitals", {"name": "Medistar Hospitals", "city": "Vadodara", "district": "Vadodara"}, {"hyderabad", "vadodara"}) == "hyderabad"
    d, _ = detail_hits("Emergency: [phone]", segments("Emergency: [phone]"), "")
    assert d and d[0]["fact_type"] == "emergency_phone"
    print("self-check ok")


if __name__ == "__main__":
    self_check() if "--test" in sys.argv else main()
