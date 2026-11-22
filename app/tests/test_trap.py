"""DEMO-TRAP-1 (#140): the How page card "One record, two answers" (app/howto/trap.py, static/trap.js).

- the card's data equals the raw ai_query re-run and the record's source sentences in derived/v1/claims.parquet;
- the Saathi side equals the engine's own why-not row for that facility_id at the demo place;
- trap.js shows those values, in English and Hindi, and shows nothing when the data is absent;
- with no raw file there is no "trap" key, so the hook never loads trap.js.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))
from howto import trap  # noqa: E402
from services import SERVICES  # noqa: E402

import app as app_module  # noqa: E402

ENGINE = app_module._engine()
CLAIMS = ROOT / "derived/v1/claims.parquet"
pytestmark = pytest.mark.skipif(ENGINE is None or not CLAIMS.is_file() or not (ROOT / trap.RAW).is_file(),
                                reason="facility data, claims or the re-run file not available")
RENDER = """
const vm = require('node:vm'), fs = require('node:fs');
const [, js, en, hi] = process.argv;
const I = {en: JSON.parse(en), hi: JSON.parse(hi)}, map = I.hi.engine;
// app.js engHi for template-free sentences: the whole sentence, else clause by clause on "; "
const one = s => map[s] ?? null;
const rsEngHi = s => one(s) ?? (s.includes('; ') && s.split('; ').every((c, i) => one(i ? c[0].toUpperCase() + c.slice(1) : c))
  ? s.split('; ').map((c, i) => one(i ? c[0].toUpperCase() + c.slice(1) : c)).join('; ') : null);
const ctx = {rsEngHi};
ctx.globalThis = ctx;
vm.runInNewContext(fs.readFileSync(js, 'utf8'), ctx);
const t = JSON.parse(fs.readFileSync(0, 'utf8'));
const render = l => { ctx.th = k => I[l][k]; return ctx.RSTrap.html(t, l, rsEngHi, t.repo_url); };
process.stdout.write(JSON.stringify({en: render('en'), hi: render('hi'), none: ctx.RSTrap.html(undefined, 'en'),
  empty: ctx.RSTrap.html({}, 'hi')}));
"""


@pytest.fixture(scope="module")
def claims() -> pd.DataFrame:
    return pd.read_parquet(CLAIMS, columns=["unique_id", "field", "text", "services"])


@pytest.fixture(scope="module")
def card(claims) -> dict:
    c = trap.build(ROOT, ENGINE, claims, SERVICES)
    assert c is not None, "the engine no longer passes over a re-run record at the demo place"
    return c


def text(h: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", h))).strip()


def test_left_side_equals_raw_rerun_and_record(card, claims):
    raw = json.loads((ROOT / trap.RAW).read_text())
    row = next(r for r in raw["rows"] if r["unique_id"] == card["unique_id"])
    assert (card["model"], card["ran_at_utc"], card["name"], card["city"]) == (
        raw["model"], raw["ran_at_utc"], row["name"], row["address_city"])
    assert card["ran_on"] == raw["ran_at_utc"][:10]
    v = card["verdict"]
    assert (v["value"], v["confidence"], v["quote"]) == (
        row["verdict"]["offers_dialysis"], row["verdict"]["confidence"], row["verdict"]["evidence_quote"])
    mine = claims[claims.unique_id == card["unique_id"]]
    # the model's quote is the record's own sentence, verbatim, in the field the card names (not procedure)
    assert set(mine[mine.text == v["quote"]].field) == {v["quote_field"]}
    assert v["quote"] not in row["procedure"]
    # the procedure sentence is in the raw row the model was given and in the record's claims, verbatim
    assert card["own"]["text"] in row["procedure"]
    assert ((mine.field == card["own"]["field"]) & (mine.text == card["own"]["text"])).sum() == 1
    assert (ROOT / card["query_file"]).is_file()


def test_saathi_side_equals_engine_why_not(card):
    p = trap.PLACE
    plan = ENGINE.plan(p["service"], p["lat"], p["lon"], None, "gps")
    w = next(w for w in plan["why_not"] if w["facility_id"] == card["unique_id"])
    s = card["saathi"]
    assert w["option_rank"] is None and card["unique_id"] not in {o["facility_id"] for o in plan["options"]}
    assert (s["facility_id"], s["reason"], s["reason_code"], s["minutes"], s["option_rank"]) == (
        w["facility_id"], w["reason"], w["reason_code"], w["travel"]["minutes"], w["option_rank"])
    assert s["reason_code"] == "location"
    assert s["band"] == w["band"] == ENGINE.score(card["unique_id"], p["service"])[0]  # its own band, e.g. Likely
    i = ENGINE.fid[card["unique_id"]]
    from facts.engine import WHERE
    assert s["where"] == WHERE[ENGINE.fac["loc_rule"][i]] and s["city"] == ENGINE.fac["city"][i]
    ev = ENGINE.score(card["unique_id"], p["service"])[5]
    assert [(q["field"], q["text"]) for q in s["quotes"]] == [tuple(ENGINE.claims[c][:2]) for c in ev]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_card_shows_the_data_in_both_languages(card):
    i18n = {lang: json.loads((APP / f"static/i18n/{lang}.json").read_text()) for lang in ("en", "hi")}
    hi_map = i18n["hi"]["engine"]
    card = {**card, "repo_url": "https://example.invalid/"}
    args = [json.dumps(i18n["en"]), json.dumps(i18n["hi"])]
    out = json.loads(subprocess.run(["node", "-e", RENDER, str(APP / "static/trap.js"), *args],
                                    input=json.dumps(card), capture_output=True, text=True, check=True).stdout)
    assert out["none"] == "" and out["empty"] == ""
    s = card["saathi"]
    for lang in ("en", "hi"):
        t = text(out[lang])
        for v in (card["unique_id"], card["name"], card["model_name"], card["query_file"], card["verdict"]["quote"],
                  card["verdict"]["quote_field"], card["own"]["text"], card["own"]["field"], s["city"], s["place"]["name"],
                  card["verdict"]["key"], card["verdict"]["value"], str(card["verdict"]["confidence"]), card["source"]):
            assert v in t, (lang, v)
        assert all(q["text"] in t for q in s["quotes"])
        assert f'data-trap="{card["unique_id"]}"' in out[lang]
        assert i18n[lang][f"band.{s['band']}"] in t and card["ran_on_label"][lang] in t
    en = text(out["en"])
    assert s["reason"] in en and s["where"] in en and card["ran_on_label"]["en"] == "22 Nov 2026"
    hi = text(out["hi"])
    # the engine's sentences in Hindi come from the reviewed templates, clause by clause
    for sentence in (s["reason"], s["where"]):
        assert (hi_map.get(sentence) or "; ".join(hi_map[c[0].upper() + c[1:]] for c in sentence.split("; "))) in hi


def test_no_raw_file_no_card(tmp_path, claims):
    assert trap.build(tmp_path, ENGINE, claims, SERVICES) is None


def test_hook_needs_the_trap_key_and_trap_js_is_lazy():
    js = (APP / "static/app.js").read_text()
    assert "h.trap && loadScript('/trap.js', 'RSTrap')" in js
    from fastapi.testclient import TestClient
    c = TestClient(app_module.app)
    assert c.get("/trap.js").status_code == 200
    assert "trap.js" not in c.get("/").text
    assert "'/trap.js'" in (APP / "static/sw.js").read_text()
