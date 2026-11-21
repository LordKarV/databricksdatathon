"""Test fixture (since #42): invented plan and area payloads in the contract shape (issue #5).

Everything here is invented sample data, flagged with meta.stub = true and "(sample)" in
facility names. The app serves real rows from facts/engine.py; this module is kept only for tests
(faithfulness and UI states that need a fixed shape, such as a Likely option).
"""
from __future__ import annotations

from datetime import UTC, datetime

from services import BAND_WORDS, SERVICES, Band, _geo_estimate, emergency_numbers  # noqa: F401
from services import travel as _travel


def _option(rank: int, fid: str, name: str, operator: str, band: Band, p: tuple[float, float, float],
            dlat: float, dlon: float, lat: float, lon: float, service: str, quotes: list[tuple[str, str]],
            n_checked: int, call_first: bool) -> dict:
    flat, flon = round(lat + dlat, 4), round(lon + dlon, 4)
    travel = _travel(lat, lon, flat, flon)
    label = SERVICES[service]["label_en"]
    call_ahead = [{"question": "Is this the branch in this town, or another branch?",
                   "asked_because": "record merges many web pages"}]
    if operator == "private":
        call_ahead.append({"question": "What does it cost? Is PM-JAY accepted?", "asked_because": "private facility"})
    if band != "likely":
        call_ahead.append({"question": f"Do you do {label} here yourselves, or send patients elsewhere?",
                           "asked_because": "service only appears in a specialty or tag list"})
    return {
        "rank": rank,
        "facility_id": fid,
        "name": name,
        "town": "Sample town",
        "district": "Sample district",
        "state": "Sample state",
        "address": "Station Road, Sample town",
        "operator": operator,  # private | public | unknown (public only when the field says so)
        "lat": flat,
        "lon": flon,
        "travel": travel,
        "band": band,
        "band_word": BAND_WORDS[band],
        "band_reason": None if band == "likely" else "own-sentence evidence below threshold",
        "p": p[0], "p_lo": p[1], "p_hi": p[2],
        "p_e": 0.97 if band == "likely" else 0.88, "p_l": 0.95 if band == "likely" else 0.62,  # model: exists / where
        "evidence": [{"claim_id": f"stub-{fid}-{i}", "field": f, "quote": t,
                      "source_url": "https://example.org/sample-listing"} for i, (f, t) in enumerate(quotes)],
        "contributions": [
            {"label": "base: " + operator + " hospital", "points": -18},
            {"label": "own sentences, 2 fields", "points": 46},
            {"label": "equipment with a count", "points": 14},
            {"label": "record merges 12 sources", "points": -6},
        ] if band == "likely" else [
            {"label": "base: " + operator + " hospital", "points": -18},
            {"label": "service only in a tag list", "points": 6},
        ],
        "flags": ([f"Ignored: \"{label.capitalize()} at City Hospital, Patna\" names a different hospital"]
                  if rank == 1 else []) + (["Phone number not available in sample data"]),
        "call_ahead": call_ahead,
        "call_first": call_first,
        "track_record": {"n": n_checked, "k_confirmed": 1 if n_checked else 0, "k_contradicted": 0,
                         "k_no_info": max(n_checked - 1, 0), "split": "dev"},
        "phone": {"e164": None, "display": None, "shared_listings": 0},
        "is_real": ["own website", "mobile number not shared with other listings"],
        "where_check": "PIN, map point and city agree (within 3 km)",
        "why_first_text": ("Sample: a nearer option exists, but the evidence here is stronger, so this ranks first."
                           if rank == 1 else None),
        "say_to_family": {
            "en": f"This hospital's listing says it offers {label}. It is about {round(travel['km'])} kilometres "
                  "away. We will phone before going.",
            "hi": None,  # Hindi templates wait for native-speaker review (issue #10)
        },
    }


def recommend_stub(service: str, lat: float, lon: float, accuracy_m: float | None, source: str) -> dict:
    info = SERVICES[service]
    label = info["label_en"]
    profile = info["profile"]
    meta = {
        "stub": True,
        "model_hash": "stub-0000",
        "data_snapshot": "derived/v1 (not read by the stub)",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    query = {"service": service, "service_label": {"en": label, "hi": info["label_hi"]}}
    location = {"lat": lat, "lon": lon, "accuracy_m": accuracy_m, "source": source, "rounded_to_deg": 0.01}
    as_of = "2026-11-21"  # stub; the model export carries its own snapshot date
    emergency_numbers_ = emergency_numbers(service)

    if service == "emergency_csection":
        # Abstention is the expected common case today (spec S3x), so the stub exercises it.
        options = [
            _option(1, "stub-201", "Sample Nursing Home (sample)", "private", "not_verified", (0.41, 0.22, 0.63),
                    0.30, 0.15, lat, lon, service, [("description", "Maternity and gynaecology services")], 0, True),
            _option(2, "stub-202", "Sample Maternity Clinic (sample)", "private", "not_verified",
                    (0.35, 0.18, 0.57), -0.40, 0.25, lat, lon, service, [], 0, False),
        ]
        return {
            "query": query, "location": location, "as_of": as_of, "profile": profile,
            "emergency_numbers": emergency_numbers_,
            "abstain": {
                "text": f"No facility within 150 km has enough public evidence that it does {label}.",
                "outside_option": {
                    "facility_id": "stub-dh", "name": "Sample District Hospital (sample)", "operator": "public",
                    "text": "The public standard says this level should offer it; not verified in our data.",
                    "travel": _travel(lat, lon, lat + 0.25, lon - 0.1)},
            },
            "options": options, "why_not": [], "meta": meta,
        }

    options = [
        _option(1, "stub-101", "Sample Care Centre (sample)", "private", "likely", (0.81, 0.70, 0.89),
                0.15, 0.08, lat, lon, service,
                [("equipment", f"6 machines for {label} in a dedicated unit"),
                 ("procedure", f"{label.capitalize()} offered on site")], 2, True),
        _option(2, "stub-102", "Sample Sadar Hospital (sample)", "public", "not_verified", (0.48, 0.30, 0.66),
                0.12, -0.05, lat, lon, service, [], 0, False),
        _option(3, "stub-103", "Sample Specialty Centre (sample)", "private", "likely", (0.77, 0.64, 0.87),
                0.55, 0.20, lat, lon, service,
                [("description", f"Department of {label}")], 2, False),
    ]
    why_not = [
        {"facility_id": "stub-301", "name": "Sample Clinic (sample)", "travel": _travel(lat, lon, lat + 0.05, lon),
         "reason": f"Our data has no own sentence about {label}: only a list of 40 words"},
        {"facility_id": "stub-302", "name": "Sample Eye Hospital (sample)",
         "travel": _travel(lat, lon, lat, lon + 0.08),
         "reason": f"Its {label} sentence names another hospital"},
    ]
    return {
        "query": query, "location": location, "as_of": as_of, "profile": profile,
        "emergency_numbers": emergency_numbers_, "abstain": None,
        "options": options, "why_not": why_not, "meta": meta,
    }


def area_stub(service: str, lat: float, lon: float) -> dict:
    """Placeholder standing referral plan for the area around a point (spec S11/S12), contract proposal for #31.

    Everything here is invented sample data; the model export (#11, area_metrics and ten-call lists) replaces it.
    """
    label = SERVICES[service]["label_en"]
    first = {"facility_id": "stub-101", "name": "Sample Care Centre (sample)"}
    backup = {"facility_id": "stub-103", "name": "Sample Specialty Centre (sample)"}
    pins = []
    for k in range(6):
        plat, plon = round(lat + 0.04 * (k - 2), 4), round(lon + 0.05 * ((k % 3) - 1), 4)
        travel = _travel(plat, plon, lat + 0.15, lon + 0.08)
        within = k % 3 != 2  # every third sample PIN has no option with public evidence in reach
        pins.append({
            "pin": 843300 + k, "lat": plat, "lon": plon,
            "first": first if within else None, "backup": backup if within else None,
            "travel": travel if within else None,
            "call_first": first["name"] if within else None,
            "nearest_km": None if within else round(travel["km"] * 2, 1),
        })
    n_without = sum(p["first"] is None for p in pins)
    return {
        "query": {"service": service, "service_label": {"en": label, "hi": SERVICES[service]["label_hi"]}},
        "area": {"district": "Sample district", "state": "Sample state", "window_min": 60},
        "as_of": "2026-11-21",
        "summary": {
            "n_pins": len(pins), "n_without_option": n_without,
            "access_now": 0.11, "access_if_confirmed": 0.22,
            "calls_could_close": 0.11, "no_public_evidence": 0.78,
        },
        "caveat": "Low web presence looks like a gap. Verify before deciding.",
        "pins": pins,
        "ten_calls": [
            {"rank": i + 1, "facility_id": f"stub-4{i:02d}", "name": f"Sample Hospital {i + 1} (sample)",
             "phone_kind": ["landline", "own mobile", "shared x3"][i % 3], "areas": 4 - i % 4,
             "access_gain": round(0.06 - 0.005 * i, 3)}
            for i in range(10)
        ],
        "meta": {"stub": True, "model_hash": "stub-0000"},
    }
