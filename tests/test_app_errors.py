"""AppTest across the real tabs: plain error boxes with "Try again" when the hub cannot be read, malformed payloads that
never crash a tab, and secrets that never reach the page, a URL or a query string."""

from __future__ import annotations

import unittest

import requests

import fixtures as fx
from helpers import (AppCase, BETA_HUB, FakeResponse, OWNER, PILOT_AI, PILOT_DEF, PILOT_HUB, PIN, READ, RUN_AI,
                     RUN_DEF, SECRETS, hub_defaults, one_workspace, two_workspaces)
from zenux_dashboard import links

ANALYST_TABS = ("briefing", "filtered", "preferences", "coverage")
EXPECTED = {
    "briefing": "Couldn't load your briefings.",
    "filtered": "Couldn't load filtered-out stories.",
    "preferences": "Couldn't load your preferences.",
    "coverage": "Couldn't load coverage areas.",
}
UNREACHABLE = "ZENUX can't be reached right now. This is usually brief. Try again in a minute."


class ErrorStateTests(AppCase):
    def test_every_tab_survives_an_unreachable_hub(self):
        for tab in ANALYST_TABS:
            with self.subTest(tab=tab):
                self.fresh()
                at = self.app(tab=tab)
                self.assert_clean(at)
                text = self.visible_text(at)
                self.assertIn(EXPECTED[tab], text)
                self.assertIn(UNREACHABLE, text)
                self.assertNotIn("ConnectionError", text)  # the technical line is for the builder only
                self.assert_plain(at)
        at = self.app(tab="control", pin=PIN)  # the pilot owner is the builder
        self.assert_clean(at)

    def test_try_again_reads_again(self):
        at = self.app()
        self.assertIn(EXPECTED["briefing"], self.visible_text(at))
        hub_defaults(self.http)
        at.button(key="zx_retry_briefing").click().run()
        self.assert_clean(at)
        self.assertNotIn(EXPECTED["briefing"], self.visible_text(at))

    def test_timeout_and_refused_tokens_are_reported_plainly(self):
        hub_defaults(self.http)
        self.http.on("GET", PILOT_HUB + "/editions", requests.Timeout("read timed out"))
        at = self.app()
        self.assert_clean(at)
        self.assertIn("ZENUX took too long to answer.", self.visible_text(at))
        self.fresh()
        self.http.on("GET", PILOT_HUB + "/editions", FakeResponse(401, {"error": "unauthorized"}))
        at = self.app()
        self.assertIn("The dashboard's access was refused. Tell the builder: the workspace's keys may have changed.",
                      self.visible_text(at))
        self.assertEqual([c.value for c in at.code], [])
        self.fresh()
        at = self.app(pin=PIN)  # the builder sees the technical line, collapsed
        self.assertIn("HTTP 401: token refused", [c.value for c in at.code])

    def test_missing_read_token_is_a_plain_note_not_a_crash(self):
        secrets = one_workspace()
        secrets["workspaces"][0]["read_token"] = ""
        at = self.app(secrets)
        self.assert_clean(at)
        self.assertIn("This workspace isn't fully set up yet. Tell the builder.", self.visible_text(at))
        self.assertEqual(self.http.calls, [])

    def test_malformed_payloads_render_without_crashing(self):
        hub_defaults(self.http)
        self.http.on("GET", PILOT_HUB + "/editions", {"editions": [
            {"id": 1, "items": [{"rank": "x", "headline": None, "sources": "nope", "metrics": {"a": 1}, "why": "x",
                                 "correction": [1]}, "junk"], "shelves": "x", "corrections": [None]},
            "junk", {"items": None}]})
        self.http.on("GET", PILOT_HUB + "/rejected", {"items": [{"title": None, "score": "n/a", "subjects": "x"}, 7]})
        self.http.on("GET", PILOT_HUB + "/preferences", {"preferences": [{"id": None}, {"id": "R-1", "stats": 4}, "x"],
                                                         "suggestions": "x", "summary_7d": None})
        self.http.on("GET", PILOT_HUB + "/modules", {"modules": [{"id": "ai-infra", "counts": "x"}, "x"]})
        self.http.on("GET", PILOT_HUB + "/modules/ai-infra/inspect", {"sources": [None, {"key": 3}],
                                                                      "entities": "x"})
        self.http.on("GET", PILOT_HUB + "/diagnostics", {"severity": {"level": 5}, "routines": "x",
                                                         "last_edition": [1]})
        for tab in ANALYST_TABS:
            with self.subTest(tab=tab):
                self.fresh()
                at = self.app(tab=tab)
                self.assert_clean(at)
                self.assertNotIn("javascript:", self.html(at))

    def test_secrets_never_reach_urls_or_the_page(self):
        hub_defaults(self.http)
        self.http.on("GET", PILOT_HUB + "/snapshot", fx.snapshot())
        self.http.on("GET", PILOT_AI + "/health", fx.module_health("ai-infra"))
        self.http.on("GET", PILOT_DEF + "/health", fx.module_health("defense-unmanned"))
        self.http.on("GET", PILOT_AI + "/backfill", fx.job("done", 3, 0))
        at = self.app(pin=PIN)
        for tab in ANALYST_TABS + ("control",):
            at.radio(key=links.TAB_KEY).set_value(tab).run()
            self.assert_clean(at)
            self.assert_no_secrets(at)
        for call in self.http.calls:
            for secret in SECRETS:
                self.assertNotIn(secret, call.url)
                self.assertNotIn(secret, str(call.params))
                self.assertNotIn(secret, str(call.body))
        self.assertEqual({c.bearer for c in self.http.calls if c.url.startswith(PILOT_HUB)}, {READ})
        self.assertEqual({c.bearer for c in self.http.calls if c.url == PILOT_AI + "/health"}, {RUN_AI})
        self.assertEqual({c.bearer for c in self.http.calls if c.url == PILOT_DEF + "/health"}, {RUN_DEF})

    def test_beta_hub_401_does_not_affect_pilot(self):
        hub_defaults(self.http)
        self.http.on("GET", BETA_HUB + "/editions", FakeResponse(401, {"error": "unauthorized"}))
        at = self.app(two_workspaces())
        self.assertNotIn(EXPECTED["briefing"], self.visible_text(at))
        at.selectbox(key="workspace").set_value("beta").run()
        self.assert_clean(at)
        self.assertIn(EXPECTED["briefing"], self.visible_text(at))
        self.assertIn("The dashboard's access was refused.", self.visible_text(at))
        for call in self.http.calls:
            if call.url.startswith(BETA_HUB):
                self.assertNotEqual(call.bearer, OWNER)


class HubRefusalTests(AppCase):
    """WF3 review CV1: a hub refusal with engine text (ids, "rule draft", "radar", module ids, source keys) is said in
    plain words on every analyst tab, and the read caches are cleared when the record moved on meanwhile."""

    def setUp(self):
        super().setUp()
        hub_defaults(self.http)

    def shown(self, at) -> list[str]:
        return self.texts(at, "error") + self.texts(at, "warning") + self.texts(at, "caption")

    def test_withdrawing_a_request_the_builder_already_approved(self):
        self.http.on("POST", PILOT_HUB + "/radar/46/reject", FakeResponse(
            409, {"error": "radar_closed", "message": "radar request 46 is approved", "status": "approved"}))
        at = self.app(tab="coverage", pin=PIN)
        at.button(key="rq_withdraw_46").click().run()
        reads = len(self.http.find("GET", PILOT_HUB + "/radar"))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. This request has moved on meanwhile (the builder may have approved it). Refresh to "
                      "see where it stands.", self.texts(at, "error"))
        self.assert_plain(at)
        at.button(key="dlg_cancel").click().run()
        self.assertGreater(len(self.http.find("GET", PILOT_HUB + "/radar")), reads)  # read again

    def test_approving_a_suggestion_handled_elsewhere(self):
        self.http.on("POST", PILOT_HUB + "/rules/43/approve", FakeResponse(
            409, {"error": "draft_closed", "message": "rule draft 43 is approved", "status": "approved"}))
        at = self.app(tab="preferences", pin=PIN, query={"section": "ok"})
        at.button(key="sg_approve_43").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. This suggestion was already handled meanwhile. Refresh to see where it stands.",
                      self.texts(at, "error"))
        self.assert_plain(at)

    def test_pausing_a_replaced_preference(self):
        self.http.on("POST", PILOT_HUB + "/rules/R-0014/pause", FakeResponse(409, {
            "error": "superseded",
            "message": "A newer version, R-0019, replaced this preference. Change that one instead."}))
        at = self.app(tab="preferences", pin=PIN, query={"section": "active"})
        at.button(key="pf_pause_R-0014").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. A newer wording replaced this preference. Change that one instead.",
                      self.texts(at, "error"))
        self.assertFalse(any("R-0019" in s for s in self.shown(at)))
        self.assert_plain(at)

    def test_the_mute_preview_of_a_removed_source(self):
        self.http.on("GET", PILOT_HUB + "/mutes/preview", FakeResponse(
            404, {"error": "unknown_source", "message": "No source dcd-news in ai-infra."}))
        at = self.app(tab="filtered", pin=PIN, run=False)
        self.open_popover(at, "zx_more_r7102")
        at.run()
        at.button(key="act_mute_source_r7102").click().run()
        self.assert_clean(at)
        self.assertIn("Couldn't load the 7-day preview. That source is no longer in your coverage. Refresh and try "
                      "again.", self.texts(at, "caption"))
        self.assert_plain(at)


if __name__ == "__main__":
    unittest.main()
