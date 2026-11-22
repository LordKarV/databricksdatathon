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
tools/public_exclude.txt lists every non-public file; tools/public_copy.sh leaves them out of the code-only copy.
"""
from __future__ import annotations

import gzip
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
CLAIM = re.compile(r"\b[0-9a-f]{8}:(?:proc|equi|capa|desc|spec|name)\b")
COORDS = re.compile(r"\b[67-9]\d\.\d{4,},[1-3]?\d\.\d{4,}\b")  # lon,lat pairs inside India, as OSRM URLs carry them
RESTRICTED_DIRS = ("external/nabh_accredited/", "external/nmc_colleges/", "external/mohfw_trauma_196/")
DATA_EXT = {".parquet", ".csv", ".tsv", ".json", ".jsonl", ".gz", ".txt", ".xlsx", ".geojson"}
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webm", ".mp4", ".pdf"}
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
WORD = re.compile(r"[a-z0-9]+")
DIGITS = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?((?:\d[\s-]?){9}\d)(?!\d)")


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
            w = tuple(words(n or ""))
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
    # emergency services available ...") identifies nobody, and also matches ordinary prose.
    owners: dict[int, set[str]] = defaultdict(set)
    tab = pq.read_table(V1 / "claims.parquet", columns=["claim_id", "text"])
    for cid, t in zip(tab.column("claim_id").to_pylist(), tab.column("text").to_pylist(), strict=True):
        w = words(t or "")
        fac = (cid or "").split(":", 1)[0]
        for i in range(len(w) - SHINGLE + 1):
            o = owners[hash(tuple(w[i:i + SHINGLE]))]
            if len(o) <= MAX_FACILITIES:
                o.add(fac)
    shingles = {h for h, o in owners.items() if len(o) <= MAX_FACILITIES}
    # Place names and timetables are not facility text ("dadra and nagar haveli and daman and diu", "09 00 13 00").
    place = {"and", "the", "of"}
    for col in ("state", "district"):
        for v in pq.read_table(V1 / "pin_gazetteer.parquet", columns=[col]).column(col).to_pylist():
            place.update(words(v or ""))
    by_first: dict[str, set[int]] = defaultdict(set)
    for n in names:
        by_first[n[0]].add(len(n))
    return {"names": names, "by_first": by_first, "phones": phones, "shingles": shingles, "place": place}


def facility_hits(text: str) -> Counter:
    """How many facility names, phones and claim spans from the dictionary a text contains."""
    d = dictionary()
    w = words(text)
    hits: Counter = Counter()
    for i, x in enumerate(w):
        for n in d["by_first"].get(x, ()):
            if tuple(w[i:i + n]) in d["names"]:
                hits["names"] += 1
                break
    for i in range(len(w) - SHINGLE + 1):
        span = w[i:i + SHINGLE]
        if (hash(tuple(span)) in d["shingles"] and not all(x in d["place"] for x in span)
                and sum(x.isdigit() for x in span) < SHINGLE // 2):
            hits["claim_spans"] += 1
    for m in DIGITS.finditer(text):
        if re.sub(r"\D", "", m.group(1))[-10:] in d["phones"]:
            hits["phones"] += 1
    return hits


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if (ROOT / p).is_file()]


def text_of(path: Path) -> str:
    if path.suffix == ".ipynb":  # the public copy clears outputs (strip_outputs), so only the code is judged
        try:
            cells = json.loads(path.read_text(encoding="utf-8")).get("cells", [])
        except ValueError:
            return path.read_text(encoding="utf-8", errors="ignore")
        return "\n".join("".join(c.get("source", [])) for c in cells)
    if path.suffix == ".parquet":
        t = pq.ParquetFile(path)
        cols = [f.name for f in t.schema_arrow if str(f.type) in ("string", "large_string")]
        if not cols or t.metadata.num_rows == 0:
            return ""
        batch = next(t.iter_batches(batch_size=500, columns=cols))
        return " ".join(str(v) for c in batch.columns for v in c.to_pylist())
    raw = path.read_bytes()[:MAX_READ]
    if path.suffix == ".gz":
        try:
            raw = gzip.decompress(path.read_bytes())[:MAX_READ]
        except OSError:
            return ""
    return raw.decode("utf-8", errors="ignore")


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
    if txt:
        h = facility_hits(txt)
        if h:
            return "facility_text", ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(h.items()))
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
        txt = text_of(p)
        why = [f"{len(set(UUID.findall(txt)))} record ids"] if UUID.search(txt) else []
        why += [f"{v} {k}" for k, v in sorted(facility_hits(txt).items())]
        if why:
            bad.append((p, ", ".join(why)))
    for p, why in bad:
        print(f"FAIL {p.relative_to(root)}: {why}")
    print(f"checked {root}: {len(bad)} files fail")
    return 1 if bad else 0


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
         "script. Option B (code-only public copy) leaves out every file not in the `public` class; the list is "
         "`tools/public_exclude.txt`."),
        "",
        "## The two options (the lead and the human owner decide; nothing here changes repo visibility)",
        "",
        ("- **A. Keep this repo private and invite judges as read-only collaborators.** Everything stays, including "
         "the derived tables and hand-check samples that make every number reproducible. Needs: judges' GitHub "
         "handles (#3), and confirmation that sharing provided-dataset rows with judges is within the Marketplace "
         "consumer terms (judges are participants in the same event)."),
        ("- **B. Publish a clean code-only copy.** `tools/public_copy.sh` builds it into `build/public/` "
         "(git-ignored, local only): every tracked file except those in `tools/public_exclude.txt`, as one fresh "
         "commit with no history (this repo's history still holds the excluded files). The copy has no `derived/`, "
         "so its notebook and app need `derived/v1` rebuilt from the Marketplace table on Databricks first. That "
         "step does not exist yet: `make derived` reads `data/raw/` with paths on the lead's machine. **Waiting for "
         "lead:** the Databricks-side pipeline comes with #11 / #57. Numbers quoted from hand checks stay in the "
         "docs; their samples do not."),
        "",
        ("Facility names, phones and claim sentences are found with a dictionary built from derived/v1 (every "
         "distinctive facility name, every listed phone, every 8-word span of a claim sentence), not by id format. "
         "`public_copy.sh` rescans the built copy with `data_audit.py --check` and fails on any hit. Not covered: "
         "a facility named only by a generic name (\"City Hospital\") or paraphrased."),
        "",
        "## Rules (first match wins)",
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
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        print(f"cleared outputs of {strip_outputs(Path(sys.argv[2]))} notebooks")
        sys.exit(check_copy(Path(sys.argv[2])))
    main()
