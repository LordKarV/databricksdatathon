"""Area pulse: anonymous district counts from logged reports, for NGO coordinators and district planners.

Only logged reports count (phone outcomes and field reports in OUTCOMES_TABLE); the app does not log searches,
so "services people looked for" means services that reports were logged for.

Privacy rules, applied before anything leaves this module:
- Times are cut to the ISO week (Monday) in SQL, so nothing finer than the week reaches the app.
- One window only: the 13 whole weeks (91 days, "the last 90 days") that end where the current ISO week starts.
  Its counts stay fixed for the whole week, and no second window can be subtracted from it.
- A district x service cell is shown only with at least MIN_REPORTERS distinct reporter keys and MIN_REPORTS
  reports; a facility or reason-class cell inside it needs DETAIL_REPORTERS and DETAIL_REPORTS. A NULL or empty
  reporter_key never counts as a reporter.
- Complementary suppression: what a shown service cell holds beyond its shown facility (or reason) cells is either
  nothing or itself passes the detail rule; otherwise the smallest detail cell is hidden too. So no cell minus its
  shown parts recovers a hidden one.
- Hidden cells are left out entirely, with no count of them; every total is the sum of the shown cells. The only
  word about hidden data is HIDDEN_NOTE, present in every answer.
- The answer holds counts only: no report rows, reporter keys or coordinates.

Known limit (app/README.md): the same query before and after a new week, or reports from colluding health workers
who know their own entries, can still be differenced.

With COMMUNITY_DEMO=1 the rows come from community.field.simulated_reports() and every sentence starts with
SIM. Hindi strings are drafts until native-speaker review (#10).
"""
from __future__ import annotations

import math
import os
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import outcomes
from errors import Invalid
from facts.engine import Engine
from services import BAND_WORDS, SERVICES

MIN_REPORTERS, MIN_REPORTS = 3, 5  # district x service
DETAIL_REPORTERS, DETAIL_REPORTS = 5, 8  # x facility, x reason class
WINDOW_DAYS = 90
TOP_FACILITIES = 5  # per service
TTL_S = 60
MAX_ROWS = 100_000  # ponytail: one district over 90 days is far below this; aggregate in SQL if it ever is not
# Field-report vocabulary (community/field.py): a "call" is a phone outcome (yes / no / no_answer); a "visit" is
# a referral the patient went on, accepted or turned away (with a reason class).
CALL, VISIT = "call", "visit"
ACCEPTED, TURNED_AWAY = "accepted", "turned_away"
HIDDEN_NOTE = {"en": "Some reports are not shown so no single health worker can be identified.",
               "hi": "\u0915\u0941\u091b \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0928\u0939\u0940\u0902 \u0926\u093f\u0916\u093e\u0908 \u0917\u0908\u0902 \u0924\u093e\u0915\u093f \u0915\u093f\u0938\u0940 \u090f\u0915 \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e \u0915\u0940 \u092a\u0939\u091a\u093e\u0928 \u0928 \u0939\u094b \u0938\u0915\u0947\u0964"}
SIM = {"en": "Simulated for the demo: ", "hi": "\u0921\u0947\u092e\u094b \u0915\u0947 \u0932\u093f\u090f \u0928\u0915\u0932\u0940 \u0906\u0901\u0915\u0921\u093c\u0947: "}


def week_start(d: date | datetime | str) -> date:
    """Monday of the ISO week that holds d (a date, datetime or ISO string)."""
    if isinstance(d, str):
        d = datetime.fromisoformat(d.replace("Z", "+00:00"))
    if isinstance(d, datetime):
        d = d.date()
    return d - timedelta(days=d.weekday())


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float] | None:
    """(rate, low, high) of the 95% Wilson score interval for k successes in n, or None when n is 0."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, mid - half), min(1.0, mid + half)


def window_bounds(today: date) -> tuple[date, date]:
    """(first Monday, Monday that ends it, exclusive): whole weeks covering WINDOW_DAYS before this week."""
    until = week_start(today)
    return week_start(until - timedelta(days=WINDOW_DAYS)), until


def shown(rows: list[dict], min_reporters: int = MIN_REPORTERS, min_reports: int = MIN_REPORTS) -> bool:
    """k-anonymity: at least min_reports reports from at least min_reporters distinct, non-NULL reporter keys."""
    keys = {r.get("reporter_key") for r in rows} - {None, ""}
    return len(rows) >= min_reports and len(keys) >= min_reporters


def detail_shown(rows: list[dict]) -> bool:
    return shown(rows, DETAIL_REPORTERS, DETAIL_REPORTS)


def with_complement(groups: list[tuple[Any, list[dict]]], parent: list[dict], top: int) -> list[tuple[Any, list]]:
    """The detail cells of a shown parent cell that may be shown (complementary suppression).

    groups: (key, rows) inside parent, largest first. A group is kept when it passes the detail rule, and only while
    the parent's rows outside the kept groups are none or pass the detail rule too: otherwise parent minus the
    shown cells would be a hidden cell. The smallest kept group is dropped until that holds.
    """
    keep = [kv for kv in groups if detail_shown(kv[1])][:top]
    while keep:
        inside = {id(r) for _, g in keep for r in g}
        rest = [r for r in parent if id(r) not in inside]
        if not rest or detail_shown(rest):
            return keep
        keep = keep[:-1]
    return keep


def _sim(text: dict[str, str], simulated: bool) -> dict[str, str]:
    return {k: SIM[k] + v for k, v in text.items()} if simulated else text


def _n(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _pct(x: float) -> int:
    return round(100 * x)


def _service_cell(district: str, sid: str, g: list[dict], simulated: bool) -> dict[str, Any]:
    days = WINDOW_DAYS
    label_en, label_hi = SERVICES[sid]["label_en"], SERVICES[sid]["label_hi"]
    visits = [r for r in g if r.get("kind") == VISIT]
    calls = [r for r in g if r.get("kind") != VISIT]
    acc = sum(r.get("outcome") == ACCEPTED for r in visits)
    decided = acc + sum(r.get("outcome") == TURNED_AWAY for r in visits)
    said = {o: sum(r.get("outcome") == o for r in calls) for o in outcomes.OUTCOMES}
    w = wilson(acc, decided)
    en = [f"In {district} district, health workers logged {_n(len(visits), label_en + ' referral')} and "
          f"{_n(len(calls), 'phone call')} in the last {days} days."]
    hi = [f"{district} \u091c\u093c\u093f\u0932\u0947 \u092e\u0947\u0902 \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e\u0913\u0902 \u0928\u0947 \u092a\u093f\u091b\u0932\u0947 {days} \u0926\u093f\u0928\u094b\u0902 \u092e\u0947\u0902 {label_hi} \u0915\u0947 {len(visits)} \u0930\u0947\u092b\u093c\u0930\u0932 "
          f"\u0914\u0930 {len(calls)} \u092b\u093c\u094b\u0928 \u0915\u0949\u0932 \u0926\u0930\u094d\u091c \u0915\u093f\u090f\u0964"]
    if decided:
        en.append(f"Of the {decided} referrals with a known result, {acc} were accepted.")
        hi.append(f"\u091c\u093f\u0928 {decided} \u0930\u0947\u092b\u093c\u0930\u0932 \u0915\u093e \u0928\u0924\u0940\u091c\u093e \u092a\u0924\u093e \u0939\u0948, \u0909\u0928\u092e\u0947\u0902 \u0938\u0947 {acc} \u092e\u0947\u0902 \u092e\u0930\u0940\u091c\u093c \u0915\u094b \u0932\u093f\u092f\u093e \u0917\u092f\u093e\u0964")
        en.append(f"From so few reports, the true acceptance rate is probably between {_pct(w[1])}% and "
                  f"{_pct(w[2])}% (95% interval); more reports would narrow it.")
        hi.append(f"\u0907\u0924\u0928\u0940 \u0915\u092e \u0930\u093f\u092a\u094b\u0930\u094d\u091f\u094b\u0902 \u0938\u0947, \u092e\u0930\u0940\u091c\u093c \u0915\u094b \u0932\u0947\u0928\u0947 \u0915\u0940 \u0905\u0938\u0932\u0940 \u0926\u0930 \u0936\u093e\u092f\u0926 {_pct(w[1])}% \u0938\u0947 {_pct(w[2])}% \u0915\u0947 \u092c\u0940\u091a \u0939\u0948 (95% \u0926\u093e\u092f\u0930\u093e); "
                  "\u091c\u093c\u094d\u092f\u093e\u0926\u093e \u0930\u093f\u092a\u094b\u0930\u094d\u091f\u094b\u0902 \u0938\u0947 \u092f\u0939 \u0926\u093e\u092f\u0930\u093e \u091b\u094b\u091f\u093e \u0939\u094b\u0917\u093e\u0964")
    if calls:
        en.append(f"On the phone, {said['yes']} said yes, {said['no']} said no and {said['no_answer']} did not "
                  "answer. A yes on the phone is what the person who answered said; it is not a confirmation.")
        hi.append(f"\u092b\u093c\u094b\u0928 \u092a\u0930 {said['yes']} \u0928\u0947 \u0939\u093e\u0901 \u0915\u0939\u093e, {said['no']} \u0928\u0947 \u0928\u093e \u0915\u0939\u093e \u0914\u0930 {said['no_answer']} \u0928\u0947 \u092b\u093c\u094b\u0928 \u0928\u0939\u0940\u0902 "
                  "\u0909\u0920\u093e\u092f\u093e\u0964 \u092b\u093c\u094b\u0928 \u092a\u0930 \u0939\u093e\u0901 \u0938\u093f\u0930\u094d\u092b\u093c \u091c\u0935\u093e\u092c \u0926\u0947\u0928\u0947 \u0935\u093e\u0932\u0947 \u0915\u0940 \u092c\u093e\u0924 \u0939\u0948; \u0907\u0938\u0938\u0947 \u092a\u0915\u094d\u0915\u093e \u0928\u0939\u0940\u0902 \u0939\u094b\u0924\u093e\u0964")
    return {"service_id": sid, "reports": len(g), "referrals": len(visits), "calls": len(calls),
            "accepted": acc, "decided": decided, "said": said,
            "rate": None if w is None else {"p": round(w[0], 3), "lo": round(w[1], 3), "hi": round(w[2], 3)},
            "text": _sim({"en": " ".join(en), "hi": " ".join(hi)}, simulated)}


def _facility(eng: Engine, fid: str, sid: str, g: list[dict]) -> dict[str, Any]:
    i = eng.fid.get(fid)
    listed = i is not None and i in eng.index.get(sid, {})
    band, *_, ev = eng.score(fid, sid) if listed else (None, [])
    visits = [r for r in g if r.get("kind") == VISIT]
    return {"facility_id": fid, "service_id": sid, "name": eng.fac["name"][i] if i is not None else None,
            "reports": len(g), "referrals": len(visits),
            "accepted": sum(r.get("outcome") == ACCEPTED for r in visits),
            "turned_away": sum(r.get("outcome") == TURNED_AWAY for r in visits),
            "band": band, "band_word": BAND_WORDS.get(band),
            # The cited listing sentence behind today's band, so the count never stands without its evidence.
            "evidence": {"claim_id": ev[0], "quote": eng.claims[ev[0]][1], "source_url": eng.cited_url(i)}
            if ev else None}


def _reason_class(reason: str) -> str:
    """not_offered speaks to whether the facility has the service at all; temporary (no bed, doctor away) does not."""
    return "not_offered" if reason in outcomes.REASONS_NOT_OFFERED else "temporary"


def _by_size(rows: list[dict], key) -> list[tuple[Any, list[dict]]]:
    out: dict[Any, list[dict]] = {}
    for r in rows:
        out.setdefault(key(r), []).append(r)
    return sorted(out.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))


def _window(eng: Engine, rows: list[dict], district: str, today: date, simulated: bool) -> dict:
    since, until = window_bounds(today)
    w = [r for r in rows if since <= r["week"] < until]
    cells = [(sid, g) for sid, g in _by_size(w, lambda r: r.get("service_id")) if sid in SERVICES and shown(g)]
    facilities, reasons = [], []
    for sid, g in cells:
        facs = with_complement(_by_size(g, lambda r: r.get("facility_id")), g, TOP_FACILITIES)
        facilities += [_facility(eng, fid, sid, fg) for fid, fg in facs]
        # A "no" on the phone and a turn-away, with or without a reason: the service cell already counts them all.
        refused = [r for r in g if r.get("outcome") in ("no", TURNED_AWAY)]
        classes = _by_size([r for r in refused if r.get("reason")], lambda r: _reason_class(r["reason"]))
        reasons += [{"service_id": sid, "class": c, "n": len(cg)} for c, cg in with_complement(classes, refused, 2)]
    services = [_service_cell(district, sid, g, simulated) for sid, g in cells]
    return {
        "days": WINDOW_DAYS, "since_week": since.isoformat(), "through": (until - timedelta(days=1)).isoformat(),
        "reports": sum(c["reports"] for c in services),  # the shown cells only
        "services": services, "facilities": facilities, "reasons": reasons,
        "empty": None if services else _sim({
            "en": f"No counts to show for {district} district in the last {WINDOW_DAYS} days.",
            "hi": f"\u092a\u093f\u091b\u0932\u0947 {WINDOW_DAYS} \u0926\u093f\u0928\u094b\u0902 \u092e\u0947\u0902 {district} \u091c\u093c\u093f\u0932\u0947 \u0915\u0947 \u0932\u093f\u090f \u0926\u093f\u0916\u093e\u0928\u0947 \u0932\u093e\u092f\u0915 \u0915\u094b\u0908 \u0938\u0902\u0916\u094d\u092f\u093e \u0928\u0939\u0940\u0902 \u0939\u0948\u0964"},
            simulated),
    }


def aggregate(eng: Engine, rows: list[dict], district: str, service: str | None, today: date,
              simulated: bool) -> dict[str, Any]:
    """Counts for the one window from report rows that already carry a `week` (date of the Monday)."""
    rows = [r for r in rows if service is None or r.get("service_id") == service]
    return {"district": district, "service": service, "simulated": simulated, "as_of": today.isoformat(),
            "rule": {"min_reporters": MIN_REPORTERS, "min_reports": MIN_REPORTS,
                     "detail_min_reporters": DETAIL_REPORTERS, "detail_min_reports": DETAIL_REPORTS,
                     "week_starts": "Monday"},
            "window": _window(eng, rows, district, today, simulated), "hidden_note": HIDDEN_NOTE}


def _live_rows(district: str, service: str | None, since: date, until: date) -> list[dict]:
    # Weeks are cut in SQL, so no time finer than the week reaches the app. Rows from before field reports have
    # no kind: they are phone outcomes.
    data = outcomes.run(f"""SELECT facility_id, service_id, coalesce(kind, 'call'), outcome, reason, reporter_key,
  CAST(date_trunc('WEEK', created_at) AS DATE)
FROM {outcomes.TABLE}
WHERE district = :district AND created_at >= to_date(:since) AND created_at < to_date(:until)
  AND (:service = '' OR service_id = :service)
LIMIT {MAX_ROWS}""", {"district": district, "since": since.isoformat(), "until": until.isoformat(),
                      "service": service or ""})
    cols = ("facility_id", "service_id", "kind", "outcome", "reason", "reporter_key", "week")
    return [{**dict(zip(cols, r, strict=True)), "week": week_start(r[6])} for r in data]


def _demo_rows(eng: Engine, district: str) -> list[dict]:
    try:
        from community.field import simulated_reports
    except ImportError as e:
        raise outcomes.OutcomeError("the demo reports are not installed on this server", "pulse_demo_missing") from e
    # ponytail: the demo reports are days old, so most fall in the current week, which is never published; they
    # are moved one week back to land in the window. Simulated and labelled either way.
    return [{**r, "week": week_start(r["created_at"]) - timedelta(days=7)} for r in simulated_reports(eng)
            if str(r.get("district") or "").title() == district]


def resolve_district(eng: Engine, district: str | None, lat: float | None, lon: float | None) -> str:
    """A district the PIN data knows (title case, as outcomes stores it), from a name or a rounded point."""
    if district:
        name = district.strip().title()
        if name not in {str(d).title() for d in eng.pins["district"]}:
            raise Invalid("pulse_unknown_district", "unknown district")
        return name
    if lat is None or lon is None:
        raise Invalid("pulse_need_where", "give a district, or lat and lon")
    found = outcomes.district(eng, round(lat, 2), round(lon, 2))
    if not found:
        raise Invalid("pulse_no_district_for_point", "no district found for this point")
    return found


_cache: dict[tuple, tuple[float, dict]] = {}


def pulse(eng: Engine, district: str | None, service: str | None, lat: float | None = None,
          lon: float | None = None) -> dict[str, Any]:
    """GET /api/pulse. Raises ValueError on bad input and outcomes.OutcomeError when the store is unavailable."""
    if service is not None and service not in SERVICES:
        raise Invalid("pulse_unknown_service", "unknown service")
    name = resolve_district(eng, district, lat, lon)
    demo = os.environ.get("COMMUNITY_DEMO") == "1"
    key = (name, service, demo)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    today = datetime.now(UTC).date()
    rows = _demo_rows(eng, name) if demo else _live_rows(name, service, *window_bounds(today))
    out = aggregate(eng, rows, name, service, today, demo)
    _cache[key] = (time.monotonic(), out)
    return out
