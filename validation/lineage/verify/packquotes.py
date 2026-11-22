"""Semantic pack diff: per (facility, service) pair, the resolved quote texts, canonical vs rebuilt."""
import gzip, itertools, json, sys
from pathlib import Path

REF = Path("/Users/karthikvattem/projects/datathon/app/packs/out")


def pairs(p: Path) -> dict:
    d = json.loads(gzip.decompress(p.read_bytes()))
    ev, q, uid = d["ev"], d["q"], d["fac"]["uid8"]
    f = list(itertools.accumulate(ev["f"]))  # ev.f is delta-coded (build_packs.py delta())
    out = {}
    for i in range(len(f)):
        key = (uid[f[i]], d["services"][ev["s"][i]])
        assert key not in out, key
        qs = tuple(tuple(q[j]) if j >= 0 else None for j in (ev["q1"][i], ev["q2"][i]))
        rest = tuple(ev[k][i] for k in ("likely", "p", "lo", "hi"))
        out[key] = (qs, rest)
    return out


def main(new: Path) -> dict:
    n_pairs = n_q = n_sw = n_set = n_other = 0
    packs, ex = set(), []
    for a in sorted(REF.glob("*.json.gz")):
        pa, pb = pairs(a), pairs(new / a.name)
        assert pa.keys() == pb.keys(), a.name
        for k in pa:
            n_pairs += 1
            (qa, ra), (qb, rb) = pa[k], pb[k]
            n_q += sum(x is not None for x in qa)
            if ra != rb:
                n_other += 1
            if qa != qb:
                n_sw += 1
                packs.add(a.stem)
                if {x for x in qa if x} != {x for x in qb if x}:
                    n_set += 1
                if len(ex) < 8:
                    ex.append((a.stem, k, [x[0] if x else None for x in qa], [x[0] if x else None for x in qb]))
    return {"pairs": n_pairs, "quotes_shown": n_q, "pairs_quote_changed": n_sw, "pairs_quote_set_changed": n_set,
            "pairs_score_changed": n_other, "packs_with_change": sorted(packs), "examples": ex}


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1])), indent=1, default=str))
