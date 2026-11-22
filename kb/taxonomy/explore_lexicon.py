"""Exploration helper: tag every claim sentence with lexicon_src and print counts plus random matched sentences.
Used to find false positives while writing exclude patterns. Writes nothing tracked (scratch parquet only)."""
from __future__ import annotations
import sys, time
import pandas as pd
import lexicon_src as LS

CLAIMS = "/Users/karthikvattem/projects/datathon/cleaning/claims/out/claims.parquet"
SCRATCH = sys.argv[1]


def main() -> None:
    c = pd.read_parquet(CLAIMS, columns=["claim_id", "unique_id", "field", "text", "services"])
    comp = LS.compile_specs(LS.all_specs())
    t0 = time.time()
    c["kb"] = ["|".join(LS.match(s, comp)) for s in c.text]
    print("tagged in", round(time.time() - t0), "s")
    c.to_parquet(SCRATCH, index=False)


if __name__ == "__main__":
    main()
