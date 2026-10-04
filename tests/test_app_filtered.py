"""AppTest: the Filtered out tab (docs/SPEC-PHASE03-UI.md section 6; GET /rejected of docs/SPEC-PHASE05.md 2).

Every GET /rejected goes through one routed handler that answers by the request's `filter`, `days`, `include_auto`,
`q`, `module` and `offset`, as the hub filters, searches and pages (fixtures_filtered.rejected_for), so each test can
check which read a view sends.
"""

from __future__ import annotations

import html as htmllib
import re
import unittest

import fixtures_filtered as ff
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, READ, hub_defaults

from zenux_dashboard import actions, filtered_view, labels
from zenux_dashboard.fmt import esc

REJECTED = PILOT_HUB + "/rejected"
MUTES = PILOT_HUB + "/mutes"


def fv_intro(view: str) -> str:
    return filtered_view.INTRO[view]


def truthy(value) -> bool:
    return str(value).lower() in ("1", "true")


def sent(call) -> dict:
    """A JSON body without the keys sent as null (an optional field may be omitted or sent as null)."""
    return {k: v for k, v in (call.body or {}).items() if v is not None}


class FilteredCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        self.http.on("GET", REJECTED, lambda call: ff.rejected_for(call.params or {}))
        self.http.on("GET", MUTES, ff.mutes())
        self.http.on("GET", PILOT_HUB + "/preferences", ff.preferences())
        self.http.on("GET", PILOT_HUB + "/mutes/preview", lambda call: ff.mute_preview(
            kind=call.params.get("kind"), ref=call.params.get("ref"), module=call.params.get("module"),
            label="Data Center Dynamics" if call.params.get("kind") == "source" else "CoreWeave"))
        self.http.on("GET", PILOT_HUB + "/stars/preview", ff.star_preview())

    def filtered(self, *, view: str | None = None, pin: str | None = None, state: dict | None = None):
        state = dict(state or {})
        if view:
            state["fo_view"] = view
        at = self.app(tab="filtered", pin=pin, state=state or None,
                      query={"tab": "filtered", **({"view": view} if view else {})})
        self.assert_clean(at)
        return at

    def reads(self) -> list:
        return self.http.find("GET", REJECTED)

    def last_read(self):
        reads = self.reads()
        self.assertTrue(reads, "no GET /rejected was sent")
        return reads[-1]

    def rows_shown(self, at) -> list[int]:
        """Event ids of the row cards on the page, in page order (from their container keys)."""
        out = []
        for node in self.walk(at._tree):
            key = getattr(node, "key", None) or ""
            match = re.fullmatch(r"zx_row_(\d+)", str(key))
            if match:
                out.append(int(match.group(1)))
        return out

    def show(self, at, view: str):
        at.segmented_control(key="fo_view").set_value(view).run()
        self.assert_clean(at)
        return at

    def count_line(self, at) -> str:
        html = self.html(at)
        match = re.search(r'<div class="rejected-summary">(.*?)</div>', html)
        self.assertIsNotNone(match, "no count line")
        return htmllib.unescape(match.group(1))

    def menu_click(self, at, row_key: str, button_key: str):
        """Click a button inside a row's lazy More popover: the popover is opened for the run that draws it and
        again for the run that clicks (AppTest keeps no popover state between runs)."""
        self.open_popover(at, f"zx_more_{row_key}")
        at.run()
        self.open_popover(at, f"zx_more_{row_key}")
        at.button(key=button_key).click().run()
        self.assert_clean(at)
        return at


class ViewTests(FilteredCase):
    def test_default_view_is_near_misses_best_score_first(self):
        at = self.filtered()
        self.assertEqual(at.segmented_control(key="fo_view").value, "near")
        call = self.last_read()
        self.assertEqual((call.params.get("filter"), int(call.params.get("days")), call.bearer), ("near_miss", 3, READ))
        self.assertFalse(truthy(call.params.get("include_auto", "")))
        self.assertNotIn("q", call.params)  # nothing typed: no search sent
        # 75, 64, 61, then the unknown score
        self.assertEqual(self.rows_shown(at), [7202, 7201, 7205, 7204])
        html = self.html(at)
        # the score and the bar in force for that run (gap 27)
        self.assertIn('<span class="rejected-chip score">Score 75 of 100 · bar 80</span>', html)
        self.assertIn('<span class="rejected-chip score">Score 64 of 100 · bar 70</span>', html)
        self.assertIn('<span class="rejected-chip">Cut for space</span>', html)
        self.assertEqual(self.count_line(at), "Showing 4 of 4 stories · last 3 days")
        self.assertIn(fv_intro("near"), self.texts(at, "caption"))
        self.assert_clean(at)

    def test_each_view_shows_its_true_count(self):
        at = self.filtered()
        control = at.segmented_control(key="fo_view")
        counts = ff.views()
        expected = [f"Near misses · {counts['near_miss']}", f"All · {counts['all_with_auto']}",
                    f"Same story · {counts['same_story']}", f"Muted · {counts['muted']}",
                    f"Old news · {counts['old_news']}"]
        self.assertEqual([getattr(o, "content", o) for o in control.options], expected)
        self.assert_clean(at)

    def test_the_view_stays_when_its_counts_change(self):
        grown = {"n": 0}

        def answer(call):
            body = ff.rejected_for(call.params or {})
            body["views"] = {**body["views"], "all_with_auto": body["views"]["all_with_auto"] + grown["n"]}
            return body

        self.http.on("GET", REJECTED, answer)
        at = self.filtered()
        self.show(at, "all")
        grown["n"] = 5  # new stories were filtered out meanwhile
        self.fresh()
        at.run()
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="fo_view").value, "all")
        self.assertIn(f"All · {ff.views()['all_with_auto'] + 5}",
                      [getattr(o, "content", o) for o in at.segmented_control(key="fo_view").options])

    def test_row_card_dateline_title_and_escaping(self):
        at = self.filtered()
        html = self.html(at)
        # the title is escaped and linked through safe_url
        self.assertIn("CoreWeave adds &lt;b&gt;Texas&lt;/b&gt; capacity", html)
        self.assertIn('href="https://example.com/story-7201"', html)
        # dateline: date · plain source name · coverage area; the source key never appears
        self.assertRegex(html, r'<div class="feed-dateline">[A-Z][a-z]{2} \d{1,2} · Data Center Dynamics · '
                               r'<span class="module-tag"[^>]*>AI INFRASTRUCTURE</span></div>')
        # a label that is only the source key falls back to the link's domain
        self.assertIn(" · breakingdefense.com · ", html)
        visible = self.visible_text(at)
        self.assertNotIn("breaking-defense", visible)
        for eid in (7201, 7202, 7204, 7205):
            self.assertNotIn(str(eid), visible)
        self.assert_clean(at)

    def test_all_view_reads_everything_newest_first(self):
        at = self.filtered()
        self.show(at, "all")
        call = self.last_read()
        self.assertEqual(call.params.get("filter"), "all")
        self.assertTrue(truthy(call.params.get("include_auto")))
        self.assertEqual(self.rows_shown(at), [7304, 7305, 7301, 7302, 7306, 7307, 7308, 7309, 7310, 7303])
        self.assertIn("Everything left out of your briefings, newest first.", self.visible_text(at))
        self.assertEqual(at.query_params.get("view"), "all")
        self.assert_clean(at)

    def test_plain_reason_labels_for_every_code(self):
        at = self.filtered()
        self.show(at, "all")
        html = self.html(at)
        for row in ff.all_rows():
            label = labels.reason_label(row["reason_code"], row.get("reason"))
            self.assertIn(f'<span class="rejected-chip">{esc(label)}</span>', html, row["reason_code"])
        self.assertIn('<span class="rejected-chip">Not confirmed by a reliable source</span>', html)  # no hub label
        self.assertIn('<span class="rejected-chip">Left out</span>', html)  # an unknown code
        visible = self.visible_text(at)
        for code in ("below_materiality", "out_of_scope", "insufficient_evidence", "brand_new_reason", "stale"):
            self.assertNotRegex(visible, rf"\b{code}\b")
        # hostile values stay inert
        self.assertIn("Drone &lt;script&gt;alert(1)&lt;/script&gt; unveiled at trade show", html)
        self.assertNotIn("javascript:", html)
        self.assert_clean(at)

    def test_same_story_view(self):
        at = self.filtered()
        self.show(at, "same")
        call = self.last_read()
        self.assertEqual(call.params.get("filter"), "same_story")
        self.assertFalse(truthy(call.params.get("include_auto", "")))
        # the hub's same-story view: duplicates and already-reported decisions, newest first
        self.assertEqual(self.rows_shown(at), [7302, 7306])
        html = self.html(at)
        briefing = ff.all_rows()[3]["canonical"]["briefing"]["briefing_label"]
        self.assertIn("Same story as: <strong>Neocloud signs 200 MW capacity deal with hyperscaler</strong>"
                      f" · in your {esc(briefing)}", html)
        self.assertIn("Same story as: <strong>Army award reported last week</strong></div>", html)
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/editions"), [])  # the hub names the story (gap 9)
        # Show it only where the repeated story's briefing is known; no Should have been in in this view
        keys = {getattr(b, "key", None) for b in at.button}
        self.assertIn("fo_show_7302", keys)
        self.assertNotIn("fo_show_7306", keys)
        self.assertFalse(any(str(k).startswith("act_promote_") for k in keys))
        at.button(key="fo_show_7302").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state["zx_tab"], "briefing")
        self.assertEqual((at.query_params.get("edition"), at.query_params.get("item")), ("12", "1201"))
        self.assert_clean(at)

    def test_muted_view_lists_mutes_and_what_they_hid(self):
        at = self.filtered(view="muted")
        call = self.last_read()
        self.assertEqual(call.params.get("filter"), "muted")
        mutes_call = self.http.find("GET", MUTES)[-1]
        self.assertTrue(truthy(mutes_call.params.get("all")))
        self.assertEqual(mutes_call.bearer, READ)
        html = self.html(at)
        visible = self.visible_text(at)
        self.assertIn("Your mutes", visible)
        self.assertIn(labels.STILL_COLLECTED, visible)
        self.assertIn('<div class="rules-section">Sources · 1</div>', html)
        self.assertIn('<div class="rules-section">Companies · 1</div>', html)
        self.assertIn("hid 12 this week (30 in all)", html)
        self.assertIn("Too noisy", html)
        self.assertRegex(html, r"since [A-Z][a-z]{2} \d{1,2} · hid 12 this week")
        keys = {getattr(b, "key", None) for b in at.button}
        self.assertTrue({"fo_unmute_4", "fo_unmute_5"} <= keys)
        self.assertFalse(any(str(k).startswith("fo_bring_back_") for k in keys))  # removed mutes stay closed
        self.assertIn("Removed mutes · 2", [e.label for e in at.expander])
        self.assertEqual(self.rows_shown(at), [7305, 7401, 7402])
        self.assertEqual(html.count('<span class="zx-chip chip-state chip-muted">Muted</span>'), 3)
        self.assertNotIn('<span class="rejected-chip">Muted by you</span>', html)  # said once, by the chip
        self.assertEqual(self.count_line(at), "Showing 3 of 3 stories · last 3 days")
        self.assert_clean(at)

    def test_the_mute_list_says_when_it_is_capped(self):
        body = ff.mutes()
        body.update(total=640, has_more=True)  # gap 17: the hub's true total
        self.http.on("GET", MUTES, body)
        at = self.filtered(view="muted")
        self.assertIn("The newest 4 of 640 mutes are listed.", self.texts(at, "caption"))
        self.http.on("GET", MUTES, ff.mutes())
        self.fresh()
        at = self.filtered(view="muted")
        self.assertFalse(any("are listed" in c for c in self.texts(at, "caption")))

    def test_old_news_view_excludes_mutes(self):
        at = self.filtered(view="old")
        self.assertEqual(self.last_read().params.get("filter"), "old_news")
        # the old-news rule and the editor's own old-news rejection; never a mute
        self.assertEqual(self.rows_shown(at), [7304, 7310])
        html = self.html(at)
        self.assertIn('<span class="rejected-chip">Old news</span>', html)
        self.assertIn('<span class="rejected-chip">Old news, reposted</span>', html)
        self.assertIn(fv_intro("old"), self.visible_text(at))
        self.assert_clean(at)

    def test_deep_link_selects_the_view(self):
        at = self.app(tab="filtered", query={"tab": "filtered", "view": "same"})
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="fo_view").value, "same")
        self.assertEqual(self.last_read().params.get("filter"), "same_story")
        bad = self.app(tab="filtered", query={"tab": "filtered", "view": "nope"})
        self.assert_clean(bad)
        self.assertEqual(bad.segmented_control(key="fo_view").value, "near")
        self.assert_clean(bad)

    def test_empty_states(self):
        self.http.on("GET", REJECTED, lambda call: ff.rejected_body([], filter=call.params.get("filter", "all")))
        cases = {"near": "No near misses in the last 3 days.", "all": "Nothing was left out in the last 3 days.",
                 "same": "No repeated stories in the last 3 days.",
                 "muted": "Your mutes hid nothing in the last 3 days.",
                 "old": "No old news was filtered out in the last 3 days."}
        at = self.filtered()
        for view, text in cases.items():
            self.show(at, view)
            self.assertIn(text, self.html(at), view)
        self.assertIn("Showing 0 of 0 stories · last 3 days", self.html(at))
        self.assert_clean(at)

    def test_read_error_shows_a_plain_error_box(self):
        self.http.on("GET", REJECTED, FakeResponse(500, {"error": "internal_error"}))
        at = self.filtered()
        visible = htmllib.unescape(self.visible_text(at))
        self.assertIn("Couldn't load filtered-out stories.", visible)
        self.assertIn("Try again", visible)
        self.assertNotIn("internal_error", visible)
        # the header stays, so the analyst can change view or days
        self.assertEqual(at.segmented_control(key="fo_view").value, "near")
        self.assert_clean(at)

    def test_malformed_rows_never_break_the_page(self):
        odd = [{"event_id": "abc", "title": None}, 7,
               {"event_id": 7501, "title": None, "score": "n/a", "feedback": "x", "subjects": "y", "rules": "z",
                "muted": 3, "requested": [], "decided_at": "soon", "module": None, "url": None},
               {"event_id": 7502, "decision": None, "reason_code": None, "reason": None, "score": True}]
        self.http.on("GET", REJECTED, {"items": odd, "total": "many"})
        at = self.filtered()
        self.assertEqual(self.rows_shown(at), [7502, 7501])  # unknown scores and times: newest id first
        self.assertIn("Untitled story", self.html(at))
        self.assertIn('<span class="rejected-chip">Left out</span>', self.html(at))
        for view in ("all", "same", "muted", "old"):
            self.show(at, view)
        self.open_expander(at, "zx_why_r7501")
        at.run()
        self.assert_clean(at)


class CountSearchFilterTests(FilteredCase):
    def test_true_totals_and_paging_past_the_first_500(self):
        self.http.on("GET", REJECTED, ff.many_rows(620))
        at = self.filtered()
        # near misses sort best first over the whole window: every page is read first, so the order is exact
        self.assertEqual(at.selectbox(key="fo_sort").value, "high")
        self.assertEqual(self.count_line(at), "Showing 50 of 620 stories · last 3 days")
        self.assertEqual([int(c.params.get("offset") or 0) for c in self.reads()], [0, 500])
        self.assertEqual(len(self.rows_shown(at)), 50)
        more = at.button(key="fo_more")
        self.assertEqual(more.label, "Show 50 more")
        more.click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.rows_shown(at)), 100)
        self.assertTrue(self.count_line(at).startswith("Showing 100 of 620 stories"))
        # newest first reads page by page: past the first page, Show 50 more reads the next one from the hub
        self.fresh()
        self.http.calls.clear()
        at.selectbox(key="fo_sort").set_value("newest").run()
        self.assert_clean(at)
        self.assertEqual([int(c.params.get("offset") or 0) for c in self.reads()], [0])
        at.session_state["fo_limit"] = (("pilot", "near", 3, "", "", "newest"), 500)
        at.run()
        at.button(key="fo_more").click().run()
        self.assert_clean(at)
        self.assertIn(500, [int(c.params.get("offset") or 0) for c in self.reads()])
        self.assertEqual(len(self.rows_shown(at)), 550)
        self.assertEqual(self.count_line(at), "Showing 550 of 620 stories · last 3 days")
        self.assert_clean(at)

    def test_sort_by_score(self):
        self.http.on("GET", REJECTED, ff.many_rows(620))
        at = self.filtered(view="all")
        self.assertEqual(at.selectbox(key="fo_sort").value, "newest")  # every view but near misses: newest first
        self.assertEqual(list(at.selectbox(key="fo_sort").options),
                         ["Newest first", "Highest score first", "Lowest score first"])
        for sort, first, last in (("high", 69, 69), ("low", 60, 60)):  # 62 stories score 69, 62 score 60
            at.selectbox(key="fo_sort").set_value(sort).run()
            self.assert_clean(at)
            scores = [int(m) for m in re.findall(r"Score (\d+) of 100", self.html(at))]
            shown = self.rows_shown(at)
            self.assertEqual(len(shown), 50)
            self.assertEqual(self.count_line(at), "Showing 50 of 620 stories · last 3 days")
            order = sorted(scores, reverse=sort == "high")
            self.assertEqual(scores, order, sort)
            self.assertEqual((scores[0], scores[-1]), (first, last), sort)
        # a new view starts in its own order
        at.segmented_control(key="fo_view").set_value("near").run()
        self.assert_clean(at)
        self.assertEqual(at.selectbox(key="fo_sort").value, "high")

    def test_unscored_stories_come_last_in_a_score_order(self):
        rows = [{"event_id": 1, "score": None}, {"event_id": 2, "score": 41}, {"event_id": 3, "score": 66}]
        self.assertEqual([r["event_id"] for r in filtered_view.view_rows("all", rows, "high")], [3, 2, 1])
        self.assertEqual([r["event_id"] for r in filtered_view.view_rows("all", rows, "low")], [2, 3, 1])
        self.assertEqual([r["event_id"] for r in filtered_view.view_rows("all", rows, "newest")], [1, 2, 3])
        self.assertEqual([r["event_id"] for r in filtered_view.view_rows("near", rows)], [3, 2, 1])

    def test_search_is_sent_to_the_hub(self):
        at = self.filtered()
        at.text_input(key="fo_search").input("coreweave").run()
        self.assert_clean(at)
        self.assertEqual(self.last_read().params.get("q"), "coreweave")  # the whole window is searched
        self.assertEqual(self.rows_shown(at), [7201])  # a subject company
        self.assertEqual(self.count_line(at), "1 story matches “coreweave” · last 3 days")
        at.text_input(key="fo_search").input("capacity figure").run()
        self.assertEqual(self.rows_shown(at), [7201])  # the editor's reasoning, every word
        at.text_input(key="fo_search").input("anduril").run()
        self.assertEqual(self.rows_shown(at), [7202])
        at.text_input(key="fo_search").input("zeppelin").run()
        self.assert_clean(at)
        self.assertEqual(self.rows_shown(at), [])
        self.assertIn("No filtered-out story matches your search.", self.html(at))
        self.assertEqual(self.count_line(at), "0 stories match “zeppelin” · last 3 days")
        self.assertIn("Headline, company or source", at.text_input(key="fo_search").placeholder)
        self.assert_clean(at)

    def test_days_and_area_filters_live_in_the_filters_popover(self):
        at = self.filtered()
        popover = self.popover_holding(at, "fo_days")
        self.assertIsNotNone(popover, "Days is not inside a popover")
        self.assertTrue(str(popover.proto.popover.label).startswith("Filters"))
        self.assertIs(self.popover_holding(at, "fo_area"), popover)
        self.assertEqual(list(at.selectbox(key="fo_days").options),
                         ["Last day", "Last 3 days", "Last 7 days", "Last 14 days", "Last 30 days"])
        self.assertEqual(list(at.selectbox(key="fo_area").options), ["All areas", "AI infrastructure",
                                                                     "Defense unmanned"])
        at.selectbox(key="fo_days").set_value(7).run()
        self.assert_clean(at)
        self.assertEqual(int(self.last_read().params.get("days")), 7)
        self.assertIn("· last 7 days", self.count_line(at))
        at.selectbox(key="fo_area").set_value("defense-unmanned").run()
        self.assert_clean(at)
        self.assertEqual(self.last_read().params.get("module"), "defense-unmanned")  # the hub narrows the area
        self.assertEqual(self.rows_shown(at), [7202])
        self.assertTrue(str(self.popover_holding(at, "fo_days").proto.popover.label).startswith("Filters · 2"))
        self.assert_clean(at)

    def test_choices_survive_a_visit_to_another_tab(self):
        at = self.filtered()
        self.show(at, "all")
        at.selectbox(key="fo_days").set_value(14).run()
        at.text_input(key="fo_search").input("miner").run()
        self.assertEqual(self.rows_shown(at), [7301])
        at.session_state["zx_tab"] = "briefing"
        at.run()
        self.assert_clean(at)
        at.session_state["zx_tab"] = "filtered"
        at.run()
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="fo_view").value, "all")
        self.assertEqual(at.selectbox(key="fo_days").value, 14)
        self.assertEqual(at.text_input(key="fo_search").value, "miner")
        self.assertEqual(self.rows_shown(at), [7301])
        self.assert_clean(at)

    def popover_holding(self, at, key: str):
        found = None
        for node in self.walk(at._tree):
            if getattr(node, "type", None) == "popover":
                if any(getattr(child, "key", None) == key for child in self.walk(node)):
                    found = node  # the innermost popover wins (walk is depth first)
        return found


class RowActionTests(FilteredCase):
    def test_a_row_a_later_briefing_published_says_so(self):
        # the hub keeps the earlier decision in GET /rejected after a later briefing took the story (a "Should have
        # been in" the editor then accepted) and says so in `published_later` (gap 24): the row offers Show it and
        # no second Should have been in
        def answer(call):
            body = ff.rejected_for(call.params or {})
            for row in body["items"]:
                if row["event_id"] == 7202:
                    row["published_later"] = {"edition_id": 12, "item_id": 1202, "headline": "Anduril wins",
                                              "published_at": ff.iso(1), **ff.briefing_name(ff.iso(1))}
            return body

        self.http.on("GET", REJECTED, answer)
        at = self.filtered(pin=PIN)
        html = self.html(at)
        card = html[html.index("Anduril wins drone order"):]
        self.assertIn('<span class="zx-chip chip-state chip-corrected">Later in your briefing</span>',
                      card[:card.index("</article>")])
        keys = {getattr(b, "key", None) for b in at.button}
        self.assertIn("fo_show_7202", keys)
        self.assertNotIn("act_promote_r7202", keys)
        self.assertIn("act_promote_r7201", keys)
        at.button(key="fo_show_7202").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state["zx_tab"], "briefing")
        self.assertEqual((at.query_params.get("edition"), at.query_params.get("item")), ("12", "1202"))
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/editions/12"), [])  # loaded with the first page

    def test_should_have_been_in_needs_a_note(self):
        self.http.on("POST", PILOT_HUB + "/promote", FakeResponse(201, ff.promoted()))
        at = self.filtered(pin=PIN)
        self.click(at, "act_promote_r7201")
        self.assert_clean(at)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/promote"), [])  # required note
        at.text_area(key="dlg_text").input("A big customer win for the region").run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/promote")[-1]
        self.assertEqual((post.bearer, sent(post)),
                         (OWNER, {"event_id": 7201, "note": "A big customer win for the region"}))
        self.assertTrue(any(t.startswith("Sent back to the ZENUX editor with your note.") for t in self.toasts(at)))
        self.assert_clean(at)

    def test_less_like_this_targets_the_event(self):
        self.http.on("POST", PILOT_HUB + "/preferences", FakeResponse(201, ff.preference_created()))
        at = self.filtered(pin=PIN)
        self.click(at, "act_less_r7201")
        self.assert_clean(at)
        scope = at.radio(key="dlg_scope")
        self.assertEqual(scope.value, "similar")
        self.assertIn(labels.SCOPE_LABELS["this_story"], list(scope.options))  # the row has a story
        at.text_input(key="dlg_text").input("capacity news without a megawatt figure").run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/preferences")[-1]
        self.assertEqual(post.bearer, OWNER)
        self.assertEqual(sent(post), {"direction": "less", "scope": "similar",
                                      "text": "capacity news without a megawatt figure", "event_id": 7201})
        self.assertTrue(any(t.startswith("Saved: Show me less like this.") for t in self.toasts(at)))
        self.assertEqual(at.session_state["zx_undo"].text, "Saved a preference.")
        self.assert_clean(at)

    def test_more_like_this_without_a_story(self):
        self.http.on("POST", PILOT_HUB + "/preferences", FakeResponse(201, ff.preference_created(direction="more")))
        at = self.filtered(pin=PIN)
        self.click(at, "act_more_r7204")
        self.assert_clean(at)
        options = list(at.radio(key="dlg_scope").options)
        self.assertEqual(len(options), 2)
        self.assertNotIn(labels.SCOPE_LABELS["this_story"], options)  # no story yet
        at.button(key="dlg_save").click().run()
        post = self.http.find("POST", PILOT_HUB + "/preferences")[-1]
        self.assertEqual(sent(post).get("event_id"), 7204)
        self.assertNotIn("item_id", sent(post))
        self.assertEqual(sent(post).get("direction"), "more")
        self.assert_clean(at)

    def test_mute_source_from_a_row(self):
        self.http.on("POST", MUTES, FakeResponse(201, ff.mute_added()))
        at = self.filtered(pin=PIN)
        self.open_popover(at, "zx_more_r7201")
        at.run()
        self.assertEqual(at.button(key="act_mute_source_r7201").label, "Mute source: Data Center Dynamics")
        self.menu_click(at, "r7201", "act_mute_source_r7201")
        preview = self.http.find("GET", PILOT_HUB + "/mutes/preview")[-1]
        self.assertEqual({k: preview.params.get(k) for k in ("kind", "module", "ref")},
                         {"kind": "source", "module": "ai-infra", "ref": "dcd"})
        self.assertIn("Would have hidden 42 stories in the last 7 days", self.html(at))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", MUTES)[-1]
        self.assertEqual((post.bearer, sent(post)),
                         (OWNER, {"action": "add", "kind": "source", "module": "ai-infra", "ref": "dcd"}))
        toast = next(t for t in self.toasts(at) if t.startswith("Muted Data Center Dynamics."))
        self.assertIn(labels.STILL_COLLECTED, toast)
        undo = at.session_state["zx_undo"]
        self.assertEqual(undo.text, "Muted Data Center Dynamics.")
        undo.run(OWNER)
        remove = self.http.find("POST", MUTES)[-1]
        self.assertEqual((remove.bearer, sent(remove)),
                         (OWNER, {"action": "remove", "mute_id": 21, "bring_back_days": 7}))
        self.assert_clean(at)

    def test_mute_a_company_from_a_row(self):
        self.http.on("POST", MUTES, FakeResponse(201, ff.mute_added(22, "entity", "coreweave", "CoreWeave", None)))
        at = self.filtered(pin=PIN)
        self.open_popover(at, "zx_more_r7201")
        at.run()
        self.assertEqual(at.button(key="act_mute_co_r7201_0").label, "Mute company: CoreWeave")
        self.menu_click(at, "r7201", "act_mute_co_r7201_0")
        preview = self.http.find("GET", PILOT_HUB + "/mutes/preview")[-1]
        self.assertEqual((preview.params.get("kind"), preview.params.get("ref")), ("entity", "coreweave"))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", MUTES)[-1]
        self.assertEqual((post.bearer, sent(post)), (OWNER, {"action": "add", "kind": "entity", "ref": "coreweave"}))
        # a starred company cannot be muted from its row
        self.open_popover(at, "zx_more_r7202")
        at.run()
        self.assertTrue(at.button(key="act_mute_co_r7202_0").disabled)
        self.assert_clean(at)

    def test_star_a_company_from_a_row(self):
        self.http.on("POST", PILOT_HUB + "/stars", FakeResponse(201, ff.star_added()))
        at = self.filtered(pin=PIN)
        self.menu_click(at, "r7201", "act_star_r7201_0")
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/stars/preview")[-1].params.get("entity"), "coreweave")
        self.assertIn("9 stories about CoreWeave in the last 7 days", self.html(at))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/stars")[-1]
        self.assertEqual((post.bearer, sent(post)), (OWNER, {"action": "add", "entity_id": "coreweave"}))
        self.assertTrue(any(t.startswith("CoreWeave is on your watchlist.") for t in self.toasts(at)))
        self.assert_clean(at)

    def test_rate_a_filtered_out_story(self):
        self.http.on("POST", PILOT_HUB + "/feedback", FakeResponse(201, ff.feedback_stored()))
        at = self.filtered(pin=PIN)
        self.click(at, "act_rate_r7201")  # beside Less like this, not in a menu
        self.assertEqual(at.radio(key="dlg_choice").value, "watch")
        self.assertIn(actions.RATE_SCALE_NOTE, self.visible_text(at))
        at.radio(key="dlg_choice").set_value("lead")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/feedback")[-1]
        body = sent(post)
        self.assertEqual((post.bearer, body.get("verdict"), body.get("event_id"), body.get("scope")),
                         (OWNER, "lead", 7201, "item"))
        self.assertNotIn("item_id", body)
        self.assertTrue(any(t.startswith("Rating saved.") for t in self.toasts(at)))
        self.assert_clean(at)

    def test_requested_and_rating_chips(self):
        at = self.filtered()
        html = self.html(at)
        self.assertIn('<span class="zx-chip chip-state chip-requested">You asked for this · re-checked at the next '
                      'briefing</span>', html)
        # the newest plain rating, not the "Should have been in" note stored after it
        self.assertIn('<span class="zx-chip grade">You rated it: Top story</span>', html)
        self.assertNotIn("You rated it: In the briefing", html)
        self.assertIn('<span class="zx-chip chip-state chip-starred">On your watchlist</span>', html)
        self.assert_clean(at)

    def test_unmute_sends_the_bring_back_choice(self):
        self.http.on("POST", MUTES, FakeResponse(200, ff.mute_removed(4, 12)))
        at = self.filtered(view="muted", pin=PIN)
        self.click(at, "fo_unmute_4")
        self.assert_clean(at)
        # the bring-back preview says how many stories would come back before anything is unmuted (gap 13)
        preview = self.http.find("GET", PILOT_HUB + "/mutes/bring-back-preview")[-1]
        self.assertEqual((preview.params.get("mute_id"), preview.params.get("days"), preview.bearer), (4, 7, READ))
        self.assertIn("12 stories it hid in the last 7 days would go back to the editor for the next briefing.",
                      self.visible_text(at))
        self.assertIn("Bring back what it hid in the last 7 days (12 stories)", list(at.radio(key="dlg_choice").options))
        self.assertEqual(at.radio(key="dlg_choice").value, 7)
        self.assert_plain(at)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", MUTES)[-1]
        self.assertEqual((post.bearer, sent(post)), (OWNER, {"action": "remove", "mute_id": 4, "bring_back_days": 7}))
        self.assertTrue(any(t.startswith(f"Unmuted {ff.SOURCE_MUTE_LABEL}.") and "12 stories" in t
                            for t in self.toasts(at)))
        self.http.on("POST", MUTES, FakeResponse(200, ff.mute_removed(5, 0)))
        self.click(at, "fo_unmute_5")
        at.radio(key="dlg_choice").set_value(0)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(sent(self.http.find("POST", MUTES)[-1]),
                         {"action": "remove", "mute_id": 5, "bring_back_days": 0})

    def test_bring_back_a_removed_mute(self):
        self.http.on("POST", MUTES, FakeResponse(200, ff.brought_back(6, 3)))
        at = self.filtered(view="muted", pin=PIN)
        self.open_expander(at, "fo_removed_mutes")
        at.run()
        self.assert_clean(at)
        keys = {getattr(b, "key", None) for b in at.button}
        self.assertIn("fo_bring_back_6", keys)
        self.assertNotIn("fo_bring_back_3", keys)  # already brought back
        self.assertIn("Brought back", self.texts(at, "caption"))
        self.assertIn("removed ", self.html(at))
        self.open_expander(at, "fo_removed_mutes")
        self.click(at, "fo_bring_back_6")
        self.assert_clean(at)
        post = self.http.find("POST", MUTES)[-1]
        self.assertEqual((post.bearer, sent(post)), (OWNER, {"action": "bring_back", "mute_id": 6, "days": 7}))
        self.assertTrue(any(t.startswith("Brought back what") for t in self.toasts(at)))
        self.assert_clean(at)

    def test_locked_controls_are_disabled_and_send_nothing(self):
        at = self.filtered()
        for key in ("act_more_r7201", "act_less_r7201", "act_promote_r7201"):
            button = at.button(key=key)
            self.assertTrue(button.disabled, key)
            self.assertEqual(button.help, labels.LOCKED_HELP)
        self.show(at, "muted")
        self.assertTrue(at.button(key="fo_unmute_4").disabled)
        self.assertEqual(self.http.posts(), [])
        self.assert_clean(at)


class WhyAndPlainWordsTests(FilteredCase):
    def test_why_on_a_near_miss(self):
        at = self.filtered()
        self.open_expander(at, "zx_why_r7201")
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Near miss · score 64 of 100", html)
        self.assertIn("Credible expansion but no capacity figure", html)
        self.assertNotIn("owner grade", html)
        self.assertNotIn("calibrated by your feedback", html)  # the Calibrated row says it
        self.assertNotIn("#9001", html)
        self.assertIn("The editor matched this to your earlier ratings.", html)
        # R-0012's words come with the row (rules_detail, gap 5): no GET /preferences lookup
        self.assertIn("Capacity announcements without a megawatt figure", html)
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/preferences"), [])
        self.assertNotIn("R-0012", self.visible_text(at))
        # the source's name and its group (lane_label, gap 26)
        self.assertIn('<span class="why-label">Source</span><span>Data Center Dynamics · Trade press</span>', html)
        self.assert_clean(at)

    def test_why_says_when_a_should_have_been_in_was_asked(self):
        at = self.filtered()
        self.open_expander(at, "zx_why_r7205")
        at.run()
        self.assert_clean(at)
        self.assertRegex(self.html(at), r"Should have been in: “Big customer” \(asked [A-Z][a-z]{2} \d{1,2}\)")

    def test_why_on_automatic_rows(self):
        at = self.filtered(view="all")
        self.open_expander(at, "zx_why_r7304")
        self.open_expander(at, "zx_why_r7305")
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Filtered automatically", html)
        self.assertIn("Published Aug 1, 2026, 63 days before Oct 3, 2026; older than the 21-day freshness line.",
                      html)  # the hub's plain words (rationale_plain)
        self.assertNotIn("stale_backlog", html)
        self.assertIn(f"Muted by you</span><span>{esc(ff.SOURCE_MUTE_LABEL)}", html)
        self.assert_clean(at)

    def test_jargon_guard_with_every_menu_open(self):
        self.more_menu_on()
        for view, rows in (("near", ff.near_rows()), ("all", ff.all_rows()), ("same", ff.same_rows()),
                           ("muted", ff.muted_rows()), ("old", ff.old_rows())):
            state = {}
            for row in rows:
                state[f"zx_why_r{row['event_id']}"] = True
                state[f"zx_more_r{row['event_id']}"] = True
            state["fo_removed_mutes"] = True
            at = self.filtered(view=view, pin=PIN, state=state)
            self.assert_plain(at)
            self.assert_no_secrets(at)
            self.assert_clean(at)


if __name__ == "__main__":
    unittest.main()
