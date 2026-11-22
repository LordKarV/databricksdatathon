"""The offline PIN label (static/offline.js resolvePin) has no empty part. A PIN the gazetteer files under no district
(227 of them, district from the nearest PIN online) is stored in the pack with district "", so the label names the
state, as online (facts/places.py: "PIN 121999, Haryana")."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

OFFLINE_JS = Path(__file__).resolve().parents[1] / "static" / "offline.js"

PACK = {"state": "HARYANA", "districts": ["", "GURUGRAM"],
        "pins": {"pin": [121999, 122001], "lat": [28.4, 28.46], "lon": [77.3, 77.03], "d": [0, 1]}}

JS = ("require(process.argv[1]); const pack = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
      "console.log(JSON.stringify([121999, 122001].map(p => RSOffline.resolvePin(pack, p).label)));")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_guessed_district_pin_label_names_the_state_and_has_no_empty_part():
    out = subprocess.run(["node", "-e", JS, str(OFFLINE_JS)], input=json.dumps(PACK), capture_output=True,
                         text=True, check=True).stdout
    assert json.loads(out) == ["PIN 121999, Haryana", "PIN 122001, Gurugram"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_pin_label_with_no_district_and_no_state_is_the_pin_alone():
    pack = dict(PACK, state=None)
    out = subprocess.run(["node", "-e", JS, str(OFFLINE_JS)], input=json.dumps(pack), capture_output=True,
                         text=True, check=True).stdout
    assert json.loads(out)[0] == "PIN 121999"
