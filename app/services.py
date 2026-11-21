"""Shared definitions for the plan contract: services, band words, travel rows and emergency numbers.

Used by the real data engine (facts/engine.py, #42) and by the stub fixture (stub_data.py).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Literal, TypedDict

Profile = Literal["emergency", "urgent", "scheduled", "planned"]
Band = Literal["likely", "not_verified", "unlikely"]


class ServiceInfo(TypedDict):
    label_en: str
    label_hi: str
    profile: Profile


SERVICES: dict[str, ServiceInfo] = {
    "emergency_csection": {
        "label_en": "emergency C-section",
        "label_hi": "\u0911\u092a\u0930\u0947\u0936\u0928 \u0938\u0947 \u0921\u093f\u0932\u0940\u0935\u0930\u0940",
        "profile": "emergency",
    },
    "nicu": {
        "label_en": "newborn intensive care (NICU)",
        "label_hi": "\u0928\u0935\u091c\u093e\u0924 ICU",
        "profile": "urgent",
    },
    "trauma_emergency": {
        "label_en": "accident and injury care",
        "label_hi": "\u090f\u0915\u094d\u0938\u0940\u0921\u0947\u0902\u091f / \u091a\u094b\u091f",
        "profile": "emergency",
    },
    "burn_care": {
        "label_en": "burn care",
        "label_hi": "\u091c\u0932\u0928\u093e",
        "profile": "emergency",
    },
    "dialysis": {
        "label_en": "dialysis",
        "label_hi": "\u0921\u093e\u092f\u0932\u093f\u0938\u093f\u0938",
        "profile": "scheduled",
    },
    "mri": {
        "label_en": "MRI scan",
        "label_hi": "MRI \u0938\u094d\u0915\u0948\u0928",
        "profile": "planned",
    },
    "cardiac_surgery": {
        "label_en": "heart surgery",
        "label_hi": "\u0926\u093f\u0932 \u0915\u093e \u0911\u092a\u0930\u0947\u0936\u0928",
        "profile": "planned",
    },
}

# Fallback only when geo/ is not importable (app folder deployed alone): the #7 constants.
ROAD_FACTOR = 1.35
SPEED_HI_KMH = 65.1
SPEED_LO_KMH = 40.0

try:  # geo/ lives at the repo root, one level above app/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from geo.travel import estimate as _geo_estimate
except ImportError:  # pragma: no cover - exercised only when deployed without geo/
    _geo_estimate = None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def travel(lat: float, lon: float, flat: float, flon: float) -> dict:
    """One geo/travel.py estimate row (#14): measured factor, speed and percentile range, no OSRM call."""
    if _geo_estimate is not None:
        return _geo_estimate((lat, lon), (flat, flon))
    road = haversine_km(lat, lon, flat, flon) * ROAD_FACTOR
    return {
        "minutes": round(road / SPEED_HI_KMH * 60),
        "low": round(road / SPEED_HI_KMH * 60),
        "high": round(road / SPEED_LO_KMH * 60),
        "km": round(road, 1),
        "method": "haversine_factor",
        "cached": False,
        "factor": ROAD_FACTOR,
        "kmh": SPEED_HI_KMH,
        "terrain": None,
        "label": f"rough estimate: straight line x {ROAD_FACTOR} (geo/ not available)",
    }


BAND_WORDS: dict[str, str] = {"likely": "Likely", "not_verified": "Not verified", "unlikely": "Unlikely"}


def emergency_numbers(service: str) -> list[dict]:
    nums = [{"number": "108", "label": "Ambulance (free)"}]
    if service in ("emergency_csection", "nicu"):
        nums.append({"number": "102", "label": "Pregnant women and babies (free). No answer? Call 108"})
    return nums
