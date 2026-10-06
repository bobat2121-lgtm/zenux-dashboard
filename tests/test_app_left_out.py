"""AppTest: what was left out, on the Briefing (docs/SPEC-SIMPLIFY.md 2.2): "Left out of this briefing · N" (lazy: GET
/rejected?edition_id=N only once opened; three groups by score, 10 rows and "Show N more"; the automatic caption with a
way to the mutes), the shared left-out row (title, dateline, one reason chip, the story icons with the up arrow, Show
it, the lazy Why with the score and the bar) and the search's "Left out · N" group (GET /rejected?q=&days=90, 20 rows
and Show more). The Filtered out tab is gone; its row actions are tested here on the rows that replaced it."""

from __future__ import annotations

import re
import unittest

import fixtures_briefing as fb
import fixtures_leftout as fl
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, READ, hub_defaults

from zenux_dashboard import actions, labels, left_out
from zenux_dashboard.fmt import esc

EDITIONS = PILOT_HUB + "/editions"
REJECTED = PILOT_HUB + "/rejected"
OPEN = "zx_leftout_open_12"  # the latest briefing's left-out expander


def sent(call) -> dict:
    """A JSON body without the keys sent as null."""
    return {k: v for k, v in (call.body or {}).items() if v is not None}


class LeftOutCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        self.http.on("GET", EDITIONS, fl.editions_v11())
        self.http.on("GET", REJECTED, lambda call: fl.rejected_for(call.params or {}))
        self.http.on("GET", PILOT_HUB + "/preferences", fl.preferences())
        self.http.on("GET", PILOT_HUB + "/mutes", fl.mutes())

    def briefing(self, *, pin: str | None = None, opened: bool = True, state: dict | None = None):
        extra = {OPEN: True} if opened else {}
        extra.update(state or {})
        at = self.app(pin=pin, state=extra)
        self.assert_clean(at)
        return at

    def edition_reads(self) -> list:
        return [c for c in self.http.find("GET", REJECTED) if (c.params or {}).get("edition_id") is not None]

    def rows_shown(self, at, prefix: str = "l12") -> list[int]:
        """Event ids of the left-out rows on the page whose key starts with prefix, in page order."""
        out = []
        for node in self.walk(at._tree):
            match = re.fullmatch(rf"zx_row_{prefix}[a-z]?_(\d+)", str(getattr(node, "key", None) or ""))
            if match:
                out.append(int(match.group(1)))
        return out

    def row_markdown(self, at, key: str) -> str:
        for node in self.walk(at._tree):
            if getattr(node, "key", None) == f"zx_row_{key}":
                return "\n".join(str(m.value) for m in self.walk(node) if getattr(m, "type", "") == "markdown")
        self.fail(f"no row {key}")

    def group_titles(self, at) -> list[str]:
        return re.findall(r'<div class="zx-group-title">(.*?)</div>', self.html(at))


class SectionTests(LeftOutCase):
    def test_the_section_is_collapsed_and_reads_nothing_until_opened(self):
        at = self.briefing(opened=False)
        self.assertIn("Left out of this briefing · 19", [e.label for e in at.expander])
        self.assertEqual(self.edition_reads(), [])  # lazy
        self.assertNotIn("Near misses · 4", self.html(at))
        self.open_expander(at, OPEN)
        at.run()
        self.assert_clean(at)
        call = self.edition_reads()[-1]
        self.assertEqual((call.params, call.bearer), ({"filter": "all", "edition_id": 12}, READ))  # no days
        # the older briefing (an older hub's shape: no left_out) has no section and reads nothing
        self.assertEqual({c.params.get("edition_id") for c in self.edition_reads()}, {12})
        self.assertEqual(sum(1 for e in at.expander if e.label.startswith("Left out of this briefing")), 1)

    def test_three_groups_by_score_ten_rows_and_show_more(self):
        at = self.briefing()
        self.assertEqual(self.group_titles(at), ["Near misses · 4", f"Below your bar · {fl.BELOW_BAR_ROWS}",
                                                 "Same story as one in your briefings · 2"])
        shown = self.rows_shown(at)
        self.assertEqual(shown[:4], [7202, 7201, 7205, 7204])  # best score first, the unscored one last
        self.assertEqual(shown[4:14], [7500 + n for n in range(10)])  # 10 rows of a group, best first
        self.assertEqual(shown[14:], [7302, 7306])
        more = at.button(key="lo_more_12_below_bar")
        self.assertEqual(more.label, f"Show {fl.BELOW_BAR_ROWS - 10} more")
        self.open_expander(at, OPEN)
        more.click().run()
        self.assert_clean(at)
        self.assertEqual(self.rows_shown(at)[4:4 + fl.BELOW_BAR_ROWS], [7500 + n for n in range(12)] + [7301])
        self.assertEqual([b.key for b in at.button if b.key == "lo_more_12_below_bar"], [])
        self.assertEqual(len(self.edition_reads()), 1)  # Show more reads nothing new
        self.assert_plain(at)

    def test_the_automatic_caption_and_the_way_to_the_mutes(self):
        at = self.briefing()
        self.assertIn('<div class="zx-leftout-auto">Kept out before the editor read them: 4 muted, 12 old news.</div>',
                      self.html(at))
        self.open_expander(at, OPEN)
        at.button(key="lo_mutes_12").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state["zx_tab"], "tuning")
        self.assertEqual(at.query_params.get("rules"), "muted")
        self.assertEqual(at.pills(key="tn_rules").value, "muted")  # Tuning opens on the mutes

    def test_no_mutes_no_way_to_them(self):
        self.http.on("GET", EDITIONS, fl.editions_v11(left_out=fl.left_out(muted=0, old=3)))
        at = self.briefing()
        self.assertIn("Kept out before the editor read them: 0 muted, 3 old news.", self.html(at))
        self.assertEqual([b.key for b in at.button if b.key == "lo_mutes_12"], [])

    def test_nothing_left_out_draws_nothing(self):
        self.http.on("GET", EDITIONS, fl.editions_v11(left_out=fl.left_out(total=0, muted=0, old=0)))
        at = self.briefing()
        self.assertFalse(any(e.label.startswith("Left out of this briefing") for e in at.expander))
        self.assertEqual(self.edition_reads(), [])

    def test_an_older_hub_has_no_section(self):
        self.http.on("GET", EDITIONS, fb.editions())  # no left_out, no tuning
        at = self.briefing()
        self.assertFalse(any(e.label.startswith("Left out of this briefing") for e in at.expander))
        self.assertEqual(self.http.find("GET", REJECTED), [])
        self.assertNotIn("Your tuning here", self.html(at))

    def test_a_failed_read_is_said_plainly(self):
        self.http.on("GET", REJECTED, FakeResponse(500, {"error": "internal_error"}))
        at = self.briefing()
        text = self.visible_text(at)
        self.assertIn("Couldn't load what this briefing left out.", text)
        self.assertIn("Something went wrong on the server.", text)
        self.assertIsNotNone(at.button(key="zx_retry_leftout_12"))
        self.http.on("GET", REJECTED, FakeResponse(404, {"error": "unknown_edition", "message": "No edition 12."}))
        self.fresh()
        at = self.briefing()
        self.assertIn("That briefing is no longer available.", self.visible_text(at))
        self.assert_plain(at)


class SharedRowTests(LeftOutCase):
    def test_title_dateline_one_chip_and_no_score(self):
        at = self.briefing()
        row = self.row_markdown(at, "l12n_7201")
        self.assertIn("CoreWeave adds &lt;b&gt;Texas&lt;/b&gt; capacity", row)
        self.assertIn('href="https://example.com/story-7201"', row)
        self.assertRegex(row, r'<div class="feed-dateline">[A-Z][a-z]{2} \d{1,2} · Data Center Dynamics · '
                              r'<span class="module-tag"[^>]*>AI INFRASTRUCTURE</span></div>')
        self.assertIn('<div class="rejected-signals"><span class="rejected-chip">Near miss</span></div>', row)
        self.assertNotIn("Score", self.html(at))  # the score and the bar are in Why
        # a label that is only the source key falls back to the link's domain
        self.assertIn(" · breakingdefense.com · ", self.row_markdown(at, "l12n_7202"))
        visible = self.visible_text(at)
        self.assertNotIn("breaking-defense", visible)
        for eid in (7201, 7202, 7204, 7205):
            self.assertNotIn(str(eid), visible)
        # the icons: thumbs, star and the up arrow (Should have been in) on a rejection, never on a repeat
        keys = {getattr(b, "key", None) for b in at.button}
        self.assertTrue({"act_more_l12n_7201", "act_less_l12n_7201", "act_rate_l12n_7201",
                         "act_promote_l12n_7201"} <= keys)
        self.assertIn("act_rate_l12s_7302", keys)
        self.assertNotIn("act_promote_l12s_7302", keys)

    def test_same_story_rows_name_the_story_and_show_it(self):
        at = self.briefing()
        briefing = fl.all_rows()[3]["canonical"]["briefing"]["briefing_label"]
        self.assertIn("Same story as: <strong>Neocloud signs 200 MW capacity deal with hyperscaler</strong>"
                      f" · in your {esc(briefing)}", self.row_markdown(at, "l12s_7302"))
        self.assertIn("Same story as: <strong>Army award reported last week</strong></div>",
                      self.row_markdown(at, "l12s_7306"))
        keys = {getattr(b, "key", None) for b in at.button}
        self.assertIn("lo_show_l12s_7302", keys)
        self.assertNotIn("lo_show_l12s_7306", keys)  # its briefing is not known
        self.open_expander(at, OPEN)
        at.button(key="lo_show_l12s_7302").click().run()
        self.assert_clean(at)
        self.assertEqual((at.query_params.get("edition"), at.query_params.get("item")), ("12", "1201"))

    def test_a_row_a_later_briefing_published_says_so(self):
        def answer(call):
            body = fl.rejected_for(call.params or {})
            for row in body["items"]:
                if row["event_id"] == 7202:
                    row["published_later"] = {"edition_id": 12, "item_id": 1202, "headline": "Anduril wins",
                                              "published_at": fl.iso(1), **fl.briefing_name(fl.iso(1))}
            return body

        self.http.on("GET", REJECTED, answer)
        at = self.briefing(pin=PIN)
        self.assertIn('<span class="zx-chip chip-state chip-corrected">Later in your briefing</span>',
                      self.row_markdown(at, "l12n_7202"))
        self.assertNotIn("Cut for space", self.row_markdown(at, "l12n_7202"))  # one chip
        keys = {getattr(b, "key", None) for b in at.button}
        self.assertIn("lo_show_l12n_7202", keys)
        self.assertNotIn("act_promote_l12n_7202", keys)  # no second Should have been in
        self.open_expander(at, OPEN)
        at.button(key="lo_show_l12n_7202").click().run()
        self.assert_clean(at)
        self.assertEqual((at.query_params.get("edition"), at.query_params.get("item")), ("12", "1202"))

    def test_should_have_been_in_needs_a_note(self):
        self.http.on("POST", PILOT_HUB + "/promote", FakeResponse(201, fl.promoted()))
        at = self.briefing(pin=PIN)
        self.open_expander(at, OPEN)
        self.click(at, "act_promote_l12n_7201")
        self.assert_clean(at)
        self.assertEqual(at.text_area(key="dlg_text").label, actions.PROMOTE_LABEL)
        at.button(key="dlg_save").click().run()
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/promote"), [])  # required note
        at.text_area(key="dlg_text").input("A big customer win for the region").run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/promote")[-1]
        self.assertEqual((post.bearer, sent(post)), (OWNER, {"event_id": 7201, "note": "A big customer win for the region"}))
        self.assertTrue(any(t.startswith("Sent back to the ZENITH editor with your note.") for t in self.toasts(at)))

    def test_a_plain_click_saves_and_ctrl_click_opens_the_options(self):
        self.http.on("POST", PILOT_HUB + "/preferences", FakeResponse(201, fl.preference_created()))
        at = self.briefing(pin=PIN)
        self.open_expander(at, OPEN)
        self.click(at, "act_less_l12n_7201")
        self.assert_clean(at)
        post = self.http.find("POST", PILOT_HUB + "/preferences")[-1]
        self.assertEqual((post.bearer, sent(post)), (OWNER, {"direction": "less", "scope": "similar", "event_id": 7201}))
        self.assertTrue(any(t.startswith("Saved: Show me less like this.") for t in self.toasts(at)))
        self.open_expander(at, OPEN)
        self.click(at, "act_morefull_l12n_7204")  # the hidden twin a Ctrl+click lands on
        options = list(at.radio(key="dlg_scope").options)
        self.assertNotIn(labels.SCOPE_LABELS["this_story"], options)  # no story yet
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(sent(self.http.find("POST", PILOT_HUB + "/preferences")[-1]),
                         {"direction": "more", "scope": "similar", "event_id": 7204})

    def test_rate_a_left_out_story(self):
        self.http.on("POST", PILOT_HUB + "/feedback", FakeResponse(201, fl.feedback_stored()))
        at = self.briefing(pin=PIN)
        self.open_expander(at, OPEN)
        self.click(at, "act_rate_l12n_7201")
        self.assertEqual(at.radio(key="dlg_choice").value, "watch")
        at.radio(key="dlg_choice").set_value("lead")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        body = sent(self.http.find("POST", PILOT_HUB + "/feedback")[-1])
        self.assertEqual((body.get("verdict"), body.get("event_id"), body.get("scope")), ("lead", 7201, "item"))
        self.assertNotIn("item_id", body)

    def test_the_glow_withdraws_the_rating_and_the_request(self):
        self.http.on("POST", PILOT_HUB + "/feedback/withdraw", {"withdrawn": [11], "effective": fl.effective()})
        self.http.on("POST", PILOT_HUB + "/promote/withdraw", {"cancelled": True, "already_reconsidered": False,
                                                               "withdrawn": [12], "effective": fl.effective()})
        at = self.briefing(pin=PIN)
        self.assertEqual({k: at.button(key=k).proto.type for k in ("act_promote_l12n_7205", "act_rate_l12n_7205",
                                                                    "act_promote_l12n_7201", "act_rate_l12n_7201")},
                         {"act_promote_l12n_7205": "primary", "act_rate_l12n_7205": "primary",
                          "act_promote_l12n_7201": "tertiary", "act_rate_l12n_7201": "tertiary"})
        self.assertEqual(at.button(key="act_promote_l12n_7205").help,
                         "You asked for it to be in your briefing. Click to withdraw the request.")
        self.open_expander(at, OPEN)
        self.click(at, "act_rate_l12n_7205")
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/feedback/withdraw")[-1].body, {"event_id": 7205})
        self.assertIn(actions.RATING_WITHDRAWN, self.toasts(at))
        self.open_expander(at, OPEN)
        self.click(at, "act_promote_l12n_7205")
        self.assertEqual(self.http.find("POST", PILOT_HUB + "/promote/withdraw")[-1].body, {"event_id": 7205})
        self.assertEqual(self.toasts(at), ["Request withdrawn."])

    def test_why_holds_the_score_the_bar_and_the_reasons(self):
        at = self.briefing(state={"zx_why_l12n_7201": True})
        html = self.html(at)
        self.assertIn("Near miss · score 64 of 100 · bar 70", html)
        self.assertIn("Credible expansion but no capacity figure", html)
        self.assertNotIn("calibrated by your feedback", html)  # the Calibrated row says it
        self.assertNotIn("#9001", html)
        self.assertIn("The editor matched this to your earlier ratings.", html)
        self.assertIn("Capacity announcements without a megawatt figure", html)  # rules_detail: no lookup
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/preferences")[-1].params, {})
        self.assertIn('<span class="why-label">Source</span><span>Data Center Dynamics · Trade press</span>', html)
        self.assertNotIn("R-0012", self.visible_text(at))
        self.assertEqual(at.button(key="why_pref_l12n_7201_0").label, "See it in Tuning")
        at = self.briefing(state={"zx_why_l12n_7205": True})
        self.assertRegex(self.html(at), r"Should have been in: “Big customer” \(asked [A-Z][a-z]{2} \d{1,2}\)")

    def test_locked_icons_are_disabled_and_send_nothing(self):
        at = self.briefing()
        for key, words in (("act_more_l12n_7201", "More like this."), ("act_less_l12n_7201", "Less like this."),
                           ("act_rate_l12n_7201", "Rate this story."), ("act_promote_l12n_7201", "Should have been in.")):
            button = at.button(key=key)
            self.assertTrue(button.disabled, key)
            self.assertEqual(button.help, f"{words} {labels.LOCKED_HELP}")
        self.assertEqual(self.http.posts(), [])

    def test_every_why_open_is_plain(self):
        state = {f"zx_why_l12{left_out.group_of(r)[0]}_{r['event_id']}": True for r in fl.edition_rows()}
        at = self.briefing(pin=PIN, state=state)
        self.assert_plain(at)
        self.assert_no_secrets(at)


class SearchGroupTests(LeftOutCase):
    def many(self, total: int = 45):
        rows = [fl.row(20_000 + i, score=69 - (i % 10), title=f"Grid story number {i}", hours=1 + i)
                for i in range(total)]

        def answer(call):
            params = call.params or {}
            if params.get("q"):
                limit = int(params.get("limit") or 500)
                body = fl.rejected_body(rows)
                body.update(items=rows[:limit], total=total, returned=min(limit, total), has_more=limit < total)
                return body
            return fl.rejected_for(params)
        return answer

    def test_two_groups_and_the_left_out_reads(self):
        self.http.on("GET", REJECTED, self.many())
        at = self.briefing(opened=False)
        at.text_input(key="br_search").set_value("grid").run()
        self.assert_clean(at)
        self.assertEqual(self.group_titles(at), ["In your briefings · 0", "Left out · 45"])
        call = [c for c in self.http.find("GET", REJECTED) if (c.params or {}).get("q")][-1]
        self.assertEqual((call.params, call.bearer), ({"days": 90, "filter": "all", "q": "grid", "limit": 20}, READ))
        self.assertEqual(len(self.rows_shown(at, "q")), 20)
        at.button(key="lo_search_more").click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.rows_shown(at, "q")), 40)
        self.assertEqual([c.params.get("limit") for c in self.http.find("GET", REJECTED) if (c.params or {}).get("q")][-1],
                         40)
        self.assert_plain(at)

    def test_matches_in_both_groups(self):
        at = self.briefing(opened=False)
        at.text_input(key="br_search").set_value("miner").run()
        self.assert_clean(at)
        titles = self.group_titles(at)
        self.assertEqual(titles[0], "In your briefings · 0")
        self.assertEqual(titles[1], "Left out · 1")
        self.assertEqual(self.rows_shown(at, "q"), [7301])
        self.assertIn("act_promote_q_7301", {getattr(b, "key", None) for b in at.button})
        at.text_input(key="br_search").set_value("anduril").run()
        self.assert_clean(at)
        self.assertEqual(self.group_titles(at), ["In your briefings · 2", "Left out · 0"])
        self.assertIn(left_out.SEARCH_NONE, self.html(at))

    def test_a_failed_left_out_search_is_said(self):
        self.http.on("GET", REJECTED, lambda call: FakeResponse(500, {"error": "x"}) if (call.params or {}).get("q")
                     else fl.rejected_for(call.params or {}))
        at = self.briefing(opened=False)
        at.text_input(key="br_search").set_value("grid").run()
        self.assert_clean(at)
        self.assertIn("Couldn't search what was left out: Something went wrong on the server.", self.texts(at, "caption"))


class ShelfTests(LeftOutCase):
    def test_shelves_use_the_shared_row(self):
        body = fl.editions_v11()
        body["editions"][0]["shelves"] = fb.with_shelves()["editions"][0]["shelves"]
        self.http.on("GET", EDITIONS, body)
        at = self.briefing(pin=PIN, opened=False)
        html = self.html(at)
        self.assertIn('<div class="shelf"><div class="shelf-title">On your watchlist · not in this briefing</div></div>',
                      html)
        self.assertIn('<div class="shelf"><div class="shelf-title">Near misses · just under your bar</div></div>', html)
        keys = {getattr(b, "key", None) for b in at.button}
        for key in ("w0_1300", "n0_1301", "n0_1302"):
            self.assertTrue({f"act_more_{key}", f"act_less_{key}", f"act_rate_{key}", f"act_promote_{key}"} <= keys, key)
        self.assertIn("lo_not_about_w0_1300_0", keys)  # a watchlist row keeps "Not about <company>"
        self.assertEqual(at.button(key="lo_not_about_w0_1300_0").label, "Not about CoreWeave")
        self.assertNotIn("lo_not_about_n0_1301_0", keys)
        self.assertNotIn("Should have been in", [b.label for b in at.button if "promote" in str(b.key)
                                                 and b.proto.type != "tertiary"])
        # the bar in force for that briefing goes into Why
        at = self.briefing(pin=PIN, opened=False, state={"zx_why_n0_1301": True})
        self.assertIn("Near miss · score 66 of 100 · bar 70", self.html(at))


if __name__ == "__main__":
    unittest.main()
