"""Unit tests: the pure helpers of Tuning (docs/SPEC-SIMPLIFY.md 2.3) and What ZENITH looks for (no Streamlit run)."""

from __future__ import annotations

import re
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import fixtures_tuning as fp
import helpers  # noqa: F401  (puts dashboard/ on sys.path)

from zenux_dashboard import api, labels
from zenux_dashboard import brief_view as bv
from zenux_dashboard import tuning_view as pv

NOW = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)


class SummaryAndStatsTests(unittest.TestCase):
    def test_summary_sentence(self):
        self.assertEqual(pv.summary_sentence({"hits": 23, "promoted": 4, "suppressed": 15, "raised": 3, "lowered": 1}),
                         "This week your preferences changed 23 decisions: 4 brought into a briefing, 15 kept out, "
                         "3 raised, 1 lowered.")
        self.assertEqual(pv.summary_sentence({"hits": 1, "suppressed": 1}),
                         "This week your preferences changed 1 decision: 1 kept out.")
        self.assertEqual(pv.summary_sentence({"hits": 2}), "This week your preferences changed 2 decisions.")
        for empty in (None, {}, {"hits": 0, "promoted": 3}, "x"):
            self.assertEqual(pv.summary_sentence(empty), pv.SUMMARY_NONE)

    def test_stats_line_by_direction_never_says_suppressed(self):
        stats = {"promoted_30d": 2, "suppressed_30d": 11, "raised_under_bar_30d": 3, "lowered_in_briefing_30d": 1,
                 "last_hit_at": (NOW - timedelta(hours=5)).isoformat()}
        more = pv.stats_line({"direction": "more", "stats": stats}, NOW)
        less = pv.stats_line({"direction": "less", "stats": stats}, NOW)
        exact = pv.stats_line({"direction": "exact", "stats": stats}, NOW)
        legacy = pv.stats_line({"direction": None, "stats": {}}, NOW)
        self.assertEqual(more, "Raised 5 stories in 30 days (2 made the briefing) · last used 5h ago")
        self.assertEqual(less, "Lowered 12 stories in 30 days (11 kept out) · last used 5h ago")
        self.assertEqual(exact, "Brought in 2 · kept out 11 in 30 days · last used 5h ago")
        self.assertEqual(legacy, "Brought in 0 · kept out 0 in 30 days · not used yet")
        self.assertEqual(pv.stats_line({"direction": "more", "stats": {"promoted_30d": 1}}, NOW),
                         "Raised 1 story in 30 days (1 made the briefing) · not used yet")
        for line in (more, less, exact, legacy):
            self.assertNotIn("suppress", line.lower())

    def test_row_meta_example_and_offers(self):
        rows = {p["id"]: p for p in fp.preference_rows()}
        self.assertEqual(pv.rule_meta({"scope": "similar", "status": "active"}, fp.TZ), "Stories like this")
        self.assertEqual(pv.rule_meta({"scope": None, "status": "paused"}, fp.TZ), "Standing preference")
        self.assertIn(" · until ", pv.rule_meta(rows["I-0007"], fp.TZ))
        self.assertEqual(pv.example_line(rows["R-0012"]), "Example: Shares jump 8% on AI <hopes> (Yahoo Finance)")
        self.assertEqual(pv.example_line({"example": {"title": "Only a title"}}), "Example: Only a title")
        self.assertEqual(pv.example_line({"example": None}), "")
        mute = rows["R-0012"]["stats"]["looks_like_mute"]
        self.assertEqual(pv.looks_like_mute_text(mute),
                         f"91% of what it kept out came from {fp.MUTE_LABEL}. Mute it instead?")
        self.assertEqual(pv.looks_like_mute_text({"label": "Example Co", "share": None}),
                         "Most of what it kept out came from Example Co. Mute it instead?")

    def test_ended_reasons_and_bring_back(self):
        for reason, text in (("owner", "You removed it"), ("undone", "Undone"),
                             ("superseded", "Replaced by a newer wording"), ("conflict", "Ended by a newer preference"),
                             ("consolidated", "Merged into another preference"), ("expired", "Its end date passed"),
                             (None, "Ended"), ("odd", "Ended")):
            self.assertEqual(pv.ended_reason({"retired_reason": reason}), text)
        self.assertTrue(pv.needs_new_end_date({"retired_reason": "expired"}, NOW))
        self.assertTrue(pv.needs_new_end_date({"retired_reason": "owner", "expires_at": "2026-10-01T04:00:00Z"}, NOW))
        self.assertFalse(pv.needs_new_end_date({"retired_reason": "owner", "expires_at": "2026-12-01T05:00:00Z"}, NOW))
        self.assertFalse(pv.needs_new_end_date({"retired_reason": "owner"}, NOW))


class NeedsYourOkShapeTests(unittest.TestCase):
    def test_suggestions_and_legacy_drafts_newest_first_without_duplicates(self):
        cards = pv.needs_ok(fp.preferences(), fp.rules())
        # the suggested company names (docs/SPEC-COMPANY-MAP.md 6.3) are in the same list, by when they arrived
        self.assertEqual([c["id"] for c in cards], [45, 41, 19, "CS-6f708192", 44, 46, "CS-7081920a", 31])
        self.assertEqual(pv.needs_ok(None, None), [])
        # only proposed company names, each once; a row whose id is not a company suggestion's is left out
        body = fp.preferences(suggestions=[], companies=[
            fp.company_add(), fp.company_add(), fp.company_fix(status="approved"), {**fp.company_remove(), "id": 7},
            fp.company_remove(status=None), "x"])
        self.assertEqual([c["id"] for c in pv.needs_ok(body, None)], ["CS-6f708192", "CS-7081920a"])
        # gap 29: drafts the analyst sent that are with the wording assistant, from with_assistant (not GET /rules)
        self.assertEqual(pv.waiting_count(fp.preferences()), 1)  # the brief suggestion; the wording is the hub's own
        self.assertEqual(pv.waiting_count({"with_assistant": {"by_origin": {"feedback": 2, "owner": 1, "grades": 4}}}),
                         3)
        self.assertEqual(pv.waiting_count(None), 0)

    def test_heads_and_buttons_by_origin(self):
        self.assertEqual(pv.suggestion_head(fp.grades_draft()), "Suggested from your ratings")
        self.assertEqual(pv.suggestion_head(fp.wording_draft()), "Suggested wording for your preference")
        self.assertEqual(pv.suggestion_head(fp.merge_draft()), "Suggested merge of 2 preferences")
        self.assertEqual(pv.suggestion_head(fp.brief_draft()), "Your suggested change to What ZENITH looks for")
        self.assertEqual(pv.suggestion_head(fp.radar_draft()), "From a coverage request")
        self.assertEqual(pv.suggestion_head(fp.legacy_draft()), "Your draft, worded by the wording assistant")
        self.assertEqual(pv.suggestion_head({"origin": "feedback"}), "Your draft, worded by the wording assistant")
        self.assertEqual(pv.button_labels(fp.wording_draft()), ("Use this wording", "Keep mine"))
        self.assertEqual(pv.button_labels(fp.merge_draft()), ("Merge them", "Keep them separate"))
        self.assertEqual(pv.button_labels(fp.grades_draft()), ("Approve", "Not now"))

    def test_grade_lines(self):
        lines, more = pv.grade_lines(fp.grades_draft())
        self.assertEqual(len(lines), 5)
        self.assertEqual(more, 1)
        self.assertEqual(lines[0], "Conference webcast notice 0 <live> · you: Not relevant · editor: 74")
        self.assertEqual(lines[4], "Conference webcast notice 4 <live> · you: Not relevant · editor: left out")
        self.assertEqual(pv.grade_lines({"context": {"grades": [{"verdict": "lead", "grader_decision": "selected"}]}}),
                         (["A story · you: Top story · editor: in the briefing"], 0))
        self.assertEqual(pv.grade_lines({"context": None}), ([], 0))

    def test_impact_line(self):
        self.assertEqual(pv.impact_line(fp.grades_draft()),
                         "Would have brought 2 stories in and kept 1 out over the last 14 days.")
        self.assertEqual(pv.impact_line({"proposal": {"preview_summary": {"window_days": 7, "added": 1, "removed": 0}}}),
                         "Would have brought 1 story in over the last 7 days.")
        self.assertEqual(pv.impact_line(fp.wording_draft()), "Would have kept 9 stories out over the last 14 days.")
        self.assertEqual(pv.impact_line(fp.merge_draft()), "Would not have changed your briefings over the last 14 days.")
        self.assertEqual(pv.impact_line(fp.brief_draft()), "No preview yet.")
        for draft in (fp.grades_draft(), fp.wording_draft(), fp.merge_draft(), fp.radar_draft()):
            self.assertEqual(labels.find_jargon(pv.impact_line(draft)), [])

    def test_suggestion_html_is_escaped_and_plain(self):
        by_id = pv.preferences_by_id(fp.preferences())
        html = pv.suggestion_html(fp.grades_draft(), by_id, fp.TZ)
        self.assertNotIn("Conference webcast notice", html)  # the ratings behind it are in Details
        self.assertIn('<div class="preview-line">Would have brought 2 stories in and kept 1 out over the last 14 days.'
                      '</div>', html)
        details = pv.details_html(fp.grades_draft())
        self.assertIn("Conference webcast notice 0 &lt;live&gt;", details)
        self.assertNotIn("<live>", details)
        self.assertIn("Would come in · 2", details)
        self.assertIn("A story no longer available", details)
        self.assertEqual(pv.details_html(fp.legacy_draft()), "")
        for draft in (fp.merge_draft(), fp.wording_draft(), fp.brief_draft(), fp.radar_draft(), fp.legacy_draft()):
            html = pv.suggestion_html(draft, by_id, fp.TZ)
            self.assertEqual(labels.find_jargon(re.sub(r"<[^>]+>", " ", html)), [], html)
            self.assertNotIn("\n\n", html)
        self.assertIn("It replaces:", pv.suggestion_html(fp.merge_draft(), by_id, fp.TZ))

    def test_a_merge_over_an_ended_preference_says_so(self):
        # gap 28: the hub's `outdated` and `replaces_detail` decide
        by_id = pv.preferences_by_id(fp.preferences())
        self.assertFalse(pv.merge_is_stale(fp.merge_draft(), by_id))
        self.assertNotIn("(ended)", pv.suggestion_html(fp.merge_draft(), by_id, fp.TZ))
        ended = fp.merge_draft()
        ended["replaces_detail"][1].update(status="retired", status_text="ended", ended=True)
        ended["outdated"] = True
        self.assertTrue(pv.merge_is_stale(ended, by_id))  # even though the loaded R-0010 is still on
        self.assertIn("Crypto price recaps. (ended)", pv.suggestion_html(ended, by_id, fp.TZ))
        # an older hub without them: worked out from the preferences loaded
        older = {k: v for k, v in fp.merge_draft().items() if k not in ("replaces_detail", "outdated")}
        self.assertFalse(pv.merge_is_stale(older, by_id))
        by_id["R-0010"] = {**by_id["R-0010"], "status": "retired"}
        self.assertTrue(pv.merge_is_stale(older, by_id))
        self.assertIn("Crypto price recaps. (ended)", pv.suggestion_html(older, by_id, fp.TZ))
        self.assertTrue(pv.merge_is_stale(older, {}))
        self.assertFalse(pv.merge_is_stale(fp.grades_draft(), {}))

    def test_shown_wording_and_reasoning_are_the_plain_ones(self):
        draft = fp.grades_draft()
        draft["proposal_plain"]["text"] = "Plain words of the proposal."
        self.assertEqual(pv.shown_text(draft), "Plain words of the proposal.")
        # approving the plain words unedited sends no text: the proposal is kept as stored
        self.assertEqual(pv.approve_body(draft, "Plain words of the proposal.", []), {"proposed_at": draft["proposed_at"]})
        self.assertEqual(pv.shown_text({"proposal": {"text": "Stored."}}), "Stored.")
        # the reasoning: proposal_plain, with clean_rationale as the last guard ("#1300" -> another story)
        self.assertEqual(pv.shown_rationale(fp.grades_draft(), {}),
                         "Six of your ratings downgraded conference notices, e.g. another story.")

    def test_which_stories_lines(self):
        more = dict(fp.grades_draft(), preview_more=7)
        self.assertIn("and 7 more stories", pv.details_html(more))
        items = fp.grades_draft()["preview_items"]
        self.assertEqual(pv.preview_item_line(items[0]),
                         "Miner monthly production update · Miner Co. investor relations")
        self.assertEqual(pv.preview_item_line(items[1]), "A story no longer available")

    def test_approve_body(self):
        draft = fp.grades_draft()
        proposed = draft["proposal"]["text"]
        self.assertEqual(pv.approve_body(draft, proposed, []), {"proposed_at": draft["proposed_at"]})
        self.assertEqual(pv.approve_body(draft, f"  {proposed}  ", ["R-0001"]),
                         {"proposed_at": draft["proposed_at"], "retire": ["R-0001"]})
        self.assertEqual(pv.approve_body(draft, " New words. ", [], as_new=True),
                         {"proposed_at": draft["proposed_at"], "text": "New words.", "as_new": True})
        self.assertEqual(pv.approve_body({"id": 3, "proposed_at": None, "proposal": None, "text": "x"}, "x", []),
                         {"proposed_at": None})

    def test_lists(self):
        prefs = fp.preferences()
        self.assertEqual([p["id"] for p in pv.live_preferences(prefs)], ["R-0012", "R-0010", "I-0007", "R-0001"])
        self.assertEqual([p["id"] for p in pv.ended_preferences(prefs)], ["R-0005", "I-0003", "R-0009"])
        self.assertEqual([m["id"] for m in pv.active_mutes(fp.mutes())], [4, 5, 6])
        self.assertEqual([m["id"] for m in pv.removed_mutes(fp.mutes())], [2, 1])
        self.assertEqual([s["id"] for s in pv.active_stars(fp.stars())], [2, 3])
        for empty in (None, {}, [], "x"):
            self.assertEqual(pv.live_preferences(empty), [])
            self.assertEqual(pv.active_mutes(empty), [])
            self.assertEqual(pv.active_stars(empty), [])


class RulesListTests(unittest.TestCase):
    def test_one_list_preferences_mutes_watchlist(self):
        rules = pv.rules_of(fp.preferences(), fp.mutes(), fp.stars())
        self.assertEqual([(r["kind"], r["id"], r["filter"]) for r in rules],
                         [("pref", "R-0012", "less"), ("pref", "R-0010", "less"), ("pref", "I-0007", "more"),
                          ("pref", "R-0001", ""), ("mute", "4", "muted"), ("mute", "5", "muted"), ("mute", "6", "muted"),
                          ("star", "2", "watchlist"), ("star", "3", "watchlist")])
        self.assertEqual(pv.filter_counts(rules), {"all": 9, "more": 1, "less": 2, "muted": 3, "watchlist": 2})
        self.assertEqual([pv.filter_label(c, pv.filter_counts(rules)) for c, _ in pv.RULE_FILTERS],
                         ["All · 9", "More · 1", "Less · 2", "Muted · 3", "Watchlist · 2"])
        self.assertEqual(pv.filter_label("muted", {"muted": None}), "Muted")  # a read that failed
        self.assertEqual([r["id"] for r in pv.filtered_rules(rules, "less")], ["R-0012", "R-0010"])
        self.assertEqual([r["id"] for r in pv.filtered_rules(rules, "all", "I-0007")][:2], ["I-0007", "R-0012"])
        self.assertEqual(pv.rules_of(None, None, None), [])

    def test_kind_meta_impact_and_hints(self):
        rows = {p["id"]: p for p in fp.preference_rows()}
        self.assertEqual([pv.kind_label(rows[pid]) for pid in ("R-0012", "I-0007", "R-0001")],
                         ["Less like this", "More like this", "Exactly as I write it"])
        self.assertEqual(pv.rule_meta(rows["R-0012"], fp.TZ), "Standing preference")
        self.assertTrue(pv.rule_meta(rows["I-0007"], fp.TZ).startswith("Stories like this · until "))
        self.assertTrue(pv.preference_hint(rows["I-0007"], fp.TZ).startswith("Paused since "))
        self.assertEqual(pv.preference_hint(rows["R-0012"], fp.TZ), "A clearer wording is waiting under Needs your OK.")
        # the wording hint needs its card under Needs your OK; then the next hint shows
        self.assertEqual(pv.preference_hint(rows["R-0012"], fp.TZ, waiting={"19"}),
                         f"91% of what it kept out came from {fp.MUTE_LABEL}. Mute it instead?")
        self.assertEqual(pv.preference_hint(rows["R-0001"], fp.TZ), "Not used in 30 days. Still useful?")
        self.assertEqual(pv.preference_hint(rows["R-0010"], fp.TZ), "")
        self.assertEqual(pv.mute_impact(fp.mutes()["mutes"][0]), "Hid 12 stories this week (30 in all)")
        self.assertEqual(pv.mute_impact({"hidden_7d": 1, "hidden_total": 1}), "Hid 1 story this week (1 in all)")
        self.assertTrue(pv.mute_meta(fp.mutes()["mutes"][1], fp.TZ).endswith(" · Not part of the <thesis>"))
        self.assertEqual(pv.star_impact(fp.stars()["stars"][0]), "9 stories this week, 2 in your briefing")
        self.assertEqual(pv.looks_like_mute(rows["R-0012"])["ref"], "gn-themes")
        self.assertIsNone(pv.looks_like_mute(rows["R-0010"]))

    def test_rule_rows_are_escaped_and_plain(self):
        for rule in pv.rules_of(fp.preferences(), fp.mutes(), fp.stars()):
            html = pv.rule_html(rule, fp.TZ)
            self.assertEqual(labels.find_jargon(re.sub(r"<[^>]+>", " ", html)), [], html)
            self.assertNotIn("<thesis>", html)
            self.assertNotIn("suppress", html.lower())
        focused = pv.rule_html(pv.rules_of(fp.preferences(), None, None)[0], fp.TZ, focused=True)
        self.assertTrue(focused.startswith('<div class="tn-rule zx-focus">'))

    def test_ended_rows_mix_preferences_and_mutes_newest_first(self):
        self.assertEqual([(k, r["id"]) for k, r in pv.ended_rows(fp.preferences(), fp.mutes())],
                         [("pref", "R-0005"), ("pref", "I-0003"), ("mute", 2), ("mute", 1), ("pref", "R-0009")])
        self.assertEqual(pv.ended_rows(None, None), [])


class SectionAndDateTests(unittest.TestCase):

    def test_end_dates_are_local_midnight_across_daylight_saving(self):
        self.assertEqual(pv.expires_iso(date(2026, 10, 31), "America/New_York"), "2026-10-31T04:00:00.000Z")
        self.assertEqual(pv.expires_iso(date(2026, 11, 1), "America/New_York"), "2026-11-01T04:00:00.000Z")
        self.assertEqual(pv.expires_iso(date(2026, 11, 2), "America/New_York"), "2026-11-02T05:00:00.000Z")
        self.assertEqual(pv.expires_iso(date(2026, 11, 2), "UTC"), "2026-11-02T00:00:00.000Z")
        self.assertEqual(pv.local_day("2026-11-02T05:00:00.000Z", "America/New_York"), date(2026, 11, 2))
        self.assertIsNone(pv.local_day(None, "America/New_York"))
        earliest, default, latest = pv.day_bounds("America/New_York", NOW)
        self.assertEqual((earliest, default, latest), (date(2026, 10, 5), date(2026, 11, 3), date(2027, 10, 5)))


    def test_volume_modes_and_labels(self):
        modes, caps, names = pv.volume_modes(fp.volume())
        self.assertEqual(modes, ["top", "standard", "broad"])
        self.assertEqual(caps, {"top": 8, "standard": 12, "broad": 20})
        self.assertEqual(pv.volume_label("broad", names), "Everything notable")
        self.assertEqual(pv.volume_modes({})[0], ["top", "standard", "broad"])
        self.assertEqual(pv.soft_cap_text(fp.preferences(over=True)["soft_cap"]),
                         "You have 41 active preferences. Older ones may conflict; the wording assistant suggests "
                         "merges once a month.")  # the hub's sentence (soft_cap.warning, gap 29)
        self.assertEqual(pv.soft_cap_text(fp.preferences()["soft_cap"]), "")


class BriefShapeTests(unittest.TestCase):
    def test_signoff_status(self):
        body = fp.brief()
        at = body["signoff"]["last"]["signed_at"]
        self.assertEqual(bv.signoff_status(body, fp.TZ),
                         f"Approved by you on {bv.fmt_day(at, fp.TZ)} {bv.fmt_clock(at, fp.TZ)}.")
        self.assertEqual(bv.signoff_status(fp.brief(signed_by="migration"), fp.TZ),
                         "Briefings are running, but you haven't approved this page yet. Read below and press Sign off "
                         "again.")
        self.assertEqual(bv.signoff_status(fp.brief(signed_by="admin"), fp.TZ),
                         f"Signed off by the builder on {bv.fmt_date(at, fp.TZ)}.")
        self.assertEqual(bv.signoff_status(fp.brief(signed_by=None), fp.TZ), bv.NOT_SIGNED)
        self.assertEqual(bv.signoff_status(None, fp.TZ),
                         "Not signed off yet. Read below and press Sign off when it matches what you want.")

    def test_expander_label_says_the_sign_off(self):
        body = fp.brief()
        day = bv.fmt_date(body["signoff"]["last"]["signed_at"], fp.TZ)
        self.assertEqual(bv.expander_label(body, fp.TZ), f"What ZENITH looks for · signed off by you on {day}")
        self.assertEqual(bv.expander_label(fp.brief(signed_by="admin"), fp.TZ),
                         f"What ZENITH looks for · signed off by the builder on {day}")
        for unsigned in (fp.brief(signed_by=None), fp.brief(signed_by="migration"), None):
            self.assertEqual(bv.expander_label(unsigned, fp.TZ), "What ZENITH looks for · not signed off yet")
        self.assertEqual(labels.find_jargon(bv.expander_label(body, fp.TZ)), [])

    def test_parts(self):
        body = fp.brief()
        part = body["sections"][1]["parts"][1]
        self.assertEqual(bv.part_html(part), '<div class="brief-part"><div class="refine-label">What is ignored</div>'
                         '<ul class="brief-lines"><li class="brief-line">Stock-price moves without new facts '
                         '&lt;b&gt;at all&lt;/b&gt;.</li></ul></div>')
        repeated = {"kind": "always", "title": "Always", "lines": [{"id": "L-9", "text": "Prefer the primary source."}]}
        self.assertEqual(bv.part_html(repeated, "ALWAYS"), '<div class="brief-part"><ul class="brief-lines">'
                         '<li class="brief-line">Prefer the primary source.</li></ul></div>')
        self.assertIn('<div class="refine-label">Always</div>', bv.part_html(repeated, "Scores"))
        self.assertEqual(bv.section_lines({"lines": [{"id": "L-1", "text": " a "}, {"id": "", "text": "b"},
                                                     {"id": "L-3", "text": ""}]}), [{"id": "L-1", "text": "a"}])
        # the "Your tuning" read-out is gone (docs/SPEC-SIMPLIFY.md 2.3): Tuning is where the tuning is
        self.assertFalse(hasattr(bv, "tuning_summary"))

    def test_catalog_missing_names_areas_and_toasts(self):
        exc = api.ApiError("http", "HTTP 409: catalog_missing", 409, "catalog_missing",
                           detail="Coverage details for ai-infra, defense-unmanned appear after the next deploy; sign "
                                  "off then.", data={"error": "catalog_missing", "modules": ["ai-infra", "defense-unmanned"]})
        text = bv.catalog_missing_text(exc)
        # WF3 review CV5: the dashboard's words, never the hub's "after the next deploy"
        self.assertEqual(text, f"Coverage details for {labels.area_name('ai-infra')} and "
                               f"{labels.area_name('defense-unmanned')} aren't ready yet. The builder is setting them "
                               "up; sign off once they appear.")
        self.assertEqual(labels.find_jargon(text), [])
        bare = api.ApiError("http", "HTTP 409: catalog_missing", 409, "catalog_missing", detail="x")
        self.assertEqual(bv.catalog_missing_text(bare),
                         "Coverage details aren't ready yet. The builder is setting them up; sign off once they appear.")
        answer = fp.signed_off()
        self.assertEqual(bv.signed_off_toast(answer, False, fp.TZ), "Signed off.")
        clock = bv.fmt_clock(answer["effective"]["next_briefing_at"], fp.TZ)
        self.assertEqual(bv.signed_off_toast(answer, True, fp.TZ), f"Signed off. Briefings start at {clock}.")
        self.assertEqual(bv.signed_off_toast({"effective": {"next_briefing_at": None}}, True, fp.TZ),
                         "Signed off. Briefings start at the next scheduled time.")


class WriteOrHandleTests(unittest.TestCase):
    """write_or_handle returns the refusals it was asked to handle instead of letting ui.write draw them."""

    @staticmethod
    def fake_write(ws, call, *, toast, undo=None, in_callback=False):  # ui.write as specified: ApiError -> drawn, None
        try:
            return call("owner-token")
        except api.ApiError:
            return None

    def test_handled_and_other_refusals(self):
        refusal = api.ApiError("http", "HTTP 409: proposal_changed", 409, "proposal_changed")
        other = api.ApiError("http", "HTTP 409: draft_closed", 409, "draft_closed")

        def raises(exc):
            def call(token):
                raise exc
            return call

        with patch.object(bv.ui, "write", side_effect=self.fake_write):
            self.assertEqual(bv.write_or_handle(None, raises(refusal), toast="x", codes=("proposal_changed",)),
                             (None, refusal))
            self.assertEqual(bv.write_or_handle(None, raises(other), toast="x", codes=("proposal_changed",)),
                             (None, None))
            self.assertEqual(bv.write_or_handle(None, lambda token: {"ok": token}, toast="x", codes=()),
                             ({"ok": "owner-token"}, None))

    def test_a_broad_ui_write_still_reports_the_refusal(self):
        refusal = api.ApiError("http", "HTTP 409: target_retired", 409, "target_retired")

        def broad_write(ws, call, *, toast, undo=None, in_callback=False):
            try:
                return call("owner-token")
            except Exception:
                return None

        def call(token):
            raise refusal

        with patch.object(bv.ui, "write", side_effect=broad_write):
            self.assertEqual(bv.write_or_handle(None, call, toast="x", codes=("target_retired",)), (None, refusal))


if __name__ == "__main__":
    unittest.main()
