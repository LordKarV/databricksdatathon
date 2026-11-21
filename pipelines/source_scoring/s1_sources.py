"""Step 1: explode source_urls into one row per (record, URL) with host, registrable domain, class and kind.

Class comes from audit/provenance/domains.py classify() and kind ('about' / 'list' / 'unverified') from
audit/provenance/q1_sources.py url_kind(), unchanged, so the totals reproduce q1_results.json
(158,444 URLs; about 44,434 / list 17,340 / unverified 96,670).
Writes derived/v1/_work/record_urls.parquet.
"""
from __future__ import annotations

import json

import pandas as pd

from ss_common import WORK, classify, facilities, host, jlist, official_hosts, registrable_domain, url_kind


def explode(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in df.itertuples(index=False):
        off = official_hosts(r)
        for pos, u in enumerate(jlist(r.source_urls)):
            h = host(u)
            c = classify(h, off, r.name)
            rows.append((r.unique_id, pos, u, h, registrable_domain(h), c, url_kind(u, r.name, c)))
    return pd.DataFrame(rows, columns=["unique_id", "url_pos", "url", "host", "domain", "source_class", "url_kind"])


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    u = explode(facilities())
    u["n_records_url"] = u.url.map(u.groupby("url").unique_id.nunique())
    u.to_parquet(WORK / "record_urls.parquet", index=False)
    st = {"rows": len(u), "records": int(u.unique_id.nunique()), "distinct_urls": int(u.url.nunique()),
          "distinct_hosts": int(u.host.nunique()), "distinct_domains": int(u.domain.nunique()),
          "url_kind": u.url_kind.value_counts().to_dict(), "source_class": u.source_class.value_counts().to_dict()}
    (WORK / "s1_stats.json").write_text(json.dumps(st, indent=1))
    print(json.dumps(st, indent=1))
    assert st["rows"] == 158444, st["rows"]


if __name__ == "__main__":
    main()
