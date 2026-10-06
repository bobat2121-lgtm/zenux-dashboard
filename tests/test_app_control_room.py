"""AppTest: the Control room (builder only): today's diagnostics for every workspace, acknowledgements and the stage
switch (toasts, undo, confirmation), the technical module view, backfill, coverage requests to review and the
configuration notes."""

from __future__ import annotations

import unittest
from typing import Any

import fixtures as fx
import fixtures_coverage as fc
import fixtures_tuning as fp
from helpers import (AppCase, BETA_COV, BETA_HUB, BETA_READ, BETA_RUN, BUILDER_PIN, Call, FakeResponse, OWNER,
                     PILOT_AI, PILOT_DEF, PILOT_HUB, PIN, READ, RUN_AI, RUN_DEF, hub_defaults, one_workspace,
                     two_workspaces)
from zenux_dashboard import company_names_view as cnv
from zenux_dashboard import control_view, ui
from zenux_dashboard.fmt import esc
INSPECT_AI = PILOT_HUB + "/modules/ai-infra/inspect"
INSPECT_DEF = PILOT_HUB + "/modules/defense-unmanned/inspect"
STAGE = PILOT_HUB + "/admin/stage"
CONFIRM = "dlg_save"  # the confirm button of ui.ask_confirm (dialog keys are dlg_*)


def undo_of(at) -> Any:
    try:
        return at.session_state[ui.UNDO_KEY]
    except KeyError:
        return None


def field(obj: Any, name: str) -> Any:
    return getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)


def with_builder(secrets: dict) -> dict:
    return {**secrets, "builder_pin": BUILDER_PIN}


class ControlCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        h = self.http
        h.on("GET", PILOT_HUB + "/diagnostics", fx.diagnostics())
        h.on("GET", PILOT_HUB + "/snapshot", fx.snapshot())
        h.on("GET", PILOT_AI + "/health", fx.module_health("ai-infra"))
        h.on("GET", PILOT_DEF + "/health", fx.module_health("defense-unmanned"))
        h.on("GET", PILOT_HUB + "/sources", lambda call: {"sources": [
            {"module_id": call.params["module"], "source_key": "dcd-news", "retired": None},
            {"module_id": call.params["module"], "source_key": "edgar-8k", "retired": None},
            {"module_id": call.params["module"], "source_key": "old-feed", "retired": "not_in_latest_run"}]})
        h.on("GET", PILOT_AI + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        h.on("GET", PILOT_DEF + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        h.on("GET", PILOT_HUB + "/settings", fc.settings())
        h.on("GET", PILOT_HUB + "/radar", fc.radar_requests())
        h.on("GET", PILOT_HUB + "/modules", fc.modules())
        h.on("GET", INSPECT_AI, fc.inspect_ai())
        h.on("GET", INSPECT_DEF, fc.inspect_def())

    def control(self, secrets: dict | None = None, **kwargs):
        """The Control room, unlocked with the builder PIN (the pilot's owner PIN is the fallback for one workspace)."""
        kwargs.setdefault("builder_pin", PIN if secrets is None else BUILDER_PIN)
        return self.app(secrets, tab="control", **kwargs)

    def beta_routes(self) -> None:
        self.http.on("GET", BETA_HUB + "/diagnostics", fx.diagnostics("beta", failing=False) | {"modules": []})
        self.http.on("GET", BETA_COV + "/health", fx.module_health("coverage"))
        self.http.on("GET", BETA_COV + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        self.http.on("GET", BETA_HUB + "/settings", fc.settings())
        self.http.on("GET", BETA_HUB + "/radar", {"requests": []})
        self.http.on("GET", BETA_HUB + "/companies/suggestions", fx.company_suggestions_v13())


class AccessTests(ControlCase):
    def test_hidden_without_the_builder(self):
        at = self.app(tab="control")
        self.assert_clean(at)
        self.assertNotIn("Control room", list(at.radio(key="zx_tab").options))
        self.assertNotIn('<div class="health-card ', self.html(at))
        self.assertEqual(self.http.find("GET", PILOT_AI + "/health"), [])  # no module is asked for its health

    def test_two_workspaces_need_a_builder_pin(self):
        at = self.app(two_workspaces(), tab="control", pin=PIN)  # the owner PIN alone opens no Control room
        self.assert_clean(at)
        self.assertNotIn("Control room", list(at.radio(key="zx_tab").options))
        self.assertNotIn('<div class="health-card ', self.html(at))

    def test_single_workspace_owner_pin_is_the_builder_fallback(self):
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Control room", list(at.radio(key="zx_tab").options))
        self.assertEqual(self.html(at).count('<div class="health-card '), 1)
        self.assertIn("Builder PIN: set (owner PIN fallback)", self.texts(at, "caption"))
        self.assert_no_secrets(at)


class BackfillTests(ControlCase):
    def test_panel_lists_sources_from_module_health(self):
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Backfill", self.html(at))
        self.assertEqual(at.selectbox(key="bf_ws").value, "pilot")
        self.assertEqual(list(at.selectbox(key="bf_module_pilot").options), ["ai-infra", "defense-unmanned"])
        self.assertEqual(at.number_input(key="bf_days").value, 14)
        # the module's /health keys plus the current keys the hub has seen (a retired one is left out)
        self.assertEqual(list(at.multiselect(key="bf_sources_pilot_ai-infra").options),
                         ["ai-infra-rss", "ai-infra-sitemap", "dcd-news", "edgar-8k"])
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/sources")[0].params, {"module": "ai-infra"})
        self.assertIn("No backfill has run for ai-infra yet.", self.texts(at, "caption"))
        self.assertEqual(self.http.find("GET", PILOT_AI + "/backfill")[0].bearer, RUN_AI)
        self.assert_no_secrets(at)

    def test_backfill_sits_below_the_diagnostics(self):
        html = self.html(self.control())
        self.assertLess(html.index('<div class="health-card '), html.index("<span>Backfill</span>"))
        self.assertLess(html.index("<span>Backfill</span>"), html.index("<span>Coverage requests to review</span>"))
        # then the source repairs and the company names to build in (docs/SPEC-COMPANY-MAP.md 6.3)
        self.assertLess(html.index("<span>Coverage requests to review</span>"),
                        html.index("<span>Source repairs to review</span>"))
        self.assertLess(html.index("<span>Source repairs to review</span>"),
                        html.index("<span>Company names to build in · 0</span>"))

    def test_run_posts_the_job_then_polls_progress_until_done(self):
        stage = {"n": 0}
        jobs = [fx.job("queued", 0, 2, days=21), fx.job("running", 1, 1, days=21), fx.job("done", 2, 0, days=21)]
        posted = []

        def status(call):
            return jobs[min(stage["n"], 2)] if posted else FakeResponse(404, {"error": "no_backfill_job"})

        def start(call):
            posted.append(call)
            return FakeResponse(202, jobs[0])

        self.http.on("GET", PILOT_AI + "/backfill", status)
        self.http.on("POST", PILOT_AI + "/backfill", start)
        at = self.control()
        at.number_input(key="bf_days").set_value(21)
        at.multiselect(key="bf_sources_pilot_ai-infra").set_value(["edgar-8k", "ai-infra-rss"])
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0].bearer, RUN_AI)
        self.assertEqual(posted[0].body, {"days": 21, "sources": ["ai-infra-rss", "edgar-8k"]})
        self.assertTrue(any("Backfill bf-1 queued for pilot/ai-infra: 21 days, 2 source(s)" in s
                            for s in self.texts(at, "success")))
        html = self.html(at)
        self.assertIn('<span class="status-pill warn">queued</span>', html)
        self.assertIn("0 of 2 sources done", html)
        self.assertTrue(at.session_state["bf_live_pilot_ai-infra"])
        stage["n"] = 1  # the polling fragment's next tick
        at.run()
        self.assertIn("1 of 2 sources done", self.html(at))
        self.assertTrue(at.session_state["bf_live_pilot_ai-infra"])
        stage["n"] = 2  # the job finishes: polling stops
        jobs[2]["totals"] = {"new": 37, "emitted": 37, "failed": 0}
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("<span>37 new · 37 emitted</span>", html)
        self.assertIn('<span class="status-pill ok">done</span>', html)
        self.assertFalse(at.session_state["bf_live_pilot_ai-infra"])
        self.assertEqual(len(posted), 1)

    def test_an_active_job_found_on_load_starts_polling(self):
        self.http.on("GET", PILOT_AI + "/backfill", fx.job("running", 2, 3))
        at = self.control()
        self.assert_clean(at)
        self.assertTrue(at.session_state["bf_live_pilot_ai-infra"])
        self.assertIn("2 of 5 sources done", self.html(at))
        self.assertTrue(any(c.startswith("Remaining: edgar-8k, dcd-news, bisnow-dc") for c in self.texts(at, "caption")))

    def test_run_while_a_job_is_in_flight_leaves_it_unchanged(self):
        self.http.on("POST", PILOT_AI + "/backfill", FakeResponse(200, fx.job("running", 1, 2, job_id="bf-old")))
        self.http.on("GET", PILOT_AI + "/backfill", fx.job("running", 1, 2, job_id="bf-old"))
        at = self.control()
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        self.assertTrue(any("A backfill is already in progress for pilot/ai-infra (job bf-old, 1 of 3 sources done)" in s
                            for s in self.texts(at, "success")))

    def test_failed_job_shows_its_last_error(self):
        self.http.on("GET", PILOT_AI + "/backfill", fx.job("failed", 1, 2) | {"last_error": "chunk timed out"})
        at = self.control()
        self.assert_clean(at)
        self.assertIn('<span class="status-pill bad">failed</span>', self.html(at))
        self.assertIn("Last chunk error: chunk timed out", self.texts(at, "caption"))
        self.assertFalse(at.session_state["bf_live_pilot_ai-infra"])

    def test_run_refused_by_the_module(self):
        self.http.on("POST", PILOT_AI + "/backfill", FakeResponse(409, {"error": "job_running"}))
        at = self.control()
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        self.assertIn("Backfill not started: HTTP 409: job_running", self.texts(at, "error"))

    def test_the_builder_runs_another_workspace_with_its_run_token(self):
        self.beta_routes()
        self.http.on("POST", BETA_COV + "/backfill", FakeResponse(202, fx.job("queued", 0, 3, job_id="bf-beta", days=30)))
        at = self.control(with_builder(two_workspaces()))
        at.selectbox(key="bf_ws").set_value("beta").run()
        self.assertEqual(list(at.selectbox(key="bf_module_beta").options), ["coverage"])
        at.number_input(key="bf_days").set_value(30)
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", BETA_COV + "/backfill")[0]
        self.assertEqual((post.body, post.bearer), ({"days": 30}, BETA_RUN))
        self.assertTrue(any("queued for beta/coverage: 30 days, every source" in s for s in self.texts(at, "success")))

    def test_backfill_disabled_without_a_run_token(self):
        secrets = one_workspace()
        secrets["workspaces"][0]["modules"][0].pop("run_token")
        at = self.control(secrets, builder_pin=PIN)
        self.assert_clean(at)
        self.assertTrue(at.button(key="bf_run").disabled)
        self.assertIn("Backfill is disabled for ai-infra: url or run_token is not configured.", self.texts(at, "caption"))
        self.assertEqual(self.http.find("GET", PILOT_AI + "/backfill"), [])

    def test_send_again_is_sent_only_when_ticked(self):
        posted = []
        self.http.on("POST", PILOT_AI + "/backfill", lambda call: posted.append(call.body) or FakeResponse(202, fx.job()))
        at = self.control()
        box = at.checkbox(key="bf_ignore_pilot_ai-infra")
        self.assertEqual((box.label, box.value), ("Send again even if already sent (after lost deliveries)", False))
        at.button(key="bf_run").click().run()
        self.assertEqual(posted[-1], {"days": 14})
        at.checkbox(key="bf_ignore_pilot_ai-infra").check()
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        self.assertEqual(posted[-1], {"days": 14, "ignore_seen": True})

    def test_module_health_unreachable_still_allows_typed_sources(self):
        self.http.routes.pop(("GET", PILOT_AI + "/health"))
        self.http.routes.pop(("GET", PILOT_HUB + "/sources"))
        at = self.control()
        self.assert_clean(at)
        self.assertEqual(list(at.multiselect(key="bf_sources_pilot_ai-infra").options), [])
        self.assertIn("Could not list sources from ai-infra/health: unreachable (ConnectionError)",
                      self.texts(at, "caption"))


class HealthPanelTests(ControlCase):
    def test_every_workspace_is_shown_with_status_pills(self):
        self.http.on("GET", BETA_COV + "/health", fx.module_health("coverage"))  # beta's hub stays unreachable
        at = self.control(with_builder(two_workspaces()))
        self.assert_clean(at)
        html = self.html(at)
        self.assertEqual(html.count('<div class="health-card '), 2)
        self.assertIn('<span class="health-title">Pilot</span><span class="status-pill warn">needs attention</span>', html)
        self.assertIn('<span class="health-title">Beta analyst</span><span class="status-pill bad">needs action</span>', html)
        self.assertIn('<div class="health-reason warn">defense-unmanned/sam-opps is failing (HTTP 429, 3 runs)</div>', html)
        self.assertIn("<strong>Hub unreachable</strong> · unreachable (ConnectionError)", html)
        self.assertIn('<div class="tile "><div class="tile-n">21</div><div class="tile-l">Stories waiting</div>', html)
        self.assertIn("fresh, 7 days · 57 in all · trend steady · 807 auto-rejected as stale", html)
        self.assertIn('<div class="tile-n">held</div><div class="tile-l">Grader lease</div>', html)
        self.assertIn('<div class="tile warn"><div class="tile-n">2</div><div class="tile-l">Dead letters</div>', html)
        self.assertIn('<div class="tile warn"><div class="tile-n">1</div><div class="tile-l">Failing sources</div>', html)
        self.assertIn('<div class="tile warn"><div class="tile-n">1</div><div class="tile-l">Silent sources</div>', html)
        self.assertIn("#12 · 2 items", html)
        # one row per module: an ok module shows its pill, a degraded one a clickable status light
        self.assertIn('<div class="mod-td"><span class="mono">ai-infra</span></div>', html)
        self.assertIn('<div class="mod-td"><span class="status-pill ok">ok</span></div>', html)
        self.assertIn('<div class="mod-td">42</div>', html)
        self.assertIn('<div class="mod-td">270</div>', html)
        self.assertEqual(at.button(key="cr_light_warn_pilot_defense-unmanned").label, "Degraded · 1 failing source")
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("cr_light_")],
                         ["cr_light_warn_pilot_defense-unmanned"])
        self.assertIn('<div class="mod-td"><span class="mono">coverage</span></div>', html)
        self.assertIn("<td>defense-unmanned</td><td><span class=\"mono\">sam-opps</span></td>"
                      "<td><span class=\"status-pill warn\">backoff</span></td><td>error</td><td>429</td><td>3</td>", html)
        self.assertIn("silent_for_96h", html)
        self.assertIn("defense-unmanned:x:1", html)
        expanders = [e.label for e in at.expander]
        for label in ("pilot · failing sources · 1", "pilot · silent sources · 1", "pilot · recent dead letters · 1"):
            self.assertIn(label, expanders)
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/diagnostics")[0].bearer, READ)
        self.assertEqual(self.http.find("GET", BETA_HUB + "/diagnostics")[0].bearer, BETA_READ)
        self.assert_no_secrets(at)
        self.assertNotIn(BUILDER_PIN, self.html(at) + "".join(self.texts(at, "caption")))

    def test_module_worker_down_and_backfill_column(self):
        self.http.routes.pop(("GET", PILOT_AI + "/health"))
        self.http.on("GET", PILOT_DEF + "/health",
                     fx.module_health("defense-unmanned", backfill={"id": "bf-9", "status": "running", "days": 7,
                                                                    "done": 3, "remaining": 5}))
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertEqual(at.button(key="cr_light_bad_pilot_ai-infra").label, "Down · unreachable (ConnectionError)")
        self.assertIn('<span class="status-pill warn">running</span> 3/8', html)
        # the light of a module that is down explains that the module itself did not answer
        at.button(key="cr_light_bad_pilot_ai-infra").click().run()
        self.assert_clean(at)
        self.assertIn("ZENITH could not reach ai-infra itself: unreachable (ConnectionError).", self.visible_text(at))

    def test_the_degraded_light_opens_the_failing_sources(self):
        at = self.control()
        self.assert_clean(at)
        at.button(key="cr_light_warn_pilot_defense-unmanned").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state["zx_dialog"]["name"], control_view.DIALOG_FAILING)
        text = self.visible_text(at)
        self.assertIn("Source health · defense-unmanned", text)
        self.assertIn("sam-opps", text)
        self.assertIn("The site asked ZENITH to slow down (HTTP 429, too many requests).", text)
        self.assertIn("Failed checks in a row 3", text)
        self.assertIn("Health backoff (retrying less often)", text)
        self.assertIn("Last worked", text)
        self.assertIn(control_view.ACK_HINT, text)
        self.assertIn("Quiet lately (working, but no new stories)", text)  # the module's silent source
        self.assert_no_secrets(at)
        at.button(key="dlg_cancel").click().run()
        self.assert_clean(at)
        self.assertNotIn("zx_dialog", at.session_state)

    def test_retrying_and_slowed_sources_colour_nothing_and_open_the_window(self):
        # docs/PLAN-SOURCE-REPAIR.md Phase A: one missed check after working is "retrying", a source slowed after
        # repeated HTTP 429s is "slowed"; neither makes the module degraded
        diag = fx.diagnostics(failing=False)
        diag["modules"][1]["status"] = "partial"
        sam = {"module_id": "defense-unmanned", "source_key": "sam-opps", "health": "degraded", "last_status": "error",
               "last_http_status": 503, "consecutive_failures": 1, "last_ok_at": fx.iso(1)}
        diag["retrying"] = [sam]
        diag["slowed"] = [{"module": "defense-unmanned", "source_key": "eu-ted-uas", "factor": 2, "base_minutes": 360,
                           "effective_minutes": 720, "reason": "throttled", "http_status": 429, "since": fx.iso(5)}]
        self.http.on("GET", PILOT_HUB + "/diagnostics", diag)
        at = self.control()
        self.assert_clean(at)
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("cr_light_")], [])  # nothing degraded
        note = at.button(key="cr_notes_pilot_defense-unmanned")
        self.assertEqual(note.label, "1 retrying · 1 slowed")
        labels_ = [e.label for e in at.expander]
        self.assertIn("pilot · retrying after one missed check · 1", labels_)
        self.assertIn("pilot · slowed down automatically · 1", labels_)
        note.click().run()
        self.assert_clean(at)
        text = self.visible_text(at)
        self.assertIn("Source health · defense-unmanned", text)
        self.assertIn("No source is failing.", text)
        self.assertIn("Retrying after one missed check (it colours nothing)", text)
        self.assertIn("The site's server had an error (HTTP 503).", text)
        self.assertIn("Slowed down automatically", text)
        self.assertIn("Checked every 12 h instead of every 6 h since", text)
        self.assertIn("the site asked us to slow down (HTTP 429)", text)

    def test_status_with_retrying_sources(self):
        status = control_view.module_status({"status": "partial"}, None, None, 0, retrying=1)
        self.assertEqual(status, ("ok", "1 source retrying"))
        self.assertEqual(control_view.module_status({"status": "partial"}, None, None, 0, retrying=1, partial_flagged=True)[0],
                         "degraded")  # a partial run with another cause stays degraded
        # a failed run whose only misses are retrying (no red reason from the hub) is ok; with a red reason it is failed
        self.assertEqual(control_view.module_status({"status": "failed"}, None, None, 0, retrying=1), ("ok", "1 source retrying"))
        self.assertEqual(control_view.module_status({"status": "failed"}, None, None, 0, retrying=1, red_flagged=True)[0], "failed")
        self.assertEqual(control_view.module_status({"status": "failed"}, None, None, 0)[0], "failed")
        self.assertEqual(control_view.every_text(90), "every 90 min")
        self.assertEqual(control_view.every_text(2880), "every 2 days")

    def test_failure_reasons_in_plain_words(self):
        reason = control_view.failure_reason
        self.assertEqual(reason({"http": 403}), "The site refused ZENITH's request (HTTP 403). It may block automated "
                                                "readers.")
        self.assertEqual(reason({"http": 404}), "The page wasn't found (HTTP 404). It may have moved.")
        self.assertEqual(reason({"http": 503}), "The site's server had an error (HTTP 503).")
        self.assertEqual(reason({"status": "timeout"}), "The site didn't answer in time.")
        self.assertEqual(reason({"kind": "structural_empty", "empty_streak": 4}),
                         "The page loads, but ZENITH found no stories on it 4 runs in a row. The site's layout may have "
                         "changed.")
        self.assertEqual(reason({"kind": "quota_streak", "quota_streak": 2}),
                         "The daily allowance for this source's service was used up 2 runs in a row.")
        self.assertEqual(reason({"http": 429, "error": "rate limited by api.sam.gov"}),
                         "The site asked ZENITH to slow down (HTTP 429, too many requests). Last error: rate limited by "
                         "api.sam.gov")
        self.assertEqual(reason({}), "The last check failed.")

    def test_all_healthy(self):
        self.http.on("GET", PILOT_HUB + "/diagnostics", fx.diagnostics(failing=False) | {"status": "ok", "modules": [
            {"module_id": "ai-infra", "status": "ok"}, {"module_id": "defense-unmanned", "status": "ok"}],
            "dead_letters": 0, "review": {"backlog": 0, "lease": {"run_id": None, "held": False}}})
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<span class="health-title">Pilot</span><span class="status-pill ok">healthy</span>', html)
        self.assertIn('<div class="health-card ok">', html)
        self.assertNotIn('class="health-reasons"', html)
        self.assertIn('<div class="tile-n">free</div><div class="tile-l">Grader lease</div>', html)
        self.assertEqual([e.label for e in at.expander if "failing" in e.label], [])

    def test_routines_with_the_due_check(self):
        # docs/SPEC-SIMPLIFY.md 2.5: prompt_state in plain words, slots_7d as a caption, Allow one extra run
        diag = fx.diagnostics()
        diag["routines"]["grader"].update(
            prompt_state="updates_next_run", slots_7d={"ran": 14, "skipped": 14, "catch_ups": 1, "manual": 0},
            last_skipped_at=fx.iso(3), allow_once_until=None)
        diag["routines"]["refiner"].update(prompt_state="current",
                                           slots_7d={"ran": 7, "skipped": 7, "catch_ups": 0, "manual": 1})
        diag["routines"]["scout"].update(prompt_state="outdated", slots_7d={"ran": 0, "skipped": 0, "catch_ups": 0,
                                                                            "manual": 0})
        self.http.on("GET", PILOT_HUB + "/diagnostics", diag)
        until = fx.iso(-2)
        self.http.on("POST", PILOT_HUB + "/admin/routines/allow-once",
                     {"allowed": True, "role": "grader", "until": until})
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        clock = control_view.fmt_clock(diag["routines"]["grader"]["next_due_at"], "America/New_York")
        self.assertIn(f'<span class="tile-d">picks up its updated instructions at its next run, {clock}</span>', html)
        self.assertIn('<span class="status-pill warn">ran with an old copy of its instructions</span>', html)
        self.assertIn("<b>Grader</b> · Last 7 days: 14 ran, 14 skipped as not due, 1 catch-up, 0 by hand · last "
                      "skipped 3h ago", html)
        self.assertIn("<b>Rule refiner</b> · Last 7 days: 7 ran, 7 skipped as not due, 0 catch-ups, 1 by hand", html)
        self.assertEqual([at.button(key=f"cr_allow_pilot_{r}").label for r in ("grader", "refiner", "scout")],
                         ["Allow one extra run"] * 3)
        at.button(key="cr_allow_pilot_grader").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/admin/routines/allow-once")[-1]
        self.assertEqual((post.bearer, post.body), (OWNER, {"role": "grader"}))
        self.assertIn(f"One extra Grader run is allowed until {control_view.fmt_clock(until, 'America/New_York')}. "
                      "Start it from claude.ai/code/routines within 2 hours.", self.toasts(at))

    def test_an_older_hub_offers_no_extra_run(self):
        at = self.control()
        self.assert_clean(at)
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("cr_allow_")], [])
        self.assertIn('<span class="status-pill warn">out of date</span>', self.html(at))  # prompt_current

    def test_schema_7_card_tiles_routines_and_footer(self):
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="tile "><div class="tile-n">31</div><div class="tile-l">Aged out unread (24 h)</div>'
                      '<div class="tile-d">0 arrived fresh</div></div>', html)
        self.assertIn('<div class="tile "><div class="tile-n">68% same band</div><div class="tile-l">Grader agreement '
                      '(30 days)</div><div class="tile-d">n=22 · 95% within one band · 7 days: 67%</div></div>', html)
        self.assertIn('<div class="tile "><div class="tile-n">0.0 GB of 10 GB</div><div class="tile-l">Database size</div>',
                      html)
        self.assertIn('<div class="health-subhead">Routines</div>', html)
        self.assertIn("<td>Grader</td><td>7:30 AM · 12:30 PM · 4:30 PM ET</td>", html)
        self.assertIn("Refused tokens today: review 2, read 0", html)
        self.assertIn('<div class="health-foot"><span>Hub build abc123def456 · schema 7', html)
        self.assertIn("Delivery check: a test record from ai-infra came through the queue in 3.1 s, 3h ago", html)
        self.assertIn("<span>cleaned up 5h ago</span>", html)
        self.assertIn("pilot · biggest disagreements · 1", [e.label for e in at.expander])
        self.assertIn("<td>Army awards counter-UAS &lt;production&gt; order</td><td>lead</td><td>55 (watch)</td>", html)

    def test_awaiting_signoff_is_listed_as_the_hub_sends_it(self):
        diag = fx.diagnostics(failing=False)
        diag["severity"] = {"level": "amber", "acknowledged": [], "reasons": [
            {"level": "amber", "code": "awaiting_signoff",
             "message": "This workspace is collecting. Briefings start after the analyst signs off."}]}
        self.http.on("GET", PILOT_HUB + "/diagnostics", diag)
        at = self.control()
        self.assertIn('<div class="health-reason warn">This workspace is collecting. Briefings start after the analyst '
                      'signs off.</div>', self.html(at))

    def test_unreachable_configured_module_turns_a_green_hub_red(self):
        self.http.on("GET", PILOT_HUB + "/diagnostics", fx.diagnostics(failing=False))
        self.http.on("GET", PILOT_DEF + "/health", FakeResponse(401, {"error": "unauthorized"}))
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<span class="health-title">Pilot</span><span class="status-pill bad">needs action</span>', html)
        self.assertIn("defense-unmanned refused the dashboard&#x27;s run token, so its health cannot be read", html)
        self.assertEqual(self.http.find("GET", PILOT_DEF + "/health")[0].bearer, RUN_DEF)

    def test_hub_errors_are_listed(self):
        diag = fx.diagnostics()
        diag["errors"] = {"last_hour": 1, "last_24h": 1, "recent": [
            {"at": fx.iso(0.2), "kind": "queue", "route": None, "message": "D1_ERROR: database is locked"}]}
        diag["severity"]["level"] = "red"
        diag["severity"]["reasons"].insert(0, {"level": "red", "code": "hub_errors",
                                               "message": "The hub recorded 1 error in the last hour"})
        self.http.on("GET", PILOT_HUB + "/diagnostics", diag)
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="health-reasons"><div class="health-reason bad">The hub recorded 1 error in the last '
                      'hour</div><div class="health-reason warn">', html)
        self.assertIn("pilot · recent hub errors · 1", [e.label for e in at.expander])

    def test_refresh_now_reads_again(self):
        at = self.control()
        before = len(self.http.find("GET", PILOT_HUB + "/diagnostics"))
        at.run()
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/diagnostics")), before)  # cached within the TTL
        at.button(key="health_refresh").click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/diagnostics")), before + 1)

    def test_unauthorized_hub(self):
        self.http.on("GET", PILOT_HUB + "/diagnostics", FakeResponse(401, {"error": "unauthorized"}))
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("<strong>Hub refused the read token</strong> · HTTP 401: token refused", html)
        self.assertIn('<div class="tile-n">none yet</div><div class="tile-l">Last edition</div>', html)


class AcknowledgeTests(ControlCase):
    ACK = PILOT_HUB + "/admin/sources/ack"
    UNACK = PILOT_HUB + "/admin/sources/unack"

    def test_acknowledge_posts_module_source_and_note_with_a_toast_and_undo(self):
        acked = fx.diagnostics()
        acked["modules"][1]["failing"][0]["acknowledged"] = {"acked_at": fx.iso(0), "note": "SAM rate limit, known"}
        acked["severity"].update(level="green", reasons=[], acknowledged=[
            {"module": "defense-unmanned", "source_key": "sam-opps", "kind": "failing", "fingerprint": "failing:error:429",
             "acked_at": fx.iso(0), "note": "SAM rate limit, known"}])

        def ack(call):
            self.http.on("GET", PILOT_HUB + "/diagnostics", acked)  # the hub now reports it acknowledged
            return {"module": "defense-unmanned", "source_key": "sam-opps", "kind": "failing",
                    "fingerprint": "failing:error:429", "acked_at": fx.iso(0), "note": call.body.get("note")}

        self.http.on("POST", self.ACK, ack)
        self.http.on("POST", self.UNACK, {"removed": True})
        at = self.control()
        self.assertIn("pilot · failing sources · 1", [e.label for e in at.expander])
        at.text_input(key="ack_note_pilot_defense-unmanned_sam-opps").set_value("SAM rate limit, known")
        at.button(key="ack_pilot_defense-unmanned_sam-opps").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", self.ACK)[0]
        self.assertEqual((post.body, post.bearer), ({"module": "defense-unmanned", "source_key": "sam-opps",
                                                     "note": "SAM rate limit, known"}, OWNER))
        self.assertIn("Acknowledged defense-unmanned/sam-opps.", self.toasts(at))
        html = self.html(at)  # read again: green, the source in its own list with a way back
        self.assertIn('<span class="health-title">Pilot</span><span class="status-pill ok">healthy</span>', html)
        labels = [e.label for e in at.expander]
        self.assertNotIn("pilot · failing sources · 1", labels)
        self.assertIn("pilot · acknowledged sources · 1", labels)
        self.assertIn("<td>SAM rate limit, known</td>", html)
        field(undo_of(at), "run")(OWNER)
        unack = self.http.find("POST", self.UNACK)[0]
        self.assertEqual((unack.body, unack.bearer), ({"module": "defense-unmanned", "source_key": "sam-opps"}, OWNER))
        self.assert_no_secrets(at)

    def test_acknowledge_a_source_that_already_recovered(self):
        self.http.on("POST", self.ACK, FakeResponse(409, {
            "error": "source_not_failing", "message": "defense-unmanned/sam-opps has no current problem to acknowledge"}))
        at = self.control()
        at.button(key="ack_pilot_defense-unmanned_sam-opps").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", self.ACK)[0].body, {"module": "defense-unmanned", "source_key": "sam-opps"})
        self.assertTrue(any("has no current problem to acknowledge" in e for e in self.texts(at, "caption")))
        self.assertEqual(self.toasts(at), [])

    def test_remove_acknowledgement_with_undo(self):
        diag = fx.diagnostics(failing=False)
        diag["severity"]["acknowledged"] = [{"module": "ai-infra", "source_key": "sify-news", "kind": "structural_empty",
                                             "fingerprint": "structural_empty:empty:-", "acked_at": fx.iso(3),
                                             "note": "known layout change"}]
        self.http.on("GET", PILOT_HUB + "/diagnostics", diag)
        self.http.on("POST", self.UNACK, {"removed": True})
        self.http.on("POST", self.ACK, {"module": "ai-infra", "source_key": "sify-news"})
        at = self.control()
        self.assertIn("pilot · acknowledged sources · 1", [e.label for e in at.expander])
        self.assertIn("<td>ai-infra</td><td><span class=\"mono\">sify-news</span></td><td>empty</td>", self.html(at))
        at.button(key="unack_pilot_ai-infra_sify-news").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", self.UNACK)[0]
        self.assertEqual((post.body, post.bearer), ({"module": "ai-infra", "source_key": "sify-news"}, OWNER))
        self.assertIn("Acknowledgement removed.", self.toasts(at))
        field(undo_of(at), "run")(OWNER)
        self.assertEqual(self.http.find("POST", self.ACK)[0].body,
                         {"module": "ai-infra", "source_key": "sify-news", "note": "known layout change"})

    def test_an_older_hub_offers_no_acknowledge_button(self):
        self.http.on("GET", PILOT_HUB + "/diagnostics", fx.diagnostics(legacy=True))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("pilot · failing sources · 1", [e.label for e in at.expander])
        self.assertEqual([b.key for b in at.button if str(b.key or "").startswith("ack_")], [])


class StageTests(ControlCase):
    def test_switch_to_staging_asks_first_with_undo(self):
        self.http.on("POST", STAGE, lambda call: fc.stage_set(call.body["stage"]))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Stage: live since Thu Oct 1", self.html(at))
        self.assertEqual(at.button(key="cr_stage_pilot").label, "Switch to staging")
        at.button(key="cr_stage_pilot").click().run()
        self.assertEqual(self.http.posts(), [])  # a confirmation first
        self.assertIn("publishes no briefings until the analyst signs off", self.visible_text(at))
        at.button(key=CONFIRM).click().run()
        self.assert_clean(at)
        post = self.http.find("POST", STAGE)[0]
        self.assertEqual((post.body, post.bearer), ({"stage": "staging"}, OWNER))
        self.assertIn("Stage is now staging.", self.toasts(at))
        field(undo_of(at), "run")(OWNER)
        self.assertEqual(self.http.find("POST", STAGE)[-1].body, {"stage": "live"})

    def test_go_live_from_staging(self):
        self.http.on("GET", PILOT_HUB + "/settings", fc.settings(stage="staging"))
        self.http.on("POST", STAGE, fc.stage_set("live"))
        at = self.control()
        self.assertIn("Stage: staging (collecting; no briefings until sign-off or Go live)", self.html(at))
        self.assertEqual(at.button(key="cr_stage_pilot").label, "Go live")
        at.button(key="cr_stage_pilot").click().run()
        self.assertIn("Going live here records a sign-off by the builder.", self.visible_text(at))
        at.button(key=CONFIRM).click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", STAGE)[0].body, {"stage": "live"})
        self.assertIn("Stage is now live.", self.toasts(at))

    def test_a_fresh_hub_without_a_stage_date(self):
        settings = fc.settings()
        settings["stage"]["since"] = None
        self.http.on("GET", PILOT_HUB + "/settings", settings)
        at = self.control()
        self.assert_clean(at)
        self.assertIn('<div class="refine-note">Stage: live</div>', self.html(at))

    def test_cancel_sends_nothing_and_an_older_hub_has_no_switch(self):
        at = self.control()
        at.button(key="cr_stage_pilot").click().run()
        at.button(key="dlg_cancel").click().run()
        self.assertEqual(self.http.posts(), [])
        self.fresh()
        self.http.on("GET", PILOT_HUB + "/settings", FakeResponse(404, {"error": "not_found"}))
        at = self.control()
        self.assert_clean(at)
        self.assertNotIn("cr_stage_pilot", [b.key for b in at.button])
        self.assertTrue(any(c.startswith("Stage unknown") for c in self.texts(at, "caption")))


class ModuleViewTests(ControlCase):
    def test_pills_open_the_technical_view(self):
        at = self.control()
        pills = at.pills(key="cr_module_pilot")
        self.assertEqual(list(pills.options), ["ai-infra", "defense-unmanned"])
        self.assertIsNone(pills.value)
        self.assertEqual(self.http.find("GET", INSPECT_AI), [])  # nothing is read until a module is chosen
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/snapshot"), [])
        at.pills(key="cr_module_pilot").set_value("ai-infra").run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", INSPECT_AI)[0].bearer, READ)
        html = self.html(at)
        self.assertIn("Catalog 0.1.0-3f2a9c1b7d4e · pushed ", html)
        self.assertIn(" · git abc123def456 · 8 sources (6 on) · 7 entities", html)
        self.assertIn('<tr><td><span class="mono">power_grid</span></td><td>Power and grid</td><td>government</td>'
                      "<td>1</td><td>4</td></tr>", html)
        self.assertIn("ai-infra · sources · 8", [e.label for e in at.expander])
        self.assertIn("ai-infra · entities · 7", [e.label for e in at.expander])
        self.assertIn('<td><span class="mono">ercot-large-load</span> <a class="" href="https://example.com/feed"', html)
        self.assertIn("<td>page-watch</td><td>Page watch</td><td>official</td><td>yes</td>"
                      '<td><span class="status-pill bad">failing</span> <span class="tile-d">ok</span></td>', html)
        self.assertIn("<td>900 / 3600</td><td>2</td><td>0.1%</td><td>muted</td>", html)  # gn-themes
        self.assertIn('<td><span class="mono">coreweave</span></td><td>CoreWeave</td><td>core</td><td>ai_cloud</td>'
                      "<td>public</td><td>NASDAQ:CRWV</td><td>own_feed, sec_filings</td>", html)
        self.assertIn('<tr><td><span class="mono">old-key</span></td><td>41</td><td>yes</td></tr>', html)
        self.assertNotIn("javascript:", html)
        # the module snapshot below it
        self.assertIn("<th>Lane</th><th>Last 24 hours</th><th>Last 7 days</th>", html)
        self.assertIn("<tr><td>trade press</td><td>30</td><td>190</td></tr>", html)
        self.assertEqual(html.count('<div class="event-row">'), 20)
        self.assertIn("Event 0 &lt;b&gt;title&lt;/b&gt;", html)
        call = self.http.find("GET", PILOT_HUB + "/snapshot")[0]
        self.assertEqual((call.params, call.bearer), ({"module": "ai-infra", "limit": 20}, READ))

    def test_catalog_missing_shows_the_sentence_and_the_snapshot_only(self):
        self.http.on("GET", INSPECT_AI, FakeResponse(404, fc.catalog_missing("ai-infra")))
        at = self.control(state={"cr_module_pilot": "ai-infra"})
        self.assert_clean(at)
        self.assertIn("Coverage details for ai-infra appear after the next deploy.", self.texts(at, "info"))
        self.assertNotIn("ai-infra · sources · ", " ".join(e.label for e in at.expander))
        self.assertEqual(self.html(at).count('<div class="event-row">'), 20)

    def test_module_link_opens_the_view(self):
        at = self.control(query={"tab": "control", "module": "defense-unmanned"})
        self.assert_clean(at)
        self.assertEqual(at.pills(key="cr_module_pilot").value, "defense-unmanned")
        self.assertEqual(len(self.http.find("GET", INSPECT_DEF)), 1)

    def test_snapshot_falls_back_to_diagnostics_counts(self):
        self.http.on("GET", PILOT_HUB + "/snapshot",
                     lambda call: {"events": []} if call.params.get("module") == "defense-unmanned" else fx.snapshot())
        at = self.control(state={"cr_module_pilot": "defense-unmanned"})
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("<tr><td>procurement</td><td>9</td><td>61</td></tr>", html)  # from /diagnostics
        self.assertIn("No events from defense-unmanned yet.", html)

    def test_snapshot_error(self):
        self.http.on("GET", PILOT_HUB + "/snapshot", FakeResponse(404, {"error": "unknown_module"}))
        at = self.control(state={"cr_module_pilot": "ai-infra"})
        self.assert_clean(at)
        self.assertIn("Could not load the snapshot for pilot/ai-infra.", self.html(at))
        self.assertIn("HTTP 404: unknown_module", self.html(at))


class ReviewTests(ControlCase):
    def test_the_technical_proposal_and_every_list(self):
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Pilot: 1 to review · 1 with the Radar scout · 1 approved, waiting for setup · 2 applied or live · "
                      "2 rejected", self.texts(at, "caption"))
        self.assertIn("Add the PUCT docket filings feed to ai-infra.", html)  # as the Source finder wrote it
        self.assertIn('<td>ai-infra</td><td><span class="mono">puct-large-load</span></td>'
                      "<td>Texas PUC large-load docket</td><td>html-list</td><td>power_grid</td><td>official</td>", html)
        self.assertIn('href="https://interchange.puc.texas.gov/"', html)
        self.assertIn("1 registry change: Oncor Electric Delivery", html)
        self.assertIn("Verified one fetch: 200, 40 filings listed.", html)
        self.assertIn("Diagnosis: no_source (No source ZENITH reads covered it.)", html)
        self.assertEqual(at.json[0].value.count("puct-large-load"), 1)
        self.assertIn("node tools/zenux.js radar apply pilot 44", [c.value for c in at.code])
        self.assertIn("pilot · approved, waiting for setup · 1", [e.label for e in at.expander])
        self.assertIn("pilot · applied and live · 2", [e.label for e in at.expander])
        self.assertIn('ai-infra/<span class="mono">ercot-large-load</span> ERCOT large-load interconnection reports: '
                      '<span class="status-pill ok">live</span>', html)
        self.assertIn("First items: 5 stories collected from it so far.", html)
        self.assertIn("rule draft #77", html)
        self.assertIn("Note: Paywalled: we cannot read it.", html)
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/radar")[0].bearer, READ)

    def test_approve_with_a_note_bound_to_the_proposal_shown(self):
        proposed_at = fc.radar_requests()["requests"][1]["proposed_at"]
        self.http.on("POST", PILOT_HUB + "/radar/45/approve", {"id": 45, "status": "approved_pending_apply"})
        at = self.control()
        at.text_input(key="rv_note_pilot_45").set_value("Use a 120-minute cadence")
        at.button(key="rv_approve_pilot_45").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/radar/45/approve")[0]
        self.assertEqual((post.body, post.bearer),
                         ({"note": "Use a 120-minute cadence", "proposed_at": proposed_at}, OWNER))
        self.assertTrue(any(t.startswith("Approved request #45 for Pilot.") for t in self.toasts(at)))
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/radar")), 2)  # read again

    def test_reject_asks_first(self):
        self.http.on("POST", PILOT_HUB + "/radar/45/reject", {"id": 45, "status": "rejected"})
        at = self.control()
        at.text_input(key="rv_note_pilot_45").set_value("We already read the PUC")
        at.button(key="rv_reject_pilot_45").click().run()
        self.assertEqual(self.http.posts(), [])
        self.assertIn("Your note: We already read the PUC", self.texts(at, "caption"))
        at.button(key=CONFIRM).click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/radar/45/reject")[0]
        self.assertEqual((post.body, post.bearer), ({"note": "We already read the PUC"}, OWNER))
        self.assertIn("Rejected request #45 for Pilot.", self.toasts(at))

    def test_approval_is_bound_to_the_proposal_shown(self):
        shown = fc.radar_requests()["requests"][1]["proposed_at"]
        at = self.control()
        newer = fx.iso(0.01)
        updated = fc.radar_requests()
        updated["requests"][1].update(proposed_at=newer, proposal={"summary": "A different Source finder proposal."})
        self.http.on("GET", PILOT_HUB + "/radar", updated)
        approved: list[dict] = []

        def approve(call: Call):  # brain.js decideRadar with body.proposed_at
            if "proposed_at" in (call.body or {}) and call.body["proposed_at"] != newer:
                return FakeResponse(409, {"error": "proposal_changed", "message": "reload it and review it again"})
            approved.append(call.body)
            return {"id": 45, "status": "approved_pending_apply"}

        self.http.on("POST", PILOT_HUB + "/radar/45/approve", approve)
        at.button(key="rv_approve_pilot_45").click().run()
        self.assert_clean(at)
        self.assertEqual(approved, [])
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/radar/45/approve")[0].body, {"proposed_at": shown})
        self.assertTrue(any("newer proposal for request #45 than the one shown, so nothing was approved" in w
                            for w in self.texts(at, "warning")))
        self.assertIn("A different Source finder proposal.", self.html(at))  # read again for review
        at.button(key="rv_approve_pilot_45").click().run()
        self.assertEqual(approved, [{"proposed_at": newer}])

    def test_unreachable_requests_say_so(self):
        self.http.on("GET", PILOT_HUB + "/radar", FakeResponse(200, no_json=True))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Could not load coverage requests from Pilot.", self.html(at))
        self.assertIn("HTTP 200: response is not JSON", self.html(at))


COMPANIES = PILOT_HUB + "/companies/suggestions"
APPLY_ADD = "node tools/zenux.js company apply pilot CS-6f708192"
DEPLOY = "node deploy/workspace.mjs pilot"


class CompanyNamesTests(ControlCase):
    """docs/SPEC-COMPANY-MAP.md 6.3: after the source repairs, the company names the analyst approved, each with the
    command that builds it in, then the deploy, then the applied ones waiting for that deploy."""

    def route(self, rows: list[dict], *, base: str = PILOT_HUB, by_status: bool = True) -> None:
        """GET /companies/suggestions?status= answers these rows (by_status=False: all of them, as a hub that ignores
        the status would)."""
        self.http.on("GET", base + "/companies/suggestions", lambda call: fp.company_list(
            rows, (call.params or {}).get("status") if by_status else None))

    @staticmethod
    def block(at, sid: str) -> str:
        return next(v for v in (str(m.value) for m in at.markdown) if f"pilot {sid} · " in v)

    def test_nothing_to_build_in_is_one_quiet_line(self):
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertLess(html.index("<span>Source repairs to review</span>"),
                        html.index("<span>Company names to build in · 0</span>"))
        self.assertIn("Pilot: no company names to build in.", self.texts(at, "caption"))
        calls = self.http.find("GET", COMPANIES)
        self.assertEqual(sorted(c.params.get("status") for c in calls), ["applied", "approved"])
        self.assertEqual({c.bearer for c in calls}, {READ})
        self.assertEqual([c.value for c in at.code if "company apply" in c.value], [])
        self.assertTrue(any(e.label.startswith("Configuration · ") for e in at.expander))

    def test_approved_with_their_commands_then_the_applied(self):
        # a hub that ignores ?status=: each list still keeps only its own; proposed and live ones are not listed
        self.route([fp.company_approved(), fp.company_applied(), fp.company_remove(), fp.company_fix(status="live")],
                   by_status=False)
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("<span>Company names to build in · 2</span>", html)
        captions = self.texts(at, "caption")
        self.assertIn("Pilot: 1 approved, waiting to be built in · 1 applied, waiting for a deploy", captions)
        self.assertIn(cnv.APPLY_HINT, captions)
        self.assertIn(cnv.DEPLOY_AFTER_APPLY, captions)
        codes = [c.value for c in at.code]
        self.assertIn(APPLY_ADD, codes)
        self.assertEqual(codes.count(DEPLOY), 1)
        self.assertLess(codes.index(APPLY_ADD), codes.index(DEPLOY))
        approved = self.block(at, "CS-6f708192")
        self.assertIn('<span class="loop-kind">Add a name</span><span class="status-pill ok">approved</span>', approved)
        self.assertIn("pilot CS-6f708192 · RCAT · ", approved)
        self.assertIn('Add <span class="co-name">Army Drone Dominance program</span> to Customers &amp; programs of '
                      '<span class="co-name">Red Cat Holdings</span>', approved)
        self.assertIn("Big customer: Expected: the Army plans to buy about 1 million drones", approved)
        self.assertIn(f'Source finder: Confirmed: <a class="source-link" href="{fp.DRONE_URL}"', approved)
        self.assertNotIn(esc(cnv.AS_TYPED), approved)
        applied = self.block(at, "CS-8192a3b4")
        self.assertIn(f"{cnv.APPLIED_HEAD} · 1", applied)
        self.assertIn('<span class="status-pill ok">applied</span>', applied)
        self.assertIn('Add <span class="co-name">Bundeswehr</span> to Customers &amp; programs of <span '
                      'class="co-name">Planet Labs</span>', applied)  # as the analyst typed it
        self.assertIn(esc(cnv.AS_TYPED), applied)
        self.assertLess(html.index("pilot CS-6f708192 · "), html.index("pilot CS-8192a3b4 · "))
        for sid in ("CS-7081920a", "CS-2b3c4d5e"):
            self.assertNotIn(sid, html)
        self.assertEqual(self.http.posts(), [])
        self.assert_no_secrets(at)

    def test_a_removal_or_fix_without_names_names_the_entry_on_file(self):
        """The hub sent neither the company's name nor the entry's (a removal without its name, a fix of the big flag
        only): the names on file (GET /brief, read only for these) give both. A check that could not confirm says so
        with what the source finder found, since the Control room has no Details."""
        self.http.on("GET", PILOT_HUB + "/brief", fp.brief())
        self.route([fp.company_remove(name=None, company_name=None, status="approved", use="as_typed"),
                    fp.company_row("CS-0b1c2d3e", "RCAT", None, "customers", "change", None, status="applied",
                                   target_id="c-air-force", big=1, applied_at=fp.iso(1),
                                   basis_text="Named as a top customer on the Q2 2026 call")])
        at = self.control()
        self.assert_clean(at)
        removal = self.block(at, "CS-7081920a")
        self.assertIn('Remove <span class="co-name">Rekor Scout</span> from Products &amp; brands of <span '
                      'class="co-name">Rekor Systems</span>', removal)
        self.assertIn(f"Source finder: {cnv.NOT_CONFIRMED}</div>", removal)
        self.assertIn('What it found: The 2025 annual report still lists <span class="co-name">Rekor Scout</span> as '
                      'a product', removal)
        fix = self.block(at, "CS-0b1c2d3e")
        self.assertIn('Fix <span class="co-name">U.S. Air Force</span> in Customers &amp; programs of <span '
                      'class="co-name">Red Cat Holdings</span>', fix)
        self.assertIn("Big customer: Named as a top customer on the Q2 2026 call", fix)
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/brief")), 1)

    def test_only_applied_ones_say_how_to_make_them_live(self):
        self.route([fp.company_applied()])
        at = self.control()
        self.assert_clean(at)
        self.assertIn("<span>Company names to build in · 1</span>", self.html(at))
        self.assertIn(cnv.DEPLOY_ONLY, self.texts(at, "caption"))
        self.assertNotIn(cnv.APPLY_HINT, self.texts(at, "caption"))
        self.assertEqual([c.value for c in at.code if "company apply" in c.value or c.value == DEPLOY], [DEPLOY])

    def test_a_failed_read_is_one_plain_line(self):
        self.http.on("GET", COMPANIES, FakeResponse(404, {"error": "not_found", "message": "ZENITH has no such page."}))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Pilot: this hub does not list company names yet; deploy the hub (schema 13) to add them.",
                      self.texts(at, "caption"))
        self.assertIn("<span>Company names to build in · 0</span>", self.html(at))
        self.fresh()
        self.http.on("GET", COMPANIES, FakeResponse(503, {"error": "unavailable", "message": "The database is busy."}))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Could not load company names from Pilot (HTTP 503: unavailable (The database is busy.)).",
                      self.texts(at, "caption"))
        self.assertIn("<span>Source repairs to review</span>", self.html(at))  # the rest of the room still works
        self.assertTrue(any(e.label.startswith("Configuration · ") for e in at.expander))
        for body in ({"suggestions": "x"}, {"suggestions": [None, 7, {"id": "x", "status": "approved"}]},
                     {"suggestions": [{"id": "CS-6f708192"}]}):
            with self.subTest(body=body):
                self.fresh()
                self.http.on("GET", COMPANIES, body)
                at = self.control()
                self.assert_clean(at)
                self.assertIn("Pilot: no company names to build in.", self.texts(at, "caption"))

    def test_hidden_without_the_builder(self):
        at = self.app(tab="control")  # open access is off in the tests, and no PIN was typed
        self.assert_clean(at)
        self.assertNotIn("Company names to build in", self.html(at))
        self.assertEqual(self.http.find("GET", COMPANIES), [])

    def test_every_workspace(self):
        self.beta_routes()
        self.route([fp.company_approved()])
        self.route([], base=BETA_HUB)
        at = self.control(with_builder(two_workspaces()))
        self.assert_clean(at)
        self.assertIn("<span>Company names to build in · 1</span>", self.html(at))
        self.assertIn("Beta analyst: no company names to build in.", self.texts(at, "caption"))
        self.assertIn(APPLY_ADD, [c.value for c in at.code])
        self.assertEqual(self.http.find("GET", BETA_HUB + "/companies/suggestions")[0].bearer, BETA_READ)


class ConfigurationTests(ControlCase):
    def test_presence_only_and_the_builder_pin_source(self):
        at = self.control()
        html = self.html(at)
        self.assertIn("<th>Workspace / module</th>", html)
        self.assertIn("<td>pilot/ai-infra</td><td>module</td>", html)
        self.assertIn("Values come from st.secrets and are never shown here.", self.texts(at, "caption"))
        self.assertIn("Builder PIN: set (owner PIN fallback)", self.texts(at, "caption"))
        self.assert_no_secrets(at)
        self.fresh()
        self.beta_routes()
        at = self.control(with_builder(two_workspaces()))
        self.assert_clean(at)
        self.assertIn("Builder PIN: set (builder_pin)", self.texts(at, "caption"))
        rendered = self.html(at) + "".join(self.texts(at, "caption"))
        self.assertNotIn(BUILDER_PIN, rendered)
        self.assert_no_secrets(at)


if __name__ == "__main__":
    unittest.main()
