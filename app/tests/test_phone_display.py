"""Phone display (#140 WS3 3b): national format from phonenumbers at build time, e164 unchanged for dialling.

phonenumbers is a build-time tool, not an app dependency, so the format test skips where it is not installed. Run it:
    uv run --no-project --with pytest --with pandas --with pyarrow --with phonenumbers python -m pytest \
        app/tests/test_phone_display.py -q
The expected strings are phonenumbers 9.0.44's own NATIONAL output (a mobile without the trunk 0), not hand-typed.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facts.build import e164, load_phonenumbers, phone_display

STATIC = Path(__file__).resolve().parents[1] / "static"

CASES = [
    ("5222300025", "0522 230 0025", "+915222300025"),  # landline, Lucknow
    ("3532527722", "0353 252 7722", "+913532527722"),  # landline, Siliguri
    ("6212230333", "0621 223 0333", "+916212230333"),  # landline that starts like a mobile (6), Muzaffarpur
    ("6452239202", "06452 239 202", "+916452239202"),  # landline, five-digit STD code
    ("9470003549", "94700 03549", "+919470003549"),  # mobile
    ("+91 94700 03549", "94700 03549", "+919470003549"),
    ("06212230333", "0621 223 0333", "+916212230333"),
    ("1800 180 1104", "1800 180 1104", "18001801104"),  # toll-free: shown as listed, dialled as is
]


@pytest.mark.parametrize("raw,shown,dial", CASES)
def test_national_format(raw, shown, dial):
    pn = pytest.importorskip("phonenumbers")
    assert phone_display(raw, pn) == shown
    assert e164(raw) == dial  # the dialled number does not change


@pytest.mark.parametrize("raw", ["5222300025", "9470003549", "1800 180 1104", "12345", ""])
def test_without_phonenumbers_the_listing_spelling_is_kept(raw):
    assert phone_display(raw, None) == raw


def test_invalid_number_is_kept_as_listed():
    pn = pytest.importorskip("phonenumbers")
    assert phone_display("12345", pn) == "12345"


def test_phonenumbers_is_not_an_app_dependency():
    req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text().lower()
    assert "phonenumbers" not in req
    assert load_phonenumbers() is None or load_phonenumbers().__name__ == "phonenumbers"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_offline_tel_href_dials_the_shown_string():
    """offline.js telHref (fixed earlier for 1800 numbers) turns every shown string into its e164 tel: link."""
    js = ("require(process.argv[1]); const t = globalThis.RSOffline.telHref;"
          "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(t)))")
    shown = [s for _, s, _ in CASES]
    out = subprocess.run(["node", "-e", js, str(STATIC / "offline.js"), json.dumps(shown)],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["tel:" + d for _, _, d in CASES]
