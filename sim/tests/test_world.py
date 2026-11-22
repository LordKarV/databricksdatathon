"""sim/world.py: cases, truth per scenario, and the honesty rules (#92). Reads derived/ and the DEV labels only."""
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from sim import world

SIM = Path(world.__file__).resolve().parent


def test_cases_are_seeded_and_shaped():
    a, b = world.cases(7, n=20), world.cases(7, n=20)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(world.cases(8, n=20))
    assert list(a.columns) == ["case_id", "seed", "lat", "lon", "state", "district", "service", "urgency",
                               "window_min", "t0_min", "has_data", "has_phone_signal"]
    assert len(a) == 20 * len(world.STATES) * len(world.SERVICES) and a.case_id.is_unique
    assert set(a.state) == set(world.STATES)
    assert dict(zip(a.service, a.urgency, strict=True)) == {"dialysis": "planned", "trauma_emergency": "emergency"}
    assert world.window_min("trauma_emergency") == 60 and world.window_min("dialysis") == 120
    assert a.has_data.any() and not a.has_data.all()


@pytest.mark.parametrize("scenario", world.SCENARIOS)
def test_truth_is_seeded_and_has_the_interface_columns(scenario):
    t = world.truth_table(scenario, 3)
    assert list(t.columns) == world.TRUTH_COLS
    pd.testing.assert_frame_equal(t, world.truth_table(scenario, 3))
    assert set(t.service) == set(world.SERVICES)
    assert not t.duplicated(["unique_id", "service"]).any()


def _with_strata(t, service):
    d = world._pairs(service)[["unique_id", "stratum", "operator", "grade", "p", "loc_rule", "lat"]]
    return t[t.service == service].merge(d, on="unique_id")


def test_s1_offers_follow_the_model_p():
    t = _with_strata(world.truth_table("S1", 4), "trauma_emergency")
    assert abs(t.offers.mean() - t.p.fillna(0).mean()) < 0.02


def test_s2_reproduces_the_dev_label_rates():
    """Each S2 cell rate is the DEV confirmed-of-decided rate, shrunk by at most SMOOTH / (n + SMOOTH); the truth
    then hits that rate within sampling error."""
    lab = world._dev()
    for (gid, stratum), rate in world.s2_rates().items():
        cell = lab[(lab.service_id == gid) & (lab.stratum == stratum)]
        assert abs(rate - cell.yes.mean()) <= world.SMOOTH / (len(cell) + world.SMOOTH) + 1e-9
    for service, meta in world.SERVICES.items():
        t = _with_strata(world.truth_table("S2", 5), service)
        for stratum, g in t.groupby("stratum"):
            r = world.s2_rates()[(meta["v2"], stratum)]
            assert abs(g.offers.mean() - r) < 4 * (r * (1 - r) / len(g)) ** 0.5 + 0.01, (service, stratum)


@pytest.mark.parametrize("scenario", ["S0-high", "S0-low"])
def test_s0_ignores_the_text(scenario):
    t = _with_strata(world.truth_table(scenario, 6), "trauma_emergency")
    priv = t[t.operator == "private"]
    by = priv.groupby("stratum").offers.mean()
    assert abs(by["strong"] - by["no_mention"]) < 0.05


def test_s0_bounds():
    """S0-high is confirmed of decided DEV pairs ("S0" is its alias); S0-low also counts no_info as not offered, so
    every cell's rate is lower, and the shared uniforms make S0-low offers a subset wherever the rate is lower."""
    pd.testing.assert_frame_equal(world.truth_table("S0", 6), world.truth_table("S0-high", 6))
    hi, lo = world.s0_rates("high"), world.s0_rates("low")
    both = hi.index.intersection(lo.index)
    assert len(both) and (lo[both] < hi[both]).all()
    th, tl = world.truth_table("S0-high", 6), world.truth_table("S0-low", 6)
    assert (th.exists == tl.exists).all() and (th.phone_ok == tl.phone_ok).all()
    assert tl.offers.mean() < th.offers.mean() and not (tl.offers & ~th.offers).any()
    with pytest.raises(ValueError):
        world.s0_rates("mid")


def test_s3_breaks_attribution_and_moves_map_points():
    t = _with_strata(world.truth_table("S3", 2), "trauma_emergency")
    assert not t[t.grade == "attributed_elsewhere"].offers.any()
    moved = t[(t.true_lat != t.lat) | t.true_lat.isna()]
    assert len(moved) > 0 and set(moved.loc_rule) != {"LOC_HIGH"}
    s2 = _with_strata(world.truth_table("S2", 2), "trauma_emergency")
    assert (s2.true_lat == s2.lat).all()


def test_listing_holds_no_truth():
    for s in world.SERVICES:
        cols = set(world.listing(s).columns)
        assert not cols & (set(world.TRUTH_COLS) - {"unique_id", "service"})


def test_no_test_labels_and_policies_never_read_truth():
    sealed = ["test_" + "labels", "test_" + "sample", "test_" + "predictions"]
    for f in SIM.glob("*.py"):
        text = f.read_text()
        assert not any(s in text for s in sealed), f.name
    pol = (SIM / "policies_baseline.py").read_text()
    assert "truth_table" not in pol and "import execute" not in pol and "write_truth" not in pol


def test_outputs_carry_the_simulated_label(tmp_path):
    p = world.write_parquet(pd.DataFrame({"a": [1]}), tmp_path / "x.parquet")
    assert pq.read_schema(p).metadata[b"simulated"].decode().startswith("SIMULATED")
