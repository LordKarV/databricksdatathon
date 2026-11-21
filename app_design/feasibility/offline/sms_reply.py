"""SMS query/reply format, answered from the prototype pack alone (no Databricks call needed).

Query: "<SERVICE WORD> <PIN>", e.g. "DIALYSIS 842001", "CSEC 800001", "BURN 846004".
Reply: the 3 facilities with phone and one quote, plus the snapshot date, in GSM-7 English.
Counts SMS segments (GSM-7: 160 chars single, 153 per part; UCS-2 for Hindi: 70 / 67).
Run: ../../../.venv-offline/bin/python sms_reply.py
"""
import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
WORDS = {"DIALYSIS": "dialysis", "CSEC": "emergency_csection", "CSECTION": "emergency_csection", "NICU": "nicu",
         "HEART": "cardiac_surgery", "CARDIAC": "cardiac_surgery", "MRI": "mri", "BURN": "burn_care",
         "TRAUMA": "trauma_emergency", "ACCIDENT": "trauma_emergency"}


def reply(text: str, pack: dict) -> str:
    parts = text.upper().split()
    svc = next((WORDS[p] for p in parts if p in WORDS), None)
    pin = next((p for p in parts if p.isdigit() and len(p) == 6), None)
    if not svc or not pin:
        return "Send: SERVICE PIN. Services: DIALYSIS CSEC NICU HEART MRI BURN TRAUMA. Example: DIALYSIS 842001"
    if pin not in pack["index"]:
        return f"PIN {pin} is not in this pack (Bihar only). Send another PIN."
    lines = [f"{svc.replace('_', ' ')} near {pin}, data {pack['snapshot']}. Call before going:"]
    for n, i in enumerate(pack["index"][pin][svc], 1):
        name, phones = pack["facilities"][i][:2]
        conf, q1 = pack["evidence"][f"{i}|{svc}"][:2]
        conf_txt = "?" if conf is None else f"{round(conf * 100)}%"
        lines.append(f"{n}) {name[:40]} {phones[0] if phones else 'no phone'} conf {conf_txt} \"{q1[0][:40]}\"")
    return "\n".join(lines)


def segments(s: str) -> int:
    gsm = all(ord(c) < 128 for c in s)  # ponytail: ASCII as a GSM-7 proxy; ignores the few non-GSM ASCII chars
    single, multi = (160, 153) if gsm else (70, 67)
    return 1 if len(s) <= single else math.ceil(len(s) / multi)


if __name__ == "__main__":
    pack = json.loads((OUT / "pack_bihar_pin_norm.json").read_text())
    res = {}
    for q in ["DIALYSIS 842001", "csec 800001", "BURN 846004", "help", "MRI 110001"]:
        r = reply(q, pack)
        res[q] = {"reply": r, "chars": len(r), "segments": segments(r)}
    hindi_line = "डायलिसिस 842001 के पास, डेटा 2026-11-21. जाने से पहले फ़ोन करें:"  # header alone, for UCS-2 cost
    res["hindi_header_only"] = {"chars": len(hindi_line), "segments": segments(hindi_line)}
    (OUT / "sms_reply_samples.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    assert "1)" in res["DIALYSIS 842001"]["reply"] and "not in this pack" in res["MRI 110001"]["reply"]
    print("ASSERTIONS PASSED")
