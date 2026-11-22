"""submission/sim_results.csv, the committed aggregate read by referral_saathi.ipynb section 7b (#57)."""
from pathlib import Path

import pandas as pd

from sim import world

TABLE = Path(__file__).resolve().parents[2] / "submission" / "sim_results.csv"


def test_table_is_simulated_and_aggregate_only() -> None:
    head = TABLE.read_text().splitlines()[0]
    t = pd.read_csv(TABLE, comment="#")
    assert head.startswith("# SIMULATED")
    assert t.label.eq("SIMULATED").all()
    assert not {"facility_id", "unique_id", "case_id", "lat", "lon", "name"} & set(t.columns)
    grid = t.groupby(["policy", "scenario", "service"]).size()
    assert grid.eq(1).all() and set(t.scenario) == set(world.SCENARIOS)
    assert len(grid) == t.policy.nunique() * len(world.SCENARIOS) * t.service.nunique()
    assert t.treated_in_window.between(t.treated_in_window_lo, t.treated_in_window_hi).all()
    assert t.minus_ncf.isna().eq(t.policy.eq("nearest_call_first")).all()
