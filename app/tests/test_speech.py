"""Spoken summaries (voice support): static/speech.js run under node on real and stub plan payloads.

Part of the faithfulness guarantee: every number and facility name the phone reads aloud equals its payload
field. buildSpeech returns the payload path of each value it used; this test resolves each path in the payload,
checks the value, checks it is in the spoken text, and fails on any digit that no field accounts for.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from stub_data import SERVICES, recommend_stub  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
JS = APP / "static" / "speech.js"
TEMPLATES = json.loads((APP / "static" / "speech_templates.json").read_text(encoding="utf-8"))
REAL_QUERIES = {"gaya_dialysis": ("dialysis", 24.79, 85.0),
                "maharashtra_csection": ("emergency_csection", 19.88, 75.34),
                "nh19_trauma_mohania": ("trauma_emergency", 25.15, 83.68)}
FIXED_NUMBERS = {"108", "102"}
ENGLISH_BAND = re.compile(r"likely|verified|call first|backup", re.I)
HARNESS = """
const fs = require('fs'), vm = require('vm');
const ctx = {}; ctx.globalThis = ctx;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const inp = JSON.parse(fs.readFileSync(0, 'utf8'));
ctx.RSSpeech.use(inp.templates);
process.stdout.write(JSON.stringify(inp.cases.map(c => ctx.RSSpeech.buildSpeech(c.plan, c.lang, c.opts))));
"""


def payloads() -> list[tuple[str, dict]]:
    out = []
    from facts.engine import Engine
    from itinerary import attach
    eng = Engine.load()
    if eng is not None:  # app/facts/out built (tools/deploy/deploy.sh order)
        for name, (svc, lat, lon) in REAL_QUERIES.items():
            out.append((f"real-{name}", attach(eng.plan(svc, lat, lon, 40, "gps"), eng)))
    out += [(f"stub-{s}", recommend_stub(s, 26.6, 85.48, 40, "gps")) for s in sorted(SERVICES)]
    return out


PAYLOADS = payloads()


def build(cases: list[dict]) -> list[dict]:
    res = subprocess.run(["node", "-e", HARNESS, str(JS)], input=json.dumps({"templates": TEMPLATES, "cases": cases}),
                         capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


SPOKEN = {(n, lang): r for (n, lang), r in zip(
    [(n, lang) for n, _ in PAYLOADS for lang in ("hi", "en")],
    build([{"plan": p, "lang": lang, "opts": {}} for _, p in PAYLOADS for lang in ("hi", "en")]))}


def resolve(doc, path: str):
    for k in path.split("."):
        doc = doc[int(k)] if isinstance(doc, list) else doc[k]
    return doc


def num_str(v) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def template_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from template_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from template_strings(v)


CASES = [(n, p, lang) for n, p in PAYLOADS for lang in ("hi", "en")]


def check_spoken(plan: dict, r: dict, lang: str) -> None:
    """Every field resolves to its payload value and is in the text; no digit the fields do not account for."""
    text, fields, L = r["text"], r["fields"], TEMPLATES[lang]
    assert text.strip(), "nothing to say"
    rest = text
    for f in sorted(fields, key=lambda f: -len(str(f["value"]))):
        src = resolve(plan, f["path"])
        if f["kind"] == "num":
            assert float(src) == float(f["value"]), f
            assert num_str(f["value"]) in text, f
        elif f["kind"] == "part":
            assert f["value"] in src and f["value"] in text, f
        else:
            assert src == f["value"], f
        if f["kind"] in ("text", "part"):
            assert f["value"] in text, f
            rest = rest.replace(f["value"], " ")
        if f["kind"] == "enum":
            word = {**L["band"], **L["purpose"]}[f["value"]]
            assert word in text, f
    # No digit the payload fields do not account for; 108 and 102 are the only fixed numbers (test_templates).
    allowed = {num_str(f["value"]) for f in fields if f["kind"] == "num"} | FIXED_NUMBERS
    stray = [d for d in re.findall(r"\d+", rest) if d not in allowed]
    assert not stray, (stray, text)
    # No template slot left empty or unfilled.
    assert not re.search(r"[{}]|undefined|null|NaN|\[object", text), text


@pytest.mark.parametrize("name, plan, lang", CASES, ids=[f"{n}-{lang}" for n, _, lang in CASES])
def test_every_spoken_value_equals_its_payload_field(name, plan, lang):
    r = SPOKEN[(name, lang)]
    text, fields = r["text"], r["fields"]
    check_spoken(plan, r, lang)
    # Facility names: the first two options and every stop of a multi-stop route, verbatim.
    paths = {f["path"] for f in fields}
    names = [(f"options.{i}.name", o["name"]) for i, o in enumerate(plan["options"][:2])]
    route = (plan.get("itinerary") or {}).get("plans") or []
    if route and len(route[0]["stops"]) > 1:
        names += [(f"itinerary.plans.0.stops.{k}.name", s["name"]) for k, s in enumerate(route[0]["stops"])]
    for path, n in names:
        assert path in paths and n in text, (path, n)


def test_one_option_speech():
    """The why / call-ahead page speaks one option (opts.only): its own name, reason and questions, nothing else."""
    cases = [(n, p, lang, i) for n, p in PAYLOADS for i in range(len(p["options"])) for lang in ("hi", "en")]
    out = build([{"plan": p, "lang": lang, "opts": {"only": i}} for _, p, lang, i in cases])
    assert cases
    for (n, p, lang, i), r in zip(cases, out):
        check_spoken(p, r, lang)
        o, paths = p["options"][i], {f["path"] for f in r["fields"]}
        assert f"options.{i}.name" in paths and o["name"] in r["text"], (n, i)
        assert all(x.startswith((f"options.{i}.", "emergency_numbers.", "abstain.", "query."))
                   for x in paths), (n, i, paths)
        assert len(o["call_ahead"]) == sum(".call_ahead." in x for x in paths) or not o["call_ahead"], (n, i)


@pytest.mark.parametrize("name, plan", PAYLOADS, ids=[n for n, _ in PAYLOADS])
def test_hindi_speech_is_hindi(name, plan):
    r = SPOKEN[(name, "hi")]
    assert re.search(r"[ऀ-ॿ]", r["text"])
    rest = r["text"]
    for f in r["fields"]:
        if f["kind"] in ("text", "part"):
            rest = rest.replace(str(f["value"]), " ")
    assert not ENGLISH_BAND.search(rest), rest
    # Every call-ahead question matched a Hindi template (no English question read out verbatim).
    assert not [f for f in r["fields"] if ".call_ahead." in f["path"] and f["kind"] == "text"], r["fields"]


def test_templates():
    hi, en = TEMPLATES["hi"], TEMPLATES["en"]
    assert set(hi) == set(en)
    assert {d for t in template_strings([hi, en]) for d in re.findall(r"\d+", t)} <= FIXED_NUMBERS
    for k, v in hi.items():
        if isinstance(v, str):
            assert set(re.findall(r"\{(\w+)\}", v)) <= set(re.findall(r"\{(\w+)\}", en[k])), k
    for en_q, hi_q in hi["questions"]:
        assert set(re.findall(r"\{(\w+)\}", hi_q)) == set(re.findall(r"\{(\w+)\}", en_q)), en_q
    hindi_side = [t for k, v in hi.items() if k != "questions" for t in template_strings(v)]
    hindi_side += [q for _, q in hi["questions"]]
    assert not [t for t in hindi_side if ENGLISH_BAND.search(t)]
    assert hi["band"] == {"likely": "संभावना ज़्यादा", "not_verified": "पक्का नहीं, पहले फ़ोन करके पूछें", "unlikely": "संभावना कम"}


def test_danger_and_route():
    cs = recommend_stub("emergency_csection", 26.6, 85.48, 40, "gps")
    dia = recommend_stub("dialysis", 26.6, 85.48, 40, "gps")
    out = build([{"plan": cs, "lang": "hi", "opts": {}}, {"plan": dia, "lang": "hi", "opts": {}},
                 {"plan": dia, "lang": "en", "opts": {"danger": True}}])
    assert "108" in out[0]["text"] and "102" in out[0]["text"]
    assert "108" not in out[1]["text"], "no danger line for a scheduled service without a danger sign"
    assert out[2]["text"].startswith("Call 108 now.")
    routed = [(n, p) for n, p in PAYLOADS if (p.get("itinerary") or {}).get("plans")
              and len(p["itinerary"]["plans"][0]["stops"]) > 1]
    for n, p in routed:
        s = p["itinerary"]["plans"][0]["stops"]
        hi = SPOKEN[(n, "hi")]["text"]
        assert f"पहले {s[0]['name']} पर" in hi and f"फिर {s[1]['name']} पर" in hi, hi
