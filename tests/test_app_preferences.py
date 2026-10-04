"""AppTest: My preferences (docs/SPEC-PHASE03-UI.md 7.1-7.3 and 7.5-7.7): the section control, Needs your OK, Active,
Muted, Watchlist and How much, with every write's method, URL, bearer, body, toast and undo."""

from __future__ import annotations

import unittest
from datetime import timedelta

import fixtures_preferences as fp
from helpers import AppCase, Call, FakeResponse, OWNER, PILOT_HUB, PIN, READ, hub_defaults

from zenux_dashboard import labels, ui
from zenux_dashboard import preferences_view as pv
from zenux_dashboard.fmt import esc

TZ = fp.TZ


def eff(hours_ahead: float = 2.0) -> str:
    """The toast's "takes effect" sentence for fp.effective(hours_ahead)."""
    return ui.effective_text(fp.effective(hours_ahead), TZ)


def text_of(pid: str) -> str:
    return labels.preference_text(next(p for p in fp.preference_rows() if p["id"] == pid))


class PrefCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        fp.route_reads(self.http)

    def open(self, section: str | None = None, *, pin: str | None = None, query: dict | None = None,
             state: dict | None = None):
        extra = dict(state or {})
        if section:
            extra["pf_section"] = section
        if query is not None:
            return self.app(query={"tab": "preferences", **query}, pin=pin, state=extra)
        return self.app(tab="preferences", pin=pin, state=extra)

    def section(self, at, value: str):
        at.segmented_control(key="pf_section").set_value(value).run()
        self.assert_clean(at)
        return at

    def posted(self, url: str) -> Call:
        calls = self.http.find("POST", url)
        self.assertTrue(calls, f"nothing was posted to {url}")
        return calls[-1]

    def assert_post(self, url: str, body) -> Call:
        call = self.posted(url)
        self.assertEqual((call.body, call.bearer), (body, OWNER))
        return call

    def undo(self, at):
        undo = at.session_state[ui.UNDO_KEY]
        self.assertIsNotNone(undo)
        return undo

    def run_undo(self, at, url: str, response=None) -> Call:
        """Run the pending undo's inverse call (as the undo bar would, with the owner token) and return it."""
        self.http.on("POST", url, response if response is not None else {"ok": True})
        self.undo(at).run(OWNER)
        return self.posted(url)

    def confirm(self, at):
        """Press the confirm button of the open ui.ask_confirm dialog."""
        return self.click(at, "dlg_save")


# ---------------------------------------------------------------------------------------------- the section control


class SectionTests(PrefCase):
    def test_counts_default_section_and_summary(self):
        at = self.open()
        self.assert_clean(at)
        control = at.segmented_control(key="pf_section")
        self.assertEqual(control.value, "ok")  # it has suggestions
        self.assertEqual(control.options, ["Needs your OK · 6", "Active · 4", "What ZENUX looks for", "Muted · 3",
                                           "Watchlist · 2", "How much"])
        self.assertIn("This week your preferences changed 23 decisions: 4 brought into a briefing, 15 kept out, "
                      "3 raised.", self.html(at))
        for path in ("/preferences", "/rules", "/mutes", "/stars"):
            self.assertEqual(self.http.find("GET", PILOT_HUB + path)[0].bearer, READ)
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/mutes")[0].params.get("all") in (1, "1", True), True)
        self.assertEqual(self.http.posts(), [])
        self.assert_no_secrets(at)

    def test_active_is_the_default_when_nothing_needs_an_ok(self):
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(suggestions=[]))
        body = fp.rules()
        body["drafts"] = [d for d in body["drafts"] if d["status"] != "proposed"]
        self.http.on("GET", PILOT_HUB + "/rules", body)
        at = self.open()
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="pf_section").value, "active")
        self.assertEqual(at.segmented_control(key="pf_section").options[0], "Needs your OK · 0")

    def test_quiet_week(self):
        body = fp.preferences()
        body["summary_7d"] = {"hits": 0, "promoted": 0, "suppressed": 0, "raised": 0, "lowered": 0, "top": []}
        self.http.on("GET", PILOT_HUB + "/preferences", body)
        at = self.open()
        self.assertIn("Your preferences haven&#x27;t changed anything this week.", self.html(at))

    def test_section_link(self):
        at = self.open(query={"section": "watchlist"})
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="pf_section").value, "watchlist")
        self.assertIn("CoreWeave", self.html(at))

    def test_preference_link_opens_active_with_that_card_first(self):
        at = self.open(query={"pref": "I-0007"})
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="pf_section").value, "active")
        html = self.html(at)
        focused = html.index('<div class="pref-card zx-focus">')
        self.assertIn(labels.preference_text(fp.preference_rows()[2]), html[focused:focused + 600])
        self.assertLess(focused, html.index(text_of("R-0012")))  # drawn before the newer ones

    def test_switching_sections_is_kept_and_mirrored(self):
        at = self.open()
        self.section(at, "muted")
        self.assertIn("Sources · 1", self.html(at))
        at.run()  # a plain rerun keeps the choice
        self.assertEqual(at.segmented_control(key="pf_section").value, "muted")
        self.assertIn("muted", str(at.query_params.get("section")))

    def test_every_section_is_plain(self):
        at = self.open(pin=PIN)
        self.open_expander(at, "sg_list_19")
        at.run()
        self.assert_plain(at)
        for section, expanders in (("active", ("pf_ended",)), ("looks_for", ()), ("muted", ("pf_removed_mutes",)),
                                   ("watchlist", ()), ("how_much", ())):
            self.section(at, section)
            for key in expanders:
                self.open_expander(at, key)
            at.run()
            self.assert_clean(at)
            self.assert_plain(at)
        self.assertNotIn("suppressed", self.visible_text(at).lower())

    def test_locked_controls_are_visible_but_disabled(self):
        at = self.open()
        self.assert_clean(at)
        for key in ("sg_approve_19", "sg_reject_41", "sg_approve_44"):
            button = at.button(key=key)
            self.assertTrue(button.disabled, key)
            self.assertEqual(button.help, labels.LOCKED_HELP)
        self.assertIn(labels.LOCKED_HELP, self.visible_text(at))
        self.section(at, "active")
        for key in ("pf_pause_R-0012", "pf_resume_I-0007", "pf_edit_R-0012", "pf_end_R-0012", "pf_remove_R-0012",
                    "pf_add_save", "pf_mute_instead_R-0012", "pf_end_it_R-0001"):
            self.assertTrue(at.button(key=key).disabled, key)
        self.assertEqual(at.button(key="pf_pause_R-0012").help, labels.LOCKED_HELP)
        self.section(at, "how_much")
        at.radio(key="pf_volume_mode").set_value("top").run()
        self.assertTrue(at.button(key="pf_volume_save").disabled)
        self.section(at, "muted")
        self.assertTrue(at.button(key="pf_unmute_4").disabled)
        self.assertEqual(self.http.posts(), [])

    def test_unreachable_preferences_keep_the_other_sections(self):
        self.http.routes.pop(("GET", PILOT_HUB + "/preferences"))
        at = self.open()
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="pf_section").value, "active")
        self.assertEqual(at.segmented_control(key="pf_section").options[:2], ["Needs your OK", "Active"])
        self.assertIn("Couldn't load your preferences.", self.visible_text(at))
        self.section(at, "muted")
        self.assertIn("Sources · 1", self.html(at))


# ---------------------------------------------------------------------------------------------- Needs your OK


class NeedsYourOkTests(PrefCase):
    def test_cards_by_origin(self):
        at = self.open()
        self.assert_clean(at)
        html = self.html(at)
        heads = ["Your suggested change to What ZENUX looks for", "Suggested wording for your preference",
                 "Suggested from your ratings", "Suggested merge of 2 preferences", "From a coverage request",
                 "Your draft, worded by the wording assistant"]
        positions = [html.index(head) for head in heads]
        self.assertEqual(positions, sorted(positions))  # newest proposal first: 45, 41, 19, 44, 46, then legacy 31
        # ratings behind a suggestion, at most five, plainly
        self.assertIn("Conference webcast notice 0 &lt;live&gt; · you: Not relevant · editor: 74", html)
        self.assertIn("Conference webcast notice 4 &lt;live&gt; · you: Not relevant · editor: left out", html)
        self.assertNotIn("Conference webcast notice 5", html)
        self.assertIn("and 1 more", html)
        self.assertNotIn("Suggested from 6 of your grades", html)
        # a clearer wording: the analyst's words and the suggestion
        self.assertIn(esc(f"Yours: {text_of('R-0012')}"), html)
        self.assertIn("Suggested: Rank stock-price move articles without new company facts as not relevant.", html)
        # a merge lists what it replaces
        self.assertIn("It replaces:", html)
        self.assertIn(esc(text_of("R-0010")), html)
        # a brief line (as What ZENUX looks for shows it now, by its id), a coverage request, a legacy draft
        self.assertIn("Line: Signed capacity: a contract with a hyperscaler or AI lab. Capture MW, dollar value, term "
                      "and counterparty.", html)
        self.assertIn("Rank Texas large-load interconnection approvals as material news.", html)
        self.assertIn("Your words: counter drone orders under 1M are watch", html)
        # previews
        self.assertIn('<span class="preview-plus">+2</span> / <span class="preview-minus">-1</span> in the last 14 days',
                      html)
        self.assertIn('<span class="preview-plus">+0</span> / <span class="preview-minus">-9</span>', html)
        self.assertIn("No preview yet.", html)
        captions = self.texts(at, "caption")
        self.assertIn("Would have added 2 stories to your briefings and removed 1.", captions)
        self.assertIn("1 suggestion you sent is with the wording assistant. It comes back here once worded.", captions)
        rationale = labels.clean_rationale(fp.grades_draft()["proposal"]["rationale"])
        self.assertIn(rationale, captions)
        self.assertNotIn("#1300", self.visible_text(at))
        # the wording box holds the proposal; button names follow the origin
        self.assertEqual(at.text_area(key="sg_text_19").value, fp.grades_draft()["proposal"]["text"])
        self.assertEqual(at.button(key="sg_approve_41").label, "Use this wording")
        self.assertEqual(at.button(key="sg_reject_41").label, "Keep mine")
        self.assertEqual(at.button(key="sg_approve_44").label, "Merge them")
        self.assertEqual(at.button(key="sg_reject_44").label, "Keep them separate")
        self.assertEqual(at.button(key="sg_approve_19").label, "Approve")
        self.assertEqual(at.button(key="sg_reject_19").label, "Not now")
        # conflicts: only a live preference, ended on approval by default
        self.assertIn("It may conflict with:", html)
        self.assertTrue(at.checkbox(key="sg_retire_19_0").value)
        self.assertNotIn("sg_retire_19_1", [c.key for c in at.checkbox])

    def test_which_stories_lists_the_previews_stories(self):
        # gap 2: the suggestion carries its preview's stories (preview_items), so nothing else is read
        at = self.open()
        self.assertNotIn("Would come in", self.html(at))  # lazy: drawn only while open
        self.open_expander(at, "sg_list_19")
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("Would come in · 2", html)
        self.assertIn("Miner monthly production update · Miner Co. investor relations", html)
        self.assertIn("A story no longer available", html)
        self.assertIn("Would drop out · 1", html)
        self.assertIn("Army awards $48M counter-drone order · war.gov", html)
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/rejected"), [])
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/editions"), [])
        self.assert_plain(at)

    def test_which_stories_counts_beyond_fifty(self):
        body = fp.preferences()
        body["suggestions"][0]["preview_more"] = 7
        self.http.on("GET", PILOT_HUB + "/preferences", body)
        at = self.open()
        self.open_expander(at, "sg_list_19")
        at.run()
        self.assert_clean(at)
        self.assertIn("and 7 more stories", self.html(at))

    def test_approve_with_an_edit_and_a_conflict_then_undo(self):
        self.http.on("POST", fp.rule_url(19, "approve"), fp.approved("R-0014"))
        at = self.open(pin=PIN)
        at.text_area(key="sg_text_19").set_value("  Conference-talk announcements from news search rank not relevant.  ")
        at.button(key="sg_approve_19").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(19, "approve"), {
            "proposed_at": fp.grades_draft()["proposed_at"],
            "text": "Conference-talk announcements from news search rank not relevant.",
            "retire": ["R-0001"]})
        self.assertIn(f"Approved. {eff()}".strip(), self.toasts(at))
        self.assertGreaterEqual(len(self.http.find("GET", PILOT_HUB + "/preferences")), 2)  # read again
        undo = self.undo(at)
        self.assertEqual((undo.text, undo.done), ("Approved a suggestion.", "Undone."))
        call = self.run_undo(at, fp.rule_url("R-0014", "retire"), fp.retired("R-0014"))
        self.assertEqual((call.body, call.bearer), ({"reason": "undone"}, OWNER))

    def test_unchanged_approval_sends_only_what_was_shown(self):
        self.http.on("POST", fp.rule_url(19, "approve"), fp.approved("R-0014"))
        at = self.open(pin=PIN)
        at.checkbox(key="sg_retire_19_0").uncheck()
        at.button(key="sg_approve_19").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(19, "approve"), {"proposed_at": fp.grades_draft()["proposed_at"]})

    def test_use_this_wording_and_undo_puts_the_old_one_back(self):
        self.http.on("POST", fp.rule_url(41, "approve"), fp.approved("R-0014", superseded="R-0012"))
        at = self.open(pin=PIN)
        at.button(key="sg_approve_41").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(41, "approve"), {"proposed_at": fp.wording_draft()["proposed_at"]})
        self.assertEqual(self.undo(at).done, "Undone. Your earlier wording is back.")
        call = self.run_undo(at, fp.rule_url("R-0014", "retire"), fp.retired("R-0014", restored="R-0012"))
        self.assertEqual(call.body, {"reason": "undone"})

    def test_merge(self):
        self.http.on("POST", fp.rule_url(44, "approve"), fp.approved("R-0017", retired=["R-0012", "R-0010"]))
        at = self.open(pin=PIN)
        at.button(key="sg_approve_44").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(44, "approve"), {"proposed_at": fp.merge_draft()["proposed_at"]})
        self.assertEqual(self.undo(at).text, "Approved a suggestion.")

    def test_not_now_sets_it_aside(self):
        self.http.on("POST", fp.rule_url(41, "reject"), fp.rejected_draft(41))
        at = self.open(pin=PIN)
        at.button(key="sg_reject_41").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(41, "reject"), {})
        self.assertIn("Set aside.", self.toasts(at))
        # Undo puts it back under Needs your OK (POST /rules/<draft>/reopen, gap 8)
        undo = self.undo(at)
        self.assertEqual((undo.text, undo.done), ("Set a suggestion aside.", "It is back under Needs your OK."))
        call = self.run_undo(at, fp.rule_url(41, "reopen"), {"draft": {"id": 41, "status": "proposed"},
                                                             "reopened": True, "effective": fp.effective()})
        self.assertEqual((call.body, call.bearer), ({}, OWNER))

    def test_a_changed_proposal_is_shown_again_not_approved(self):
        at = self.open(pin=PIN)
        newer = fp.iso(0.01)
        changed = fp.preferences()
        changed["suggestions"][0]["proposed_at"] = newer
        changed["suggestions"][0]["proposal"]["text"] = "A newer wording from the wording assistant."
        changed["suggestions"][0]["proposal_plain"]["text"] = "A newer wording from the wording assistant."
        self.http.on("GET", PILOT_HUB + "/preferences", changed)
        activated: list[dict] = []

        def approve(call: Call):  # brain.js decideRule with body.proposed_at
            if call.body.get("proposed_at") != newer:
                return fp.refusal(409, "proposal_changed", "rule draft 19 has a different proposal than the one "
                                  "reviewed; reload it and review it again (nothing was approved)",
                                  status="proposed", proposed_at=newer)
            activated.append(call.body)
            return fp.approved("R-0014")

        self.http.on("POST", fp.rule_url(19, "approve"), approve)
        at.button(key="sg_approve_19").click().run()
        self.assert_clean(at)
        self.assertEqual(activated, [])
        self.assertIn(pv.PROPOSAL_CHANGED, self.texts(at, "warning"))
        self.assertEqual(self.texts(at, "error"), [])
        self.assertFalse(any(t.startswith("Approved.") for t in self.toasts(at)))
        self.assertEqual(at.text_area(key="sg_text_19").value, "A newer wording from the wording assistant.")
        at.checkbox(key="sg_retire_19_0").uncheck()
        at.button(key="sg_approve_19").click().run()
        self.assertEqual(activated, [{"proposed_at": newer}])

    def test_a_merge_over_an_ended_preference_is_flagged(self):
        # gap 28: the hub marks the merge outdated; only "Keep them separate" is offered
        body = fp.preferences()
        next(p for p in body["preferences"] if p["id"] == "R-0010").update(status="retired", retired_reason="owner")
        merge = next(s for s in body["suggestions"] if s["id"] == 44)
        merge["replaces_detail"][1].update(status="retired", status_text="ended", ended=True)
        merge["outdated"] = True
        self.http.on("GET", PILOT_HUB + "/preferences", body)
        self.http.on("POST", fp.rule_url(44, "reject"), fp.rejected_draft(44))
        at = self.open(pin=PIN)
        self.assert_clean(at)
        self.assertIn(pv.MERGE_STALE, self.texts(at, "caption"))
        self.assertIn("Crypto price recaps. (ended)", self.html(at))
        keys = {getattr(b, "key", None) for b in at.button}
        self.assertNotIn("sg_approve_44", keys)
        self.assertTrue(at.text_area(key="sg_text_44").disabled)
        at.button(key="sg_reject_44").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(44, "reject"), {})

    def test_an_outdated_merge_reloads(self):
        self.http.on("POST", fp.rule_url(44, "approve"), fp.refusal(
            409, "merge_outdated", "A preference this merge replaces has changed since it was proposed (R-0010).",
            changed=["R-0010"]))
        at = self.open(pin=PIN)
        at.button(key="sg_approve_44").click().run()
        self.assert_clean(at)
        self.assertIn(pv.MERGE_OUTDATED, self.texts(at, "warning"))
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/preferences")), 2)

    def test_an_ended_preference_offers_approve_as_new(self):
        calls: list[dict] = []

        def approve(call: Call):
            calls.append(call.body)
            if not call.body.get("as_new"):
                return fp.refusal(409, "target_retired", pv.TARGET_RETIRED, target_precedent_id="R-0012")
            return fp.approved("R-0018")

        self.http.on("POST", fp.rule_url(41, "approve"), approve)
        at = self.open(pin=PIN)
        at.button(key="sg_approve_41").click().run()
        self.assert_clean(at)
        self.assertIn(pv.TARGET_RETIRED, self.texts(at, "info"))
        self.assertEqual(self.texts(at, "error"), [])
        at.button(key="sg_as_new_41").click().run()
        self.assert_clean(at)
        self.assertEqual(calls[-1], {"proposed_at": fp.wording_draft()["proposed_at"], "as_new": True})
        self.assertIn(f"Approved. {eff()}".strip(), self.toasts(at))

    def test_other_refusals_in_plain_words(self):
        self.http.on("POST", fp.rule_url(19, "approve"), fp.refusal(
            409, "draft_closed", "rule draft 19 is approved"))
        at = self.open(pin=PIN)
        at.button(key="sg_approve_19").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. This suggestion was already handled meanwhile. Refresh to see where it stands.",
                      self.texts(at, "error"))
        self.assert_plain(at)

    def test_nothing_needs_an_ok(self):
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(suggestions=[]))
        self.http.on("GET", PILOT_HUB + "/rules", {"precedents": [], "drafts": []})
        at = self.open("ok")
        self.assert_clean(at)
        self.assertIn(pv.EMPTY_OK, self.html(at))


# ---------------------------------------------------------------------------------------------- Active


class ActiveTests(PrefCase):
    def test_cards_with_what_each_preference_did(self):
        at = self.open("active")
        self.assert_clean(at)
        html = self.html(at)
        visible = self.visible_text(at)
        self.assertIn("Lowered 12 stories in 30 days (11 kept out) · last used 5h ago", html)
        self.assertIn("Raised 5 stories in 30 days (2 made the briefing) · last used 2d ago", html)
        self.assertIn("Brought in 0 · kept out 0 in 30 days · not used yet", html)
        self.assertNotIn("suppressed", visible.lower())
        self.assertIn("Example: Shares jump 8% on AI &lt;hopes&gt; (Yahoo Finance)", html)
        self.assertIn("Stories like this · Paused since", html)
        self.assertIn(" · until ", html)
        self.assertIn("Exactly as I write it", visible)  # legacy direction
        self.assertIn("Standing preference · Active", html)
        self.assertNotIn("event #", visible)
        self.assertNotIn("R-0012", visible)
        # offers
        self.assertIn("Not used in 30 days. Still useful?", html)
        self.assertEqual(at.button(key="pf_end_it_R-0001").label, "End it")
        self.assertIn(f"91% of what it kept out came from {fp.MUTE_LABEL}. Mute it instead?", html)
        self.assertEqual(at.button(key="pf_mute_instead_R-0012").label, f"Mute {fp.MUTE_LABEL}")
        self.assertIn(f"Mostly kept out: {fp.MUTE_LABEL}, Example Co", self.texts(at, "caption"))
        self.assertIn("A clearer wording is waiting in Needs your OK.", html)
        # Pause for active, Resume for paused
        self.assertEqual(at.button(key="pf_pause_R-0012").label, "Pause")
        self.assertEqual(at.button(key="pf_resume_I-0007").label, "Resume")
        self.assertNotIn("pf_pause_I-0007", [b.key for b in at.button])
        # the ended ones wait in a closed list
        self.assertNotIn("pf_bring_back_R-0005", [b.key for b in at.button])
        self.assertIn("Ended preferences · 3", [e.label for e in at.expander])

    def test_add_a_preference_with_an_end_date_then_undo(self):
        self.http.on("POST", PILOT_HUB + "/preferences", fp.created("R-0016"))
        at = self.open("active", pin=PIN)
        until = pv.local_today(TZ) + timedelta(days=10)
        at.radio(key="pf_add_dir").set_value("less")
        at.text_area(key="pf_add_text").set_value("  Fewer crypto price recaps unless a miner announces AI hosting.  ")
        at.checkbox(key="pf_add_until_on").check()
        at.date_input(key="pf_add_until").set_value(until)
        at.button(key="pf_add_save").click().run()
        self.assert_clean(at)
        self.assert_post(PILOT_HUB + "/preferences", {
            "direction": "less", "scope": "standing",
            "text": "Fewer crypto price recaps unless a miner announces AI hosting.",
            "expires_at": pv.expires_iso(until, TZ)})
        self.assertIn(f"Added: Show me less like this. {eff()}".strip(), self.toasts(at))
        self.assertEqual(at.text_area(key="pf_add_text").value, "")
        self.assertEqual(self.undo(at).text, "Added a preference.")
        call = self.run_undo(at, fp.rule_url("R-0016", "retire"), fp.retired("R-0016"))
        self.assertEqual(call.body, {"reason": "undone"})

    def test_add_refuses_a_few_words(self):
        at = self.open("active", pin=PIN)
        at.text_area(key="pf_add_text").set_value("crypto")
        at.button(key="pf_add_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertIn(pv.TOO_SHORT, self.texts(at, "info"))

    def test_soft_cap(self):
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(over=True))
        at = self.open("active")
        self.assertIn("You have 41 active preferences. Older ones may conflict; the wording assistant suggests merges "
                      "once a month.", self.texts(at, "info"))

    def test_pause_and_resume_with_undo(self):
        self.http.on("POST", fp.rule_url("R-0012", "pause"), fp.lifecycle("R-0012", "paused"))
        self.http.on("POST", fp.rule_url("I-0007", "resume"), fp.lifecycle("I-0007", "active"))
        at = self.open("active", pin=PIN)
        at.button(key="pf_pause_R-0012").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("R-0012", "pause"), {})
        self.assertIn(pv.PAUSED_TOAST, self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0012", "resume")).body, {})
        at.button(key="pf_resume_I-0007").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("I-0007", "resume"), {})
        self.assertIn(f"Resumed. {eff()}".strip(), self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("I-0007", "pause")).body, {})

    def test_a_refusal_shows_the_hub_sentence(self):
        self.http.on("POST", fp.rule_url("R-0012", "pause"), fp.refusal(
            409, "not_active", "Only an active preference can be paused.", status="paused"))
        at = self.open("active", pin=PIN)
        at.button(key="pf_pause_R-0012").click().run()
        self.assert_clean(at)
        self.assertTrue(any("Only an active preference can be paused." in e for e in self.texts(at, "error")))
        self.assertEqual(self.toasts(at), [])

    def test_edit_makes_a_new_version_and_undo_restores(self):
        self.http.on("POST", fp.rule_url("R-0012", "edit"), fp.edited("R-0015", "R-0012"))
        at = self.open("active", pin=PIN)
        at.button(key="pf_edit_R-0012").click().run()
        self.assert_clean(at)
        self.assertEqual(at.text_area(key="dlg_text").value, text_of("R-0012"))
        self.assertEqual(at.radio(key="dlg_direction").value, "less")
        self.assertEqual(at.radio(key="dlg_scope").value, "standing")
        self.assertNotIn(labels.SCOPE_LABELS["this_story"], at.radio(key="dlg_scope").options)  # no story behind it
        at.text_area(key="dlg_text").set_value("Stock-move articles with no new company facts.")
        at.radio(key="dlg_scope").set_value("similar")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("R-0012", "edit"), {"text": "Stock-move articles with no new company facts.",
                                                          "scope": "similar"})
        self.assertIn(f"Saved your new wording. {eff()}".strip(), self.toasts(at))
        self.assertNotIn("dlg_save", [b.key for b in at.button])  # the dialog closed
        undo = self.undo(at)
        self.assertEqual(undo.done, "Undone. Your earlier wording is back.")
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0015", "retire")).body, {"reason": "undone"})

    def test_edit_with_nothing_changed_sends_nothing(self):
        at = self.open("active", pin=PIN)
        at.button(key="pf_edit_R-0010").click().run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertIn(pv.NOTHING_CHANGED, self.texts(at, "info"))
        at.button(key="dlg_cancel").click().run()
        self.assertNotIn("dlg_save", [b.key for b in at.button])

    def test_end_date_clear_and_set(self):
        previous = next(p for p in fp.preference_rows() if p["id"] == "I-0007")["expires_at"]
        self.http.on("POST", fp.rule_url("I-0007", "end-date"), fp.lifecycle("I-0007", "paused"))
        at = self.open("active", pin=PIN)
        at.button(key="pf_end_I-0007").click().run()
        at.radio(key="dlg_choice").set_value("none").run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("I-0007", "end-date"), {"expires_at": None})
        self.assertIn("No end date.", self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("I-0007", "end-date")).body, {"expires_at": previous})
        self.http.on("POST", fp.rule_url("R-0012", "end-date"), fp.lifecycle("R-0012"))
        day = pv.local_today(TZ) + timedelta(days=45)
        at.button(key="pf_end_R-0012").click().run()
        at.date_input(key="dlg_until").set_value(day)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        expires = pv.expires_iso(day, TZ)
        self.assert_post(fp.rule_url("R-0012", "end-date"), {"expires_at": expires})
        self.assertIn(f"It ends on {pv.fmt_date(expires, TZ)}.", self.toasts(at))

    def test_remove_asks_first_and_undo_brings_it_back(self):
        self.http.on("POST", fp.rule_url("R-0010", "retire"), fp.retired("R-0010"))
        at = self.open("active", pin=PIN)
        at.button(key="pf_remove_R-0010").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])  # nothing until confirmed
        self.assertIn(pv.REMOVE_MESSAGE, self.visible_text(at))
        self.confirm(at)
        self.assert_clean(at)
        self.assert_post(fp.rule_url("R-0010", "retire"), {})
        self.assertIn("Removed.", self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0010", "reactivate")).body, {})

    def test_end_it_on_a_dormant_preference_is_the_remove_confirm(self):
        self.http.on("POST", fp.rule_url("R-0001", "retire"), fp.retired("R-0001"))
        at = self.open("active", pin=PIN)
        at.button(key="pf_end_it_R-0001").click().run()
        self.assertIn(pv.REMOVE_MESSAGE, self.visible_text(at))
        self.confirm(at)
        self.assert_post(fp.rule_url("R-0001", "retire"), {})

    def test_looks_like_a_mute_opens_the_mute_dialog_prefilled(self):
        at = self.open("active", pin=PIN)
        at.button(key="pf_mute_instead_R-0012").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state[ui.DIALOG_KEY]["name"], "mute")
        preview = self.http.find("GET", PILOT_HUB + "/mutes/preview")
        self.assertTrue(preview)
        self.assertEqual({k: preview[-1].params.get(k) for k in ("kind", "module", "ref")},
                         {"kind": "source", "module": "ai-infra", "ref": "gn-themes"})
        self.assertEqual(self.http.posts(), [])

    def test_see_the_waiting_wording(self):
        at = self.open("active")
        at.button(key="pf_wording_R-0012").click().run()
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="pf_section").value, "ok")

    def test_ended_preferences_and_bring_back(self):
        self.http.on("POST", fp.rule_url("R-0005", "reactivate"), fp.lifecycle("R-0005"))
        at = self.open("active", pin=PIN)
        self.open_expander(at, "pf_ended")
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        for reason in ("You removed it", "Its end date passed", "Replaced by a newer wording"):
            self.assertIn(reason, html)
        self.open_expander(at, "pf_ended")  # a lazy expander's state is set before the run that clicks in it
        at.button(key="pf_bring_back_R-0005").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("R-0005", "reactivate"), {})
        self.assertIn(f"Brought back. {eff()}".strip(), self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0005", "retire")).body, {})

    def test_bringing_back_an_expired_preference_asks_for_an_end_date(self):
        self.http.on("POST", fp.rule_url("I-0003", "reactivate"), fp.lifecycle("I-0003"))
        at = self.open("active", pin=PIN)
        self.open_expander(at, "pf_ended")
        at.run()
        self.open_expander(at, "pf_ended")
        at.button(key="pf_bring_back_I-0003").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertEqual(at.radio(key="dlg_choice").value, "none")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("I-0003", "reactivate"), {"expires_at": None})

    def test_a_link_to_an_ended_preference_opens_the_list(self):
        at = self.open(query={"pref": "R-0005"})
        self.assert_clean(at)
        self.assertIn('<div class="pref-card zx-focus"><div class="pref-text">', self.html(at))

    def test_no_preferences_yet(self):
        body = fp.preferences(suggestions=[])
        body["preferences"] = []
        self.http.on("GET", PILOT_HUB + "/preferences", body)
        at = self.open("active")
        self.assertIn(pv.EMPTY_ACTIVE, self.html(at))


# ---------------------------------------------------------------------------------------------- Muted and Watchlist


class MutedTests(PrefCase):
    def test_mutes_grouped_with_what_they_hid(self):
        at = self.open("muted")
        self.assert_clean(at)
        html = self.html(at)
        for group in ("Sources · 1", "Companies · 1", "Stories · 1"):
            self.assertIn(group, html)
        self.assertIn(fp.MUTE_LABEL, html)
        self.assertIn("hid 12 this week (30 in all)", html)
        self.assertIn("Not part of the &lt;thesis&gt;", html)
        self.assertIn(pv.MUTED_CAPTION, self.texts(at, "caption"))
        self.assertNotIn("Old trade feed", html)  # removed mutes wait in a closed list
        self.open_expander(at, "pf_removed_mutes")
        at.run()
        html = self.html(at)
        self.assertIn("Old trade feed", html)
        self.assertIn("Brought back", self.texts(at, "caption"))
        self.assertNotIn("pf_bring_back_m1", [b.key for b in at.button])
        self.assertEqual(at.button(key="pf_bring_back_m2").label, "Bring back the last 7 days")

    def test_unmute_opens_the_unmute_dialog(self):
        at = self.open("muted", pin=PIN)
        at.button(key="pf_unmute_4").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state[ui.DIALOG_KEY]["name"], "unmute")
        self.assertEqual(self.http.posts(), [])

    def test_bring_back_a_removed_mute(self):
        self.http.on("POST", PILOT_HUB + "/mutes", {"mute": fp.mute(2, "source", "old-feed", "Old trade feed",
                                                                    module="ai-infra", active=False, removed_hours=30,
                                                                    brought_back=True),
                                                    "brought_back": 5, "requeued": 4, "effective": fp.effective()})
        at = self.open("muted", pin=PIN)
        self.open_expander(at, "pf_removed_mutes")
        at.run()
        self.open_expander(at, "pf_removed_mutes")
        at.button(key="pf_bring_back_m2").click().run()
        self.assert_clean(at)
        self.assert_post(PILOT_HUB + "/mutes", {"action": "bring_back", "mute_id": 2, "days": 7})

    def test_show_what_they_hid(self):
        at = self.open("muted")
        at.button(key="pf_show_hidden").click().run()
        self.assertEqual(at.session_state["zx_tab"], "filtered")

    def test_nothing_muted(self):
        self.http.on("GET", PILOT_HUB + "/mutes", {"mutes": [], "active_count": 0})
        at = self.open("muted")
        self.assert_clean(at)
        self.assertIn(pv.EMPTY_MUTED, self.html(at))
        self.assertEqual(at.segmented_control(key="pf_section").options[3], "Muted · 0")


class WatchlistTests(PrefCase):
    def test_stars_with_their_counts(self):
        at = self.open("watchlist")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("CoreWeave", html)
        self.assertIn("9 stories this week, 2 in your briefing", html)
        self.assertIn("1 story this week, 0 in your briefing · Watch the Finland build", html)
        self.assertNotIn("IREN", html)  # removed
        self.assertIn(labels.STAR_PROMISE, self.texts(at, "caption"))

    def test_remove_a_star(self):
        self.http.on("POST", PILOT_HUB + "/stars", {"star": {"id": 2, "entity_id": "coreweave", "active": False},
                                                    "removed": True, "effective": fp.effective()})
        at = self.open("watchlist", pin=PIN)
        at.button(key="pf_unstar_2").click().run()
        self.assert_clean(at)
        self.assert_post(PILOT_HUB + "/stars", {"action": "remove", "entity_id": "coreweave"})

    def test_find_companies_in_coverage_and_empty(self):
        at = self.open("watchlist")
        at.button(key="pf_find_coverage").click().run()
        self.assertEqual(at.session_state["zx_tab"], "coverage")
        self.http.on("GET", PILOT_HUB + "/stars", {"stars": []})
        self.fresh()
        at = self.open("watchlist")
        self.assertIn(pv.EMPTY_WATCHLIST, self.html(at))


# ---------------------------------------------------------------------------------------------- How much


class HowMuchTests(PrefCase):
    def test_modes_from_the_hub_and_the_current_setting(self):
        at = self.open("how_much")
        self.assert_clean(at)
        radio = at.radio(key="pf_volume_mode")
        self.assertEqual((radio.value, radio.options), ("standard", ["Only the big ones", "Standard",
                                                                     "Everything notable"]))
        self.assertFalse(at.toggle(key="pf_volume_shelf").value)
        self.assertIn(pv.VOLUME_CURRENT, self.html(at))
        self.assertTrue(at.button(key="pf_volume_save").disabled)
        self.assertIn(pv.VOLUME_CAPTION, self.texts(at, "caption"))
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/settings/volume/preview"), [])

    def test_preview_save_and_undo(self):
        self.http.on("POST", PILOT_HUB + "/settings/volume", fp.volume_set("top"))
        at = self.open("how_much", pin=PIN)
        at.radio(key="pf_volume_mode").set_value("top").run()
        self.assert_clean(at)
        self.assertIn(fp.PREVIEW_TEXT["top"], self.html(at))
        preview = self.http.find("GET", PILOT_HUB + "/settings/volume/preview")[-1]
        self.assertEqual(preview.params.get("mode"), "top")
        self.assertFalse(at.button(key="pf_volume_save").disabled)
        at.button(key="pf_volume_save").click().run()
        self.assert_clean(at)
        self.assert_post(PILOT_HUB + "/settings/volume", {"mode": "top", "near_miss_shelf": False})
        self.assertIn(f"Now: Only the big ones. {eff()}".strip(), self.toasts(at))
        call = self.run_undo(at, PILOT_HUB + "/settings/volume", fp.volume_set("standard"))
        self.assertEqual(call.body, {"mode": "standard", "near_miss_shelf": False})

    def test_near_miss_shelf_switch(self):
        self.http.on("POST", PILOT_HUB + "/settings/volume", fp.volume_set("standard", True))
        at = self.open("how_much", pin=PIN)
        at.toggle(key="pf_volume_shelf").set_value(True).run()
        self.assert_clean(at)
        preview = self.http.find("GET", PILOT_HUB + "/settings/volume/preview")[-1]
        self.assertEqual(preview.params.get("mode"), "standard")
        self.assertIn(str(preview.params.get("near_miss_shelf")), ("1", "True", "true"))
        at.button(key="pf_volume_save").click().run()
        self.assert_post(PILOT_HUB + "/settings/volume", {"mode": "standard", "near_miss_shelf": True})

    def test_a_changed_saved_setting_moves_the_choice(self):
        at = self.open("how_much")
        self.http.on("GET", PILOT_HUB + "/settings", fp.settings("broad"))
        self.fresh()
        at.run()
        self.assert_clean(at)
        self.assertEqual(at.radio(key="pf_volume_mode").value, "broad")
        self.assertIn(pv.VOLUME_CURRENT, self.html(at))

    def test_unreadable_settings(self):
        self.http.routes.pop(("GET", PILOT_HUB + "/settings"))
        at = self.open("how_much")
        self.assert_clean(at)
        self.assertIn("Couldn't load your 'how much' setting.", self.visible_text(at))


if __name__ == "__main__":
    unittest.main()
