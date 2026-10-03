"""AppTest: the app shell (masthead, workspace switcher, config states) and the Feed tab."""

from __future__ import annotations

import base64
import re
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import fixtures as fx
import streamlit as st
from helpers import (AppCase, BETA_HUB, BETA_READ, DASHBOARD, FakeResponse, OWNER, PILOT_HUB, PIN, READ, beta_secrets,
                     one_workspace, two_workspaces, wrong_pin)
from zenux_dashboard import fmt

ITEM_CARD = re.compile(r'<article class="feed-item">.*?</article>')
BLANK_LINE = chr(10) * 2


FOOTER = '<footer class="zx-footer">ZENUX · internal research tool · data from public sources</footer>'


class ShellTests(AppCase):
    def test_masthead_is_zenux_and_workspace_aware(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<header class="zx-masthead"><div class="brand" role="heading" aria-level="1" aria-label="ZENUX">',
                      html)
        self.assertIn('<span class="brand-core">ZENUX</span>', html)
        self.assertIn('<span class="brand-sub">NEWS INTELLIGENCE</span>', html)
        self.assertIn('<span class="brand-workspace">PILOT</span>', html)
        self.assertNotIn("brand-accent", html)  # the old two-colour wordmark is gone
        self.assertNotIn("PHYSICAL", html)
        view = at.radio(key="dashboard_view")
        self.assertEqual(list(view.options), ["Feed", "Rejected", "Rules", "Radar", "Diagnostics"])
        self.assertEqual(view.value, "Feed")
        # one workspace: no switcher
        self.assertEqual([s.key for s in at.selectbox if s.key == "workspace"], [])

    def test_masthead_shows_the_logo_mark_inline(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())
        at = self.app()
        self.assert_clean(at)
        masthead = next(str(m.value) for m in at.markdown if str(m.value).startswith('<header class="zx-masthead">'))
        match = re.search(r'<span class="brand-lockup"><img class="brand-mark" src="data:image/png;base64,([A-Za-z0-9+/=]+)" '
                          r'alt="ZENUX" width="42" height="42"><span class="brand-core">ZENUX</span></span>', masthead)
        self.assertIsNotNone(match, "the mark sits immediately left of the wordmark")
        self.assertEqual(base64.b64decode(match.group(1)), (DASHBOARD / "assets" / "zenux-favicon.png").read_bytes())

    def test_page_icon_is_the_favicon_file(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())
        with patch("streamlit.set_page_config", wraps=st.set_page_config) as spy:
            at = self.app()
        self.assert_clean(at)
        icon = Path(spy.call_args.kwargs["page_icon"])
        self.assertEqual(icon.resolve(), (DASHBOARD / "assets" / "zenux-favicon.png").resolve())
        self.assertTrue(icon.is_file())
        self.assertEqual(spy.call_args.kwargs["page_title"], "ZENUX")

    def test_theme_is_black_with_the_brand_green(self):
        with open(DASHBOARD / ".streamlit" / "config.toml", "rb") as handle:
            theme = tomllib.load(handle)["theme"]
        self.assertEqual(
            {k: theme[k] for k in ("base", "primaryColor", "backgroundColor", "secondaryBackgroundColor", "textColor",
                                   "font")},
            {"base": "dark", "primaryColor": "#006341", "backgroundColor": "#0A0A0A",
             "secondaryBackgroundColor": "#141414", "textColor": "#EDEDED", "font": "sans serif"})
        css = (DASHBOARD / "feed.css").read_text(encoding="utf-8")
        self.assertTrue(css.lstrip().startswith("/*") and "@import url(\"https://fonts.googleapis.com/css2?family=Roboto"
                                                         ":wght@400;500;700;900" in css.split("{", 1)[0])
        tokens = dict(re.findall(r"(--zx-[a-z-]+):\s*(#[0-9a-f]{6})", css))
        # the CSS surfaces match the theme: near-black page, dark cards, hairlines, light text, gray meta
        self.assertEqual(tokens["--zx-bg"], theme["backgroundColor"].lower())
        self.assertEqual(tokens["--zx-card"], theme["secondaryBackgroundColor"].lower())
        self.assertEqual(tokens["--zx-text"], theme["textColor"].lower())
        self.assertEqual((tokens["--zx-muted"], tokens["--zx-line"]), ("#9a9a9a", "#2a2a2a"))
        self.assertEqual(tokens["--zx-green"], "#006341")  # the top bar, the footer and primary buttons stay on brand
        for light in ("#f7f7f7", "#e3e3e3", "#c4c4c4", "--zx-band"):  # the light design's surfaces are gone
            self.assertNotIn(light, css.lower())

    def test_footer_on_every_page(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions())
        for view in ("Feed", "Rejected", "Rules", "Radar", "Diagnostics"):
            with self.subTest(view=view):
                at = self.app(view=view)
                self.assert_clean(at)
                self.assertTrue(self.html(at).endswith(FOOTER))
        at = self.app({"zenux": {"note": "no workspaces here"}})
        self.assertIn(FOOTER, self.html(at))

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

    def edition_blocks(self, at) -> list[str]:
        """The edition card HTML blocks (header and items), newest first."""
        return [str(m.value) for m in at.markdown if str(m.value).startswith('<section class="feed-edition')]

    def test_editions_render_newest_first_with_the_hero_on_the_latest(self):
        at = self.app()
        self.assert_clean(at)
        html = self.html(at)
        latest, older = self.edition_blocks(at)
        self.assertLess(html.index("Edition #12"), html.index("Edition #11"))
        self.assertEqual(html.count('<span class="latest-badge">LATEST</span>'), 1)
        # the hero: the kicker (LATEST, edition, age, time, items), the summary as the title, then the stats panel
        self.assertTrue(latest.startswith(
            '<section class="feed-edition latest-edition"><header class="edition-head has-stats"><div class="edition-main">'
            '<div class="edition-kicker"><span class="latest-badge">LATEST</span><span class="edition-label">Edition #12'
            '</span><span aria-hidden="true">·</span><span>2h ago</span><span aria-hidden="true">·</span><span>'))
        self.assertIn('<span aria-hidden="true">·</span><span>2 items</span></div>'
                      '<div class="edition-title" role="heading" aria-level="2">2 items across AI infrastructure (1) and '
                      'defense unmanned (1), led by Neocloud signs 200 MW &lt;lease&gt; with hyperscaler.</div></div>'
                      '<div class="edition-stats"><div class="stat-grid">', latest)
        # 2x2 tiles: white ITEMS and REVIEWED, orange LEAD 90+, amber DIGEST 70-89
        self.assertIn('<div class="stat-grid">'
                      '<div class="stat"><div class="stat-n">2</div><div class="stat-l">ITEMS</div></div>'
                      '<div class="stat"><div class="stat-n">41</div><div class="stat-l">REVIEWED</div></div>'
                      '<div class="stat stat-high"><div class="stat-n">1</div><div class="stat-l">LEAD 90+</div></div>'
                      '<div class="stat stat-medium"><div class="stat-n">1</div><div class="stat-l">DIGEST 70–89</div></div>'
                      '</div>', latest)
        # the module split bar and its legend: violet ai-infra, teal defense-unmanned
        self.assertIn('<div class="theme-bar" aria-hidden="true"><span style="flex-grow:1;background:#A78BFA"></span>'
                      '<span style="flex-grow:1;background:#2DD4BF"></span></div>'
                      '<div class="theme-legend"><span><i style="background:#A78BFA"></i>AI-INFRA 1</span>'
                      '<span><i style="background:#2DD4BF"></i>DEFENSE-UNMANNED 1</span></div></div></header>', latest)
        # an older edition: the kicker and its title, no stats panel
        self.assertTrue(older.startswith('<section class="feed-edition"><header class="edition-head"><div class="edition-main">'
                                         '<div class="edition-kicker"><span class="edition-label">Edition #11</span>'))
        self.assertNotIn("stat-grid", older)
        self.assertNotIn("theme-bar", older)
        self.assertIn('<div class="rank-marker">01</div>', html)
        # bold white headlines (the colour is the stylesheet's); escaped headline and text, no blank line in the block
        self.assertIn('<div class="feed-item-headline">Neocloud signs 200 MW &lt;lease&gt; with hyperscaler</div>', html)
        self.assertIn("critical IT capacity.<br>Energization is planned for 2027.", html)
        # the source line above the headline
        self.assertIn('<div class="feed-source">Company newsroom</div><details class="feed-details">', html)
        # metrics, sources, tags and the owner's earlier grade
        self.assertIn('<span class="feed-metric">Critical IT <b>200 MW</b></span>', html)
        self.assertIn('<span class="feed-metric">Term <b>15 years</b></span>', html)
        self.assertIn('<a class="source-link" href="https://example.com/neocloud-lease" target="_blank" '
                      'rel="noopener noreferrer">Company newsroom ↗</a>', html)
        self.assertIn('<span class="zx-chip grade">your grade: digest 80</span>', html)
        self.assertIn('<span class="zx-chip tier">Tier 3 · catalyst</span>', html)
        # an unsafe source link is dropped, never rendered as a link
        self.assertNotIn("javascript:", html)
        self.assertNotIn(BLANK_LINE, html)
        call = self.http.find("GET", PILOT_HUB + "/editions")[0]
        self.assertEqual(call.params, {"limit": 10})
        self.assertEqual(call.bearer, READ)
        self.assert_no_secrets(at)

    def test_header_title_is_the_edition_summary(self):
        body = fx.editions()
        body["editions"][0]["summary"] = "A 200 MW <neocloud> lease and a $48M counter-UAS order lead the morning."
        self.http.on("GET", PILOT_HUB + "/editions", body)
        at = self.app()
        self.assert_clean(at)
        latest, older = self.edition_blocks(at)
        self.assertIn('<div class="edition-title" role="heading" aria-level="2">A 200 MW &lt;neocloud&gt; lease and a '
                      '$48M counter-UAS order lead the morning.</div>', latest)
        self.assertNotIn("led by", latest)
        # the older edition has no summary: the fallback sentence
        self.assertIn('<div class="edition-title" role="heading" aria-level="2">2 items across AI infrastructure (1) '
                      'and defense unmanned (1), led by Neocloud signs 200 MW &lt;lease&gt; with hyperscaler.</div>',
                      older)

    def test_header_falls_back_to_a_sentence_built_from_the_items(self):
        body = fx.editions(1)
        items = body["editions"][0]["items"]
        for n in range(3, 10):  # 9 items: 4 in ai-infra, 5 in defense-unmanned
            items.append(dict(items[1], id=1200 + n, rank=n, headline=f"Item {n}",
                              module="ai-infra" if n <= 5 else "defense-unmanned"))
        self.http.on("GET", PILOT_HUB + "/editions", body)
        at = self.app()
        self.assert_clean(at)
        (block,) = self.edition_blocks(at)
        self.assertIn('<div class="edition-title" role="heading" aria-level="2">9 items across AI infrastructure (4) '
                      'and defense unmanned (5), led by Neocloud signs 200 MW &lt;lease&gt; with hyperscaler.</div>',
                      block)
        self.assertIn('<div class="stat"><div class="stat-n">9</div><div class="stat-l">ITEMS</div></div>', block)
        self.assertIn('<span style="flex-grow:4;background:#A78BFA"></span><span style="flex-grow:5;background:#2DD4BF">'
                      '</span>', block)
        self.assertIn('<span><i style="background:#A78BFA"></i>AI-INFRA 4</span>'
                      '<span><i style="background:#2DD4BF"></i>DEFENSE-UNMANNED 5</span>', block)

    def test_grading_note_only_in_a_collapsed_expander_at_the_bottom_of_its_edition(self):
        at = self.app()
        self.assert_clean(at)
        for block in self.edition_blocks(at):  # never in the hero or any edition header
            self.assertNotIn("note", block.lower())
            self.assertNotIn("Two items cleared the bar.", block)
            self.assertNotIn("Edition 11 note", block)
        self.assertNotIn("edition-note", self.html(at))
        self.assertEqual([e.label for e in at.expander], ["Grading notes", "Grading notes"])
        self.assertEqual([e.proto.expanded for e in at.expander], [False, False])
        # page order: each edition card, then its own notes, then the next edition
        order = []
        for node in self.walk(at._tree):
            if node.type == "expander":
                inside = " ".join(str(m.value) for m in self.walk(node) if m.type == "markdown")
                order.append(("notes", inside))
            elif node.type == "markdown" and str(node.value).startswith('<section class="feed-edition'):
                order.append(("edition", re.search(r"Edition #\d+", str(node.value)).group(0)))
        self.assertEqual(order, [
            ("edition", "Edition #12"), ("notes", '<div class="grading-notes">Two items cleared the bar.</div>'),
            ("edition", "Edition #11"), ("notes", '<div class="grading-notes">Edition 11 note</div>'),
        ])

    def test_no_grading_notes_expander_without_a_note(self):
        self.http.on("GET", PILOT_HUB + "/editions", fx.empty_edition())
        at = self.app()
        self.assert_clean(at)
        self.assertEqual(list(at.expander), [])
        self.assertIn("An empty edition: nothing cleared the bar in this window.", self.html(at))

    def test_grading_notes_sit_between_the_items_and_the_grade_form(self):
        at = self.app(pin=PIN, grading=True)
        self.assert_clean(at)
        form = next(n for n in self.walk(at._tree) if n.type == "form")
        kinds = []
        for node in self.walk(form):
            if node.type == "expander":
                kinds.append("notes")
            elif node.type == "markdown" and 'class="feed-edition' in str(node.value):
                kinds.append("edition")
            elif node.type == "markdown" and "digest-grading-title" in str(node.value):
                kinds.append("grade form")
        self.assertEqual(kinds, ["edition", "notes", "grade form"])

    def test_item_cards_show_module_tags_and_no_score_pill(self):
        body = fx.editions(1)
        body["editions"][0]["items"][1]["modules"] = ["defense-unmanned", "ai-infra", "space-launch"]
        self.http.on("GET", PILOT_HUB + "/editions", body)
        at = self.app()
        self.assert_clean(at)
        first, second = ITEM_CARD.findall(self.html(at))
        for card in (first, second):
            self.assertNotIn("score", card.lower())
            self.assertNotIn("value-badge", card)
        violet = "color:#A78BFA;border-color:rgba(167,139,250,0.55);background:rgba(167,139,250,0.14)"
        teal = "color:#2DD4BF;border-color:rgba(45,212,191,0.55);background:rgba(45,212,191,0.14)"
        # no `modules`: the item's own module, as a violet pill (tinted fill, coloured border, coloured text)
        self.assertIn(f'<div class="feed-tags"><span class="module-tag" style="{violet}">AI INFRASTRUCTURE</span>'
                      '<span class="zx-chip tier">Tier 3 · catalyst</span></div>', first)
        # `modules` wins, in order; an unknown module gets a stable colour from the small palette
        other = fmt.module_color("space-launch")
        self.assertIn(other, fmt.TAG_COLORS)
        self.assertIn(f'<div class="feed-tags"><span class="module-tag" style="{teal}">DEFENSE UNMANNED</span>'
                      f'<span class="module-tag" style="{violet}">AI INFRASTRUCTURE</span>'
                      f'<span class="module-tag" style="{fmt.tag_style(other)}">SPACE LAUNCH</span>'
                      '<span class="zx-chip tier">Tier 3 · catalyst</span>', second)

    def test_search_filters_loaded_items(self):
        at = self.app()
        at.text_input(key="feed_search").set_value("counter-uas").run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("2 search results", html)
        self.assertIn('<div class="feed-item-headline">Army awards $48M counter-UAS order</div>', html)
        self.assertNotIn('<div class="feed-item-headline">Neocloud', html)  # its card is filtered out
        self.assertEqual(len(ITEM_CARD.findall(html)), 2)
        # the header still describes the whole edition, and says how many items matched
        self.assertIn('<span>2 items</span><span aria-hidden="true">·</span><span>1 matching</span>', html)
        self.assertNotIn("LATEST", html)
        at.text_input(key="feed_search").set_value("defense unmanned").run()  # module display names are searchable
        self.assertEqual(len(ITEM_CARD.findall(self.html(at))), 2)
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
