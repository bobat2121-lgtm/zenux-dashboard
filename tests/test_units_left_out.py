"""Unit tests: the shared left-out row's pure helpers (left_out, docs/SPEC-SIMPLIFY.md 2.2): fields, plain source names,
ratings and requests, the groups of a briefing's left-out list, the story a row repeats and the briefing that later ran
it, the Why mapping (with the bar), the one chip and the escaping of a row, and the section's label and caption."""

from __future__ import annotations

import unittest

import fixtures_leftout as fl
from fixtures import iso
from helpers import one_workspace
import helpers  # noqa: F401  (puts dashboard/ on sys.path)

from zenux_dashboard import actions, labels
from zenux_dashboard import left_out as lo
from zenux_dashboard.config import parse_config

WS = parse_config(one_workspace()).workspace("pilot")
TZ = "America/New_York"


def ids(rows) -> list[int]:
    return [r["event_id"] for r in rows]


class FieldTests(unittest.TestCase):
    def test_rows_of_tolerates_shapes(self):
        self.assertEqual(len(lo.rows_of(fl.rejected_body(fl.all_rows()))), len(fl.all_rows()))
        self.assertEqual(lo.rows_of({"decisions": [{"event_id": 1}, 7]}), [{"event_id": 1}])
        self.assertEqual(lo.rows_of([{"event_id": 2}]), [{"event_id": 2}])
        self.assertEqual(lo.rows_of(None), [])

    def test_one_row_per_story_and_no_row_without_an_id(self):
        rows = [fl.row(5, hours=1), fl.row(5, hours=9, title="older decision"), {"title": "no id"}, "junk"]
        out = lo.unique_rows(rows)
        self.assertEqual(ids(out), [5])
        self.assertEqual(out[0]["title"], "A story")

    def test_source_label_never_the_key(self):
        self.assertEqual(lo.source_label(fl.row(1)), "Data Center Dynamics")
        key_only = fl.row(2, source_key="breaking-defense", source_label="breaking-defense",
                          url="https://www.breakingdefense.com/a")
        self.assertEqual(lo.source_label(key_only), "breakingdefense.com")
        self.assertEqual(lo.source_label(fl.row(3, source_label=None, url="javascript:alert(1)")), "")

    def test_newest_rating_and_open_request(self):
        # the star glows for the newest rating (not the "Should have been in" grade); the arrow for an open request
        self.assertEqual(actions.target_from_row(WS, fl.near_rows()[3]).rating, "lead")
        self.assertIsNone(actions.target_from_row(WS, fl.row(1)).rating)
        self.assertEqual(lo.requested_of(fl.near_rows()[3])["note"], "Big customer")
        self.assertIsNone(lo.requested_of(fl.row(1, requested={"reason": "unmute", "note": None})))
        cancelled = fl.row(1, requested={"reason": "promote", "note": "x", "cancelled_at": iso(1)})
        self.assertIsNone(lo.requested_of(cancelled))
        self.assertFalse(actions.target_from_row(WS, cancelled).requested)
        self.assertTrue(actions.target_from_row(WS, fl.near_rows()[3]).requested)

    def test_auto_rationale_is_the_hubs_plain_sentence(self):
        row = fl.all_rows()[0]
        self.assertEqual(lo.auto_rationale(row), fl.STALE_PLAIN)
        older = {**row, "rationale_plain": None}  # an older hub: the rule's name is still dropped
        self.assertEqual(lo.auto_rationale(older), "Published 2026-08-01, 63 days before 2026-10-03; older than the "
                                                   "21-day freshness line.")
        self.assertEqual(labels.find_jargon(lo.auto_rationale(row)), [])
        self.assertEqual(lo.calibrated_ids("Fine; calibrated: owner grade #41. And calibrated: owner grade #7"), [41, 7])
        self.assertEqual(lo.calibrated_ids(None), [])


class GroupTests(unittest.TestCase):
    def test_the_hubs_group_decides(self):
        groups = lo.grouped(fl.edition_rows())
        self.assertEqual(list(groups), ["near_miss", "below_bar", "same_story"])
        self.assertEqual([len(groups[g]) for g in groups], [4, fl.BELOW_BAR_ROWS, 2])
        # best score first in each group, unknown scores last
        self.assertEqual(ids(groups["near_miss"]), [7202, 7201, 7205, 7204])
        self.assertEqual(ids(groups["below_bar"])[0], 7500)
        self.assertEqual(ids(groups["below_bar"])[-1], 7301)
        self.assertEqual(ids(groups["same_story"]), [7302, 7306])

    def test_a_row_without_a_group_is_placed_by_the_same_rule(self):
        self.assertEqual(lo.group_of(fl.row(1, decision="duplicate")), "same_story")
        self.assertEqual(lo.group_of(fl.row(2, decision="already_covered", score=None)), "same_story")
        self.assertEqual(lo.group_of(fl.row(3, score=61, bar=70)), "near_miss")  # within 10 of the bar
        self.assertEqual(lo.group_of(fl.row(4, score=75, bar=80, reason_code="edition_limit")), "near_miss")
        self.assertEqual(lo.group_of(fl.row(5, score=59, bar=70)), "below_bar")
        self.assertEqual(lo.group_of(fl.row(6, score=None, bar=70)), "below_bar")
        self.assertEqual(lo.group_of(fl.row(7, score=20, near_miss=True)), "near_miss")  # the hub's flag
        self.assertEqual(lo.group_of(fl.row(8, score=90, group="below_bar")), "below_bar")  # the hub's group wins
        self.assertEqual(lo.group_of(fl.row(9, group="something_new", score=10)), "below_bar")

    def test_by_score(self):
        rows = [fl.row(1, score=None, hours=1), fl.row(2, score=41, hours=1), fl.row(3, score=66, hours=9),
                fl.row(4, score=66, hours=2)]
        self.assertEqual(ids(lo.by_score(rows)), [4, 3, 2, 1])  # equal scores: the newest story first


class SameStoryAndLaterTests(unittest.TestCase):
    def test_same_line_names_the_story_and_its_briefing(self):
        row = fl.all_rows()[3]
        name = row["canonical"]["briefing"]["briefing_label"]
        self.assertEqual(lo.same_html(row), '<div class="rejected-rationale">Same story as: <strong>Neocloud signs 200 '
                                            f'MW capacity deal with hyperscaler</strong> · in your {name}</div>')
        self.assertIn("<strong>Army award reported last week</strong></div>", lo.same_html(fl.all_rows()[4]))
        self.assertEqual(lo.same_html(fl.row(1)), "")  # the hub named no story
        hostile = fl.row(2, canonical={"title": "A <b>deal</b>", "briefing": None})
        self.assertIn("Same story as: <strong>A &lt;b&gt;deal&lt;/b&gt;</strong>", lo.same_html(hostile))

    def test_same_line_names_a_story_the_old_tracker_ran(self):
        old = fl.old_tracker_row()
        self.assertEqual(lo.same_html(old), '<div class="rejected-rationale">Same story as: <strong>Red Cat ships Black '
                                            'Widow drones to the Army</strong> · From the old tracker · Sep 20, 2026 · '
                                            '9am digest</div>')
        self.assertEqual(lo.reason_chip(old), "")  # the line already names what it repeats
        self.assertIsNone(lo.briefing_of(lo.canonical_of(old)["briefing"]))  # nothing to show in a briefing
        # a label never stands in for a briefing's name
        both = fl.row(3, canonical={"title": "A deal", "label": "From the old tracker", "briefing": {"edition_id": 12}})
        self.assertIn("</strong> · in your briefing</div>", lo.same_html(both))

    def test_briefing_of_needs_an_edition(self):
        self.assertIsNone(lo.briefing_of({"item_id": 3}))
        self.assertIsNone(lo.briefing_of(None))
        self.assertEqual(lo.briefing_of({"edition_id": 12, "item_id": 3})["item_id"], 3)
        self.assertIsNone(lo.later_of(fl.row(1)))
        self.assertEqual(lo.later_of(fl.row(1, published_later={"edition_id": 13}))["edition_id"], 13)


class WhyTests(unittest.TestCase):
    def test_why_of_an_editor_rejection_carries_the_score_and_the_bar(self):
        why = lo.why_of(fl.near_rows()[0])
        self.assertEqual((why["reason"], why["score"], why["bar"]), ("Near miss", 64, 70))
        self.assertEqual([r["id"] for r in why["rules"]], ["R-0012"])  # rules_detail, with their words
        self.assertIn("megawatt", why["rules"][0]["plain_text"])
        self.assertEqual(why["calibrated_by"], [41])
        self.assertEqual([s["name"] for s in why["subjects"]], ["CoreWeave"])
        self.assertIsNone(why["promoted"])
        self.assertEqual(why["source"], {"module": "ai-infra", "label": "Data Center Dynamics",
                                         "lane_label": "Trade press"})
        # the score and the bar move into Why (docs/SPEC-SIMPLIFY.md 2.2)
        target = actions.target_from_row(WS, fl.near_rows()[0])
        first, _ = actions.why_rows(target, why, TZ)
        self.assertEqual(first[0], ("Why it was left out", "Near miss · score 64 of 100 · bar 70"))
        unscored = actions.why_rows(target, lo.why_of(fl.near_rows()[2]), TZ)[0]
        self.assertEqual(unscored[0], ("Why it was left out", "Below your \"how much\" setting"))

    def test_bare_rule_ids_and_promoted_rows(self):
        self.assertEqual(lo.why_of(fl.row(1, rules=["R-0007"]))["rules"], ["R-0007"])
        promoted = lo.why_of(fl.near_rows()[3])["promoted"]
        self.assertEqual(promoted["note"], "Big customer")
        self.assertTrue(promoted["requested_at"])
        self.assertEqual(lo.why_of(fl.near_rows()[1])["stars"], [{"entity_id": "anduril", "name": "Anduril"}])

    def test_automatic_rows_have_no_editor_reasoning(self):
        stale, mute = fl.all_rows()[0], fl.all_rows()[1]
        self.assertIsNone(lo.why_of(stale)["rationale"])
        self.assertIsNone(lo.why_of(stale)["rationale_plain"])
        self.assertEqual(lo.extra_of(stale), [("Filtered automatically", fl.STALE_PLAIN)])
        self.assertEqual(lo.extra_of(mute), [("Muted by you", fl.SOURCE_MUTE_LABEL)])
        self.assertEqual(lo.extra_of(fl.muted_rows()[2]), [("Muted by you", "“Old story” (unmuted since)")])
        self.assertEqual(lo.extra_of(fl.row(1)), [])


class RowHtmlTests(unittest.TestCase):
    def test_row_is_escaped_linked_and_plain(self):
        row = fl.all_rows()[-1]
        html = lo.row_html(row, TZ)
        self.assertIn("Drone &lt;script&gt;alert(1)&lt;/script&gt; unveiled at trade show", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("\n\n", html)
        self.assertIn(">DEFENSE TECH</span>", html)
        self.assertNotIn("uas-vision", html)
        self.assertNotIn("7303", html)

    def test_one_reason_chip_and_no_score_chip(self):
        row = fl.near_rows()[0]
        self.assertEqual(lo.tags_html(row), '<div class="rejected-signals"><span class="rejected-chip">Near miss</span>'
                                            '</div>')
        for any_row in fl.near_rows() + fl.all_rows():
            tags = lo.tags_html(any_row)
            self.assertNotIn("Score", tags)
            self.assertLessEqual(tags.count("<span"), 1)
        self.assertIn('<span class="rejected-chip">Outside your coverage</span>', lo.tags_html(fl.all_rows()[-1]))
        # a repeat whose line names the story it repeats needs no chip; one the hub cannot name keeps its reason
        self.assertEqual(lo.reason_chip(fl.all_rows()[3]), "")
        self.assertIn("Same story as another", lo.reason_chip({**fl.all_rows()[3], "canonical": None}))
        # a later briefing published it: that is the chip
        later = fl.row(1, published_later={"edition_id": 13, "item_id": 1301})
        self.assertEqual(lo.reason_chip(later),
                         '<span class="zx-chip chip-state chip-corrected">Later in your briefing</span>')


class SectionTests(unittest.TestCase):
    def test_label_count_and_caption(self):
        self.assertEqual(lo.section_label(fl.left_out()), "Left out of this briefing · 19")
        self.assertEqual(lo.section_label({"near_miss": 1}), "Left out of this briefing")
        self.assertEqual(lo.automatic_text(fl.left_out()), "Kept out before the editor read them: 4 muted, 12 old news.")
        self.assertEqual(lo.automatic_text(fl.left_out(muted=0, old=3)),
                         "Kept out before the editor read them: 0 muted, 3 old news.")
        self.assertEqual(lo.automatic_text(fl.left_out(muted=0, old=0)), "")
        self.assertEqual(lo.automatic_text(None), "")
        self.assertEqual(lo.group_title("same_story", 2), "Same story as one in your briefings · 2")
        for text in (lo.section_label(fl.left_out()), lo.automatic_text(fl.left_out())) + tuple(
                name for _, name in lo.GROUPS):
            self.assertEqual(labels.find_jargon(text), [])

    def test_when_the_section_is_drawn(self):
        self.assertTrue(lo.has_section(fl.left_out()))
        self.assertTrue(lo.has_section(fl.left_out(total=0, muted=2, old=0)))  # only the caption to say
        self.assertFalse(lo.has_section(fl.left_out(total=0, muted=0, old=0)))
        self.assertFalse(lo.has_section(None))  # an older hub: GET /rejected would ignore edition_id
        self.assertIsNone(lo.left_out_of({"id": 12}))
        self.assertEqual(lo.left_out_of({"left_out": fl.left_out()})["total"], 19)
        self.assertEqual(lo.automatic_counts({"kept_out_automatically": {"muted": "x", "old_news": -3}}), (0, 0))


if __name__ == "__main__":
    unittest.main()
