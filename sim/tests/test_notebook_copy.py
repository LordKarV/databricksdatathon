"""The submission notebook under the project's name, Bharosa, and its copy under the earlier name stay identical.

`submission/build_notebook.py` writes `bharosa.ipynb` and copies it to `referral_saathi.ipynb`, the path the deployed
Databricks job runs. A hand edit to one of them would make the two tell different stories.
"""
from __future__ import annotations

from pathlib import Path

SUB = Path(__file__).resolve().parents[2] / "submission"


def test_notebook_copies_identical() -> None:
    new, old = SUB / "bharosa.ipynb", SUB / "referral_saathi.ipynb"
    assert new.exists() and old.exists()
    assert new.read_bytes() == old.read_bytes(), "edit bharosa.ipynb via build_notebook.py, which writes both"
