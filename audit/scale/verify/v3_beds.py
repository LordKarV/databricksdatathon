"""V3: S3 and S4. Independent bed-total extraction (different design from the finder's beds_text.py).

Design: a claim yields a facility total only for explicit facility phrasings
("N-bed(ded) hospital/facility/...", "has N beds", "bed capacity of N", "bed strength of N",
"capacity of N beds", "N beds" when the claim mentions no unit word anywhere). Any unit word
anywhere in the claim disqualifies the loose "N beds" form, which is stricter than the finder.
"""
import json, re
from v_common import con

NUM = r"(\d{1,3}(?:,\d{3})+|\d+)"
STRONG = [
    re.compile(NUM + r"\s*[- ]?\s*bed(?:ded)?\s+(?:multi|super|tertiary|general|teaching|hospital|facility|nursing home|healthcare|health care|medical|charitable|private|government|district)", re.I),
    re.compile(r"\b(?:has|with|having|offers|houses|equipped with)\s+(?:a total of\s+|over\s+|more than\s+|around\s+|about\s+)?" + NUM + r"\s+(?:inpatient\s+)?beds\b(?!\s+(?:in|for|at)\b)", re.I),
    re.compile(r"\bbed (?:capacity|strength) (?:of\s+)?(?:is\s+)?" + NUM, re.I),
    re.compile(r"\bcapacity of\s+" + NUM + r"\s+beds", re.I),
    re.compile(r"\btotal (?:of\s+)?" + NUM + r"\s+beds", re.I),
]
UNIT = re.compile(r"\b(icu|nicu|picu|iccu|ccu|hdu|intensive|critical|dialysis|ward|unit|department|emergency|casualty|labou?r|maternity|room|burns?|isolation|neonatal|sncu|covid|ventilator|chairs?|hospitals|network|group|chain|across|branches|expan\w*|propos\w*|plan\w*|will|upcoming|had|initially|originally|started|inaugurated|increased)\b", re.I)


def items(row):
    desc, *arrs = row
    out = [s for s in re.split(r"(?<=[.;])\s+", desc or "")]
    for a in arrs:
        try:
            x = json.loads(a) if a else []
        except ValueError:
            continue
        if isinstance(x, list):
            out += [s for s in x if isinstance(s, str)]
    return out


def totals(row):
    found = []
    for s in items(row):
        if UNIT.search(s):
            continue
        for rx in STRONG:
            for m in rx.finditer(s):
                n = int(m.group(1).replace(",", ""))
                if n > 0:
                    found.append((n, s))
    return found


if __name__ == "__main__":
    assert totals(("", '["Has 50 beds"]', None, None))[0][0] == 50
    assert totals(("", '["Has a 10-bed ICU"]', None, None)) == []
    assert totals(("", '["300-bed tertiary care hospital"]', None, None))[0][0] == 300
    assert totals(("", '["7,600 beds in 27 hospitals"]', None, None)) == []
    c = con()
    rs = c.execute("select unique_id, name, facilityTypeId, nnum(capacity), description, capability, procedure, equipment from w").fetchall()
    both = agree = fill = nocheck = conflict = anymention = cap_any_num = cap_n = 0
    dis_ex, fill_ex, conf_ex = [], [], []
    for uid, name, ft, cap, *txt in rs:
        t = totals(txt)
        ns = sorted({n for n, _ in t})
        alltxt = " ".join(items(txt))
        if re.search(r"\bbeds?\b|\bbedded\b", alltxt, re.I):
            anymention += 1
        if cap is not None:
            cap_n += 1
            # does the capacity value appear anywhere in the text right before 'bed'?
            if re.search(r"(?<![\d,])" + f"{cap:,}".replace(",", ",?") + r"\s*[- ]?\s*(?:\+\s*)?(?:inpatient\s+)?bed", alltxt, re.I):
                cap_any_num += 1
        if ns and cap is not None:
            both += 1
            if any(abs(n - cap) <= max(2, 0.1 * cap) for n in ns):
                agree += 1
            else:
                dis_ex.append((uid[:8], name, cap, ns, t[0][1][:120]))
        elif ns:
            fill += 1
            fill_ex.append((uid[:8], name, ns, t[-1][1][:120]))
        elif cap is not None:
            nocheck += 1
        if len(ns) >= 2 and max(ns) > 1.5 * min(ns):
            conflict += 1
            conf_ex.append((uid[:8], name, cap, ns))
    print(f"rows mentioning bed(s): {anymention}")
    print(f"capacity present {cap_n}; capacity number appears adjacent to 'bed' somewhere in text: {cap_any_num} ({cap_any_num/cap_n:.3f})")
    print(f"both {both}, agree {agree} ({agree/both:.3f}), disagree {both-agree}; fillable {fill}; cap but no text total {nocheck}; conflicting totals {conflict}")
    json.dump({"disagree": dis_ex, "fillable": fill_ex, "conflict": conf_ex}, open("v3_beds_examples.json", "w"), indent=1)
    import random
    random.seed(1)
    for k, ex in [("DIS", dis_ex), ("FILL", fill_ex), ("CONF", conf_ex)]:
        for e in random.sample(ex, min(6, len(ex))):
            print(k, e)
    # S4 clinics
    print("clinic capacity:", c.execute("""select count(*) filter (where nnum(capacity) is not null), count(*) filter (where nnum(capacity)>=50),
        count(*) filter (where nnum(capacity)>=100), count(*) filter (where nnum(capacity)>=200) from w where facilityTypeId='clinic'""").fetchall())
    print(c.execute("""select unique_id, name, capacity, numberDoctors from w where facilityTypeId='clinic' and nnum(capacity)>=100 order by nnum(capacity) desc""").df().to_string())
