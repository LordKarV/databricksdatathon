"""Field reports and the field witness. The warehouse is mocked; no network. Run from the repo root:
pytest app/tests/test_field.py -q"""
import json
import sys
import types
import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import outcomes
from community import field, reporter
from community.field import apply_field, field_adjust
from facts.engine import _logit

import app as app_module
from app import app

client = TestClient(app)
needs_data = pytest.mark.skipif(app_module._engine() is None, reason="facility data not built (app/facts/build.py)")
NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)


def rep(key, outcome, kind="visit", reason=None, days=1, **kw):
    return {"reporter_key": key, "kind": kind, "outcome": outcome, "reason": reason,
            "created_at": NOW - timedelta(days=days), **kw}


def accepted(n, days=1):
    return [rep(f"k{i}", "accepted", days=days) for i in range(n)]


# ---------- the update math ----------
def test_more_accepted_reports_raise_the_score_and_stay_bounded():
    ps = [field_adjust(0.4, accepted(n), NOW)["p"] for n in range(2, 40)]
    assert all(a < b for a, b in pairwise(ps))
    assert all(0.4 < p < 1 for p in ps)


def test_more_not_offered_reports_lower_the_score_but_never_below_the_unlikely_line():
    ps = [field_adjust(0.5, [rep(f"k{i}", "turned_away", reason="service_not_here") for i in range(n)], NOW)["p"]
          for n in range(2, 40)]
    assert all(a >= b for a, b in pairwise(ps)) and ps[0] < 0.5
    assert min(ps) == field.T_UNLIKELY  # floored: reports alone never make a public "Unlikely"
    out = field_adjust(0.5, [rep(f"k{i}", "turned_away", reason="equipment_absent") for i in range(30)], NOW)
    assert out["disagree"] and field.DISAGREE in out["lines"]


def test_a_model_score_already_below_the_line_is_not_raised_by_the_floor():
    out = field_adjust(0.1, [rep(f"k{i}", "turned_away", reason="service_not_here") for i in range(5)], NOW)
    assert out["p"] == 0.1 and out["term"] == 0


def test_one_reporter_never_moves_the_score():
    one = [rep("k1", "accepted", days=d) for d in (1, 2, 3, 4)]  # the same person, many times
    out = field_adjust(0.4, one, NOW)
    assert out["p"] == 0.4 and out["term"] == 0 and out["n_reporters"] == 1
    assert field.ONE_REPORTER in out["lines"]
    assert field_adjust(0.4, accepted(2), NOW)["term"] > 0


def test_reports_without_a_reporter_key_do_not_count():
    out = field_adjust(0.4, [rep(None, "accepted"), rep("", "accepted"), rep("k1", "accepted")], NOW)
    assert out["n_reporters"] == 1 and out["term"] == 0


def test_only_each_reporters_latest_report_counts():
    a = field_adjust(0.4, [rep("k1", "accepted", days=1), rep("k1", "accepted", days=2), rep("k2", "accepted")], NOW)
    b = field_adjust(0.4, [rep("k1", "accepted", days=1), rep("k2", "accepted")], NOW)
    assert a["p"] == pytest.approx(b["p"])


def test_a_phone_yes_counts_half_of_an_accepted_visit():
    yes = field_adjust(0.4, [rep(f"k{i}", "yes", kind="call") for i in range(4)], NOW)
    acc = field_adjust(0.4, accepted(2), NOW)
    n0, w = field.N0, 0.5 ** (1 / field.HALF_LIFE_DAYS)
    assert yes["p"] == pytest.approx((n0 * 0.4 + 4 * 0.5 * w) / (n0 + 4 * 0.5 * w))
    assert acc["p"] == pytest.approx((n0 * 0.4 + 2 * w) / (n0 + 2 * w))
    assert yes["p"] == pytest.approx(acc["p"])


def test_older_reports_weigh_less():
    assert field_adjust(0.4, accepted(3, days=2), NOW)["p"] > field_adjust(0.4, accepted(3, days=60), NOW)["p"]
    assert field_adjust(0.4, accepted(3, days=field.WINDOW_DAYS + 1), NOW)["lines"] == []  # out of the window


@pytest.mark.parametrize("reason", outcomes.REASONS_TEMPORARY)
def test_temporary_reasons_only_produce_an_availability_note(reason):
    reports = [rep(f"k{i}", "turned_away", reason=reason, days=i + 1) for i in range(3)]
    reports += [rep("k9", "no", kind="call", reason=reason)]
    out = field_adjust(0.4, reports, NOW)
    assert out["p"] == 0.4 and out["term"] == 0 and out["lines"] == []
    (note,) = out["notes"]
    assert note["en"].startswith(f"4 reports of {field.REASON[reason]['en']} in the last 7 days; latest 1 day ago")
    assert note["hi"]


def test_a_phone_no_without_a_reason_says_nothing_about_the_service():
    out = field_adjust(0.4, [rep(f"k{i}", "no", kind="call") for i in range(5)], NOW)
    assert out["p"] == 0.4 and out["lines"] == [] and out["notes"] == []


def test_the_term_is_exactly_additive_in_log_odds():
    for p0 in (0.05, 0.3, 0.5, 0.81, 0.97):
        for reports in (accepted(3), [rep(f"k{i}", "turned_away", reason="service_not_here") for i in range(3)]):
            out = field_adjust(p0, reports, NOW)
            assert _logit(p0) + out["term"] == pytest.approx(_logit(out["p"]), abs=1e-12)


def test_reports_alone_cannot_lift_a_pair_with_no_service_text_to_likely():
    out = field_adjust(0.30, accepted(40), NOW, has_text=False)  # below the model's Likely line (t_L 0.3686)
    assert out["p"] < field.T_LIKELY and field.NO_TEXT_CAP in out["lines"]
    assert field_adjust(0.30, accepted(40), NOW)["p"] >= field.T_LIKELY


def test_lines_say_what_happened_without_names():
    reports = [rep("k1", "accepted", days=4), rep("k2", "accepted", days=10),
               rep("k3", "turned_away", reason="service_not_here", days=20)]
    out = field_adjust(0.4, reports, NOW)
    assert out["lines"][0]["en"] == ("Reports from 3 health workers in the last 90 days: 2 accepted, "
                                     "1 said the service is not here; latest 4 days ago.")
    assert out["lines"][0]["hi"] and "k1" not in json.dumps(out)


def test_simulated_reports_mark_every_line():
    reports = [{**r, "simulated": True} for r in accepted(2)]
    reports.append(rep("k7", "turned_away", reason="no_bed", simulated=True))
    out = field_adjust(0.4, reports, NOW)
    assert out["simulated"]
    for line in out["lines"] + out["notes"]:
        assert line["en"].startswith("Simulated for the demo: ") and line["hi"].startswith(field.SIM["hi"])


# ---------- rescore: one pair read against the reports ----------
def scored(band="not_verified", p=0.4, ev=("c1",)):
    return band, p, p - 0.1, min(0.99, p + 0.1), [{"label": "evidence", "points": -4}], list(ev)


def not_offered(n, reason="equipment_absent"):
    return [rep(f"k{i}", "turned_away", reason=reason) for i in range(n)]


def test_rescore_adds_one_named_term_and_keeps_a_not_verified_band():
    (band, p, lo, hi, contrib, _), info = field.rescore(scored(), accepted(3), NOW)
    assert band == "not_verified" and p > 0.4 and lo > 0.3 and hi > 0.5
    assert contrib[:-1] == scored()[4] and contrib[-1] == {"label": "Field reports", "points": round(10 * info["term"])}
    assert info["p_model"] == 0.4 and info["n_reporters"] == 3 and not info["rebanded"]


def test_reports_never_raise_a_band():
    (band, p, *_), info = field.rescore(scored(p=0.6), accepted(40), NOW)
    assert band == "not_verified" and p >= field.T_LIKELY and not info["rebanded"]


def test_a_likely_pair_reports_take_below_the_line_becomes_not_verified():
    (band, p, *_), info = field.rescore(scored("likely", 0.97), not_offered(45), NOW)
    assert band == "not_verified" and p == pytest.approx(field.T_UNLIKELY) and info["rebanded"] and info["disagree"]
    assert field.REBANDED in info["lines"] and field.REBANDED["hi"]
    assert info["lines"][-1]["en"] == "Health-worker reports disagree with the listing: call first"


def test_a_likely_pair_still_above_the_line_stays_likely_and_says_call_first():
    (band, p, *_), info = field.rescore(scored("likely", 0.97), not_offered(3, "service_not_here"), NOW)
    assert band == "likely" and field.T_LIKELY <= p < 0.8 and info["disagree"] and not info["rebanded"]
    assert field.DISAGREE in info["lines"]


def test_rescore_uses_no_evidence_as_no_service_text():
    (_, p, *_), _ = field.rescore(scored(p=0.30, ev=()), accepted(40), NOW)
    assert p < field.T_LIKELY


# ---------- apply_field: the plan rebuilt from the adjusted scores (COMMUNITY_CHECK.md 1g) ----------
PATNA = (25.6, 85.1)


def likely_case(service):
    eng = app_module._engine()
    p = eng.plan(service, *PATNA, None, "gps")
    o = next((o for o in p["options"] if o["band"] == "likely"), None)
    if o is None or len(p["options"]) < 2:
        pytest.skip(f"no Likely {service} option among several at {PATNA}")
    return eng, p, o


def rebuilt(service, reports_for):
    eng, before, o = likely_case(service)
    after = apply_field(before, {(o["facility_id"], service): reports_for}, NOW, eng)
    return eng, before, o, after


def check_ledger(eng, service, o):
    """The why page's ledger: the model's rows unchanged plus one Field reports row of exactly the term."""
    model = eng.score(o["facility_id"], service)
    assert o["contributions"][:-1] == model[4] and o["contributions"][-1]["label"] == field.TERM_LABEL
    assert o["contributions"][-1]["points"] == round(10 * o["field"]["term"])
    assert sum(c["points"] for c in o["contributions"]) == sum(c["points"] for c in model[4]) + round(10 * o["field"]["term"])


@needs_data
def test_45_equipment_not_here_reports_rebuild_the_whole_plan():
    eng, before, o, after = rebuilt("cardiac_surgery", not_offered(45))
    fid = o["facility_id"]
    new = next((x for x in after["options"] if x["facility_id"] == fid), None)
    assert before["options"] != after["options"] and not any(x["band"] == "unlikely" for x in after["options"])
    if new is None:  # it dropped out of the top 3; its card as it would read
        scored, info = field.rescore(eng.score(fid, "cardiac_surgery"), not_offered(45), NOW)
        pr = eng.index["cardiac_surgery"][eng.fid[fid]]
        new = field._annotate(eng.option(1, pr, "cardiac_surgery", *PATNA, eng._travel(*PATNA, pr.fi), {fid: scored}),
                              info)
    assert new["band"] == "not_verified" and new["band_reason"] == field.REBANDED["en"]
    assert new["p"] == 0.2 and new["call_first"] and field.DISAGREE["en"] in new["flags"]
    assert "listing mentions" in new["say_to_family"]["en"] and "says it offers" not in new["say_to_family"]["en"]
    assert any(c["question"].startswith(("Can you do", "Do you do")) for c in new["call_ahead"])
    check_ledger(eng, "cardiac_surgery", new)
    # The ranking uses the adjusted p: an option at 0.20 no longer ranks above one the model scores far higher.
    first = after["options"][0]
    assert first["facility_id"] != fid or len(after["options"]) == 1
    text = first["why_first_text"] or ""
    assert f"{o['p']:.2f} against" not in text and "0.97" not in text
    if text:
        assert f"({first['p']:.2f} against" in text
    # why_not and the abstention come from the same re-ranked pool.
    assert eng.plan("cardiac_surgery", *PATNA, None, "gps", {fid: field.rescore(eng.score(fid, "cardiac_surgery"),
                                                                                 not_offered(45), NOW)[0]})["why_not"] \
        == after["why_not"]


@needs_data
def test_3_service_not_here_reports_keep_likely_but_the_card_says_call_first():
    reports = not_offered(3, "service_not_here")
    eng, before, o, after = rebuilt("dialysis", reports)
    new = next((x for x in after["options"] if x["facility_id"] == o["facility_id"]), None)
    if new is None:  # the lowered option can fall out of the top 3 under v2 ranking; check the rescore itself
        scored, fb = field.rescore(eng.score(o["facility_id"], "dialysis"), reports, NOW)
        assert scored[0] == "likely" and field.T_LIKELY <= scored[1] < o["p"] and fb["disagree"]
        return
    assert field.T_LIKELY <= new["p"] < o["p"]
    assert new["band"] == "likely" and new["field"]["disagree"] and new["call_first"]
    assert field.DISAGREE["en"] in new["flags"] and field.DISAGREE in new["field"]["lines"]
    check_ledger(eng, "dialysis", new)


@needs_data
def test_positive_reports_never_raise_a_band_in_the_plan():
    eng = app_module._engine()
    before = eng.plan("dialysis", *PATNA, None, "gps")
    o = next((o for o in before["options"] if o["band"] == "not_verified" and o["evidence"]), None)
    if o is None:
        pytest.skip("no Not verified option with evidence")
    after = apply_field(before, {(o["facility_id"], "dialysis"): accepted(40)}, NOW, eng)
    new = next(x for x in after["options"] if x["facility_id"] == o["facility_id"])
    assert new["band"] == "not_verified" and new["field"]["lines"]


def test_no_reports_for_this_service_return_the_plan_as_it_is():
    p = {"query": {"service": "dialysis"}, "options": [{"facility_id": "F1"}]}
    assert apply_field(p, {("F1", "nicu"): accepted(3)}, NOW, types.SimpleNamespace(fid={}, index={})) is p


# ---------- reporter key ----------
def test_reporter_key_is_a_keyed_hash_and_never_the_user(monkeypatch):
    monkeypatch.setenv("REPORTER_KEY", "s3cret")
    k = reporter.reporter_key({"x-forwarded-email": "Asha.Worker@example.org"})
    assert len(k) == 16 and all(c in "0123456789abcdef" for c in k) and "asha" not in k
    assert k == reporter.reporter_key({"x-forwarded-email": "asha.worker@example.org "})
    monkeypatch.setenv("REPORTER_KEY", "other")
    assert reporter.reporter_key({"x-forwarded-email": "asha.worker@example.org"}) != k
    monkeypatch.delenv("REPORTER_KEY")
    assert reporter.reporter_key({"x-forwarded-email": "asha.worker@example.org"}) is None


# ---------- the write path ----------
@pytest.fixture
def wh(monkeypatch):
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh-1")
    monkeypatch.setenv("REPORTER_KEY", "s3cret")
    field._cache.clear()

    class W:
        calls: list
        select_rows: list

    W.calls, W.select_rows = [], []

    def fake(body):
        W.calls.append(body)
        rows = W.select_rows if body["statement"].lstrip().startswith("SELECT") else []
        return {"status": {"state": "SUCCEEDED"}, "result": {"data_array": rows}}

    monkeypatch.setattr(outcomes, "_sql", fake)
    return W


def a_pair():
    eng = app_module._engine()
    svc, rows = next(iter(eng.pairs.items()))
    return eng.fac["id"][rows[0].fi], svc


def body(**kw):
    fid, svc = a_pair()
    return {"outcome_id": str(uuid.uuid4()), "facility_id": fid, "service_id": svc, "outcome": "yes",
            "said_at_ms": int(NOW.timestamp() * 1000), "lat": 26.6, "lon": 85.48, **kw}


def params(call):
    return {p["name"]: p["value"] for p in call["parameters"]}


USER = {"X-Forwarded-Email": "asha.worker@example.org", "X-Forwarded-User": "1234567890@4242"}


@needs_data
def test_old_request_shape_without_a_user_writes_the_old_statement(wh, monkeypatch):
    monkeypatch.delenv("REPORTER_KEY")
    r = client.post("/api/outcome", json=body())
    assert r.status_code == 200
    (call,) = wh.calls  # no rate check without a key
    assert set(params(call)) == {"outcome_id", "facility_id", "service_id", "outcome", "questions",
                                 "model_version", "district", "created_at", "app_version"}
    assert "kind" not in call["statement"] and "reporter_key" not in call["statement"]


@needs_data
def test_a_visit_report_stores_the_hash_never_the_user(wh):
    b = body(kind="visit", outcome="turned_away", reason="no_bed", wait_bucket="gt_2h")
    r = client.post("/api/outcome", json=b, headers=USER)
    assert r.status_code == 200, r.text
    check, merge = wh.calls
    assert check["statement"].lstrip().startswith("SELECT") and merge["statement"].startswith("MERGE INTO")
    p = params(merge)
    assert p["kind"] == "visit" and p["reason"] == "no_bed" and p["wait_bucket"] == "gt_2h"
    assert p["reporter_key"] == reporter.reporter_key({"x-forwarded-user": USER["X-Forwarded-User"]})
    sent = json.dumps(wh.calls)
    assert "asha" not in sent and "1234567890" not in sent and "26.6" not in sent


@needs_data
def test_the_stored_time_is_cut_to_the_hour_before_the_write(wh):
    said = datetime.now(UTC).replace(minute=37, second=12) - timedelta(hours=1)
    b = body(kind="visit", outcome="accepted", said_at_ms=int(said.timestamp() * 1000))
    assert client.post("/api/outcome", json=b, headers=USER).status_code == 200
    check, merge = wh.calls
    assert params(merge)["created_at"] == said.strftime("%Y-%m-%d %H:00:00")
    assert params(check)["since"].endswith(":00:00") and params(check)["until"].endswith(":00:00")


@needs_data
def test_every_value_is_a_named_parameter_never_spliced_into_sql(wh):
    b = body(kind="visit", outcome="accepted", wait_bucket="lt_30m")
    assert client.post("/api/outcome", json=b, headers=USER).status_code == 200
    for call in wh.calls:
        for name, value in params(call).items():
            assert f":{name}" in call["statement"]
            if value and len(value) > 3:
                assert value not in call["statement"]


@needs_data
def test_rate_limit_one_report_per_reporter_pair_and_kind_per_day(wh):
    wh.select_rows = [[str(uuid.uuid4())]]  # another report by this key in the window
    r = client.post("/api/outcome", json=body(), headers=USER)
    assert r.status_code == 429 and not r.json()["ok"]
    assert len(wh.calls) == 1 and "MERGE" not in wh.calls[0]["statement"]
    p = params(wh.calls[0])
    assert p["kind"] == "call" and p["reporter_key"] and p["since"] < p["until"]


@needs_data
def test_a_retried_flush_of_the_same_report_is_not_rate_limited(wh):
    b = body()
    wh.select_rows = [[b["outcome_id"]]]
    assert client.post("/api/outcome", json=b, headers=USER).status_code == 200
    assert wh.calls[-1]["statement"].startswith("MERGE INTO")


@needs_data
@pytest.mark.parametrize("bad", [
    {"kind": "visit", "outcome": "yes"}, {"kind": "call", "outcome": "accepted"},
    {"outcome": "yes", "reason": "no_bed"}, {"kind": "visit", "outcome": "accepted", "reason": "no_bed"},
    {"outcome": "no", "reason": "the nurse was rude"}, {"outcome": "no", "wait_bucket": "lt_30m"},
    {"kind": "visit", "outcome": "accepted", "wait_bucket": "3 hours"}, {"kind": "review"}, {"comment": "bad"}])
def test_bad_combinations_and_free_text_are_rejected(wh, bad):
    assert client.post("/api/outcome", json=body(**bad), headers=USER).status_code == 422
    assert wh.calls == []


# ---------- the read path ----------
def test_aggregates_read_once_a_minute_and_survive_a_missing_warehouse(monkeypatch):
    field._cache.clear()
    monkeypatch.delenv("COMMUNITY_DEMO", raising=False)
    calls = []

    def fake(body):
        calls.append(body)
        return {"status": {"state": "SUCCEEDED"}, "result": {"data_array": [
            ["F1", "dialysis", "abcdabcdabcdabcd", "visit", "accepted", None, "2026-11-20T10:00:00.000Z"]]}}

    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh-1")
    monkeypatch.setattr(outcomes, "_sql", fake)
    a = field.aggregates(NOW)
    field.aggregates(NOW)
    assert len(calls) == 1 and "reporter_key IS NOT NULL" in calls[0]["statement"]
    (r,) = a[("F1", "dialysis")]
    assert r["created_at"] == datetime(2026, 11, 20, 10, tzinfo=UTC)
    field._cache.clear()
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID")
    assert field.aggregates(NOW) == {}


@needs_data
def test_demo_reports_are_simulated_in_memory_and_reach_a_real_plan(monkeypatch):
    field._cache.clear()
    monkeypatch.setenv("COMMUNITY_DEMO", "1")
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    writes = []
    monkeypatch.setattr(outcomes, "_sql", lambda b: writes.append(b))
    sim = field.simulated_reports()
    assert sim and all(r["simulated"] for r in sim)
    now = datetime.now(UTC)
    p = app_module._engine().plan("dialysis", *field.DEMO_POINT, None, "gps")
    out = apply_field(p, field.aggregates(now), now)
    shown = [o["field"] for o in out["options"] if "field" in o]
    assert shown and writes == []
    for f in shown:
        for line in f["lines"] + f["notes"]:
            assert line["en"].startswith("Simulated for the demo: ")


def test_band_lines_match_the_model_card():
    """The field rules use the shipped model's own band lines, not a second set of numbers."""
    import json
    from pathlib import Path
    card = Path(__file__).resolve().parents[2] / "derived" / "v2" / "model_card.json"
    if not card.is_file():
        pytest.skip("model card not present")
    bt = json.loads(card.read_text())["band_thresholds"]
    assert abs(field.T_LIKELY - bt["likely"]["p"]) < 1e-3 and abs(field.T_UNLIKELY - bt["unlikely"]["p"]) < 1e-9


# ---------- tie-break from health-worker reports (#86) ----------
def test_tie_value_counts_accepted_and_half_phone_yes_never_temporary_reasons():
    base = [rep("k1", "accepted", days=0), rep("k2", "yes", kind="call", days=0)]
    assert field_adjust(0.5, base, NOW)["net"] == 1.5
    temporary = [rep(f"t{i}", "turned_away", reason=r, days=0) for i, r in enumerate(outcomes.REASONS_TEMPORARY)]
    assert field_adjust(0.5, base + temporary, NOW)["net"] == 1.5
    against = [rep("k3", "turned_away", reason="service_not_here", days=0),
               rep("k4", "no", kind="call", reason="equipment_absent", days=0)]
    assert field_adjust(0.5, base + against, NOW)["net"] == 0.0  # 1.5 - 1 (visit) - 0.5 (phone)
    assert field_adjust(0.5, [rep("k1", "accepted", days=30), rep("k2", "accepted", days=30)], NOW)["net"] == 1.0
    assert field_adjust(0.5, base[:1], NOW)["net"] is None  # one reporter: no value


def test_tied_prefix_needs_same_band_and_both_limits_for_every_pair():
    from facts.engine import tied_prefix
    assert tied_prefix([(0.9, 60, "likely"), (0.86, 69, "likely"), (0.84, 61, "likely")]) == 2  # 0.9 - 0.84 > 0.05
    assert tied_prefix([(0.9, 60, "likely"), (0.9, 71, "likely")]) == 0
    assert tied_prefix([(0.9, 60, "likely"), (0.9, 60, "not_verified")]) == 0
    assert tied_prefix([(0.9, 60, "likely"), (0.85, 70, "likely"), (0.9, 62, "likely")]) == 3


def demo_plan(eng, service):
    return eng.plan(service, *field.DEMO_POINT, None, "gps")


def keyed(fid, keys, service="dialysis"):
    return {(fid, service): [{**rep(k, "accepted", days=2), "facility_id": fid, "service_id": service}
                             for k in keys]}


@needs_data
def test_tied_options_reorder_only_with_two_or_more_reporters():
    eng = app_module._engine()
    before = demo_plan(eng, "dialysis")
    ids = [o["facility_id"] for o in before["options"]]
    assert len(ids) == 3 and len({o["band"] for o in before["options"]}) == 1
    one = apply_field(before, keyed(ids[2], ["k1", "k1"]), NOW, eng)
    assert [o["facility_id"] for o in one["options"]] == ids and "tie_break" not in one
    agg = keyed(ids[2], ["k1", "k2"])
    two = apply_field(before, agg, NOW, eng)
    # The field term alone leaves it third; the tie-break puts it first.
    third = field.rescore(eng.score(ids[2], "dialysis"), agg[(ids[2], "dialysis")], NOW)[0]
    assert [o["facility_id"] for o in eng.plan("dialysis", *field.DEMO_POINT, None, "gps",
                                               {ids[2]: third})["options"]] == ids
    assert [o["facility_id"] for o in two["options"]] == [ids[2], ids[0], ids[1]]
    tb = two["tie_break"]
    assert tb["label"] == field.TIE_LABEL and not tb["simulated"] and tb["moved"]
    assert [x["facility_id"] for x in tb["options"]] == [ids[2], ids[0], ids[1]]
    assert [x["n_reporters"] for x in tb["options"]] == [2, 0, 0] and tb["options"][1]["net"] is None


@needs_data
def test_untied_options_never_move():
    eng = app_module._engine()
    before = demo_plan(eng, "mri")  # option 2 is more than 10 min farther than option 1: no tie
    ids = [o["facility_id"] for o in before["options"]]
    after = eng.plan("mri", *field.DEMO_POINT, None, "gps", None, {ids[1]: 9.0, ids[2]: 9.0})
    assert [o["facility_id"] for o in after["options"]] == ids and "tie_break" not in after
    assert after["why_not"] == before["why_not"]


@needs_data
@pytest.mark.parametrize("service", ["emergency_csection", "trauma_emergency", "burn_care", "nicu"])
def test_emergencies_and_nicu_never_move(service):
    """Emergency and urgent (NICU) orders never move on report counts (#116: TIE_BREAK_PROFILES)."""
    eng = app_module._engine()
    before = demo_plan(eng, service)
    ids = [o["facility_id"] for o in before["options"]]
    after = eng.plan(service, *field.DEMO_POINT, None, "gps", None, {f: 9.0 * (k + 1) for k, f in enumerate(ids)})
    assert [o["facility_id"] for o in after["options"]] == ids and "tie_break" not in after
    agg = {}
    for f in ids[1:]:
        agg.update(keyed(f, ["k1", "k2", "k3"], service))
    out = apply_field(before, agg, NOW, eng)
    term_only = eng.plan(service, *field.DEMO_POINT, None, "gps",
                         {f: field.rescore(eng.score(f, service), agg[(f, service)], NOW)[0] for f in ids[1:]})
    assert "tie_break" not in out
    assert [o["facility_id"] for o in out["options"]] == [o["facility_id"] for o in term_only["options"]]


@needs_data
def test_simulated_demo_reports_break_the_tie_and_stay_labelled(monkeypatch):
    field._cache.clear()
    monkeypatch.setenv("COMMUNITY_DEMO", "1")
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    monkeypatch.setattr(outcomes, "_sql", lambda b: None)
    eng, now = app_module._engine(), datetime.now(UTC)
    before = demo_plan(eng, "dialysis")
    out = apply_field(before, field.aggregates(now), now, eng)
    tb = out["tie_break"]
    assert tb["simulated"] and tb["moved"] and tb["label"] == field.TIE_LABEL + " (simulated for the demo)"
    assert out["options"][1]["facility_id"] == before["options"][2]["facility_id"]
    for o in out["options"]:
        assert all(x["en"].startswith("Simulated for the demo: ") for x in o["field"]["lines"] + o["field"]["notes"])
    field._cache.clear()
