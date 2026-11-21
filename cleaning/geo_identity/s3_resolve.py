"""Step 3: turn what a user types (PIN, coordinates, district, city, 'city, state') into a point,
or into a question back to the user when the answer is ambiguous.

Order (GEO-08 plus the verifier's changes):
  1 'lat, lon'                        -> point if inside India
  2 6-digit PIN                       -> PIN gazetteer (also the 134 facility PINs the directory lacks)
  3 optional trailing state ('Jaipur Rajasthan', 'Aurangabad, Bihar') narrows every later step
  4 exact district / city name (+ aliases, which ADD candidates and never replace: 'bijapur' keeps
    Bijapur, Chhattisgarh next to Vijayapura, Karnataka) -> one state: ok; several: ask which state
  5 a state name alone ('goa'), checked after the name lookup -> ask which district
  6 India Post office name            -> 'confirm' only (a village office named 'Hydrabad' exists in UP)
  7 fuzzy (ratio >= 80) over district and city names -> 'did you mean' list, never auto-picked
Statuses: ok | ask_state | confirm | did_you_mean | not_found.
Writes place_gazetteer.parquet, resolve_tests.csv, s3_stats.json.
"""
import json
import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from common import OUT, hav_km, norm
from geo_common import CITY_ALIAS, STATE_ALIAS
from places import build_layers

ALIAS_ADD = {**{k: [v] for k, v in CITY_ALIAS.items() if k != "bijapur"},
             "bijapur": ["vijayapura", "bijapur"], "bangalore": ["bengaluru urban", "bengaluru"],
             "gurgaon": ["gurugram"], "gurugram": ["gurugram"], "bombay": ["mumbai"],
             "hyderabad": ["hyderabad"], "secunderabad": ["secunderabad", "hyderabad"],
             "noida": ["gautam buddha nagar", "noida"], "greater noida": ["gautam buddha nagar"],
             "navi mumbai": ["navi mumbai", "thane"], "mohali": ["s a s nagar", "mohali"],
             "trivandrum": ["thiruvananthapuram"], "vizag": ["visakhapatnam", "visakhapatanam"],
             "ahmedabad": ["ahmadabad", "ahmedabad"], "raigad": ["raigad"], "raigarh": ["raigarh"]}
FUZZY_MIN = 80


def city_layer() -> pd.DataFrame:
    """Facility city names -> median of their resolved points (high/medium confidence only), with
    points more than 50 km from the first median dropped (the raw city layer had Noida p90 243 km)."""
    loc = pd.read_parquet(OUT / "facility_location.parquet")
    loc = loc[loc.loc_conf.isin(["high", "medium"])].assign(name=lambda d: d.address_city.map(norm))
    loc = loc.rename(columns={"loc_lat": "lat", "loc_lon": "lon", "state_final": "state"})
    loc = loc[loc.name != ""]
    m = loc.groupby(["state", "name"])[["lat", "lon"]].transform("median")
    loc = loc[hav_km(loc.lat, loc.lon, m.lat, m.lon) <= 50]
    g = loc.groupby(["state", "name"])
    out = g[["lat", "lon"]].median().assign(n_points=g.size()).reset_index()
    out = out[out.n_points >= 2]
    j = loc.merge(out[["state", "name", "lat", "lon"]], on=["state", "name"], suffixes=("", "_m"))
    sp = hav_km(j.lat, j.lon, j.lat_m, j.lon_m).groupby([j.state, j.name]).quantile(0.9).round(1)
    return out.join(sp.rename("spread_km"), on=["state", "name"])


class Resolver:
    def __init__(self):
        L = build_layers()
        self.gz = pd.read_parquet(OUT / "pin_gazetteer.parquet").dropna(subset=["lat"]).set_index("pin")
        self.layers = {"district": L["district"], "city": city_layer(), "office": L["office"]}
        self.states = sorted(set(self.layers["district"].state))
        self.state_names = {norm(s): s for s in self.states} | {k: v for k, v in STATE_ALIAS.items()}
        self.names = sorted(set(self.layers["district"].name) | set(self.layers["city"].name))

    def _cands(self, kind, names, state):
        t = self.layers[kind]
        hit = t[t.name.isin(names)]
        return hit[hit.state == state] if state else hit

    @staticmethod
    def _out(status, rows, note):
        return {"status": status, "candidates": rows, "note": note}

    def _rows(self, hit, kind):
        rows = [dict(label=r.name, state=r.state, kind=kind, lat=round(float(r.lat), 5), lon=round(float(r.lon), 5),
                     radius_km=round(max(float(r.spread_km), 2.0), 1)) for r in hit.itertuples()]
        return sorted(rows, key=lambda x: x["state"])

    def resolve(self, q: str) -> dict:
        s = (q or "").strip()
        m = re.fullmatch(r"\s*(-?\d{1,2}\.\d+)\s*[, ]\s*(-?\d{2,3}\.\d+)\s*", s)
        if m:
            la, lo = float(m.group(1)), float(m.group(2))
            if 6 <= la <= 37.6 and 68 <= lo <= 97.6:
                return self._out("ok", [dict(label="coordinates", state=None, kind="coordinates", lat=la, lon=lo, radius_km=0.1)], "Coordinates used as given.")
            return self._out("not_found", [], "Those coordinates are outside India.")
        digits = re.sub(r"\s", "", s)
        if re.fullmatch(r"\d{6}", digits):
            pin = int(digits)
            if pin in self.gz.index:
                r = self.gz.loc[pin]
                return self._out("ok", [dict(label=f"PIN {pin}", state=r.state, kind="pin", lat=float(r.lat), lon=float(r.lon),
                                             radius_km=float(r.radius_km))], f"Centre of PIN {pin} ({r.district}), accurate to about {r.radius_km:.0f} km.")
            return self._out("not_found", [], f"PIN {pin} is not in the India Post directory; try the town name.")
        n = norm(s)
        state = None
        for sn in sorted(self.state_names, key=len, reverse=True):  # trailing state: 'jaipur rajasthan'
            if n.endswith(" " + sn) and len(n) > len(sn) + 2:
                state, n = self.state_names[sn], n[: -len(sn)].strip()
                break
        names = set(ALIAS_ADD.get(n, [])) | {n}
        for kind in ("district", "city"):
            hit = self._cands(kind, names, state)
            if kind == "city" and len(hit):  # a city name that is also a district elsewhere stays one place per state
                hit = hit.sort_values("n_points", ascending=False).drop_duplicates("state")
            if len(hit):
                rows = self._rows(hit.drop_duplicates("state"), kind)
                if len(rows) == 1:
                    return self._out("ok", rows, f"Matched {kind} '{rows[0]['label']}', {rows[0]['state']}.")
                return self._out("ask_state", rows, f"'{s}' exists in {len(rows)} states; which one?")
        if n in self.state_names and not state:  # after the name lookup, so 'Delhi' or 'Pondicherry' still resolve
            st = self.state_names[n]
            d = self.layers["district"]
            return self._out("ask_state", self._rows(d[d.state == st], "district"), f"'{s}' is a state; which district?")
        fz = process.extract(n, self.names, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN, limit=4)
        sug = []
        for name, score, _ in fz:
            for kind in ("district", "city"):
                h = self._cands(kind, {name}, state)
                sug += [dict(r, score=round(score)) for r in self._rows(h.drop_duplicates("state"), kind)]
        sug = list({(x["label"], x["state"]): x for x in sug}.values())[:6]
        off = self._cands("office", {n}, state)
        off = off[off.spread_km <= 30]
        if len(off):
            orow = self._rows(off, "post office")
            return self._out("confirm", sug + orow, f"'{s}' is only a post-office name ({', '.join(r['state'] for r in orow)}); please confirm"
                             + (" or pick a suggestion." if sug else "."))
        if sug:
            return self._out("did_you_mean", sug, "No exact match; did you mean one of these?")
        return self._out("not_found", [], f"Could not find '{s}'. Try a PIN code or the district name.")


# (typed, expected status, expected state of the first/only candidate or a state that must be listed)
TESTS = [("Jaipur", "ok", "RAJASTHAN"), ("Lucknow", "ok", "UTTAR PRADESH"), ("Patna", "ok", "BIHAR"),
         ("Gurgaon", "ok", "HARYANA"), ("Gurugram", "ok", "HARYANA"), ("Bombay", "ok", "MAHARASHTRA"),
         ("Mumbai", "ok", "MAHARASHTRA"), ("Bangalore", "ok", "KARNATAKA"), ("Bengaluru", "ok", "KARNATAKA"),
         ("Madras", "ok", "TAMIL NADU"), ("Calcutta", "ok", "WEST BENGAL"), ("Kolkata", "ok", "WEST BENGAL"),
         ("Trivandrum", "ok", "KERALA"), ("Cochin", "ok", "KERALA"), ("Kochi", "ok", "KERALA"),
         ("Vizag", "ok", "ANDHRA PRADESH"), ("Mysore", "ok", "KARNATAKA"), ("Allahabad", "ok", "UTTAR PRADESH"),
         ("Prayagraj", "ok", "UTTAR PRADESH"), ("Baroda", "ok", "GUJARAT"), ("Poona", "ok", "MAHARASHTRA"),
         ("Noida", "ok", "UTTAR PRADESH"), ("Navi Mumbai", "ok", "MAHARASHTRA"), ("Secunderabad", "ok", "TELANGANA"),
         ("Mohali", "ok", "PUNJAB"), ("Darbhanga", "ok", "BIHAR"), ("Muzaffarpur", "ok", "BIHAR"),
         ("Aurangabad", "ask_state", "BIHAR"), ("Bilaspur", "ask_state", "HIMACHAL PRADESH"),
         ("Hamirpur", "ask_state", "UTTAR PRADESH"), ("Pratapgarh", "ask_state", "RAJASTHAN"),
         ("Raigarh", "ok", "CHHATTISGARH"), ("Raigad", "ok", "MAHARASHTRA"), ("Rampur", "ok", "UTTAR PRADESH"),
         ("Balrampur", "ask_state", "CHHATTISGARH"), ("Jaipur Rajasthan", "ok", "RAJASTHAN"),
         ("Aurangabad, Bihar", "ok", "BIHAR"), ("Hydrabad", "confirm", "TELANGANA"), ("Lucknw", "did_you_mean", "UTTAR PRADESH"),
         ("Bhubaneshwar", "ok", "ODISHA"), ("Pondicherry", "ok", "PUDUCHERRY"), ("Thane", "ok", "MAHARASHTRA"),
         ("Bijapur", "ask_state", "CHHATTISGARH"), ("Goa", "ask_state", "GOA"), ("Patana", "confirm", "BIHAR"),
         ("560017", "ok", "KARNATAKA"), ("422009", "ok", "MAHARASHTRA"), ("500063", "ok", "TELANGANA"),
         ("110001", "ok", "DELHI"), ("999999", "not_found", None), ("26.85, 80.95", "ok", None),
         ("51.5, -0.12", "not_found", None), ("Xyzabad", "not_found", None), ("Kaithal", "ok", "HARYANA")]


def main():
    R = Resolver()
    rows = []
    for q, exp_status, exp_state in TESTS:
        r = R.resolve(q)
        states = [c["state"] for c in r["candidates"]]
        ok = r["status"] == exp_status and (exp_state is None or exp_state in states)
        first = r["candidates"][0] if r["candidates"] else {}
        rows.append(dict(typed=q, status=r["status"], expected_status=exp_status, expected_state=exp_state,
                         states="|".join(sorted({s for s in states if s})), first_label=first.get("label"),
                         radius_km=first.get("radius_km"), passed=ok, note=r["note"]))
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "resolve_tests.csv", index=False)
    gaz = pd.concat([v.assign(kind=k) for k, v in R.layers.items()], ignore_index=True)
    gaz.to_parquet(OUT / "place_gazetteer.parquet", index=False)
    st = {"tests": len(t), "passed": int(t.passed.sum()), "status_counts": t.status.value_counts().to_dict(),
          "failed": t[~t.passed][["typed", "status", "expected_status", "states"]].values.tolist(),
          "gazetteer_rows_by_kind": gaz.kind.value_counts().to_dict(),
          "city_layer_spread_p90_quantiles_50_90_99": R.layers["city"].spread_km.quantile([0.5, 0.9, 0.99]).round(1).tolist()}
    (OUT / "s3_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(t[["typed", "status", "states", "first_label", "passed"]].to_string())
    print(json.dumps(st, indent=1, default=str))


if __name__ == "__main__":
    main()
