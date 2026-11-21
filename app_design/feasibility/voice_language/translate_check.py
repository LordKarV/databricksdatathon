"""Translate one recommendation explanation into Hindi and Marathi, then check automatically that
numbers, the facility name and quoted evidence survive verbatim.

Usage: python translate_check.py <endpoint> <hi|mr> [--placeholders]
--placeholders swaps every protected span for a token like [[P3]] before translation and restores
it after, so the model never sees (and cannot alter) the protected text.
Output: out/translate_<endpoint>_<lang>[_ph].json
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(__file__).parent / "out"

# Facility name and quotes are real dataset text (facilities.parquet); distance, minutes and
# probabilities are illustrative fixture values, not model output.
FACILITY = "NKP Salve Institute of Medical Sciences and Research Centre, Nagpur"
QUOTES = [
    "Has 17 dialysis machines currently",
    "Procedure performed free of cost under Ayushman Bharat and Mahatma Jyotiba Phule Jan Aarogya Yojana",
    "Plans to increase dialysis capacity to 27 units",
]
EXPLANATION = (
    f"Best option for dialysis: {FACILITY}. It is 7.4 km away, about 22 minutes by road. "
    f"Chance you will be treated when you arrive: 0.81 (likely range 0.70 to 0.89). "
    f"Why: the hospital's own text says \"{QUOTES[0]}\" and \"{QUOTES[1]}\". "
    f"Caution: \"{QUOTES[2]}\" is a future plan, so we did not count it. "
    f"For 3 sessions a week, travel adds about 132 minutes per week. "
    f"Backup: if they cannot take you, option 2 is 12.9 km away with a 0.64 chance."
)
LANG = {"hi": "Hindi", "mr": "Marathi"}
NUM = re.compile(r"\d+(?:\.\d+)?")
INDIC_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def protected() -> list[str]:
    # Longest first so the facility name is replaced before any number inside a quote.
    return sorted({FACILITY, *QUOTES}, key=len, reverse=True)


def prompt(lang: str, text: str, ph: bool) -> str:
    keep = ("Keep every token of the form [[P0]], [[P1]] ... exactly as is." if ph else
            "Keep the facility name in English exactly as written. Keep every text inside double "
            "quotes exactly as written, in English, inside the quotes. Keep all numbers as Western "
            "digits exactly as written.")
    return (f"Translate the following patient-facing message into simple {LANG[lang]} that a family "
            f"member can understand. {keep} Output only the translation.\n\n{text}")


def call(endpoint: str, content: str) -> tuple[str, float]:
    body = {"messages": [{"role": "user", "content": content}], "temperature": 0, "max_tokens": 900}
    t0 = time.perf_counter()
    p = subprocess.run(["databricks", "api", "post", f"/serving-endpoints/{endpoint}/invocations",
                        "--json", json.dumps(body, ensure_ascii=False)], capture_output=True, text=True,
                       env={**os.environ, "DATABRICKS_CONFIG_PROFILE": "vf"})
    ms = (time.perf_counter() - t0) * 1000
    if p.returncode != 0:
        raise SystemExit(f"call failed: {(p.stderr or p.stdout)[-500:]}")
    return json.loads(p.stdout)["choices"][0]["message"]["content"], ms


def check(src: str, out: str) -> dict:
    """Facility name and each quote must appear verbatim; the multiset of numbers must match
    (strict = Western digits as written; normalised = Devanagari digits mapped to Western)."""
    src_nums = sorted(NUM.findall(src))
    strict = sorted(NUM.findall(out))
    norm = sorted(NUM.findall(out.translate(INDIC_DIGITS)))
    spans = {s: s in out for s in [FACILITY, *QUOTES]}
    return {"spans_verbatim": spans, "all_spans_ok": all(spans.values()),
            "numbers_expected": src_nums, "numbers_strict": strict, "numbers_ok_strict": strict == src_nums,
            "numbers_ok_normalised": norm == src_nums,
            "missing_numbers": sorted(set(src_nums) - set(norm)), "extra_numbers": sorted(set(norm) - set(src_nums))}


def main() -> None:
    endpoint, lang, ph = sys.argv[1], sys.argv[2], "--placeholders" in sys.argv
    text, table = EXPLANATION, {}
    if ph:
        for i, span in enumerate(protected()):
            table[f"[[P{i}]]"] = span
            text = text.replace(span, f"[[P{i}]]")
        for n in sorted(set(NUM.findall(text)), key=len, reverse=True):
            key = f"[[P{len(table)}]]"
            table[key] = n
            text = re.sub(rf"(?<![\d.P]){re.escape(n)}(?![\d.]|\]\])", key, text)
    raw, ms = call(endpoint, prompt(lang, text, ph))
    final = raw
    for key, span in table.items():
        final = final.replace(key, span)
    res = {"endpoint": endpoint, "lang": lang, "placeholders": ph, "ms": round(ms), "source": EXPLANATION,
           "sent": text, "raw": raw, "final": final, "unrestored_tokens": re.findall(r"\[\[P\d+\]\]", final),
           "check": check(EXPLANATION, final)}
    OUT.mkdir(exist_ok=True)
    name = f"translate_{endpoint}_{lang}{'_ph' if ph else ''}.json"
    (OUT / name).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: res[k] for k in ("endpoint", "lang", "placeholders", "ms")} | res["check"], ensure_ascii=False))


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        assert check(EXPLANATION, EXPLANATION)["all_spans_ok"] and check(EXPLANATION, EXPLANATION)["numbers_ok_strict"]
        bad = check(EXPLANATION, EXPLANATION.replace("7.4", "७.४").replace("17 dialysis", "17 डायलिसिस"))
        assert bad["numbers_ok_normalised"] and not bad["numbers_ok_strict"] and not bad["all_spans_ok"]
        print("selftest ok")
    else:
        main()
