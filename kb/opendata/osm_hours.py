"""Parse the OSM opening_hours tag into a weekly schedule, is_24x7 and a readable string.

Covers the subset seen on Indian health features: "24/7", day ranges and lists ("Mo-Sa",
"Mo,We,Fr", wrap-around "Fr-We"), several time spans per day, overnight spans, "off"/"closed",
";" (later rule overrides those days) and "," between rules (adds), PH/SH rules (ignored for
the weekly view). Anything else (months, weeks, sunrise, comments, "9am") is returned with
parse_ok False and is_24x7 None, never guessed.

Self-check: .venv/bin/python -I kb/opendata/osm_hours.py
"""
import re
from typing import NamedTuple

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
LONG = {"Mo": "Mon", "Tu": "Tue", "We": "Wed", "Th": "Thu", "Fr": "Fri", "Sa": "Sat", "Su": "Sun"}
ALIASES = {  # English spellings people type instead of OSM two-letter codes
    r"\bmon(day)?\b": "Mo", r"\btue(s|sday)?\b": "Tu", r"\bwed(nesday)?\b": "We",
    r"\bthu(r|rs|rsday)?\b": "Th", r"\bfri(day)?\b": "Fr", r"\bsat(urday)?\b": "Sa",
    r"\bsun(day)?\b": "Su",
}
FULL_DAY = re.compile(r"^\s*(24\s*/\s*7|24\s*[x*]\s*7|24\s*hours?|open 24 hours|00:00\s*-\s*24:00)\s*$", re.I)
D = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
DAYSEL = re.compile(rf"^((?:{D}(?:\s*-\s*{D})?|PH|SH)(?:\s*,\s*(?:{D}(?:\s*-\s*{D})?|PH|SH))*)\s*(.*)$")
SPAN = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\+?$")


class Hours(NamedTuple):
    parse_ok: bool
    is_24x7: bool | None
    week: dict | None  # day -> list of (start_min, end_min)
    readable: str


def _days(sel: str) -> list[str] | None:
    out: list[str] = []
    for part in re.split(r"\s*,\s*", sel):
        if part in ("PH", "SH"):
            continue
        if "-" in part:
            a, b = [p.strip() for p in part.split("-")]
            i, j = DAYS.index(a), DAYS.index(b)
            out += [DAYS[k % 7] for k in range(i, j + 1 if j >= i else j + 8)]
        else:
            out.append(part)
    return out


def _spans(txt: str) -> list[tuple[int, int]] | None:
    """'09:00-13:00,17:00-20:00' -> minutes; None if anything does not parse."""
    out = []
    for s in re.split(r"\s*,\s*", txt.strip()):
        m = SPAN.match(s)
        if not m:
            return None
        h1, m1, h2, m2 = map(int, m.groups())
        a, b = h1 * 60 + m1, h2 * 60 + m2
        if b == 23 * 60 + 59:
            b = 1440
        if a > 1440 or b > 1440 or a == b:
            return None
        out.append((a, b))
    return out


def _fmt(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _readable(week: dict) -> str:
    if all(week[d] == [(0, 1440)] for d in DAYS):
        return "Open 24 hours, 7 days"
    txt = {d: ", ".join(f"{_fmt(a)}-{_fmt(b)}" for a, b in week[d]) or "closed" for d in DAYS}
    groups, start = [], 0
    for i in range(1, 8):
        if i == 7 or txt[DAYS[i]] != txt[DAYS[start]]:
            name = LONG[DAYS[start]] + ("" if i - 1 == start else "-" + LONG[DAYS[i - 1]])
            groups.append(f"{name} {txt[DAYS[start]]}")
            start = i
    return "; ".join(groups)


def parse(raw: str | None) -> Hours:
    if not isinstance(raw, str) or not raw.strip():
        return Hours(False, None, None, "")
    s = raw.strip().replace("–", "-").replace("—", "-").replace("||", ";")
    if FULL_DAY.match(s):
        week = {d: [(0, 1440)] for d in DAYS}
        return Hours(True, True, week, _readable(week))
    for pat, code in ALIASES.items():
        s = re.sub(pat, code, s, flags=re.I)
    s = re.sub(r"\b(mo|tu|we|th|fr|sa|su|ph|sh)\b", lambda m: m.group(1).capitalize().replace("Ph", "PH")
               .replace("Sh", "SH"), s, flags=re.I)
    s = re.sub(rf"({D})\s*:\s*(?=\d)", r"\1 ", s)  # "Mo-Su: 17:00" -> "Mo-Su 17:00"
    s = re.sub(r"(\d)\s+-\s*(\d)|(\d)\s*-\s+(\d)", lambda m: "-".join(x for x in m.groups() if x), s)
    s = re.sub(r"\b(\d):", r"0\1:", s)
    week: dict = {d: [] for d in DAYS}
    for rule in [r.strip() for r in s.split(";") if r.strip()]:
        # "Mo-Fr 09:00-17:00, Sa 10:00-14:00": a comma after a time and before a day adds a rule
        subs = re.split(rf"(?<=\d)\s*,\s*(?={D}|PH|SH)", rule)
        touched: dict = {}
        for sub in subs:
            m = DAYSEL.match(sub)
            sel, rest = (m.group(1), m.group(2)) if m else ("", sub)
            days = _days(sel) if sel else DAYS
            if sel and not days:  # PH/SH only
                continue
            rest = rest.strip()
            if rest.lower() in ("off", "closed"):
                spans: list | None = []
            elif rest == "" or FULL_DAY.match(rest) or rest.lower() == "open":
                spans = [(0, 1440)]
            else:
                spans = _spans(rest)
            if spans is None:
                return Hours(False, None, None, raw.strip())
            for i, d in enumerate(DAYS):
                if d not in days:
                    continue
                for a, b in spans:
                    if b > a:
                        touched.setdefault(d, []).append((a, b))
                    else:  # overnight: tail goes to the next day
                        touched.setdefault(d, []).append((a, 1440))
                        touched.setdefault(DAYS[(i + 1) % 7], []).append((0, b))
                touched.setdefault(d, [])
        for d, sp in touched.items():  # ";" semantics: this rule replaces earlier ones for its days
            week[d] = _merge(sp)
    is247 = all(week[d] == [(0, 1440)] for d in DAYS)
    return Hours(True, is247, week, _readable(week))


def week_text(week: dict | None) -> str | None:
    if week is None:
        return None
    return "; ".join(f"{d} " + (",".join(f"{_fmt(a)}-{_fmt(b)}" for a, b in week[d]) or "off") for d in DAYS)


def _demo() -> None:
    assert parse("24/7").is_24x7 is True
    assert parse("Mo-Su 00:00-24:00").is_24x7 is True
    assert parse("Mo-Su 00:00-23:59").is_24x7 is True
    h = parse("Mo-Sa 09:00-21:00; Su off")
    assert h.is_24x7 is False and h.readable == "Mon-Sat 09:00-21:00; Sun closed", h.readable
    h = parse("Mo-Tu, Th-Sa 15:00-21:00")
    assert h.week["We"] == [] and h.week["Th"] == [(900, 1260)], h
    h = parse("Fr-We 09:00-15:00")
    assert h.week["Th"] == [] and h.week["Mo"] == [(540, 900)]
    h = parse("Mo-Fr 09:00-13:00,17:00-20:00, Sa 10:00-14:00")
    assert h.week["Mo"] == [(540, 780), (1020, 1200)] and h.week["Sa"] == [(600, 840)], h
    h = parse("Mo-Su 20:00-08:00")
    assert h.week["Tu"] == [(0, 480), (1200, 1440)], h.week
    h = parse("Mo-Su 00:00-24:00; PH off")
    assert h.is_24x7 is True
    assert parse("Jan-Mar Mo 10:00-12:00").parse_ok is False
    assert parse("9am-5pm").is_24x7 is None
    assert parse("Monday-Saturday 9:00-17:00").week["Sa"] == [(540, 1020)]
    assert parse("10:00-20:00").week["Su"] == [(600, 1200)]
    assert parse("mo-sa 8:00-20:00 ; Su 08:00-13:00").week["Su"] == [(480, 780)]
    assert parse("Mo-Su: 17:00 -21:00").week["We"] == [(1020, 1260)]
    print("osm_hours self-check ok")


if __name__ == "__main__":
    _demo()
