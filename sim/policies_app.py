"""The app as referral policies (issue #92). Policies never see the truth: only what the app shows a worker.

- app: the product as shipped. With mobile data, Engine.plan on derived/v2 (the deployed /api/plan), options in
  order. Without data, the offline state pack the phone saved (app/packs, read the way app/static/pack.js reads it).
  Field reports are OFF.
- app_offline: the state pack only, as if the phone never had data.
- app_before_101 (diagnostic, not in the minimum run): the app with the emergency order it had before PR #101,
  p x exp(-minutes / 45) best first, kept so the notebook can show what that change did. It reads
  ctx["app_before_101"], an AppAdapter(old_emergency_rank=True); planned care is ranked the same as by app.
- app_plus_reports (future work, not in the minimum run): the same answers re-ranked with a Beta update from earlier
  field reports (sim/reports.py). Each facility-service starts at Beta(p k, (1 - p) k), k = Assumptions.report_k.

call_first is True on every step. The app tells the worker to phone every option before going: each option's
say_to_family ends "We will phone before going" whatever its band (app/facts/engine.py option()), not-verified bands
read "call to confirm" (app/static/app.js bandHtml), and the offline screen heads its list "Call before you go"
(app/static/offline.js). Every policy tries at most N_OPTIONS facilities (equal caps).
"""
from __future__ import annotations

import math
from typing import Any

from sim.app_adapter import AppAdapter
from sim.assumptions import DEFAULT
from sim.interface import N_OPTIONS, Case, Step

CALL_FIRST = True


def online_steps(case: Case, app: AppAdapter) -> list[Step]:
    opts = app.options(case.service, case.lat, case.lon)
    return [Step(o["facility_id"], CALL_FIRST, f"online {k}: {o['model_band'] or o['band']} p={o['p']:.2f}")
            for k, o in enumerate(opts[:N_OPTIONS], 1)]


def offline_steps(case: Case, app: AppAdapter) -> list[Step]:
    """The pack's cards in screen order (nearest first). A pack can show a 4th card (the nearest likely listing);
    the equal cap keeps the first N_OPTIONS."""
    opts = app.pack_options(case.state, case.service, case.lat, case.lon)
    return [Step(o["facility_id"], CALL_FIRST, f"offline {k}: {'likely' if o['likely'] else 'not verified'} "
                 f"{o['km_straight']} km") for k, o in enumerate(opts[:N_OPTIONS], 1)]


class AppPolicy:
    name = "app"

    def choose(self, case: Case, ctx: dict[str, Any]) -> list[Step]:
        return online_steps(case, ctx["app"]) if case.has_data else offline_steps(case, ctx["app"])


class AppOfflinePolicy:
    name = "app_offline"

    def choose(self, case: Case, ctx: dict[str, Any]) -> list[Step]:
        return offline_steps(case, ctx["app"])


class AppBefore101Policy:
    name = "app_before_101"

    def choose(self, case: Case, ctx: dict[str, Any]) -> list[Step]:
        return AppPolicy().choose(case, {"app": ctx["app_before_101"]})


def context(app: AppAdapter) -> dict[str, Any]:
    """The app policies' ctx: the shipped app, and the same engine under the order before PR #101."""
    return {"app": app, "app_before_101": AppAdapter(app.engine, old_emergency_rank=True)}


class AppPlusReportsPolicy:
    """Future work (owner's decision on #92): kept so the hook exists, left out of the minimum run.

    ctx["beliefs"] is a sim.reports.Beliefs built from earlier waves' field reports, never from truth.
    """
    name = "app_plus_reports"

    def choose(self, case: Case, ctx: dict[str, Any]) -> list[Step]:
        app: AppAdapter = ctx["app"]
        beliefs = ctx["beliefs"]
        k = ctx.get("report_k", DEFAULT.report_k)
        if case.has_data:
            scale = app.time_scale(case.service)
            pool = app.pool(case.service, case.lat, case.lon)
            ranked = sorted(pool, key=lambda o: -beliefs.posterior(o["facility_id"], case.service, o["p"], k)
                            * math.exp(-o["minutes"] / scale))
            return [Step(o["facility_id"], CALL_FIRST, "online + reports") for o in ranked[:N_OPTIONS]]
        opts = app.pack_options(case.state, case.service, case.lat, case.lon)
        ranked = sorted(opts, key=lambda o: (-round(beliefs.posterior(o["facility_id"], case.service, o["p"], k), 1),
                                             o["km_straight"]))
        return [Step(o["facility_id"], CALL_FIRST, "offline + reports") for o in ranked[:N_OPTIONS]]


POLICIES: dict[str, Any] = {"app": AppPolicy(), "app_offline": AppOfflinePolicy()}
FUTURE: dict[str, Any] = {"app_plus_reports": AppPlusReportsPolicy()}
DIAGNOSTIC: dict[str, Any] = {"app_before_101": AppBefore101Policy()}  # opt-in: simulate(policies=[...])
