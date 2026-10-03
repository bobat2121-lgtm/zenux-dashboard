"""AppTest: Diagnostics, the control room: backfill, the live health panel (two workspaces) and the snapshot."""

from __future__ import annotations

import unittest

import fixtures as fx
from helpers import (AppCase, BETA_COV, BETA_HUB, BETA_PIN, BETA_READ, BETA_RUN, FakeResponse, PILOT_AI, PILOT_DEF,
                     PILOT_HUB, PIN, READ, RUN_AI, one_workspace, two_workspaces, wrong_pin)


class DiagnosticsCase(AppCase):
    def setUp(self):
        super().setUp()
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


class BackfillTests(DiagnosticsCase):
    def test_panel_lists_sources_from_module_health(self):
        at = self.app(view="Diagnostics")
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
        at = self.app(view="Diagnostics", pin=PIN)
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
        # the polling fragment's next tick
        stage["n"] = 1
        at.run()
        self.assertIn("1 of 2 sources done", self.html(at))
        self.assertIn('<span class="status-pill warn">running</span>', self.html(at))
        self.assertTrue(at.session_state["bf_live_pilot_ai-infra"])
        # the job finishes: polling stops
        stage["n"] = 2
        jobs[2]["totals"] = {"new": 37, "emitted": 37, "failed": 0}
        at.run()
        self.assert_clean(at)
        self.assertIn("<span>37 new · 37 emitted</span>", self.html(at))
        html = self.html(at)
        self.assertIn('<span class="status-pill ok">done</span>', html)
        self.assertIn("2 of 2 sources done", html)
        self.assertFalse(at.session_state["bf_live_pilot_ai-infra"])
        self.assertEqual(len(posted), 1)

    def test_an_active_job_found_on_load_starts_polling(self):
        self.http.on("GET", PILOT_AI + "/backfill", fx.job("running", 2, 3))
        at = self.app(view="Diagnostics")
        self.assert_clean(at)
        self.assertTrue(at.session_state["bf_live_pilot_ai-infra"])
        self.assertIn("2 of 5 sources done", self.html(at))
        self.assertTrue(any(c.startswith("Remaining: edgar-8k, dcd-news, bisnow-dc") for c in self.texts(at, "caption")))

    def test_run_needs_the_owner_pin(self):
        self.http.on("POST", PILOT_AI + "/backfill", FakeResponse(202, fx.job()))
        at = self.app(view="Diagnostics")
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertTrue(any("Owner actions are locked" in w for w in self.texts(at, "warning")))
        at.text_input(key="owner_pin").set_value("nope").run()
        at.button(key="bf_run").click().run()
        self.assertEqual(self.http.posts(), [])
        self.assertIn(wrong_pin("pilot"), self.texts(at, "error"))

    def test_run_while_a_job_is_in_flight_leaves_it_unchanged(self):
        self.http.on("POST", PILOT_AI + "/backfill", FakeResponse(200, fx.job("running", 1, 2, job_id="bf-old")))
        self.http.on("GET", PILOT_AI + "/backfill", fx.job("running", 1, 2, job_id="bf-old"))
        at = self.app(view="Diagnostics", pin=PIN)
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        self.assertTrue(any("A backfill is already in progress for pilot/ai-infra (job bf-old, 1 of 3 sources done)" in s
                            for s in self.texts(at, "success")))

    def test_failed_job_shows_its_last_error(self):
        failed = fx.job("failed", 1, 2) | {"last_error": "chunk timed out", "failures": 3}
        self.http.on("GET", PILOT_AI + "/backfill", failed)
        at = self.app(view="Diagnostics")
        self.assert_clean(at)
        self.assertIn('<span class="status-pill bad">failed</span>', self.html(at))
        self.assertIn("Last chunk error: chunk timed out", self.texts(at, "caption"))
        self.assertFalse(at.session_state["bf_live_pilot_ai-infra"])

    def test_run_refused_by_the_module(self):
        self.http.on("POST", PILOT_AI + "/backfill", FakeResponse(409, {"error": "job_running"}))
        at = self.app(view="Diagnostics", pin=PIN)
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        self.assertIn("Backfill not started: HTTP 409: job_running", self.texts(at, "error"))

    def test_other_workspace_module_with_its_own_pin_and_run_token(self):
        self.http.on("GET", BETA_HUB + "/diagnostics", fx.diagnostics("beta", failing=False) | {"modules": []})
        self.http.on("GET", BETA_COV + "/health", fx.module_health("coverage"))
        self.http.on("GET", BETA_COV + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        self.http.on("POST", BETA_COV + "/backfill", FakeResponse(202, fx.job("queued", 0, 3, job_id="bf-beta", days=30)))
        at = self.app(two_workspaces(), view="Diagnostics", pin=PIN)
        at.selectbox(key="bf_ws").set_value("beta").run()
        self.assertEqual(list(at.selectbox(key="bf_module_beta").options), ["coverage"])
        at.number_input(key="bf_days").set_value(30)
        at.button(key="bf_run").click().run()
        self.assertEqual(self.http.posts(), [])  # the pilot PIN does not unlock beta
        self.assertIn(wrong_pin("beta"), self.texts(at, "error"))
        at.text_input(key="owner_pin").set_value(BETA_PIN)
        at.button(key="bf_run").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", BETA_COV + "/backfill")[0]
        self.assertEqual((post.body, post.bearer), ({"days": 30}, BETA_RUN))
        self.assertTrue(any("queued for beta/coverage: 30 days, every source" in s for s in self.texts(at, "success")))

    def test_backfill_disabled_without_a_run_token(self):
        secrets = one_workspace()
        secrets["workspaces"][0]["modules"][0].pop("run_token")
        at = self.app(secrets, view="Diagnostics", pin=PIN)
        self.assert_clean(at)
        self.assertTrue(at.button(key="bf_run").disabled)
        self.assertIn("Backfill is disabled for ai-infra: url or run_token is not configured.", self.texts(at, "caption"))
        self.assertEqual(self.http.find("GET", PILOT_AI + "/backfill"), [])

    def test_module_health_unreachable_still_allows_typed_sources(self):
        self.http.routes.pop(("GET", PILOT_AI + "/health"))
        self.http.routes.pop(("GET", PILOT_HUB + "/sources"))
        at = self.app(view="Diagnostics")
        self.assert_clean(at)
        self.assertEqual(list(at.multiselect(key="bf_sources_pilot_ai-infra").options), [])
        self.assertIn("Could not list sources from ai-infra/health: unreachable (ConnectionError)",
                      self.texts(at, "caption"))


class HealthPanelTests(DiagnosticsCase):
    def test_every_workspace_is_shown_with_status_pills(self):
        self.http.on("GET", BETA_COV + "/health", fx.module_health("coverage"))  # beta's hub stays unreachable
        at = self.app(two_workspaces(), view="Diagnostics")
        self.assert_clean(at)
        html = self.html(at)
        self.assertEqual(html.count('<div class="health-card '), 2)
        self.assertIn('<span class="health-title">Pilot</span><span class="status-pill warn">degraded</span>', html)
        self.assertIn('<span class="health-title">Beta analyst</span><span class="status-pill bad">down</span>', html)
        self.assertIn("<strong>Hub unreachable</strong> · unreachable (ConnectionError)", html)
        # pilot tiles: backlog, lease, dead letters, failing and silent sources, last edition
        self.assertIn('<div class="tile-n">57</div><div class="tile-l">Review backlog</div>', html)
        self.assertIn('<div class="tile-n">held</div><div class="tile-l">Grader lease</div>', html)
        self.assertIn('<div class="tile bad"><div class="tile-n">2</div><div class="tile-l">Dead letters</div>', html)
        self.assertIn('<div class="tile bad"><div class="tile-n">1</div><div class="tile-l">Failing sources</div>', html)
        self.assertIn('<div class="tile warn"><div class="tile-n">1</div><div class="tile-l">Silent sources</div>', html)
        self.assertIn("#12 · 2 items", html)
        # module rows: status, last run, events 24h and 7d
        self.assertIn('<td><span class="mono">ai-infra</span></td><td><span class="status-pill ok">ok</span></td>', html)
        self.assertIn('<td>42</td><td>270</td>', html)
        self.assertIn('<span class="mono">defense-unmanned</span></td><td><span class="status-pill warn">degraded</span>', html)
        self.assertIn('<td>9</td><td>65</td>', html)
        self.assertIn('<span class="mono">coverage</span></td><td><span class="status-pill ok">ok</span>', html)
        # detail tables
        self.assertIn("<td>defense-unmanned</td><td><span class=\"mono\">sam-opps</span></td>"
                      "<td><span class=\"status-pill warn\">backoff</span></td><td>error</td><td>429</td><td>3</td>", html)
        self.assertIn("silent_for_96h", html)
        self.assertIn("defense-unmanned:x:1", html)
        expanders = [e.label for e in at.expander]
        self.assertIn("pilot · failing sources · 1", expanders)
        self.assertIn("pilot · silent sources · 1", expanders)
        self.assertIn("pilot · recent dead letters · 1", expanders)
        # each hub is read with its own token
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/diagnostics")[0].bearer, READ)
        self.assertEqual(self.http.find("GET", BETA_HUB + "/diagnostics")[0].bearer, BETA_READ)
        self.assert_no_secrets(at)

    def test_module_worker_down_and_backfill_column(self):
        self.http.routes.pop(("GET", PILOT_AI + "/health"))
        self.http.on("GET", PILOT_DEF + "/health",
                     fx.module_health("defense-unmanned", backfill={"id": "bf-9", "status": "running", "days": 7,
                                                                    "done": 3, "remaining": 5}))
        at = self.app(view="Diagnostics")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<span class="status-pill bad">down</span> <span class="tile-d">unreachable (ConnectionError)</span>', html)
        self.assertIn('<span class="status-pill warn">running</span> 3/8', html)

    def test_all_healthy(self):
        self.http.on("GET", PILOT_HUB + "/diagnostics", fx.diagnostics(failing=False) | {"status": "ok", "modules": [
            {"module_id": "ai-infra", "status": "ok"}, {"module_id": "defense-unmanned", "status": "ok"}],
            "dead_letters": 0, "review": {"backlog": 0, "lease": {"run_id": None, "held": False}}})
        at = self.app(view="Diagnostics")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<span class="health-title">Pilot</span><span class="status-pill ok">ok</span>', html)
        self.assertIn('<div class="health-card ok">', html)
        self.assertIn('<div class="tile-n">free</div><div class="tile-l">Grader lease</div>', html)
        self.assertIn('<div class="tile "><div class="tile-n">0</div><div class="tile-l">Dead letters</div>', html)
        self.assertEqual([e.label for e in at.expander if "failing" in e.label], [])

    def test_refresh_now_reads_again(self):
        at = self.app(view="Diagnostics")
        before = len(self.http.find("GET", PILOT_HUB + "/diagnostics"))
        at.run()
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/diagnostics")), before)  # cached within the TTL
        at.button(key="health_refresh").click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/diagnostics")), before + 1)

    def test_no_editions_yet_and_unauthorized_hub(self):
        self.http.on("GET", PILOT_HUB + "/diagnostics", FakeResponse(401, {"error": "unauthorized"}))
        at = self.app(view="Diagnostics")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("<strong>Hub refused the read token</strong> · HTTP 401: token refused", html)
        self.assertIn('<div class="tile-n">none yet</div><div class="tile-l">Last edition</div>', html)


class SnapshotTests(DiagnosticsCase):
    def test_counts_by_lane_and_latest_twenty_events(self):
        at = self.app(view="Diagnostics")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("<th>Lane</th><th>Last 24 hours</th><th>Last 7 days</th>", html)
        self.assertIn("<tr><td>trade press</td><td>30</td><td>190</td></tr>", html)
        self.assertIn("<tr><td><b>All lanes</b></td><td><b>42</b></td><td><b>270</b></td></tr>", html)
        self.assertEqual(html.count('<div class="event-row">'), 20)
        self.assertIn("Event 0 &lt;b&gt;title&lt;/b&gt;", html)
        self.assertNotIn("Event 20 ", html)
        call = self.http.find("GET", PILOT_HUB + "/snapshot")[0]
        self.assertEqual((call.params, call.bearer), ({"module": "ai-infra", "limit": 20}, READ))

    def test_switch_module_and_fall_back_to_diagnostics_counts(self):
        self.http.on("GET", PILOT_HUB + "/snapshot",
                     lambda call: {"events": []} if call.params.get("module") == "defense-unmanned" else fx.snapshot())
        at = self.app(view="Diagnostics")
        at.selectbox(key="snap_target").set_value("pilot/defense-unmanned").run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("<tr><td>procurement</td><td>9</td><td>61</td></tr>", html)  # from /diagnostics
        self.assertIn("No events from defense-unmanned yet.", html)
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/snapshot")[-1].params["module"], "defense-unmanned")

    def test_snapshot_error(self):
        self.http.on("GET", PILOT_HUB + "/snapshot", FakeResponse(404, {"error": "unknown_module"}))
        at = self.app(view="Diagnostics")
        self.assert_clean(at)
        self.assertIn("Could not load the snapshot for pilot/ai-infra.", self.html(at))
        self.assertIn("HTTP 404: unknown_module", self.html(at))

    def test_configuration_expander_shows_presence_only(self):
        at = self.app(view="Diagnostics")
        html = self.html(at)
        self.assertIn("<th>Workspace / module</th>", html)
        self.assertIn("<td>pilot/ai-infra</td><td>module</td>", html)
        self.assertIn("Values come from st.secrets and are never shown here.", self.texts(at, "caption"))
        self.assert_no_secrets(at)


if __name__ == "__main__":
    unittest.main()
