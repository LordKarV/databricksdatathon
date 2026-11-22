"""Independent re-count of the privacy / licence audit (validation/privacy_licence). Read-only.

Own code: it does not import the auditor's checks.py. It imports tools/data_audit.py only to learn which class the
option-B filter gives each tracked file, because that filter is the thing under test.
Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python validation/privacy_licence/verify/checks.py [names]
Every check_<name>() returns dict(name, status, metric, threshold, detail, examples) and writes out/<name>.csv.
Outputs mask numbers to their last 4 digits and never copy email users or full facility rows.
"""
from __future__ import annotations

import csv
_HANDLES = tuple(h for h in __import__("os").environ.get("PRIVACY_HANDLES", "").split(",") if h)
import gzip
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "validation/privacy_licence/verify"
OUT = HERE / "out"
EXPORT_DIRS = ("app/facts/out", "app/packs/out", "planner/out", "app/howto/out")
MEDIA = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".wav", ".mp3", ".mp4", ".webm", ".ttf", ".otf", ".woff",
         ".woff2", ".pdf", ".ico", ".pyc", ".sqlite", ".db"}


# ------------------------------------------------------------------------------------------------- corpus helpers
def sh(*args: str, inp: str | None = None) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True, input=inp,
                          errors="replace").stdout


@lru_cache(maxsize=1)
def tracked() -> tuple[str, ...]:
    return tuple(p for p in sh("git", "ls-files", "-z").split("\0") if p and (ROOT / p).is_file())


@lru_cache(maxsize=1)
def exports() -> tuple[str, ...]:
    return tuple(sorted(str(f.relative_to(ROOT)) for d in EXPORT_DIRS if (ROOT / d).is_dir()
                        for f in (ROOT / d).rglob("*") if f.is_file()))


def decode(raw: bytes, name: str) -> str:
    if name.endswith(".gz"):
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return ""
    if b"\x00" in raw[:4096]:
        return ""
    return raw.decode("utf-8", errors="ignore")


@lru_cache(maxsize=4096)
def read(rel: str) -> str:
    p = ROOT / rel
    if p.suffix.lower() in MEDIA:
        return ""
    if p.suffix == ".parquet":
        t = pq.read_table(p)
        cols = [c for c, ty in zip(t.column_names, t.schema.types) if "string" in str(ty)]
        out = []
        for c in cols:
            for v in t.column(c).to_pylist():
                if isinstance(v, list):
                    out += [str(x) for x in v if x]
                elif v:
                    out.append(v)
        return "\n".join(out)
    return decode(p.read_bytes(), p.name)


@lru_cache(maxsize=1)
def filter_class() -> dict[str, tuple[str, str]]:
    """The option-B filter's verdict for every tracked file (cached: it reads every file)."""
    cache = HERE / "out/_filter_class.json"
    if cache.exists():
        d = json.loads(cache.read_text())
        if set(d) == set(tracked()):
            return {k: tuple(v) for k, v in d.items()}
    spec = importlib.util.spec_from_file_location("data_audit_filter", ROOT / "tools/data_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    d = {rel: mod.classify(rel) for rel in tracked()}
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(d))
    return d


def public(rel: str) -> bool:
    return filter_class().get(rel, ("?",))[0] == "public"


def write(name: str, rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r)) or ["none"]
    with (OUT / f"{name}.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def res(name, status, metric, threshold, detail, examples):
    return dict(name=name, status=status, metric=metric, threshold=threshold, detail=detail, examples=examples[:5])


def last4(d: str) -> str:
    return "..." + d[-4:]


# ------------------------------------------------------------------------------------------ provided-table indexes
@lru_cache(maxsize=1)
def raw():
    import pandas as pd
    return pd.read_parquet(ROOT / "data/raw/facilities.parquet")


DIGITS = re.compile(r"\+?\d[\d \-()]{8,16}\d")


def phones_in(txt: str) -> set[str]:
    """Indian numbers in text, normalised to their last 10 digits (mobiles and STD landlines)."""
    out = set()
    for m in DIGITS.finditer(txt):
        d = re.sub(r"\D", "", m.group(0))
        if d.startswith("91") and len(d) == 12:
            d = d[2:]
        elif d.startswith("0") and len(d) == 11:
            d = d[1:]
        if len(d) == 10 and d[0] != "0":
            out.add(d)
    return out


@lru_cache(maxsize=1)
def provided_phones() -> frozenset:
    r = raw()
    s = set()
    for c in ("phone_numbers", "officialPhone"):
        for v in r[c].dropna().astype(str):
            s |= phones_in(v)
    return frozenset(s)


def norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(s).lower().replace("&", " and ")))


@lru_cache(maxsize=1)
def provided_names() -> dict[str, int]:
    """Normalised provided facility name -> number of raw records carrying it (>=3 words, >=15 chars)."""
    c = Counter(norm(n) for n in raw().name.dropna())
    return {n: k for n, k in c.items() if len(n.split()) >= 3 and len(n) >= 15}


def names_in(txt: str, ix: dict[str, int]) -> set[str]:
    """Provided names that occur in txt on word boundaries (window search over the token stream)."""
    toks = norm(txt).split()
    by_len = defaultdict(set)
    for n in ix:
        by_len[len(n.split())].add(n)
    first = {n.split()[0] for n in ix}
    hits = set()
    for i, t in enumerate(toks):
        if t not in first:
            continue
        for L, names in by_len.items():
            g = " ".join(toks[i:i + L])
            if g in names:
                hits.add(g)
    return hits


# ------------------------------------------------------------------------------------------------------ secrets
SECRETS = {
    "google_api_key": r"AIza[0-9A-Za-z_\-]{35}",
    "databricks_pat": r"dapi[0-9a-f]{32}",
    "github": r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_\w{40,}",
    "anthropic": r"sk-ant-[\w-]{20,}",
    "openai": r"sk-(?:proj-)?[A-Za-z0-9]{40,}",
    "aws": r"(?<![A-Za-z0-9+/])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9+/=])",  # not inside base64 (OSRM "hint" fields)
    "slack": r"xox[abprs]-[\w-]{10,}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY",
    "jwt": r"eyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,}",
    "bearer": r"(?i)bearer\s+[A-Za-z0-9._\-]{30,}",
    "token_env": r"(?i)(?:DATABRICKS_TOKEN|HF_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY|GITHUB_TOKEN)\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}",
}
SECRET_RX = {k: re.compile(v) for k, v in SECRETS.items()}


def _blob_texts():
    """Every blob reachable from any ref (history), as (sha, path, text)."""
    objs = sh("git", "rev-list", "--objects", "--all").splitlines()
    path = {}
    for line in objs:
        sha, _, p = line.partition(" ")
        path.setdefault(sha, p)
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    proc.stdin.write(("\n".join(path) + "\n").encode())
    proc.stdin.close()
    f = proc.stdout
    while True:
        header = f.readline()
        if not header:
            break
        sha, typ, size = header.decode().split()[:3]
        data = f.read(int(size))
        f.read(1)
        if typ == "blob":
            yield sha, path[sha], data
    proc.wait()


def check_v_secrets() -> dict:
    rows = []
    files_tp = set()
    for sha, p, data in _blob_texts():
        if Path(p).suffix.lower() in MEDIA:
            continue
        txt = decode(data, p) if not p.endswith(".parquet") else ""
        for k, rx in SECRET_RX.items():
            for m in rx.finditer(txt):
                tp = bool(re.search(r"/(sources|probes)/", p))
                files_tp.add(p) if tp else None
                rows.append({"where": "history_blob", "path": p, "kind": k, "value_sha_prefix": sha[:8],
                             "value_head": m.group(0)[:8], "value_tail4": m.group(0)[-4:], "third_party_page": tp})
    for rel in exports():
        for k, rx in SECRET_RX.items():
            for m in rx.finditer(read(rel)):
                rows.append({"where": "export", "path": rel, "kind": k, "value_head": m.group(0)[:8],
                             "value_tail4": m.group(0)[-4:], "third_party_page": False})
    write("v_secrets", rows)
    own = [r for r in rows if not r["third_party_page"]]
    keys = {(r["value_head"], r["value_tail4"]) for r in rows if r["kind"] == "google_api_key"}
    head_tp = [r for r in rows if r["third_party_page"] and r["path"] in set(tracked())]
    return res("v_secrets", "fail" if own else ("warn" if rows else "pass"),
               (f"{len(own)} non-third-party hits; {len(rows)} hits over all history blobs + exports, "
                f"{len({r['path'] for r in rows})} paths; distinct Google keys {len(keys)}; "
                f"by kind {dict(Counter(r['kind'] for r in rows))}"),
               "0 project credentials in any blob ever committed or any export",
               "Scans every blob reachable from every ref (not only added diff lines), so a secret later deleted "
               f"still counts. Third-party-page hits in HEAD paths: {len(head_tp)}.",
               [f"{r['path']} {r['kind']} {r['value_head']}..{r['value_tail4']}" for r in (own or rows)][:5])


# ------------------------------------------------------------------------------------------------ identity
def check_v_identity() -> dict:
    rows = []
    users = Counter()
    for rel in list(tracked()) + list(exports()):
        t = read(rel)
        homes = re.findall(r"/Users/([A-Za-z0-9._-]+)/", t)
        users.update(homes)
        n_email = sum(t.count(h) for h in _HANDLES)
        n_handle = len(re.findall(r"LordKarV", t))
        if homes or n_email or n_handle:
            rows.append({"file": rel, "home_paths": len(homes), "user_ids": n_email, "github_handle": n_handle,
                         "public": public(rel) if rel in filter_class() else "export"})
    write("v_identity", rows)
    hp = [r for r in rows if r["home_paths"]]
    hp_pub = [r for r in hp if r["public"] is True]
    gh = [r for r in rows if r["github_handle"]]
    return res("v_identity", "warn" if hp_pub else "pass",
               (f"/Users/<name>/ in {len(hp)} files ({sum(r['home_paths'] for r in hp)} mentions), "
                f"{len(hp_pub)} public-class; home names {dict(users.most_common(5))}; user email/id in "
                f"{sum(1 for r in rows if r['user_ids'])} files; GitHub handle in {len(gh)} files"),
               "0 home paths in public-class files", "Exports included.",
               [f"{r['file']} home x{r['home_paths']}" for r in sorted(hp_pub, key=lambda r: -r["home_paths"])])


# -------------------------------------------------------------------------------- provided phones in option B
def check_v_provided_phones_public() -> dict:
    P = provided_phones()
    rows, union = [], set()
    for rel in tracked():
        if not public(rel):
            continue
        hit = phones_in(read(rel)) & P
        if hit:
            union |= hit
            rows.append({"file": rel, "provided_numbers": len(hit), "ext": Path(rel).suffix,
                         "eg_last4": ";".join(sorted(last4(h) for h in hit)[:3])})
    rows.sort(key=lambda r: -r["provided_numbers"])
    write("v_provided_phones_public", rows)
    big = [r for r in rows if r["provided_numbers"] >= 20]
    return res("v_provided_phones_public", "fail" if big else ("warn" if rows else "pass"),
               (f"{len(rows)} public-class files carry provided numbers; {len(union)} DISTINCT numbers "
                f"(sum over files {sum(r['provided_numbers'] for r in rows)}); {len(big)} files with >=20; "
                f"provided set {len(P)}"),
               "0 provided numbers in the option-B copy",
               "Own normaliser: +91 / 0 prefixes stripped, separators ignored, last 10 digits.",
               [f"{r['file']}: {r['provided_numbers']}" for r in rows])


# --------------------------------------------------------------------------------- provided names in option B
GENERIC = re.compile(r"\b(primary health|community health|district hospital|sub district|government|govt|"
                     r"civil hospital|esi|railway|phc|chc|urban health)\b")


def check_v_names_public() -> dict:
    ix = provided_names()
    rows = []
    for rel in tracked():
        if not public(rel):
            continue
        t = read(rel)
        if not t:
            continue
        hits = names_in(t, ix)
        if hits:
            gen = {h for h in hits if GENERIC.search(h) or ix[h] >= 3}
            rows.append({"file": rel, "names": len(hits), "specific_names": len(hits - gen), "generic_or_shared":
                         len(gen)})
    rows.sort(key=lambda r: -r["names"])
    write("v_names_public", rows)
    bulk = [r for r in rows if r["specific_names"] >= 20]
    return res("v_names_public", "fail" if bulk else ("warn" if rows else "pass"),
               (f"{len(rows)} public-class files name >=1 provided facility; {sum(r['names'] >= 20 for r in rows)} "
                f"name >=20; {len(bulk)} name >=20 specific (non-government, unique) names"),
               "0 public files listing >=20 specific provided names",
               "Whole-name match on word boundaries, names >=3 words and >=15 chars; 'generic' = government "
               "facility type words or a name carried by >=3 records.",
               [f"{r['file']}: {r['names']} ({r['specific_names']} specific)" for r in rows])


# ------------------------------------------------------------------------------- doctor mobiles in exports
AUD_DR = re.compile(r"^\s*(?:Dr|DR|dr)\.?\s*[A-Za-z]|\bDr\.?\s+[A-Z][a-z]+", re.M)  # the auditor's rule, for diffing
STRICT_DR = re.compile(r"(?:^|[\s(,])(?:Dr|DR|dr)(?:\.\s*|\s+)[A-Za-z]")
INST = re.compile(r"(?i)hospital|institute|nursing home|medical college|research cent|multi ?speciality|"
                  r"healthcare|health care|eye care|\bpvt\b|\bltd\b|\bclinic\b|centre|center|diagnostic|dental|lab")


def check_v_doctor_mobiles_exports() -> dict:
    f = json.load(gzip.open(ROOT / "app/facts/out/facts.json.gz"))["fac"]
    rows = []
    n_any = 0
    for i, fid in enumerate(f["id"]):
        d = re.sub(r"\D", "", str(f["phone_e164"][i] or f["phone_raw"][i] or ""))[-10:]
        if len(d) < 10 or d[0] not in "6789":
            continue
        n_any += 1
        name = f["name"][i] or ""
        a, s = bool(AUD_DR.search(name)), bool(STRICT_DR.search(name))
        if a or s:
            rows.append({"id8": fid[:8], "name": name[:60], "auditor_rule": a, "strict_rule": s,
                         "shared": f["phone_shared"][i], "own_site": bool(f["website_own"][i]),
                         "no_institution_word": not INST.search(name), "mobile": last4(d)})
    write("v_doctor_mobiles_exports", rows)
    aud = [r for r in rows if r["auditor_rule"]]
    fp = [r for r in aud if not r["strict_rule"]]
    strict = [r for r in rows if r["strict_rule"]]
    strict_unshared = [r for r in strict if (r["shared"] or 1) <= 1]
    return res("v_doctor_mobiles_exports", "warn" if strict else "pass",
               (f"{n_any} facilities show a mobile; auditor's Dr rule hits {len(aud)}, of which {len(fp)} are not "
                f"'Dr' as a title (Drishti, Dream...); strict 'Dr.'/'Dr ' title: {len(strict)}, "
                f"{len(strict_unshared)} with an unshared number"),
               "doctor-titled records with a mobile counted with a title-only rule",
               "Strict rule: 'Dr' followed by '.' or a space. Not hand-checked for whether the number is personal.",
               [f"{r['id8']} '{r['name'][:40]}' (auditor rule only)" for r in fp][:3] +
               [f"{r['id8']} '{r['name'][:40]}' {r['mobile']}" for r in strict_unshared][:2])


DOC_CTX = re.compile(r"\bDr\.?\s+[A-Z][a-z]+|\bMBBS\b|\bBDS\b|\bMDS\b|\bM\.D\.|\bFRCS\b")
# not OSM element ids (node/123...) or Wikidata Q-ids
MOB = re.compile(r"(?<![\d/Q])(?:\+91[\s-]?|91[\s-]?|0)?([6-9]\d{4}[\s-]?\d{5})(?!\d)")


def check_v_doctor_mobiles_text() -> dict:
    """Mobiles within 150 chars of a doctor TITLE or degree (no 'consultant'/'doctor' words), split by filter class."""
    rows = []
    for rel in list(tracked()) + list(exports()):
        if re.search(r"/(sources|probes)/", rel):
            continue
        t = read(rel)
        for m in MOB.finditer(t):
            if DOC_CTX.search(t[max(0, m.start() - 150): m.end() + 150]):
                rows.append({"file": rel, "mobile": re.sub(r"\D", "", m.group(1)),
                             "where": "export" if rel in exports() else
                             ("public" if public(rel) else filter_class()[rel][0])})
    by = defaultdict(set)
    for r in rows:
        by[(r["file"], r["where"])].add(r["mobile"])
    out = [{"file": k[0], "where": k[1], "distinct_mobiles": len(v)} for k, v in by.items()]
    out.sort(key=lambda r: -r["distinct_mobiles"])
    write("v_doctor_mobiles_text", out)
    allm = {r["mobile"] for r in rows}
    shipped = {r["mobile"] for r in rows if r["where"] in ("public", "export")}
    pub = {r["mobile"] for r in rows if r["where"] == "public"}
    return res("v_doctor_mobiles_text", "fail" if pub else "warn",
               (f"{len(allm)} distinct mobiles near a doctor title/degree in {len(out)} files; "
                f"{len(shipped)} in public-class or export files ({len(pub)} public-class)"),
               "0 in public-class files", "Narrower context rule than the auditor (no 'consultant', 'doctor').",
               [f"{r['file']} ({r['where']}): {r['distinct_mobiles']}" for r in out if r["where"] != "provided"][:5])


# ------------------------------------------------------------------------------------- third-party saved pages
def check_v_third_party_pages() -> dict:
    rows = []
    for rel in tracked():
        if not re.search(r"(^|/)(sources|probes)/[^/]+$", rel) or rel.startswith("viz/sources/") or "/fixtures/" in rel:
            continue
        t = read(rel)
        keys = set(SECRET_RX["google_api_key"].findall(t))
        rows.append({"file": rel, "kb": (ROOT / rel).stat().st_size // 1000, "public": public(rel),
                     "html_page": bool(re.search(r"<html|<!doctype", t[:5000], re.I)),
                     "aiza_occurrences": len(SECRET_RX["google_api_key"].findall(t)), "aiza_distinct": len(keys),
                     "jwt": len(SECRET_RX["jwt"].findall(t)),
                     "copyright_line": (re.search(r"(?i)(©|&copy;|copyright)[^<\n]{0,60}", t) or [None])[0]})
    write("v_third_party_pages", rows)
    allkeys = set()
    for r in rows:
        allkeys |= set(SECRET_RX["google_api_key"].findall(read(r["file"])))
    kp = [r for r in rows if r["aiza_occurrences"]]
    pub_full = [r for r in rows if r["public"] and r["html_page"]]
    return res("v_third_party_pages", "warn" if pub_full else "pass",
               (f"{len(rows)} saved pages ({sum(r['kb'] for r in rows) / 1000:.1f} MB); {sum(r['public'] for r in rows)}"
                f" public-class, {len(pub_full)} public-class full HTML pages; AIza: "
                f"{sum(r['aiza_occurrences'] for r in kp)} occurrences of {len(allkeys)} distinct keys in {len(kp)} "
                f"files ({sum(r['public'] for r in kp)} public-class)"),
               "0 full third-party pages in the public copy", "",
               [f"{r['file']} aiza={r['aiza_occurrences']} public={r['public']}" for r in kp])


# --------------------------------------------------------------------------------- filter blind spots (new)
READ_EXT = {".parquet", ".csv", ".tsv", ".json", ".jsonl", ".gz", ".txt", ".xlsx", ".geojson", ".py", ".js", ".sh",
            ".sql", ".html", ".css", ".md", ".yaml", ".yml", ".toml", ".webmanifest", ".ipynb"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webm", ".mp4", ".pdf"}
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
SID = re.compile(r"\b[0-9a-f]{8}:(?:proc|equi|capa|desc|spec|name)\b")


def check_v_filter_unread_ext() -> dict:
    """Tracked files whose extension tools/data_audit.py never reads: they fall to 'public' without a scan."""
    ix, P = provided_names(), provided_phones()
    rows = []
    for rel in tracked():
        ext = Path(rel).suffix.lower()
        if ext in READ_EXT or ext in IMG_EXT:
            continue
        t = read(rel)
        rows.append({"file": rel, "ext": ext or "(none)", "class": filter_class()[rel][0],
                     "record_ids": len(set(UUID.findall(t))), "sentence_ids": len(set(SID.findall(t))),
                     "provided_phones": len(phones_in(t) & P), "provided_names": len(names_in(t, ix)) if t else 0})
    write("v_filter_unread_ext", rows)
    leak = [r for r in rows if r["class"] == "public" and (r["record_ids"] or r["sentence_ids"] or
                                                           r["provided_names"] >= 5 or r["provided_phones"])]
    return res("v_filter_unread_ext", "fail" if any(r["record_ids"] or r["sentence_ids"] for r in leak) else
               ("warn" if leak else "pass"),
               (f"{len(rows)} tracked files with unread extensions ({dict(Counter(r['ext'] for r in rows))}); "
                f"{len(leak)} public-class carry ids or provided names/phones; "
                f"{sum(1 for r in leak if r['record_ids'] or r['sentence_ids'])} carry record/sentence ids"),
               "0 unread files carrying provided ids", "tools/data_audit.py:54-57 and :87 read only DATA_EXT and "
               "CODE_EXT; .svg/.log/.out fall through to 'public' with txt=''.",
               [f"{r['file']}: ids={r['record_ids']} sids={r['sentence_ids']} names={r['provided_names']} "
                f"phones={r['provided_phones']}" for r in sorted(leak, key=lambda r: -(r['record_ids'] + r['sentence_ids']))])


# ----------------------------------------------------------------------------------- filter staleness recount
def check_v_public_filter_stale() -> dict:
    excl = {l for l in (ROOT / "tools/public_exclude.txt").read_text().splitlines() if l and not l.startswith("#")}
    cls = filter_class()
    non_pub = {r for r, c in cls.items() if c[0] != "public"}
    missing = sorted(non_pub - excl)
    extra = sorted(excl - non_pub)
    gone = sorted(e for e in excl if e not in cls)
    m = re.search(r"from the ([\d,]+) tracked", (ROOT / "DATA_AUDIT.md").read_text())
    rows = [{"file": f, "kind": "missing_from_exclude", "class": cls[f][0]} for f in missing] + \
           [{"file": f, "kind": "excluded_but_now_public", "class": cls.get(f, ("untracked",))[0]} for f in extra]
    write("v_public_filter_stale", rows)
    return res("v_public_filter_stale", "warn" if missing or extra else "pass",
               (f"DATA_AUDIT.md says {m.group(1) if m else '?'} files, git {len(cls)}; {len(missing)} non-public "
                f"files missing from exclude list ({dict(Counter(cls[f][0] for f in missing))}); {len(extra)} "
                f"listed but now public or untracked ({len(gone)} untracked)"),
               "exclude list equals the filter's current non-public set", "",
               missing[:5])


# ------------------------------------------------------------------------------- untracked validation outputs
def check_v_validation_outputs() -> dict:
    """validation/ is untracked today; if committed, what the filter would let into the public copy."""
    spec = importlib.util.spec_from_file_location("data_audit_filter2", ROOT / "tools/data_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    P = provided_phones()
    rows = []
    for p in sorted((ROOT / "validation").rglob("*")):
        rel = str(p.relative_to(ROOT))
        if not p.is_file() or "/.venv" in rel or "__pycache__" in rel or rel.startswith(
                "validation/privacy_licence/verify/"):
            continue
        if p.stat().st_size > 30_000_000:
            continue
        t = decode(p.read_bytes(), p.name) if p.suffix not in (".parquet",) and p.suffix.lower() not in MEDIA else ""
        ph = len(phones_in(t) & P)
        em = len({e for e in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", t) if re.search(r"@(gmail|yahoo|rediffmail|hotmail|outlook)\.", e, re.I)})
        uid = any(h in t for h in _HANDLES)
        if ph or em or uid:
            try:
                c = mod.classify(rel)[0]
            except Exception as e:  # noqa: BLE001 - report, the filter crashing is itself a finding
                c = f"error {type(e).__name__}"
            rows.append({"file": rel, "provided_phones": ph, "webmail": em, "user_id": uid, "filter_class": c})
    write("v_validation_outputs", rows)
    pub = [r for r in rows if r["filter_class"] == "public"]
    return res("v_validation_outputs", "warn" if pub else "pass",
               (f"{len(rows)} untracked validation/ files carry provided phones, webmail or the user id; "
                f"{len(pub)} would be 'public' if committed ({sum(r['provided_phones'] for r in pub)} phone hits, "
                f"{sum(r['webmail'] for r in pub)} webmail, {sum(r['user_id'] for r in pub)} with the user id)"),
               "0 public-class validation files with personal data", "validation/ is not tracked now.",
               [f"{r['file']}: phones={r['provided_phones']} webmail={r['webmail']} uid={r['user_id']} "
                f"class={r['filter_class']}" for r in sorted(pub, key=lambda r: -r["provided_phones"])])


# ---------------------------------------------------------------------------------------- other branch tips
def check_v_other_branches() -> dict:
    head = set(tracked())
    P = provided_phones()
    rows = []
    for ref in sh("git", "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").split():
        for path in sh("git", "ls-tree", "-r", "--name-only", ref).splitlines():
            if path in head or Path(path).suffix.lower() in MEDIA | {".parquet"}:
                continue
            t = sh("git", "show", f"{ref}:{path}")
            rows.append({"ref": ref, "file": path, "ids": len(set(UUID.findall(t))),
                         "phones": len(phones_in(t) & P),
                         "secrets": sum(len(rx.findall(t)) for rx in SECRET_RX.values())})
    write("v_other_branches", rows)
    ids = [r for r in rows if r["ids"]]
    return res("v_other_branches", "fail" if any(r["secrets"] for r in rows) else ("warn" if ids else "pass"),
               (f"{len(rows)} (ref, file) text pairs not in HEAD, {len({r['file'] for r in rows})} distinct paths; "
                f"{len(ids)} pairs with record ids ({len({r['file'] for r in ids})} paths); "
                f"phones {sum(r['phones'] for r in rows)}; secrets {sum(r['secrets'] for r in rows)}"),
               "0 secrets", "", [f"{r['ref']}:{r['file']} ids={r['ids']}" for r in ids])


def _shingles(txt: str, k: int = 12) -> set[int]:
    w = re.findall(r"[a-z0-9]+", txt.lower())
    return {hash(" ".join(w[i:i + k])) for i in range(0, max(0, len(w) - k + 1))}


def _unjson(v) -> str:
    """Raw list cells are JSON text with \\uXXXX escapes; decode them so words match the decoded claims."""
    v = str(v)
    if v.startswith("["):
        try:
            return "\n".join(map(str, json.loads(v)))
        except ValueError:
            pass
    return v


def check_v_crawl_shingles() -> dict:
    """12-word shingles of each public-class file / export / kb file that occur in crawled pages but not in the
    provided table. Boundary-free, so it also catches page text pasted without sentence breaks.
    ponytail: derived/v1 claims and data_point_scores are skipped (private-only, ~10M shingles); add if needed."""
    skip = {"derived/v1/claims.parquet", "derived/v1/data_point_scores.parquet"}
    cand = [r for r in tracked() if r not in skip and (public(r) or r.startswith(("kb/", "derived/")))] + list(exports())
    per = {}
    for rel in cand:
        t = read(rel)
        if t:
            s = _shingles(t)
            if s:
                per[rel] = s
    want = set().union(*per.values())
    in_crawl = set()
    for p in (ROOT / "data/crawl/pages").glob("*.json.gz"):
        try:
            in_crawl |= _shingles(json.load(gzip.open(p)).get("text") or "") & want
        except (OSError, ValueError):
            continue
    rawtxt = "\n".join(_unjson(v) for c in raw().columns if raw()[c].dtype.kind not in "biufmMb" for v in raw()[c].dropna())
    crawl_only = in_crawl - _shingles(rawtxt)
    rows = [{"file": r, "crawl_only_shingles": len(s & crawl_only), "shingles": len(s),
             "where": "export" if r in exports() else filter_class()[r][0]} for r, s in per.items() if s & crawl_only]
    rows.sort(key=lambda r: -r["crawl_only_shingles"])
    write("v_crawl_shingles", rows)
    pub = [r for r in rows if r["where"] in ("public", "export")]
    return res("v_crawl_shingles", "warn" if any(r["crawl_only_shingles"] >= 500 for r in pub) else "pass",
               (f"{len(per)} files scanned; {len(rows)} share crawl-only 12-word shingles; max in a public/export "
                f"file {max([r['crawl_only_shingles'] for r in pub] or [0])}"),
               ">=500 crawl-only shingles (about 50 sentences) in a shipped file = a page-body copy",
               "Skipped derived/v1/claims.parquet and data_point_scores.parquet.",
               [f"{r['file']} ({r['where']}): {r['crawl_only_shingles']} of {r['shingles']}" for r in rows])


# ------------------------------------------------------------------------------------------- missed by the audit
def check_v_svg_png_twins() -> dict:
    """The filter excludes chart PNGs as 'image' (they show provided names) but keeps the identical SVG twin."""
    cls, ix = filter_class(), provided_names()
    rows = []
    for rel in tracked():
        if not rel.endswith(".svg"):
            continue
        t = read(rel)
        png = rel[:-4] + ".png"
        rows.append({"svg": rel, "svg_class": cls[rel][0], "png_twin_class": cls.get(png, ("none",))[0],
                     "provided_names": len(names_in(t, ix)), "sentence_ids": len(set(SID.findall(t))),
                     "record_ids": len(set(UUID.findall(t)))})
    write("v_svg_png_twins", rows)
    leak = [r for r in rows if r["svg_class"] == "public" and r["png_twin_class"] == "image"]
    named = [r for r in leak if r["provided_names"] or r["sentence_ids"] or r["record_ids"]]
    return res("v_svg_png_twins", "warn" if named else "pass",
               (f"{len(rows)} tracked SVGs, {len(leak)} public-class with a PNG twin classed 'image'; {len(named)} "
                f"of them name provided facilities or carry ids ({sum(r['provided_names'] for r in named)} names, "
                f"{sum(r['sentence_ids'] for r in named)} sentence ids)"),
               "SVG twin gets the same class as its PNG", "tools/data_audit.py MEDIA_EXT (line 34) has no .svg and "
               "the read set (DATA_EXT, CODE_EXT) skips .svg, so an SVG is never scanned.",
               [f"{r['svg']}: names={r['provided_names']} sids={r['sentence_ids']}"
                for r in sorted(named, key=lambda r: -(r["provided_names"] + r["sentence_ids"]))])


def check_v_blood_bulk_export() -> dict:
    """planner/out/planner_v1.json.gz embeds the e-RaktKosh centre directory, which its README says not to publish."""
    d = json.load(gzip.open(ROOT / "planner/out/planner_v1.json.gz"))
    b = d.get("blood") or {}
    names = (b.get("centres") or {}).get("name") or []
    import pandas as pd
    m = pd.read_parquet(ROOT / "data/external/eraktkosh_blood_centres/erk_vf_matches.parquet", columns=["erk_name"])
    matched = set(m.erk_name)
    unmatched = [n for n in names if n not in matched]
    in_bundle = (ROOT / "build/deploy_bundle/planner/out/planner_v1.json.gz").is_file()
    write("v_blood_bulk_export", [{"centre_name": n[:60]} for n in unmatched[:200]])
    return res("v_blood_bulk_export", "warn" if unmatched else "pass",
               (f"planner_v1.json.gz carries {len(names)} e-RaktKosh centres (names + lat/lon), {len(unmatched)} not "
                f"matched to any VF record; copy in build/deploy_bundle: {in_bundle}"),
               "only per-facility e-RaktKosh facts for matched VF records ship",
               "external/eraktkosh_blood_centres/README.md:25-26 'Do not publish the bulk table'; "
               "research/DATASETS.md:207-208 same. Producer: planner/export_v1.py:42-53 (blood()).",
               unmatched[:5])


WS_IDS = {"workspace_host": r"dbc-[0-9a-f]{8}-[0-9a-f]{4}\.cloud\.databricks\.com",
          "warehouse_id": r"\b6a2f5637720a2c17\b", "app_sp_id": r"3770ad65-e41d-4f22-8b7d-305dfc97dc1d",
          "dashboard_or_genie_id": r"\b01f1e6[0-9a-f]{26}\b"}


def check_v_workspace_ids() -> dict:
    """Databricks workspace host and resource ids in files option B would publish (identifiers, not credentials)."""
    rows = []
    for rel in tracked():
        t = read(rel)
        hits = {k: len(re.findall(v, t)) for k, v in WS_IDS.items()}
        if any(hits.values()):
            rows.append({"file": rel, "class": filter_class()[rel][0], **hits})
    write("v_workspace_ids", rows)
    pub = [r for r in rows if r["class"] == "public"]
    return res("v_workspace_ids", "warn" if pub else "pass",
               f"{len(rows)} tracked files name the workspace host or resource ids; {len(pub)} public-class",
               "0 workspace identifiers in the option-B copy (low: identifiers are not credentials)",
               "The app service-principal id in grants.sql is classed 'provided' by the UUID rule by accident.",
               [f"{r['file']} ({r['class']})" for r in pub])


def check_v_deploy_bundle() -> dict:
    """Secrets and personal data in the untracked build/deploy_bundle (what deploy.sh uploads to the workspace)."""
    base = ROOT / "build/deploy_bundle"
    if not base.is_dir():
        return res("v_deploy_bundle", "warn", "not run: build/deploy_bundle missing", "", "", [])
    P = provided_phones()
    rows = []
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix.lower() in MEDIA:
            continue
        rel = str(p.relative_to(ROOT))
        t = decode(p.read_bytes(), p.name)
        sec = {k: len(rx.findall(t)) for k, rx in SECRET_RX.items() if rx.search(t)}
        rows.append({"file": rel, "secrets": json.dumps(sec) if sec else "", "provided_phones": len(phones_in(t) & P),
                     "kb": p.stat().st_size // 1000})
    write("v_deploy_bundle", rows)
    sec = [r for r in rows if r["secrets"]]
    sqlite = [str(p.relative_to(ROOT)) for p in base.rglob("*.sqlite")]
    return res("v_deploy_bundle", "fail" if sec else ("warn" if sqlite else "pass"),
               (f"{len(rows)} text files in the bundle, {len(sec)} with a secret pattern; sqlite files {sqlite}; "
                f"{sum(1 for r in rows if r['provided_phones'])} files carry provided phones (expected in exports)"),
               "0 secrets in the bundle", "", [f"{r['file']} {r['secrets']}" for r in sec] or sqlite)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (c - h) / d, (c + h) / d


# Hand labels (read by the verifier, 2026-11-21) of a seed-20261121 sample of 40 from the auditor's 380
# 'personal_likely' rows: does the name carry a person's name? Not person-named: Drishti (Hindi 'vision', not
# a title), 'Dr Smile' (brand), 'Dr. VCs' (initials only). Whether the NUMBER is personal cannot be read from text.
P2_NOT_PERSON = {"8cea1673", "02456893", "1faf226f"}


def check_v_p2_name_precision() -> dict:
    import pandas as pd
    d = pd.read_csv(ROOT / "validation/privacy_licence/out/doctor_mobiles_exports.csv")
    s = d[d.tier != "doctor_named"].sample(40, random_state=20261121)
    ids = [i[:8] for i in s.id]
    k = sum(1 for i in ids if i not in P2_NOT_PERSON)
    lo, hi = wilson(k, len(ids))
    write("v_p2_name_precision", [{"id8": i, "name": n[:60], "person_named": i not in P2_NOT_PERSON}
                                  for i, n in zip(ids, s.name)])
    return res("v_p2_name_precision", "warn", f"{k}/{len(ids)} sampled 'personal_likely' names carry a person's name "
               f"({k / len(ids):.0%}, 95% Wilson {lo:.0%}-{hi:.0%})", "precision of the name rule, not of 'personal'",
               "All 40 are clinics named after a doctor, with the number listed for the business; none is shown to be "
               "a private number. The auditor's example ...2706 (kb/web_evidence/out/llm_hours_raw.json) is an 011 "
               "Delhi landline of 'Smile Dental Hub', not a mobile.", [f"{i} {n[:40]}" for i, n in
                                                                     zip(ids, s.name) if i in P2_NOT_PERSON])


CHECKS = [check_v_svg_png_twins, check_v_blood_bulk_export, check_v_workspace_ids, check_v_deploy_bundle,
          check_v_p2_name_precision, check_v_crawl_shingles, check_v_secrets, check_v_identity, check_v_provided_phones_public, check_v_names_public,
          check_v_doctor_mobiles_exports, check_v_doctor_mobiles_text, check_v_third_party_pages,
          check_v_filter_unread_ext, check_v_public_filter_stale, check_v_validation_outputs, check_v_other_branches]


def main() -> None:
    want = sys.argv[1:]
    results = []
    for fn in CHECKS:
        if want and fn.__name__[6:] not in want:
            continue
        try:
            r = fn()
        except Exception as e:  # a crashed check is "not run", never green
            r = res(fn.__name__[6:], "fail", "not run", "", f"{type(e).__name__}: {e}", [])
        print(json.dumps(r, ensure_ascii=True), flush=True)
        results.append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ("results.json" if not want else f"results_{'_'.join(want)}.json")).write_text(
        json.dumps(results, indent=1, ensure_ascii=True))


if __name__ == "__main__":
    main()
