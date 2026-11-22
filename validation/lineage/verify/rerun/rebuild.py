"""Re-run pipelines/source_scoring into a scratch directory and diff the result against derived/v1.

run_all.sh and ss_common.py hard-code OUT = derived/v1, so the pipeline cannot be pointed elsewhere.
This copies the scripts into <scratch>/src, rewrites the single OUT line in the copy of ss_common.py,
pre-seeds <scratch>/out with the stored source_page_checks.parquet (so s3, the live web fetch, is skipped
exactly as run_all.sh does when that file exists) and runs the same steps in the same order.
Nothing under the project is written except validation/lineage/out/rebuild_diff.json.
Usage: rebuild.py [scratch_dir]   (default: a fresh temp dir)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
SRC = ROOT / "pipelines/source_scoring"
REF = ROOT / "derived/v1"
PY = ROOT / ".venv/bin/python"
HERE = Path(__file__).resolve().parent
STEPS = ["ss_common.py", "package.py --hashes-before", "s1_sources.py", "s2_gold.py", "s4_datapoints.py",
         "s5_fit.py", "s6_score.py", "s7_eval.py", "package.py", "selfcheck.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(scratch: Path, extra_env: dict | None = None) -> dict:
    src, out = scratch / "src", scratch / "out"
    shutil.copytree(SRC, src, ignore=shutil.ignore_patterns("__pycache__"))
    ssc = src / "ss_common.py"
    text = ssc.read_text()
    old = 'OUT = ROOT / "derived/v1"'
    assert text.count(old) == 1, "ss_common.py OUT line changed; update rebuild.py"
    ssc.write_text(text.replace(old, f'OUT = Path({str(out)!r})'))
    out.mkdir(parents=True)
    shutil.copy2(REF / "source_page_checks.parquet", out / "source_page_checks.parquet")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})}
    log = []
    for step in STEPS:
        r = subprocess.run([str(PY), *step.split()], cwd=src, env=env, capture_output=True, text=True)
        log.append({"step": step, "rc": r.returncode, "stderr_tail": r.stderr[-800:], "stdout_tail": r.stdout[-300:]})
        if r.returncode:
            return {"scratch": str(scratch), "ok": False, "log": log}
    return {"scratch": str(scratch), "ok": True, "log": log, "diff": diff(out)}


def frame_diff(a: Path, b: Path) -> dict:
    """Exact cell comparison; floats also report the max absolute difference."""
    x, y = pd.read_parquet(a), pd.read_parquet(b)
    res = {"rows_ref": len(x), "rows_new": len(y), "cols_equal": list(x.columns) == list(y.columns)}
    if not res["cols_equal"] or len(x) != len(y):
        return res
    bad = {}
    for c in x.columns:
        xa, ya = x[c], y[c]
        both_na = xa.isna() & ya.isna()
        if pd.api.types.is_float_dtype(xa):
            ne = ~((xa == ya) | both_na)
            e = {"n": int(ne.sum()), "max_abs": float((xa - ya).abs().max()) if ne.any() else 0.0}
        else:
            ne = ~((xa.astype(object) == ya.astype(object)).fillna(False).astype(bool) | both_na)
            e = {"n": int(ne.sum())}
        if ne.any():
            e["first_rows"] = [int(i) for i in ne[ne].index[:5]]
            bad[c] = e
    res["cells_differ"] = bad
    res["max_abs_float_diff"] = max([v.get("max_abs", 0.0) for v in bad.values()], default=0.0)
    res["non_float_cells_differ"] = sum(v["n"] for v in bad.values() if "max_abs" not in v)
    return res


def diff(out: Path) -> dict:
    ref_files = {p.name for p in REF.iterdir() if p.is_file()}
    new_files = {p.name for p in out.iterdir() if p.is_file()}
    res = {"only_ref": sorted(ref_files - new_files), "only_new": sorted(new_files - ref_files), "files": {}}
    for n in sorted(ref_files & new_files):
        a, b = REF / n, out / n
        same = sha(a) == sha(b)
        e = {"byte_identical": same}
        if not same and n.endswith(".parquet"):
            e["frame"] = frame_diff(a, b)
        elif not same and n.endswith(".json"):
            ja, jb = json.loads(a.read_text()), json.loads(b.read_text())
            e["json_top_keys_differ"] = sorted(k for k in set(ja) | set(jb) if ja.get(k) != jb.get(k))
        elif not same and n.endswith(".csv"):
            ca, cb = pd.read_csv(a), pd.read_csv(b)
            e["csv_rows"] = [len(ca), len(cb)]
            num = ca.select_dtypes("number").columns
            e["csv_non_numeric_equal"] = ca.drop(columns=num).equals(cb.drop(columns=num))
            e["csv_max_abs_numeric_diff"] = float((ca[num] - cb[num]).abs().max().max()) if len(num) else 0.0
        res["files"][n] = e
    return res


if __name__ == "__main__":
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="ss_rebuild_"))
    if scratch.exists() and any(scratch.iterdir()):
        sys.exit(f"{scratch} is not empty")
    scratch.mkdir(parents=True, exist_ok=True)
    res = run(scratch)
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / f"out/rebuild_diff_{scratch.name}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1)[:6000])
