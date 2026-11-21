"""Assert-based self-check of derived/v1. Exit code 0 and 'selfcheck ok' when every check holds."""
from __future__ import annotations

import json

import duckdb
import pandas as pd

from ss_common import OUT, RAW, sha256

UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def main() -> None:
    man = json.loads((OUT / "MANIFEST.json").read_text())
    # 1. original data/raw files unchanged (hashes recorded before the build)
    for name, h in man["raw_input_sha256"].items():
        assert sha256(RAW / name) == h, f"data/raw/{name} changed"
    raw = duckdb.sql(f"select unique_id, officialPhone, email from read_parquet('{RAW}/facilities.parquet') "
                     f"where source='kie' and regexp_matches(unique_id, '{UUID}')").df().drop_duplicates("unique_id")
    ids = set(raw.unique_id)
    assert len(ids) == 9959, len(ids)
    dp = pd.read_parquet(OUT / "data_point_scores.parquet")
    # 2. scores and intervals in [0, 1] and ordered
    assert dp.score.between(0, 1).all() and dp.score_lo.between(0, 1).all() and dp.score_hi.between(0, 1).all()
    assert (dp.score_lo <= dp.score + 1e-12).all() and (dp.score <= dp.score_hi + 1e-12).all()
    # 3. verified-false below 0.1, verified-true above 0.9
    assert (dp.loc[dp.status == "verified_false", "score"] < 0.1).all()
    assert (dp.loc[dp.status == "verified_true", "score"] > 0.9).all()
    assert dp.status.isin(["verified_true", "verified_false", "unverified"]).all()
    # 4. every row joins to an original unique_id, in every published table that has one
    for p in OUT.glob("*.parquet"):
        cols = pq_cols(p)
        if "unique_id" in cols:
            u = set(pd.read_parquet(p, columns=["unique_id"]).unique_id)
            assert u <= ids, f"{p.name}: {len(u - ids)} unique_ids not in data/raw"
    # 5. original values copied unchanged
    cl = pd.read_parquet(OUT / "claims.parquet", columns=["claim_id", "text"]).set_index("claim_id").text
    s = dp[dp.dp_type == "claim_attribution"]
    assert len(s) == len(cl) and (s.original_value.to_numpy() == cl.reindex(s.claim_id).to_numpy()).all()
    ph = dp[dp.dp_type == "phone"].set_index("unique_id").original_value
    assert (ph == raw.set_index("unique_id").officialPhone.reindex(ph.index)).all()
    em = dp[dp.dp_type == "email"].set_index("unique_id").original_value
    assert (em == raw.set_index("unique_id").email.reindex(em.index)).all()
    assert dp.dp_id.is_unique
    # 6. domain reliabilities are proper posteriors; every table under 50 MB; row counts match the manifest
    d = pd.read_parquet(OUT / "source_domains.parquet")
    assert d.reliability.between(0, 1).all() and (d.ci05 <= d.reliability).all() and (d.reliability <= d.ci95).all()
    for name, t in man["tables"].items():
        assert t["bytes"] < 50 * 1024 * 1024 and pq_rows(OUT / name) == t["rows"], name
    # 7. Goal 3 stayed within its bounds
    pc = pd.read_parquet(OUT / "source_page_checks.parquet")
    assert pc.url.nunique() <= 400 and (pc.snippet.fillna("").str.len() <= 160).all()
    print(f"selfcheck ok: {len(dp)} data points, {len(d)} domains, {len(man['tables'])} tables")


def pq_cols(p) -> list[str]:
    import pyarrow.parquet as pq
    return pq.ParquetFile(p).schema_arrow.names


def pq_rows(p) -> int:
    import pyarrow.parquet as pq
    return pq.ParquetFile(p).metadata.num_rows


if __name__ == "__main__":
    main()
