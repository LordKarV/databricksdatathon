"""Self-check for kb/pathways/care_pathways.json and capabilities.json: shape, references and the
sourcing rules.

Checks
- required keys and types at every level, unique ids
- every capability and source a pathway refers to is defined; sources have a URL
- capabilities.json lists, for each tag, exactly the pathway stages that use it
- every number (window, dwell, rule threshold) says whether it is a guideline value or an
  assumption; guideline values carry a source id and a quote
- time-critical pathways with more than one stage have an add-stop rule gated on the window
  (a stop is never added unless the definitive facility is outside the window)
- plain ASCII

Standard library only.
Run: python3 kb/pathways/check_pathways.py            (exit code 1 on any error)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE / "care_pathways.json"
CAPS_PATH = HERE / "capabilities.json"

URGENCY = {"emergency", "urgent", "scheduled"}
OBJECTIVE = {"time_critical", "fewest_trips"}
PURPOSE = {"stabilise", "definitive", "assess", "access", "recurring"}
BASIS = {"guideline", "assumption"}
WINDOW_KIND = {"hard", "target"}
RULE_TYPE = {"add_stop_only_if", "skip_stop_if", "never_delay", "before_transfer", "refer_if", "caution"}
ORIGIN = {"india", "international"}
KB_STATUS = {"existing", "proposed"}
LEVELS = {"HWC", "PHC", "CHC", "SDH", "DH", "MC", "private", "programme_unit"}


class Checker:
    def __init__(self):
        self.errors = []

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def need(self, obj, where, key, types, allow_none=False):
        """Return obj[key] if present with the right type, else record an error and return None."""
        if not isinstance(obj, dict) or key not in obj:
            self.err(where, f"missing key '{key}'")
            return None
        v = obj[key]
        if v is None:
            if not allow_none:
                self.err(where, f"'{key}' must not be null")
            return None
        if isinstance(v, bool) or not isinstance(v, types):
            self.err(where, f"'{key}' has type {type(v).__name__}")
            return None
        return v

    def one_of(self, obj, where, key, allowed):
        v = self.need(obj, where, key, str)
        if v is not None and v not in allowed:
            self.err(where, f"'{key}' is '{v}', expected one of {sorted(allowed)}")
        return v

    def sourced(self, obj, where, sources):
        """A number's provenance: guideline needs source + quote, assumption needs a reason."""
        basis = self.one_of(obj, where, "basis", BASIS)
        if basis == "guideline":
            src = self.need(obj, where, "source", str)
            if src is not None and src not in sources:
                self.err(where, f"unknown source '{src}'")
            quote = self.need(obj, where, "quote", str)
            if quote is not None and len(quote.strip()) < 10:
                self.err(where, "guideline value needs a real quote")
        elif basis == "assumption":
            why = self.need(obj, where, "why", str)
            if why is not None and len(why.strip()) < 10:
                self.err(where, "assumption needs a reason in 'why'")

    def positive(self, obj, where, key, allow_none=False):
        v = self.need(obj, where, key, (int, float), allow_none=allow_none)
        if v is not None and v <= 0:
            self.err(where, f"'{key}' must be positive")
        return v


def check(doc, caps_doc):
    c = Checker()
    for key in ("version", "built"):
        c.need(doc, "top", key, str)
    sources = c.need(doc, "top", "sources", dict) or {}
    cap_list = c.need(caps_doc, "capabilities.json", "capabilities", list) or []
    caps = {}
    for i, cap in enumerate(cap_list):
        cid = c.need(cap, f"capabilities[{i}]", "id", str)
        if cid is None:
            continue
        if cid in caps:
            c.err(f"capabilities.{cid}", "duplicate capability id")
        caps[cid] = cap
    pathways = c.need(doc, "top", "pathways", list) or []
    used = {}

    for sid, s in sources.items():
        w = f"sources.{sid}"
        for key in ("title", "publisher"):
            c.need(s, w, key, str)
        c.need(s, w, "year", int, allow_none=True)
        c.one_of(s, w, "origin", ORIGIN)
        url = c.need(s, w, "url", str)
        if url is not None and not url.startswith("https://") and not url.startswith("http://"):
            c.err(w, "url must start with http:// or https://")

    for cid, cap in caps.items():
        w = f"capabilities.{cid}"
        c.need(cap, w, "meaning", str)
        words = c.need(cap, w, "evidence_words", list)
        if words is not None and (not words or not all(isinstance(x, str) and x for x in words)):
            c.err(w, "evidence_words must be a non-empty list of strings")
        c.need(cap, w, "used_by", list)
        status = c.one_of(cap, w, "kb_status", KB_STATUS)
        if status == "existing":
            c.need(cap, w, "kb_service", str)

    seen = set()
    for i, p in enumerate(pathways):
        pid = c.need(p, f"pathways[{i}]", "id", str) or f"#{i}"
        w = f"pathway {pid}"
        if pid in seen:
            c.err(w, "duplicate pathway id")
        seen.add(pid)
        for key in ("name", "service", "clock_start"):
            c.need(p, w, key, str)
        c.one_of(p, w, "urgency", URGENCY)
        objective = c.one_of(p, w, "objective", OBJECTIVE)
        c.need(p, w, "open_questions", list)
        for src in c.need(p, w, "sources", list) or []:
            if src not in sources:
                c.err(w, f"unknown source '{src}'")

        stages = c.need(p, w, "stages", list) or []
        if not stages:
            c.err(w, "needs at least one stage")
        stage_ids = set()
        for j, st in enumerate(stages):
            stid = c.need(st, f"{w} stages[{j}]", "id", str) or f"#{j}"
            ws = f"{w} stage {stid}"
            if stid in stage_ids:
                c.err(ws, "duplicate stage id")
            stage_ids.add(stid)
            c.need(st, ws, "name", str)
            c.one_of(st, ws, "purpose", PURPOSE)
            actions = c.need(st, ws, "actions", list)
            if actions is not None and not actions:
                c.err(ws, "needs at least one action")
            req_all = c.need(st, ws, "requires_all", list) or []
            req_any = c.need(st, ws, "requires_any", list) or []
            if not req_all and not req_any:
                c.err(ws, "needs at least one required capability")
            for cap in req_all:
                used.setdefault(cap, set()).add(f"{pid}.{stid}")
                if cap not in caps:
                    c.err(ws, f"unknown capability '{cap}'")
            for group in req_any:
                if not isinstance(group, list) or len(group) < 2:
                    c.err(ws, "each requires_any group must be a list of two or more capabilities")
                    continue
                for cap in group:
                    used.setdefault(cap, set()).add(f"{pid}.{stid}")
                    if cap not in caps:
                        c.err(ws, f"unknown capability '{cap}'")
            for lv in c.need(st, ws, "facility_levels", list) or []:
                if lv not in LEVELS:
                    c.err(ws, f"unknown facility level '{lv}'")
            window = c.need(st, ws, "window", dict, allow_none=True)
            if window is not None:
                c.positive(window, f"{ws} window", "minutes")
                c.need(window, f"{ws} window", "from", str)
                c.one_of(window, f"{ws} window", "kind", WINDOW_KIND)
                c.sourced(window, f"{ws} window", sources)
            # time spent at this stop before moving on; the last stage has none
            last = j == len(stages) - 1
            dwell = c.need(st, ws, "dwell_minutes", dict, allow_none=last)
            if dwell is not None:
                c.positive(dwell, f"{ws} dwell_minutes", "typical")
                c.sourced(dwell, f"{ws} dwell_minutes", sources)
            repeat = c.need(st, ws, "repeat", dict, allow_none=True)
            if repeat is not None:
                c.positive(repeat, f"{ws} repeat", "per_week")
                c.sourced(repeat, f"{ws} repeat", sources)

        if stages and isinstance(stages[-1], dict) and stages[-1].get("purpose") not in ("definitive", "recurring"):
            c.err(w, "last stage must be definitive or recurring")

        rules = c.need(p, w, "rules", list) or []
        rule_ids = set()
        gated = False
        for j, r in enumerate(rules):
            rid = c.need(r, f"{w} rules[{j}]", "id", str) or f"#{j}"
            wr = f"{w} rule {rid}"
            if rid in rule_ids:
                c.err(wr, "duplicate rule id")
            rule_ids.add(rid)
            rtype = c.one_of(r, wr, "type", RULE_TYPE)
            for key in ("when", "then"):
                c.need(r, wr, key, str)
            stage = c.need(r, wr, "stage", str, allow_none=True)
            if stage is not None and stage not in stage_ids:
                c.err(wr, f"unknown stage '{stage}'")
            cond = c.need(r, wr, "condition", dict, allow_none=True)
            if cond is not None:
                for k, v in cond.items():
                    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                        c.err(wr, f"condition '{k}' must be a number or string")
            if cond and "needs_capability" in cond and cond["needs_capability"] not in caps:
                c.err(wr, f"unknown capability '{cond['needs_capability']}' in condition")
            c.sourced(r, wr, sources)
            if rtype == "add_stop_only_if" and cond and "definitive_travel_minutes_gt" in cond:
                gated = True
        if objective == "time_critical" and len(stages) > 1 and not gated:
            c.err(w, "time-critical pathway with a stabilising stop needs an add_stop_only_if rule "
                     "with condition definitive_travel_minutes_gt")

    for cid, cap in caps.items():
        listed = set(cap.get("used_by") or []) if isinstance(cap, dict) else set()
        actual = used.get(cid, set())
        if listed != actual:
            c.err(f"capabilities.{cid}", f"used_by {sorted(listed)} does not match the pathway stages {sorted(actual)}")
    return c.errors


def main():
    raw = PATH.read_text(encoding="utf-8")
    caps_raw = CAPS_PATH.read_text(encoding="utf-8")
    errors = [f"{name}: non-ASCII character {ch!r} at offset {i}"
              for name, text in (("care_pathways.json", raw), ("capabilities.json", caps_raw))
              for i, ch in enumerate(text) if ord(ch) > 127][:10]
    doc, caps_doc = json.loads(raw), json.loads(caps_raw)
    errors += check(doc, caps_doc)
    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    p = doc["pathways"]
    n_stage = sum(len(x["stages"]) for x in p)
    n_rule = sum(len(x["rules"]) for x in p)
    nums = [n for x in p for st in x["stages"] for n in (st["window"], st["dwell_minutes"], st["repeat"]) if n] \
        + [r for x in p for r in x["rules"]]
    n_guideline = sum(1 for n in nums if n["basis"] == "guideline")
    print(f"OK: {len(p)} pathways, {n_stage} stages, {n_rule} rules, {len(caps_doc['capabilities'])} capabilities, "
          f"{len(doc['sources'])} sources")
    print(f"sourced values: {n_guideline} guideline, {len(nums) - n_guideline} assumption")


if __name__ == "__main__":
    main()
