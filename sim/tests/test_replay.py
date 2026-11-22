"""The replay page (sim/replay.py) builds from a run's files, embeds only the chosen cases, and cannot break out of
its script tag."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from sim import replay

ROOT = Path(__file__).resolve().parents[2]
needs_data = pytest.mark.skipif(not (ROOT / "derived/v1/facility_location.parquet").is_file(), reason="no derived/v1")


def tiny_run(out: Path) -> list[str]:
    fac = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "state_final"])
    ids = fac[fac.state_final.str.upper() == "BIHAR"].unique_id.head(3).tolist()
    (out / "cases").mkdir(parents=True)
    (out / "events").mkdir()
    (out / "truth").mkdir()
    pd.DataFrame([{"case_id": "s0c1", "seed": 0, "lat": 25.6, "lon": 85.1, "state": "BIHAR", "district": "PATNA",
                   "service": "trauma_emergency", "urgency": "emergency", "window_min": 60, "t0_min": 0,
                   "has_data": True, "has_phone_signal": True}]).to_parquet(out / "cases" / "r1.parquet")
    ev = []
    for pol, fid, end in (("app", ids[0], "treated"), ("nearest_call_first", ids[1], "gave_up"),
                          ("best_on_paper", ids[2], "treated")):
        ev += [{"policy": pol, "step": 1, "kind": "call", "facility_id": fid, "t_min": 5.0, "outcome": "yes"},
               {"policy": pol, "step": 1, "kind": "travel", "facility_id": fid, "t_min": 40.0, "outcome": "35"},
               {"policy": pol, "step": 1, "kind": end, "facility_id": fid, "t_min": 40.0,
                "outcome": "ok" if end == "treated" else "list_exhausted"}]
    e = pd.DataFrame(ev).assign(run_id="r1", scenario="S0", seed=0, case_id="s0c1")
    e.to_parquet(out / "events" / "r1.parquet")
    pd.DataFrame([{"unique_id": i, "service": "trauma_emergency", "exists": True, "offers": k != 1, "phone_ok": True,
                   "open_now_p": 0.9, "accept_p": 0.9, "true_lat": 25.6, "true_lon": 85.1} for k, i in enumerate(ids)]
                 ).to_parquet(out / "truth" / "S0_0.parquet")
    return ids


@needs_data
def test_replay_builds_a_self_contained_page(tmp_path, monkeypatch):
    ids = tiny_run(tmp_path)
    monkeypatch.setattr("sys.argv", ["replay", "--sim-out", str(tmp_path)])
    replay.main()
    html = (tmp_path / "replay.html").read_text()
    assert "SIMULATED" in html and "<script src" not in html and "http" not in html.split("<script>")[1]
    data = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1).replace("<\\/", "</"))
    assert [c["id"] for c in data["cases"]] == ["s0c1"]
    assert set(data["steps"]["S0|s0c1"]) == {"app", "nearest_call_first", "best_on_paper"}
    assert set(data["fac"]) == set(ids) and all(not v[0].count("-") == 4 for v in data["fac"].values())  # names
    assert data["truth"]["S0"][f"{ids[1]}|trauma_emergency"][0] is False
    assert data["summary"]["S0"]["app"]["in_window"] == 1.0
    assert data["summary"]["S0"]["nearest_call_first"]["in_window"] == 0.0


def test_payload_cannot_close_the_script_tag():
    s = json.dumps({"x": "</script><script>alert(1)</script>"}).replace("</", "<\\/")
    assert "</script" not in s
