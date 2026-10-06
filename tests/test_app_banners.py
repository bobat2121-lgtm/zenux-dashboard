"""AppTest: the Briefing's banners (docs/SPEC-SIMPLIFY.md 2.2): at most two one-line banners, only when they apply.
"N suggestions need your OK" with Review (opens Tuning), and the weekly tune-up (GET /tuneup `due`): Start opens an
inline panel of compact rows with a one-click rating (POST /feedback; no dialog, score or note), "Skip this week"
(POST /tuneup/dismiss) and, when every row is rated, the thanks. Also the tuning receipt under a briefing's summary."""

from __future__ import annotations

import re
import unittest

import fixtures as fx
import fixtures_briefing as fb
import fixtures_leftout as fl
import fixtures_tuning as fp
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, READ, hub_defaults

from zenux_dashboard import labels, tuneup

EDITIONS = PILOT_HUB + "/editions"
TUNEUP = PILOT_HUB + "/tuneup"
FEEDBACK = PILOT_HUB + "/feedback"
BANNER = "Weekly tune-up: rate 5 stories so the editor learns your bar (about 2 minutes)."


class BannerCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        self.http.on("GET", EDITIONS, fb.editions())
        self.http.on("GET", PILOT_HUB + "/preferences", fb.preferences())  # no suggestions
        self.http.on("GET", PILOT_HUB + "/rules", {"precedents": [], "drafts": []})

    def banners(self, at) -> list[str]:
        return re.findall(r'<div class="zx-banner-text">(.*?)</div>', self.html(at))

    def tuneup_rows(self, at) -> list[str]:
        return [str(n.key)[len("zx_tu_"):] for n in self.walk(at._tree)
                if re.fullmatch(r"zx_tu_[ie]\d+", str(getattr(n, "key", None) or ""))]


class OkBannerTests(BannerCase):
    def test_no_banner_when_nothing_applies(self):
        at = self.app()
        self.assert_clean(at)
        self.assertEqual(self.banners(at), [])
        self.assertEqual(self.http.find("GET", TUNEUP)[-1].bearer, READ)

    def test_suggestions_need_your_ok_and_review_opens_tuning(self):
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences())
        self.http.on("GET", PILOT_HUB + "/rules", fp.rules())
        at = self.app()
        self.assert_clean(at)
        # what Needs your OK lists: six suggestions and two suggested company names (docs/SPEC-COMPANY-MAP.md 6.3)
        self.assertEqual(self.banners(at), ["8 suggestions need your OK"])
        self.assertEqual(at.button(key="br_ok_review").label, "Review")
        at.button(key="br_ok_review").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state["zx_tab"], "tuning")
        self.assertIn("Needs your OK · 8", self.html(at))
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(suggestions=[fp.grades_draft()], companies=[]))
        self.http.on("GET", PILOT_HUB + "/rules", {"drafts": []})
        self.fresh()
        at = self.app()
        self.assertEqual(self.banners(at), ["1 suggestion needs your OK"])
        self.assert_plain(at)
        # a suggested company name alone is counted too
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(suggestions=[], companies=[fp.company_remove()]))
        self.fresh()
        at = self.app()
        self.assertEqual(self.banners(at), ["1 suggestion needs your OK"])
        self.assert_plain(at)

    def test_a_failed_read_shows_no_banner(self):
        self.http.routes.pop(("GET", PILOT_HUB + "/preferences"))
        at = self.app()
        self.assert_clean(at)
        self.assertEqual(self.banners(at), [])


class TuneupTests(BannerCase):
    def setUp(self):
        super().setUp()
        self.http.on("GET", TUNEUP, fx.tuneup_due())
        self.http.on("POST", FEEDBACK, FakeResponse(201, fb.feedback_stored()))

    def start(self, *, pin: str | None = PIN):
        at = self.app(pin=pin)
        self.assert_clean(at)
        at.button(key="tu_start").click().run()
        self.assert_clean(at)
        return at

    def test_the_banner_while_due(self):
        at = self.app(pin=PIN)
        self.assert_clean(at)
        self.assertEqual(self.banners(at), [BANNER])
        self.assertEqual([at.button(key=k).label for k in ("tu_start", "tu_skip")], ["Start", "Skip this week"])
        self.assertEqual(self.tuneup_rows(at), [])  # the panel opens on Start
        self.assertEqual(self.http.posts(), [])
        self.assert_plain(at)

    def test_two_banners_at_most(self):
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences())
        self.http.on("GET", PILOT_HUB + "/rules", fp.rules())
        at = self.app()
        self.assertEqual(self.banners(at), ["8 suggestions need your OK", BANNER])
        html = self.html(at)
        self.assertLess(html.index("zx-status"), html.index("need your OK"))
        self.assertLess(html.index("Weekly tune-up"), html.index('<section class="feed-edition'))

    def test_start_opens_one_compact_row_per_story(self):
        at = self.start()
        self.assertEqual(self.tuneup_rows(at), ["i1201", "i1202", "e9103", "e9104", "e9105"])
        html = self.html(at)
        self.assertIn('<div class="tu-editor">In your briefing at 74</div>', html)
        self.assertIn('<div class="tu-editor">Left out at 66, bar 70 · Near miss</div>', html)
        self.assertIn('<div class="tu-editor">Left out at 65, bar 70 · Cut for space</div>', html)
        self.assertIn('href="https://example.com/tune-9103"', html)
        self.assertRegex(html, r'<div class="feed-dateline">[A-Z][a-z]{2} \d{1,2} · Data Center Dynamics · '
                               r'<span class="module-tag"[^>]*>AI INFRASTRUCTURE</span></div>')
        # one click per rating: no dialog, no score, no note
        self.assertEqual([at.button(key=f"tu_{v}_e9103").label for v in labels.RATING_CHOICES],
                         ["Top story", "In the briefing", "Near miss", "Not relevant"])
        self.assertEqual([s for s in at.get("slider")], [])
        self.assertEqual([t.key for t in at.text_input if str(t.key).startswith("dlg_")], [])
        self.assertIn("Weekly tune-up · 0 of 5 stories rated", self.banners(at))
        self.assert_plain(at)

    def test_a_click_rates_the_story_or_its_briefing_item(self):
        at = self.start()
        at.button(key="tu_watch_e9103").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", FEEDBACK)[-1]
        self.assertEqual((post.bearer, post.body), (OWNER, {"verdict": "watch", "scope": "item", "event_id": 9103}))
        self.assertIn("Rated: Near miss.", self.toasts(at))
        self.assertIsNone(at.session_state["zx_dialog"] if "zx_dialog" in at.session_state else None)
        self.assertIn('<div class="tu-done">Rated: Near miss.</div>', self.html(at))
        self.assertEqual([b.key for b in at.button if str(b.key).endswith("_e9103")], [])
        at.button(key="tu_lead_i1201").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", FEEDBACK)[-1].body, {"verdict": "lead", "scope": "item", "item_id": 1201})
        self.assertIn("Weekly tune-up · 2 of 5 stories rated", self.banners(at))
        # the rows stay put while the fresh tune-up read no longer lists the rated stories
        self.http.on("GET", TUNEUP, fx.tuneup(due=True, items=fx.tuneup_due()["items"][2:], rated=2))
        self.fresh()
        at.run()
        self.assertEqual(self.tuneup_rows(at), ["i1201", "i1202", "e9103", "e9104", "e9105"])

    def test_when_every_row_is_rated_it_says_thanks(self):
        at = self.start()
        for key, verdict in (("i1201", "lead"), ("i1202", "digest"), ("e9103", "watch"), ("e9104", "reject")):
            at.button(key=f"tu_{verdict}_{key}").click().run()
            self.assert_clean(at)
        self.http.on("GET", TUNEUP, fx.tuneup(due=False, items=[], rated=5))  # the hub: no longer due
        at.button(key="tu_digest_e9105").click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.http.find("POST", FEEDBACK)), 5)
        self.assertIn(tuneup.DONE, self.banners(at))
        self.assertEqual(self.tuneup_rows(at), [])
        self.assertEqual(at.button(key="tu_close").label, "Close")
        at.button(key="tu_close").click().run()
        self.assert_clean(at)
        self.assertEqual(self.banners(at), [])

    def test_skip_this_week(self):
        self.http.on("POST", TUNEUP + "/dismiss", {"dismissed": True, "week": "2026-W40"})
        at = self.app(pin=PIN)
        self.http.on("GET", TUNEUP, fx.tuneup(dismissed=True))  # what the hub answers after the skip
        at.button(key="tu_skip").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", TUNEUP + "/dismiss")[-1]
        self.assertEqual((post.bearer, post.body), (OWNER, {}))
        self.assertIn(tuneup.SKIPPED, self.toasts(at))
        self.assertEqual(self.banners(at), [])

    def test_locked_the_rating_is_disabled(self):
        at = self.start(pin=None)
        for key in ("tu_lead_e9103", "tu_skip"):
            self.assertTrue(at.button(key=key).disabled, key)
            self.assertEqual(at.button(key=key).help, labels.LOCKED_HELP)
        self.assertEqual(self.http.posts(), [])

    def test_not_due_an_older_hub_or_odd_items_show_nothing(self):
        for answer in (fx.tuneup(), FakeResponse(404, {"error": "not_found"}),
                       {"due": True, "items": [None, {"title": "no id"}]}, {"due": "yes", "items": "x"}):
            with self.subTest(answer=answer):
                self.fresh()
                self.http.on("GET", TUNEUP, answer)
                at = self.app(pin=PIN)
                self.assert_clean(at)
                self.assertEqual(self.banners(at), [])

    def test_fewer_stories_say_so(self):
        self.http.on("GET", TUNEUP, fx.tuneup_due(2))
        at = self.app()
        self.assertEqual(self.banners(at), ["Weekly tune-up: rate 2 stories so the editor learns your bar (about 2 "
                                            "minutes)."])


class ReceiptTests(BannerCase):
    def test_the_receipt_under_the_summary_only_with_counts(self):
        self.http.on("GET", EDITIONS, fl.editions_v11())
        at = self.app()
        self.assert_clean(at)
        latest, older = [str(m.value) for m in at.markdown if str(m.value).startswith('<section class="feed-edition')]
        self.assertIn('</div><div class="edition-receipt">Your tuning here: 2 stories brought in and 1 kept out by your '
                      'rules; the editor used 3 of your ratings.</div></div>', latest)
        self.assertNotIn("edition-receipt", older)  # an older briefing (an older hub's shape)
        self.http.on("GET", EDITIONS, fl.editions_v11(tuning=fl.tuning(brought_in=0, kept_out=0, rules_used=0,
                                                                         ratings_used=0)))
        self.fresh()
        at = self.app()
        self.assertNotIn("edition-receipt", self.html(at))
        self.assert_plain(at)


if __name__ == "__main__":
    unittest.main()
