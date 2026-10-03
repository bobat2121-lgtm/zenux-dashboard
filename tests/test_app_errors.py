"""AppTest: graceful error and empty states across tabs, and that secrets never leak into the page or URLs."""

from __future__ import annotations

import unittest

import requests

import fixtures as fx
from helpers import (AppCase, BETA_HUB, FakeResponse, OWNER, PILOT_AI, PILOT_DEF, PILOT_HUB, PIN, READ, RUN_AI,
                     RUN_DEF, one_workspace, two_workspaces)

VIEWS = ["Feed", "Rejected", "Rules", "Radar", "Diagnostics"]


class ErrorStateTests(AppCase):
    def test_every_tab_survives_an_unreachable_hub(self):
        expected = {
            "Feed": "Could not load editions from the Pilot hub.",
            "Rejected": "Could not load rejected events from the Pilot hub.",
            "Rules": "Could not load rules from the Pilot hub.",
            "Radar": "Could not load radar requests from the Pilot hub.",
            "Diagnostics": "Could not load the snapshot for pilot/ai-infra.",
        }
        for view in VIEWS:
            with self.subTest(view=view):
                self.fresh()
                at = self.app(view=view)
                self.assert_clean(at)
                self.assertIn(expected[view], self.html(at))
                self.assertIn("unreachable (ConnectionError)", self.html(at))

    def test_timeout_is_reported_plainly(self):
        self.http.on("GET", PILOT_HUB + "/editions", requests.Timeout("read timed out"))
        at = self.app()
        self.assert_clean(at)
        self.assertIn("<code>timed out</code>", self.html(at))

    def test_diagnostics_with_everything_down(self):
        at = self.app(two_workspaces(), view="Diagnostics")
        self.assert_clean(at)
        html = self.html(at)
        self.assertEqual(html.count('<span class="status-pill bad">down</span>'), 2 + 3)  # 2 hubs, 3 module rows
        self.assertIn("Could not read backfill progress for ai-infra.", html)
        self.assertIn("Could not list sources from ai-infra/health: unreachable (ConnectionError)", self.texts(at, "caption"))

    def test_missing_read_token_is_a_config_note_not_a_crash(self):
        secrets = one_workspace()
        secrets["workspaces"][0]["read_token"] = ""
        at = self.app(secrets)
        self.assert_clean(at)
        self.assertIn("read_token is not configured for workspace &#x27;pilot&#x27;", self.html(at))
        self.assertEqual(self.http.calls, [])
        at.radio(key="dashboard_view").set_value("Diagnostics").run()
        self.assert_clean(at)
        self.assertIn("workspace 'pilot': read_token missing (hub reads disabled)", self.texts(at, "caption"))

    def test_owner_writes_disabled_without_owner_config(self):
        secrets = one_workspace()
        del secrets["workspaces"][0]["owner_pin"]
        self.http.on("GET", PILOT_HUB + "/rules", fx.rules())
        at = self.app(secrets, view="Rules", pin=PIN)
        at.button(key="rule_retire_pilot_R-0001").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertTrue(any("owner_token or owner_pin is not configured" in w for w in self.texts(at, "warning")))

    def test_malformed_payloads_render_without_crashing(self):
        self.http.on("GET", PILOT_HUB + "/editions", {"editions": [
            {"id": 1, "items": [{"rank": "x", "headline": None, "sources": "nope", "metrics": {"a": 1}}, "junk"]},
            "junk", {"items": None}]})
        self.http.on("GET", PILOT_HUB + "/rejected", {"items": [{"title": None, "score": "n/a"}, 7]})
        # null and repeated ids: widget keys are built from ids, so these must neither crash nor collide
        self.http.on("GET", PILOT_HUB + "/rules", {
            "rules": [{"id": None}, {"id": None}, {"id": "R-1", "status": "active"}, {"id": "R-1", "status": "active"}, "x"],
            "drafts": [{"proposal": 5}, {"id": 3, "status": "proposed"}, {"id": 3, "status": "proposed"}]})
        self.http.on("GET", PILOT_HUB + "/radar", {"requests": [
            {"id": 1, "proposal": ["odd"], "status": "proposed"}, {"id": 1, "status": "proposed"}, {"status": "queued"}]})
        self.http.on("GET", PILOT_HUB + "/diagnostics", {"modules": "nope", "failing": [None, {"source_key": 3}],
                                                          "review": {"lease": "x"}, "dead_letters": "many"})
        self.http.on("GET", PILOT_HUB + "/snapshot", {"events": [{"title": None, "url": "javascript:x"}], "counts": 4})
        self.http.on("GET", PILOT_AI + "/health", {"ok": "maybe", "failing": "x", "backfill": [1]})
        self.http.on("GET", PILOT_AI + "/backfill", {"job": {"status": None, "done": "x"}})
        for view in VIEWS:
            with self.subTest(view=view):
                self.fresh()
                at = self.app(view=view)
                self.assert_clean(at)
                self.assertNotIn("javascript:", self.html(at))

    def test_secrets_never_reach_urls_or_the_page(self):
        for path, body in (("/editions", fx.editions()), ("/rejected", fx.rejected()), ("/rules", fx.rules()),
                           ("/radar", fx.radar()), ("/diagnostics", fx.diagnostics()), ("/snapshot", fx.snapshot())):
            self.http.on("GET", PILOT_HUB + path, body)
        self.http.on("GET", PILOT_AI + "/health", fx.module_health("ai-infra"))
        self.http.on("GET", PILOT_DEF + "/health", fx.module_health("defense-unmanned"))
        self.http.on("GET", PILOT_AI + "/backfill", fx.job("done", 3, 0))
        at = self.app(pin=PIN, grading=True)
        for view in VIEWS:
            at.radio(key="dashboard_view").set_value(view).run()
            self.assert_clean(at)
            self.assert_no_secrets(at)
        for call in self.http.calls:
            for secret in (READ, OWNER, RUN_AI, RUN_DEF, PIN):
                self.assertNotIn(secret, call.url)
                self.assertNotIn(secret, str(call.params))
                self.assertNotIn(secret, str(call.body))
        self.assertEqual({c.bearer for c in self.http.calls if c.url.startswith(PILOT_HUB)}, {READ})
        self.assertEqual({c.bearer for c in self.http.calls if c.url.endswith("/health")}, {None})

    def test_beta_hub_401_does_not_affect_pilot(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())
        self.http.on("GET", BETA_HUB + "/editions", FakeResponse(401, {"error": "unauthorized"}))
        at = self.app(two_workspaces())
        self.assertIn("Two items cleared the bar.", self.html(at))
        at.selectbox(key="workspace").set_value("beta").run()
        self.assert_clean(at)
        self.assertIn("Could not load editions from the Beta analyst hub.", self.html(at))
        self.assertIn("HTTP 401: token refused", self.html(at))


if __name__ == "__main__":
    unittest.main()
