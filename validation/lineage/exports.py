"""Rebuild the app exports (planner/out, app/facts/out, app/packs/out) into a scratch directory and diff.

Each builder's module-level output path (OUT, and HERE for the packs size tables) is pointed at a temp dir
before main() runs, so nothing under the project is written. Inputs are the live derived/v1 and kb files,
exactly what the real builders read. Order matters: facts reads planner/out/planner_v1.json.gz (the real one).
Usage: .venv/bin/python -B exports.py   (prints and writes out/exports_diff.json)
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))


def load_gz(p: Path) -> dict:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def first_diff(a, b, path: str = "") -> str | None:
    """Path of the first differing element (dict keys, list items), None when equal."""
    if type(a) is not type(b):
        return f"{path}: type {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        if set(a) != set(b):
            return f"{path}: keys {sorted(set(a) ^ set(b))[:5]}"
        for k in a:
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: len {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {str(a)[:60]!r} vs {str(b)[:60]!r}"


def planner(tmp: Path) -> dict:
    from planner import export_v1
    export_v1.OUT, export_v1.ROOT = tmp / "planner_v1.json.gz", tmp  # ROOT only feeds its final print
    export_v1.main()
    a, b = load_gz(ROOT / "planner/out/planner_v1.json.gz"), load_gz(export_v1.OUT)
    a.pop("built_utc"), b.pop("built_utc")
    return {"equal_except_build_time": a == b, "first_diff": first_diff(a, b)}


def facts(tmp: Path) -> dict:
    from app.facts import build
    build.OUT = tmp / "facts"
    build.main()
    a, b = load_gz(ROOT / "app/facts/out/facts.json.gz"), load_gz(build.OUT / "facts.json.gz")
    a["meta"].pop("built_at"), b["meta"].pop("built_at")
    sha_ref = (ROOT / "app/facts/out/facts.sha").read_text().strip()
    sha_new = (build.OUT / "facts.sha").read_text().strip()
    return {"equal_except_build_time": a == b, "first_diff": first_diff(a, b),
            "facts_sha_ref": sha_ref, "facts_sha_new": sha_new, "meta_scores": b["meta"]["scores"]}


def packs(tmp: Path) -> dict:
    from app.packs import build_packs as bp
    bp.HERE, bp.OUT = tmp / "packs", tmp / "packs/out"
    bp.HERE.mkdir(parents=True)
    argv, sys.argv = sys.argv, ["build_packs.py"]
    try:
        bp.main()
    finally:
        sys.argv = argv
    ref_dir = ROOT / "app/packs/out"
    ref_idx = json.loads((ref_dir / "index.json").read_text())["packs"]
    new_idx = json.loads((bp.OUT / "index.json").read_text())["packs"]
    bad_files, bad_index, diffs = [], [], {}
    for name, e in ref_idx.items():
        ref_sha = hashlib.sha256((ref_dir / f"{name}.json.gz").read_bytes()).hexdigest()
        if ref_sha[:16] != e["sha256"]:
            bad_index.append(name)
        new = bp.OUT / f"{name}.json.gz"
        if not new.is_file() or hashlib.sha256(new.read_bytes()).hexdigest() != ref_sha:
            bad_files.append(name)
            if len(diffs) < 5 and new.is_file():
                diffs[name] = first_diff(load_gz(ref_dir / f"{name}.json.gz"), load_gz(new))
    other = {}
    for n in ("pin_index.json",):
        other[n] = (ref_dir / n).read_bytes() == (bp.OUT / n).read_bytes()
    return {"n_ref": len(ref_idx), "n_new": len(new_idx), "same_names": set(ref_idx) == set(new_idx),
            "index_sha_mismatch": bad_index, "rebuilt_bytes_differ": bad_files, "first_diffs": diffs, "other_files_identical": other,
            "unlisted_ref_files": sorted(p.name for p in ref_dir.glob("*.json.gz") if p.name[:-8] not in ref_idx)}


def main() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="exports_rebuild_"))
    res = {"scratch": str(tmp)}
    for name, fn in (("planner", planner), ("facts", facts), ("packs", packs)):
        try:
            res[name] = fn(tmp)
        except Exception as e:  # report, keep going: one failed builder should not hide the others
            res[name] = {"error": f"{type(e).__name__}: {e}"}
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out/exports_diff.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, default=str))
