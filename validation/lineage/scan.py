"""Static scan of the pipeline scripts for things that break a rebuild on another machine or on Databricks.

Categories (regex, one hit per matching line):
  abs_path      a hard-coded absolute path (/Users/..., /private/..., /tmp/..., ~/...).
  venv_pin      a hard-coded interpreter or venv path (.venv*/bin/python).
  random_unseeded  random / numpy random / DataFrame.sample / shuffle with no seed visible on the line.
  hash_order    iteration over a Python set of strings (order depends on PYTHONHASHSEED per process).
  wallclock     datetime.now / time.time / date.today written into outputs (non-reproducible stamps).
  network       HTTP clients, sockets, curl/wget, thread pools used for fetching.
  warehouse_llm Databricks SQL statement API or ai_query (needs a workspace profile and spends LLM calls).
  shell_portability  zsh-only shebang (absent on Databricks clusters) or an error swallowed with '|| true'.
Pure-comment lines are skipped. Writes out/static_scan.csv and returns the hits.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path("/Users/karthikvattem/projects/datathon")
AREAS = ["cleaning", "pipelines", "kb", "app/facts", "app/packs", "planner", "audit/provenance"]  # audit/provenance: imported by pipelines/source_scoring
EXTS = {".py", ".sh", ".mjs", ".js"}
SKIP_PARTS = {"__pycache__", "node_modules", "out"}
OUT = Path(__file__).resolve().parent / "out"

PATTERNS = {
    "abs_path": re.compile(r"""(["'`=\s(]|^)(/Users/|/private/|/tmp/|/home/|~/)"""),
    "venv_pin": re.compile(r"\.venv[\w-]*/bin/python"),
    "random_unseeded": re.compile(
        r"(\brandom\.(random|choice|choices|shuffle|sample|randint|uniform|gauss)\(|np\.random\.(rand|randn|choice|shuffle|"
        r"permutation|randint|random|normal|uniform|seed)\(|default_rng\(\s*\)|Random\(\s*\)|\.sample\((?!.*random_state))"),
    # set iteration, or a sort of a set by a key that can tie (ties keep set order)
    "hash_order": re.compile(r"for \w+(, \w+)* in (set\(|\{[^}:]*\}|[\w.]+ \| [\w.(]+)|sorted\(\{.*\}, key="),
    "wallclock": re.compile(r"datetime\.(now|utcnow|today)\(|date\.today\(|time\.time\(\)|strftime\("),
    "network": re.compile(
        r"\b(import requests|from requests|requests\.(get|post|Session)|urllib\.request|urlopen\(|httpx|aiohttp|"
        r"http\.client|socket\.|playwright|selenium|curl |wget |sql\.sh|databricks |WorkspaceClient|statement_execution|"
        r"anthropic|openai|overpass|query\.wikidata|api\.github|ThreadPoolExecutor)"),
    "warehouse_llm": re.compile(r"\"databricks\", \"api\"|ai_query\(|sql/statements"),
    "shell_portability": re.compile(r"^#!/bin/zsh|\|\| true"),
}


SEEDED = re.compile(r"random\.seed\(\s*\w|default_rng\(\s*\w|Random\(\s*\w")


def files() -> list[Path]:
    out = []
    for a in AREAS:
        for p in sorted((ROOT / a).rglob("*")):
            if p.is_file() and p.suffix in EXTS and not SKIP_PARTS & set(p.relative_to(ROOT).parts[:-1]):
                out.append(p)
    return out


def is_comment(line: str, suffix: str) -> bool:
    s = line.strip()
    return s.startswith("#") or (suffix in {".js", ".mjs"} and s.startswith("//"))


def scan() -> list[dict]:
    hits = []
    for p in files():
        rel = str(p.relative_to(ROOT))
        in_doc, seeded = False, False
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if p.suffix == ".py" and line.strip().count('"""') == 1:
                in_doc = not in_doc
                continue
            if i == 1 and line.startswith("#!/bin/zsh"):
                hits.append({"file": rel, "line": 1, "category": "shell_portability", "snippet": line.strip()})
            if in_doc or is_comment(line, p.suffix):
                continue
            if SEEDED.search(line):
                seeded = True
            for cat, rx in PATTERNS.items():
                if cat == "random_unseeded" and seeded:
                    continue  # a seed was set earlier in this file (random.seed(n), default_rng(n), Random(n))
                if rx.search(line):
                    hits.append({"file": rel, "line": i, "category": cat, "snippet": line.strip()[:160]})
    OUT.mkdir(exist_ok=True)
    with open(OUT / "static_scan.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "line", "category", "snippet"])
        w.writeheader()
        w.writerows(hits)
    return hits


if __name__ == "__main__":
    from collections import Counter
    h = scan()
    print(len(files()), "files;", Counter(x["category"] for x in h))
    print(Counter((x["file"].split("/")[0] + "/" + x["file"].split("/")[1], x["category"]) for x in h))
