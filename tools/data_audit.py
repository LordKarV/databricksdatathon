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
  public      none of the above.
tools/public_exclude.txt lists every non-public file; tools/public_copy.sh leaves them out of the code-only copy.
"""
from __future__ import annotations

import gzip
import re
import subprocess
from collections import Counter, defaultdict
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
    ("public", "everything else: code, docs without record ids, configuration"),
]


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if (ROOT / p).is_file()]


def text_of(path: Path) -> str:
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
    txt = text_of(p) if is_data or ext in CODE_EXT else ""
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
    return "public", ""


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
        ("Known gap: the rules find record ids, sentence ids and coordinates, not facility names written in prose. "
         "A few docs (REPORT.md, model/MODEL_SPEC.md, app_design/, and external/*/README.md for the lists that are "
         "not restricted) name example facilities; read them before option B."),
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
    main()
