"""AppTest: the Briefing tab (docs/SPEC-PHASE03-UI.md 5.1-5.3): briefing names, the hero, story cards, corrections,
shelves, the editor's notes, search, paging, deep links, the Why expander, the empty, staging and error states, and
the plain-words guard. The card actions themselves are in test_actions.py."""

from __future__ import annotations

import re
import unittest

import fixtures as fx
import fixtures_briefing as fb
from helpers import (AppCase, BETA_HUB, BETA_READ, DASHBOARD, FakeResponse, PILOT_HUB, PIN, READ, hub_defaults,
                     two_workspaces)
from zenux_dashboard import feed_view, labels

EDITIONS = PILOT_HUB + "/editions"
ITEM_CARD = re.compile(r'<article class="feed-item[^"]*">.*?</article>')
BLANK_LINE = chr(10) * 2
TZ = "America/New_York"


def esc_text(text: str) -> str:
    """How esc() writes a plain sentence into the page."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#x27;").replace(
        '"', "&quot;")


class BriefingCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        self.http.on("GET", EDITIONS, fb.editions())
        self.http.on("GET", PILOT_HUB + "/preferences", fb.preferences())
        self.http.on("GET", PILOT_HUB + "/mutes", fb.mutes())

    @staticmethod
    def edition_blocks(at) -> list[str]:
        """The briefing header blocks, in page order."""
        return [str(m.value) for m in at.markdown if str(m.value).startswith('<section class="feed-edition')]

    def cards(self, at) -> list[str]:
        return ITEM_CARD.findall(self.html(at))

    def editions_calls(self) -> list[dict]:
        return [c.params for c in self.http.find("GET", EDITIONS)]


class BriefingPageTests(BriefingCase):
    def test_briefings_are_named_by_time_never_by_number(self):
        at = self.app()
        self.assert_clean(at)
        latest, older = self.edition_blocks(at)
        self.assertTrue(latest.startswith(
            '<section class="feed-edition latest-edition"><header class="edition-head has-stats"><div class="edition-main">'
            f'<div class="edition-kicker"><span class="latest-badge">LATEST</span><span class="edition-label">'
            f'{fb.LATEST_LABEL}</span><span aria-hidden="true">·</span><span>'))
        self.assertIn('<span aria-hidden="true">·</span><span>7:41 AM ET</span><span aria-hidden="true">·</span>'
                      '<span>2 stories</span></div>', latest)
        self.assertTrue(older.startswith(
            '<section class="feed-edition"><header class="edition-head"><div class="edition-main"><div class="edition-kicker">'
            f'<span class="edition-label">{fb.OLDER_LABEL}</span>'))
        html = self.html(at)
        self.assertNotIn("Edition #", html)
        self.assertNotIn("#12", self.visible_text(at))
        self.assertEqual(html.count('<span class="latest-badge">LATEST</span>'), 1)
        # the fallback title says stories, and names coverage areas plainly
        self.assertIn('<div class="edition-title" role="heading" aria-level="2">2 stories across AI infrastructure (1) '
                      'and defense unmanned (1), led by CoreWeave signs 200 MW &lt;capacity&gt; deal with Microsoft.'
                      '</div>', latest)
        # five briefings per page, read with the read token
        first = self.http.find("GET", EDITIONS)[0]
        self.assertEqual((first.params, first.bearer), ({"limit": 5}, READ))
        self.assert_no_secrets(at)

    def test_summary_title_and_volume_chip(self):
        body = fb.editions()
        body["editions"][0]["summary"] = "A 200 MW <capacity> deal and a $48M order lead the morning."
        body["editions"][0]["selection"]["volume"] = "top"
        body["editions"][1]["selection"]["volume"] = "standard"
        self.http.on("GET", EDITIONS, body)
        at = self.app()
        self.assert_clean(at)
        latest, older = self.edition_blocks(at)
        self.assertIn('<div class="edition-title" role="heading" aria-level="2">A 200 MW &lt;capacity&gt; deal and a $48M '
                      'order lead the morning.</div>', latest)
        self.assertIn('<span class="zx-chip tier">Only the big ones</span></div>', latest)
        self.assertNotIn("Standard", older)

    def test_hero_tiles_and_coverage_area_legend(self):
        at = self.app()
        self.assert_clean(at)
        latest, older = self.edition_blocks(at)
        self.assertIn('<div class="stat-grid">'
                      '<div class="stat"><div class="stat-n">2</div><div class="stat-l">STORIES</div></div>'
                      '<div class="stat"><div class="stat-n">41</div><div class="stat-l">SCREENED</div></div>'
                      '<div class="stat stat-high"><div class="stat-n">1</div><div class="stat-l">TOP STORIES</div></div>'
                      '<div class="stat stat-medium"><div class="stat-n">1</div><div class="stat-l">ALSO NOTABLE</div></div>'
                      '</div>', latest)
        self.assertIn('<div class="theme-legend"><span><i style="background:#A78BFA"></i>AI INFRASTRUCTURE 1</span>'
                      '<span><i style="background:#2DD4BF"></i>DEFENSE UNMANNED 1</span></div>', latest)
        for old in ("ITEMS", "REVIEWED", "LEAD 90+", "DIGEST", "AI-INFRA", "DEFENSE-UNMANNED"):
            self.assertNotIn(old, latest)
        self.assertNotIn("stat-grid", older)

    def test_story_cards(self):
        at = self.app()
        self.assert_clean(at)
        first, second, *_ = self.cards(at)
        # dateline: the story's date and its plain source name
        self.assertIn('<div class="rank-marker">01</div><div class="feed-copy"><div class="feed-dateline">Oct 2 · '
                      'CoreWeave newsroom</div><details class="feed-details">', first)
        # the hub's label is only the source key (no catalog yet): the first source's name; the briefing's date
        self.assertIn('<div class="feed-dateline">Oct 3 · war.gov</div>', second)
        self.assertNotIn("wargov-contracts", self.html(at))
        self.assertNotIn("ent-coreweave-1", self.html(at))
        # TOP STORY only at 90+
        self.assertIn('<span class="badge-top">TOP STORY</span>', first)
        self.assertNotIn("TOP STORY", second)
        # plain tier names, coverage-area tags
        violet = "color:#A78BFA;border-color:rgba(167,139,250,0.55);background:rgba(167,139,250,0.14)"
        teal = "color:#2DD4BF;border-color:rgba(45,212,191,0.55);background:rgba(45,212,191,0.14)"
        self.assertIn(f'<div class="feed-tags"><span class="module-tag" style="{violet}">AI INFRASTRUCTURE</span>'
                      '<span class="badge-top">TOP STORY</span><span class="zx-chip tier">Your coverage</span>', first)
        self.assertIn(f'<div class="feed-tags"><span class="module-tag" style="{teal}">DEFENSE UNMANNED</span>'
                      f'<span class="module-tag" style="{violet}">AI INFRASTRUCTURE</span>'
                      '<span class="zx-chip tier">Industry and policy</span>', second)
        self.assertNotIn("Tier", self.html(at))
        # states: the newest plain rating (not the "Should have been in" note after it), a starred subject
        self.assertIn('<span class="zx-chip grade">You rated it: Top story</span>', first)
        self.assertNotIn("You rated it: In the briefing", first)
        self.assertIn('<span class="zx-chip chip-state chip-starred">On your watchlist</span>', first)
        self.assertNotIn("chip-state", second)
        # headline, text, metrics and links, escaped; an unsafe link is dropped
        self.assertIn('<div class="feed-item-headline">CoreWeave signs 200 MW &lt;capacity&gt; deal with Microsoft</div>',
                      first)
        self.assertIn("critical IT capacity.<br>Energization is planned for 2027.", first)
        self.assertIn('<span class="feed-metric">Critical IT <b>200 MW</b></span>', first)
        self.assertIn('<a class="source-link" href="https://example.com/coreweave" target="_blank" '
                      'rel="noopener noreferrer">CoreWeave newsroom ↗</a>', first)
        html = self.html(at)
        self.assertNotIn("javascript:", html)
        self.assertNotIn(BLANK_LINE, html)
        # every card is its own block with its action row: More, Less and Rate side by side, no More menu
        self.assertEqual({b.key for b in at.button if str(b.key).startswith("act_more_")},
                         {"act_more_i1201", "act_more_i1202", "act_more_i1101", "act_more_i1102"})
        self.assertEqual({b.key for b in at.button if str(b.key).startswith("act_rate_")},
                         {"act_rate_i1201", "act_rate_i1202", "act_rate_i1101", "act_rate_i1102"})
        self.assertEqual([p for p in at.get("popover") if str(getattr(p, "key", "") or "").startswith("zx_more_")], [])
        # one "Why am I seeing this?" per briefing, under the editor's notes, collapsed
        self.assertEqual([e.label for e in at.expander if e.label != feed_view.NOTES_LABEL],
                         ["Why am I seeing this?"] * 2)

    def test_correction_states(self):
        self.http.on("GET", EDITIONS, fb.with_corrections())
        at = self.app()
        self.assert_clean(at)
        flagged, corrected = self.cards(at)
        self.assertIn('<span class="zx-chip chip-state chip-flagged">Flagged by you · being re-checked</span>', flagged)
        # a corrected story shows the corrected headline, text and metrics instead of its own
        self.assertIn('<span class="zx-chip chip-state chip-corrected">Corrected</span>', corrected)
        self.assertIn('<div class="feed-item-headline">Army awards $12M counter-UAS order to Anduril</div>', corrected)
        self.assertIn("The Army awarded a $12 million order for interceptors.", corrected)
        self.assertIn('<span class="feed-metric">Obligated <b>$12M</b></span>', corrected)
        self.assertNotIn("$48", corrected)
        # the briefing's corrections block, above the stories
        block = next(str(m.value) for m in at.markdown if str(m.value).startswith('<div class="correction-note">'))
        self.assertIn('<div class="correction-note"><div class="edition-label">Correction to “Army awards $48M '
                      'counter-UAS order to Anduril”</div><div class="feed-item-headline">Army awards $12M counter-UAS '
                      'order to Anduril</div><div class="feed-text">The award was $12 million, not $48 million.</div>',
                      block)
        self.assertIn('href="https://www.war.gov/News/Contracts/"', block)
        self.assertIn('<div class="correction-note"><div class="edition-label">Checked: “Nebius signs 300 MW deal” '
                      'stands.</div><div class="feed-text">The release states 300 MW in its second paragraph; the story '
                      'is correct.</div></div>', block)
        html = self.html(at)
        self.assertLess(html.index('<section class="feed-edition'), html.index('<div class="correction-note">'))
        self.assertLess(html.index('<div class="correction-note">'), html.index('<article class="feed-item'))

    def test_upheld_story(self):
        self.http.on("GET", EDITIONS, fb.upheld_item())
        at = self.app()
        self.assert_clean(at)
        self.assertIn('<span class="zx-chip chip-state chip-upheld">Checked: stands</span>', self.cards(at)[0])

    def test_watchlist_and_near_miss_shelves(self):
        self.http.on("GET", EDITIONS, fb.with_shelves())
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="shelf"><div class="shelf-title">On your watchlist · not in this briefing</div></div>',
                      html)
        self.assertIn('<div class="shelf"><div class="shelf-title">Near misses · just under your bar</div></div>', html)
        self.assertLess(html.index("On your watchlist · not in"), html.index("Near misses · just under"))
        self.assertIn('<div class="shelf-row"><div class="feed-dateline">Oct 3 · Data Center Dynamics</div>'
                      '<div><a class="source-link" href="https://example.com/story-1300" target="_blank" '
                      'rel="noopener noreferrer">CoreWeave opens a &lt;new&gt; site in Texas</a></div>'
                      '<div class="feed-tags"><span class="zx-chip tier">Near miss</span>'
                      '<span class="zx-chip chip-state chip-starred">About CoreWeave</span></div></div>', html)
        self.assertIn('<span class="zx-chip tier">Below your &quot;how much&quot; setting</span></div></div>', html)
        self.assertEqual(html.count("About "), 1)  # company names only on the watchlist shelf
        keys = [b.key for b in at.button if str(b.key).startswith("br_promote_")]
        self.assertEqual(keys, ["br_promote_0_watchlist_1300", "br_promote_0_near_1301", "br_promote_0_near_1302"])
        self.assertEqual({at.button(key=k).label for k in keys}, {"Should have been in"})

    def test_no_shelves_when_empty_or_off(self):
        body = fb.editions()
        body["editions"][1]["shelves"] = None  # a briefing published before shelves existed
        self.http.on("GET", EDITIONS, body)
        at = self.app()
        self.assert_clean(at)
        self.assertNotIn("shelf-title", self.html(at))
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("br_promote_")], [])

    def test_editors_notes_are_collapsed_at_the_bottom(self):
        at = self.app()
        self.assert_clean(at)
        for block in self.edition_blocks(at):
            self.assertNotIn("Two stories cleared the bar.", block)
        notes = [e for e in at.expander if e.label == "Editor's notes"]
        self.assertEqual(len(notes), 2)
        self.assertEqual([e.proto.expanded for e in notes], [False, False])
        self.assertNotIn("Grading notes", [e.label for e in at.expander])
        inside = [" ".join(str(m.value) for m in self.walk(e) if m.type == "markdown") for e in notes]
        self.assertEqual(inside, ['<div class="grading-notes">Two stories cleared the bar.</div>',
                                  '<div class="grading-notes">Briefing 11 note</div>'])

    def test_an_empty_briefing(self):
        body = fb.editions(1)
        body["editions"][0].update(items=[], note=None, item_count=0)
        self.http.on("GET", EDITIONS, body)
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="edition-empty">Nothing new cleared your bar in this briefing.</div>', html)
        self.assertIn("An empty briefing: nothing new cleared your bar.", html)
        self.assertIn('<div class="stat-n">0</div><div class="stat-l">STORIES</div>', html)
        self.assertEqual([e.label for e in at.expander], [])


class SearchTests(BriefingCase):
    def test_search_box_is_always_visible_and_says_what_it_covers(self):
        at = self.app()
        self.assert_clean(at)
        box = at.text_input(key="br_search")
        self.assertEqual((box.label, box.placeholder), ("Search your briefings", "Company, topic or source"))
        self.assertIn("Searches headlines, story text and companies in your briefings of the last 90 days. Matches in "
                      "the 2 briefings loaded below (back to Fri Oct 2) show in full.", self.texts(at, "caption"))

    def test_search_results_and_no_hits(self):
        at = self.app()
        at.text_input(key="br_search").set_value("anduril").run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="section-label"><span>2 matching stories</span></div>', html)
        self.assertEqual(len(self.cards(at)), 2)
        self.assertNotIn("CoreWeave signs", "".join(self.cards(at)))
        self.assertIn('<span>2 stories</span><span aria-hidden="true">·</span><span>1 matching</span>', html)
        self.assertNotIn("LATEST", html)
        # companies, sources and coverage areas are searchable
        for query, hits in (("microsoft", 2), ("war.gov", 2), ("defense unmanned", 2), ("coreweave newsroom", 2),
                            ("army anduril", 2), ("capacity deal", 2)):
            with self.subTest(query=query):
                at.text_input(key="br_search").set_value(query).run()
                self.assert_clean(at)
                self.assertEqual(len(self.cards(at)), hits)
        at.text_input(key="br_search").set_value("no such company").run()
        self.assert_clean(at)
        self.assertIn("No matching stories in your briefings of the last 90 days. Try another word.", self.html(at))
        self.assertEqual(self.cards(at), [])
        # every briefing is loaded here: the hub's search is not needed
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/editions/search"), [])

    def test_earlier_briefings_are_searched_by_the_hub(self):
        # gap 4: matches in briefings not loaded come from GET /editions/search, each with Show it
        first = fb.page(20, 5, more=True)
        self.http.on("GET", EDITIONS, first)
        hits = [fx.search_hit(20, 2001, "A match in a loaded briefing"),  # drawn as a card already: left out
                fx.search_hit(9, 901, "Anduril wins an older <order>", hours=400),
                fx.search_hit(8, 801, "Anduril earlier still", hours=500)]
        self.http.on("GET", PILOT_HUB + "/editions/search", fx.search_hits("anduril", hits, total=60))
        at = self.app()
        at.text_input(key="br_search").set_value("anduril").run()
        self.assert_clean(at)
        call = self.http.find("GET", PILOT_HUB + "/editions/search")[-1]
        self.assertEqual((call.params.get("q"), call.params.get("days"), call.bearer), ("anduril", 90, READ))
        html = self.html(at)
        self.assertIn('<div class="shelf-title">Earlier briefings · 2</div>', html)
        self.assertIn("Anduril wins an older &lt;order&gt;", html)
        self.assertNotIn("A match in a loaded briefing", html)
        self.assertIn(fx.search_hit(9, 901, "x", hours=400)["briefing_label"], html)
        self.assertIn(feed_view.EARLIER_MORE.format(n=2), self.texts(at, "caption"))
        cards = len(self.cards(at))
        self.assertIn(f"<span>{cards + 2} matching stories</span>", html)
        self.assert_plain(at)
        self.http.on("GET", EDITIONS + "/9", {"edition": fb.edition(9, "2026-09-20T12:00:00Z")})
        at.button(key="br_hit_9_901").click().run()
        self.assert_clean(at)
        self.assertEqual(at.text_input(key="br_search").value, "")  # the search is cleared
        self.assertEqual((at.query_params.get("edition"), at.query_params.get("item")), ("9", "901"))
        self.assertTrue(self.http.find("GET", EDITIONS + "/9"))
        self.assertIn("Showing the briefing you linked.", self.html(at))

    def test_a_failed_search_of_earlier_briefings_is_said(self):
        self.http.on("GET", EDITIONS, fb.page(20, 5, more=True))
        self.http.on("GET", PILOT_HUB + "/editions/search", FakeResponse(500, {"error": "internal_error"}))
        at = self.app()
        at.text_input(key="br_search").set_value("zeppelin").run()
        self.assert_clean(at)
        self.assertIn("Couldn't search earlier briefings: Something went wrong on the server.", self.texts(at, "caption"))
        self.assertIn(feed_view.NO_HITS, self.html(at))


class PagingTests(BriefingCase):
    def test_load_earlier_briefings(self):
        first = fb.page(20, 5, more=True)
        older = fb.page(15, 2, more=False)
        self.http.on("GET", EDITIONS, lambda call: older if call.params.get("before") == 16 else first)
        at = self.app()
        self.assert_clean(at)
        self.assertEqual(len(self.edition_blocks(at)), 5)
        self.assertTrue(any(c.endswith("Matches in earlier briefings are listed after them.")
                            for c in self.texts(at, "caption")))
        at.button(key="br_more").click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.edition_blocks(at)), 7)
        self.assertEqual([p.get("before") for p in self.editions_calls() if p.get("limit") == 5][-2:], [None, 16])
        self.assertEqual([b.key for b in at.button if b.key == "br_more"], [])
        self.assertFalse(any("earlier briefings" in c for c in self.texts(at, "caption")))


class DeepLinkTests(BriefingCase):
    def linked(self):
        old = fb.edition(7, "2026-09-30T16:05:00Z")  # Wed Sep 30, 12:05 PM ET
        old["note"] = "Briefing 7 note"
        self.http.on("GET", EDITIONS + "/7", {"edition": old})  # GET /editions/<id> (gap 1)

    def test_a_linked_older_briefing_is_drawn_first(self):
        self.linked()
        at = self.app(query={"tab": "briefing", "edition": "7", "item": "702"})
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", EDITIONS + "/7")[-1].bearer, READ)
        self.assertEqual(self.editions_calls(), [{"limit": 5}])  # no paging trick
        self.assertIn("Showing the briefing you linked.", self.html(at))
        blocks = self.edition_blocks(at)
        self.assertEqual(len(blocks), 3)
        self.assertIn('<span class="edition-label">Wed Sep 30 · midday briefing</span>', blocks[0])
        self.assertIn("latest-edition", blocks[1])  # the hero stays on the newest briefing
        focused = [c for c in self.cards(at) if c.startswith('<article class="feed-item zx-focus">')]
        self.assertEqual(len(focused), 1)
        self.assertIn("Army awards $48M", focused[0])
        # Why starts collapsed, also for a linked story; opened, it lists the linked briefing's stories by number
        self.assertNotIn("Official confirmation · score 78 of 100", self.html(at))
        self.open_expander(at, "zx_whyall_linked")
        at.run()
        self.assert_clean(at)
        self.assertIn("Official confirmation · score 78 of 100", self.html(at))
        at.button(key="br_back_latest").click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.edition_blocks(at)), 2)
        self.assertNotIn("Showing the briefing you linked.", self.html(at))
        self.assertNotIn("zx-focus", self.html(at))

    def test_a_linked_item_in_a_loaded_briefing(self):
        at = self.app(query={"tab": "briefing", "edition": "12", "item": "1201"})
        self.assert_clean(at)
        self.assertNotIn({"limit": 1, "before": 13}, self.editions_calls())  # already loaded: no extra read
        self.assertNotIn("Showing the briefing you linked.", self.html(at))
        focused = [c for c in self.cards(at) if "zx-focus" in c]
        self.assertEqual(len(focused), 1)
        self.assertIn("CoreWeave signs 200 MW", focused[0])
        self.assertNotIn("Material news · score 93 of 100", self.html(at))  # Why starts collapsed

    def test_a_linked_briefing_that_is_gone(self):
        self.http.on("GET", EDITIONS, lambda call: {"editions": [], "next_before": None, "has_more": False}
                     if call.params.get("before") == 100 else fb.editions())
        at = self.app(query={"tab": "briefing", "edition": "99"})
        self.assert_clean(at)
        self.assertIn("The briefing you linked isn" + "&#x27;t available any more.", self.html(at))
        self.assertEqual(len(self.edition_blocks(at)), 2)
        self.assertTrue(any(b.key == "br_back_latest" for b in at.button))


class WhyTests(BriefingCase):
    def test_why_rows(self):
        at = self.app()
        self.open_expander(at, "zx_whyall_0")
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        # one entry per story of the briefing, headed by the story's number and headline
        heads = [str(m.value) for m in at.markdown if 'class="why-item-head"' in str(m.value)]
        self.assertEqual(heads, [
            '<div class="why-item-head"><span class="why-num">01</span><span class="why-title">CoreWeave signs 200 MW '
            '&lt;capacity&gt; deal with Microsoft</span></div>',
            '<div class="why-item-head"><span class="why-num">02</span><span class="why-title">'
            f'{esc_text(fb.edition(fb.LATEST_ID, fb.LATEST_AT)["items"][1]["headline"])}</span></div>'])
        rows = next(str(m.value) for m in at.markdown if "Why it&#x27;s here" in str(m.value))
        self.assertEqual(rows, (
            '<div class="why-block">'
            '<div class="why-row"><span class="why-label">Why it&#x27;s here</span><span>Material news · score 93 of 100'
            '</span></div>'
            '<div class="why-row"><span class="why-label">The editor&#x27;s reasoning</span><span>'
            f'{esc_text(labels.clean_rationale(fb.RATIONALE))}</span></div>'
            '<div class="why-row"><span class="why-label">Calibrated</span><span>The editor matched this to your earlier '
            'ratings.</span></div></div>'))
        self.assertNotIn("#41", html)
        self.assertNotIn("#9002", html)
        # the preferences that applied, in the analyst's words (I-0003's text is looked up), with their status
        self.assertIn('<div class="why-row"><span>Capacity deals with named hyperscalers.</span>'
                      '<span class="why-label">Active</span></div>', html)
        self.assertIn('<div class="why-row"><span>Stock-move articles with no new facts.</span>'
                      '<span class="why-label">Paused</span></div>', html)
        self.assertNotIn("R-0012", self.visible_text(at))
        self.assertNotIn("event #1234", html)
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/preferences")), 1)
        after = next(str(m.value) for m in at.markdown if "You asked for this" in str(m.value))
        self.assertEqual(after, (
            '<div class="why-block">'
            '<div class="why-row"><span class="why-label">You asked for this</span><span>Should have been in: “Big '
            'capacity deals always belong” (asked Oct 3)</span></div>'
            '<div class="why-row"><span class="why-label">Source</span><span>CoreWeave newsroom · Company news and filings'
            '</span></div>'
            '<div class="why-row"><span class="why-label">Companies</span><span>CoreWeave, Microsoft (on your watchlist)'
            '</span></div></div>'))
        # each preference links to My preferences (AppTest forgets a keyed expander's open state: open it again)
        self.assertEqual(at.button(key="why_pref_w0_0_0").label, "See it in My preferences")
        self.open_expander(at, "zx_whyall_0")
        at.button(key="why_pref_w0_0_1").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state["zx_tab"], "preferences")
        self.assertEqual({k: at.session_state["zx_focus"].get(k) for k in ("section", "pref")},
                         {"section": "active", "pref": "I-0003"})

    def test_why_is_lazy(self):
        at = self.app()
        self.assert_clean(at)
        self.assertNotIn("why-block", self.html(at))
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/preferences"), [])
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("why_pref_")], [])


class HubPlainWordsTests(AppCase):
    """The WF5 fields of GET /editions (docs/SPEC-PHASE05.md 3.3 and 4), from fixtures.editions_v8."""

    def setUp(self):
        super().setUp()
        hub_defaults(self.http)

    def test_the_hubs_briefing_name_is_shown(self):
        body = fx.editions_v8()
        body["editions"][0]["briefing_label"] = "Sun Oct 4 · special briefing"  # whatever the hub says
        self.http.on("GET", EDITIONS, body)
        at = self.app()
        self.assert_clean(at)
        self.assertIn('<span class="edition-label">Sun Oct 4 · special briefing</span>', self.html(at))
        self.assertIn(f'<span class="edition-label">{body["editions"][1]["briefing_label"]}</span>', self.html(at))

    def test_every_company_the_story_is_about_can_be_starred_or_muted(self):
        # gap 15: why.companies adds the buyer, which why.subjects leaves out
        self.more_menu_on()
        at = self.app(pin=PIN, state={"zx_more_i1201": True})
        self.assert_clean(at)
        labels_shown = {b.label for b in at.button if str(b.key or "").startswith(("act_star_i1201", "act_mute_co_i1201"))}
        self.assertIn("Star Hyperscale Co", labels_shown)
        self.assertIn("Mute company: Hyperscale Co", labels_shown)
        self.assertIn("Remove CoreWeave from watchlist", {b.label for b in at.button})
        self.assert_plain(at)

    def test_why_reads_the_plain_reasoning(self):
        at = self.app(state={"zx_whyall_0": True})
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Signed 15-year 200 MW agreement with a named hyperscaler", html)
        self.assertNotIn("calibrated by your feedback", html)  # the Calibrated row says it
        self.assertIn("Follows the award reported as another story with the order value.", html)  # the last guard
        self.assertIn('<span class="why-label">Source</span><span>war.gov</span>', html)  # never the source key
        self.assert_plain(at)


class StateTests(BriefingCase):
    def test_no_briefings_yet(self):
        self.http.on("GET", EDITIONS, {"editions": [], "next_before": None, "has_more": False})
        at = self.app()
        self.assert_clean(at)
        message = next(m for m in re.findall(r'<div class="empty-state">(.*?)</div>', self.html(at)))
        self.assertTrue(message.startswith("No briefings yet. The ZENUX editor publishes one at each scheduled time "
                                           "(next: "), message)
        self.assertTrue(message.endswith(" ET)."), message)

    def test_staging_points_to_sign_off(self):
        self.http.on("GET", EDITIONS, {"editions": [], "next_before": None, "has_more": False})
        self.http.on("GET", PILOT_HUB + "/status", fx.status("amber", stage="staging", last_hours=None, reasons=[
            {"level": "amber", "code": "awaiting_signoff", "text": "Collecting. Briefings start after you sign off."}]))
        at = self.app()
        self.assert_clean(at)
        self.assertIn("ZENUX is collecting. Briefings start after you sign off in My preferences › What ZENUX looks "
                      "for.", self.html(at))
        at.button(key="br_signoff").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state["zx_tab"], "preferences")
        self.assertEqual(at.session_state["zx_focus"].get("section"), "looks_for")

    def test_read_errors_are_plain(self):
        for handler, words in ((None, "be reached right now."),
                               (FakeResponse(401, {"error": "unauthorized"}), "access was refused."),
                               (FakeResponse(500, {"error": "internal"}), "Something went wrong on the server.")):
            with self.subTest(words=words):
                self.fresh()
                if handler is None:
                    self.http.routes.pop(("GET", EDITIONS), None)
                else:
                    self.http.on("GET", EDITIONS, handler)
                at = self.app()
                self.assert_clean(at)
                text = self.visible_text(at)
                self.assertIn("load your briefings.", text)
                self.assertIn(words, text)
                self.assertTrue(any(b.key == "zx_retry_briefing" for b in at.button))
                self.assertNotIn("HTTP 401", self.html(at))
                self.assert_no_secrets(at)

    def test_malformed_payloads_render_without_crashing(self):
        junk_why = {"subjects": "x", "rules": [None, 3, {"id": None}, "R-1"], "source": 5, "stars": [None, "a"],
                    "promoted": "x", "calibrated_by": "x", "score": "high", "reason_code": ["x"]}
        self.http.on("GET", EDITIONS, {"editions": [
            {"id": 1, "published_at": "soon", "selection": "x", "corrections": [None, {"outcome": "corrected",
                                                                                        "sources": "x"}],
             "shelves": {"watchlist": "x", "near_misses": [None, {"event_id": "x", "url": "javascript:x"}]},
             "items": [{"rank": "x", "headline": None, "sources": "nope", "metrics": {"a": 1}, "why": "junk",
                        "correction": [1], "feedback": "x", "modules": "y", "tier": True},
                       "junk", {"id": 5, "why": junk_why, "event": "x"}, {"id": 5, "rank": 2}]},
            "junk", {"items": None}, {"id": 1, "items": []}]})
        self.http.on("GET", PILOT_HUB + "/preferences", {"preferences": "x"})
        at = self.app(pin=PIN)
        self.assert_clean(at)
        self.assertNotIn("javascript:", self.html(at))
        keys = [str(b.key)[len("act_more_"):] for b in at.button if str(b.key).startswith("act_more_")]
        self.assertEqual(len(keys), len(set(keys)))  # repeated ids never collide
        for key in keys:
            self.open_popover(at, f"zx_more_{key}")
        for index in range(4):
            self.open_expander(at, f"zx_whyall_{index}")
        at.run()
        self.assert_clean(at)
        self.assertNotIn("javascript:", self.html(at))

    def test_nothing_on_the_page_reruns_on_a_timer(self):
        for name in ("feed_view.py", "actions.py"):
            source = (DASHBOARD / "zenux_dashboard" / name).read_text(encoding="utf-8")
            self.assertNotIn("run_every", source)
            self.assertNotIn("st.fragment", source)

    def test_another_workspace_reads_its_own_hub(self):
        hub_defaults(self.http, BETA_HUB)
        beta = fb.editions(1)
        beta["editions"][0]["note"] = "Beta analyst briefing"
        self.http.on("GET", BETA_HUB + "/editions", beta)
        at = self.app(two_workspaces())
        self.assert_clean(at)
        at.selectbox(key="workspace").set_value("beta").run()
        self.assert_clean(at)
        self.assertIn("Beta analyst briefing", self.html(at))
        calls = self.http.find("GET", BETA_HUB + "/editions")
        self.assertTrue(calls)
        self.assertEqual({c.bearer for c in calls}, {BETA_READ})


class PlainWordsTests(BriefingCase):
    def test_a_fully_open_briefing_uses_plain_words(self):
        body = fb.with_corrections()
        body["editions"][0]["shelves"] = fb.with_shelves()["editions"][0]["shelves"]
        body["editions"].append(fb.edition(fb.OLDER_ID, fb.OLDER_AT))
        self.http.on("GET", EDITIONS, body)
        at = self.app(pin=PIN, run=False)
        for key in ("i1201", "i1202", "i1101", "i1102"):
            self.open_popover(at, f"zx_more_{key}")
        for index in (0, 1):
            self.open_expander(at, f"zx_whyall_{index}")
        at.run()
        self.assert_clean(at)
        visible = self.visible_text(at)
        for word in ("Wrong facts", "Rate this story", "Mute source: CoreWeave newsroom", "Mute company: CoreWeave",
                     "Star CoreWeave", "Remove Microsoft from watchlist", "Unmute company: Anduril", "Mute this story",
                     labels.STILL_COLLECTED, "Your preferences that applied", "Editor's notes"):
            self.assertIn(word, visible)
        self.assert_plain(at)
        self.assert_no_secrets(at)
        for code in ("ent-coreweave-1", "wargov-contracts", "R-0012", "I-0003", "s-100", "ai-infra",
                     "defense-unmanned", "#41", "#1234"):
            self.assertNotIn(code, visible)


if __name__ == "__main__":
    unittest.main()
