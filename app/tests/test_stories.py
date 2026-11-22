"""Data stories page (issue #53): build from viz/gallery.json, the two endpoints, and a check that
everything stories.js shows equals the built file (and so the gallery)."""
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))
import app as app_module  # noqa: E402
from app import app  # noqa: E402
from stories import build  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("stories")
    old_build, old_app = build.OUT, app_module.STORIES
    build.OUT = app_module.STORIES = out / "out"
    build.main()
    yield json.loads((out / "out" / "stories.json").read_text(encoding="utf-8"))
    build.OUT, app_module.STORIES = old_build, old_app


def test_build_copies_the_gallery_verbatim(built):
    gallery = json.loads((ROOT / "viz/gallery.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in gallery["stories"]}
    assert len(built["stories"]) == len(gallery["stories"]) > 0
    assert [s["order"] for s in built["stories"]] == sorted(s["order"] for s in built["stories"])
    for s in built["stories"]:
        g = by_id[s["id"]]
        for k in ("act", "theme", "headline", "presenter_line", "caveat", "verification"):
            assert s[k] == g[k], (s["id"], k)
        assert [c["alt_text"] for c in s["charts"]] == [c["alt_text"] for c in g["charts"]]
        assert [c["source"] for c in s["charts"]] == [c["svg"] for c in g["charts"]]
        assert s["charts"] and s["data_csv"]
        for c in s["data_csv"]:
            assert c["in_repo"] == (ROOT / c["path"]).is_file()
    assert built["acts"] == list(dict.fromkeys(s["act"] for s in built["stories"]))
    assert built["missing_data_files"] == [f"{s['id']}: {c['path']}" for s in built["stories"] for c in s["data_csv"]
                                           if not c["in_repo"]]


def test_as_list_reads_the_gallery_list_formats():
    assert build.as_list("['a.csv', 'b.csv']") == ["a.csv", "b.csv"]
    assert build.as_list(["a.csv"]) == ["a.csv"] and build.as_list("a.csv") == ["a.csv"] and build.as_list("") == []


def test_endpoints_serve_the_page_data_and_only_listed_charts(built):
    r = client.get("/api/stories")
    assert r.status_code == 200 and r.json()["stories"][0]["id"] == built["stories"][0]["id"]
    name = built["stories"][0]["charts"][0]["file"]
    c = client.get(f"/api/stories/chart/{name}")
    assert c.status_code == 200 and c.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in c.headers["content-security-policy"] and c.text.lstrip().startswith("<")
    for bad in ("nope.svg", "..%2Fstories.json", "stories.json", "%2e%2e%2f%2e%2e%2fapp.py"):
        assert client.get(f"/api/stories/chart/{bad}").status_code == 404
    assert client.get("/stories.js").status_code == 200
    assert "#/stories" in client.get("/app.js").text  # UI2: linked from the How it works tab


def test_page_data_missing_is_a_clear_503(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "STORIES", tmp_path / "nothing")
    r = client.get("/api/stories")
    assert r.status_code == 503 and "app/stories/build.py" in r.json()["error"]
    assert client.get("/api/stories/chart/x.svg").status_code == 404


def lookup(doc, path):
    cur = doc
    for part in path.split("."):
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_everything_the_page_shows_equals_the_built_file(built):
    js = ("const s = require(process.argv[1]); let d = ''; process.stdin.on('data', c => d += c);"
          "process.stdin.on('end', () => process.stdout.write(s.render(JSON.parse(d))));")
    page = subprocess.run(["node", "-e", js, str(APP / "static" / "stories.js")], input=json.dumps(built),
                          capture_output=True, text=True, check=True).stdout
    spans = re.findall(r'<span data-f="([^"]+)" data-k="text">(.*?)</span>', page, flags=re.S)
    alts = re.findall(r'<img [^>]*?alt="([^"]*)"[^>]*?data-f="([^"]+)" data-k="alt">', page, flags=re.S)
    assert spans and alts
    for path, shown in spans:
        assert html.unescape(shown) == str(lookup(built, path)), path
    for shown, path in alts:
        assert html.unescape(shown) == lookup(built, path), path
    shown_paths = {p for p, _ in spans} | {p for _, p in alts}
    for i, s in enumerate(built["stories"]):
        for k in ("headline", "presenter_line", "caveat", "verification", "theme"):
            assert f"stories.{i}.{k}" in shown_paths, (s["id"], k)
        assert all(f"stories.{i}.charts.{j}.alt_text" in shown_paths for j in range(len(s["charts"])))
        assert all(f"stories.{i}.data_csv.{j}.path" in shown_paths for j in range(len(s["data_csv"])))
    # a data file that is not in the repo is named but never linked
    for i, s in enumerate(built["stories"]):
        for c in s["data_csv"]:
            linked = f'href="{built["repo_url"]}{c["path"]}"' in page
            assert linked == c["in_repo"], c["path"]
    # the only digits outside marked text are chart counters ("Chart 1 of 2") and element ids
    stripped = re.sub(r'<span data-f=.*?</span>', "", page, flags=re.S)
    stripped = re.sub(r"<details class=\"small\"><summary>Describe this chart in words</summary>.*?</details>", "", stripped, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", stripped)
    leftovers = [m for m in re.findall(r"\d[\d,.]*", text)]
    counters = re.findall(r"Chart (\d+) of (\d+)", text)
    assert len(leftovers) == 2 * len(counters), sorted(set(leftovers))[:20]
