"""Band source for the offline packs (issue #22): conservative placeholder, model table when published."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packs"))
import build_packs  # noqa: E402


def _svc() -> pd.DataFrame:
    return pd.DataFrame({
        "unique_id": ["a", "b", "c", "d"],
        "service": ["dialysis", "dialysis", "mri", "nicu"],
        "status": ["verified_true", "unverified", "unverified", "unverified"],
        "grade": ["moderate", "strong", "strong", "weak"],
        "score": [0.9, 0.95, 0.97, 0.5], "score_lo": [0.8, 0.9, 0.9, 0.3], "score_hi": [0.95, 0.99, 0.99, 0.7],
    })


def test_placeholder_marks_only_verified_true_likely(tmp_path):
    out = build_packs.apply_bands(_svc(), tmp_path / "missing.parquet")
    assert out.likely.tolist() == [1, 0, 0, 0], "strong grades alone must not become likely"
    assert out.score.tolist() == [0.9, 0.95, 0.97, 0.5]
    assert out.attrs["band_source"].startswith("placeholder")


def test_model_table_replaces_bands_and_drops_unlikely(tmp_path):
    path = tmp_path / "facility_service_scores.parquet"
    pd.DataFrame({
        "unique_id": ["a", "b", "c"], "service_id": ["dialysis", "dialysis", "mri"],
        "band": ["not_verified", "likely", "unlikely"], "p": [0.4, 0.8, 0.1], "lo": [0.2, 0.7, 0.05],
        "hi": [0.6, 0.9, 0.2], "as_of": ["2026-11-22"] * 3,
    }).to_parquet(path)
    out = build_packs.apply_bands(_svc(), path).set_index("unique_id")
    assert list(out.index) == ["a", "b"], "unlikely (c) and unscored (d) pairs are dropped"
    assert out.loc["a", "likely"] == 0 and out.loc["b", "likely"] == 1
    assert (out.loc["b", "score"], out.loc["b", "score_lo"], out.loc["b", "score_hi"]) == (0.8, 0.7, 0.9)
    assert out.attrs["band_source"] == "model: facility_service_scores.parquet as of 2026-11-22"


def test_model_table_accepts_derived_service_names(tmp_path):
    path = tmp_path / "s.parquet"
    pd.DataFrame({"unique_id": ["d"], "service_id": ["nicu"], "band": ["likely"], "p": [0.8], "lo": [0.7],
                  "hi": [0.9], "as_of": ["x"]}).to_parquet(path)
    svc = _svc().assign(service=["emergency_csection", "dialysis", "mri", "nicu"])
    svc.loc[0, "service"] = "emergency_csection"
    path2 = tmp_path / "s2.parquet"
    pd.DataFrame({"unique_id": ["a"], "service_id": ["csection"], "band": ["likely"], "p": [0.8], "lo": [0.7],
                  "hi": [0.9], "as_of": ["x"]}).to_parquet(path2)
    assert build_packs.apply_bands(svc, path2).likely.tolist() == [1]
    assert build_packs.apply_bands(svc, path).likely.tolist() == [1]
