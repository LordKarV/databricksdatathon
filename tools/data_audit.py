"""Licence and data audit of every tracked file (issue #58). Writes DATA_AUDIT.md and tools/public_exclude.txt.

Run from the repo root (any Python with pandas and pyarrow):
    .venv-app/bin/python tools/data_audit.py

Each tracked file is put in one class by the first rule that matches. Every rule is printed in DATA_AUDIT.md, so
a reviewer can check the classes instead of trusting them:
  provided    rows or text from the provided facility dataset (Marketplace consumer terms): record ids
              (unique_id UUIDs), sentence ids (<8 hex>:proc|equi|capa|desc|spec), or facility coordinates;
  restricted  facility-level facts from the NABH, NMC or MoHFW trauma lists (per-facility citation only);
  third_party other external data committed as files (each source's licence is in DATASETS.md);
  image       screenshots and recordings of the app, which show provided facility names;
  review      prose or code that mentions record ids: usually a few quoted examples, to be read by a human;
  facility_text  any other text file holding a facility name, phone number or claim sentence from the provided data
              (a dictionary built from derived/v1: the public-copy rule on #82 is "no facility-level row, quote, name,
              phone or restricted-list fact; only code, docs and aggregate numbers");
  public      none of the above.
tools/public_exclude.txt lists every non-public file (it fed tools/public_copy.sh, superseded: the repo is public).

The repo check (#82, #83; the repo itself is public since the lead's decision on #2):
    .venv-app/bin/python tools/data_audit.py --repo origin/dev
reads every file tracked at a git ref (git ls-tree / cat-file; nothing is checked out or written), runs the same
detectors, notebook outputs included, and puts each file under REPO_RULES. It prints paths, rule names and counts
only, never a matched string. Exit 1 when any file falls under a rule that needs a human decision.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
CLAIM = re.compile(r"\b[0-9a-f]{8}:(?:proc|equi|capa|desc|spec|name)\b")
COORDS = re.compile(r"\b[67-9]\d\.\d{4,},[1-3]?\d\.\d{4,}\b")  # lon,lat pairs inside India, as OSRM URLs carry them
RESTRICTED_DIRS = ("external/nabh_accredited/", "external/nmc_colleges/", "external/mohfw_trauma_196/")
DATA_EXT = {".parquet", ".csv", ".tsv", ".json", ".jsonl", ".gz", ".txt", ".xlsx", ".geojson"}
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webm", ".mp4", ".pdf"}
BINARY_EXT = {".xlsx", ".sqlite", ".tif", ".tiff", ".zip", ".pbf", ".npy", ".npz", ".pkl", ".joblib"}
CODE_EXT = {".py", ".js", ".sh", ".sql", ".html", ".css", ".md", ".yaml", ".yml", ".toml", ".webmanifest", ".ipynb"}
MAX_READ = 8_000_000
_FAC = r"\b(?:Hospitals?|College|Centre|Center|Institute|Medical|TCF|Scans)\b"
# a facility named in a table row, a numbered list, or a quote; or an NABH certificate number
NAMES_ROW = re.compile(rf"^(?:\||\d+[ .]).*{_FAC}|\"[^\"\n]*{_FAC}[^\"\n]*\"|\bH-\d{{4}}-\d{{4}}\b", re.MULTILINE)

RULES = [
    ("provided", "a data file holding provided record ids, sentence ids or facility coordinates"),
    ("restricted", ("any data file in external/nabh_accredited, external/nmc_colleges or external/mohfw_trauma_196, "
                    "and their READMEs when they name a listed facility (table row, numbered list, quote, "
                    "certificate no.)")),
    ("third_party", "any other data file under external/ (each source's licence: research/DATASETS.md)"),
    ("image", "screenshots or recordings (they show provided facility names)"),
    ("review", "prose or code that mentions a record id or sentence id (usually a quoted example)"),
    ("facility_text", ("any other file holding a facility name, phone number or claim sentence from the provided "
                       "data (dictionary from derived/v1; counts only are printed here)")),
    ("public", "everything else: code, docs without record ids, configuration"),
]


# ---------- the facility dictionary (#82, B1) ----------
V1 = ROOT / "derived" / "v1"
SHINGLE = 8  # a claim sentence is matched on any 8 consecutive words
MAX_FACILITIES = 3  # ... that appear in the claims of at most this many facilities
GENERIC = {"hospital", "hospitals", "clinic", "clinics", "nursing", "home", "medical", "college", "centre", "center",
           "care", "multi", "super", "speciality", "specialty", "multispeciality", "multispecialty", "health",
           "institute", "research", "and", "the", "of", "district", "government", "govt", "civil", "general",
           "memorial", "trust", "private", "limited", "ltd", "pvt", "india", "maternity", "children", "child",
           "eye", "dental", "diagnostic", "diagnostics", "heart", "cancer", "city", "new", "sub", "divisional",
           "community", "primary", "phc", "chc", "dr", "doctor", "doctors", "clinik", "polyclinic", "lab", "labs",
           "scan", "scans", "imaging", "path", "pathology", "foundation", "society", "mission", "unit", "blood", "bank",
           "sadar", "rural", "taluk", "taluka", "dispensary", "studio", "kidney", "veterinary", "sciences", "science",
           "referral", "upgraded", "area", "esi", "railway", "police", "army", "military", "cantonment", "urban",
           "block", "subdivisional", "dialysis", "trauma", "burn", "burns", "orthopaedic", "orthopedic", "women",
           "mother", "skin", "neuro", "ortho", "gynae", "surgical", "medicine", "medicare", "hospitality"}
WORD = re.compile(r"[a-z0-9]+|[\u0900-\u0DFF]+")  # Latin words and Indic-script words, Devanagari to Sinhala (#83 7)
HEX8 = re.compile(r"\b[0-9a-f]{8}\b")  # a record cited by its 8-character id prefix (#83 review 4)
DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b")
EMAIL = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+\b")
SECRET = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")  # Google API keys, found in saved third-party pages (H8)
WORDLIST = Path("/usr/share/dict/words")
ALLOW = ROOT / "tools" / "public_allow_words.txt"
TOKEN_MAX_FACILITIES = 2  # a single name word identifies a facility when at most this many names carry it ...
TOKEN_COMMON_CLAIMS = 5  # ... and the claims of at most this many facilities use it
SHORT_CLAIM = (4, SHINGLE - 1)  # claims too short for the 8-word span rule, matched as whole texts ...
RARE_WORD = 20
SHORT_CLAIMS_PER_FILE = 5  # ... and a file fails when it holds this many distinct ones (a few are coincidence)
PUBLIC_HOST = re.compile(r"(^|\.)(gov|nic|edu|ac|res|mil)(\.[a-z]{2})?$|\.(gov|nic|edu|ac)\.in$"
                         r"|(^|\.)(tinyurl\.com|bit\.ly|google\.com|facebook\.com|wikipedia\.org|rediff\.com|linktr\.ee|webs\.com"
                         r"|blogspot\.com|wordpress\.com|wixsite\.com|business\.site)$")
MAIL_HOSTS = {"gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "rediffmail.com", "outlook.com",
              "ymail.com", "live.com", "icloud.com", "aol.com", "rocketmail.com", "googlemail.com"}
DIGITS = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?((?:\d[\s-]?){9}\d)(?!\d)")
PREFIXES_MANY = 10  # record ids (full or 8-hex prefix) count only when a file cites this many (#83 review 4)

# ---------- restricted lists (#83 review 6) ----------
# The NABH, NMC and MoHFW trauma lists (and e-RaktKosh, same terms in research/DATASETS.md) are for per-facility
# citation only. Their raw files are not tracked; matched per-facility facts with a citation live in derived/v2
# (facility_attributes, witnesses) and the list's own folder holds its code. A list entry outside those places is
# found by its NABH accreditation number (any entry, matched or not: the format is the list's own), by the list
# entry ids our parsers give (nmc:college:N, tcf:N, erk:N), or by a list entry's own name when that name is not a
# provided record name (MoHFW trauma and e-RaktKosh names, from the witnesses' quotes).
LIST_HOMES = ("external/nabh_accredited/", "external/nmc_colleges/", "external/mohfw_trauma_196/",
              "external/eraktkosh_blood_centres/", "derived/v2/")
NABH_ACC = re.compile(
    r"(?<![A-Za-z0-9-])(?:(?:PESHCO|SHCO|PEH|ECO|EAH|ELCP|ELDC|EAC|ECE|MIS|MLP|AH|BB|CD|CH|PC|ST|H|D|N|E|C"
    r"|DHC?-[SGP]|EC-CT|Manyata)-\d{4}-\d{4,5}|(?:HOS|EYE|DEN|LAB)/\d{4}/[CE]\d{3,5})(?!\d)")
LIST_ID = re.compile(r"\b(?:nmc:college|tcf|erk):\d+\b")
LIST_MANY = 20  # a file outside LIST_HOMES with this many list entries is a copy of list rows (validation/ uses 20)
BULK_FACILITIES = 50  # a file naming or keying this many facilities is a facility-level dump, not a citation
CLAIMS_MANY = 20  # a file holding this many distinct exact claim texts, any length from 4 words (#83 review 2)
REPO_RULES = [  # (rule, needs a human decision, what it means); first match listed first
    ("secret", True, "an API key"),
    ("restricted_copy", True, f"{LIST_MANY}+ restricted-list entries outside {', '.join(LIST_HOMES)}"),
    ("bulk_rows", True, (f"{BULK_FACILITIES}+ distinct facilities by record id, name, phone, email or domain "
                         "(the largest of these counts)")),
    ("claim_copy", True, f"{CLAIMS_MANY}+ distinct claim texts from the provided data"),
    ("mentions", False, "fewer hits: per-facility facts, to be read with their citation"),
]


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


@cache
def dictionary() -> dict:
    """names: word tuples of every distinctive facility name; phones: last 10 digits; shingles: 8-word claim spans.

    A name counts when it has 2+ words and a word of 4+ letters that is not generic ("City Hospital" alone is not a
    facility identity; a name with a distinctive word is). Built in memory only, never written out.
    """
    names: set[tuple[str, ...]] = set()
    for f, cols in (("facility_location.parquet", ["name"]), ("record_trust.parquet", ["name"])):
        for n in pq.read_table(V1 / f, columns=cols).column("name").to_pylist():
            # the full name, and its head before a bracket, dash or comma ("X Hospitals (A Unit Of Y) - Road, Town"
            # is usually written "X Hospitals")
            for part in {n or "", re.split(r"\s*[(,|]|\s+-\s+", n or "", maxsplit=1)[0]}:
                w = tuple(words(part))
                if len(w) >= 2 and any(len(x) >= 4 and not x.isdigit() and x not in GENERIC for x in w):
                    names.add(w)
    phones = set()
    listed = pq.read_table(V1 / "record_trust.parquet", columns=["display_phones"]).column("display_phones")
    for ps in listed.to_pylist():
        for ph in ps or []:
            d = re.sub(r"\D", "", str(ph))[-10:]
            if len(d) == 10 and len(set(d)) > 2:
                phones.add(d)
    # Only spans specific to at most MAX_FACILITIES facilities: boilerplate shared by many listings ("24 hours
    # emergency services available ...") identifies nobody, and also matches ordinary prose. Each span maps to the
    # first claim that holds it, so a file's hits can be counted as distinct claims.
    owners: dict[int, set[str]] = defaultdict(set)
    first: dict[int, int] = {}
    tab = pq.read_table(V1 / "claims.parquet", columns=["claim_id", "text"])
    for k, (cid, t) in enumerate(zip(tab.column("claim_id").to_pylist(), tab.column("text").to_pylist(), strict=True)):
        w = words(t or "")
        fac = (cid or "").split(":", 1)[0]
        for i in range(len(w) - SHINGLE + 1):
            h = hash(tuple(w[i:i + SHINGLE]))
            o = owners[h]
            first.setdefault(h, k)
            if len(o) <= MAX_FACILITIES:
                o.add(fac)
    shingles = {h: first[h] for h, o in owners.items() if len(o) <= MAX_FACILITIES}
    # Place names and timetables are not facility text ("dadra and nagar haveli and daman and diu", "09 00 13 00").
    place = {"and", "the", "of"}
    for col in ("state", "district"):
        for v in pq.read_table(V1 / "pin_gazetteer.parquet", columns=[col]).column(col).to_pylist():
            place.update(words(v or ""))
    for v in pq.read_table(V1 / "facility_location.parquet", columns=["address_city"]).column(0).to_pylist():
        place.update(words(v or ""))
    towns = {x for v in pq.read_table(V1 / "place_gazetteer.parquet", columns=["name"]).column(0).to_pylist()
             for x in words(v or "")}  # towns and villages: kept apart, used only to clear single name words
    by_first: dict[str, set[int]] = defaultdict(set)
    for n in names:
        by_first[n[0]].add(len(n))
    return {"names": names, "by_first": by_first, "phones": phones, "shingles": shingles, "place": place,
            "short": short_claims(), "tokens": name_tokens(place | towns) - allowed_words(), **contacts(),
            "list_names": (ln := list_names()), "list_first": {t[0] for t in ln}, "provided_acc": provided_acc()}


def provided_acc() -> set[str]:
    """NABH numbers the provided records themselves quote ("NABH accredited, H-2019-0123"): provided text, not a
    copy of the list, so they never count as list entries (validation/privacy_licence does the same)."""
    tab = pq.read_table(V1 / "claims.parquet", columns=["text"]).column(0).to_pylist()
    return set(NABH_ACC.findall(" ".join(t for t in tab if t)))


def list_names() -> set[tuple[str, ...]]:
    """Names of MoHFW trauma and e-RaktKosh list entries (the witnesses quote them) that are 3+ words and not also a
    provided record name: those can only have come from the list. NABH and NMC entries are found by number."""
    v2 = ROOT / "derived" / "v2" / "witnesses.parquet"
    if not v2.exists():
        return set()
    provided = {tuple(words(n or "")) for f in ("facility_location.parquet", "record_trust.parquet")
                for n in pq.read_table(V1 / f, columns=["name"]).column(0).to_pylist()}
    q = pq.read_table(v2, columns=["quote"], filters=[("source_key", "in", ["mohfw_tcf", "eraktkosh"])])
    return {w for w in (tuple(words(t or "")) for t in q.column(0).to_pylist()) if len(w) >= 3} - provided


@cache
def word_facilities() -> Counter:
    """For each word, how many facilities' claims use it."""
    seen: set[tuple[str, str]] = set()
    tab = pq.read_table(V1 / "claims.parquet", columns=["claim_id", "text"])
    for cid, t in zip(tab.column("claim_id").to_pylist(), tab.column("text").to_pylist(), strict=True):
        fac = (cid or "").split(":", 1)[0]
        seen.update((fac, x) for x in words(t or ""))
    return Counter(x for _, x in seen)


def short_claims() -> set[int]:
    """Whole claim texts of 4 to 7 words specific to at most MAX_FACILITIES facilities (#83 review 2). A text made
    only of common vocabulary ("head and neck cancer", "blood centre blood bank") identifies nobody: it needs a word
    the claims of at most RARE_WORD facilities use."""
    common = word_facilities()
    owners: dict[int, set[str]] = defaultdict(set)
    tab = pq.read_table(V1 / "claims.parquet", columns=["claim_id", "text"])
    for cid, t in zip(tab.column("claim_id").to_pylist(), tab.column("text").to_pylist(), strict=True):
        w = words(t or "")
        if SHORT_CLAIM[0] <= len(w) <= SHORT_CLAIM[1] and min(common[x] for x in w) <= RARE_WORD:
            o = owners[hash(tuple(w))]
            if len(o) <= MAX_FACILITIES:
                o.add((cid or "").split(":", 1)[0])
    return {h for h, o in owners.items() if len(o) <= MAX_FACILITIES}


def name_tokens(place: set[str]) -> set[str]:
    """Single distinctive name words (a brand or coined name) of 5+ letters: in at most
    TOKEN_MAX_FACILITIES facility names, not an English word, not generic, not a place (#83 review 1)."""
    if not WORDLIST.exists():
        raise SystemExit(f"{WORDLIST} is missing: the single-name-word rule needs an English word list")
    english = {w.strip().lower() for w in WORDLIST.read_text(errors="ignore").splitlines()}
    count: Counter = Counter()
    for n in set(pq.read_table(V1 / "facility_location.parquet", columns=["name"]).column(0).to_pylist()):
        count.update({x for x in words(n or "") if len(x) >= 5 and x.isascii() and x.isalpha()})
    # Words the claims of many facilities use are vocabulary, not identity: specialties ("pulmonology"), plurals the
    # word list lacks ("specialties"), surnames in doctor bios, towns. Only rarer words stay.
    common = word_facilities()

    def english_word(x: str) -> bool:
        stems = {x, x[:-1], x[:-2], x[:-3] + "y", x[:-3], x[:-2] + "e"} if len(x) > 5 else {x}
        return bool(stems & english)
    return {x for x, c in count.items() if c <= TOKEN_MAX_FACILITIES and common[x] <= TOKEN_COMMON_CLAIMS
            and not english_word(x) and x not in GENERIC and x not in place}


def allowed_words() -> set[str]:
    """Single name words a person read in context and cleared (a place, a person, an ordinary word); see the file."""
    return {ln.split("#", 1)[0].strip() for ln in ALLOW.read_text().splitlines()} - {""} if ALLOW.exists() else set()


def contacts() -> dict[str, set[str]]:
    """Record id prefixes, own website domains and email addresses (#83 review 3, 4). A domain counts when it is
    the record's own site or email host and at most MAX_FACILITIES records share it (not a mail provider)."""
    ids = pq.read_table(V1 / "facility_location.parquet", columns=["unique_id"]).column(0).to_pylist()
    rt = pq.read_table(V1 / "record_trust.parquet", columns=["website_domain", "website_class", "emails_clean"])
    dom: Counter = Counter()
    emails: set[str] = set()
    for d, cls, es in zip(*(rt.column(c).to_pylist() for c in rt.column_names), strict=True):
        hosts = {d.lower().removeprefix("www.")} if d and cls == "own" else set()
        for e in es or []:
            e = str(e).lower().strip()
            emails.add(e)
            hosts.add(e.rsplit("@", 1)[-1])
        dom.update(hosts - MAIL_HOSTS)
    # Public bodies and generic hosts identify no private record ("gov.in", "aiims.edu", "tinyurl.com").
    keep = {d for d, c in dom.items() if c <= MAX_FACILITIES and not PUBLIC_HOST.search(d)}
    return {"prefixes": {str(u)[:8] for u in ids if u}, "domains": keep,
            "emails": emails}


def facility_hits(text: str) -> Counter:
    """How many facility names, name words, phones, claim texts, ids, domains and emails a text contains."""
    """Every count is of distinct items: names, phones, claims, record ids, list entries."""
    d = dictionary()
    w = words(text)
    hits: Counter = Counter()
    hits["name_words"] = len({x for x in w if x in d["tokens"]})
    short = {hash(tuple(w[i:i + n])) for n in range(SHORT_CLAIM[0], SHORT_CLAIM[1] + 1)
             for i in range(len(w) - n + 1)} & d["short"]
    if len(short) >= SHORT_CLAIMS_PER_FILE:
        hits["short_claims"] = len(short)
    low = text.lower()
    # A full record id or its 8-hex prefix; a few are citations, many are a keyed table.
    ids = {m for m in HEX8.findall(low) if m in d["prefixes"]} | {u[:8] for u in UUID.findall(low)
                                                                    if u[:8] in d["prefixes"]}
    if len(ids) >= PREFIXES_MANY:
        hits["record_ids"] = len(ids)
    hits["domains"] = len({m.removeprefix("www.") for m in DOMAIN.findall(low)} & d["domains"])
    hits["emails"] = len(set(EMAIL.findall(low)) & d["emails"])
    names: set[tuple[str, ...]] = set()
    lists: set[tuple[str, ...]] = set()
    for i, x in enumerate(w):
        for n in d["by_first"].get(x, ()):
            if tuple(w[i:i + n]) in d["names"]:
                names.add(tuple(w[i:i + n]))
                break
        if x in d["list_first"]:
            lists.update(t for n in range(3, 13) if (t := tuple(w[i:i + n])) in d["list_names"])
    hits["names"] = len(names)
    claims = set()
    for i in range(len(w) - SHINGLE + 1):
        span = w[i:i + SHINGLE]
        k = d["shingles"].get(hash(tuple(span)))
        if k is not None and not all(x in d["place"] for x in span) and sum(x.isdigit() for x in span) < SHINGLE // 2:
            claims.add(k)
    hits["claim_spans"] = len(claims)  # distinct claims of 8+ words, matched by any 8-word span
    phones = {re.sub(r"\D", "", m.group(1))[-10:] for m in DIGITS.finditer(text)}
    hits["phones"] = len(phones & d["phones"])
    acc = set(NABH_ACC.findall(text)) - d["provided_acc"]
    hits["list_entries"] = len(acc | set(LIST_ID.findall(low))) + len(lists)
    return +hits  # drop zero counts


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if (ROOT / p).is_file()]


def text_of(path: Path) -> str:
    """A tracked file's text as the public-copy check judged it (notebook outputs left out: the copy cleared them)."""
    return text_from(path.name, path.read_bytes(), outputs=False)


def text_from(name: str, raw: bytes, outputs: bool = True) -> str:
    """The searchable text of a file's bytes: notebook sources (and saved outputs), parquet string cells, gz text."""
    suffix = Path(name).suffix.lower()
    if suffix == ".ipynb":
        try:
            cells = json.loads(raw).get("cells", [])
        except ValueError:
            return raw[:MAX_READ].decode("utf-8", errors="ignore")
        return "\n".join(_cell_text(c, outputs) for c in cells)
    if suffix == ".parquet":
        return _parquet_text(raw)
    if suffix == ".gz":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return ""
    return raw[:MAX_READ].decode("utf-8", errors="ignore")


def _cell_text(cell: dict, outputs: bool) -> str:
    def joined(v: object) -> str:
        return "".join(v) if isinstance(v, list) else str(v or "")
    parts = [joined(cell.get("source"))]
    for o in cell.get("outputs", []) if outputs else []:
        parts.append(joined(o.get("text")))
        parts += [joined(v) for mime, v in (o.get("data") or {}).items()
                  if mime.startswith("text/") or mime == "application/json"]
    return "\n".join(parts)


def _parquet_text(raw: bytes) -> str:
    """String and list-of-string cells, row batch by row batch, up to MAX_READ characters."""
    try:
        f = pq.ParquetFile(pa.BufferReader(raw))
    except (pa.ArrowException, OSError):
        return ""
    cols = [x.name for x in f.schema_arrow if "string" in str(x.type)]
    out: list[str] = []
    size = 0
    for batch in f.iter_batches(batch_size=2000, columns=cols) if cols else ():
        for c in batch.columns:
            for v in c.to_pylist():
                s = " ".join(map(str, v)) if isinstance(v, list) else str(v)
                out.append(s)
                size += len(s) + 1
        if size >= MAX_READ:
            break
    return " ".join(out)


def detect(txt: str) -> Counter:
    """Every detector, shared by the classifier, the rescan of the built copy and the repo check (#83 review 5)."""
    if not txt:
        return Counter()
    hits = facility_hits(txt)
    hits["uuids"] = len(set(UUID.findall(txt)))
    hits["sentence_ids"] = len(set(CLAIM.findall(txt)))
    hits["coordinates"] = len(set(COORDS.findall(txt)))
    hits["api_keys"] = len(set(SECRET.findall(txt)))
    return +hits


def findings(txt: str) -> list[str]:
    return [f"{v} {k.replace('_', ' ')}" for k, v in sorted(detect(txt).items())]


def classify(rel: str) -> tuple[str, str]:
    p = ROOT / rel
    ext = p.suffix.lower()
    is_data = ext in DATA_EXT
    if ext in MEDIA_EXT:
        return "image", "media file"
    txt = text_of(p)  # every non-media file is read: .log, .svg and other text carry names too
    ids, claims = len(set(UUID.findall(txt))), len(set(CLAIM.findall(txt)))
    if rel.startswith(RESTRICTED_DIRS):
        if is_data or ids or claims:
            return "restricted", f"{ids} record ids" if ids else "list data"
        if ext == ".md" and NAMES_ROW.search(txt):
            return "restricted", "names listed facilities (hand check)"
    if is_data:
        if ids or claims:
            return "provided", ", ".join(x for x in (f"{ids} record ids" if ids else "",
                                                       f"{claims} sentence ids" if claims else "") if x)
        if COORDS.search(txt):
            return "provided", "facility coordinates"
        if rel.startswith("external/"):
            return "third_party", "external data"
    if ids or claims:
        return "review", ", ".join(x for x in (f"{ids} record ids" if ids else "",
                                               f"{claims} sentence ids" if claims else "") if x)
    if "/sources/" in rel and ext in {".html", ".htm"}:
        return "third_party", "saved third-party page"
    why = findings(txt)
    if why:
        return "facility_text", ", ".join(why)
    return "public", ""


def strip_outputs(root: Path) -> int:
    """Clear every notebook's outputs in a built copy: they print facility rows. Returns how many changed."""
    n = 0
    for p in root.rglob("*.ipynb"):
        nb = json.loads(p.read_text(encoding="utf-8"))
        for c in nb.get("cells", []):
            if c.get("cell_type") == "code":
                c["outputs"], c["execution_count"] = [], None
        p.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        n += 1
    return n


def check_copy(root: Path) -> int:
    """Rescan a built public copy: every text file must be free of record ids and dictionary hits. Exit 1 if not."""
    bad = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or ".git" in p.parts or p.suffix.lower() in MEDIA_EXT:
            if p.is_file() and p.suffix.lower() in MEDIA_EXT and ".git" not in p.parts:
                bad.append((p, "media file"))
            continue
        why = findings(text_of(p))
        if why:
            bad.append((p, ", ".join(why)))
    for p, why in bad:
        print(f"FAIL {p.relative_to(root)}: {why}")
    print(f"checked {root}: {len(bad)} files fail")
    return 1 if bad else 0


def git_blobs(ref: str) -> Iterator[tuple[str, bytes]]:
    """(path, bytes) of every file tracked at a git ref, read with one git cat-file process; nothing is written."""
    ls = subprocess.run(["git", "ls-tree", "-r", "-z", ref], cwd=ROOT, capture_output=True, check=True).stdout
    entries = []
    for rec in filter(None, ls.split(b"\0")):
        meta, path = rec.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind == b"blob" and mode != b"120000":  # skip symlinks and submodules
            entries.append((path.decode(), sha))
    with subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE) as git:
        assert git.stdin and git.stdout
        for path, sha in entries:
            git.stdin.write(sha + b"\n")
            git.stdin.flush()
            size = int(git.stdout.readline().split()[2])
            data = git.stdout.read(size)
            git.stdout.read(1)  # the newline after each object
            yield path, data
        git.stdin.close()


def repo_rules(rel: str, hits: Counter) -> list[str]:
    """Every REPO_RULES rule a file's counts fall under ("mentions" only when no other applies)."""
    out = ["secret"] if hits["api_keys"] else []
    out += ["restricted_copy"] if hits["list_entries"] >= LIST_MANY and not rel.startswith(LIST_HOMES) else []
    if max(hits[k] for k in ("record_ids", "names", "phones", "emails", "domains")) >= BULK_FACILITIES:
        out.append("bulk_rows")
    out += ["claim_copy"] if hits["claim_spans"] + hits["short_claims"] >= CLAIMS_MANY else []
    quiet = {"uuids"}  # any UUID (also Databricks and job ids); real record ids are counted as record_ids
    return out or (["mentions"] if set(hits) - quiet else [])


def scan_repo(ref: str) -> list[tuple[str, list[str], Counter]]:
    """(path, rules, counts) for every file tracked at ref with a hit. Media and other binary files are not read."""
    out = []
    for rel, raw in git_blobs(ref):
        if Path(rel).suffix.lower() in MEDIA_EXT | BINARY_EXT:
            continue
        hits = detect(text_from(rel, raw))
        rules = repo_rules(rel, hits)
        if rules:
            out.append((rel, rules, hits))
    return out


def report_repo(ref: str, verbose: bool) -> int:
    """Print the repo check: per rule, the file count; per file needing a decision, its counts (never strings)."""
    sha = subprocess.run(["git", "rev-parse", "--short", ref], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout.strip()
    rows = scan_repo(ref)
    by = Counter(rule for r in rows for rule in r[1])
    print(f"repo check of {ref} ({sha}): {len(rows)} files with a hit")
    for rule, decide, what in REPO_RULES:
        print(f"  {rule:<16} {by.get(rule, 0):>5}  {'DECIDE' if decide else 'read  '}  {what}")
    decide_rules = {r for r, d, _ in REPO_RULES if d}
    for rel, rules, hits in sorted(rows, key=lambda r: (r[1], r[0])):
        if decide_rules & set(rules) or verbose:
            counts = ", ".join(f"{v} {k}" for k, v in sorted(hits.items()))
            print(f"{'+'.join(rules)} {rel}: {counts}")
    if not verbose and by.get("mentions"):
        dirs = Counter(str(Path(r[0]).parent) for r in rows if r[1] == ["mentions"])
        print("mentions by folder:", ", ".join(f"{d}/ {n}" for d, n in dirs.most_common()))
    return 1 if any(by.get(r) for r in decide_rules) else 0


def repo_section(ref: str = "HEAD") -> list[str]:
    """DATA_AUDIT.md lines for the repo check: files per rule, then files needing a decision by folder."""
    rows = scan_repo(ref)
    by = Counter(rule for r in rows for rule in r[1])
    out = [f"## Repo check at {ref}", "", "| rule | files | decision | meaning |", "| --- | --- | --- | --- |"]
    out += [f"| `{k}` | {by.get(k, 0):,} | {'human decides' if d else 'read with its citation'} | {w} |"
            for k, d, w in REPO_RULES]
    out += ["", "Files under a rule that needs a decision, by folder (counts only; nothing is deleted or rewritten):",
            "", "| folder | files | rules |", "| --- | --- | --- |"]
    decide = {k for k, d, _ in REPO_RULES if d}
    dirs: dict[str, Counter] = defaultdict(Counter)
    for rel, rules, _ in rows:
        if decide & set(rules):
            dirs[str(Path(rel).parent)].update(r for r in rules if r in decide)
    for d, c in sorted(dirs.items()):
        out.append(f"| `{d}/` | {sum(1 for r in rows if str(Path(r[0]).parent) == d and decide & set(r[1]))} | "
                   + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) + " |")
    return out + [""]


def main() -> None:
    files = tracked()
    rows = [(rel, *classify(rel), (ROOT / rel).stat().st_size) for rel in files]
    by = defaultdict(list)
    for r in rows:
        by[r[1]].append(r)
    counts = Counter(r[1] for r in rows)
    def mb(rs: list) -> float:
        return sum(r[3] for r in rs) / 1e6

    lines = [
        "# Data and licence audit",
        "",
        (f"Generated by `tools/data_audit.py` from the {len(files):,} tracked files. Do not edit by hand; rerun the "
         "script."),
        "",
        "## Status: the repo itself is public",
        "",
        ("The lead made this repo public (#2), which replaced the code-only copy that `tools/public_copy.sh` built "
         "(kept, superseded). The rule on #82 now applies to the repo itself: no whole restricted lists, per-facility "
         "facts only with citations, no personal or patient data, no raw dataset dumps. The repo check "
         "(`data_audit.py --repo REF`) reads every file tracked at a git ref, notebook outputs included, and sorts "
         "files with a hit under the rules below; its result at HEAD is the next section. The classes after it are "
         "the earlier public-copy classification, kept because the exclude list still documents what a code-only "
         "copy would leave out."),
        "",
        ("Facility names, phones, claim texts, record ids, own website domains, emails and restricted-list entries "
         "are found with a dictionary built from derived/v1 and derived/v2, not by id format. Not covered: a "
         "facility named only by a generic name (\"City Hospital\") or paraphrased, and list entries that matched "
         "no provided record and carry no accreditation number (the raw list files are not in the repo)."),
        "",
        *repo_section(),
        "## Public-copy classes (superseded; first match wins)",
        "",
        *[f"- `{k}`: {v}" for k, v in RULES],
        "",
        "## Summary",
        "",
        "| class | files | MB |",
        "| --- | --- | --- |",
        *[f"| {k} | {counts.get(k, 0):,} | {mb(by[k]):.1f} |" for k, _ in RULES],
        "",
    ]
    for k, _ in RULES[:-1]:
        if not by[k]:
            continue
        lines += [f"## {k}", ""]
        dirs = defaultdict(list)
        for r in sorted(by[k]):
            dirs[str(Path(r[0]).parent)].append(r)
        lines += ["| folder or file | files | MB | why |", "| --- | --- | --- | --- |"]
        for d, rs in sorted(dirs.items()):
            if len(rs) > 5:
                why = Counter(r[2].split(" ", 1)[-1] for r in rs).most_common(1)[0][0]
                lines.append(f"| `{d}/` | {len(rs)} | {mb(rs):.1f} | {why} |")
            else:
                lines += [f"| `{r[0]}` | 1 | {r[3] / 1e6:.2f} | {r[2]} |" for r in rs]
        lines.append("")
    (ROOT / "DATA_AUDIT.md").write_text("\n".join(lines) + "\n")
    excl = sorted(r[0] for r in rows if r[1] != "public")
    (ROOT / "tools" / "public_exclude.txt").write_text(
        "# Files left out of the code-only public copy (generated by tools/data_audit.py; do not edit).\n"
        + "\n".join(excl) + "\n")
    print("  ".join(f"{k} {counts.get(k, 0)}" for k, _ in RULES), f"| excluded {len(excl)} files")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", metavar="REF", help="check every file tracked at this git ref (e.g. HEAD, origin/dev)")
    ap.add_argument("--check", metavar="DIR", help="rescan a built public copy (superseded; see public_copy.sh)")
    ap.add_argument("-v", "--verbose", action="store_true", help="with --repo, list every file with a hit")
    a = ap.parse_args()
    if a.repo:
        sys.exit(report_repo(a.repo, a.verbose))
    if a.check:
        print(f"cleared outputs of {strip_outputs(Path(a.check))} notebooks")
        sys.exit(check_copy(Path(a.check)))
    main()
