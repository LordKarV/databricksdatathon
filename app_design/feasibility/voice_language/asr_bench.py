"""CPU speech-to-text benchmark with faster-whisper, pinned to 2 threads to mimic the 2 vCPU app.

Audio is synthetic: macOS `say` voices reading test inputs (generated here, no third-party audio).
Clean TTS speech is an optimistic case; real phone audio with noise will score worse.
Usage: .venv-voice/bin/python asr_bench.py <model> [<model> ...]   (e.g. base small)
Writes out/asr_<model>.json.
"""
import json
import resource
import subprocess
import sys
import time
import unicodedata
import wave
from pathlib import Path

from faster_whisper import WhisperModel

from inputs import CASES, HARD

HERE = Path(__file__).parent
AUDIO = HERE / "audio"
OUT = HERE / "out"
# (case id, macOS voice, whisper language code)
CLIPS = [("E1", "Rishi", "en"), ("H1", "Lekha", "hi"), ("H2", "Lekha", "hi"), ("H6", "Lekha", "hi"),
         ("H7", "Lekha", "hi"), ("G1", "Lekha", "hi"), ("X5", "Piya", "bn"), ("X6", "Vani", "ta")]
TEXT = {c[0]: c[2] for c in CASES + HARD}


def synth(cid: str, voice: str) -> Path:
    wav = AUDIO / f"{cid}.wav"
    if not wav.exists():
        AUDIO.mkdir(exist_ok=True)
        subprocess.run(["say", "-v", voice, "--data-format=LEI16@16000", "-o", str(wav), TEXT[cid]], check=True)
    return wav


def duration(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def norm(s: str) -> str:
    # Keep letters, combining marks (Indic vowel signs are category M) and digits; drop punctuation.
    s = unicodedata.normalize("NFC", s).lower()
    return " ".join("".join(ch for ch in s if unicodedata.category(ch)[0] in "LMN" or ch.isspace()).split())


def cer(ref: str, hyp: str) -> float:
    """Character error rate: Levenshtein distance / reference length, on normalised text."""
    r, h = norm(ref), norm(hyp)
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i]
        for j, hc in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / max(len(r), 1)


def bench(model_name: str) -> dict:
    t0 = time.perf_counter()
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=2)
    load_s = time.perf_counter() - t0
    rows = []
    for cid, voice, lang in CLIPS:
        wav = synth(cid, voice)
        for forced in (lang, None):
            t0 = time.perf_counter()
            segs, info = model.transcribe(str(wav), language=forced, beam_size=1)
            hyp = " ".join(s.text.strip() for s in segs)
            secs = time.perf_counter() - t0
            rows.append({"id": cid, "lang": lang, "forced_lang": forced, "detected": info.language,
                         "audio_s": round(duration(wav), 2), "transcribe_s": round(secs, 2),
                         "rtf": round(secs / duration(wav), 2), "cer": round(cer(TEXT[cid], hyp), 3),
                         "ref": TEXT[cid], "hyp": hyp})
            print(model_name, cid, forced, info.language, rows[-1]["transcribe_s"], "s cer", rows[-1]["cer"], hyp)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # bytes on macOS
    return {"model": model_name, "compute_type": "int8", "cpu_threads": 2, "load_s": round(load_s, 1),
            "peak_rss_mb": round(peak_mb), "rows": rows}


if __name__ == "__main__":
    assert cer("abc", "abc") == 0 and cer("abc", "abd") == 1 / 3
    OUT.mkdir(exist_ok=True)
    for m in sys.argv[1:]:
        (OUT / f"asr_{m.replace('/', '_')}.json").write_text(json.dumps(bench(m), ensure_ascii=False, indent=1))
