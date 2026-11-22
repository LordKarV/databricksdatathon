"""Field witness: health workers' reports move the score through one named, glass-box term.

What speaks to "does this facility OFFER the service":
- a visit the patient was accepted on (weight 1);
- a turn-away or a phone "no" whose reason is "does not offer" (service_not_here, equipment_absent,
  referred_elsewhere_for_this_service): weight 1 for a visit, 1/2 on the phone;
- a phone "yes" at weight 1/2 (SAFETY 10: a receptionist's yes is not confirmation).
Temporary reasons (no bed, doctor absent, machine down, asked to pay, closed) never lower P(offers); they become
an availability note for the last 7 days. A phone "no" with no reason, and "no answer", say nothing here.

The update is beta-binomial. Prior Beta(N0 p, N0 (1 - p)) with p the model's score; N0 = 10 is an ASSUMPTION
(the model counts as 10 earlier reports, the same weight the notebook's section 9b gives today's mean). Each
report is weighted by recency, 0.5 ** (age_days / 30). Only reports with a reporter key count, one per key (that
reporter's latest), and nothing moves until 2 distinct reporters have spoken: one person cannot move a public
verdict about a real hospital. The effect is one additive logit term, "Field reports" = logit(posterior) -
logit(p), so the contributions ledger still sums exactly to the score shown.

Guardrails (SAFETY 9): reports alone never take a score below the Unlikely line (0.20, MODEL_SPEC fallback t_U),
they say "Reports disagree with the listing: call first" instead; and with no facility text they never lift a
score to the Likely line (t_L = 0.3686, derived/v2/model_card.json), so NO SERVICE TEXT stays its own flag.

Reports can lower a band, never raise it: a Likely pair whose adjusted p falls below t_L becomes Not verified
("Health-worker reports disagree with the listing: call first"). Every other band stays as the model set it, even
when reports are positive. The plan is then rebuilt from the adjusted scores (apply_field), so the order, the
abstention and every sentence built from p agree with the card.

Tie-break (#86, lead's rule): after the term, the leading options of a non-emergency plan that tie (same band, shown
p within 0.05, travel within 10 min; engine.tied_prefix) are ordered by `net`, the same recency-weighted counts the
term used (accepted + phone yes at half weight - "does not offer"; temporary reasons never count), from options
with at least MIN_REPORTERS reporters; others count 0. Nothing else moves. The emergency order is untouched. The why
page shows it as the row "Tie broken by: health-worker reports" (payload `tie_break`); cards add nothing.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import outcomes
from facts.engine import _logit, _pts
from outcomes import REASONS_NOT_OFFERED, REASONS_TEMPORARY

log = logging.getLogger(__name__)

N0 = 10.0  # assumption: prior strength, in reports
HALF_LIFE_DAYS = 30.0
PHONE_WEIGHT = 0.5
MIN_REPORTERS = 2
WINDOW_DAYS = 90
NOTE_DAYS = 7
# The model v2 band lines (derived/v2/model_card.json band_thresholds; test_field pins them to the card).
T_LIKELY, T_UNLIKELY = 0.3686, 0.20
TTL_S = 60
TERM_LABEL = "Field reports"
TIE_LABEL = "Tie broken by: health-worker reports"
MAX_ROWS = 50_000  # ponytail: 90 days of keyed reports nationally is far below this; aggregate further if not

SIM = {"en": "Simulated for the demo: ", "hi": "\u0921\u0947\u092e\u094b \u0915\u0947 \u0932\u093f\u090f \u0928\u0915\u0932\u0940 \u0906\u0901\u0915\u0921\u093c\u0947: "}
REASON = {
    "service_not_here": {"en": "the service is not here", "hi": "\u092f\u0939 \u0938\u0947\u0935\u093e \u092f\u0939\u093e\u0901 \u0928\u0939\u0940\u0902 \u0939\u0948"},
    "equipment_absent": {"en": "the equipment is not here", "hi": "\u0909\u092a\u0915\u0930\u0923 \u092f\u0939\u093e\u0901 \u0928\u0939\u0940\u0902 \u0939\u0948"},
    "referred_elsewhere_for_this_service": {"en": "they send this service elsewhere",
                                            "hi": "\u0935\u0947 \u092f\u0939 \u0938\u0947\u0935\u093e \u0915\u0939\u0940\u0902 \u0914\u0930 \u092d\u0947\u091c\u0924\u0947 \u0939\u0948\u0902"},
    "no_bed": {"en": "no bed", "hi": "\u092c\u0947\u0921 \u0916\u093e\u0932\u0940 \u0928\u0939\u0940\u0902"},
    "doctor_absent": {"en": "doctor not present", "hi": "\u0921\u0949\u0915\u094d\u091f\u0930 \u092e\u094c\u091c\u0942\u0926 \u0928\u0939\u0940\u0902"},
    "machine_down": {"en": "machine not working", "hi": "\u092e\u0936\u0940\u0928 \u0916\u0930\u093e\u092c"},
    "asked_to_pay": {"en": "asked to pay", "hi": "\u092a\u0948\u0938\u0947 \u092e\u093e\u0901\u0917\u0947"},
    "closed_now": {"en": "closed at the time", "hi": "\u0909\u0938 \u0938\u092e\u092f \u092c\u0902\u0926"},
    "visit_none": {"en": "turned away, no reason given", "hi": "\u0932\u094c\u091f\u093e \u0926\u093f\u092f\u093e, \u0915\u093e\u0930\u0923 \u0928\u0939\u0940\u0902 \u092c\u0924\u093e\u092f\u093e"},
}
REBANDED = {"en": "Health-worker reports disagree with the listing: call first",
            "hi": "\u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e\u0913\u0902 \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u0938\u0947 \u092e\u0947\u0932 \u0928\u0939\u0940\u0902 \u0916\u093e\u0924\u0940\u0902: \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0915\u0947 \u092a\u0942\u091b\u0947\u0902\u0964"}
DISAGREE = {"en": "Reports disagree with the listing: call first.",
            "hi": "\u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0914\u0930 \u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u092e\u0947\u0932 \u0928\u0939\u0940\u0902: \u092a\u0939\u0932\u0947 \u092b\u093c\u094b\u0928 \u0915\u0930\u0915\u0947 \u092a\u0942\u091b\u0947\u0902\u0964"}
ONE_REPORTER = {"en": "One health worker's report does not change the score; it needs reports from at least 2.",
                "hi": "\u090f\u0915 \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0938\u0947 \u0938\u094d\u0915\u094b\u0930 \u0928\u0939\u0940\u0902 \u092c\u0926\u0932\u0924\u093e; \u0915\u092e \u0938\u0947 \u0915\u092e 2 \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e\u0913\u0902 \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u091a\u093e\u0939\u093f\u090f\u0964"}
NO_TEXT_CAP = {"en": "The listing has no sentence about this service, so reports alone cannot make it Likely.",
               "hi": "\u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u0907\u0938 \u0938\u0947\u0935\u093e \u0915\u0947 \u092c\u093e\u0930\u0947 \u092e\u0947\u0902 \u0915\u0941\u091b \u0928\u0939\u0940\u0902 \u0932\u093f\u0916\u093e \u0939\u0948, \u0907\u0938\u0932\u093f\u090f \u0938\u093f\u0930\u094d\u092b\u093c \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0938\u0947 \u092f\u0939 Likely (\u0938\u0902\u092d\u093e\u0935\u0928\u093e \u091c\u093c\u094d\u092f\u093e\u0926\u093e) \u0928\u0939\u0940\u0902 \u0939\u094b\u0917\u093e\u0964"}


def _age_days(at: datetime, now: datetime) -> float:
    return max(0.0, (now - at).total_seconds() / 86400)


def _ago(days: float) -> dict[str, str]:
    d = int(days)
    if d == 0:
        return {"en": "today", "hi": "\u0906\u091c"}
    return {"en": f"{d} day{'s' if d > 1 else ''} ago", "hi": f"{d} \u0926\u093f\u0928 \u092a\u0939\u0932\u0947"}


def _signal(r: dict) -> tuple[float, float, str] | None:
    """(weight for offers, weight against, what it was) for reports that speak to whether the service exists."""
    kind, outcome, reason = r.get("kind") or "call", r["outcome"], r.get("reason")
    if kind == "visit" and outcome == "accepted":
        return 1.0, 0.0, "accepted"
    if kind == "call" and outcome == "yes":
        return PHONE_WEIGHT, 0.0, "phone_yes"
    if outcome in ("no", "turned_away") and reason in REASONS_NOT_OFFERED:
        return 0.0, PHONE_WEIGHT if kind == "call" else 1.0, reason
    return None


def _note_key(r: dict) -> str | None:
    """Temporary reasons (and a turn-away with no reason) are availability, not capability."""
    if r.get("reason") in REASONS_TEMPORARY:
        return r["reason"]
    if r.get("kind") == "visit" and r["outcome"] == "turned_away" and not r.get("reason"):
        return "visit_none"
    return None


def _prefix(line: dict[str, str], simulated: bool) -> dict[str, str]:
    return {k: SIM[k] + v for k, v in line.items()} if simulated else line


def _summary_line(latest: list[tuple[dict, tuple]], now: datetime) -> dict[str, str]:
    n = len(latest)
    counts: dict[str, int] = {}
    for _, (_, _, what) in latest:
        counts[what] = counts.get(what, 0) + 1
    en, hi = [], []
    if counts.get("accepted"):
        en.append(f"{counts['accepted']} accepted")
        hi.append(f"{counts['accepted']} \u092c\u093e\u0930 \u092e\u0930\u0940\u091c\u093c \u0915\u094b \u0932\u093f\u092f\u093e \u0917\u092f\u093e")
    if counts.get("phone_yes"):
        en.append(f"{counts['phone_yes']} said yes on the phone")
        hi.append(f"{counts['phone_yes']} \u0928\u0947 \u092b\u093c\u094b\u0928 \u092a\u0930 \u0939\u093e\u0901 \u0915\u0939\u093e")
    for reason in REASONS_NOT_OFFERED:
        if counts.get(reason):
            en.append(f"{counts[reason]} said {REASON[reason]['en']}")
            hi.append(f"{counts[reason]} \u0928\u0947 \u0915\u0939\u093e: {REASON[reason]['hi']}")
    ago = _ago(min(_age_days(r["created_at"], now) for r, _ in latest))
    who_en = "1 health worker" if n == 1 else f"{n} health workers"
    who_hi = "1 \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e" if n == 1 else f"{n} \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e\u0913\u0902"
    return {"en": f"Reports from {who_en} in the last {WINDOW_DAYS} days: {', '.join(en)}; latest {ago['en']}.",
            "hi": f"\u092a\u093f\u091b\u0932\u0947 {WINDOW_DAYS} \u0926\u093f\u0928\u094b\u0902 \u092e\u0947\u0902 {who_hi} \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f: {', '.join(hi)}; "
                  f"\u0938\u092c\u0938\u0947 \u0928\u0908 \u0930\u093f\u092a\u094b\u0930\u094d\u091f: {ago['hi']}\u0964"}


def _notes(reports: list[dict], now: datetime) -> list[dict[str, str]]:
    by_reason: dict[str, dict[str, float]] = {}  # reason -> reporter key -> age of their latest such report
    for r in reports:
        key, age = _note_key(r), _age_days(r["created_at"], now)
        if key and age <= NOTE_DAYS:
            seen = by_reason.setdefault(key, {})
            seen[r["reporter_key"]] = min(age, seen.get(r["reporter_key"], age))
    out = []
    for key, ages in by_reason.items():
        n, ago = len(ages), _ago(min(ages.values()))
        out.append({"en": f"{n} report{'s' if n > 1 else ''} of {REASON[key]['en']} in the last {NOTE_DAYS} days; "
                          f"latest {ago['en']}. This is about availability, not whether the service exists.",
                    "hi": f"\u092a\u093f\u091b\u0932\u0947 {NOTE_DAYS} \u0926\u093f\u0928\u094b\u0902 \u092e\u0947\u0902 {n} \u0930\u093f\u092a\u094b\u0930\u094d\u091f: {REASON[key]['hi']}; \u0938\u092c\u0938\u0947 \u0928\u0908 \u0930\u093f\u092a\u094b\u0930\u094d\u091f: {ago['hi']}\u0964 "
                          "\u092f\u0939 \u0909\u0938 \u0938\u092e\u092f \u0915\u0940 \u092c\u093e\u0924 \u0939\u0948; \u0907\u0938\u0938\u0947 \u092f\u0939 \u092a\u0924\u093e \u0928\u0939\u0940\u0902 \u091a\u0932\u0924\u093e \u0915\u093f \u0905\u0938\u094d\u092a\u0924\u093e\u0932 \u092e\u0947\u0902 \u092f\u0939 \u0938\u0947\u0935\u093e \u0939\u0948 \u092f\u093e \u0928\u0939\u0940\u0902\u0964"})
    return out


def field_adjust(p_model: float, reports: Iterable[dict], now: datetime, has_text: bool = True,
                 likely: bool = False) -> dict[str, Any]:
    """{p, term, lines, notes, disagree, rebanded, n_reporters, simulated, net} for one facility and service. Pure.

    `term` is in logit units: _logit(p_model) + term == _logit(p). Reports without a reporter key are ignored.
    `likely`: the model banded this pair Likely; `rebanded` says the reports took it below the Likely line.
    `net`: the recency-weighted s - f the term used, or None below MIN_REPORTERS; only the tie-break reads it.
    """
    keyed = [r for r in reports if r.get("reporter_key") and _age_days(r["created_at"], now) <= WINDOW_DAYS]
    simulated = any(r.get("simulated") for r in keyed)
    latest: dict[str, tuple[dict, tuple]] = {}
    for r in keyed:
        sig = _signal(r)
        k = r["reporter_key"]
        if sig and (k not in latest or r["created_at"] > latest[k][0]["created_at"]):
            latest[k] = (r, sig)
    p, lines, disagree, net = p_model, [], False, None
    if latest:
        lines.append(_summary_line(list(latest.values()), now))
    if len(latest) == 1:
        lines.append(ONE_REPORTER)
    elif len(latest) >= MIN_REPORTERS:
        s = f = 0.0
        for r, (w_yes, w_no, _) in latest.values():
            w = 0.5 ** (_age_days(r["created_at"], now) / HALF_LIFE_DAYS)
            s, f = s + w * w_yes, f + w * w_no
        p = (N0 * p_model + s) / (N0 + s + f)
        disagree = f > s
        net = round(s - f, 2)  # the tie-break value: accepted + phone yes at half weight - "does not offer"
        p = max(p, min(p_model, T_UNLIKELY))  # reports alone never make a public "Unlikely"
        if not has_text and p > max(p_model, T_LIKELY - 0.01):
            p = max(p_model, T_LIKELY - 0.01)
            lines.append(NO_TEXT_CAP)
    rebanded = likely and p < min(T_LIKELY, p_model)  # the reports took it below the line; never raised
    disagree = disagree or rebanded
    if disagree:
        lines.append(REBANDED if rebanded else DISAGREE)
    return {"p": p, "term": _logit(p) - _logit(p_model), "lines": [_prefix(x, simulated) for x in lines],
            "notes": [_prefix(x, simulated) for x in _notes(keyed, now)], "disagree": disagree,
            "rebanded": rebanded, "n_reporters": len(latest), "simulated": simulated, "net": net}


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def rescore(scored: tuple, reports: Iterable[dict], now: datetime) -> tuple[tuple, dict | None]:
    """(Engine.score() tuple read against the reports, the option's `field` block or None). Pure.

    The tuple keeps the model's evidence; p, the interval and the ledger take the field term; a Likely pair the
    reports take below the Likely line becomes Not verified. None when the reports say nothing about this pair.
    """
    band, p, lo, hi, contrib, ev = scored
    adj = field_adjust(p, reports, now, bool(ev) and band != "no_service_text", band == "likely")
    if not (adj["lines"] or adj["notes"]):
        return scored, None
    info = {"p_model": round(p, 2), **{k: adj[k] for k in
                                       ("term", "lines", "notes", "disagree", "rebanded", "n_reporters", "simulated",
                                        "net")}}
    t = adj["term"]
    if t:
        # The interval moves by the same logit shift. ponytail: not the beta posterior's own interval.
        label = TERM_LABEL + (" (simulated for the demo)" if adj["simulated"] else "")
        scored = ("not_verified" if adj["rebanded"] else band, adj["p"], _sigmoid(_logit(lo) + t),
                  _sigmoid(_logit(hi) + t), [*contrib, {"label": label, "points": _pts(t)}], ev)
    return scored, info


def _annotate(o: dict, info: dict | None) -> dict:
    if info is None:
        return o
    out = {**o, "field": info}
    if info["rebanded"]:
        out["band_reason"] = REBANDED["en"]
    if info["disagree"]:
        out.update(flags=[*o["flags"], DISAGREE["en"]], call_first=True)
    return out


def apply_field(plan_payload: dict, aggregates: dict, now: datetime, eng: Any = None) -> dict:
    """The integrator's hook: a new plan payload rebuilt from the field-adjusted scores.

    The options, their order, why_not and the abstention come from Engine.plan run on the adjusted scores, so every
    sentence built from p or the band agrees with the card. Options with reports gain `field`. Without any report
    for this service near the point the payload is returned as it is.
    """
    service = plan_payload["query"]["service"]
    if eng is None:
        import app  # the loaded engine; imported here because app imports this package

        eng = app._engine()
    found = {}
    for (fid, sid), reports in aggregates.items():
        i = eng.fid.get(fid)
        if sid == service and i is not None and i in eng.index.get(service, {}):
            scored, info = rescore(eng.score(fid, sid), reports, now)
            if info:
                found[fid] = (scored, info)
    if not found:
        return plan_payload
    loc = plan_payload["location"]
    # The route's first stop keeps its lead (itinerary.lead_with_route, #121): it is listed first, so it stays first.
    lead = {o["facility_id"]: o["route_reason"] for o in plan_payload["options"] if o.get("route_reason")}
    # The tie-break reads the same reports as the term: an option counts only with MIN_REPORTERS (net not None).
    fresh = eng.plan(service, loc["lat"], loc["lon"], loc["accuracy_m"], loc["source"],
                     {fid: scored for fid, (scored, _) in found.items()},
                     {fid: info["net"] for fid, (_, info) in found.items() if info["net"] is not None}, lead or None)
    # Every block built from the option order comes from the rebuilt plan (a reorder changes "if the first says no").
    out = {**plan_payload, **{k: fresh[k] for k in ("abstain", "why_not", "what_would_change", "time_window",
                                                    "rank_rule", "public_option")},
           "options": [_annotate(o, (found.get(o["facility_id"]) or (None, None))[1]) for o in fresh["options"]]}
    if fresh.get("tie_break"):
        out["tie_break"] = _tie_row(fresh["tie_break"], fresh["options"], found)
    return out


def _tie_row(tie: dict, options: list[dict], found: dict) -> dict:
    """The why page's row "Tie broken by: health-worker reports": the rule and each tied option's value."""
    rank = {o["facility_id"]: o["rank"] for o in options}
    infos = [(found.get(fid) or (None, {}))[1] for fid in tie["facility_ids"]]
    simulated = any(i.get("simulated") for i in infos)
    return {"label": TIE_LABEL + (" (simulated for the demo)" if simulated else ""), "simulated": simulated,
            "moved": tie["moved"], "p_within": tie["p_within"], "minutes_within": tie["minutes_within"],
            "min_reporters": MIN_REPORTERS,
            "options": [{"facility_id": fid, "rank": rank[fid], "net": i.get("net"),
                         "n_reporters": i.get("n_reporters", 0)} for fid, i in zip(tie["facility_ids"], infos,
                                                                                   strict=True)]}


# ---------- reading: one aggregate query a minute ----------
AGG_SQL = f"""SELECT facility_id, service_id, reporter_key, coalesce(kind, 'call'), outcome, reason, max(created_at)
FROM {outcomes.TABLE}
WHERE reporter_key IS NOT NULL AND created_at >= to_timestamp(:since)
GROUP BY ALL
LIMIT {MAX_ROWS}"""
_cache: dict[str, tuple[float, dict]] = {}


def _ts(v: Any) -> datetime:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _read_live(now: datetime) -> None:
    """One aggregate query into the cache as (time, reports, read_ok)."""
    live: dict[tuple[str, str], list[dict]] = {}
    try:
        rows = outcomes.run(AGG_SQL, {"since": (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")})
        ok = True
    except outcomes.OutcomeError as e:
        log.warning("field reports not read: %s", e)
        rows, ok = [], False
    for fid, sid, key, kind, outcome, reason, at in rows:
        live.setdefault((fid, sid), []).append({"facility_id": fid, "service_id": sid, "reporter_key": key,
                                                "kind": kind, "outcome": outcome, "reason": reason,
                                                "created_at": _ts(at)})
    _cache["a"] = (time.monotonic(), live, ok)


def _read_in_background(now: datetime) -> None:
    try:
        _read_live(now)
    finally:
        _reading.release()


_reading = threading.Lock()


def aggregates(now: datetime | None = None, wait: bool = True) -> dict[tuple[str, str], list[dict]]:
    """{(facility_id, service_id): [report]} from the table (cached 60 s), plus the demo reports when enabled.

    A warehouse error leaves the plan unchanged (no field lines) and is logged, never raised into /api/plan.
    wait=False (what /api/plan uses) never blocks on the warehouse: a stale cache is refreshed in a background
    thread and this answer uses what was read last (nothing on the first request after start-up). A stopped
    warehouse can take 30 s to answer, and a referral must not wait for that.
    """
    now = now or datetime.now(UTC)
    hit = _cache.get("a")
    if not hit or time.monotonic() - hit[0] >= TTL_S:
        if wait:
            _read_live(now)
        elif _reading.acquire(blocking=False):
            threading.Thread(target=_read_in_background, args=(now,), daemon=True).start()
    live = (_cache.get("a") or (0.0, {}, None))[1]
    if os.environ.get("COMMUNITY_DEMO") != "1":
        return live
    out = {k: list(v) for k, v in live.items()}
    for r in simulated_reports(now=now):
        out.setdefault((r["facility_id"], r["service_id"]), []).append(r)
    return out


NOT_READ = {"en": "Logged field reports were not read for this answer; the scores come from the listings only.",
            "hi": "\u0907\u0938 \u091c\u0935\u093e\u092c \u0915\u0947 \u0932\u093f\u090f \u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0915\u093e\u0930\u094d\u092f\u0915\u0930\u094d\u0924\u093e\u0913\u0902 \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0928\u0939\u0940\u0902 \u092a\u0922\u093c\u0940 \u091c\u093e \u0938\u0915\u0940\u0902; "
                  "\u0938\u094d\u0915\u094b\u0930 \u0938\u093f\u0930\u094d\u092b\u093c \u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u0938\u0947 \u0939\u0948\u0902\u0964"}


def status() -> dict[str, Any]:
    """`field_reports` in /api/plan: whether the last read worked; a plain note when it did not (or not yet)."""
    ok = (_cache.get("a") or (0.0, {}, None))[2]
    return {"read": bool(ok), "note": None if ok else NOT_READ}


# ---------- demo: in memory, marked simulated, never written ----------
DEMO_POINT = (26.6, 85.48)  # the README's example point
# (service, option rank, reporter, kind, outcome, reason, days ago)
DEMO = (
    ("dialysis", 1, "sim-a", "visit", "accepted", None, 4),
    ("dialysis", 1, "sim-b", "visit", "accepted", None, 12),
    ("dialysis", 1, "sim-c", "call", "yes", None, 20),
    ("dialysis", 2, "sim-d", "visit", "turned_away", "no_bed", 1),
    ("dialysis", 2, "sim-e", "visit", "turned_away", "no_bed", 3),
    ("dialysis", 2, "sim-a", "visit", "accepted", None, 25),
    # Option 3 is tied with 1 and 2 at the README point; two reporters let the tie-break order it (#86).
    ("dialysis", 3, "sim-f", "visit", "accepted", None, 6),
    ("dialysis", 3, "sim-g", "visit", "accepted", None, 9),
    ("emergency_csection", 1, "sim-b", "call", "yes", None, 2),
)


def simulated_reports(eng: Any = None, now: datetime | None = None) -> list[dict]:
    """Demo reports for real pairs: the options /api/plan gives at DEMO_POINT. Same keys as live reports."""
    if eng is None:
        import app  # the loaded engine (lru_cache); imported here because app imports this package

        eng = app._engine()
    if eng is None:
        return []
    now = now or datetime.now(UTC)
    plans = {svc: eng.plan(svc, *DEMO_POINT, None, "gps")["options"] for svc in {d[0] for d in DEMO}}
    district = outcomes.district(eng, *DEMO_POINT)
    out = []
    for svc, rank, key, kind, outcome, reason, days in DEMO:
        opts = plans[svc]
        if rank <= len(opts):
            out.append({"facility_id": opts[rank - 1]["facility_id"], "service_id": svc, "reporter_key": key,
                        "kind": kind, "outcome": outcome, "reason": reason, "district": district,
                        "created_at": now - timedelta(days=days, hours=2), "simulated": True})
    return out
