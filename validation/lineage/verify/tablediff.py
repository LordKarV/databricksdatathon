"""Independent table diff (not the auditor's code): derived/v1 vs a rebuild dir, cell by cell after aligning on keys."""
import hashlib, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

V1 = Path("/Users/karthikvattem/projects/datathon/derived/v1")


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def frame_diff(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return {"shape_or_cols_differ": [list(a.columns) == list(b.columns), len(a), len(b)]}
    out = {"cells_differ": 0, "max_abs": 0.0, "nonfloat_cols_differ": [], "rank_changes": {}, "round3_differ": 0}
    for c in a.columns:
        x, y = a[c], b[c]
        if pd.api.types.is_float_dtype(x):
            xv, yv = x.to_numpy(float), y.to_numpy(float)
            both_nan = np.isnan(xv) & np.isnan(yv)
            neq = ~both_nan & (xv != yv)
            out["cells_differ"] += int(neq.sum())
            if neq.any():
                out["max_abs"] = max(out["max_abs"], float(np.nanmax(np.abs(xv - yv)[neq])))
                out["round3_differ"] += int((np.round(xv, 3) != np.round(yv, 3))[~both_nan].sum())
                # rank: does ordering of the column change? (ties count)
                ok = ~np.isnan(xv) & ~np.isnan(yv)  # NaN rows have no rank
                rx, ry = pd.Series(xv[ok]).rank(method="min"), pd.Series(yv[ok]).rank(method="min")
                out["rank_changes"][c] = int((rx.to_numpy() != ry.to_numpy()).sum())
        else:
            xs = x.astype(str).where(x.notna(), "<NA>")
            ys = y.astype(str).where(y.notna(), "<NA>")
            n = int((xs != ys).sum())
            if n:
                out["nonfloat_cols_differ"].append((c, n))
    return out


def main(new_dir: Path) -> dict:
    res = {}
    for p in sorted(V1.iterdir()):
        q = new_dir / p.name
        if p.name in ("README.md",) or not q.exists():
            res[p.name] = "missing in rebuild" if not q.exists() and p.name != "README.md" else "skip"
            continue
        e = {"byte_identical": sha(p) == sha(q)}
        if not e["byte_identical"] and p.suffix in (".parquet", ".csv"):
            rd = pd.read_parquet if p.suffix == ".parquet" else pd.read_csv
            e.update(frame_diff(rd(p), rd(q)))
        elif not e["byte_identical"] and p.suffix == ".json":
            a, b = json.loads(p.read_text()), json.loads(q.read_text())
            e["top_keys_differ"] = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
        res[p.name] = e
    return res


if __name__ == "__main__":
    r = main(Path(sys.argv[1]))
    print(json.dumps(r, indent=1, default=str))
