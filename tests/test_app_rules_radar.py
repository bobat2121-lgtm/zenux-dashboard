"""AppTest: the Rules and Radar tabs, including PIN-gated writes."""

from __future__ import annotations

import unittest

import fixtures as fx
from helpers import AppCase, Call, FakeResponse, OWNER, PILOT_HUB, PIN, READ, wrong_pin


class RulesTests(AppCase):
    def setUp(self):
        super().setUp()
        self.rules = fx.rules()
        self.http.on("GET", PILOT_HUB + "/rules", self.rules)
        self.proposed_at_31 = self.rules["drafts"][1]["proposed_at"]

    def test_sections_render(self):
        at = self.app(view="Rules")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("1 for you · 1 with the Zenux Rule refiner · 2 active", self.texts(at, "caption"))
        self.assertIn("Your turn · 1", html)
        self.assertIn("counter drone orders under 1M are watch", html)  # the owner's own words
        self.assertIn("Generalised from three grades.", html)
        self.assertEqual(at.text_area(key="rule_edit_pilot_31").value,
                         "Counter-UAS orders under $1M score in the watch band unless the buyer is new.")
        self.assertIn("With the refiner · 1", html)
        self.assertIn("Grid interconnection approvals for 100 MW+ sites lead.", html)
        self.assertIn("From a grade on: Neocloud signs 200 MW lease · your grade: lead 92", html)
        self.assertIn("became R-0001", html)
        self.assertIn("Active rules and worked examples · 2", html)
        self.assertIn('<span class="rule-id">R-0001</span>', html)
        self.assertIn("A miner&#x27;s routine monthly update", html)
        self.assertIn('<div class="rule-row inactive">', html)  # the retired one, in its expander
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/rules")[0].bearer, READ)

    def test_new_draft_needs_the_pin(self):
        at = self.app(view="Rules")
        at.text_area(key="rules_text_pilot").set_value("Allied counter-UAS orders rank digest for 30 days.")
        at.button(key="rules_send_pilot").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertTrue(any("Owner actions are locked" in w for w in self.texts(at, "warning")))

    def test_new_draft_with_the_pin(self):
        self.http.on("POST", PILOT_HUB + "/rules/drafts", {"id": 33, "status": "queued"})
        at = self.app(view="Rules", pin=PIN)
        at.radio(key="rules_kind_pilot").set_value("Worked example")
        at.text_area(key="rules_text_pilot").set_value("  Allied counter-UAS orders rank digest for 30 days.  ")
        at.button(key="rules_send_pilot").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/rules/drafts")[0]
        self.assertEqual(post.bearer, OWNER)
        self.assertEqual(post.body, {"text": "Allied counter-UAS orders rank digest for 30 days.", "kind": "item"})
        self.assertTrue(any("Zenux Rule refiner" in s for s in self.texts(at, "success")))

    def test_short_draft_is_refused_before_sending(self):
        at = self.app(view="Rules", pin=PIN)
        at.text_area(key="rules_text_pilot").set_value("too short")
        at.button(key="rules_send_pilot").click().run()
        self.assertEqual(self.http.posts(), [])
        self.assertTrue(any("at least a sentence" in i for i in self.texts(at, "info")))

    def test_approve_with_an_edit_reject_and_retire(self):
        for path in ("/rules/31/approve", "/rules/31/reject", "/rules/R-0001/retire", "/rules/32/reject"):
            self.http.on("POST", PILOT_HUB + path, {"ok": True})
        at = self.app(view="Rules", pin=PIN)
        at.text_area(key="rule_edit_pilot_31").set_value("Counter-UAS orders under $1M are watch-band.")
        at.button(key="rule_approve_pilot_31").click().run()
        self.assert_clean(at)
        approve = self.http.find("POST", PILOT_HUB + "/rules/31/approve")[0]
        self.assertEqual((approve.body, approve.bearer), ({"text": "Counter-UAS orders under $1M are watch-band.",
                                                           "proposed_at": self.proposed_at_31}, OWNER))
        self.assertIn("Approved draft #31 · the Grader uses it from its next run", self.texts(at, "success"))
        at.button(key="rule_reject_pilot_31").click().run()
        at.button(key="rule_retire_pilot_R-0001").click().run()
        at.button(key="rule_withdraw_pilot_32").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/rules/31/reject")[0].body, {})
        self.assertEqual(len(self.http.find("POST", PILOT_HUB + "/rules/R-0001/retire")), 1)
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/rules/32/reject")[0].body, {"note": "withdrawn by owner"})

    def test_approve_a_queued_draft_as_written(self):
        self.http.on("POST", PILOT_HUB + "/rules/32/approve", {"draft": {"id": 32}, "precedent": {"id": "I-0002"}})
        at = self.app(view="Rules", pin=PIN)
        at.button(key="rule_approve_now_pilot_32").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/rules/32/approve")[0]
        # The owner's words and kind as shown, bound to "no proposal": a refiner proposal since is refused (409).
        self.assertEqual((post.body, post.bearer), ({"kind": "item", "proposed_at": None,
                                                     "text": "Grid interconnection approvals for 100 MW+ sites lead."},
                                                    OWNER))
        self.assertIn("Approved draft #32 as written", self.texts(at, "success"))

    def test_unchanged_approval_sends_no_text(self):
        self.http.on("POST", PILOT_HUB + "/rules/31/approve", {"ok": True})
        at = self.app(view="Rules", pin=PIN)
        at.button(key="rule_approve_pilot_31").click().run()
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/rules/31/approve")[0].body,
                         {"proposed_at": self.proposed_at_31})

    def hub_binding(self, draft_id: int, refiner_text: str, proposed_at: str) -> list[str]:
        """A fake POST /rules/<id>/approve that behaves like brain.js decideRule once the Rule refiner has proposed
        refiner_text at proposed_at: a body naming another proposed_at is 409 proposal_changed (nothing activated);
        a body naming none activates its own text, else the refiner's (the race the binding closes)."""
        activated: list[str] = []

        def approve(call: Call):
            body = call.body or {}
            if "proposed_at" in body and body["proposed_at"] != proposed_at:
                return FakeResponse(409, {"error": "proposal_changed", "message": "reload it and review it again",
                                          "status": "proposed", "proposed_at": proposed_at})
            activated.append(body.get("text") or refiner_text)
            return {"draft": {"id": draft_id, "status": "approved"}, "precedent": {"id": "I-0002", "text": activated[-1]}}

        self.http.on("POST", PILOT_HUB + f"/rules/{draft_id}/approve", approve)
        return activated

    def test_approve_as_written_never_activates_a_proposal_the_owner_did_not_see(self):
        at = self.app(view="Rules", pin=PIN)  # draft 32 is waiting: no proposal on screen
        refined, later = "Grid interconnection approvals of 100 MW or more lead the edition.", fx.iso(0.01)
        updated = fx.rules()
        updated["drafts"][0].update(status="proposed", proposed_at=later, proposal={"text": refined, "kind": "item"})
        self.http.on("GET", PILOT_HUB + "/rules", updated)  # the refiner proposed after the page read the list
        activated = self.hub_binding(32, refined, later)
        at.button(key="rule_approve_now_pilot_32").click().run()
        self.assert_clean(at)
        self.assertEqual(activated, [])  # nothing activated: neither the refiner's words nor the owner's
        self.assertIsNone(self.http.find("POST", PILOT_HUB + "/rules/32/approve")[0].body["proposed_at"])
        self.assertEqual(self.texts(at, "success"), [])
        self.assertTrue(any("proposed a wording for draft #32 after this page loaded, so nothing was approved" in w
                            for w in self.texts(at, "warning")))
        # The list was read again: the proposal is now on screen, and approving it names the version shown.
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/rules")), 2)
        self.assertEqual(at.text_area(key="rule_edit_pilot_32").value, refined)
        at.button(key="rule_approve_pilot_32").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/rules/32/approve")[-1].body, {"proposed_at": later})
        self.assertEqual(activated, [refined])
        self.assertIn("Approved draft #32 · the Grader uses it from its next run", self.texts(at, "success"))

    def test_a_changed_proposal_is_reviewed_again(self):
        at = self.app(view="Rules", pin=PIN)
        at.text_area(key="rule_edit_pilot_31").set_value("Counter-UAS orders under $1M are watch-band.")
        newer = fx.iso(0.01)
        updated = fx.rules()
        updated["drafts"][1].update(proposed_at=newer, proposal={"text": "A newer refiner wording for draft 31."})
        self.http.on("GET", PILOT_HUB + "/rules", updated)
        activated = self.hub_binding(31, "A newer refiner wording for draft 31.", newer)
        at.button(key="rule_approve_pilot_31").click().run()
        self.assert_clean(at)
        self.assertEqual(activated, [])
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/rules/31/approve")[0].body,
                         {"text": "Counter-UAS orders under $1M are watch-band.", "proposed_at": self.proposed_at_31})
        self.assertTrue(any("newer proposal for draft #31 than the one shown, so nothing was approved" in w
                            for w in self.texts(at, "warning")))
        self.assertEqual(at.text_area(key="rule_edit_pilot_31").value, "A newer refiner wording for draft 31.")

    def test_write_error_is_shown(self):
        self.http.on("POST", PILOT_HUB + "/rules/R-0001/retire", FakeResponse(409, {"error": "already_retired"}))
        at = self.app(view="Rules", pin=PIN)
        at.button(key="rule_retire_pilot_R-0001").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved: HTTP 409: already_retired", self.texts(at, "error"))

    def test_no_rules_yet_and_unreachable(self):
        self.http.on("GET", PILOT_HUB + "/rules", {"rules": [], "drafts": []})
        at = self.app(view="Rules")
        self.assertIn("No learned rules yet", self.html(at))
        self.fresh()
        self.http.routes.clear()
        at = self.app(view="Rules")
        self.assert_clean(at)
        self.assertIn("Could not load rules from the Pilot hub.", self.html(at))


class RadarTests(AppCase):
    def setUp(self):
        super().setUp()
        self.radar = fx.radar()
        self.http.on("GET", PILOT_HUB + "/radar", self.radar)
        self.proposed_at_41 = self.radar["requests"][1]["proposed_at"]

    def test_sections_render(self):
        at = self.app(view="Radar")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("1 for you · 1 with the Zenux Radar scout · 1 decided", self.texts(at, "caption"))
        self.assertIn("Follow the Texas PUC large-load docket", html)
        self.assertIn("Add the PUCT docket filings feed to ai-infra.", html)
        self.assertIn('<td>ai-infra</td><td><span class="mono">puct-large-load</span></td><td>html-list</td>'
                      '<td>power_policy</td><td>official</td>', html)
        self.assertIn("1 registry change: Oncor Electric Delivery", html)
        self.assertIn("Verified one fetch: 200, 40 filings listed.", html)
        self.assertIn('<span class="status-pill ok">approved pending apply</span>', html)
        self.assertIn("Your note: Start with the trade feeds", html)
        self.assertIn('href="https://interchange.puc.texas.gov/"', html)
        self.assertIn("With the scout · 1", html)
        self.assertIn('<span class="loop-kind loop-kind-missed_story">Missed story</span>', html)
        self.assertEqual(at.json[0].value.count("puct-large-load"), 1)
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/radar")[0].bearer, READ)

    def test_new_request_validation_and_send(self):
        self.http.on("POST", PILOT_HUB + "/radar/requests", {"id": 43})
        at = self.app(view="Radar", pin=PIN)
        at.radio(key="radar_kind_pilot").set_value("Missed story")
        at.text_area(key="radar_text_pilot").set_value("We missed the Anduril Fury award")
        at.button(key="radar_send_pilot").click().run()
        self.assertTrue(any("Paste the story's link" in i for i in self.texts(at, "info")))
        at.text_input(key="radar_url_pilot").set_value("ftp://example.com/x")
        at.button(key="radar_send_pilot").click().run()
        self.assertTrue(any("must start with https://" in i for i in self.texts(at, "info")))
        self.assertEqual(self.http.posts(), [])
        at.text_input(key="radar_url_pilot").set_value("https://example.com/fury")
        at.selectbox(key="radar_module_pilot").set_value("defense-unmanned")
        at.button(key="radar_send_pilot").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/radar/requests")[0]
        self.assertEqual(post.bearer, OWNER)
        self.assertEqual(post.body, {"kind": "missed_story", "text": "We missed the Anduril Fury award",
                                     "url": "https://example.com/fury", "module": "defense-unmanned"})

    def test_approve_and_reject_with_a_note(self):
        self.http.on("POST", PILOT_HUB + "/radar/41/approve", {"ok": True})
        self.http.on("POST", PILOT_HUB + "/radar/41/reject", {"ok": True})
        self.http.on("POST", PILOT_HUB + "/radar/42/reject", {"ok": True})
        at = self.app(view="Radar", pin=PIN)
        at.text_input(key="radar_note_pilot_41").set_value("Use a 120-minute cadence")
        at.button(key="radar_approve_pilot_41").click().run()
        self.assert_clean(at)
        approve = self.http.find("POST", PILOT_HUB + "/radar/41/approve")[0]
        self.assertEqual((approve.body, approve.bearer),
                         ({"note": "Use a 120-minute cadence", "proposed_at": self.proposed_at_41}, OWNER))
        self.assertIn("Approved radar request #41", self.texts(at, "success"))
        at.button(key="radar_reject_pilot_41").click().run()
        at.button(key="radar_withdraw_pilot_42").click().run()
        self.assertEqual(len(self.http.find("POST", PILOT_HUB + "/radar/41/reject")), 1)
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/radar/42/reject")[0].body, {"note": "withdrawn by owner"})

    def test_approval_is_bound_to_the_proposal_shown(self):
        at = self.app(view="Radar", pin=PIN)
        newer = fx.iso(0.01)
        updated = fx.radar()
        updated["requests"][1].update(proposed_at=newer, proposal={"summary": "A different scout proposal."})
        self.http.on("GET", PILOT_HUB + "/radar", updated)
        approved: list[dict] = []

        def approve(call: Call):  # brain.js decideRadar with body.proposed_at
            if "proposed_at" in (call.body or {}) and call.body["proposed_at"] != newer:
                return FakeResponse(409, {"error": "proposal_changed", "proposed_at": newer})
            approved.append(call.body)
            return {"id": 41, "status": "approved_pending_apply"}

        self.http.on("POST", PILOT_HUB + "/radar/41/approve", approve)
        at.button(key="radar_approve_pilot_41").click().run()
        self.assert_clean(at)
        self.assertEqual(approved, [])
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/radar/41/approve")[0].body,
                         {"proposed_at": self.proposed_at_41})
        self.assertTrue(any("newer proposal for radar request #41 than the one shown, so nothing was approved" in w
                            for w in self.texts(at, "warning")))
        self.assertIn("A different scout proposal.", self.html(at))  # read again for the owner to review
        at.button(key="radar_approve_pilot_41").click().run()
        self.assertEqual(approved, [{"proposed_at": newer}])
        self.assertIn("Approved radar request #41", self.texts(at, "success"))

    def test_decisions_are_locked_without_the_pin(self):
        at = self.app(view="Radar", pin="bad")
        at.button(key="radar_approve_pilot_41").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertIn(wrong_pin("pilot"), self.texts(at, "error"))

    def test_nothing_waiting_and_unreachable(self):
        self.http.on("GET", PILOT_HUB + "/radar", {"requests": []})
        at = self.app(view="Radar")
        self.assertIn("Nothing waiting.", self.html(at))
        self.fresh()
        self.http.on("GET", PILOT_HUB + "/radar", FakeResponse(200, no_json=True))
        at = self.app(view="Radar")
        self.assert_clean(at)
        self.assertIn("HTTP 200: response is not JSON", self.html(at))


if __name__ == "__main__":
    unittest.main()
