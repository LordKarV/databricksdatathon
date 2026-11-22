"""Privacy, licensing and safety audit of committed data and app exports.

Read-only. Every check_<name>() returns dict(name, status, metric, threshold, detail, examples) and writes its full
hit list to out/<name>.csv. Run all checks (about 5 minutes, mostly the crawl-sentence index):
    /Users/karthikvattem/projects/datathon/.venv-viz/bin/python validation/privacy_licence/checks.py
Scope: every file in `git ls-files`, the git history (commit diffs and blob sizes), and the app exports that ship
inside the Databricks App bundle (app/facts/out, app/packs/out, planner/out, app/howto/out, app/verify/out).
"""
from __future__ import annotations

import os

import csv
import gzip
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "validation" / "privacy_licence"
OUT = HERE / "out"
USER_EMAIL = os.environ.get("PRIVACY_EMAIL", "")  # set locally; never committed
USER_HANDLES = tuple(h for h in os.environ.get("PRIVACY_HANDLES", "").split(",") if h)
EXPORT_DIRS = ("app/facts/out", "app/packs/out", "planner/out", "app/howto/out", "app/verify/out")
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".wav", ".mp3", ".mp4", ".webm", ".ttf", ".otf", ".woff",
              ".woff2", ".pdf", ".ico", ".pyc"}
# Saved copies of third-party web pages / source code, kept as research evidence.
THIRD_PARTY_PAGE = re.compile(r"(^|/)(sources|probes)/[^/]+\.(html?|txt|java|cc|json)$")
OWN_DIRS = ("viz/sources/",)  # viz/sources/*.txt are the project's own chart notes
WEBMAIL = re.compile(r"@(gmail|googlemail|yahoo|ymail|rediffmail|hotmail|outlook|live|msn|icloud|aol|protonmail)\.",
                     re.I)


# ----------------------------------------------------------------------------------------------------------- corpus
def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True,
                          errors="replace").stdout


@lru_cache(maxsize=1)
def tracked() -> tuple[str, ...]:
    return tuple(p for p in git("ls-files").splitlines() if (ROOT / p).is_file())


@lru_cache(maxsize=1)
def exports() -> tuple[str, ...]:
    out = []
    for d in EXPORT_DIRS:
        p = ROOT / d
        if p.is_dir():
            out += sorted(str(f.relative_to(ROOT)) for f in p.rglob("*") if f.is_file())
    return tuple(out)


def _parquet_text(path: Path) -> str:
    t = pq.read_table(path)
    parts = []
    for f in t.schema:
        ty = str(f.type)
        if "string" not in ty:
            continue
        col = t.column(f.name).to_pylist()
        if ty.startswith("list"):
            col = [x for v in col if v for x in v]
        parts.append("\n".join(v for v in col if v))
    return "\n".join(parts)


@lru_cache(maxsize=4096)
def text_of(rel: str) -> str:
    """Full text of a file: every string cell of a parquet, decompressed .gz, '' for binary media."""
    p = ROOT / rel
    ext = p.suffix.lower()
    if ext in BINARY_EXT:
        return ""
    if ext == ".parquet":
        return _parquet_text(p)
    raw = p.read_bytes()
    if ext == ".gz":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return ""
    if b"\x00" in raw[:8192]:
        return ""
    return raw.decode("utf-8", errors="ignore")


def corpus() -> list[str]:
    return list(tracked()) + list(exports())


def is_third_party_page(rel: str) -> bool:
    return bool(THIRD_PARTY_PAGE.search(rel)) and not rel.startswith(OWN_DIRS) and "/fixtures/" not in rel


@lru_cache(maxsize=1)
def audit_classes() -> dict[str, str]:
    """Class each tracked file gets from tools/data_audit.py (the option-B public-copy filter), run in memory."""
    spec = importlib.util.spec_from_file_location("data_audit", ROOT / "tools" / "data_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # module top level only defines functions; main() is not called
    return {rel: mod.classify(rel)[0] for rel in tracked()}


def ships(rel: str) -> str:
    """Where a file ends up: 'export' (app bundle), 'public_copy' (option B keeps it) or 'private_only'."""
    if rel in exports():
        return "export"
    return "public_copy" if audit_classes().get(rel) == "public" else "private_only"


def write_csv(name: str, rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.csv"
    if not rows:
        path.write_text("")
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def result(name: str, status: str, metric: str, threshold: str, detail: str, examples: list) -> dict:
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail,
            "examples": examples[:5]}


def mask(s: str) -> str:
    """Outputs must not become a new copy of personal data: keep the last 4 digits of numbers, hide email users."""
    s = re.sub(r"\d[\d\s-]{5,}\d", lambda m: "*" * (len(m.group(0)) - 4) + m.group(0)[-4:], s)
    return re.sub(r"\b([A-Za-z0-9._%+-]{1,2})[A-Za-z0-9._%+-]*@", r"\1***@", s)


def snippet(txt: str, a: int, b: int, pad: int = 50) -> str:
    return mask(re.sub(r"\s+", " ", txt[max(0, a - pad): b + pad])[:220])


# ---------------------------------------------------------------------------------------------------------- secrets
SECRET_PATTERNS = {
    "databricks_pat": r"\bdapi[0-9a-f]{32}(?:-\d)?\b",
    "github_token": r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{50,}",
    "anthropic_key": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    "openai_key": r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b",
    "aws_access_key": r"\bAKIA[0-9A-Z]{16}\b",
    "slack_token": r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "google_api_key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "hf_token": r"\bhf_[A-Za-z0-9]{34,}\b",
    "jwt": r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    "url_with_credentials": r"\bhttps?://[A-Za-z0-9._%-]+:[A-Za-z0-9._%-]{6,}@[A-Za-z0-9.-]+",
    "assigned_secret": (r"(?i)\b(?:password|passwd|client_secret|api_key|apikey|access_token|auth_token|"
                        r"databricks_token)\b[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_\-./+=]{12,}[\"']"),
}
SECRET_RE = {k: re.compile(v) for k, v in SECRET_PATTERNS.items()}
CRED_FILES = re.compile(r"(^|/)(\.env(\..*)?|\.databrickscfg|\.netrc|credentials\.json|token\.json|id_rsa|id_ed25519|"
                        r".*\.pem|.*\.key|.*\.p12|kaggle\.json|secrets?\.(json|ya?ml|toml))$")


def _secret_hits(rel: str, txt: str) -> list[dict]:
    rows = []
    for kind, rx in SECRET_RE.items():
        for m in rx.finditer(txt):
            rows.append({"file": rel, "kind": kind, "value_prefix": m.group(0)[:12] + "...",
                         "third_party_page": is_third_party_page(rel), "ships": ships(rel),
                         "context": snippet(txt, m.start(), m.end(), 30)})
    return rows


def check_secrets_tracked() -> dict:
    rows = []
    for rel in corpus():
        rows += _secret_hits(rel, text_of(rel))
    rows += [{"file": rel, "kind": "credential_filename", "value_prefix": "", "third_party_page": False,
              "ships": ships(rel), "context": ""} for rel in tracked() if CRED_FILES.search(rel)]
    write_csv("secrets_tracked", rows)
    own = [r for r in rows if not r["third_party_page"]]
    tp = [r for r in rows if r["third_party_page"]]
    tp_files = sorted({r["file"] for r in tp})
    status = "fail" if own else ("warn" if tp else "pass")
    return result("secrets_tracked", status,
                  f"{len(own)} project credentials; {len(tp)} third-party key strings in {len(tp_files)} saved pages",
                  "0 credentials in any tracked file or export",
                  (f"Scanned {len(corpus())} files ({len(tracked())} tracked + {len(exports())} exports) for "
                   f"{len(SECRET_PATTERNS)} token patterns and credential file names. Third-party hits by kind: "
                   f"{dict(Counter(r['kind'] for r in tp))}; own hits by kind: {dict(Counter(r['kind'] for r in own))}. "
                   "The Google keys are the public browser keys Google embeds in its own developer pages, saved "
                   "here as research copies; they are not project secrets, but GitHub secret scanning flags them."),
                  [f"{r['file']}: {r['kind']} {r['value_prefix']}" for r in (own or tp)][:5] + tp_files[:3])


def check_secrets_history() -> dict:
    """Added lines in every commit on every ref, plus every path ever committed."""
    log = git("log", "--all", "-p", "--no-color", "--unified=0", "--format=COMMIT %H")
    rows, commit, fname = [], "", ""
    for line in log.splitlines():
        if line.startswith("COMMIT "):
            commit = line[7:15]
        elif line.startswith("+++ b/"):
            fname = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            for kind, rx in SECRET_RE.items():
                for m in rx.finditer(line):
                    rows.append({"commit": commit, "file": fname, "kind": kind,
                                 "value_prefix": m.group(0)[:12] + "...",
                                 "third_party_page": is_third_party_page(fname)})
    ever = set(git("log", "--all", "--name-only", "--format=").split())
    cred_paths = sorted(p for p in ever if CRED_FILES.search(p))
    write_csv("secrets_history", rows + [{"commit": "", "file": p, "kind": "credential_filename"} for p in cred_paths])
    own = [r for r in rows if not r["third_party_page"]]
    status = "fail" if own or cred_paths else ("warn" if rows else "pass")
    return result("secrets_history", status,
                  f"{len(own)} project credentials, {len(cred_paths)} credential files ever committed; "
                  f"{len(rows) - len(own)} third-party key strings in history",
                  "0", f"Scanned added lines of {len(set(git('rev-list', '--all').split()))} commits and "
                       f"{len(ever)} paths ever committed.",
                  [f"{r['commit']} {r['file']} {r['kind']}" for r in (own or rows)] + cred_paths)


# ---------------------------------------------------------------------------------------------- the user's identity
HOME_RE = re.compile(r"/Users/(karthikvattem)\b")


def check_user_identity() -> dict:
    rows = []
    for rel in corpus():
        txt = text_of(rel)
        n_email = txt.count(USER_EMAIL)
        n_home = len(HOME_RE.findall(txt))
        if n_email or n_home:
            rows.append({"file": rel, "user_email": n_email, "home_path": n_home, "ships": ships(rel)})
    authors = Counter(git("log", "--all", "--format=%ae").split())
    write_csv("user_identity", rows)
    email_files = [r for r in rows if r["user_email"]]
    pub_home = [r for r in rows if r["home_path"] and r["ships"] != "private_only"]
    status = "fail" if email_files else ("warn" if pub_home else "pass")
    return result("user_identity", status,
                  f"{len(email_files)} files with the user's email; {len(rows)} files with the /Users/<name> home "
                  f"path ({sum(r['home_path'] for r in rows)} mentions, {len(pub_home)} would ship publicly or "
                  "in the app)",
                  "0 files with the user's email; 0 home paths in shipped files",
                  ("Commit metadata (not file content) carries author emails: "
                   + ", ".join(f"{('<user email>' if e == USER_EMAIL else mask(e))} x{n}" for e, n in authors.items())
                   + ". The option-B copy is one fresh commit by public-copy@localhost, so it drops these."),
                  [f"{r['file']} (home path x{r['home_path']}, {r['ships']})" for r in
                   sorted(pub_home or rows, key=lambda r: -r["home_path"])])


# ------------------------------------------------------------------------------------------------------- emails
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,12}\b")
NOT_EMAIL_TLD = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js|mjs|ts|json|html?|py|ico|woff2?|ttf)$", re.I)
# Case-sensitive on purpose: with re.I, "Dr" + letter matches "drive", "draft", "address".
DOCTOR_RE = re.compile(r"\bDr\.?\s+[A-Z][a-z]+|\bDr\.[A-Z][a-z]+|\bDR\.?\s+[A-Z]{3,}|\b[Dd]octor\b|\bMBBS\b|"
                       r"\bBDS\b|\bMDS\b|\bM\.D\.|\bFRCS\b|\bDNB\b|\b[Cc]onsultant\b")


@lru_cache(maxsize=1)
def raw_contacts() -> tuple[frozenset, frozenset]:
    """Emails and 10-digit phones as published in the provided facility table (lower-cased emails)."""
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["email", "phone_numbers", "officialPhone"])
    emails = {e.lower() for v in raw.email.dropna() for e in EMAIL_RE.findall(v)}
    phones = {m[-10:] for c in ("phone_numbers", "officialPhone") for v in raw[c].dropna()
              for m in re.findall(r"\d{10,13}", re.sub(r"[\s-]", "", v))}
    return frozenset(emails), frozenset(phones)


def check_emails() -> dict:
    raw_emails, _ = raw_contacts()
    rows = []
    for rel in corpus():
        txt = text_of(rel)
        for m in EMAIL_RE.finditer(txt):
            e = m.group(0)
            if NOT_EMAIL_TLD.search(e) or "@" not in e or re.match(r"^[\w-]+@\d", e):
                continue
            el = e.lower()
            kind = ("user" if el == USER_EMAIL else
                    "placeholder" if re.search(r"noreply|no-reply|example\.|localhost|users\.noreply", el) else
                    "webmail" if WEBMAIL.search(el) else "organisational")
            ctx = txt[max(0, m.start() - 150): m.end() + 150]
            rows.append({"file": rel, "email": el, "email_masked": mask(el), "kind": kind, "in_provided_table": el in raw_emails,
                         "doctor_context": bool(DOCTOR_RE.search(ctx)), "ships": ships(rel),
                         "third_party_page": is_third_party_page(rel)})
    write_csv("emails", [{k: v for k, v in r.items() if k != "email"} for r in rows])
    df = pd.DataFrame(rows)
    if df.empty:
        return result("emails", "pass", "0 emails", "", "", [])
    u = df.drop_duplicates(["email"])
    web = df[df.kind == "webmail"]
    web_doc = web[web.doctor_context]
    web_not_raw = web[~web.in_provided_table & ~web.third_party_page]
    shipped_web = web[web.ships != "private_only"]
    status = "fail" if (df.kind == "user").any() or len(shipped_web) else ("warn" if len(web) else "pass")
    by_file = web.groupby("file").email.nunique().sort_values(ascending=False)
    return result("emails", status,
                  (f"{u.shape[0]} distinct emails ({dict(Counter(u.kind))}); webmail: {web.email.nunique()} distinct "
                   f"in {web.file.nunique()} files, {web_doc.email.nunique()} next to a doctor name/degree, "
                   f"{web_not_raw.email.nunique()} not in the provided table"),
                  "0 personal (webmail) addresses outside the provided table; 0 in shipped files",
                  (f"Webmail addresses are mostly single-doctor clinics' published contacts copied from the provided "
                   f"table (email column), so they are personal data of named individuals; the ones 'not in the "
                   f"provided table' are cleaned forms of provided values (record_trust.emails_clean). Shipped (public copy or "
                   f"app export): {shipped_web.email.nunique()} distinct in {shipped_web.file.nunique()} files. "
                   f"Top files: {dict(by_file.head(6))}"),
                  [f"{r.file}: {r.email_masked} (doctor ctx={r.doctor_context}, {r.ships})"
                   for r in web.drop_duplicates("file").itertuples()])


# --------------------------------------------------------------------------------------------- doctor mobile numbers
MOBILE_RE = re.compile(r"(?<![\w.:/=-])(?:\+91[\s-]?|91[\s-]|0)?([6-9]\d{4}[\s-]?\d{5})(?![\w.])")
DR_NAME = re.compile(r"^\s*(?:Dr|DR|dr)\.?\s*[A-Za-z]|\bDr\.?\s+[A-Z][a-z]+", re.M)


def check_doctor_mobiles_text() -> dict:
    """Indian mobile numbers within 150 characters of a doctor name or degree, in any tracked file or export."""
    rows = []
    for rel in corpus():
        if is_third_party_page(rel):
            continue
        txt = text_of(rel)
        for m in MOBILE_RE.finditer(txt):
            ctx = txt[max(0, m.start() - 150): m.end() + 150]
            d = DOCTOR_RE.search(ctx)
            if d:
                rows.append({"file": rel, "mobile_last4": m.group(1)[-4:], "mobile": re.sub(r"\D", "", m.group(1)),
                             "ships": ships(rel), "context": snippet(txt, m.start(), m.end(), 60)})
    df = pd.DataFrame(rows)
    write_csv("doctor_mobiles_text", [{k: v for k, v in r.items() if k != "mobile"} for r in rows])
    if df.empty:
        return result("doctor_mobiles_text", "pass", "0", "0", "", [])
    per = df.groupby("file").mobile.nunique().sort_values(ascending=False)
    shipped = df[df.ships != "private_only"]
    status = "fail" if len(shipped) else "warn"
    return result("doctor_mobiles_text", status,
                  (f"{df.mobile.nunique()} distinct mobiles next to a doctor name/degree in {df.file.nunique()} "
                   f"files; {shipped.mobile.nunique()} distinct in {shipped.file.nunique()} shipped files"),
                  "0 doctor-attached mobiles in shipped files (public copy or app export)",
                  f"Files by distinct numbers: {dict(per.head(8))}",
                  [f"{r.file}: ...{r.mobile_last4} | {r.context[:120]}" for r in
                   (shipped if len(shipped) else df).drop_duplicates("file").itertuples()])


def _phone10(v) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return d[-10:] if len(d) >= 10 else None


INSTITUTION = re.compile(r"(?i)hospital|institute|nursing home|medical college|research cent|multi ?speciality|"
                         r"healthcare|health care|eye care|\bpvt\b|\bltd\b")


def check_doctor_mobiles_exports() -> dict:
    """Facility records in the app exports whose name is a doctor's name and whose phone is a mobile.

    Tier 'personal_likely': a doctor-named clinic (no hospital/institute word) whose mobile is not shared with any
    other record (shared numbers are chain helplines). Tier 'doctor_named': any doctor-named record with a mobile."""
    rows = []
    f = json.load(gzip.open(ROOT / "app/facts/out/facts.json.gz"))["fac"]
    n_fac = len(f["id"])
    n_mobile = 0
    for i in range(n_fac):
        ph = _phone10(f["phone_e164"][i] or f["phone_raw"][i])
        if not (ph and ph[0] in "6789"):
            continue
        n_mobile += 1
        name = f["name"][i] or ""
        if DR_NAME.search(name):
            personal = not INSTITUTION.search(name) and (f["phone_shared"][i] or 1) <= 1
            rows.append({"export": "app/facts/out/facts.json.gz", "id": f["id"][i], "name": name,
                         "mobile_last4": ph[-4:], "phone_shared": f["phone_shared"][i],
                         "official_site": bool(f["website_own"][i]),
                         "tier": "personal_likely" if personal else "doctor_named"})
    packs = sorted((ROOT / "app/packs/out").glob("*.json.gz"))
    pack_rows = pack_personal = 0
    for p in packs:
        fac = json.load(gzip.open(p))["fac"]
        for j, name in enumerate(fac["name"]):
            ph = _phone10(fac["tel"][j])
            if ph and ph[0] in "6789" and DR_NAME.search(name or ""):
                pack_rows += 1
                pack_personal += not INSTITUTION.search(name)
    pl = json.load(gzip.open(ROOT / "planner/out/planner_v1.json.gz"))["facilities"]
    pl_phone_keys = [k for k in pl if re.search(r"phone|tel", k)]
    write_csv("doctor_mobiles_exports", rows)
    pers = [r for r in rows if r["tier"] == "personal_likely"]
    status = "warn" if pers else "pass"
    return result("doctor_mobiles_exports", status,
                  (f"facts.json: {len(pers)} personal-likely + {len(rows) - len(pers)} other doctor-named records "
                   f"show a mobile, of {n_fac} facilities ({n_mobile} show any mobile); packs: {pack_rows} "
                   f"doctor-named rows with a mobile ({pack_personal} without an institution word) across "
                   f"{len(packs)} states; planner phone fields: {pl_phone_keys}"),
                  "0 personal-likely doctor mobiles shown unless the number is on the facility's own site",
                  (f"{sum(r['official_site'] for r in pers)} of the {len(pers)} personal-likely records have an own "
                   "website where the number could be confirmed as published. Numbers come from the provided "
                   "table's phone fields (publicly listed), but for a one-doctor clinic the number is the doctor's "
                   "own mobile."),
                  [f"{r['id'][:8]} {r['name'][:40]} ...{r['mobile_last4']} (own site={r['official_site']})"
                   for r in pers])


# -------------------------------------------------------------------------------------------- patient-like details
PATIENT_PATTERNS = {
    "patient_name_label": r"\b(?:[Pp]atient|PATIENT|Pt)(?:\s+[Nn]ame)?\s*:\s*[A-Z][a-z]+\s+[A-Z][a-z]+",
    "record_number": r"(?i)\b(?:UHID|MRN|IPD\s*no|OPD\s*no|CR\s*no|IP\s*no)\.?\s*[:#]?\s*[A-Z0-9-]*\d{4,}",
    "aadhaar_like": r"(?i)(?:aadhaa?r|\bUID\b)[^\n+]{0,30}(?<![+\d])[2-9]\d{3}\s?\d{4}\s?\d{4}\b",
    "age_sex": r"(?i)\b(?:age|aged)\s*[:/]?\s*\d{1,3}\s*(?:y|yrs?|years?)?\s*[,/ ]\s*(?:sex\s*[:/]?\s*)?(?:male|female|M|F)\b",
    "titled_person_age": r"\b(?:Mr|Mrs|Ms|Smt|Shri)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s*,?\s*\(?\d{1,3}\s*(?:yrs?|years?|Y)\b",
    "diagnosis_of_named": r"\b(?:Mr|Mrs|Ms|Smt|Shri)\.?\s+[A-Z][a-z]+[^\n.]{0,60}\b(?:diagnosed|admitted|discharged|operated)\b",
}
PATIENT_RE = {k: re.compile(v) for k, v in PATIENT_PATTERNS.items()}


def check_patient_like() -> dict:
    rows = []
    for rel in corpus():
        if is_third_party_page(rel):
            continue
        txt = text_of(rel)
        for kind, rx in PATIENT_RE.items():
            for m in rx.finditer(txt):
                ctx = snippet(txt, m.start(), m.end(), 40)
                synthetic = bool(re.search(r"Test Patient|example|synthetic|invented", ctx, re.I)) or \
                    rel.endswith(("make_images.py", "inputs.py"))
                rows.append({"file": rel, "kind": kind, "synthetic_marker": synthetic, "ships": ships(rel),
                             "match": mask(m.group(0)[:80]), "context": ctx})
    write_csv("patient_like", rows)
    real = [r for r in rows if not r["synthetic_marker"]]
    shipped = [r for r in real if r["ships"] != "private_only"]
    status = "fail" if shipped else ("warn" if real else "pass")
    return result("patient_like", status,
                  (f"{len(real)} non-synthetic matches in {len({r['file'] for r in real})} files "
                   f"({dict(Counter(r['kind'] for r in real))}); {len(rows) - len(real)} synthetic test values"),
                  "0 patient-identifying details in shipped files",
                  ("Matches need a human read: most are facility marketing text in the provided table ('Mr X, 45 "
                   "years, underwent ...' testimonials). Vision test images are synthetic (make_images.py: 'All text "
                   "is invented; no real patient'), audio is macOS `say` (asr_bench.py), and the three external "
                   "photos are Wikimedia Commons (CC BY-SA 3.0 x2, public domain)."),
                  [f"{r['file']} [{r['kind']}]: {r['context'][:140]}" for r in (shipped or real)])


# ------------------------------------------------------------------- provided-data rows that leak into option B
ANY_PHONE = re.compile(r"(?<![\w.:/=-])(?:\+?91[\s-]?|0)?(\d[\d\s-]{8,11}\d)(?![\w.])")


def check_provided_contacts_public_copy() -> dict:
    """Phone numbers from the provided table inside files the option-B filter would publish (or the app ships)."""
    _, raw_phones = raw_contacts()
    rows = []
    for rel in corpus():
        if ships(rel) == "private_only":
            continue
        txt = text_of(rel)
        found = {d[-10:] for m in ANY_PHONE.finditer(txt) if len(d := re.sub(r"\D", "", m.group(1))) >= 10}
        hit = found & raw_phones
        if hit:
            rows.append({"file": rel, "ships": ships(rel), "provided_phones": len(hit),
                         "examples_last4": ";".join(sorted(h[-4:] for h in hit)[:5])})
    write_csv("provided_contacts_public_copy", rows)
    pub = [r for r in rows if r["ships"] == "public_copy"]
    status = "fail" if any(r["provided_phones"] >= 20 for r in pub) else ("warn" if pub else "pass")
    return result("provided_contacts_public_copy", status,
                  (f"{len(pub)} option-B files carry provided phone numbers "
                   f"({sum(r['provided_phones'] for r in pub)} numbers); {len(rows) - len(pub)} app exports do "
                   "(expected: the app shows them)"),
                  "0 provided phone numbers in the option-B public copy",
                  ("tools/data_audit.py keys only on record ids, sentence ids and coordinates, so a file of "
                   "phones plus facility names with no ids passes as 'public'."),
                  [f"{r['file']}: {r['provided_phones']} numbers" for r in sorted(pub, key=lambda r: -r["provided_phones"])])


@lru_cache(maxsize=1)
def provided_name_index() -> dict:
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["name"]).name.dropna()
    ix = {}
    for i, n in enumerate(raw.drop_duplicates()):
        t = tuple(_norm_tokens(n))
        if len(t) >= 3 and len(" ".join(t)) >= 15:
            ix.setdefault(t, i)
    return ix


def check_provided_names_public_copy() -> dict:
    """Distinct provided facility names (>=3 tokens) per option-B file: a list of names is a copy of provided rows."""
    ix = provided_name_index()
    rows = []
    for rel in tracked():
        if ships(rel) != "public_copy":
            continue
        txt = text_of(rel)
        if txt:
            n = len(_name_hits(_norm_tokens(txt), ix))
            if n:
                rows.append({"file": rel, "provided_names": n})
    rows.sort(key=lambda r: -r["provided_names"])
    write_csv("provided_names_public_copy", rows)
    bulk = [r for r in rows if r["provided_names"] >= 20]
    status = "fail" if bulk else ("warn" if rows else "pass")
    return result("provided_names_public_copy", status,
                  f"{len(bulk)} option-B files name >=20 provided facilities; {len(rows)} name >=1",
                  "0 option-B files listing >=20 provided facility names (a few quoted examples are fine)",
                  ("DATA_AUDIT.md calls this its known gap (facility names in prose). Counts distinct names of "
                   ">=3 tokens; generic names shared by many records count once."),
                  [f"{r['file']}: {r['provided_names']} names" for r in rows])


# ----------------------------------------------------------------------------------------- restricted list copies
ID_TOKEN = re.compile(r"\b[A-Z]{1,6}-\d{4}-\d{3,5}\b|\b[A-Z]{2}/\d{3}/[A-Z]/\d+\b")


def _norm_tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(s).lower().replace("&", " and "))


@lru_cache(maxsize=1)
def restricted_lists() -> dict:
    """Per list: entry count, id->entry, name-token-tuple->entry for names not shared with any provided record."""
    raw_names = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["name"]).name.dropna()
    vf = {tuple(_norm_tokens(n)) for n in raw_names}
    nabh = pd.read_parquet(ROOT / "data/external/nabh_accredited/nabh_hco.parquet")
    nmc = pd.read_parquet(ROOT / "data/external/nmc_colleges/nmc_colleges.parquet")
    tcf = pd.read_csv(ROOT / "data/external/mohfw_trauma_196/tcf_196.csv")
    raw_txt = _parquet_text(ROOT / "data/raw/facilities.parquet")
    raw_tokens, raw_ids = _norm_tokens(raw_txt), set(ID_TOKEN.findall(raw_txt))
    out = {}
    for key, names, ids in (("nabh", nabh.name, nabh.acc_no), ("nmc", nmc.college_name, nmc.college_code),
                            ("trauma", tcf.name, None)):
        name_ix = {}
        for i, n in enumerate(names):
            t = tuple(_norm_tokens(n))
            if len(t) >= 3 and len(" ".join(t)) >= 15 and t not in vf:
                name_ix.setdefault(t, i)
        id_ix = {} if ids is None else {str(v).strip(): i for i, v in enumerate(ids) if isinstance(v, str) and v.strip()}
        # Entries the provided table itself mentions (a longer record name, a description quoting an NABH number)
        # are explained by provided data, not by copying the list: drop them so only list-sourced text counts.
        in_raw = _name_hits(raw_tokens, name_ix)
        name_ix = {t: i for t, i in name_ix.items() if i not in in_raw}
        id_ix = {k: i for k, i in id_ix.items() if k not in raw_ids}
        out[key] = {"n": len(names), "names": name_ix, "ids": id_ix, "explained_by_provided": len(in_raw)}
    return out


def _name_hits(tokens: list[str], name_ix: dict) -> set[int]:
    by_bigram = defaultdict(list)
    for t, i in name_ix.items():
        by_bigram[t[:2]].append((t, i))
    hits = set()
    for k in range(len(tokens) - 1):
        cands = by_bigram.get((tokens[k], tokens[k + 1]))
        if cands:
            for t, i in cands:
                if tuple(tokens[k:k + len(t)]) == t:
                    hits.add(i)
    return hits


def check_restricted_list_copies() -> dict:
    lists = restricted_lists()
    rows = []
    for rel in corpus():
        txt = text_of(rel)
        if not txt:
            continue
        ids_in = set(ID_TOKEN.findall(txt))
        toks = _norm_tokens(txt)
        for key, L in lists.items():
            hit_ids = {L["ids"][x] for x in ids_in if x in L["ids"]}
            hit_names = _name_hits(toks, L["names"])
            n = len(hit_ids | hit_names)
            if n:
                rows.append({"file": rel, "list": key, "list_size": L["n"], "entries_hit": n,
                             "by_id": len(hit_ids), "by_list_only_name": len(hit_names),
                             "share": round(n / L["n"], 4), "ships": ships(rel)})
    write_csv("restricted_list_copies", rows)
    near_whole = [r for r in rows if r["share"] >= 0.5]
    bulk = [r for r in rows if r["entries_hit"] >= 20]
    shipped_bulk = [r for r in bulk if r["ships"] != "private_only"]
    status = "fail" if near_whole or shipped_bulk else ("warn" if bulk else "pass")
    sizes = {k: f"{v['n']} ({v['explained_by_provided']} names also in the provided table, not counted)"
             for k, v in lists.items()}
    return result("restricted_list_copies", status,
                  (f"{len(near_whole)} files hold >=50% of a restricted list; {len(bulk)} files hold >=20 entries "
                   f"({len(shipped_bulk)} of them shipped); {len(rows)} files mention >=1 entry"),
                  "no file holds >=50% of NABH/NMC/trauma; no shipped file holds >=20 entries",
                  (f"List sizes {sizes}. An entry counts when its accreditation no. / NMC college code appears, or "
                   "its full name (>=3 tokens) appears and that name is not also a provided-record name (so a "
                   "provided facility's own name never counts). Per-facility facts with citations are allowed."),
                  [f"{r['file']}: {r['list']} {r['entries_hit']}/{r['list_size']} ({r['ships']})"
                   for r in sorted(rows, key=lambda r: -r["entries_hit"])])


# -------------------------------------------------------------------------------------------- crawled page bodies
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
MIN_SENT = 80


def _sentences(txt: str) -> set[int]:
    out = set()
    for s in SENT_SPLIT.split(txt):
        s = re.sub(r"\s+", " ", s).strip().lower()
        if len(s) >= MIN_SENT:
            out.add(hash(s))
    return out


@lru_cache(maxsize=1)
def crawl_only_sentences() -> frozenset:
    """Sentences (>=80 chars) of crawled facility pages that are not also in the provided table's text."""
    crawl = set()
    for p in (ROOT / "data/crawl/pages").glob("*.json.gz"):
        try:
            d = json.load(gzip.open(p))
        except (OSError, ValueError):
            continue
        crawl |= _sentences(d.get("text") or "")
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet")
    provided = set()
    for c in raw.columns:
        if raw[c].dtype == object:
            # list fields are JSON arrays ('["a", "b"]'); split items so each item is a sentence, like claims
            joined = "\n".join(raw[c].dropna().astype(str))
            provided |= _sentences(re.sub(r'"\s*,\s*"|\["|"\]', "\n", joined))
    return frozenset(crawl - provided)


@lru_cache(maxsize=1)
def provided_blob() -> str:
    """Whole provided table as one case/whitespace-folded string, to test 'is this sentence provided text?'."""
    return re.sub(r"\s+", " ", _parquet_text(ROOT / "data/raw/facilities.parquet")).lower()


def check_crawled_page_bodies() -> dict:
    crawl = crawl_only_sentences()
    blob = provided_blob()
    rows = []
    for rel in corpus():
        txt = text_of(rel)
        if not txt:
            continue
        sents = {}
        for x in SENT_SPLIT.split(txt):
            x = re.sub(r"\s+", " ", x).strip().lower()
            if len(x) >= MIN_SENT:
                sents[hash(x)] = x
        hits = [x for h, x in sents.items() if h in crawl]
        # sentence boundaries differ between claims and the raw table, so re-test each hit as a substring
        n = sum(1 for x in hits if x not in blob)
        if n:
            rows.append({"file": rel, "crawl_sentences": n, "also_provided": len(hits) - n,
                         "file_sentences": len(sents), "ships": ships(rel)})
    write_csv("crawled_page_bodies", rows)
    # positive control: a crawled page's own text must score most of its sentences (fixed order, first long page)
    ctrl = "not run"
    for pth in sorted((ROOT / "data/crawl/pages").glob("*.json.gz"))[:200]:
        t = json.load(gzip.open(pth)).get("text") or ""
        own = _sentences(t)
        if len(own) >= 10:
            ctrl = f"{pth.name} scores {len(own & crawl)} of {len(own)} sentences"
            break
    bodies = [r for r in rows if r["crawl_sentences"] >= 50]
    shipped = [r for r in bodies if r["ships"] != "private_only"]
    status = "fail" if shipped else ("warn" if bodies else "pass")
    return result("crawled_page_bodies", status,
                  (f"{len(bodies)} files carry >=50 crawled-page sentences ({len(shipped)} shipped); "
                   f"{len(rows)} files carry >=1; index has {len(crawl):,} crawl-only sentences"),
                  ">=50 verbatim crawl sentences in one file = a page-body copy; 0 such files shipped",
                  ("Sentence = >=80 chars, case and whitespace folded. Sentences also present in the provided "
                   "table are removed first, so quoting the provided dataset does not count. Short quote-verified "
                   "snippets (web_evidence, source_page_checks) are expected below the threshold. Positive control: " + ctrl),
                  [f"{r['file']}: {r['crawl_sentences']} of {r['file_sentences']} ({r['ships']})"
                   for r in sorted(rows, key=lambda r: -r["crawl_sentences"])])


# ------------------------------------------------------------------------------------- third-party saved pages
LICENCE_HINTS = [
    (r"wiki_", "Wikipedia text, CC BY-SA 4.0 (attribution + share-alike)"),
    (r"mdn_", "MDN, CC BY-SA 2.5"),
    (r"wcag|understanding_|coga_", "W3C document, W3C Document License (copy allowed with notice)"),
    (r"chromium_", "Chromium source, BSD-3-Clause (keep licence header)"),
    (r"android_|talkback|developer\.android|google", "Google page, CC BY 4.0 text / Google ToS; embeds Google API keys"),
    (r"uber|olacabs|ola_|rapido|nammayatri", "ride-hailing vendor page, all rights reserved"),
    (r"medhi|msr_|s2_", "ACM / Microsoft Research / Semantic Scholar page, all rights reserved or API terms"),
    (r"pib_", "PIB press release, GoI copyright policy (reproduce with attribution)"),
    (r"gradio|streamlit|dash_|databricks", "framework docs page, vendor copyright"),
    (r"gsma|cable_", "industry report page, all rights reserved"),
    (r"hf_|bcd_", "Hugging Face model card / browser-compat-data JSON (mixed licences)"),
]


def check_third_party_pages() -> dict:
    rows = []
    for rel in tracked():
        if not is_third_party_page(rel):
            continue
        name = Path(rel).name
        lic = next((v for k, v in LICENCE_HINTS if re.search(k, name, re.I)), "unknown, all rights reserved assumed")
        txt = text_of(rel)
        rows.append({"file": rel, "bytes": (ROOT / rel).stat().st_size, "licence_hint": lic,
                     "is_full_page": bool(re.search(r"<html|<!doctype", txt[:5000], re.I)) or len(txt) > 20000,
                     "google_keys": len(SECRET_RE["google_api_key"].findall(txt)), "ships": ships(rel)})
    write_csv("third_party_pages", rows)
    shipped = [r for r in rows if r["ships"] == "public_copy" and r["is_full_page"]]
    restrictive = [r for r in shipped if "all rights reserved" in r["licence_hint"] or "ToS" in r["licence_hint"]]
    mb = sum(r["bytes"] for r in rows) / 1e6
    status = "warn" if restrictive else "pass"
    return result("third_party_pages", status,
                  (f"{len(rows)} saved third-party pages/files ({mb:.1f} MB); {len(shipped)} full pages kept by the "
                   f"option-B copy, {len(restrictive)} of them under all-rights-reserved or vendor terms"),
                  "0 full copies of all-rights-reserved pages in the public copy",
                  "These are research evidence copies (app_design/feasibility/*/sources|probes). Licence by origin: "
                  + json.dumps(dict(Counter(r["licence_hint"] for r in rows))),
                  [f"{r['file']} ({r['bytes'] // 1000} KB, {r['licence_hint'][:40]})"
                   for r in sorted(restrictive, key=lambda r: -r["bytes"])])


# ------------------------------------------------------------------------------------------------- large files
def check_large_files() -> dict:
    rows = [{"file": rel, "bytes": (ROOT / rel).stat().st_size, "ships": ships(rel)} for rel in tracked()]
    rows += [{"file": rel, "bytes": (ROOT / rel).stat().st_size, "ships": "export"} for rel in exports()]
    rows.sort(key=lambda r: -r["bytes"])
    write_csv("large_files", [r for r in rows if r["bytes"] >= 1_000_000])
    tot = sum(r["bytes"] for r in rows if r["ships"] != "export")
    over50 = [r for r in rows if r["bytes"] >= 50_000_000]
    over5 = [r for r in rows if r["bytes"] >= 5_000_000]
    status = "fail" if over50 else ("warn" if over5 else "pass")
    return result("large_files", status,
                  (f"{len(over50)} files >=50 MB, {len(over5)} >=5 MB, "
                   f"{sum(r['bytes'] >= 1_000_000 for r in rows)} >=1 MB; tracked total {tot / 1e6:.1f} MB"),
                  "GitHub warns at 50 MB and rejects 100 MB; 5 MB is this audit's review line",
                  "The >=5 MB files are the derived/v1 tables (provided-data derivatives, private repo only).",
                  [f"{r['file']} {r['bytes'] / 1e6:.1f} MB ({r['ships']})" for r in over5 or rows])


def check_large_blobs_history() -> dict:
    objs = git("rev-list", "--objects", "--all")
    batch = subprocess.run(["git", "-C", str(ROOT), "cat-file", "--batch-check=%(objecttype) %(objectname) %(objectsize)"],
                           input="\n".join(l.split(" ", 1)[0] for l in objs.splitlines()), capture_output=True,
                           text=True, check=True).stdout
    path_of = {l.split(" ", 1)[0]: (l.split(" ", 1)[1] if " " in l else "") for l in objs.splitlines()}
    blobs = [(int(s), path_of.get(h, ""), h) for t, h, s in (l.split() for l in batch.splitlines()) if t == "blob"]
    blobs.sort(reverse=True)
    head = set(tracked())
    gone = [(s, p, h) for s, p, h in blobs if p and p not in head]
    big_gone = [(s, p) for s, p, _ in gone if s >= 1_000_000]
    write_csv("history_blobs", [{"bytes": s, "path": p, "in_head": p in head} for s, p, _ in blobs[:300]])
    total = sum(s for s, _, _ in blobs)
    status = "fail" if blobs and blobs[0][0] >= 50_000_000 else ("warn" if big_gone else "pass")
    return result("large_blobs_history", status,
                  (f"{len(blobs)} blobs, {total / 1e6:.0f} MB uncompressed; largest {blobs[0][0] / 1e6:.1f} MB; "
                   f"{len(gone)} blobs at paths no longer tracked ({len(big_gone)} >=1 MB)"),
                  "no blob >=50 MB; files removed from HEAD still sit in history",
                  "History is why option B builds a fresh single-commit copy instead of flipping visibility.",
                  [f"{p} {s / 1e6:.1f} MB (removed from HEAD)" for s, p in big_gone] +
                  [f"{p} {s / 1e6:.1f} MB" for s, p, _ in blobs[:3]])


# -------------------------------------------------------------------------------- public-copy filter freshness
def check_public_filter() -> dict:
    """tools/public_exclude.txt vs the current tracked set, and the filter's known blind spots."""
    excl = {l for l in (ROOT / "tools/public_exclude.txt").read_text().splitlines() if l and not l.startswith("#")}
    cls = audit_classes()
    now_non_public = {r for r, c in cls.items() if c != "public"}
    stale_missing = sorted(now_non_public - excl)
    m = re.search(r"from the ([\d,]+) tracked files", (ROOT / "DATA_AUDIT.md").read_text())
    doc_n = int(m.group(1).replace(",", "")) if m else -1
    # parquet files the filter samples (first 500 rows) and text files it truncates (8 MB)
    trunc = [r for r in tracked() if not r.endswith(".parquet") and (ROOT / r).stat().st_size > 8_000_000]
    rows = [{"file": r, "class_now": cls[r], "in_exclude_txt": False} for r in stale_missing]
    write_csv("public_filter_stale", rows)
    status = "warn" if stale_missing or doc_n != len(tracked()) else "pass"
    return result("public_filter", status,
                  (f"DATA_AUDIT.md counts {doc_n} tracked files, git has {len(tracked())}; {len(stale_missing)} "
                   f"files the filter now excludes are missing from tools/public_exclude.txt"),
                  "exclude list regenerated after the last commit",
                  ("tools/public_copy.sh reruns tools/data_audit.py before copying, so the stale list is fixed at "
                   "build time; the committed DATA_AUDIT.md is out of date. The filter only looks for record ids, "
                   "sentence ids and coordinates: it does not look for phones, emails, secrets, list names or "
                   f"third-party pages (see the other checks' 'public_copy' rows). {len(trunc)} non-parquet files "
                   "are over its 8 MB read cap."),
                  stale_missing)


# ------------------------------------------------------------------------------------- export shipping contract
def check_export_bundle() -> dict:
    """What the Databricks App bundle carries beyond code, and where its links point."""
    how = json.load(open(ROOT / "app/howto/out/how.json"))
    repo_url = how.get("repo_url", "")
    vis = subprocess.run(["gh", "repo", "view", "LordKarV/databricksdatathon", "--json", "visibility"],
                         capture_output=True, text=True, timeout=30)
    visibility = json.loads(vis.stdout).get("visibility", "unknown") if vis.returncode == 0 else "not run"
    f = json.load(gzip.open(ROOT / "app/facts/out/facts.json.gz"))
    n_claims = len(f["claims"])
    claim_chars = sum(len(v[1]) for v in f["claims"].values() if isinstance(v, list) and len(v) > 1)
    phones = sum(1 for v in f["fac"]["phone_raw"] if v)
    bundle = ROOT / "build/deploy_bundle"
    bundle_files = [str(p.relative_to(bundle)) for p in bundle.rglob("*") if p.is_file()] if bundle.is_dir() else []
    untracked_in_bundle = [p for p in bundle_files if p not in set(tracked()) and not p.startswith(("app/facts/out",
                           "app/packs/out", "planner/out", "app/howto/out", "app/verify/out")) and p not in
                           ("app.yaml", "requirements.txt")]
    rows = [{"item": "repo_url", "value": repo_url, "repo_visibility": visibility},
            {"item": "facts_claims", "value": n_claims, "chars": claim_chars},
            {"item": "facts_phones", "value": phones},
            *[{"item": "untracked_in_bundle", "value": p} for p in untracked_in_bundle]]
    write_csv("export_bundle", rows)
    status = "warn" if (visibility == "PRIVATE" and "github.com" in repo_url) or untracked_in_bundle else "pass"
    return result("export_bundle", status,
                  (f"how.json links {repo_url} (repo {visibility}); facts.json carries {n_claims:,} provided "
                   f"sentences ({claim_chars / 1e6:.1f} M chars) and {phones:,} phone numbers; "
                   f"{len(untracked_in_bundle)} untracked non-export files in build/deploy_bundle"),
                  "links in the shipped app resolve for judges; bundle = tracked code + documented exports",
                  ("The exports are provided-dataset rows shown inside the event's own Databricks workspace app, "
                   "which DATA_AUDIT.md option A treats as in scope of the Marketplace consumer terms; they must "
                   "not be committed (they are .gitignored)."),
                  [r["value"] for r in rows[:1]] + untracked_in_bundle[:4])


UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def check_other_branches() -> dict:
    """Files on any other local or remote branch tip that the checkout does not have (teammates' open work)."""
    head = set(tracked())
    _, raw_phones = raw_contacts()
    rows = []
    for ref in git("for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").split():
        for path in git("ls-tree", "-r", "--name-only", ref).splitlines():
            if path in head or Path(path).suffix.lower() in BINARY_EXT | {".parquet"}:
                continue
            txt = subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:{path}"], capture_output=True,
                                 text=True, errors="ignore").stdout
            phones = {d[-10:] for m in ANY_PHONE.finditer(txt) if len(d := re.sub(r"\D", "", m.group(1))) >= 10}
            rows.append({"ref": ref, "file": path, "secrets": sum(len(rx.findall(txt)) for rx in SECRET_RE.values()),
                         "record_ids": len(set(UUID_RE.findall(txt))), "provided_phones": len(phones & raw_phones),
                         "webmail": len({e for e in EMAIL_RE.findall(txt) if WEBMAIL.search(e)}),
                         "home_path": len(HOME_RE.findall(txt)), "bytes": len(txt)})
    write_csv("other_branches", rows)
    bad = [r for r in rows if r["secrets"] or r["provided_phones"] or r["webmail"]]
    ids = [r for r in rows if r["record_ids"]]
    status = "fail" if any(r["secrets"] for r in rows) else ("warn" if bad or ids else "pass")
    return result("other_branches", status,
                  (f"{len(rows)} text files on other branch tips; {len(ids)} carry record ids, "
                   f"{len(bad)} carry secrets/provided phones/webmail"),
                  "0 secrets; provided rows only in files the public filter would exclude",
                  "Branch tips change while teammates work; rerun before any publish.",
                  [f"{r['ref']}:{r['file']} ids={r['record_ids']} phones={r['provided_phones']}" for r in (bad or ids)])


CHECKS = [check_secrets_tracked, check_secrets_history, check_user_identity, check_emails, check_doctor_mobiles_text,
          check_doctor_mobiles_exports, check_patient_like, check_provided_contacts_public_copy,
          check_provided_names_public_copy, check_restricted_list_copies, check_crawled_page_bodies,
          check_third_party_pages, check_large_files, check_large_blobs_history, check_public_filter,
          check_export_bundle, check_other_branches]


def main() -> None:
    names = sys.argv[1:]
    res = []
    for fn in CHECKS:
        if names and fn.__name__.removeprefix("check_") not in names:
            continue
        try:
            r = fn()
        except Exception as e:  # report, never hide: a crashed check is "not run", not green
            r = result(fn.__name__.removeprefix("check_"), "fail", "not run", "", f"{type(e).__name__}: {e}", [])
        print(json.dumps(r, ensure_ascii=True)[:1500], flush=True)
        res.append(r)
    if not names:
        (OUT / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=True))


if __name__ == "__main__":
    main()
