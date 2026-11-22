"""POST /api/transcribe (voice input). The model is faked unless faster-whisper and its "small" files are present.

Run from the repo root: pytest app/tests/test_voice.py -q
The real-model test runs only when faster_whisper is importable and VOICE_MODEL_DIR (or the default cache) already
holds the model; it never downloads.
"""
import base64
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice import transcribe as v

from app import app

client = TestClient(app)
AUDIO = Path(__file__).resolve().parents[2] / "app_design" / "feasibility" / "voice_language" / "audio"
WEBM = "data:audio/webm;codecs=opus;base64," + base64.b64encode(b"\x1aE\xdf\xa3fake").decode()


class FakeModel:
    def __init__(self, text="mere papa ko dialysis"):
        self.text, self.calls = text, []

    def transcribe(self, audio, **kw):
        self.calls.append(kw)
        return iter([type("Seg", (), {"text": f" {self.text} "})()]), None


@pytest.fixture
def ready(monkeypatch):
    """A loaded fake model and a decoder that returns 3 s of silence."""
    m = FakeModel()
    monkeypatch.setitem(v._state, "status", "ready")
    monkeypatch.setitem(v._state, "model", m)
    monkeypatch.setattr(v, "_decode", lambda raw: [0.0] * (3 * v.SAMPLE_RATE))
    v._done.set()
    return m


def post(audio=WEBM, lang="hi"):
    return client.post("/api/transcribe", json={"audio": audio, "lang": lang})


def test_transcribes_with_forced_language_and_greedy_decoding(ready):
    r = post(lang="hi")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.json() == {"text": "mere papa ko dialysis", "lang": "hi", "seconds": 3.0, "model": "small"}
    assert ready.calls[0]["language"] == "hi" and ready.calls[0]["beam_size"] == 1
    assert ready.calls[0]["temperature"] == 0.0  # no fallback re-decodes: they cost 6x on a repeating clip


@pytest.mark.parametrize("audio", [
    "data:audio/flac;base64,AAAA", "data:image/png;base64,AAAA", "data:audio/webm,AAAA", "AAAA",
    "data:audio/webm;base64,not base64!",
])
def test_rejects_other_media_types_with_415(ready, audio):
    r = post(audio=audio)
    assert r.status_code == 415 and r.headers["cache-control"] == "no-store"
    assert r.json()["error"]


def test_rejects_more_than_2_mb_with_413(ready):
    big = "data:audio/wav;base64," + base64.b64encode(b"\0" * (v.MAX_BYTES + 3)).decode()
    assert post(audio=big).status_code == 413


def test_rejects_more_than_30_seconds_with_413(ready, monkeypatch):
    monkeypatch.setattr(v, "_decode", lambda raw: [0.0] * (31 * v.SAMPLE_RATE))
    assert post().status_code == 413


def test_undecodable_audio_is_415(ready, monkeypatch):
    def bad(raw):
        raise ValueError("not audio")
    monkeypatch.setattr(v, "_decode", bad)
    assert post().status_code == 415


@pytest.mark.parametrize("body", [{"audio": WEBM, "lang": "auto"}, {"audio": WEBM}, {"audio": WEBM, "lang": "hi", "x": 1}])
def test_language_must_be_chosen_hi_or_en(ready, body):
    assert client.post("/api/transcribe", json=body).status_code == 422


def test_still_loading_is_a_friendly_503_not_a_hang(monkeypatch):
    monkeypatch.setitem(v._state, "status", "loading")
    monkeypatch.setattr(v, "start_loading", lambda: None)
    monkeypatch.setattr(v, "LOAD_WAIT_S", 0)
    v._done.clear()
    r = post()
    assert r.status_code == 503 and "getting ready" in r.json()["error"]
    assert r.headers["cache-control"] == "no-store"



def test_ping_does_not_load_the_model():
    before = v.status()
    assert client.get("/api/ping").json() == {"ok": True}
    assert v.status() == before


WRITE_EVENTS = {"os.mkdir", "os.rename", "os.remove", "os.rmdir", "shutil.copyfile", "shutil.move",
                "tempfile.mkstemp", "tempfile.mkdtemp", "os.truncate"}
_watch: list = []


def _hook(event, args):
    if not _watch:
        return
    if event in WRITE_EVENTS:
        _watch[0].append((event, args[0] if args else None))
    elif event == "open":
        mode, flags = args[1], args[2] if len(args) > 2 else 0
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            _watch[0].append((event, args[0]))


sys.addaudithook(_hook)  # audit hooks cannot be removed; it records only while _watch is set


def _writes_during(fn):
    found = []
    _watch.append(found)
    try:
        r = fn()
    finally:
        _watch.clear()
    return r, found


def test_endpoint_never_writes_files(ready):
    r, writes = _writes_during(post)
    assert r.status_code == 200
    assert writes == []


def _real_model_cached() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    root = Path(os.environ.get("VOICE_MODEL_DIR") or v._cache_dir())
    return (root / "models--Systran--faster-whisper-small").is_dir()


@pytest.mark.skipif(not _real_model_cached(), reason="faster-whisper or its small model is not on this machine")
def test_real_model_on_a_wav_writes_nothing(monkeypatch):
    monkeypatch.setitem(v._state, "status", "idle")
    v.start_loading()
    v._done.wait(120)
    assert v.status() == "ready"
    wav = "data:audio/wav;base64," + base64.b64encode((AUDIO / "E1.wav").read_bytes()).decode()
    assert post(audio=wav, lang="en").status_code == 200  # warm-up: first imports of av submodules write __pycache__
    r, writes = _writes_during(lambda: post(audio=wav, lang="en"))
    assert r.status_code == 200, r.text
    assert "dialysis" in r.json()["text"].lower()
    assert writes == []
