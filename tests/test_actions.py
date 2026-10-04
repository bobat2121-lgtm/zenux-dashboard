"""AppTest: the card actions on Briefing stories (docs/SPEC-PHASE03-UI.md 5.4), end to end: the button, the dialog,
the exact write (method, URL, owner bearer, JSON body), the toast, and the undo. Also the lock: every action is drawn
disabled with "Unlock to edit" and nothing is sent while locked."""

from __future__ import annotations

import unittest
from datetime import timedelta

import fixtures as fx
import fixtures_briefing as fb
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, hub_defaults
from zenux_dashboard import actions, labels, ui
from zenux_dashboard.fmt import fmt_clock

EDITIONS = PILOT_HUB + "/editions"
PREFERENCES = PILOT_HUB + "/preferences"
FEEDBACK = PILOT_HUB + "/feedback"
MUTES = PILOT_HUB + "/mutes"
STARS = PILOT_HUB + "/stars"
PROMOTE = PILOT_HUB + "/promote"
TZ = "America/New_York"


class ActionCase(AppCase):
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

    def last_post(self, url: str):
        posts = self.http.find("POST", url)
        self.assertTrue(posts, f"nothing was sent to {url}")
        return posts[-1]

    def assert_sent(self, url: str, body: dict) -> None:
        post = self.last_post(url)
        self.assertEqual((post.bearer, post.body), (OWNER, body))

    def assert_dialog_closed(self, at) -> None:
        self.assertIsNone(at.session_state["zx_dialog"] if "zx_dialog" in at.session_state else None)
        self.assertEqual([b.key for b in at.button if b.key == "dlg_save"], [])

    def undo(self, at):
        return at.session_state["zx_undo"] if "zx_undo" in at.session_state else None

    def click_undo(self, at):
        button = next(b for b in at.button if b.label == "Undo")
        button.click().run()
        self.assert_clean(at)
        return at


class PreferenceTests(ActionCase):
    def test_more_like_this(self):
        answer = fb.preference_created("R-0013")
        self.http.on("POST", PREFERENCES, FakeResponse(201, answer))
        at = self.briefing()
        self.click(at, "act_more_i1201")
        self.assert_clean(at)
        scope = at.radio(key="dlg_scope")
        self.assertEqual(scope.value, "similar")
        self.assertEqual(list(scope.options), [labels.SCOPE_LABELS[s] for s in ("this_story", "similar", "standing")])
        text = at.text_input(key="dlg_text")
        self.assertEqual((text.label, text.placeholder), ("In a few words, what about it? (optional)",
                                                          "e.g. production orders for small drones"))
        self.assertIn(actions.ACTIVE_AT_ONCE, self.texts(at, "caption"))
        text.input("production orders for small drones")
        at.checkbox(key="dlg_until_on").check().run()
        until = ui.local_today(TZ) + timedelta(days=10)
        self.assertEqual(at.date_input(key="dlg_until").value, ui.local_today(TZ) + timedelta(days=30))  # default
        at.date_input(key="dlg_until").set_value(until)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(PREFERENCES, {"direction": "more", "scope": "similar",
                                       "text": "production orders for small drones", "item_id": 1201,
                                       "expires_at": ui.local_midnight_iso(until, TZ)})
        toast = f"Saved: Show me more like this. {ui.effective_text(answer['effective'], TZ)}"
        self.assertIn(toast, self.toasts(at))
        self.assertTrue(toast.startswith("Saved: Show me more like this. Applies from ") and toast.endswith(" briefing."))
        self.assert_dialog_closed(at)
        undo = self.undo(at)
        self.assertEqual((undo.text, undo.done), ("Saved a preference.", "Preference removed."))
        self.http.on("POST", PILOT_HUB + "/rules/R-0013/retire", fb.retired())
        self.click_undo(at)
        self.assert_sent(PILOT_HUB + "/rules/R-0013/retire", {"reason": "undone"})
        self.assertIn("Preference removed.", self.toasts(at))

    def test_less_like_this_without_a_story(self):
        self.http.on("POST", PREFERENCES, FakeResponse(201, fb.preference_created("R-0014")))
        at = self.briefing()
        self.click(at, "act_less_i1202")  # this story has not been in a briefing as a story yet: no story id
        self.assert_clean(at)
        scope = at.radio(key="dlg_scope")
        self.assertEqual(list(scope.options), [labels.SCOPE_LABELS[s] for s in ("similar", "standing")])
        self.assertIn(actions.NO_STORY_YET, self.texts(at, "caption"))
        self.assertEqual(at.text_input(key="dlg_text").placeholder, "e.g. stock-move articles with no new facts")
        scope.set_value("standing")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(PREFERENCES, {"direction": "less", "scope": "standing", "item_id": 1202})
        self.assertTrue(any(t.startswith("Saved: Show me less like this. Applies from") for t in self.toasts(at)))

    def test_just_this_story(self):
        self.http.on("POST", PREFERENCES, FakeResponse(201, fb.preference_created()))
        at = self.briefing()
        self.click(at, "act_less_i1201")
        at.radio(key="dlg_scope").set_value("this_story")
        at.text_input(key="dlg_text").input("more of the same deal")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(PREFERENCES, {"direction": "less", "scope": "this_story", "text": "more of the same deal",
                                       "item_id": 1201})

    def test_a_refusal_keeps_the_dialog_open(self):
        sentence = "This story has not been in a briefing yet; choose 'Stories like this'."
        self.http.on("POST", PREFERENCES, FakeResponse(400, {"error": "no_story", "message": sentence}))
        at = self.briefing()
        self.click(at, "act_more_i1201")
        at.radio(key="dlg_scope").set_value("this_story")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. " + sentence, self.texts(at, "error"))
        self.assertTrue(any(b.key == "dlg_save" for b in at.button))
        self.assertEqual(self.toasts(at), [])
        self.assertIsNone(self.undo(at))

    def test_cancel_sends_nothing(self):
        at = self.briefing()
        self.click(at, "act_more_i1201")
        at.button(key="dlg_cancel").click().run()
        self.assert_clean(at)
        self.assert_dialog_closed(at)
        self.assertEqual(self.http.posts(), [])

    def test_an_item_without_an_id(self):
        body = fb.editions(1)
        for item in body["editions"][0]["items"]:
            item.pop("id")
        self.http.on("GET", EDITIONS, body)
        self.http.on("POST", PREFERENCES, FakeResponse(201, fb.preference_created()))
        self.http.on("POST", FEEDBACK, FakeResponse(201, fb.feedback_stored()))
        at = self.briefing(popover="zx_more_e12r1")
        keys = {b.key for b in at.button}
        self.assertIn("act_rate_e12r1", keys)
        self.assertNotIn("act_wrong_e12r1", keys)  # Wrong facts needs the briefing item
        self.click(at, "act_more_e12r1")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(PREFERENCES, {"direction": "more", "scope": "similar", "event_id": 9001})
        self.open_popover(at, "zx_more_e12r1")
        at.run()
        self.click(at, "act_rate_e12r1")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(FEEDBACK, {"verdict": "digest", "scope": "item", "edition_id": 12, "item_rank": 1})


class FeedbackTests(ActionCase):
    def test_wrong_facts(self):
        answer = fb.feedback_stored(correction_id=7)
        self.http.on("POST", FEEDBACK, FakeResponse(201, answer))
        at = self.briefing(popover="zx_more_i1201")
        self.click(at, "act_wrong_i1201")
        self.assert_clean(at)
        self.assertEqual(at.text_area(key="dlg_text").label, actions.WRONG_FACTS_LABEL)
        self.assertIn(labels.NO_UNDO, self.texts(at, "caption"))
        at.text_area(key="dlg_text").input("Too short")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", FEEDBACK), [])  # a sentence is required
        self.assertIn(actions.WRONG_FACTS_SHORT, self.texts(at, "warning"))
        at.text_area(key="dlg_text").input("The term is 12 years, not 15 years.")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(FEEDBACK, {"verdict": "factual_error", "scope": "item", "item_id": 1201,
                                    "note": "The term is 12 years, not 15 years."})
        clock = fmt_clock(answer["effective"]["next_briefing_at"], TZ)
        self.assertIn(f"Flagged. The ZENUX editor re-checks it at the {clock} briefing and either corrects it or "
                      "explains why it stands.", self.toasts(at))
        self.assertIsNone(self.undo(at))
        self.assert_dialog_closed(at)

    def test_wrong_facts_without_a_known_time(self):
        self.assertEqual(actions.wrong_facts_toast({"effective": {"next_briefing_at": None}}, TZ),
                         "Flagged. The ZENUX editor re-checks it at the next briefing and either corrects it or "
                         "explains why it stands.")

    def test_rate_this_story(self):
        self.http.on("POST", FEEDBACK, FakeResponse(201, fb.feedback_stored()))
        at = self.briefing()
        self.click(at, "act_rate_i1202")  # beside Less like this, not in a menu
        self.assert_clean(at)
        choice = at.radio(key="dlg_choice")
        self.assertEqual(choice.value, "digest")
        self.assertEqual(list(choice.options), ["Top story", "In the briefing", "Near miss", "Not relevant"])
        # the slider sits under the note, in the rating's band, with the editor's score and the scale beside it
        self.assertEqual(at.slider(key="dlg_score").value, actions.RATING_SCORES["digest"])
        self.assertEqual((at.slider(key="dlg_score").min, at.slider(key="dlg_score").max), (0, 100))
        self.assertIn("The ZENUX editor scored it 78.", self.texts(at, "caption"))
        self.assertIn(actions.RATE_SCALE_NOTE, self.texts(at, "caption"))
        scale = next(str(m.value) for m in at.markdown if 'class="why-block score-scale"' in str(m.value))
        for span, name, meaning in actions.SCORE_SCALE:
            self.assertIn(f"{span} · {name}", scale)
            self.assertIn(meaning, scale)
        # a rating moves the slider into its band; the score is only sent when the analyst moved the slider
        choice.set_value("reject").run()
        self.assertEqual(at.slider(key="dlg_score").value, actions.RATING_SCORES["reject"])
        at.text_input(key="dlg_text").input("Old news for us")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(FEEDBACK, {"verdict": "reject", "scope": "item", "item_id": 1202, "note": "Old news for us"})
        self.assertIn("Rating saved. " + labels.RATING_HONEST, self.toasts(at))
        self.assertIsNone(self.undo(at))

    def test_the_slider_picks_the_rating_and_sends_the_score(self):
        self.http.on("POST", FEEDBACK, FakeResponse(201, fb.feedback_stored()))
        at = self.briefing()
        self.click(at, "act_rate_i1202")
        for score, verdict in ((93, "lead"), (64, "watch"), (12, "reject"), (77, "digest"), (90, "lead")):
            at.slider(key="dlg_score").set_value(score).run()
            self.assert_clean(at)
            self.assertEqual(at.radio(key="dlg_choice").value, verdict, score)
            self.assertEqual(at.slider(key="dlg_score").value, score)  # the rating never moves a score in its band
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(FEEDBACK, {"verdict": "lead", "scope": "item", "item_id": 1202, "score": 90})
        self.assertIn("Rating saved with your score of 90. " + labels.RATING_HONEST, self.toasts(at))

    def test_should_have_been_in_from_a_shelf(self):
        self.http.on("GET", EDITIONS, fb.with_shelves())
        answer = fb.promoted()
        self.http.on("POST", PROMOTE, FakeResponse(201, answer))
        at = self.briefing()
        self.click(at, "br_promote_0_near_1301")
        self.assert_clean(at)
        self.assertIn("Left out: Near miss", self.texts(at, "caption"))
        self.assertEqual(at.text_area(key="dlg_text").label, actions.PROMOTE_LABEL)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", PROMOTE), [])  # the note is required
        self.assertIn(actions.PROMOTE_SHORT, self.texts(at, "warning"))
        at.text_area(key="dlg_text").input("Capital for capacity matters to me")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(PROMOTE, {"event_id": 1301, "note": "Capital for capacity matters to me"})
        self.assertIn(f"Sent back to the ZENUX editor with your note. {ui.effective_text(answer['effective'], TZ)} "
                      "It may still stay out if the evidence is thin.", self.toasts(at))
        self.assertIsNone(self.undo(at))

    def test_should_have_been_in_refused(self):
        self.http.on("GET", EDITIONS, fb.with_shelves())
        self.http.on("POST", PROMOTE, FakeResponse(409, {"error": "already_in_briefing",
                                                         "message": "This story is already in a briefing."}))
        at = self.briefing()
        self.click(at, "br_promote_0_watchlist_1300")
        at.text_area(key="dlg_text").input("It is about CoreWeave")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. This story is already in a briefing.", self.texts(at, "error"))
        self.assertTrue(any(b.key == "dlg_save" for b in at.button))

    def test_promote_is_not_offered_on_a_briefing_story(self):
        at = self.briefing(popover="zx_more_i1201")
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("act_promote_")], [])


class MuteTests(ActionCase):
    def test_mute_source(self):
        self.http.on("POST", MUTES, FakeResponse(201, fb.mute_added(4)))
        at = self.briefing(popover="zx_more_i1201")
        button = at.button(key="act_mute_source_i1201")
        self.assertEqual(button.label, "Mute source: CoreWeave newsroom")
        button.click().run()
        self.assert_clean(at)
        preview = self.http.find("GET", MUTES + "/preview")[-1]
        # WF5 AW-14: the story the menu was opened from leads the preview's examples
        self.assertEqual(preview.params, {"kind": "source", "module": "ai-infra", "ref": "ent-coreweave-1", "event_id": 9001})
        html = self.html(at)
        self.assertIn("Would have hidden 42 stories in the last 7 days; 1 was in your briefing; 3 were official records.",
                      html)
        self.assertIn('<div class="why-row"><span>CoreWeave adds a &lt;site&gt; · Oct 2 · CoreWeave newsroom</span>'
                      '<span class="zx-chip chip-state chip-flagged">in your briefing</span></div>', html)
        self.assertIn(labels.STILL_COLLECTED, self.visible_text(at))
        self.assertIn(actions.UNMUTE_ANY_TIME, self.texts(at, "caption"))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(MUTES, {"action": "add", "kind": "source", "module": "ai-infra", "ref": "ent-coreweave-1"})
        self.assertIn("Muted CoreWeave newsroom. Still collected, kept out of your briefing. 30 waiting stories were set "
                      "aside now.", self.toasts(at))
        undo = self.undo(at)
        self.assertEqual((undo.text, undo.done), ("Muted CoreWeave newsroom.",
                                                  "Unmuted. The stories it hid this week come back."))
        self.http.on("POST", MUTES, FakeResponse(200, fb.mute_removed(4, 30)))
        self.click_undo(at)
        self.assert_sent(MUTES, {"action": "remove", "mute_id": 4, "bring_back_days": 7})
        self.assertIn("Unmuted. The stories it hid this week come back.", self.toasts(at))

    def test_a_menu_item_closes_the_more_menu_before_its_dialog_opens(self):
        # otherwise the open popover is drawn over the dialog and hides its buttons
        at = self.briefing(popover="zx_more_i1201")
        self.click(at, "act_mute_source_i1201")
        self.assert_clean(at)
        self.assertIs(at.session_state["zx_more_i1201"], False)
        self.assertEqual(at.session_state["zx_dialog"]["name"], "mute")
        self.assertIn("dlg_save", [b.key for b in at.button])

    def test_a_mute_that_already_existed_has_no_undo(self):
        self.http.on("POST", MUTES, FakeResponse(200, fb.mute_added(4, created=False, applied_now=0)))
        at = self.briefing(popover="zx_more_i1201")
        self.click(at, "act_mute_source_i1201")
        at.text_input(key="dlg_text").input("Too many hiring posts")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(MUTES, {"action": "add", "kind": "source", "module": "ai-infra", "ref": "ent-coreweave-1",
                                 "note": "Too many hiring posts"})
        self.assertIn("Muted CoreWeave newsroom. Still collected, kept out of your briefing.", self.toasts(at))
        self.assertIsNone(self.undo(at))

    def test_already_muted_offers_no_button(self):
        self.http.on("GET", MUTES + "/preview", fb.mute_preview(already=True))
        at = self.briefing(popover="zx_more_i1201")
        self.click(at, "act_mute_source_i1201")
        self.assert_clean(at)
        self.assertIn("Already muted.", self.texts(at, "info"))
        self.assertEqual([b.key for b in at.button if b.key == "dlg_save"], [])

    def test_a_failing_preview_still_offers_the_mute(self):
        self.http.on("GET", MUTES + "/preview", FakeResponse(500, {"error": "internal"}))
        self.http.on("POST", MUTES, FakeResponse(201, fb.mute_added(4)))
        at = self.briefing(popover="zx_more_i1201")
        self.click(at, "act_mute_source_i1201")
        self.assert_clean(at)
        self.assertTrue(any(c.startswith("Couldn't load the 7-day preview. Something went wrong on the server.")
                            for c in self.texts(at, "caption")))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.http.find("POST", MUTES)), 1)

    def test_mute_company_only_for_subjects(self):
        self.http.on("POST", MUTES, FakeResponse(201, fb.mute_added(5, kind="entity")))
        at = self.briefing(popover="zx_more_i1201")
        company_keys = sorted(b.key for b in at.button if str(b.key).startswith("act_mute_co_i1201_"))
        self.assertEqual(company_keys, ["act_mute_co_i1201_0", "act_mute_co_i1201_1"])  # the two subjects only
        self.assertEqual(at.button(key="act_mute_co_i1201_0").label, "Mute company: CoreWeave")
        starred = at.button(key="act_mute_co_i1201_1")
        self.assertEqual((starred.label, starred.disabled, starred.help),
                         ("Mute company: Microsoft", True, "Microsoft is on your watchlist. Remove the star first."))
        self.click(at, "act_mute_co_i1201_0")
        self.assert_clean(at)
        preview = self.http.find("GET", MUTES + "/preview")[-1]
        self.assertEqual(preview.params, {"kind": "entity", "ref": "coreweave", "event_id": 9001})
        self.assertIn(actions.COMPANY_MUTE_RULE, self.visible_text(at))  # WF5 AW-7: the rule is said
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(MUTES, {"action": "add", "kind": "entity", "ref": "coreweave"})
        self.assertTrue(any(t.startswith("Muted CoreWeave. " + labels.STILL_COLLECTED) for t in self.toasts(at)))

    def test_mute_company_refused_while_starred(self):
        sentence = "CoreWeave is on your watchlist. Remove the star first."
        self.http.on("POST", MUTES, FakeResponse(409, {"error": "company_starred", "message": sentence}))
        at = self.briefing(popover="zx_more_i1201")
        self.click(at, "act_mute_co_i1201_0")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. " + sentence, self.texts(at, "error"))

    def test_unmute_a_muted_company(self):
        self.http.on("POST", MUTES, FakeResponse(200, fb.mute_removed(6, 4)))
        self.http.on("GET", MUTES + "/bring-back-preview", fx.bring_back_preview(6, 4))
        at = self.briefing(popover="zx_more_i1202")
        button = at.button(key="act_mute_co_i1202_0")
        self.assertEqual(button.label, "Unmute company: Anduril")
        star = at.button(key="act_star_i1202_0")
        self.assertEqual((star.label, star.disabled, star.help),
                         ("Star Anduril", True, "Anduril is muted. Unmute it first."))
        button.click().run()
        self.assert_clean(at)
        choice = at.radio(key="dlg_choice")
        self.assertEqual(choice.value, 7)
        # the bring-back preview counts what would come back before anything is unmuted (gap 13)
        self.assertEqual(list(choice.options), ["Bring back what it hid in the last 7 days (4 stories)",
                                                "Only from now on"])
        self.assertIn("4 stories it hid in the last 7 days would go back to the editor for the next briefing.",
                      self.visible_text(at))
        self.assertEqual(self.http.find("GET", MUTES + "/bring-back-preview")[-1].params, {"mute_id": 6, "days": 7})
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(MUTES, {"action": "remove", "mute_id": 6, "bring_back_days": 7})
        self.assertIn("Unmuted Anduril. 4 stories come back for the editor to look at.", self.toasts(at))
        undo = self.undo(at)
        self.assertEqual((undo.text, undo.done), ("Unmuted Anduril.", "Muted again."))
        self.http.on("POST", MUTES, FakeResponse(201, fb.mute_added(7, kind="entity")))
        self.click_undo(at)
        self.assert_sent(MUTES, {"action": "add", "kind": "entity", "ref": "anduril"})

    def test_unmute_from_now_on(self):
        self.http.on("POST", MUTES, FakeResponse(200, fb.mute_removed(6, 0)))
        at = self.briefing(popover="zx_more_i1202")
        self.click(at, "act_mute_co_i1202_0")
        at.radio(key="dlg_choice").set_value(0)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(MUTES, {"action": "remove", "mute_id": 6, "bring_back_days": 0})
        self.assertIn("Unmuted Anduril.", self.toasts(at))

    def test_mute_this_story(self):
        self.http.on("POST", MUTES, FakeResponse(201, fb.mute_added(8, kind="story")))
        at = self.briefing(popover="zx_more_i1201")
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("act_mute_story_")], ["act_mute_story_i1201"])
        self.click(at, "act_mute_story_i1201")
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", MUTES + "/preview")[-1].params, {"kind": "story", "ref": "s-100"})
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(MUTES, {"action": "add", "kind": "story", "ref": "s-100"})
        # the toast is Markdown, so the headline's control characters are escaped (fmt.md_label)
        self.assertTrue(any(t.startswith("Muted “CoreWeave signs 200 MW \\<capacity\\> deal with Microsoft”. ")
                            for t in self.toasts(at)))

    def test_no_story_mute_without_a_story(self):
        at = self.briefing(popover="zx_more_i1202")
        self.assertEqual([b.key for b in at.button if str(b.key).startswith("act_mute_story_")], [])


class StarTests(ActionCase):
    def test_star_a_company(self):
        self.http.on("POST", STARS, FakeResponse(201, fb.star_added()))
        at = self.briefing(popover="zx_more_i1201")
        self.assertEqual(at.button(key="act_star_i1201_0").label, "Star CoreWeave")
        self.click(at, "act_star_i1201_0")
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", STARS + "/preview")[-1].params, {"entity": "coreweave"})
        self.assertIn("9 stories about CoreWeave in the last 7 days; 2 were in your briefing.", self.html(at))
        self.assertIn(labels.STAR_PROMISE, self.texts(at, "caption"))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_sent(STARS, {"action": "add", "entity_id": "coreweave"})
        self.assertIn(f"CoreWeave is on your watchlist. {labels.STAR_PROMISE}", self.toasts(at))
        undo = self.undo(at)
        self.assertEqual((undo.text, undo.done), ("Added CoreWeave to your watchlist.", "Removed from your watchlist."))
        self.http.on("POST", STARS, FakeResponse(200, fb.star_removed()))
        self.click_undo(at)
        self.assert_sent(STARS, {"action": "remove", "entity_id": "coreweave"})

    def test_remove_from_watchlist(self):
        self.http.on("POST", STARS, FakeResponse(200, fb.star_removed()))
        at = self.briefing(popover="zx_more_i1201")
        button = at.button(key="act_unstar_i1201_1")
        self.assertEqual(button.label, "Remove Microsoft from watchlist")
        button.click().run()
        self.assert_clean(at)
        self.assert_sent(STARS, {"action": "remove", "entity_id": "microsoft"})
        self.assertIn("Microsoft removed from your watchlist.", self.toasts(at))
        undo = self.undo(at)
        self.assertEqual(undo.text, "Removed Microsoft from your watchlist.")
        self.http.on("POST", STARS, FakeResponse(201, fb.star_added()))
        self.click_undo(at)
        self.assert_sent(STARS, {"action": "add", "entity_id": "microsoft"})


class HubTextTests(ActionCase):
    """WF3 review CR-4 and CR-5: hub text in Markdown places, and a menu write's failure."""

    def dialog_titles(self, at) -> list[str]:
        return [n.proto.dialog.title for n in self.walk(at._tree) if getattr(n, "type", "") == "dialog"]

    def test_dollar_amounts_and_markdown_in_a_headline_stay_literal(self):
        body = fb.editions(1)
        body["editions"][0]["items"][0]["headline"] = "Neocloud wins $11.9B deal; *shares* jump $5"
        body["editions"][0]["items"][0]["why"]["subjects"][1]["name"] = "Micro_soft [AI]"
        self.http.on("GET", EDITIONS, body)
        self.http.on("POST", MUTES, FakeResponse(201, fb.mute_added(8, kind="story")))
        at = self.briefing(popover="zx_more_i1201")
        labels_shown = [b.label for b in at.button]
        self.assertIn("Remove Micro\\_soft \\[AI\\] from watchlist", labels_shown)
        self.click(at, "act_mute_story_i1201")
        self.assert_clean(at)
        self.assertEqual(self.dialog_titles(at), ["Mute “Neocloud wins \\$11.9B deal; \\*shares\\* jump \\$5”?"])
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertTrue(any(t.startswith("Muted “Neocloud wins \\$11.9B deal; \\*shares\\* jump \\$5”. ")
                            for t in self.toasts(at)), self.toasts(at))

    def test_a_failed_remove_from_watchlist_is_said_in_a_toast(self):
        # the write runs in the menu item's callback: an error drawn there would land above the masthead
        self.http.on("POST", STARS, FakeResponse(404, {"error": "unknown_star",
                                                      "message": "Microsoft is not on your watchlist."}))
        at = self.briefing(popover="zx_more_i1201")
        at.button(key="act_unstar_i1201_1").click().run()
        self.assert_clean(at)
        self.assertEqual(self.texts(at, "error"), [])
        self.assertIn("Not saved. Microsoft is not on your watchlist.", self.toasts(at))
        self.http.on("POST", STARS, FakeResponse(503, {"error": "internal_error"}))
        self.open_popover(at, "zx_more_i1201")
        at.run()
        at.button(key="act_unstar_i1201_1").click().run()
        self.assertIn("Not saved. Something went wrong on the server. Try again in a minute.", self.toasts(at))
        self.assertEqual(self.texts(at, "error"), [])
        self.assert_plain(at)


class LockTests(ActionCase):
    def test_every_action_is_disabled_while_locked(self):
        body = fb.with_shelves()
        self.http.on("GET", EDITIONS, body)
        at = self.briefing(pin=None, popover="zx_more_i1201")
        for key in ("act_more_i1201", "act_less_i1201", "act_wrong_i1201", "act_rate_i1201", "act_mute_source_i1201",
                    "act_mute_co_i1201_0", "act_star_i1201_0", "act_unstar_i1201_1", "act_mute_story_i1201",
                    "br_promote_0_near_1301"):
            with self.subTest(key=key):
                button = at.button(key=key)
                self.assertTrue(button.disabled)
                self.assertEqual(button.help, labels.LOCKED_HELP)
        self.assertIn(labels.STILL_COLLECTED, self.texts(at, "caption"))

    def test_nothing_is_sent_while_locked(self):
        self.http.on("POST", PREFERENCES, FakeResponse(201, fb.preference_created()))
        at = self.briefing(pin=None)
        at.session_state["zx_dialog"] = {"name": actions.DIALOG_PREF,
                                         "args": {"workspace_id": "pilot", "direction": "more",
                                                  "target": actions.Target("pilot", "A story", 9001, item_id=1201)}}
        at.run()
        self.assert_clean(at)
        save = at.button(key="dlg_save")
        self.assertTrue(save.disabled)  # AppTest, like a browser, refuses a click on a disabled button
        self.assertEqual(save.help, labels.LOCKED_HELP)
        at.text_input(key="dlg_text").input("production orders for small drones").run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])


if __name__ == "__main__":
    unittest.main()
