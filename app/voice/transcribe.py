"""Speech to text on the app server: faster-whisper "small", int8, 2 CPU threads (voice input).

Why on the server: the audio never leaves the Databricks App, and it works in any browser that can record.
Measured on synthetic macOS voices (app_design/feasibility/voice_language/out/asr_small.json): Hindi CER 0.13 to
0.21 with the language forced, English CER 0, about 0.5 x real time, about 2 GB peak RSS.

The language is the user's choice ("hi" or "en") and is always forced; auto-detect is never used (it doubled the
time per clip in the benchmark, and short Hindi clips can come back as Urdu script).

Privacy: the audio is decoded in memory and dropped after one call. Nothing here logs or stores the audio or the
transcript; the only log line is the exception type when the model fails to load.

The model loads lazily on the first request, in a background thread, so the app starts fast and a request never
blocks for more than LOAD_WAIT_S. Model files are cached under VOICE_MODEL_DIR (default: <tmp>/rs-whisper).
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
import os
import re
import tempfile
import threading
from typing import Any

log = logging.getLogger(__name__)

MODEL = "small"
SAMPLE_RATE = 16_000
MAX_SECONDS = 30
MAX_BYTES = 2_000_000
# A cold load from the local cache takes about 1 to 5 s; the first download (about 480 MB) takes longer, and the
# page then gets a "getting ready" answer instead of a hung request.
LOAD_WAIT_S = 20
# What MediaRecorder writes: Chrome and Android webm/opus, Firefox ogg/opus, Safari mp4/aac; wav for tools.
DATA_URL = re.compile(r"data:audio/(webm|ogg|mp4|wav|x-wav)(;codecs=[\w.]+)?;base64,", re.IGNORECASE)
KEYBOARD_HINT = "Use your keyboard's mic to speak."


class Rejected(Exception):
    """A request the endpoint answers with an error status and a message the page can show as is."""

    def __init__(self, status: int, message: str, code: str) -> None:
        super().__init__(message)
        self.status, self.message, self.code = status, message, code  # code: a key of errors.MESSAGES


_lock = threading.Lock()
_done = threading.Event()
_state: dict[str, Any] = {"status": "idle", "model": None}  # idle | loading | ready | failed


def _cache_dir() -> str:
    return os.environ.get("VOICE_MODEL_DIR") or os.path.join(tempfile.gettempdir(), "rs-whisper")


def _load() -> None:
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=2, download_root=_cache_dir())
        _state.update(model=model, status="ready")
    except Exception as e:  # missing package, no network for the first download, disk full
        _state["status"] = "failed"
        log.warning("speech model did not load: %s", type(e).__name__)
    finally:
        _done.set()


def start_loading() -> None:
    """Start the background load once; after a failure the next request tries again."""
    with _lock:
        if _state["status"] in ("idle", "failed"):
            _state["status"] = "loading"
            _done.clear()
            threading.Thread(target=_load, name="whisper-load", daemon=True).start()


def status() -> str:
    return _state["status"]


def _model() -> Any:
    start_loading()
    _done.wait(LOAD_WAIT_S)
    if _state["status"] == "ready":
        return _state["model"]
    if _state["status"] == "failed":
        raise Rejected(503, f"Voice input is not working on this server now. {KEYBOARD_HINT}", "voice_failed")
    raise Rejected(503, "Voice input is getting ready. Try again in a minute, or type.", "voice_loading")


def _decode(raw: bytes) -> Any:
    """Compressed audio bytes -> 16 kHz mono float32 samples, in memory (PyAV reads the BytesIO, no temp file)."""
    from faster_whisper import decode_audio

    return decode_audio(io.BytesIO(raw), sampling_rate=SAMPLE_RATE)


def _audio_bytes(data_url: str) -> bytes:
    m = DATA_URL.match(data_url)
    if not m:
        raise Rejected(415, "Send the recording as webm, ogg, mp4 or wav audio.", "voice_bad_type")
    b64 = data_url[m.end():]
    if len(b64) > (MAX_BYTES + 2) // 3 * 4:
        raise Rejected(413, "The recording is too big. Speak for up to 15 seconds.", "voice_too_big")
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise Rejected(415, "The recording could not be read. Try again.", "voice_unreadable") from None


def transcribe(data_url: str, lang: str) -> dict[str, Any]:
    """One recording -> {text, lang, seconds (audio length), model}. Raises Rejected (413, 415, 503)."""
    raw = _audio_bytes(data_url)
    model = _model()
    try:
        audio = _decode(raw)
    except Exception:  # bad container or codec; the bytes are not logged
        raise Rejected(415, "The recording could not be read. Try again.", "voice_unreadable") from None
    seconds = len(audio) / SAMPLE_RATE
    if seconds > MAX_SECONDS:
        raise Rejected(413, "The recording is too long. Speak for up to 15 seconds.", "voice_too_long")
    # temperature 0 only: the default fallback re-decodes at higher temperatures when the text repeats, which took
    # a 14 s Hindi clip from 3.5 s to 23 s and turned it into mixed-script garbage.
    # No vad_filter: on 4 s of pink noise it changed nothing (both empty) and cost about 200 MB more peak RSS.
    segments, _ = model.transcribe(audio, language=lang, beam_size=1, temperature=0.0,
                                   condition_on_previous_text=False)
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "lang": lang, "seconds": round(seconds, 1), "model": MODEL}
