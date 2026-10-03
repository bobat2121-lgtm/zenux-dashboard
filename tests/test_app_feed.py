"""AppTest: the app shell (masthead, workspace switcher, config states) and the Feed tab."""

from __future__ import annotations

import unittest

import fixtures as fx
from helpers import (AppCase, BETA_HUB, BETA_READ, FakeResponse, OWNER, PILOT_HUB, PIN, READ, beta_secrets,
                     one_workspace, two_workspaces, wrong_pin)


class ShellTests(AppCase):
    def test_masthead_is_zenux_and_workspace_aware(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('aria-label="ZENUX"', html)
        self.assertIn('ZENU<span class="brand-accent">X</span>', html)
        self.assertIn('<span class="brand-workspace">PILOT</span>', html)
        self.assertNotIn("PHYSICAL", html)
        view = at.radio(key="dashboard_view")
        self.assertEqual(list(view.options), ["Feed", "Rejected", "Rules", "Radar", "Diagnostics"])
        self.assertEqual(view.value, "Feed")
        # one workspace: no switcher
        self.assertEqual([s.key for s in at.selectbox if s.key == "workspace"], [])

    def test_no_configuration(self):
        at = self.app({"zenux": {"note": "no workspaces here"}})
        self.assert_clean(at)
        self.assertIn("No Zenux workspace is configured", self.html(at))
        self.assertEqual(self.http.calls, [])

    def test_invalid_configuration_lists_problems_without_values(self):
        at = self.app({"workspaces": [{"id": "Bad Id", "read_token": "not-shown-value"}]})
        self.assert_clean(at)
        captions = "\n".join(self.texts(at, "caption"))
        self.assertIn("workspace #1: id is missing or invalid", captions)
        self.assertNotIn("not-shown-value", captions + self.html(at))

    def test_workspace_switcher_reads_the_other_hub(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())
        beta = fx.editions(1, start_id=3)
        beta["editions"][0]["note"] = "Beta analyst edition"
        self.http.on("GET", BETA_HUB + "/editions", beta)
        at = self.app(two_workspaces())
        self.assert_clean(at)
        switcher = at.selectbox(key="workspace")
        self.assertEqual(list(switcher.options), ["Pilot", "Beta analyst"])
        self.assertIn("Two items cleared the bar.", self.html(at))
        switcher.set_value("beta").run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Beta analyst edition", html)
        self.assertIn('<span class="brand-workspace">BETA ANALYST</span>', html)
        beta_calls = self.http.find("GET", BETA_HUB + "/editions")
        self.assertEqual(len(beta_calls), 1)
        self.assertEqual(beta_calls[0].bearer, BETA_READ)

    def test_owner_popover_reports_the_lock(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())
        at = self.app(pin="wrong-pin")
        self.assertIn(wrong_pin("pilot"), self.texts(at, "caption"))
        at.text_input(key="owner_pin").set_value(PIN).run()
        self.assertIn("Owner actions unlocked for pilot.", self.texts(at, "caption"))
        self.assert_no_secrets(at)


class FeedTests(AppCase):
    def setUp(self):
        super().setUp()
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())

    def test_editions_render_newest_first_with_the_legacy_card_design(self):
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        self.assertLess(html.index("Edition #12"), html.index("Edition #11"))
        self.assertIn('<div class="edition-note">Two items cleared the bar.</div>', html)
        self.assertEqual(html.count('<span class="latest-badge">LATEST</span>'), 1)
        self.assertIn('<section class="feed-edition latest-edition">', html)
        self.assertIn('<div class="rank-marker">01</div>', html)
        # escaped headline and text; the blank line in the text never reaches the HTML block
        self.assertIn("Neocloud signs 200 MW &lt;lease&gt; with hyperscaler", html)
        self.assertIn("critical IT capacity.<br>Energization is planned for 2027.", html)
        # stats panel on the latest edition
        self.assertIn('<div class="stat"><div class="stat-n">2</div><div class="stat-l">ITEMS</div></div>', html)
        self.assertIn('<div class="stat"><div class="stat-n">41</div><div class="stat-l">REVIEWED</div></div>', html)
        self.assertIn('<div class="stat stat-high"><div class="stat-n">1</div><div class="stat-l">LEAD 90+</div></div>', html)
        self.assertIn('<span><i style="background:#b692f6"></i>AI-INFRA 1</span>', html)
        # metrics, sources and score badges
        self.assertIn('<span class="feed-metric">Critical IT <b>200 MW</b></span>', html)
        self.assertIn('href="https://example.com/neocloud-lease"', html)
        self.assertIn('<span class="value-badge level-high">score 93</span>', html)
        self.assertIn('<span class="value-badge level-medium">score 78</span>', html)
        self.assertIn('<span class="zx-chip score">your grade: digest 80</span>', html)  # the owner's earlier grade
        self.assertIn('<span class="feed-metric">Term <b>15 years</b></span>', html)
        self.assertIn("Tier 3 · catalyst", html)
        # an unsafe source link is dropped, never rendered as a link
        self.assertNotIn("javascript:", html)
        self.assertNotIn("\n\n", html)
        call = self.http.find("GET", PILOT_HUB + "/editions")[0]
        self.assertEqual(call.params, {"limit": 10})
        self.assertEqual(call.bearer, READ)
        self.assert_no_secrets(at)

    def test_search_filters_loaded_items(self):
        at = self.app()
        at.text_input(key="feed_search").set_value("counter-uas").run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("2 search results", html)
        self.assertIn("Army awards $48M counter-UAS order", html)
        self.assertNotIn("Neocloud signs", html)
        self.assertNotIn("LATEST", html)
        at.text_input(key="feed_search").set_value("no such company").run()
        self.assertIn("No matching stories", self.html(at))

    def test_load_earlier_editions_pages_with_before(self):
        first = {"editions": fx.editions(1, start_id=20)["editions"], "next_before": 20, "has_more": True}
        older = {"editions": [dict(fx.editions(1, start_id=9)["editions"][0], note="Older edition nine",
                                   published_at=fx.iso(200))], "next_before": None, "has_more": False}
        self.http.on("GET", PILOT_HUB + "/editions", lambda call: older if call.params.get("before") == "20" else first)
        at = self.app()
        self.assertNotIn("Older edition nine", self.html(at))
        at.button(key="feed_more_pilot").click().run()
        self.assert_clean(at)
        self.assertIn("Older edition nine", self.html(at))
        self.assertEqual([c.params.get("before") for c in self.http.find("GET", PILOT_HUB + "/editions")][-2:],
                         [None, "20"])
        self.assertEqual([b.key for b in at.button if b.key == "feed_more_pilot"], [])

    def test_no_editions_yet(self):
        self.http.on("GET", PILOT_HUB + "/editions", {"editions": []})
        at = self.app()
        self.assert_clean(at)
        self.assertIn("No editions yet", self.html(at))

    def test_empty_edition_says_nothing_material(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.empty_edition())
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Nothing material in this window", html)
        self.assertIn('<div class="stat-n">0</div><div class="stat-l">ITEMS</div>', html)

    def test_hub_unreachable(self):
        self.http.routes.clear()
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Could not load editions from the Pilot hub.", html)
        self.assertIn("unreachable (ConnectionError)", html)

    def test_token_refused(self):
        self.http.on("GET", PILOT_HUB + "/editions", FakeResponse(401, {"error": "unauthorized"}))
        at = self.app()
        self.assertIn("HTTP 401: token refused", self.html(at))
        self.assert_no_secrets(at)

    def test_grade_an_item_posts_feedback_with_the_owner_token(self):
        self.http.on("POST", PILOT_HUB + "/feedback", FakeResponse(201, {"id": 77, "draft_id": 9}))
        at = self.app(pin=PIN, grading=True)
        self.assert_clean(at)
        self.assertIn('class="feed-edition latest-edition owner-edition"', self.html(at))
        key = "ed_pilot_12"
        self.assertEqual(list(at.selectbox(key=f"gitem_{key}").options),
                         ["1. Neocloud signs 200 MW <lease> with hyperscaler", "2. Army awards $48M counter-UAS order"])
        at.selectbox(key=f"gitem_{key}").set_value("item-1202")
        at.radio(key=f"ggrade_{key}").set_value("Lead")
        at.text_area(key=f"gnote_{key}").set_value("Counter-UAS production orders for the Army lead the digest.")
        at.radio(key=f"gscope_{key}").set_value("Rule")
        at.button(key=f"gsubmit_{key}").click().run()
        self.assert_clean(at)
        posts = self.http.find("POST", PILOT_HUB + "/feedback")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].bearer, OWNER)
        self.assertEqual(posts[0].body, {
            "item_id": 1202, "event_id": 9002, "verdict": "lead",
            "scope": "rule", "note": "Counter-UAS production orders for the Army lead the digest.",
        })
        self.assertIn("Grade stored #77 · lead · draft #9 queued for the Zenux Rule refiner", self.texts(at, "success"))

    def test_factual_error_keeps_its_verdict_with_a_score(self):
        self.http.on("POST", PILOT_HUB + "/feedback", FakeResponse(201, {"id": 78, "draft_id": None}))
        at = self.app(pin=PIN, grading=True)
        key = "ed_pilot_12"
        at.radio(key=f"ggrade_{key}").set_value("Factual error")
        at.number_input(key=f"gscore_{key}").set_value(10)
        at.text_area(key=f"gnote_{key}").set_value("The lease is 150 MW, not 200 MW.")
        at.button(key=f"gsubmit_{key}").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/feedback")[0].body, {
            "item_id": 1201, "event_id": 9001, "score": 10, "verdict": "factual_error", "scope": "item",
            "note": "The lease is 150 MW, not 200 MW."})
        self.assertIn("Grade stored #78 · factual error 10", self.texts(at, "success"))

    def test_items_without_an_item_id_are_graded_by_edition_and_rank(self):
        body = fx.editions(1)
        for item in body["editions"][0]["items"]:
            item.pop("id")
        self.http.on("GET", PILOT_HUB + "/editions", body)
        self.http.on("POST", PILOT_HUB + "/feedback", FakeResponse(201, {"id": 79}))
        at = self.app(pin=PIN, grading=True)
        at.selectbox(key="gitem_ed_pilot_12").set_value("rank-12-2")
        at.button(key="gsubmit_ed_pilot_12").click().run()
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/feedback")[0].body,
                         {"edition_id": 12, "item_rank": 2, "event_id": 9002, "verdict": "digest", "scope": "item",
                          "note": ""})

    def test_rule_scope_needs_a_ruling(self):
        at = self.app(pin=PIN, grading=True)
        key = "ed_pilot_12"
        at.radio(key=f"gscope_{key}").set_value("Rule")
        at.button(key=f"gsubmit_{key}").click().run()
        self.assertEqual(self.http.posts(), [])
        self.assertTrue(any("write your ruling" in t for t in self.texts(at, "info")))

    def test_grading_is_locked_without_the_pin(self):
        at = self.app(grading=True)
        key = "ed_pilot_12"
        at.button(key=f"gsubmit_{key}").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertTrue(any("Owner actions are locked" in t for t in self.texts(at, "warning")))

    def test_grading_with_a_wrong_pin(self):
        at = self.app(grading=True, pin="0000")
        at.button(key="gsubmit_ed_pilot_12").click().run()
        self.assertEqual(self.http.posts(), [])
        self.assertIn(wrong_pin("pilot"), self.texts(at, "error"))

    def test_a_pin_unlocks_only_its_own_workspace(self):
        beta_editions = fx.editions(1, start_id=3)
        self.http.on("GET", BETA_HUB + "/editions", beta_editions)
        at = self.app(two_workspaces(), pin=PIN, grading=True, state={"workspace": "beta"})
        at.button(key="gsubmit_ed_beta_3").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertIn(wrong_pin("beta"), self.texts(at, "error"))
        self.assertEqual(beta_secrets()["id"], "beta")


if __name__ == "__main__":
    unittest.main()
