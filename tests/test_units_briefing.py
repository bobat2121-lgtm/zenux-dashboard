"""Unit tests for the Briefing's pure helpers (feed_view) and the card actions' targets, Why rows and toasts
(actions). No Streamlit run: these take hub shapes and return values or HTML."""

from __future__ import annotations

import unittest

import fixtures_briefing as fb
import helpers  # noqa: F401  (puts dashboard/ on sys.path)
from zenux_dashboard import actions, feed_view, fmt, labels
from zenux_dashboard.config import Workspace

TZ = "America/New_York"
WS = Workspace(id="pilot", title="Pilot", hub_url="https://zenux-pilot-hub.test.invalid")


def item(rank, module, headline="Story"):
    return {"rank": rank, "module": module, "headline": headline}


class ShapeTests(unittest.TestCase):
    def test_editions_and_paging(self):
        body = fb.editions(1)
        self.assertEqual(len(feed_view.editions_of(body)), 1)
        self.assertEqual(feed_view.editions_of([{"id": 1}]), [{"id": 1}])
        self.assertEqual(feed_view.editions_of({"editions": "nope"}), [])
        self.assertIsNone(feed_view.next_cursor(body, feed_view.editions_of(body)))
        self.assertEqual(feed_view.next_cursor({"next_before": 7}, []), 7)
        self.assertEqual(feed_view.next_cursor({"next_before": "7"}, []), 7)
        full = [{"id": n} for n in range(20, 15, -1)]
        self.assertEqual(feed_view.next_cursor({"editions": full}, full), 16)  # a full page without next_before
        self.assertIsNone(feed_view.next_cursor({"has_more": False}, full))
        self.assertEqual(feed_view.PAGE_SIZE, 5)

    def test_items_sorted_by_rank_and_all_items_after_search(self):
        edition = {"items": [item(2, "ai-infra"), item(None, "ai-infra"), item(1, "ai-infra"), "junk"]}
        self.assertEqual([i["rank"] for i in feed_view.items_of(edition)], [1, 2, None])
        hits = feed_view.search(fb.editions(2)["editions"], "anduril")
        self.assertEqual([len(e["items"]) for e in hits], [1, 1])
        self.assertEqual([len(feed_view.all_items(e)) for e in hits], [2, 2])  # the header still counts every story
        self.assertEqual(feed_view.search(fb.editions(2)["editions"], "  "), fb.editions(2)["editions"])

    def test_search_covers_headlines_text_companies_sources_and_areas(self):
        story = fb.items(12)[0]
        hay = feed_view.item_haystack(story)
        for word in ("coreweave signs", "critical it capacity", "microsoft", "coreweave newsroom", "company news",
                     "ai infrastructure", "your coverage", "example.com"):
            self.assertIn(word, hay)
        corrected = dict(story, correction={"state": "corrected", "headline": "Nebius fixes", "text": "New words"})
        self.assertIn("nebius fixes", feed_view.item_haystack(corrected))

    def test_coverage_areas_and_tags(self):
        self.assertEqual(feed_view.item_modules({"module": "ai-infra"}), ["ai-infra"])
        self.assertEqual(feed_view.item_modules({"module": "ai-infra", "modules": []}), ["ai-infra"])
        self.assertEqual(feed_view.item_modules({"module": "ai-infra", "modules": ["defense-unmanned", "ai-infra",
                                                                                   "defense-unmanned", None]}),
                         ["defense-unmanned", "ai-infra"])
        self.assertEqual(feed_view.item_modules({}), [])
        self.assertEqual(feed_view.module_tags_html({"modules": ["ai-infra", "<x>"]}),
                         f'<span class="module-tag" style="{fmt.tag_style("#A78BFA")}">AI INFRASTRUCTURE</span>'
                         f'<span class="module-tag" style="{fmt.tag_style(fmt.module_color("<x>"))}">&lt;X&gt;</span>')
        self.assertEqual(feed_view.module_tag("defense-unmanned").rsplit(">", 2)[-2], "DEFENSE UNMANNED</span")

    def test_fallback_summary_says_stories(self):
        items = [item(1, "defense-unmanned", "Army orders a new autonomy command.")] + [
            item(n, "ai-infra" if n <= 5 else "defense-unmanned") for n in range(2, 10)]
        self.assertEqual(feed_view.fallback_summary(items),
                         "9 stories across AI infrastructure (4) and defense unmanned (5), led by Army orders a new "
                         "autonomy command.")
        self.assertEqual(feed_view.fallback_summary([item(1, "ai-infra", "Lead"), item(2, "ai-infra")]),
                         "2 stories in AI infrastructure, led by Lead.")
        self.assertEqual(feed_view.fallback_summary([item(1, "ai-infra", "Only one!")]),
                         "1 story in AI infrastructure: Only one!")
        self.assertEqual(feed_view.fallback_summary([{"rank": 1}]), "1 story.")
        self.assertEqual(feed_view.fallback_summary([]), "An empty briefing: nothing new cleared your bar.")
        self.assertEqual(feed_view.summary_of({"summary": "  One sentence.  "}, items), "One sentence.")
        self.assertEqual(feed_view.note_of({"note": "  Rank 2 is paywalled.\n"}), "Rank 2 is paywalled.")
        self.assertEqual(feed_view.note_of({"note": "   "}), "")

    def test_metric_and_score(self):
        self.assertIn("<b>200 MW</b>", feed_view.metric_html({"label": "Critical IT", "value": "200", "unit": "MW"}))
        self.assertEqual(feed_view.metric_html({}), "")
        self.assertEqual(feed_view.score_of({"score": 91}), 91)
        self.assertEqual(feed_view.score_of({"score": None, "why": {"score": 72}}), 72)
        self.assertIsNone(feed_view.score_of({}))

    def test_newest_rating(self):
        # what makes the star glow (Target.rating): the newest plain rating, never "Should have been in"'s grade
        rows = [{"id": 1, "verdict": "watch", "created_at": "2026-10-03T10:00:00Z"},
                {"id": 2, "verdict": "lead", "created_at": "2026-10-03T11:00:00Z"},
                {"id": 3, "verdict": "factual_error", "created_at": "2026-10-03T12:00:00Z"},
                {"id": 4, "verdict": "digest", "note": "Should have been in: x", "created_at": "2026-10-03T13:00:00Z"}]
        self.assertEqual(actions.newest_rating(rows), "lead")
        self.assertIsNone(actions.newest_rating([]))
        self.assertIsNone(actions.newest_rating("nope"))
        self.assertEqual(actions.newest_rating(rows + [{"id": 5, "verdict": "reject", "scope": "rule",
                                                        "created_at": "2026-10-03T14:00:00Z"}]), "lead")
        self.assertEqual(actions.newest_rating([dict(rows[1], withdrawn_at="2026-10-04T10:00:00Z"), rows[0]]), "watch")


class CardHtmlTests(unittest.TestCase):
    def setUp(self):
        self.edition = fb.edition()
        self.first, self.second = self.edition["items"]

    def test_dateline(self):
        self.assertEqual(feed_view.dateline_html(self.first, self.edition, TZ),
                         '<div class="feed-dateline">Oct 2 · CoreWeave newsroom</div>')
        # the label is the source key and the story has no date: the first http source's name, the briefing's date
        self.assertEqual(feed_view.dateline_html(self.second, self.edition, TZ),
                         '<div class="feed-dateline">Oct 3 · war.gov</div>')
        bare = {"why": {"source": {"label": "dcd-news", "source_key": "dcd-news"}}, "event": {"url": "nope"}}
        self.assertEqual(feed_view.dateline_html(bare, {}, TZ), "")

    def test_top_story_tier_and_states(self):
        # the tags sit in the row under the headline (item_tags_html), beside the icons, not in the card's HTML
        first = feed_view.item_tags_html(self.first)
        second = feed_view.item_tags_html(self.second)
        self.assertNotIn("feed-tags", feed_view.item_html(self.first, self.edition, TZ))
        self.assertTrue(feed_view.item_html(self.second, self.edition, TZ, focus=True).startswith(
            '<article class="feed-item zx-focus">'))
        self.assertIn('<span class="badge-top">TOP STORY</span>', first)
        self.assertNotIn("badge-top", second)
        # the tier in plain grey words, no pill
        self.assertIn('<span class="feed-tier">Your coverage</span>', first)
        self.assertIn('<span class="feed-tier">Industry and policy</span>', second)
        self.assertNotIn("zx-chip tier", first + second)
        self.assertNotIn("feed-tier", feed_view.item_tags_html(dict(self.first, tier=None)))
        self.assertNotIn("score", first.lower())
        exactly_90 = dict(self.second, score=90)
        self.assertIn("TOP STORY", feed_view.item_tags_html(exactly_90))
        self.assertNotIn("TOP STORY", feed_view.item_tags_html(dict(self.second, score=89)))
        self.assertNotIn("feed-nolink", first)
        self.assertIn("No source link captured", feed_view.item_tags_html(dict(self.first, sources=[])))
        # a rating has no chip: the glowing star says it (docs/SPEC-ICON-ACTIONS.md)
        self.assertNotIn("You rated it", first)
        self.assertIn("On your watchlist", first)

    def test_correction_chips_and_replacement(self):
        def chips(correction):
            return feed_view.state_chips(dict(self.second, correction=correction))

        self.assertEqual(chips({"state": "flagged"}),
                         '<span class="zx-chip chip-state chip-flagged">Flagged by you · being re-checked</span>')
        self.assertEqual(chips({"state": "upheld"}), '<span class="zx-chip chip-state chip-upheld">Checked: stands</span>')
        self.assertEqual(chips(None), "")
        corrected = dict(self.second, correction={"state": "corrected", "headline": "New <headline>",
                                                  "text": "New text.", "metrics": []})
        html = feed_view.item_html(corrected, self.edition, TZ)
        self.assertIn('<div class="feed-item-headline">New &lt;headline&gt;</div>', html)
        self.assertIn('<div class="feed-text">New text.</div>', html)
        self.assertNotIn("feed-metrics", html)  # none of the published metrics stands

    def test_head_and_hero(self):
        head = feed_view.head_html(self.edition, TZ, latest=True)
        self.assertIn(f'<span class="edition-label">{fb.LATEST_LABEL}</span>', head)
        self.assertIn("<span>7:41 AM ET</span>", head)
        self.assertIn('<div class="stat-l">TOP STORIES</div>', head)
        self.assertNotIn("Only the big ones", head)
        broad = dict(self.edition, selection={"volume": "broad"})
        self.assertIn('<span class="zx-chip tier">Everything notable</span>', feed_view.head_html(broad, TZ))
        unknown = feed_view.head_html({"items": []}, TZ)
        self.assertIn('<span class="edition-label">Briefing</span><span aria-hidden="true">·</span><span>0 stories</span>',
                      unknown)

    def test_corrections_and_shelf_rows(self):
        notes = feed_view.corrections_html(fb.with_corrections()["editions"][0], TZ)
        self.assertEqual(notes.count('<div class="correction-note">'), 2)
        self.assertEqual(feed_view.corrections_html({"corrections": [{"outcome": "open"}]}, TZ), "")
        self.assertIn("Checked: an earlier story stands.",
                      feed_view.corrections_html({"corrections": [{"outcome": "upheld", "text": "Fine."}]}, TZ))
        shelves = fb.with_shelves()["editions"][0]
        self.assertEqual(len(feed_view.shelf_rows(shelves, "watchlist")), 1)
        self.assertEqual(len(feed_view.shelf_rows(shelves, "near")), 2)
        self.assertEqual(feed_view.shelf_rows({"shelves": None}, "near"), [])
        self.assertEqual(feed_view.shelf_rows({"shelves": {"near_misses": None}}, "near"), [])
        # a shelf row is the shared left-out row; it carries the briefing's bar for its Why
        row = feed_view.shelf_row(shelves["shelves"]["near_misses"][0], shelves)
        self.assertEqual(row["bar"], 70)
        self.assertEqual(feed_view.shelf_row({"bar": 80}, shelves)["bar"], 80)
        self.assertNotIn("bar", feed_view.shelf_row({}, {}))


class ReceiptTests(unittest.TestCase):
    """The tuning receipt under a briefing's summary (docs/SPEC-SIMPLIFY.md 2.2, from the edition's `tuning`)."""

    def receipt(self, **tuning) -> str:
        return feed_view.receipt_text({"tuning": tuning})

    def test_the_specs_sentence(self):
        self.assertEqual(self.receipt(brought_in=2, kept_out=1, raised=0, lowered=0, rules_used=2, ratings_used=3),
                         "Your tuning here: 2 stories brought in and 1 kept out by your rules; the editor used 3 of your "
                         "ratings.")

    def test_only_counts_above_zero(self):
        self.assertEqual(self.receipt(brought_in=1), "Your tuning here: 1 story brought in by your rules.")
        self.assertEqual(self.receipt(kept_out=4, raised=2, lowered=1),
                         "Your tuning here: 4 stories kept out, 2 raised and 1 lowered by your rules.")
        self.assertEqual(self.receipt(ratings_used=1), "Your tuning here: the editor used 1 of your ratings.")
        self.assertEqual(self.receipt(rules_used=2), "Your tuning here: the editor applied 2 of your rules.")
        self.assertEqual(self.receipt(brought_in=0, kept_out=0, raised=0, lowered=0, rules_used=0, ratings_used=0), "")
        self.assertEqual(feed_view.receipt_text({}), "")  # an older hub
        self.assertEqual(self.receipt(brought_in="x", kept_out=-2), "")

    def test_plain_words(self):
        for text in (self.receipt(brought_in=2, kept_out=1, ratings_used=3), self.receipt(rules_used=4)):
            self.assertEqual(labels.find_jargon(text), [])
        head = feed_view.head_html({"items": [], "tuning": {"kept_out": 3}}, TZ)
        self.assertIn('<div class="edition-receipt">Your tuning here: 3 stories kept out by your rules.</div>', head)
        self.assertNotIn("edition-receipt", feed_view.head_html({"items": []}, TZ))


class TargetTests(unittest.TestCase):
    def test_target_from_item(self):
        edition = fb.edition()
        target = actions.target_from_item(WS, edition, edition["items"][0])
        self.assertEqual(target, actions.Target(
            workspace_id="pilot", title="CoreWeave signs 200 MW <capacity> deal with Microsoft", event_id=9001,
            item_id=1201, edition_id=12, story_id="s-100", module="ai-infra", source_key="ent-coreweave-1",
            source_label="CoreWeave newsroom",
            subjects=({"entity_id": "coreweave", "name": "CoreWeave", "muted": False, "starred": False},
                      {"entity_id": "microsoft", "name": "Microsoft", "muted": False, "starred": True}),
            url="https://example.com/coreweave", published=True, in_briefing=True, reason="Material news",
            item_rank=1, score=93, rating="lead"))
        second = actions.target_from_item(WS, edition, edition["items"][1])
        self.assertEqual((second.source_label, second.module, second.source_key, second.story_id, second.rating,
                          second.requested), ("war.gov", "defense-unmanned", "wargov-contracts", None, None, False))
        bare = actions.target_from_item(WS, {}, {"rank": "x"})
        self.assertEqual((bare.title, bare.event_id, bare.item_id, bare.subjects, bare.source_label),
                         ("This story", None, None, (), None))

    def test_target_from_row(self):
        row = fb.shelf_row(1301, "Nebius raises capital", 66)
        target = actions.target_from_row(WS, row)
        self.assertEqual((target.title, target.event_id, target.item_id, target.module, target.source_key,
                          target.source_label, target.published, target.in_briefing, target.reason),
                         ("Nebius raises capital", 1301, None, "ai-infra", "dcd-news", "Data Center Dynamics", False,
                          False, "Near miss"))
        self.assertEqual(target.score, 66)
        keyed = actions.target_from_row(WS, dict(row, source_label="dcd-news"))
        self.assertEqual(keyed.source_label, "example.com")  # never the source key
        self.assertEqual(actions.subjects_of([{"entity_id": "a", "name": "A"}, {"id": "a"}, {"name": "x"}, "junk"]),
                         ({"entity_id": "a", "name": "A", "muted": False, "starred": False},))

    def test_source_labels(self):
        self.assertEqual(actions.plain_source_label("Data Center Dynamics", "dcd"), "Data Center Dynamics")
        self.assertEqual(actions.plain_source_label("dcd", "dcd", "https://www.dcd.com/x"), "dcd.com")
        self.assertEqual(actions.plain_source_label("dcd", "dcd", "javascript:x"), "")
        self.assertEqual(actions.plain_source_label(None, None), "")
        self.assertEqual(actions.item_source_label({"why": {"source": {"label": "k", "source_key": "k"}},
                                                    "event": {"url": "https://news.google.com/x"}}), "Google News")
        self.assertEqual(actions.item_sources({"sources": [{"url": "javascript:x"}, "https://a.com/1",
                                                           {"href": "https://b.com", "publisher": "B"}]}),
                         [("https://a.com/1", "a.com"), ("https://b.com", "B")])
        self.assertEqual(actions.story_label("A" * 100)[-2:], "…”")
        self.assertEqual(actions.story_label(""), "this story")

    def test_preview_examples_never_show_a_source_key(self):
        """A hub without a catalog gives the source key as the example's source_label (seen on a live local hub)."""
        self.assertEqual(actions.example_source("Data Center Dynamics"), "Data Center Dynamics")
        self.assertEqual(actions.example_source("war.gov"), "war.gov")
        self.assertEqual(actions.example_source("zenux-test-feed"), "")
        self.assertEqual(actions.example_source("ent-coreweave-1"), "")
        self.assertEqual(actions.example_source("edgar_8k"), "")
        self.assertEqual(actions.example_source("Nebius", "Nebius"), "")
        html = actions.preview_examples_html([{"title": "A <b>", "published_at": "2026-10-02T15:00:00Z",
                                               "source_label": "dcd-news", "in_briefing": False}] * 7, TZ, "dcd-news")
        self.assertEqual(html.count('<div class="why-row">'), 6, "5 examples and '+2 more' (WF5 AW-14)")
        self.assertIn('<div class="why-row"><span class="why-label">+2 more</span></div>', html)
        self.assertIn("<span>A &lt;b&gt; · Oct 2</span>", html)
        self.assertNotIn("dcd-news", html)
        # The hub's count of what the examples leave out, and the story the menu was opened from.
        two = actions.preview_examples_html([{"title": "This one", "this_story": True, "in_briefing": True},
                                             {"title": "Other"}], TZ, more=4)
        self.assertIn('<span>This one</span><span class="zx-chip chip-state chip-starred">this story</span>'
                      '<span class="zx-chip chip-state chip-flagged">in your briefing</span>', two)
        self.assertIn("+4 more", two)
        self.assertNotIn("more", actions.preview_examples_html([{"title": "Only"}], TZ, more=0))

    def test_outlet_behind_a_news_search_story(self):
        # WF5 AW-1: a news-search source names its outlet; a source that is the outlet itself does not repeat it
        self.assertEqual(actions.outlet_of("Yahoo Finance", "www.finance.yahoo.com", "News search: data center deals"),
                         ("Yahoo Finance", "finance.yahoo.com"))
        self.assertEqual(actions.outlet_of("Data Center Dynamics", "datacenterdynamics.com", "Data Center Dynamics"), ("", ""))
        self.assertEqual(actions.outlet_of("Yahoo Finance", None, "News search: x"), ("", ""))
        self.assertEqual(actions.with_outlet("News search: x", "Yahoo Finance"), "Yahoo Finance via News search: x")
        self.assertEqual(actions.with_outlet("News search: x", ""), "News search: x")
        edition = fb.edition()
        item = dict(edition["items"][0])
        item["why"] = dict(item["why"], source=dict(item["why"]["source"], label="News search: AI deals",
                                                     publisher="Yahoo Finance", publisher_domain="finance.yahoo.com"),
                           my_preferences=[{"id": "I-0003", "direction": "less", "status": "active"}])
        target = actions.target_from_item(WS, edition, item)
        self.assertEqual((target.outlet, target.outlet_domain, target.my_prefs),
                         ("Yahoo Finance", "finance.yahoo.com", ({"id": "I-0003", "direction": "less", "status": "active"},)))
        self.assertEqual(actions.item_source_line(item), "Yahoo Finance via News search: AI deals")
        self.assertEqual(actions.asked_text(target.my_prefs[0]), "You asked for less like this")

    def test_company_mute_says_when_this_story_stays(self):
        # WF5 AW-7
        also = {"this_story": {"event_id": 1, "hidden": False, "is_subject": True, "also_about": ["Nscale"]}}
        self.assertEqual(actions.this_story_line("entity", "Meta Platforms", also), actions.ALSO_ABOUT.format(names="Nscale"))
        vendor = {"this_story": {"event_id": 1, "hidden": False, "is_subject": False, "also_about": []}}
        self.assertIn("names Meta Platforms but isn't about it", actions.this_story_line("entity", "Meta Platforms", vendor))
        self.assertEqual(actions.this_story_line("entity", "Meta", {"this_story": {"hidden": True}}), "")
        self.assertEqual(actions.this_story_line("source", "X", also), "")


class WhyRowTests(unittest.TestCase):
    def test_rows_for_a_briefing_story(self):
        edition = fb.edition()
        target = actions.target_from_item(WS, edition, edition["items"][0])
        first, after = actions.why_rows(target, edition["items"][0]["why"])
        self.assertEqual([label for label, _ in first], ["Why it's here", "The editor's reasoning", "Calibrated"])
        self.assertEqual(first[0][1], "Material news · score 93 of 100")
        self.assertNotIn("#", first[1][1])
        self.assertEqual(first[1][1], labels.clean_rationale(fb.RATIONALE))
        self.assertEqual(after, [("You asked for this", "Should have been in: “Big capacity deals always belong”"),
                                 ("Source", "CoreWeave newsroom · Company news and filings"),
                                 ("Companies", "CoreWeave, Microsoft (on your watchlist)")])

    def test_rows_for_a_filtered_out_row(self):
        row = dict(fb.shelf_row(1301, "Nebius raises capital", 66),
                   subjects=[{"entity_id": "nebius", "name": "Nebius", "muted": True, "starred": False}],
                   stars=[{"entity_id": "x", "name": "X Corp"}])
        target = actions.target_from_row(WS, row)
        first, after = actions.why_rows(target, row)
        self.assertEqual(first, [("Why it was left out", "Near miss · score 66 of 100"),
                                 ("The editor's reasoning", "Close, but no signed capacity.")])
        self.assertEqual(after, [("On your watchlist", "X Corp"), ("Source", "Data Center Dynamics"),
                                 ("Companies", "Nebius (muted)")])
        self.assertEqual(actions.why_rows(target, {"score": 50})[0], [("Why it was left out", "score 50 of 100")])
        self.assertEqual(actions.rows_html([("A", "<b>")]),
                         '<div class="why-block"><div class="why-row"><span class="why-label">A</span><span>&lt;b&gt;'
                         '</span></div></div>')
        self.assertEqual(actions.rows_html([("A", "  ")]), "")


class ToastTests(unittest.TestCase):
    def test_write_toasts(self):
        self.assertEqual(actions.mute_toast("Data Center Dynamics", {"applied_now": 1}),
                         "Muted Data Center Dynamics. Still collected, kept out of your briefing. 1 waiting story was "
                         "set aside now.")
        self.assertEqual(actions.mute_toast("X", {"applied_now": 0}), "Muted X. " + labels.STILL_COLLECTED)
        self.assertEqual(actions.unmute_toast("X", {"brought_back": 1}),
                         "Unmuted X. 1 story comes back for the editor to look at.")
        self.assertEqual(actions.unmute_toast("X", {"brought_back": 0}), "Unmuted X.")
        self.assertEqual(actions.bring_back_toast("X", {"brought_back": 12}),
                         "Brought back what X hid in the last 7 days: 12 stories.")
        self.assertEqual(actions.star_toast("CoreWeave"), "CoreWeave is on your watchlist. " + labels.STAR_PROMISE)
        self.assertEqual(actions.rating_toast(), "Rating saved. " + labels.RATING_HONEST)
        self.assertTrue(actions.preference_toast("less", {}, TZ).startswith("Saved: Show me less like this. "))
        self.assertTrue(actions.promote_toast(None, TZ).endswith("It may still stay out if the evidence is thin."))
        self.assertEqual(actions.mute_label({"kind": "entity"}), "this company")
        self.assertEqual(actions.mute_label({"label": "Anduril"}), "Anduril")
        self.assertEqual(actions.unmute_title(mute={"label": "Anduril"}), "Unmute Anduril?")
        self.assertEqual((actions.preference_title(direction="more"), actions.preference_title(direction="less")),
                         ("More like this", "Less like this"))

    def test_rating_copy_is_honest(self):
        for text in (actions.rating_toast(), actions.__doc__):
            self.assertNotIn("teach", text.lower())
            self.assertNotIn("learn", text.lower())
        self.assertIn("calibrate the next briefing when it differs from the ZENUX editor's score", actions.rating_toast())


if __name__ == "__main__":
    unittest.main()
