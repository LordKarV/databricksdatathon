"""The offline satellite watch (static/offline.js watchSatellite): a geolocation error (denied, unavailable, or the
120 s timeout) clears the watch and tells the caller, so the offline screen drops its "getting GPS" prompt."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

OFFLINE_JS = Path(__file__).resolve().parents[1] / "static" / "offline.js"

# a fake navigator.geolocation that records the watch and lets the test fire its callbacks
HARNESS = """
const calls = {cleared: [], fix: [], fail: 0};
let cb = null;
Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {geolocation: {
  watchPosition(ok, err) { cb = {ok, err}; return 7; },
  clearWatch(id) { calls.cleared.push(id); },
}}});
require(process.argv[1]);
const stop = RSOffline.watchSatellite(f => calls.fix.push(f), () => { calls.fail++; });
const step = process.argv[2];
if (step === 'error') cb.err({code: 3, message: 'Timeout expired'});
if (step === 'fix') cb.ok({coords: {latitude: 25.6, longitude: 85.1, accuracy: 40}});
calls.stop = typeof stop;
console.log(JSON.stringify(calls));
"""


def _run(step: str) -> dict:
    out = subprocess.run(["node", "-e", HARNESS, str(OFFLINE_JS), step], capture_output=True, text=True,
                         check=True).stdout
    return json.loads(out)


pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def test_a_geolocation_error_clears_the_watch_and_tells_the_caller():
    got = _run("error")
    assert got["cleared"] == [7]
    assert got["fail"] == 1
    assert got["fix"] == []


def test_a_good_fix_clears_the_watch_and_does_not_report_a_failure():
    got = _run("fix")
    assert got["cleared"] == [7]
    assert got["fail"] == 0
    assert [(f["lat"], f["lon"], f["source"]) for f in got["fix"]] == [(25.6, 85.1, "gps")]
    assert got["stop"] == "function"
