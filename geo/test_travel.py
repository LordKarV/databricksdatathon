"""Tests for geo/travel.py. No network: the HTTP call is replaced in every test.
Run: .venv/bin/python -m pytest geo/test_travel.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import travel  # noqa: E402

O = (26.45, 85.95)
D = [(26.3650, 86.0800), (26.1520, 85.8970)]


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(travel, "CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(travel, "_osrm_down_until", 0.0)


def fake_osrm(calls, durations, distances):
    def fetch(url, timeout_s):
        calls.append(url)
        return {"code": "Ok", "durations": [[0] + durations], "distances": [[0] + distances]}
    return fetch


def boom(url, timeout_s):
    raise TimeoutError("timed out")


def test_haversine_known_value():
    assert abs(travel.hav_km((0, 0), (0, 1)) - 111.19) < 0.01
    assert travel.hav_km(O, O) == 0


def test_osrm_result_and_request_shape(monkeypatch):
    calls = []
    monkeypatch.setattr(travel, "_fetch", fake_osrm(calls, [1800, 3600], [20000, 45000]))
    r = travel.travel_minutes(O, D)
    assert [x["method"] for x in r] == ["osrm", "osrm"]
    assert r[0]["minutes"] == 30 and r[0]["km"] == 20.0
    assert r[0]["low"] == 30 and r[0]["high"] == 30      # 20 km at 40 km/h is also 30 min
    assert r[1]["minutes"] == 60 and r[1]["high"] == 68  # 45 km at 40 km/h
    assert len(calls) == 1
    # OSRM wants lon,lat with the origin first
    assert "/table/v1/driving/85.950000,26.450000;86.080000,26.365000;85.897000,26.152000?" in calls[0]


def test_second_call_is_served_from_disk(monkeypatch):
    calls = []
    monkeypatch.setattr(travel, "_fetch", fake_osrm(calls, [1800, 3600], [20000, 45000]))
    first = travel.travel_minutes(O, D)
    monkeypatch.setattr(travel, "_fetch", boom)
    second = travel.travel_minutes(O, D)
    assert [(x["method"], x["cached"]) for x in second] == [("osrm", True), ("osrm", True)]
    assert [x["minutes"] for x in second] == [x["minutes"] for x in first]
    assert len(calls) == 1


def test_only_missing_destinations_are_requested(monkeypatch):
    calls = []
    monkeypatch.setattr(travel, "_fetch", fake_osrm(calls, [1800], [20000]))
    travel.travel_minutes(O, D[:1])
    monkeypatch.setattr(travel, "_fetch", fake_osrm(calls, [3600], [45000]))
    r = travel.travel_minutes(O, D)
    assert [(x["method"], x["cached"]) for x in r] == [("osrm", True), ("osrm", False)]
    assert calls[1].count(";") == 1  # origin plus the one missing destination


def test_falls_back_to_estimate_when_osrm_is_down(monkeypatch):
    monkeypatch.setattr(travel, "_fetch", boom)
    r = travel.travel_minutes(O, D)
    assert [x["method"] for x in r] == ["haversine_factor", "haversine_factor"]
    for x, d in zip(r, D):
        assert x["low"] <= x["minutes"] <= x["high"]
        assert x["km"] > travel.hav_km(O, d)
        assert "estimate" in x["label"]


def test_osrm_is_skipped_during_backoff(monkeypatch):
    calls = []

    def failing(url, timeout_s):
        calls.append(url)
        raise OSError("no route to host")
    monkeypatch.setattr(travel, "_fetch", failing)
    travel.travel_minutes(O, D)
    travel.travel_minutes(O, D)
    assert len(calls) == 1


def test_unroutable_destination_gets_estimate(monkeypatch):
    monkeypatch.setattr(travel, "_fetch", fake_osrm([], [1800, None], [20000, None]))
    r = travel.travel_minutes(O, D)
    assert [x["method"] for x in r] == ["osrm", "haversine_factor"]


def test_bad_osrm_payload_falls_back(monkeypatch):
    monkeypatch.setattr(travel, "_fetch", lambda url, timeout_s: {"code": "InvalidQuery"})
    assert [x["method"] for x in travel.travel_minutes(O, D)] == ["haversine_factor", "haversine_factor"]
    monkeypatch.setattr(travel, "_osrm_down_until", 0.0)
    monkeypatch.setattr(travel, "_fetch", fake_osrm([], [1800], [20000]))  # one result for two destinations
    assert [x["method"] for x in travel.travel_minutes(O, D)] == ["haversine_factor", "haversine_factor"]


def test_use_osrm_false_never_calls_the_network(monkeypatch):
    monkeypatch.setattr(travel, "_fetch", lambda *a: pytest.fail("network used"))
    assert [x["method"] for x in travel.travel_minutes(O, D, use_osrm=False)] == ["haversine_factor", "haversine_factor"]


def test_large_request_is_split(monkeypatch):
    calls = []

    def fetch(url, timeout_s):
        calls.append(url)
        n = url.split("?")[0].count(";")
        return {"code": "Ok", "durations": [[0] + [600] * n], "distances": [[0] + [8000] * n]}
    monkeypatch.setattr(travel, "_fetch", fetch)
    dests = [(26.0 + i * 0.001, 85.0) for i in range(150)]
    r = travel.travel_minutes(O, dests)
    assert len(r) == 150 and all(x["method"] == "osrm" for x in r)
    assert [u.split("?")[0].count(";") for u in calls] == [99, 51]


def test_cache_off_and_broken_cache_still_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(travel, "_fetch", fake_osrm([], [1800, 3600], [20000, 45000]))
    monkeypatch.setattr(travel, "CACHE_PATH", "off")
    assert [x["method"] for x in travel.travel_minutes(O, D)] == ["osrm", "osrm"]
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(travel, "CACHE_PATH", str(blocker / "cache.sqlite"))  # parent is a file
    assert [x["method"] for x in travel.travel_minutes(O, D)] == ["osrm", "osrm"]


def test_estimate_is_monotonic_in_distance():
    mins = [travel.estimate((20.0, 78.0), (20.0 + k / 111.19, 78.0))["minutes"] for k in [x / 4 for x in range(1, 1200)]]
    assert mins == sorted(mins) and mins[-1] > mins[0] >= 0


def test_input_validation():
    with pytest.raises(ValueError):
        travel.travel_minutes(O, D, mode="walk")
    with pytest.raises(ValueError):
        travel.travel_minutes((91.0, 80.0), D)
    with pytest.raises(ValueError):
        travel.travel_minutes(O, [("a", 1)])
    with pytest.raises(ValueError):
        travel.travel_minutes(O, [(float("nan"), 1.0)])
    assert travel.travel_minutes(O, []) == []
