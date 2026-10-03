"""AppTest: the Rejected tab."""

from __future__ import annotations

import unittest

import fixtures as fx
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, READ


class RejectedTests(AppCase):
    def setUp(self):
        super().setUp()
        self.http.on("GET", PILOT_HUB + "/rejected", fx.rejected())

    def test_rows_render_with_decision_chips_and_rationale(self):
        at = self.app(view="Rejected")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Showing 1–3 of 3 total · newest first · last 3 days", html)
        self.assertLess(html.index("#7001"), html.index("#7002"))
        self.assertLess(html.index("#7002"), html.index("#7003"))
        self.assertIn('<span class="rejected-chip decision">duplicate</span>', html)
        self.assertIn('<span class="rejected-chip ">same event as #9002</span>', html)
        self.assertIn('<span class="rejected-chip score">score 31</span>', html)
        self.assertIn('<span class="rejected-chip ">below materiality</span>', html)
        self.assertIn("<strong>Grader rationale</strong> · Routine monthly update; no material change.", html)
        self.assertIn('<span class="zx-chip grade">your grade: watch 55</span>', html)
        call = self.http.find("GET", PILOT_HUB + "/rejected")[0]
        self.assertEqual((call.params, call.bearer), ({"days": 3}, READ))

    def test_window_module_and_decision_filters(self):
        at = self.app(view="Rejected")
        at.selectbox(key="rej_days_pilot").set_value(7).run()
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/rejected")[-1].params, {"days": 7})
        at.selectbox(key="rej_module_pilot").set_value("defense-unmanned").run()
        html = self.html(at)
        self.assertNotIn("#7001", html)
        self.assertIn("#7002", html)
        self.assertIn("of 2 loaded", html)
        at.selectbox(key="rej_decision_pilot").set_value("duplicate").run()
        html = self.html(at)
        self.assertIn("#7002", html)
        self.assertNotIn("#7003", html)
        self.assert_clean(at)

    def test_empty_window(self):
        self.http.on("GET", PILOT_HUB + "/rejected", {"items": [], "total": 0})
        at = self.app(view="Rejected")
        self.assert_clean(at)
        self.assertIn("Nothing rejected in this window.", self.html(at))

    def test_hub_error(self):
        self.http.on("GET", PILOT_HUB + "/rejected", FakeResponse(500, {"error": "internal_error"}))
        at = self.app(view="Rejected")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Could not load rejected events from the Pilot hub.", html)
        self.assertIn("HTTP 500: internal_error", html)

    def test_grade_a_rejected_event(self):
        self.http.on("POST", PILOT_HUB + "/feedback", FakeResponse(201, {"id": 5, "draft_id": 9}))
        at = self.app(view="Rejected", pin=PIN, grading=True)
        key = "rej_pilot"
        self.assertEqual(list(at.selectbox(key=f"gitem_{key}").options)[0], "#7001 · Miner monthly production update")
        at.selectbox(key=f"gitem_{key}").set_value("event-7003")
        at.number_input(key=f"gscore_{key}").set_value(91)
        at.radio(key=f"gscope_{key}").set_value("Worked example")
        at.text_area(key=f"gnote_{key}").set_value("A first production order for a new service always leads.")
        at.button(key=f"gsubmit_{key}").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/feedback")[0]
        self.assertEqual(post.bearer, OWNER)
        self.assertEqual(post.body, {"event_id": 7003, "score": 91, "verdict": "lead",
                                     "scope": "case", "note": "A first production order for a new service always leads."})
        self.assertIn("Grade stored #5 · lead 91 · draft #9 queued for the Zenux Rule refiner", self.texts(at, "success"))

    def test_feedback_rejected_by_the_hub(self):
        self.http.on("POST", PILOT_HUB + "/feedback", FakeResponse(422, {"error": "event_not_in_window"}))
        at = self.app(view="Rejected", pin=PIN, grading=True)
        at.button(key="gsubmit_rej_pilot").click().run()
        self.assert_clean(at)
        self.assertIn("The grade was not stored: HTTP 422: event_not_in_window", self.texts(at, "error"))


if __name__ == "__main__":
    unittest.main()
