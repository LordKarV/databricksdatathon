"""Checks on the built derived/v2 tables (run after build.py):
/Users/karthikvattem/projects/datathon/.venv-viz/bin/python test_assemble.py

Named cases from MODEL_SPEC 3.1 and 8: Sharda Hospital gets a PIN dissent (PIN 270001 not in India Post),
Smile Kraft Dental Clinic gets S = 1 for trauma, Nayan Jyoti Eye Hospital gets S = 1 for emergency C-section,
Wockhardt Nagpur keeps its rejected dialysis sentences in family C.
"""
from __future__ import annotations

import pandas as pd

import acommon as A


def main() -> None:
    W = pd.read_parquet(A.OUT / "witnesses.parquet")
    F = pd.read_parquet(A.OUT / "facility_features.parquet")
    T = pd.read_parquet(A.OUT / "facility_attributes.parquet")
    nm = T.set_index("unique_id").name

    def uids(s: str) -> list[str]:
        return nm.index[nm.str.contains(s, regex=False)].tolist()

    assert len(F) == 9959 * 36 and F.unique_id.nunique() == 9959 and len(T) == 9959
    sharda = F[F.unique_id.isin(uids("Sharda Hospital")) & (F.pin_in_india_post == 0)]
    assert len(sharda) and (sharda.vote_pin == -1).all(), "Sharda: PIN missing from India Post must dissent"
    sk = F[F.unique_id.isin(uids("Smile Kraft")) & (F.service == "trauma_care")]
    assert len(sk) and (sk.a_scope_conflict == 1).all()
    nj = F[F.unique_id.isin(uids("Nayan Jyoti")) & (F.service == "emergency_csection")]
    assert len(nj) and (nj.a_scope_conflict == 1).all()
    wk = W[W.unique_id.isin(uids("Wockhardt Hospital Nagpur")) & (W.service == "dialysis") & (W.family == "C")]
    assert (wk.observability == "present").any() and wk.note.str.contains("Nair Hospital").any()
    # fairness coding: no NaN-coded (not observable) website value for a facility with an attributable site
    assert F.loc[F.obs_W == "not_observable", "e_web_service"].isna().all()
    assert F.loc[F.obs_W == "absent", "e_web_service"].eq(0).all()
    # public facilities without a NABH match are not observable, never 0
    pub = F.operator_public == 1
    assert F.loc[pub & F.d_nabh_listed.notna(), "d_nabh_listed"].eq(1).all()
    # not-observable and absent rows carry value 0 and no evidence
    q = W[W.observability != "present"]
    assert q.value.eq(0).all() and q.evidence_id.isna().all() and q.quote.isna().all()
    assert set(W.family) == set(A.FAMILIES) - {"R"} or set(W.family) == set(A.FAMILIES)
    print("test_assemble ok")


if __name__ == "__main__":
    main()
