"""Independent helpers for the verification scripts (do not import claims_io)."""
import json
from math import sqrt
import pandas as pd

R = "/Users/karthikvattem/projects/datathon/"
OK = set(pd.read_parquet(R + "derived/v1/facility_location.parquet", columns=["unique_id"]).unique_id)
SERVICES = [s["id"] for c in json.load(open(R + "kb/taxonomy/services.json"))["categories"] for s in c["services"]]


def wil(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 3
    ph = k / n; d = 1 + z * z / n; c = (ph + z * z / (2 * n)) / d
    h = z * sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return round(ph, 4), round(c - h, 4), round(c + h, 4)


def raw():
    return pd.read_parquet(R + "data/raw/facilities.parquet").query("unique_id in @OK").drop_duplicates("unique_id")


def claims():
    """(unique_id, service) -> flags text_pos / spec, per kb/web_evidence/compare_dataset.py rule."""
    m = pd.read_parquet(R + "kb/taxonomy/out/lexicon_matches.parquet")
    m = m[m.unique_id.isin(OK)]
    good = (m.nonoffer_cue.fillna("") == "") & ~m.negation_extra & (m.attribution != "other_facility") & ~m.kind.isin(["staff", "directory"])
    tp = set(zip(m.unique_id[good], m.service[good]))
    ta = set(zip(m.unique_id, m.service))
    smap = pd.read_csv(R + "kb/taxonomy/specialty_map.csv", keep_default_na=False)
    v2s = {}
    for sp, sid in zip(smap.specialty, smap.service_id):
        for s in sid.split(";"):
            if s in SERVICES:
                v2s.setdefault(sp, set()).add(s)
    rw = raw()
    spec = set()
    for u, s in zip(rw.unique_id, rw.specialties):
        try:
            vals = json.loads(s) if isinstance(s, str) else []
        except ValueError:
            vals = []
        for v in vals if isinstance(vals, list) else []:
            for svc in v2s.get(v, ()):
                spec.add((u, svc))
    keys = sorted({k for k in ta | spec if k[1] in SERVICES})
    return pd.DataFrame([(u, s, (u, s) in tp, (u, s) in spec, (u, s) in ta) for u, s in keys],
                        columns=["unique_id", "service", "text_pos", "spec", "text_any"])
