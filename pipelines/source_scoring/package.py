"""Step 8: copy the canonical cleaned tables into derived/v1, write MANIFEST.json, drop intermediates.

Canonical grade table: cleaning/claims/out/grades.parquet = grader v2 with the other-facility quarantine on.
It is the table REPORT.md section 3 reports and the product reads; v2 was tuned after reading the 36 web
verdicts, so grades_v1.parquet (frozen before them) is shipped next to it as the honest out-of-sample
reference. The pending "G_nonspec leak" fix (department lists and research protocols should fall to weak)
is NOT applied in either file; nothing in this pipeline changes grades.
Usage: package.py --hashes-before (record data/raw hashes first) | package.py (copy + manifest)
"""
from __future__ import annotations

import json
import shutil
import sys

import pyarrow.parquet as pq

from ss_common import BUILD_DATE, HERE, OUT, RAW, ROOT, VERSION, WORK, sha256

COPY = {  # published name -> source (relative to ROOT)
    "facility_location.parquet": "cleaning/geo_identity/facility_location.parquet",
    "record_trust.parquet": "cleaning/geo_identity/record_trust.parquet",
    "facility_groups.parquet": "cleaning/geo_identity/facility_groups.parquet",
    "pin_gazetteer.parquet": "cleaning/geo_identity/pin_gazetteer.parquet",
    "place_gazetteer.parquet": "cleaning/geo_identity/place_gazetteer.parquet",
    "claims.parquet": "cleaning/claims/out/claims.parquet",
    "specialties.parquet": "cleaning/claims/out/specialties.parquet",
    "grades.parquet": "cleaning/claims/out/grades.parquet",
    "grades_v1.parquet": "cleaning/claims/out/grades_v1.parquet",
}
PUBLISH_WORK = {"evidence_rules.parquet", "gold_pairs.parquet"}
INPUTS = [  # files the scores depend on, hashed into the manifest
    "audit/provenance/domains.py", "audit/provenance/q1_sources.py", "audit/provenance/common.py",
    "audit/ground_truth/web_1.json", "audit/ground_truth/web_2.json", "audit/ground_truth/web_3.json",
    "model/gold/splits.json", *[f"model/gold/labels_{b}.json" for b in ("o1", "o2", "p1", "p2", "p3", "p4", "p5", "p6", "p7")],
    "cleaning/claims/out/handcheck.json", "cleaning/geo_identity/handcheck_location.csv", "audit/geo/hand_check_verdicts.csv",
    *COPY.values(),
]
MAX_BYTES = 50 * 1024 * 1024


def raw_hashes() -> dict[str, str]:
    return {p.name: sha256(p) for p in sorted(RAW.glob("*")) if p.is_file()}


def main() -> None:
    if "--hashes-before" in sys.argv:
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / "raw_hashes_before.json").write_text(json.dumps(raw_hashes(), indent=1))
        return
    for dst, src in COPY.items():
        shutil.copy2(ROOT / src, OUT / dst)
    for name in PUBLISH_WORK:
        shutil.copy2(WORK / name, OUT / name)
    stats = {p.stem: json.loads(p.read_text()) for p in sorted(WORK.glob("s*_stats.json"))}
    (OUT / "build_stats.json").write_text(json.dumps(stats, indent=1))
    tables = {}
    for p in sorted(OUT.glob("*.parquet")):
        size = p.stat().st_size
        assert size < MAX_BYTES, f"{p.name} is {size} bytes"
        tables[p.name] = {"rows": pq.ParquetFile(p).metadata.num_rows, "bytes": size}
    csvs = {p.name: {"rows": sum(1 for _ in open(p, encoding="utf-8")) - 1, "bytes": p.stat().st_size} for p in sorted(OUT.glob("*.csv"))}
    before = json.loads((WORK / "raw_hashes_before.json").read_text())
    after = raw_hashes()
    assert before == after, "data/raw changed during the build"
    manifest = {
        "build_date": BUILD_DATE, "pipeline": VERSION, "builder": "pipelines/source_scoring/run_all.sh",
        "tables": tables, "csv_copies": csvs,
        "raw_input_sha256": after,
        "other_input_sha256": {p: sha256(ROOT / p) for p in INPUTS},
        "script_sha256": {p.name: sha256(p) for p in sorted([*HERE.glob("*.py"), HERE / "run_all.sh"]) if p.exists()},
        "canonical_grades": "grades.parquet = cleaning/claims grade.py v2, quarantine on; grader-leak fix not applied",
        "licence": "Facility data: Databricks Marketplace consumer terms (Virtue Foundation share), keep the repo private. "
                   "PIN directory and NFHS-5: GODL-India.",
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=False))
    shutil.rmtree(WORK)
    print(json.dumps({k: v["rows"] for k, v in tables.items()}, indent=1))


if __name__ == "__main__":
    main()
