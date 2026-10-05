"""WF5 final fixes, end to end on the Briefing (AppTest) and in the pure helpers: the outlet behind a news-search story
(AW-1), what the analyst already said about a story (AW-2), the Remove confirmation (AW-3), the locked line (AW-4),
the tiles under Everything notable (AW-8), the stylesheet fixes (AW-9, AW-15, AW-5), "Not about" a look-alike name
(AW-10), a link without https:// (AW-13) and the capped watchlist shelf (SA-2)."""

from __future__ import annotations

import re
import unittest

import fixtures_briefing as fb
from helpers import DASHBOARD, AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, hub_defaults
from zenux_dashboard import actions, api, feed_view, preferences_view, radar_view

EDITIONS = PILOT_HUB + "/editions"
PREFERENCES = PILOT_HUB + "/preferences"
MUTES = PILOT_HUB + "/mutes"
STARS = PILOT_HUB + "/stars"


def esc_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#x27;").replace(
        '"', "&quot;")


class Case(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        self.http.on("GET", EDITIONS, fb.editions(1))
        self.http.on("GET", PREFERENCES, fb.preferences())
        self.http.on("GET", MUTES, fb.mutes())
        self.http.on("GET", MUTES + "/preview", lambda call: fb.mute_preview(call.params.get("kind", "source")))
        self.http.on("GET", STARS + "/preview", fb.star_preview())

    def briefing(self, *, pin: str | None = PIN, popover: str | None = None):
        at = self.app(pin=pin, run=False)
        if popover:
            self.open_popover(at, popover)
        at.run()
        self.assert_clean(at)
        return at

    def sent(self, url: str):
        posts = self.http.find("POST", url)
        self.assertTrue(posts, f"nothing was sent to {url}")
        self.assertEqual(posts[-1].bearer, OWNER)
        return posts[-1].body


def news_search_editions() -> dict:
    """The first story came from a news-search source; its record names Yahoo Finance as the outlet."""
    body = fb.editions(1)
    item = body["editions"][0]["items"][0]
    item["why"]["source"] = dict(item["why"]["source"], label="News search: AI deals", publisher="Yahoo Finance",
                                 publisher_domain="finance.yahoo.com")
    return body


class OutletTests(Case):
    def test_the_outlet_is_named_and_can_be_muted_alone(self):
        self.http.on("GET", EDITIONS, news_search_editions())
        self.http.on("POST", MUTES, FakeResponse(201, fb.mute_added(7, kind="outlet")))
        at = self.briefing(popover="zx_more_i1201")
        self.assertIn('<div class="feed-dateline">Oct 2 · Yahoo Finance via News search: AI deals</div>', self.html(at))
        self.assertEqual(at.button(key="act_mute_outlet_i1201").label, "Mute outlet: Yahoo Finance")
        self.assertEqual(at.button(key="act_mute_source_i1201").label, "Mute every outlet in News search: AI deals")
        self.click(at, "act_mute_outlet_i1201")
        self.assert_clean(at)
        preview = self.http.find("GET", MUTES + "/preview")[-1]
        self.assertEqual(preview.params, {"kind": "outlet", "ref": "finance.yahoo.com", "event_id": 9001})
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.sent(MUTES), {"action": "add", "kind": "outlet", "ref": "finance.yahoo.com"})

    def test_a_source_that_is_the_outlet_itself_offers_no_outlet_mute(self):
        at = self.briefing(popover="zx_more_i1201")
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("act_mute_outlet_")], [])
        self.assertEqual(at.button(key="act_mute_source_i1201").label, "Mute source: CoreWeave newsroom")


class AlreadySaidTests(Case):
    """WF5 AW-2, as icons (docs/SPEC-ICON-ACTIONS.md): what the analyst already said about a story is a glowing thumb,
    and a click on it undoes it; there is no "You asked for ..." chip, Undo or Change on the card any more."""

    def editions_with_a_preference(self, direction: str = "less", status: str = "active") -> dict:
        body = fb.editions(1)
        body["editions"][0]["items"][0]["why"]["my_preferences"] = [
            {"id": "I-0002", "direction": direction, "direction_label": f"Show me {direction} like this",
             "scope": "similar", "status": status}]
        return body

    def test_the_glowing_thumb_says_what_you_asked_and_undoes_it(self):
        self.http.on("GET", EDITIONS, self.editions_with_a_preference())
        self.http.on("POST", PILOT_HUB + "/rules/I-0002/retire", fb.retired("I-0002"))
        at = self.briefing()
        self.assertEqual(at.button(key="act_less_i1201").proto.type, "primary")
        self.assertEqual(at.button(key="act_more_i1201").proto.type, "tertiary")
        self.assertNotIn("zx-asked", self.html(at))
        self.assertNotIn("You asked for less like this", self.visible_text(at))
        at.button(key="act_less_i1201").click().run()
        self.assert_clean(at)
        self.assertEqual(self.sent(PILOT_HUB + "/rules/I-0002/retire"), {"reason": "undone"})
        self.assertTrue(any(t.startswith("Undone: less like this. Stops applying from the ") for t in self.toasts(at)),
                        self.toasts(at))
        self.assertEqual(self.http.find("POST", PREFERENCES), [])

    def test_ctrl_click_opens_the_options_set_to_replace_the_first(self):
        self.http.on("GET", EDITIONS, self.editions_with_a_preference())
        self.http.on("POST", PREFERENCES, FakeResponse(201, dict(fb.preference_created("I-0003"), replaced=["I-0002"])))
        at = self.briefing()
        self.click(at, "act_morefull_i1201")  # a Ctrl+click on thumb up, while thumb down glows
        self.assert_clean(at)
        self.assertIn(actions.CHANGE_REPLACES, self.texts(at, "warning"))
        self.assertEqual(at.button(key="dlg_save").label, "Replace it")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.sent(PREFERENCES), {"direction": "more", "scope": "similar", "item_id": 1201,
                                                  "replace": True})
        self.assertTrue(any("It replaces your earlier one on this story." in t for t in self.toasts(at)))

    def test_a_preference_the_page_did_not_show_still_asks_to_replace_it(self):
        # the hub knows of a preference the page has not drawn yet: its sentence opens the options, set to replace
        sentence = "You already asked for less like this on this story. Replace it with more like this?"

        def answer(call):
            if call.body.get("replace") is True:
                return FakeResponse(201, dict(fb.preference_created("I-0003"), replaced=["I-0002"]))
            return FakeResponse(409, {"error": "preference_exists", "message": sentence,
                                      "existing": [{"id": "I-0002", "direction": "less"}]})

        self.http.on("POST", PREFERENCES, answer)
        at = self.briefing()
        self.click(at, "act_more_i1201")
        self.assert_clean(at)
        self.assertNotIn("replace", self.http.find("POST", PREFERENCES)[-1].body)
        self.assertIn(sentence, self.texts(at, "warning"))
        self.assertEqual(at.button(key="dlg_save").label, "Replace it")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIs(self.sent(PREFERENCES)["replace"], True)

    def test_a_click_the_other_way_switches_in_one_click(self):
        self.http.on("GET", EDITIONS, self.editions_with_a_preference())
        self.http.on("POST", PREFERENCES, FakeResponse(201, dict(fb.preference_created("I-0003"), replaced=["I-0002"])))
        at = self.briefing()
        self.click(at, "act_more_i1201")
        self.assert_clean(at)
        self.assertEqual(self.sent(PREFERENCES), {"direction": "more", "scope": "similar", "item_id": 1201,
                                                  "replace": True})
        self.assertNotIn("dlg_save", [b.key for b in at.button])  # no dialog
        self.assertTrue(any(t.startswith("Switched to more like this. Applies from") for t in self.toasts(at)),
                        self.toasts(at))

    def test_a_paused_preference_glows_and_undoes_too(self):
        self.http.on("GET", EDITIONS, self.editions_with_a_preference("more", "paused"))
        self.http.on("POST", PILOT_HUB + "/rules/I-0002/retire", fb.retired("I-0002"))
        at = self.briefing()
        self.assertEqual(at.button(key="act_more_i1201").proto.type, "primary")
        self.click(at, "act_more_i1201")
        self.assert_clean(at)
        self.assertEqual(self.sent(PILOT_HUB + "/rules/I-0002/retire"), {"reason": "undone"})

    def test_no_undo_or_change_on_the_card(self):
        # phones and tablets: a tap saves or undoes; the options for a preference are on My preferences
        self.http.on("GET", EDITIONS, self.editions_with_a_preference())
        at = self.briefing()
        keys = [str(b.key) for b in at.button]
        self.assertEqual([k for k in keys if k.startswith(("act_undo_pref_", "act_change_pref_"))], [])
        self.assertNotIn("Change", [b.label for b in at.button])


class LockedAndTilesTests(Case):
    def test_locked_briefing_says_how_to_edit(self):
        at = self.briefing(pin=None)
        self.assertIn(f'<div class="zx-locked">{esc_text(feed_view.BRIEFING_LOCKED)}</div>', self.html(at))
        at = self.briefing()
        self.assertNotIn(feed_view.BRIEFING_LOCKED, self.html(at))

    def test_also_notable_counts_every_other_scored_story(self):
        body = fb.editions(1)
        body["editions"][0]["selection"].update(volume="broad", min_score=60)
        second = body["editions"][0]["items"][1]
        second["score"] = 63
        second["why"]["score"] = 63
        self.http.on("GET", EDITIONS, body)
        at = self.briefing()
        self.assertIn('<div class="stat stat-medium"><div class="stat-n">1</div><div class="stat-l">ALSO NOTABLE</div>',
                      self.html(at))


class ShelfTests(Case):
    def editions_with_a_long_watchlist(self, n: int = 8) -> dict:
        body = fb.editions(1)
        star = [{"entity_id": "lambda", "name": "Lambda"}]
        body["editions"][0]["shelves"] = {"watchlist": [fb.shelf_row(1400 + i, f"Story {i}", 20 + i, stars=star)
                                                        for i in range(n)], "near_misses": None}
        return body

    def test_a_long_watchlist_shelf_shows_five_and_the_rest_on_demand(self):
        self.http.on("GET", EDITIONS, self.editions_with_a_long_watchlist())
        at = self.briefing()
        html = self.html(at)
        self.assertIn('<div class="shelf-title">On your watchlist · not in this briefing · 8</div>', html)
        promote = [b.key for b in at.button if str(b.key).startswith("br_promote_")]
        self.assertEqual(promote, [f"br_promote_0_watchlist_{1400 + i}" for i in (7, 6, 5, 4, 3)], "best score first")
        self.assertIn("Show all 8", [e.label for e in at.expander])

    def test_not_about_a_look_alike_company(self):
        self.http.on("GET", EDITIONS, self.editions_with_a_long_watchlist(1))
        self.http.on("POST", STARS, {"reported": True, "created": True, "entity_id": "lambda", "event_id": 1400,
                                     "label": "Lambda", "effective": fb.effective()})
        at = self.briefing()
        button = at.button(key="br_not_about_0_1400_0")
        self.assertEqual(button.label, "Not about Lambda")
        button.click().run()
        self.assert_clean(at)
        self.assertEqual(self.sent(STARS), {"action": "not_about", "entity_id": "lambda", "event_id": 1400})
        self.assertIn(actions.NOT_ABOUT_TOAST.format(name="Lambda"), self.toasts(at))
        at.button(key="zx_undo_run").click().run()
        self.assert_clean(at)
        self.assertEqual(self.sent(STARS), {"action": "is_about", "entity_id": "lambda", "event_id": 1400})


class HelperTests(unittest.TestCase):
    def test_remove_confirmation_names_the_preference(self):
        pref = {"id": "I-0002", "direction": "less", "text": "Show me less like this: stories like this example.",
                "example": {"title": "The Hidden Failure Domain in N+1 Data Center Cooling"}}
        self.assertEqual(preferences_view.remove_detail(pref),
                         "Remove “Show me less like this: Stories like this example. (Example: The Hidden Failure Domain "
                         "in N+1 Data Center Cooling)”?")
        more = dict(pref, direction="more")
        self.assertNotEqual(preferences_view.remove_detail(more), preferences_view.remove_detail(pref))

    def test_a_link_copied_without_https_gets_it(self):
        self.assertEqual(api.with_scheme("www.utilitydive.com"), "https://www.utilitydive.com")
        self.assertEqual(api.with_scheme("utilitydive.com/news/x?a=1"), "https://utilitydive.com/news/x?a=1")
        self.assertEqual(api.with_scheme("http://a.example"), "http://a.example")
        self.assertEqual(api.with_scheme("not a link"), "not a link")
        self.assertEqual(api.with_scheme(""), "")
        self.assertIsNone(radar_view.validate("source", "Utility Dive news on data center power deals",
                                              api.with_scheme("www.utilitydive.com")))

    def test_stylesheet(self):
        css = (DASHBOARD / "feed.css").read_text(encoding="utf-8")
        # AW-15: menus fit a phone and their items line up on the left; AW-4: disabled labels stay readable
        self.assertIn('[data-testid="stPopoverBody"] { max-width: min(calc(100vw - 16px), calc(100% - 16px)) !important;',
                      css)
        self.assertIn('[data-testid="stPopoverBody"] button:disabled p { color: var(--zx-muted) !important; }', css)
        self.assertRegex(css, r'stBaseButton-tertiary"\]\) \{ justify-content: flex-start !important; text-align: left')
        self.assertIn('.stApp button:disabled, [data-testid="stPopoverBody"] button:disabled { opacity: 1;', css)
        self.assertIn('div[role="dialog"]:not([data-testid="stPopoverBody"]) { width: 100vw', css)  # dialogs only
        self.assertNotIn("opacity: .45", css)
        # AW-5: the Undo bar floats in view
        self.assertTrue(re.search(r"\.st-key-zx_undo \{ position: fixed !important;[^}]*bottom: 16px", css))


if __name__ == "__main__":
    unittest.main()
