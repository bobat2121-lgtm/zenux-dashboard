"""Unit tests: the Filtered out tab's pure helpers (filtered_view): the order of a view, plain source names, ratings,
counts, the story a row repeats and the briefing that later ran it, the Why mapping and the escaping of a row card."""

from __future__ import annotations

import unittest

import fixtures_filtered as ff
from fixtures import iso
from helpers import one_workspace
import helpers  # noqa: F401  (puts dashboard/ on sys.path)

from zenux_dashboard import filtered_view as fv
from zenux_dashboard import labels
from zenux_dashboard.config import parse_config

WS = parse_config(one_workspace()).workspace("pilot")


def ids(rows) -> list[int]:
    return [r["event_id"] for r in rows]


class ViewRowsTests(unittest.TestCase):
    def test_near_misses_best_score_first_unknown_last(self):
        self.assertEqual(ids(fv.view_rows("near", ff.near_rows())), [7202, 7201, 7205, 7204])

    def test_near_misses_equal_scores_newest_first(self):
        rows = [ff.row(1, score=60, hours=9), ff.row(2, score=60, hours=1), ff.row(3, score=60, hours=5)]
        self.assertEqual(ids(fv.view_rows("near", rows)), [2, 3, 1])

    def test_other_views_keep_the_hubs_order(self):
        self.assertEqual(ids(fv.view_rows("all", ff.all_rows())), ids(ff.all_rows()))
        self.assertEqual(ids(fv.view_rows("same", ff.same_rows())), [7302, 7306])
        self.assertEqual(ids(fv.view_rows("old", ff.old_rows())), [7304, 7310])
        self.assertEqual(ids(fv.view_rows("muted", ff.muted_rows())), [7305, 7401, 7402])

    def test_one_row_per_story_and_no_row_without_an_id(self):
        rows = [ff.row(5, hours=1), ff.row(5, hours=9, title="older decision"), {"title": "no id"}]
        out = fv.view_rows("all", rows)
        self.assertEqual(ids(out), [5])
        self.assertEqual(out[0]["title"], "A story")

    def test_area_options_configured_and_present(self):
        self.assertEqual(fv.area_options(WS, ff.all_rows(), ""), ["ai-infra", "defense-unmanned"])
        self.assertEqual(fv.area_options(WS, [ff.row(1, module="space-launch")], "")[-1], "space-launch")
        self.assertEqual([labels.area_name(a) for a in fv.area_options(WS, [], "")],
                         ["AI infrastructure", "Defense unmanned"])

    def test_view_labels_carry_the_true_counts(self):
        counts = {"near_miss": 12, "all_with_auto": 80, "same_story": 4, "muted": 0, "old_news": 3}
        self.assertEqual([fv.view_label(v, counts) for v, _ in fv.VIEWS],
                         ["Near misses · 12", "All · 80", "Same story · 4", "Muted · 0", "Old news · 3"])
        self.assertEqual(fv.view_label("near", {}), "Near misses")  # an older hub sends no counts


class FieldTests(unittest.TestCase):
    def test_rows_of_tolerates_shapes(self):
        self.assertEqual(len(fv.rows_of(ff.rejected_body(ff.all_rows()))), len(ff.all_rows()))
        self.assertEqual(fv.rows_of({"decisions": [{"event_id": 1}, 7]}), [{"event_id": 1}])
        self.assertEqual(fv.rows_of([{"event_id": 2}]), [{"event_id": 2}])
        self.assertEqual(fv.rows_of(None), [])

    def test_source_label_never_the_key(self):
        self.assertEqual(fv.source_label(ff.row(1)), "Data Center Dynamics")
        key_only = ff.row(2, source_key="breaking-defense", source_label="breaking-defense",
                          url="https://www.breakingdefense.com/a")
        self.assertEqual(fv.source_label(key_only), "breakingdefense.com")
        self.assertEqual(fv.source_label(ff.row(3, source_label=None, url="javascript:alert(1)")), "")

    def test_newest_rating_skips_the_should_have_been_in_note(self):
        self.assertEqual(fv.newest_rating(ff.near_rows()[3]), "lead")
        self.assertIsNone(fv.newest_rating(ff.row(1)))
        wrong = ff.row(2, feedback=[{"verdict": "factual_error", "created_at": iso(1)}])
        self.assertIsNone(fv.newest_rating(wrong))

    def test_requested_only_for_a_promotion(self):
        self.assertEqual(fv.requested_of(ff.near_rows()[3])["note"], "Big customer")
        self.assertIsNone(fv.requested_of(ff.row(1, requested={"reason": "unmute", "note": None})))
        self.assertIsNone(fv.requested_of(ff.row(1)))

    def test_auto_rationale_is_the_hubs_plain_sentence(self):
        row = ff.all_rows()[0]
        self.assertEqual(fv.auto_rationale(row), ff.STALE_PLAIN)
        # an older hub without rationale_plain: the rule's name is still dropped
        older = {**row, "rationale_plain": None}
        self.assertEqual(fv.auto_rationale(older), "Published 2026-08-01, 63 days before 2026-10-03; older than the "
                                                   "21-day freshness line.")
        self.assertEqual(labels.find_jargon(fv.auto_rationale(row)), [])

    def test_calibrated_ids(self):
        self.assertEqual(fv.calibrated_ids("Fine; calibrated: owner grade #41. And calibrated: owner grade #7"),
                         [41, 7])
        self.assertEqual(fv.calibrated_ids(None), [])

    def test_last_days(self):
        self.assertEqual((fv.last_days(1), fv.last_days(3)), ("last day", "last 3 days"))
        self.assertEqual((fv.days_label(1), fv.days_label(30)), ("Last day", "Last 30 days"))


class CountTests(unittest.TestCase):
    def test_count_lines_from_the_true_total(self):
        self.assertEqual(fv.count_line(shown=4, total=4, days=3, loaded=4), "Showing 4 of 4 stories · last 3 days")
        self.assertEqual(fv.count_line(shown=1, total=1, days=1, loaded=1), "Showing 1 of 1 story · last day")
        self.assertEqual(fv.count_line(shown=50, total=1200, days=30, loaded=500),
                         "Showing 50 of 1200 stories · last 30 days")
        self.assertEqual(fv.count_line(shown=50, total=1200, days=30, loaded=500, near=True),
                         "Showing 50 of 1200 stories · last 30 days · best first among the newest 500")
        self.assertEqual(fv.count_line(shown=1, total=1, days=3, loaded=1, query="coreweave"),
                         "1 story matches “coreweave” · last 3 days")
        self.assertEqual(fv.count_line(shown=50, total=70, days=3, loaded=70, query="grid"),
                         "70 stories match “grid” · showing 50 · last 3 days")
        for text in (fv.count_line(shown=50, total=1200, days=30, loaded=500, near=True),
                     fv.count_line(shown=1, total=1, days=3, loaded=1, query="x")):
            self.assertEqual(labels.find_jargon(text), [])


class SameStoryAndLaterTests(unittest.TestCase):
    def test_same_line_names_the_story_and_its_briefing(self):
        row = ff.all_rows()[3]
        name = row["canonical"]["briefing"]["briefing_label"]
        self.assertEqual(fv.same_html(row), '<div class="rejected-rationale">Same story as: <strong>Neocloud signs 200 '
                                            f'MW capacity deal with hyperscaler</strong> · in your {name}</div>')
        self.assertIn("<strong>Army award reported last week</strong></div>", fv.same_html(ff.all_rows()[4]))
        self.assertEqual(fv.same_html(ff.row(1)), "")  # the hub named no story
        hostile = ff.row(2, canonical={"title": "A <b>deal</b>", "briefing": None})
        self.assertIn("Same story as: <strong>A &lt;b&gt;deal&lt;/b&gt;</strong>", fv.same_html(hostile))

    def test_briefing_of_needs_an_edition(self):
        self.assertIsNone(fv.briefing_of({"item_id": 3}))
        self.assertIsNone(fv.briefing_of(None))
        self.assertEqual(fv.briefing_of({"edition_id": 12, "item_id": 3})["item_id"], 3)
        self.assertIsNone(fv.later_of(ff.row(1)))
        self.assertEqual(fv.later_of(ff.row(1, published_later={"edition_id": 13}))["edition_id"], 13)


class WhyTests(unittest.TestCase):
    def test_why_of_an_editor_rejection(self):
        why = fv.why_of(ff.near_rows()[0])
        self.assertEqual(why["reason"], "Near miss")
        self.assertEqual(why["score"], 64)
        self.assertEqual([r["id"] for r in why["rules"]], ["R-0012"])  # rules_detail, with their words
        self.assertIn("megawatt", why["rules"][0]["plain_text"])
        self.assertEqual(why["calibrated_by"], [41])
        self.assertIn("calibrated by your feedback", why["rationale_plain"])
        self.assertEqual([s["name"] for s in why["subjects"]], ["CoreWeave"])
        self.assertIsNone(why["promoted"])
        self.assertEqual(why["source"], {"module": "ai-infra", "label": "Data Center Dynamics",
                                         "lane_label": "Trade press"})

    def test_bare_rule_ids_from_an_older_hub(self):
        self.assertEqual(fv.why_of(ff.row(1, rules=["R-0007"]))["rules"], ["R-0007"])

    def test_why_of_a_promoted_row(self):
        promoted = fv.why_of(ff.near_rows()[3])["promoted"]
        self.assertEqual(promoted["note"], "Big customer")
        self.assertTrue(promoted["requested_at"])

    def test_automatic_rows_have_no_editor_reasoning(self):
        stale, mute = ff.all_rows()[0], ff.all_rows()[1]
        self.assertIsNone(fv.why_of(stale)["rationale"])
        self.assertIsNone(fv.why_of(stale)["rationale_plain"])
        self.assertEqual(fv.extra_of(stale), [("Filtered automatically", ff.STALE_PLAIN)])
        self.assertEqual(fv.extra_of(mute), [("Muted by you", ff.SOURCE_MUTE_LABEL)])
        self.assertEqual(fv.extra_of(ff.muted_rows()[2]), [("Muted by you", "“Old story” (unmuted since)")])
        self.assertEqual(fv.extra_of(ff.row(1)), [])

    def test_stars_from_starred_subjects(self):
        self.assertEqual(fv.why_of(ff.near_rows()[1])["stars"], [{"entity_id": "anduril", "name": "Anduril"}])


class RowHtmlTests(unittest.TestCase):
    def test_row_card_is_escaped_linked_and_plain(self):
        html = fv.row_html(ff.all_rows()[-1], "all", "America/New_York")
        self.assertIn("Drone &lt;script&gt;alert(1)&lt;/script&gt; unveiled at trade show", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("\n\n", html)
        self.assertIn('<span class="rejected-chip">Outside your coverage</span>', html)
        self.assertIn(">DEFENSE UNMANNED</span>", html)
        self.assertNotIn("uas-vision", html)
        self.assertNotIn("7303", html)

    def test_score_chip_in_every_view(self):
        row = ff.near_rows()[0]
        for view in ("near", "all"):  # a score order sorts by it, so every view shows it
            self.assertIn('<span class="rejected-chip score">Score 64 of 100 · bar 70</span>',
                          fv.row_html(row, view, "UTC"))
        self.assertNotIn("Score", fv.row_html({**row, "score": None}, "all", "UTC"))  # old news, mutes: no score
        # WF3 review CV9: the chip never names a band (a 74 is "Also notable" elsewhere)
        high = {**row, "score": 74, "bar": None}
        self.assertIn('<span class="rejected-chip score">Score 74 of 100</span>', fv.row_html(high, "near", "UTC"))
        self.assertNotIn("Near miss · score", fv.row_html(high, "near", "UTC"))

    def test_same_view_leaves_the_reason_to_the_same_story_line(self):
        named = {"event_id": 9, "title": "Copy", "reason_code": "duplicate", "decision": "duplicate",
                 "canonical": {"title": "The original", "briefing": None}}
        self.assertNotIn("Same story as another", fv.chips_html(named, "same"))
        self.assertIn("Same story as another", fv.chips_html(named, "all"))
        unnamed = {**named, "canonical": None}  # no story named: the reason stays
        self.assertIn("Same story as another", fv.chips_html(unnamed, "same"))

    def test_later_chip_replaces_the_requested_chip(self):
        row = ff.near_rows()[3]
        self.assertIn("You asked for this", fv.chips_html(row, "near"))
        later = fv.chips_html(row, "near", later=True)
        self.assertIn(">Later in your briefing<", later)
        self.assertNotIn("You asked for this", later)

    def test_muted_chip_in_the_muted_view(self):
        muted = fv.row_html(ff.muted_rows()[0], "muted", "UTC")
        self.assertIn('<span class="zx-chip chip-state chip-muted">Muted</span>', muted)
        self.assertNotIn("Muted by you", muted)
        self.assertIn('<span class="rejected-chip">Muted by you</span>', fv.row_html(ff.muted_rows()[0], "all", "UTC"))

    def test_mute_line(self):
        html = fv.mute_html(ff.mutes()["mutes"][0], "America/New_York")
        self.assertIn("News search: AI data center themes", html)
        self.assertIn("hid 12 this week (30 in all)", html)
        self.assertIn("Too noisy", html)
        removed = fv.mute_html(ff.mutes()["mutes"][2], "America/New_York", removed=True)
        self.assertIn("removed ", removed)
        self.assertNotIn("hid ", removed)


if __name__ == "__main__":
    unittest.main()
