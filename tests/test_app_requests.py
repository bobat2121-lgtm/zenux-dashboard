"""AppTest: coverage requests on the Coverage tab: the composer (validation, bodies, toast and withdraw undo), every
stage of the timeline, source states and first stories, Withdraw behind a confirmation, and no technical field on the
analyst's page."""

from __future__ import annotations

import unittest
from typing import Any

import fixtures as fx
import fixtures_coverage as fc
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, READ, hub_defaults
from zenux_dashboard import labels, radar_view, ui
from zenux_dashboard.fmt import fmt_date

RADAR = PILOT_HUB + "/radar"
RADAR_NEW = PILOT_HUB + "/radar/requests"
TZ = "America/New_York"
SCOUT_NEXT = "2026-10-04T17:00:00Z"  # 1:00 PM ET
CONFIRM = "dlg_save"  # the confirm button of ui.ask_confirm (dialog keys are dlg_*)


def undo_of(at) -> Any:
    try:
        return at.session_state[ui.UNDO_KEY]
    except KeyError:
        return None


def field(obj: Any, name: str) -> Any:
    return getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)


class RequestsCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        h = self.http
        h.on("GET", PILOT_HUB + "/modules", fc.modules())
        h.on("GET", PILOT_HUB + "/modules/ai-infra/inspect", fc.inspect_ai())
        h.on("GET", PILOT_HUB + "/modules/defense-unmanned/inspect", fc.inspect_def())
        h.on("GET", PILOT_HUB + "/settings", fc.settings())
        h.on("GET", PILOT_HUB + "/mutes", fc.mutes())
        self.radar = fc.radar_requests()
        h.on("GET", RADAR, self.radar)
        diag = fx.diagnostics()
        diag["routines"]["scout"]["next_due_at"] = SCOUT_NEXT
        h.on("GET", PILOT_HUB + "/diagnostics", diag)

    def coverage(self, **kwargs):
        return self.app(tab="coverage", **kwargs)

    @staticmethod
    def date(hours_ago: float) -> str:
        return fmt_date(fx.iso(hours_ago), TZ)

    def step(self, css: str, label: str, hours_ago: float | None = None) -> str:
        when = f"<br><span>{self.date(hours_ago)}</span>" if hours_ago is not None else ""
        return f'<div class="timeline-step{" " + css if css else ""}">{label}{when}</div>'


class ListTests(RequestsCase):
    def test_every_stage_with_its_timeline(self):
        at = self.coverage()
        self.assert_clean(at)
        html = self.html(at)
        self.assertEqual(self.http.find("GET", RADAR)[0].bearer, READ)
        # asked
        self.assertIn('<div class="timeline">' + self.step("current", "Asked", 2) + self.step("", "Proposal ready")
                      + self.step("", "Approved, waiting for setup") + self.step("", "Set up") + self.step("", "Live")
                      + "</div>", html)
        self.assertIn("A missed story · asked ", html)
        self.assertIn(" · Defense tech</div>", html)
        self.assertIn("You asked: We missed the Shield AI Hivemind award", html)
        self.assertIn("The source finder looks into it at its next run.", html)
        # proposal: the plain summary (the area id replaced by its name), the diagnosis and the source's state
        self.assertIn(self.step("done", "Asked", 26) + self.step("current", "Proposal ready", 20), html)
        self.assertIn('<div class="rule-text">Add the PUCT docket filings feed to AI infrastructure.</div>', html)
        self.assertIn("No source ZENITH reads covered it.", html)
        self.assertIn("Texas PUC large-load docket: Waiting for setup", html)
        self.assertIn("A proposal is ready. The builder reviews it and sets it up.", html)
        # approved
        self.assertIn(self.step("current", "Approved, waiting for setup", 90), html)
        self.assertIn("Approved. The builder is setting it up.", html)
        # applied: in the coverage list, no stories yet
        self.assertIn(self.step("current", "Set up", 5) + self.step("", "Live"), html)
        self.assertIn("Loudoun County, VA agendas: Added", html)
        self.assertIn("No stories from it yet.", html)
        # live: collecting, first stories counted
        self.assertIn(self.step("done", "Set up", 100) + self.step("current", "Live", 50), html)
        self.assertIn("ERCOT large-load interconnection reports: Collecting", html)
        self.assertIn("5 stories collected from it so far.", html)
        self.assertIn("A source that covers it wasn&#x27;t responding.", html)
        # rejected: Asked and Not added only, with the reason
        self.assertIn(self.step("done", "Asked", 410) + self.step("current", "Not added", 400) + "</div>", html)
        self.assertIn("Not added · You withdrew this request.", html)
        self.assertIn("Not added · Paywalled: we cannot read it.", html)
        # Withdraw only while asked or proposed
        self.assertEqual([b.key for b in at.button if str(b.key or "").startswith("rq_withdraw_")],
                         ["rq_withdraw_46", "rq_withdraw_45"])
        # nothing technical on the analyst's page
        for word in ("puct-large-load", "html-list", "power_grid", "registry", "loudoun-agendas"):
            self.assertNotIn(word, html)
        self.assertEqual([j for j in at.json], [])
        self.assert_plain(at)
        self.assert_no_secrets(at)

    def test_the_hubs_plain_proposal_and_first_stories(self):
        # gaps 20 and 31: the newest stories from the new sources, the summary with area names, the plain diagnosis
        body = fc.radar_requests()
        by_id = {r["id"]: r for r in body["requests"]}
        by_id[45]["proposal_plain"] = {"summary": "Add the docket filings feed to AI infrastructure.", "notes": None,
                                       "cause": "None of your sources carries it."}
        by_id[42]["first_stories"] = [{"event_id": 8801, "title": "ERCOT posts the <October> large-load report",
                                       "url": "https://example.com/ercot", "published_at": fx.iso(30)}]
        body.update(total=240, limit=200, has_more=True)
        self.http.on("GET", RADAR, body)
        at = self.coverage()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="rule-text">Add the docket filings feed to AI infrastructure.</div>', html)
        self.assertIn("None of your sources carries it.", html)
        self.assertNotIn("No source ZENITH reads covered it.", html)
        self.assertIn(f"First stories: ERCOT posts the &lt;October&gt; large-load report ({self.date(30)})", html)
        self.assertNotIn("5 stories collected from it so far.", html)
        self.assertIn(f"The newest {len(body['requests'])} of 240 coverage requests are listed.",
                      self.texts(at, "caption"))
        self.assert_plain(at)

    def test_newest_first_and_a_linked_request_first_of_all(self):
        at = self.coverage()
        html = self.html(at)
        self.assertLess(html.index("We missed the Shield AI"), html.index("Follow the Texas PUC"))
        at = self.coverage(query={"tab": "coverage", "request": "43"})
        self.assert_clean(at)
        html = self.html(at)
        self.assertLess(html.index("Track the Loudoun County agendas"), html.index("We missed the Shield AI"))
        self.assertIn('<div class="rq-card zx-focus">', html)
        self.assertEqual(html.count("zx-focus"), 1)

    def test_no_requests_yet(self):
        self.http.on("GET", RADAR, {"requests": []})
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("No coverage requests yet. Ask above; the source finder answers after its next run.", self.html(at))

    def test_read_error_keeps_the_composer(self):
        self.http.on("GET", RADAR, FakeResponse(500, {"error": "internal"}))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("Couldn't load your coverage requests.", self.visible_text(at))
        self.assertIsNotNone(at.button(key="zx_retry_requests"))
        self.assertIsNotNone(at.button(key="rq_send"))


class ComposerTests(RequestsCase):
    def test_ask_for_a_source_body_toast_and_withdraw_undo(self):
        self.http.on("POST", RADAR_NEW, FakeResponse(201, fc.radar_created(47)))
        self.http.on("POST", PILOT_HUB + "/radar/47/reject", {"id": 47, "status": "rejected"})
        at = self.coverage(pin=PIN)
        self.assertEqual(at.segmented_control(key="rq_kind").value, "source_or_topic")
        self.assertEqual(at.radio(key="rq_what").value, "track_source")
        self.assertEqual(list(at.radio(key="rq_what").options), ["A source", "A company or topic"])
        self.assertEqual(at.selectbox(key="rq_area").value, "ai-infra")  # the coverage area shown above
        at.text_area(key="rq_text").input("  Follow the Texas PUC large-load docket filings  ")
        at.button(key="rq_send").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", RADAR_NEW)[0]
        self.assertEqual((post.body, post.bearer), ({"kind": "track_source", "module": "ai-infra",
                                                     "text": "Follow the Texas PUC large-load docket filings"}, OWNER))
        self.assertIn("Sent to the source finder. It answers after its next run (about 1:00 PM ET).", self.toasts(at))
        self.assertEqual(at.text_area(key="rq_text").value, "")  # cleared after a send
        undo = undo_of(at)
        self.assertEqual((field(undo, "text"), field(undo, "done")), ("Sent a coverage request.", "Request withdrawn."))
        field(undo, "run")(OWNER)
        withdraw = self.http.find("POST", PILOT_HUB + "/radar/47/reject")[0]
        self.assertEqual((withdraw.body, withdraw.bearer), ({"note": "withdrawn by owner"}, OWNER))

    def test_a_company_or_topic_with_no_area(self):
        self.http.on("POST", RADAR_NEW, FakeResponse(201, fc.radar_created(48, "new_coverage")))
        at = self.coverage(pin=PIN)
        at.radio(key="rq_what").set_value("new_coverage")
        at.selectbox(key="rq_area").set_value("")
        at.text_area(key="rq_text").input("Cover sodium-ion storage for data centers")
        at.button(key="rq_send").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", RADAR_NEW)[0].body,
                         {"kind": "new_coverage", "text": "Cover sodium-ion storage for data centers"})

    def test_missed_story_validation_then_send(self):
        self.http.on("POST", RADAR_NEW, FakeResponse(201, fc.radar_created(49, "missed_story")))
        at = self.coverage(pin=PIN)
        at.segmented_control(key="rq_kind").set_value("missed_story").run()
        self.assertNotIn("rq_what", [r.key for r in at.radio])
        self.assertEqual(at.text_input(key="rq_url").proto.placeholder, "https://… (required)")
        at.text_area(key="rq_text").input("too short")
        at.button(key="rq_send").click().run()
        self.assertIn(radar_view.TEXT_MESSAGE, self.texts(at, "info"))
        at.text_area(key="rq_text").input("Army order for 500 interceptors")
        at.button(key="rq_send").click().run()
        self.assertIn("Paste the story's link so the source finder can see what was missed.", self.texts(at, "info"))
        at.text_input(key="rq_url").input("ftp://example.com/x")
        at.button(key="rq_send").click().run()
        self.assertIn("The link must start with https:// or http://.", self.texts(at, "info"))
        self.assertEqual(self.http.posts(), [])
        at.text_input(key="rq_url").input("https://example.com/interceptors")
        at.selectbox(key="rq_area").set_value("defense-unmanned")
        at.button(key="rq_send").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", RADAR_NEW)[0]
        self.assertEqual(post.body, {"kind": "missed_story", "text": "Army order for 500 interceptors",
                                     "url": "https://example.com/interceptors", "module": "defense-unmanned"})

    def test_toast_without_a_known_next_run(self):
        self.http.on("GET", PILOT_HUB + "/diagnostics", FakeResponse(503, {"error": "x"}))
        self.http.on("POST", RADAR_NEW, FakeResponse(201, fc.radar_created(47)))
        at = self.coverage(pin=PIN)
        at.text_area(key="rq_text").input("Follow the Texas PUC large-load docket filings")
        at.button(key="rq_send").click().run()
        self.assert_clean(at)
        self.assertIn("Sent to the source finder. It answers after its next run.", self.toasts(at))

    def test_a_refused_request_shows_the_hub_sentence(self):
        self.http.on("POST", RADAR_NEW, FakeResponse(400, {"error": "invalid_radar",
                                                           "message": "The link is not a web address."}))
        at = self.coverage(pin=PIN)
        at.text_area(key="rq_text").input("Follow the Texas PUC large-load docket filings")
        at.button(key="rq_send").click().run()
        self.assert_clean(at)
        self.assertTrue(any("The link is not a web address." in e for e in self.texts(at, "error")))
        self.assertEqual(at.text_area(key="rq_text").value, "Follow the Texas PUC large-load docket filings")

    def test_locked_composer_and_withdraw(self):
        at = self.coverage()
        self.assert_clean(at)
        self.assertTrue(at.button(key="rq_send").disabled)
        self.assertTrue(at.button(key="rq_withdraw_46").disabled)
        self.assertEqual(at.button(key="rq_withdraw_46").proto.help, labels.LOCKED_HELP)
        self.assertIn(":material/lock: " + labels.LOCKED_HELP, self.texts(at, "caption"))
        self.assertEqual(self.http.posts(), [])


class WithdrawTests(RequestsCase):
    def test_withdraw_asks_first_then_sends(self):
        self.http.on("POST", PILOT_HUB + "/radar/46/reject", {"id": 46, "status": "rejected"})
        at = self.coverage(pin=PIN)
        at.button(key="rq_withdraw_46").click().run()
        self.assert_clean(at)
        self.assertIn("The source finder stops working on it.", self.visible_text(at))
        self.assertEqual(self.http.posts(), [])
        at.button(key=CONFIRM).click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/radar/46/reject")[0]
        self.assertEqual((post.body, post.bearer), ({"note": "withdrawn by owner"}, OWNER))
        self.assertIn("Withdrawn.", self.toasts(at))
        self.assertIsNone(undo_of(at))  # no route reopens a request
        self.assertEqual(len(self.http.find("GET", RADAR)), 2)  # read again

    def test_cancel_sends_nothing(self):
        at = self.coverage(pin=PIN)
        at.button(key="rq_withdraw_45").click().run()
        at.button(key="dlg_cancel").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])


if __name__ == "__main__":
    unittest.main()
