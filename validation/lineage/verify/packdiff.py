"""Independent pack diff: canonical app/packs/out vs a rebuilt packs dir, leaf by leaf."""
import gzip, json, sys
from pathlib import Path

REF = Path("/Users/karthikvattem/projects/datathon/app/packs/out")


def leaves(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, f"{p}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, f"{p}[{i}]")
    else:
        yield p, o


def main(new: Path) -> dict:
    res = {"packs": 0, "bytes_differ": [], "content_differ": {}, "leaf_diffs": 0, "examples": [], "total_strings": 0}
    for a in sorted(REF.glob("*.json.gz")):
        b = new / a.name
        res["packs"] += 1
        if a.read_bytes() != b.read_bytes():
            res["bytes_differ"].append(a.stem)
        da, db = (json.loads(gzip.decompress(x.read_bytes())) for x in (a, b))
        la, lb = dict(leaves(da)), dict(leaves(db))
        res["total_strings"] += sum(isinstance(v, str) for v in la.values())
        d = [k for k in set(la) | set(lb) if la.get(k) != lb.get(k)]
        if d:
            res["content_differ"][a.stem] = len(d)
            res["leaf_diffs"] += len(d)
            for k in sorted(d)[:1]:
                res["examples"].append((a.stem, k, la.get(k), lb.get(k)))
    for n in ("index.json", "pin_index.json"):
        res[f"{n}_identical"] = (REF / n).read_bytes() == (new / n).read_bytes()
    return res


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1])), indent=1, default=str))
