"""AppTest: Tuning (docs/SPEC-SIMPLIFY.md 2.3), one page without sub-tabs: the title and 7-day summary, Needs your OK
(only when something waits; Details holds the rest), How much in one row, Your rules (one list with filter pills, + Add
a rule and one menu per row, without Pause; Resume for a paused preference) and Ended, with every write's method, URL,
bearer, body, toast and undo."""

from __future__ import annotations

import re
import unittest
from datetime import timedelta

import fixtures_tuning as fp
from helpers import AppCase, Call, OWNER, PILOT_HUB, PIN, READ, hub_defaults

from zenux_dashboard import company_names_view as cnv
from zenux_dashboard import labels, ui
from zenux_dashboard import tuning_view as tv
from zenux_dashboard.fmt import esc

TZ = fp.TZ


def eff(hours_ahead: float = 2.0) -> str:
    """The toast's "takes effect" sentence for fp.effective(hours_ahead)."""
    return ui.effective_text(fp.effective(hours_ahead), TZ)


def text_of(pid: str) -> str:
    return labels.preference_text(next(p for p in fp.preference_rows() if p["id"] == pid))


class TuningCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        fp.route_reads(self.http)

    def open(self, *, pin: str | None = None, query: dict | None = None, state: dict | None = None):
        if query is not None:
            at = self.app(query={"tab": "tuning", **query}, pin=pin, state=state)
        else:
            at = self.app(tab="tuning", pin=pin, state=state)
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

    def menu(self, at, ident: str, item: str | None = None):
        """Open a rule's ⋯ menu (tn_menu_<ident>, lazy) and, with `item`, click that item: the menu is opened for the
        run that draws it and again for the run that clicks (AppTest keeps no popover state between runs)."""
        at.session_state[f"tn_menu_{ident}"] = True
        at.run()
        self.assert_clean(at)
        if item:
            at.session_state[f"tn_menu_{ident}"] = True
            at.button(key=item).click().run()
            self.assert_clean(at)
        return at

    def menu_labels(self, at, ident: str) -> list[str]:
        """The items of a rule's open ⋯ menu, in order (Pause would be tn_pause_: there is none)."""
        return [b.label for b in at.button if str(b.key or "").startswith(("tn_resume_", "tn_edit_", "tn_end_",
                                                                         "tn_remove_", "tn_mute_instead_",
                                                                         "tn_unmute_", "tn_unstar_", "tn_pause_"))
                and str(b.key).endswith(ident)]

    def rule_rows(self, at) -> list[str]:
        """The rows of Your rules in page order, as their container keys (zx_rule_<kind>_<id>)."""
        return [str(n.key)[len("zx_rule_"):] for n in self.walk(at._tree)
                if str(getattr(n, "key", None) or "").startswith("zx_rule_")]


# ---------------------------------------------------------------------------------------------- the page


class PageTests(TuningCase):
    def test_one_page_in_the_specs_order(self):
        at = self.open()
        html = self.html(at)
        self.assertIn('<div class="tn-title">Tuning</div>', html)
        self.assertIn("This week your preferences changed 23 decisions: 4 brought into a briefing, 15 kept out, "
                      "3 raised.", html)
        sections = re.findall(r'<div class="rules-section">(.*?)</div>', html)
        self.assertEqual(sections, ["Needs your OK · 8", "How much", "Your rules · 9"])
        self.assertEqual([e.label for e in at.expander if e.label.startswith("Ended")], ["Ended · 5"])
        self.assertLess(html.index("Needs your OK · 8"), html.index("How much"))
        self.assertIsNotNone(at.button(key="zx_refresh_tuning"))
        # no sub-tabs, no Filtered out, no preference sections
        self.assertEqual([c for c in at.get("segmented_control") if getattr(c, "key", "") == "pf_section"], [])
        for path in ("/preferences", "/rules", "/mutes", "/stars", "/settings"):
            self.assertEqual(self.http.find("GET", PILOT_HUB + path)[0].bearer, READ)
        self.assertIn(self.http.find("GET", PILOT_HUB + "/mutes")[0].params.get("all"), (1, "1", True))
        self.assertIn("1 suggestion you sent is with the wording assistant. It comes back under Needs your OK once "
                      "worded.", self.texts(at, "caption"))
        self.assertEqual(self.http.posts(), [])
        self.assert_no_secrets(at)

    def test_needs_your_ok_shows_only_when_something_waits(self):
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(suggestions=[], companies=[]))
        self.http.on("GET", PILOT_HUB + "/rules", {"precedents": [], "drafts": []})
        at = self.open()
        html = self.html(at)
        self.assertNotIn("Needs your OK", html)
        self.assertEqual(re.findall(r'<div class="rules-section">(.*?)</div>', html), ["How much", "Your rules · 9"])

    def test_quiet_week(self):
        body = fp.preferences()
        body["summary_7d"] = {"hits": 0, "promoted": 0, "suppressed": 0, "raised": 0, "lowered": 0, "top": []}
        self.http.on("GET", PILOT_HUB + "/preferences", body)
        at = self.open()
        self.assertIn("Your preferences haven&#x27;t changed anything this week.", self.html(at))

    def test_every_part_is_plain(self):
        state = {tv.ENDED_KEY: True}
        for ident in ("pref_R-0012", "pref_I-0007", "mute_4", "star_2"):
            state[f"tn_menu_{ident}"] = True
        at = self.open(pin=PIN, state=state)
        self.assert_plain(at)
        visible = self.visible_text(at)
        self.assertNotIn("suppressed", visible.lower())
        for old in ("My preferences", "Filtered out"):
            self.assertNotIn(old, visible)
        self.assertNotIn("Pause", [b.label for b in at.button])  # no Pause (Resume for a paused one)
        self.assert_no_secrets(at)

    def test_locked_controls_are_visible_but_disabled(self):
        at = self.open(state={"tn_menu_pref_R-0012": True})
        for key in ("sg_approve_19", "sg_reject_41", "sg_approve_44", "tn_add", "tn_edit_pref_R-0012",
                    "tn_end_pref_R-0012", "tn_remove_pref_R-0012", "tn_mute_instead_pref_R-0012"):
            button = at.button(key=key)
            self.assertTrue(button.disabled, key)
            self.assertEqual(button.help, labels.LOCKED_HELP)
        self.assertIn(labels.LOCKED_HELP, self.visible_text(at))
        at.segmented_control(key=tv.VOLUME_MODE_KEY).set_value("top").run()
        self.assertTrue(at.button(key="tn_volume_save").disabled)
        self.assertEqual(self.http.posts(), [])

    def test_unreachable_preferences_keep_the_other_parts(self):
        self.http.routes.pop(("GET", PILOT_HUB + "/preferences"))
        at = self.open()
        text = self.visible_text(at)
        self.assertIn("Couldn't load your preferences.", text)
        self.assertNotIn("Needs your OK", text)
        self.assertIn("How much", text)
        self.assertEqual(self.rule_rows(at), ["mute_4", "mute_5", "mute_6", "star_2", "star_3"])
        self.assertEqual(list(at.pills(key=tv.RULES_KEY).options), ["All", "More", "Less", "Muted · 3",
                                                                    "Watchlist · 2"])


# ---------------------------------------------------------------------------------------------- Needs your OK


class NeedsYourOkTests(TuningCase):
    def test_cards_by_origin_with_one_impact_line(self):
        at = self.open()
        html = self.html(at)
        heads = ["Your suggested change to What ZENITH looks for", "Suggested wording for your preference",
                 "Suggested from your ratings", "Suggested merge of 2 preferences", "From a coverage request",
                 "Your draft, worded by the wording assistant"]
        positions = [html.index(head) for head in heads]
        self.assertEqual(positions, sorted(positions))  # newest proposal first: 45, 41, 19, 44, 46, then legacy 31
        # the impact line, in words
        for line in ("Would have brought 2 stories in and kept 1 out over the last 14 days.",
                     "Would have kept 9 stories out over the last 14 days.",
                     "Would not have changed your briefings over the last 14 days.",
                     "Would have brought 1 story in over the last 14 days.", "No preview yet."):
            self.assertIn(f'<div class="preview-line">{esc(line)}</div>', html)
        self.assertNotIn("preview-plus", html)
        # a clearer wording: the analyst's words and the suggestion; a merge: what it replaces; a brief line
        self.assertIn(esc(f"Yours: {text_of('R-0012')}"), html)
        self.assertIn("Suggested: Rank stock-price move articles without new company facts as not relevant.", html)
        self.assertIn("It replaces:", html)
        self.assertIn(esc(text_of("R-0010")), html)
        self.assertIn("Line: Signed capacity: a contract with a hyperscaler or AI lab. Capture MW, dollar value, term "
                      "and counterparty.", html)
        self.assertIn("Your words: counter drone orders under 1M are watch", html)
        # button names follow the origin
        self.assertEqual([at.button(key=k).label for k in ("sg_approve_41", "sg_reject_41", "sg_approve_44",
                                                           "sg_reject_44", "sg_approve_19", "sg_reject_19")],
                         ["Use this wording", "Keep mine", "Merge them", "Keep them separate", "Approve", "Not now"])

    def test_details_hold_the_rest(self):
        at = self.open()
        details = [e for e in at.expander if e.label == "Details"]
        self.assertEqual(len(details), 8)  # six suggestions, two company names
        self.assertEqual({e.proto.expanded for e in details}, {False})  # collapsed
        inside = "\n".join(str(m.value) for m in self.walk(details[2]) if getattr(m, "type", "") == "markdown")
        # the ratings behind it (at most five), which stories, the reasoning, the wording box, the conflicts
        self.assertIn("Conference webcast notice 0 &lt;live&gt; · you: Not relevant · editor: 74", inside)
        self.assertIn("Conference webcast notice 4 &lt;live&gt; · you: Not relevant · editor: left out", inside)
        self.assertNotIn("Conference webcast notice 5", inside)
        self.assertIn("and 1 more", inside)
        self.assertIn("Would come in · 2", inside)
        self.assertIn("Miner monthly production update · Miner Co. investor relations", inside)
        self.assertIn("A story no longer available", inside)
        self.assertIn("Would drop out · 1", inside)
        self.assertIn("It may conflict with:", inside)
        self.assertIn(labels.clean_rationale(fp.grades_draft()["proposal"]["rationale"]), self.texts(at, "caption"))
        self.assertNotIn("#1300", self.visible_text(at))
        self.assertEqual(at.text_area(key="sg_text_19").value, fp.grades_draft()["proposal"]["text"])
        self.assertTrue(at.checkbox(key="sg_retire_19_0").value)  # on by default
        self.assertNotIn("sg_retire_19_1", [c.key for c in at.checkbox])  # only a live preference
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/rejected"), [])
        self.assert_plain(at)

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

    def test_approving_without_opening_details_ends_the_conflict(self):
        self.http.on("POST", fp.rule_url(19, "approve"), fp.approved("R-0014"))
        at = self.open(pin=PIN)
        at.button(key="sg_approve_19").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(19, "approve"), {"proposed_at": fp.grades_draft()["proposed_at"],
                                                      "retire": ["R-0001"]})

    def test_use_this_wording_and_undo_puts_the_old_one_back(self):
        self.http.on("POST", fp.rule_url(41, "approve"), fp.approved("R-0014", superseded="R-0012"))
        at = self.open(pin=PIN)
        at.button(key="sg_approve_41").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(41, "approve"), {"proposed_at": fp.wording_draft()["proposed_at"]})
        self.assertEqual(self.undo(at).done, "Undone. Your earlier wording is back.")
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0014", "retire"),
                                       fp.retired("R-0014", restored="R-0012")).body, {"reason": "undone"})

    def test_merge(self):
        self.http.on("POST", fp.rule_url(44, "approve"), fp.approved("R-0017", retired=["R-0012", "R-0010"]))
        at = self.open(pin=PIN)
        at.button(key="sg_approve_44").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(44, "approve"), {"proposed_at": fp.merge_draft()["proposed_at"]})

    def test_not_now_sets_it_aside_and_undo_reopens(self):
        self.http.on("POST", fp.rule_url(41, "reject"), fp.rejected_draft(41))
        at = self.open(pin=PIN)
        at.button(key="sg_reject_41").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url(41, "reject"), {})
        self.assertIn("Set aside.", self.toasts(at))
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

        def approve(call: Call):
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
        self.assertIn(tv.PROPOSAL_CHANGED, self.texts(at, "warning"))
        self.assertEqual(self.texts(at, "error"), [])
        self.assertEqual(at.text_area(key="sg_text_19").value, "A newer wording from the wording assistant.")
        at.checkbox(key="sg_retire_19_0").uncheck()
        at.button(key="sg_approve_19").click().run()
        self.assertEqual(activated, [{"proposed_at": newer}])

    def test_a_merge_over_an_ended_preference_offers_only_keep_separate(self):
        body = fp.preferences()
        merge = next(s for s in body["suggestions"] if s["id"] == 44)
        merge["replaces_detail"][1].update(status="retired", status_text="ended", ended=True)
        merge["outdated"] = True
        self.http.on("GET", PILOT_HUB + "/preferences", body)
        self.http.on("POST", fp.rule_url(44, "reject"), fp.rejected_draft(44))
        at = self.open(pin=PIN)
        self.assertIn(tv.MERGE_STALE, self.texts(at, "caption"))
        self.assertIn("Crypto price recaps. (ended)", self.html(at))
        self.assertNotIn("sg_approve_44", {getattr(b, "key", None) for b in at.button})
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
        self.assertIn(tv.MERGE_OUTDATED, self.texts(at, "warning"))
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/preferences")), 2)

    def test_an_ended_preference_offers_approve_as_new(self):
        calls: list[dict] = []

        def approve(call: Call):
            calls.append(call.body)
            if not call.body.get("as_new"):
                return fp.refusal(409, "target_retired", tv.TARGET_RETIRED, target_precedent_id="R-0012")
            return fp.approved("R-0018")

        self.http.on("POST", fp.rule_url(41, "approve"), approve)
        at = self.open(pin=PIN)
        at.button(key="sg_approve_41").click().run()
        self.assert_clean(at)
        self.assertIn(tv.TARGET_RETIRED, self.texts(at, "info"))
        at.button(key="sg_as_new_41").click().run()
        self.assert_clean(at)
        self.assertEqual(calls[-1], {"proposed_at": fp.wording_draft()["proposed_at"], "as_new": True})
        self.assertIn(f"Approved. {eff()}".strip(), self.toasts(at))

    def test_other_refusals_in_plain_words(self):
        self.http.on("POST", fp.rule_url(19, "approve"), fp.refusal(409, "draft_closed", "rule draft 19 is approved"))
        at = self.open(pin=PIN)
        at.button(key="sg_approve_19").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. This suggestion was already handled meanwhile. Refresh to see where it stands.",
                      self.texts(at, "error"))
        self.assert_plain(at)


# ---------------------------------------------------------------------------------------------- suggested company names


ADD, REMOVE, FIX = "CS-6f708192", "CS-7081920a", "CS-2b3c4d5e"


def company_url(sid: str, action: str) -> str:
    return f"{PILOT_HUB}/companies/suggestions/{sid}/{action}"


class CompanyNamesTests(TuningCase):
    """docs/SPEC-COMPANY-MAP.md 6.3: suggested company names the source finder checked, under Needs your OK."""

    @staticmethod
    def pending_undo(at):
        try:
            return at.session_state[ui.UNDO_KEY]
        except KeyError:
            return None

    @staticmethod
    def card(at, sid: str) -> str:
        """The HTML of one suggested company name's card (inside its container zx_card_cs_<id>)."""
        box = next(n for n in AppCase.walk(at._tree) if getattr(n, "key", None) == f"zx_card_cs_{sid}")
        return "\n".join(str(m.value) for m in AppCase.walk(box) if getattr(m, "type", "") == "markdown")

    def test_the_cards_say_what_changes_and_what_the_source_finder_found(self):
        at = self.open()
        html = self.html(at)
        # in the one list, by when they arrived: after the ratings' suggestion, before the merge; then near the end
        order = [html.index(text) for text in ("Suggested from your ratings", "Red Cat Holdings",
                                               "Suggested merge of 2 preferences", "From a coverage request",
                                               "Rekor Systems", "Your draft, worded by the wording assistant")]
        self.assertEqual(order, sorted(order))
        add = self.card(at, ADD)
        self.assertIn('<span class="zx-chip suggested">Suggested name for <span class="co-name">Red Cat Holdings</span>'
                      '</span>', add)
        # the source finder's version (what an approval writes), the analyst's own name, the note and the reason
        self.assertIn('<div class="pref-text">Add <span class="co-name">Army Drone Dominance program</span> to '
                      'Customers &amp; programs</div>', add)
        self.assertIn('You wrote: <span class="co-name">Drone Dominance</span>', add)
        self.assertIn("U.S. Army plan to buy small drones in large numbers from 2026.", add)
        self.assertIn("Big customer: Expected: the Army plans to buy about 1 million drones", add)
        self.assertIn(f'<div class="preview-line">Confirmed: <a class="source-link" href="{fp.DRONE_URL}" '
                      'target="_blank" rel="noopener noreferrer">Red Cat selected for the Army&#x27;s &lt;Drone '
                      'Dominance&gt; program</a>, Sep 30, 2026</div>', add)
        # Details: what the source finder found, its sources (a javascript: link is no link), what the analyst sent
        self.assertIn("What the source finder found", add)
        self.assertIn("Red Cat&#x27;s September release names the program; management expects orders in 2026.", add)
        self.assertIn("2 sources", add)
        self.assertIn('<div class="grade-line">Red Cat Q2 2026 earnings call, Aug 2026</div>', add)
        self.assertNotIn("javascript:", html)
        self.assertIn('Also known as</div><div class="grade-line"><span class="co-name">Drone Dominance</span>', add)
        for line in ("What it is: Army plan to buy drones at scale", "Big customer: Management expects big orders",
                     "Your note: Heard it on the Q2 call.", 'href="https://example.com/drone-dominance-news"'):
            self.assertIn(line, add)
        # a removal the source finder could not confirm; its name trips the jargon guard, so it is drawn as a name
        remove = self.card(at, REMOVE)
        self.assertIn('<div class="pref-text">Remove <span class="co-name">Rekor Scout</span> from Products &amp; '
                      'brands</div>', remove)
        self.assertIn("Folded into Rekor Discover in 2025", remove)
        self.assertNotIn("Big customer", remove)
        self.assertIn('<div class="preview-line">Could not confirm. What the source finder found is under '
                      'Details.</div>', remove)
        self.assertIn('still lists <span class="co-name">Rekor Scout</span> as a product', remove)
        self.assertIn('“<span class="co-name">Rekor Scout</span> remains our license-plate recognition product.”',
                      remove)
        self.assertEqual([at.button(key=f"cs_{verb}_{sid}").label for sid in (ADD, REMOVE)
                          for verb in ("approve", "reject")], ["Approve", "Reject", "Approve", "Reject"])
        self.assertEqual({e.proto.expanded for e in at.expander if e.label == "Details"}, {False})
        # Tuning makes no new read, and nothing is sent
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/companies/suggestions"), [])
        self.assertEqual(self.http.posts(), [])
        self.assert_plain(at)
        self.assert_no_secrets(at)

    def test_a_rename_without_a_company_name_or_a_check(self):
        unchecked = fp.company_row("CS-3c4d5e6f", "RCAT", "Red Cat Holdings", "units", "add", "Skypersonic",
                                   hours=9, verdict=None)
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(
            suggestions=[], companies=[fp.company_fix(), unchecked, {"id": "CS-zz", "status": "proposed"}, None]))
        self.http.on("GET", PILOT_HUB + "/rules", {"drafts": []})
        at = self.open()
        self.assertIn("Needs your OK · 2", self.html(at))
        fix = self.card(at, FIX)
        # the hub sent no company name: the names on file (GET /brief, cached) give it
        self.assertIn('Suggested name for <span class="co-name">Planet Labs</span>', fix)
        self.assertIn('Fix <span class="co-name">Planet Insights Platform</span> in Products &amp; brands: call it '
                      '<span class="co-name">Planet Insights</span>', fix)
        self.assertIn('<div class="preview-line">Could not confirm.</div>', fix)
        unchecked = self.card(at, "CS-3c4d5e6f")
        self.assertIn(esc(cnv.NOT_CHECKED), unchecked)
        self.assertNotIn("What the source finder found", unchecked)  # Details holds only what the analyst sent
        self.assertIn('What you sent</div><div class="grade-lines"><div class="grade-line">Name: <span '
                      'class="co-name">Skypersonic</span></div></div>', unchecked)
        self.assert_plain(at)

    def test_a_removal_or_fix_without_names_names_the_entry_on_file(self):
        """A removal sent without its name and a fix that changes only the big flag (the hub sends neither the company's
        name nor the entry's): the card names both from the names on file, and big comes as the stored 1."""
        removal = fp.company_remove(name=None, company_name=None)
        big_only = fp.company_row("CS-0b1c2d3e", "RCAT", None, "customers", "change", None, hours=3,
                                  target_id="c-air-force", big=1,
                                  basis_text="Named as a top customer on the Q2 2026 call")
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(suggestions=[], companies=[removal, big_only]))
        self.http.on("GET", PILOT_HUB + "/rules", {"drafts": []})
        at = self.open()
        self.assert_clean(at)
        self.assertIn("Needs your OK · 2", self.html(at))
        card = self.card(at, "CS-0b1c2d3e")
        self.assertIn('Suggested name for <span class="co-name">Red Cat Holdings</span>', card)
        self.assertIn('<div class="pref-text">Fix <span class="co-name">U.S. Air Force</span> in Customers &amp; '
                      'programs</div>', card)
        self.assertIn("Big customer: Named as a top customer on the Q2 2026 call", card)
        card = self.card(at, REMOVE)
        self.assertIn('Suggested name for <span class="co-name">Rekor Systems</span>', card)
        self.assertIn('<div class="pref-text">Remove <span class="co-name">Rekor Scout</span> from Products &amp; '
                      'brands</div>', card)
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/brief")), 1)
        self.assert_plain(at)

    def test_approve_sends_the_version_shown_never_rules(self):
        def approve(call: Call):  # the hub now lists it approved: the card is gone
            self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(companies=[fp.company_remove()]))
            return fp.company_decided(ADD, "approved")

        self.http.on("POST", company_url(ADD, "approve"), approve)
        at = self.open(pin=PIN)
        at.button(key=f"cs_approve_{ADD}").click().run()
        self.assert_clean(at)
        self.assert_post(company_url(ADD, "approve"), {"use": "proposal"})
        self.assertEqual([c.url for c in self.http.posts()], [company_url(ADD, "approve")])  # never /rules
        self.assertIn(cnv.APPROVED, self.toasts(at))
        self.assertEqual(cnv.APPROVED,
                         "Approved. The ZENITH editor uses it from the next briefing. The builder adds it to story "
                         "tagging with the next update.")
        self.assertIsNone(self.pending_undo(at))  # no undo
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/preferences")), 2)  # read again
        self.assertNotIn(f"cs_approve_{ADD}", [b.key for b in at.button])
        self.assertIn("Needs your OK · 7", self.html(at))

    def test_approve_as_typed_when_there_is_no_proposal_and_reject(self):
        self.http.on("POST", company_url(REMOVE, "approve"), fp.company_decided(REMOVE, "approved"))
        self.http.on("POST", company_url(ADD, "reject"), fp.company_decided(ADD, "rejected"))
        at = self.open(pin=PIN)
        at.button(key=f"cs_approve_{REMOVE}").click().run()
        self.assert_clean(at)
        self.assert_post(company_url(REMOVE, "approve"), {"use": "as_typed"})
        self.assertIn(cnv.APPROVED_REMOVAL, self.toasts(at))  # a removal stops counting: never "uses it"
        at.button(key=f"cs_reject_{ADD}").click().run()
        self.assert_clean(at)
        self.assertEqual(len(self.http.posts()), 1)  # Reject asks first: no route reverses it
        self.assertIn(esc(cnv.REJECT_MESSAGE), self.html(at))
        self.assertIn(labels.NO_UNDO, self.texts(at, "caption"))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_post(company_url(ADD, "reject"), {})
        self.assertIn(cnv.REJECTED, self.toasts(at))
        self.assertIsNone(self.pending_undo(at))
        self.assertNotIn("dlg_save", [b.key for b in at.button])  # closed
        self.assertFalse(any("/rules/" in c.url for c in self.http.posts()))

    def test_reject_can_be_cancelled_and_a_suggestion_decided_meanwhile_is_said(self):
        self.http.on("POST", company_url(ADD, "reject"), fp.refusal(
            409, "suggestion_closed", "This suggestion was already decided.", status="approved"))
        at = self.open(pin=PIN)
        at.button(key=f"cs_reject_{ADD}").click().run()
        at.button(key="dlg_cancel").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertNotIn("dlg_save", [b.key for b in at.button])
        reads = len(self.http.find("GET", PILOT_HUB + "/preferences"))
        at.button(key=f"cs_reject_{ADD}").click().run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn(cnv.CLOSED, self.texts(at, "warning"))
        self.assertEqual((self.texts(at, "error"), self.toasts(at)), ([], []))
        self.assertNotIn("dlg_save", [b.key for b in at.button])
        self.assertGreater(len(self.http.find("GET", PILOT_HUB + "/preferences")), reads)

    def test_a_suggestion_decided_meanwhile_is_said_and_read_again(self):
        self.http.on("POST", company_url(ADD, "approve"), fp.refusal(
            409, "suggestion_closed", "This suggestion was already decided.", status="rejected"))
        at = self.open(pin=PIN)
        reads = len(self.http.find("GET", PILOT_HUB + "/preferences"))
        at.button(key=f"cs_approve_{ADD}").click().run()
        self.assert_clean(at)
        self.assertIn(cnv.CLOSED, self.texts(at, "warning"))
        self.assertEqual(self.texts(at, "error"), [])
        self.assertEqual(self.toasts(at), [])
        self.assertGreater(len(self.http.find("GET", PILOT_HUB + "/preferences")), reads)
        self.assert_plain(at)

    def test_other_refusals_in_plain_words(self):
        self.http.on("POST", company_url(REMOVE, "reject"), fp.refusal(503, "unavailable", "The database is busy."))
        at = self.open(pin=PIN)
        at.button(key=f"cs_reject_{REMOVE}").click().run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. The database is busy.", self.texts(at, "error"))
        self.assertIn("dlg_save", [b.key for b in at.button])  # the confirmation stays open
        self.assertEqual(self.toasts(at), [])
        self.assert_plain(at)

    def test_locked_buttons_are_visible_but_disabled(self):
        at = self.open()
        for key in (f"cs_approve_{ADD}", f"cs_reject_{ADD}", f"cs_approve_{REMOVE}", f"cs_reject_{REMOVE}"):
            self.assertTrue(at.button(key=key).disabled, key)
            self.assertEqual(at.button(key=key).help, labels.LOCKED_HELP)
        self.assertEqual(self.http.posts(), [])

    def test_an_older_hub_or_odd_rows_never_break_the_page(self):
        for companies in ("x", [None, 7, {"id": "CS-6f708192", "status": "proposed", "verdict": "{not json",
                                         "column": "x", "action": "x", "big": "yes"}]):
            with self.subTest(companies=companies):
                self.fresh()
                body = fp.preferences(suggestions=[])
                body["company_suggestions"] = companies
                self.http.on("GET", PILOT_HUB + "/preferences", body)
                self.http.on("GET", PILOT_HUB + "/rules", {"drafts": []})
                at = self.open()
                self.assert_plain(at)
        self.assertIn("Needs your OK · 1", self.html(at))
        self.assertIn("Change a name", self.card(at, ADD))
        self.assertNotIn(f"cs_details_{ADD}", [e.key for e in at.expander])  # nothing more to read: no Details
        body = fp.preferences(suggestions=[])
        body.pop("company_suggestions")  # a hub before schema 13
        self.fresh()
        self.http.on("GET", PILOT_HUB + "/preferences", body)
        self.assertNotIn("Needs your OK", self.html(self.open()))


# ---------------------------------------------------------------------------------------------- How much


class HowMuchTests(TuningCase):
    def test_one_row_from_the_hubs_modes(self):
        at = self.open()
        control = at.segmented_control(key=tv.VOLUME_MODE_KEY)
        self.assertEqual((control.value, list(control.options)),
                         ("standard", ["Only the big ones", "Standard", "Everything notable"]))
        self.assertFalse(at.toggle(key=tv.VOLUME_SHELF_KEY).value)
        self.assertEqual(at.toggle(key=tv.VOLUME_SHELF_KEY).label, "Near misses under each briefing")
        self.assertIn("Up to 12 stories that clear the usual bar. This is your current setting.", self.html(at))
        self.assertTrue(at.button(key="tn_volume_save").disabled)
        self.assertIn(tv.VOLUME_CAPTION, self.texts(at, "caption"))
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/settings/volume/preview"), [])
        row = next(n for n in self.walk(at._tree) if getattr(n, "key", None) == "zx_how_much")
        keys = {getattr(n, "key", None) for n in self.walk(row)}
        self.assertTrue({tv.VOLUME_MODE_KEY, tv.VOLUME_SHELF_KEY, "tn_volume_save"} <= keys)  # one row

    def test_preview_save_and_undo(self):
        self.http.on("POST", PILOT_HUB + "/settings/volume", fp.volume_set("top"))
        at = self.open(pin=PIN)
        at.segmented_control(key=tv.VOLUME_MODE_KEY).set_value("top").run()
        self.assert_clean(at)
        self.assertIn(fp.PREVIEW_TEXT["top"], self.html(at))
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/settings/volume/preview")[-1].params.get("mode"), "top")
        self.assertFalse(at.button(key="tn_volume_save").disabled)
        at.button(key="tn_volume_save").click().run()
        self.assert_clean(at)
        self.assert_post(PILOT_HUB + "/settings/volume", {"mode": "top", "near_miss_shelf": False})
        self.assertIn(f"Now: Only the big ones. {eff()}".strip(), self.toasts(at))
        call = self.run_undo(at, PILOT_HUB + "/settings/volume", fp.volume_set("standard"))
        self.assertEqual(call.body, {"mode": "standard", "near_miss_shelf": False})

    def test_near_miss_shelf_switch(self):
        self.http.on("POST", PILOT_HUB + "/settings/volume", fp.volume_set("standard", True))
        at = self.open(pin=PIN)
        at.toggle(key=tv.VOLUME_SHELF_KEY).set_value(True).run()
        self.assert_clean(at)
        preview = self.http.find("GET", PILOT_HUB + "/settings/volume/preview")[-1]
        self.assertIn(str(preview.params.get("near_miss_shelf")), ("1", "True", "true"))
        at.button(key="tn_volume_save").click().run()
        self.assert_post(PILOT_HUB + "/settings/volume", {"mode": "standard", "near_miss_shelf": True})

    def test_a_changed_saved_setting_moves_the_choice(self):
        at = self.open()
        self.http.on("GET", PILOT_HUB + "/settings", fp.settings("broad"))
        self.fresh()
        at.run()
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key=tv.VOLUME_MODE_KEY).value, "broad")

    def test_unreadable_settings(self):
        self.http.routes.pop(("GET", PILOT_HUB + "/settings"))
        at = self.open()
        self.assertIn("Couldn't load your 'how much' setting.", self.visible_text(at))
        self.assertIn("Your rules · 9", self.html(at))


# ---------------------------------------------------------------------------------------------- Your rules


class RulesTests(TuningCase):
    def test_one_list_with_pills_and_counts(self):
        at = self.open()
        pills = at.pills(key=tv.RULES_KEY)
        self.assertEqual((pills.value, list(pills.options)),
                         ("all", ["All · 9", "More · 1", "Less · 2", "Muted · 3", "Watchlist · 2"]))
        self.assertEqual(self.rule_rows(at), ["pref_R-0012", "pref_R-0010", "pref_I-0007", "pref_R-0001", "mute_4",
                                              "mute_5", "mute_6", "star_2", "star_3"])
        html = self.html(at)
        # what kind, its words, one impact line, an optional hint
        self.assertIn("Lowered 12 stories in 30 days (11 kept out) · last used 5h ago", html)
        self.assertIn("Raised 5 stories in 30 days (2 made the briefing) · last used 2d ago", html)
        self.assertIn("Brought in 0 · kept out 0 in 30 days · not used yet", html)
        self.assertIn("Example: Shares jump 8% on AI &lt;hopes&gt; (Yahoo Finance)", html)
        self.assertIn("Hid 12 stories this week (30 in all)", html)
        self.assertIn("1 story this week, 0 in your briefing", html)
        self.assertIn("Muted company", html)
        self.assertIn("Not part of the &lt;thesis&gt;", html)
        hints = re.findall(r'<div class="tn-hint">(.*?)</div>', html)
        self.assertEqual(hints[0], "A clearer wording is waiting under Needs your OK.")
        self.assertTrue(hints[1].startswith("Paused since ") and hints[1].endswith(
            ". The editor ignores it until you resume it."), hints[1])
        self.assertEqual(hints[2], "Not used in 30 days. Still useful?")
        self.assertEqual(len(hints), 3)
        self.assertNotIn("IREN", html)  # removed from the watchlist
        visible = self.visible_text(at)
        self.assertNotIn("R-0012", visible)
        self.assertNotIn("event #", visible)
        self.assertNotIn("suppressed", visible.lower())

    def test_the_pills_filter_and_go_into_the_link(self):
        at = self.open()
        at.pills(key=tv.RULES_KEY).set_value("muted").run()
        self.assert_clean(at)
        self.assertEqual(self.rule_rows(at), ["mute_4", "mute_5", "mute_6"])
        self.assertEqual(at.query_params.get("rules"), "muted")
        self.assertIn(tv.FILTER_NOTES["muted"], self.texts(at, "caption"))
        at.button(key="tn_open_coverage").click().run()
        self.assertEqual(at.session_state["zx_tab"], "coverage")
        at = self.open(query={"rules": "less"})
        self.assertEqual(self.rule_rows(at), ["pref_R-0012", "pref_R-0010"])
        at.pills(key=tv.RULES_KEY).set_value("watchlist").run()
        self.assertEqual(self.rule_rows(at), ["star_2", "star_3"])
        self.assertIn(labels.STAR_PROMISE, self.texts(at, "caption"))
        at.pills(key=tv.RULES_KEY).set_value("more").run()
        self.assertEqual(self.rule_rows(at), ["pref_I-0007"])
        at.pills(key=tv.RULES_KEY).set_value("all").run()
        self.assertNotIn("rules", at.query_params)

    def test_a_pref_link_highlights_its_row_and_shows_all(self):
        at = self.open(query={"pref": "I-0007", "rules": "muted"}, state={tv.RULES_KEY: "muted"})
        self.assertEqual(self.rule_rows(at), ["mute_4", "mute_5", "mute_6"])  # a rules link wins
        at = self.open(query={"pref": "I-0007"})
        self.assertEqual(at.pills(key=tv.RULES_KEY).value, "all")
        self.assertEqual(self.rule_rows(at)[0], "pref_I-0007")  # first, highlighted
        html = self.html(at)
        focused = html.index('<div class="tn-rule zx-focus">')
        self.assertIn(esc(text_of("I-0007")), html[focused:focused + 800])
        self.assertEqual(html.count("zx-focus"), 1)

    def test_a_preferences_menu_has_no_pause(self):
        at = self.menu(self.open(pin=PIN), "pref_R-0012")
        self.assertEqual(self.menu_labels(at, "pref_R-0012"),
                         ["Edit", "End date", "Remove", f"Mute {fp.MUTE_LABEL} instead"])
        at = self.menu(self.open(pin=PIN), "pref_I-0007")
        self.assertEqual(self.menu_labels(at, "pref_I-0007"), ["Resume", "Edit", "End date", "Remove"])
        self.assertNotIn("Pause", [b.label for b in at.button])
        at = self.menu(self.open(pin=PIN), "mute_4")
        self.assertEqual(self.menu_labels(at, "mute_4"), ["Unmute"])
        at = self.menu(self.open(pin=PIN), "star_2")
        self.assertEqual(self.menu_labels(at, "star_2"), ["Remove from watchlist"])

    def test_resume_a_paused_preference_with_undo(self):
        self.http.on("POST", fp.rule_url("I-0007", "resume"), fp.lifecycle("I-0007", "active"))
        at = self.menu(self.open(pin=PIN), "pref_I-0007", "tn_resume_pref_I-0007")
        self.assert_post(fp.rule_url("I-0007", "resume"), {})
        self.assertIn(f"Resumed. {eff()}".strip(), self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("I-0007", "pause")).body, {})

    def test_a_refusal_in_a_menu_is_said_in_a_toast(self):
        self.http.on("POST", fp.rule_url("I-0007", "resume"), fp.refusal(
            409, "superseded", "A newer version, R-0019, replaced this preference. Change that one instead."))
        at = self.menu(self.open(pin=PIN), "pref_I-0007", "tn_resume_pref_I-0007")
        self.assertIn("Not saved. A newer wording replaced this preference. Change that one instead.", self.toasts(at))
        self.assert_plain(at)

    def test_edit_makes_a_new_version_and_undo_restores(self):
        self.http.on("POST", fp.rule_url("R-0012", "edit"), fp.edited("R-0015", "R-0012"))
        at = self.menu(self.open(pin=PIN), "pref_R-0012", "tn_edit_pref_R-0012")
        self.assertEqual(at.text_area(key="dlg_text").value, text_of("R-0012"))
        self.assertEqual(at.radio(key="dlg_direction").value, "less")
        self.assertEqual(at.radio(key="dlg_scope").value, "standing")
        at.text_area(key="dlg_text").set_value("Stock-move articles with no new company facts.")
        at.radio(key="dlg_scope").set_value("similar")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("R-0012", "edit"), {"text": "Stock-move articles with no new company facts.",
                                                          "scope": "similar"})
        self.assertIn(f"Saved your new wording. {eff()}".strip(), self.toasts(at))
        self.assertNotIn("dlg_save", [b.key for b in at.button])
        self.assertEqual(self.undo(at).done, "Undone. Your earlier wording is back.")
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0015", "retire")).body, {"reason": "undone"})

    def test_end_date_clear_and_set(self):
        previous = next(p for p in fp.preference_rows() if p["id"] == "I-0007")["expires_at"]
        self.http.on("POST", fp.rule_url("I-0007", "end-date"), fp.lifecycle("I-0007", "paused"))
        at = self.menu(self.open(pin=PIN), "pref_I-0007", "tn_end_pref_I-0007")
        at.radio(key="dlg_choice").set_value("none").run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("I-0007", "end-date"), {"expires_at": None})
        self.assertIn("No end date.", self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("I-0007", "end-date")).body, {"expires_at": previous})
        self.http.on("POST", fp.rule_url("R-0012", "end-date"), fp.lifecycle("R-0012"))
        day = tv.local_today(TZ) + timedelta(days=45)
        at = self.menu(at, "pref_R-0012", "tn_end_pref_R-0012")
        at.date_input(key="dlg_until").set_value(day)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        expires = tv.expires_iso(day, TZ)
        self.assert_post(fp.rule_url("R-0012", "end-date"), {"expires_at": expires})
        self.assertIn(f"It ends on {tv.fmt_date(expires, TZ)}.", self.toasts(at))

    def test_remove_asks_first_and_undo_brings_it_back(self):
        self.http.on("POST", fp.rule_url("R-0010", "retire"), fp.retired("R-0010"))
        at = self.menu(self.open(pin=PIN), "pref_R-0010", "tn_remove_pref_R-0010")
        self.assertEqual(self.http.posts(), [])  # nothing until confirmed
        self.assertIn(tv.REMOVE_MESSAGE, self.visible_text(at))
        self.click(at, "dlg_save")
        self.assert_clean(at)
        self.assert_post(fp.rule_url("R-0010", "retire"), {})
        self.assertIn("Removed.", self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0010", "reactivate")).body, {})

    def test_mute_instead_opens_the_mute_dialog(self):
        at = self.menu(self.open(pin=PIN), "pref_R-0012", "tn_mute_instead_pref_R-0012")
        self.assertEqual(at.session_state[ui.DIALOG_KEY]["name"], "mute")
        preview = self.http.find("GET", PILOT_HUB + "/mutes/preview")[-1]
        self.assertEqual({k: preview.params.get(k) for k in ("kind", "module", "ref")},
                         {"kind": "source", "module": "ai-infra", "ref": "gn-themes"})
        self.assertEqual(self.http.posts(), [])

    def test_unmute_opens_the_unmute_dialog(self):
        at = self.menu(self.open(pin=PIN), "mute_4", "tn_unmute_mute_4")
        self.assertEqual(at.session_state[ui.DIALOG_KEY]["name"], "unmute")
        self.assertIn("Bring back what it hid in the last 7 days (12 stories)", list(at.radio(key="dlg_choice").options))
        self.assertEqual(self.http.posts(), [])

    def test_remove_from_watchlist(self):
        self.http.on("POST", PILOT_HUB + "/stars", {"star": {"id": 2, "entity_id": "coreweave", "active": False},
                                                    "removed": True, "effective": fp.effective()})
        at = self.menu(self.open(pin=PIN), "star_2", "tn_unstar_star_2")
        self.assert_post(PILOT_HUB + "/stars", {"action": "remove", "entity_id": "coreweave"})
        self.assertIn("CoreWeave removed from your watchlist.", self.toasts(at))

    def test_add_a_rule_with_an_end_date_then_undo(self):
        self.http.on("POST", PILOT_HUB + "/preferences", fp.created("R-0016"))
        at = self.open(pin=PIN)
        self.click(at, "tn_add")
        self.assertEqual(at.session_state[ui.DIALOG_KEY]["name"], "add_rule")
        self.assertEqual(list(at.radio(key="dlg_direction").options),
                         ["Show me more like this", "Show me less like this", "Exactly as I write it"])
        until = tv.local_today(TZ) + timedelta(days=10)
        at.radio(key="dlg_direction").set_value("less")
        at.text_area(key="dlg_text").set_value("crypto")
        at.button(key="dlg_save").click().run()
        self.assertIn(tv.TOO_SHORT, self.texts(at, "info"))
        self.assertEqual(self.http.posts(), [])
        at.text_area(key="dlg_text").set_value("  Fewer crypto price recaps unless a miner announces AI hosting.  ")
        at.checkbox(key="dlg_until_on").check().run()
        at.date_input(key="dlg_until").set_value(until)
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_post(PILOT_HUB + "/preferences", {
            "direction": "less", "scope": "standing",
            "text": "Fewer crypto price recaps unless a miner announces AI hosting.",
            "expires_at": tv.expires_iso(until, TZ)})
        self.assertIn(f"Added: Show me less like this. {eff()}".strip(), self.toasts(at))
        self.assertNotIn("dlg_save", [b.key for b in at.button])
        self.assertEqual(self.undo(at).text, "Added a preference.")
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0016", "retire"), fp.retired("R-0016")).body,
                         {"reason": "undone"})

    def test_soft_cap(self):
        self.http.on("GET", PILOT_HUB + "/preferences", fp.preferences(over=True))
        at = self.open()
        self.assertIn("You have 41 active preferences. Older ones may conflict; the wording assistant suggests merges "
                      "once a month.", self.texts(at, "info"))

    def test_no_rules_yet(self):
        body = fp.preferences(suggestions=[])
        body["preferences"] = []
        self.http.on("GET", PILOT_HUB + "/preferences", body)
        self.http.on("GET", PILOT_HUB + "/mutes", {"mutes": [], "active_count": 0})
        self.http.on("GET", PILOT_HUB + "/stars", {"stars": []})
        at = self.open()
        self.assertIn(esc(tv.EMPTY_RULES), self.html(at))
        self.assertIn("Your rules · 0", self.html(at))
        at.pills(key=tv.RULES_KEY).set_value("muted").run()
        self.assertIn(esc(tv.EMPTY_FILTER["muted"]), self.html(at))


# ---------------------------------------------------------------------------------------------- Ended


class EndedTests(TuningCase):
    def test_ended_preferences_and_removed_mutes_in_one_collapsed_list(self):
        at = self.open()
        self.assertNotIn("pf_bring_back_R-0005", [b.key for b in at.button])  # collapsed, lazy
        self.open_expander(at, tv.ENDED_KEY)
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        for reason in ("You removed it", "Its end date passed", "Replaced by a newer wording"):
            self.assertIn(reason, html)
        self.assertIn("Old trade feed", html)
        self.assertIn("Brought back", self.texts(at, "caption"))
        self.assertNotIn("pf_bring_back_m1", [b.key for b in at.button])  # already brought back
        self.assertEqual(at.button(key="pf_bring_back_m2").label, "Bring back the last 7 days")
        keys = [str(n.key) for n in self.walk(at._tree) if str(getattr(n, "key", "") or "").startswith("zx_ended_")]
        self.assertEqual(keys, ["zx_ended_pref_R-0005", "zx_ended_pref_I-0003", "zx_ended_mute_2",
                                "zx_ended_mute_1", "zx_ended_pref_R-0009"])  # the most recently ended first

    def test_bring_back_a_preference_and_undo(self):
        self.http.on("POST", fp.rule_url("R-0005", "reactivate"), fp.lifecycle("R-0005"))
        at = self.open(pin=PIN, state={tv.ENDED_KEY: True})
        self.open_expander(at, tv.ENDED_KEY)
        at.button(key="pf_bring_back_R-0005").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("R-0005", "reactivate"), {})
        self.assertIn(f"Brought back. {eff()}".strip(), self.toasts(at))
        self.assertEqual(self.run_undo(at, fp.rule_url("R-0005", "retire")).body, {})

    def test_bringing_back_an_expired_preference_asks_for_an_end_date(self):
        self.http.on("POST", fp.rule_url("I-0003", "reactivate"), fp.lifecycle("I-0003"))
        at = self.open(pin=PIN, state={tv.ENDED_KEY: True})
        self.open_expander(at, tv.ENDED_KEY)
        at.button(key="pf_bring_back_I-0003").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertEqual(at.radio(key="dlg_choice").value, "none")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assert_post(fp.rule_url("I-0003", "reactivate"), {"expires_at": None})

    def test_bring_back_a_removed_mute(self):
        self.http.on("POST", PILOT_HUB + "/mutes", {"mute": fp.mute(2, "source", "old-feed", "Old trade feed",
                                                                    module="ai-infra", active=False, removed_hours=30,
                                                                    brought_back=True),
                                                    "brought_back": 5, "requeued": 4, "effective": fp.effective()})
        at = self.open(pin=PIN, state={tv.ENDED_KEY: True})
        self.open_expander(at, tv.ENDED_KEY)
        at.button(key="pf_bring_back_m2").click().run()
        self.assert_clean(at)
        self.assert_post(PILOT_HUB + "/mutes", {"action": "bring_back", "mute_id": 2, "days": 7})

    def test_a_link_to_an_ended_preference_opens_the_list(self):
        at = self.open(query={"pref": "R-0005"})
        self.assertIn('<div class="pref-card zx-focus"><div class="pref-text">', self.html(at))


if __name__ == "__main__":
    unittest.main()
