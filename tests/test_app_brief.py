"""AppTest: What ZENUX looks for (docs/SPEC-PHASE03-UI.md 7.4), at the top of Coverage (docs/SPEC-SIMPLIFY.md 2.4):
one expander titled with its sign-off state, open while staging; the one-pager in plain sections, Suggest a change,
the staging banner, the sign-off status and the sign-off itself (bound to the versions shown)."""

from __future__ import annotations

import unittest

import fixtures_tuning as fp
from helpers import AppCase, Call, OWNER, PILOT_HUB, PIN, READ, hub_defaults

from zenux_dashboard import brief_view as bv
from zenux_dashboard import labels
from zenux_dashboard.fmt import esc, fmt_clock, fmt_date, fmt_day

TZ = fp.TZ


class BriefCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        fp.route_reads(self.http)

    def open(self, *, pin: str | None = None):
        return self.app(tab="coverage", pin=pin)

    @staticmethod
    def brief_expander(at):
        found = [e for e in at.expander if str(e.label).startswith(bv.LABEL)]
        return found[0] if found else None

    def posted(self, url: str) -> Call:
        calls = self.http.find("POST", url)
        self.assertTrue(calls, f"nothing was posted to {url}")
        return calls[-1]


class BriefTests(BriefCase):
    def test_an_expander_above_the_area_picker_titled_with_the_sign_off(self):
        at = self.open()
        self.assert_clean(at)
        body = fp.brief()
        day = fmt_date(body["signoff"]["last"]["signed_at"], TZ)
        box = self.brief_expander(at)
        self.assertEqual(box.label, f"What ZENUX looks for · signed off by you on {day}")
        self.assertFalse(box.proto.expanded)  # collapsed once the workspace is live
        html = self.html(at)
        self.assertLess(html.index("What ZENUX looks for: AI infrastructure"), html.index("How ZENUX covers this area"))
        self.assertEqual(at.segmented_control(key="cv_area").value, "ai-infra")  # the area picker follows it
        self.fresh()
        self.http.on("GET", PILOT_HUB + "/brief", fp.brief(signed_by=None))
        at = self.open()
        self.assertEqual(self.brief_expander(at).label, "What ZENUX looks for · not signed off yet")

    def test_sections_parts_and_lines(self):
        at = self.open()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("What ZENUX looks for: AI infrastructure and defense unmanned", html)
        self.assertIn("AI infrastructure: data centers, colocation, AI cloud, bitcoin miners", html)
        self.assertIn('<div class="brief-part"><div class="refine-label">What ranks high</div>', html)
        self.assertIn('<li class="brief-line">Power: interconnection approvals for 100 MW or more.</li>', html)
        self.assertIn("Stock-price moves without new facts &lt;b&gt;at all&lt;/b&gt;.", html)
        self.assertIn("Who is covered", html)
        # the "Your tuning" read-out is gone (docs/SPEC-SIMPLIFY.md 2.3)
        self.assertNotIn("Your tuning", html)
        self.assertNotIn("3 active preferences", html)
        for key in ("br_suggest_s-ai-infrastructure_0", "br_suggest_s-ai-infrastructure_1",
                    "br_suggest_s-defense-unmanned_0"):
            self.assertEqual(at.button(key=key).label, "Suggest a change")
        self.assertEqual(self.http.find("GET", PILOT_HUB + "/brief")[0].bearer, READ)
        self.assertNotIn(bv.STAGING_BANNER, self.texts(at, "info"))
        self.assertEqual(at.button(key="br_signoff").label, "Sign off again")
        self.assert_plain(at)
        self.assert_no_secrets(at)

    def test_the_approved_vocabulary_as_the_hub_sends_it(self):
        # gap 33: GET /brief maps the rubric's words (Lead item, Rejected tab, Tier 1 ...); the originals never show
        at = self.open()
        self.assert_clean(at)
        html = self.html(at)
        for shown in ("90+: Top story", "40-69: Near miss; listed under each briefing in Left out",
                      "Your coverage, Read-through, Industry and policy"):
            self.assertIn(f'<li class="brief-line">{shown}</li>', html)
        visible = self.visible_text(at)
        for original in ("Lead item", "Rejected tab", "Tier 1", "Pilot rubric v0"):
            self.assertNotIn(original, visible)
        self.assertEqual(at.button(key="br_suggest_s-scores_0").label, "Suggest a change")
        self.assert_plain(at)

    def test_signoff_status_in_plain_words(self):
        body = fp.brief()
        at_time = body["signoff"]["last"]["signed_at"]
        at = self.open()
        # WF5 AW-11: the analyst's own words, no builder history
        self.assertIn(f"Approved by you on {fmt_day(at_time, TZ)} {fmt_clock(at_time, TZ)}.", self.html(at))
        for by, text in (("migration", "Briefings are running, but you haven&#x27;t approved this page yet. Read below and "
                                       "press Sign off again."),
                         ("admin", f"Signed off by the builder on {fmt_date(at_time, TZ)}."),
                         (None, "Not signed off yet. Read below and press Sign off when it matches what you want.")):
            self.fresh()
            self.http.on("GET", PILOT_HUB + "/brief", fp.brief(signed_by=by))
            at = self.open()
            self.assert_clean(at)
            self.assertIn(text, self.html(at))

    def test_staging_banner_and_the_expander_open(self):
        self.http.on("GET", PILOT_HUB + "/brief", fp.brief(stage="staging", signed_by=None))
        at = self.open()
        self.assert_clean(at)
        self.assertIn(bv.STAGING_BANNER, self.texts(at, "info"))
        self.assertTrue(self.brief_expander(at).proto.expanded)  # open while staging
        self.assertEqual(at.button(key="br_signoff").label, "Sign off")
        self.assertEqual([b.key for b in at.button if b.key == "br_open_coverage"], [])  # it is on Coverage now

    def test_sign_off_sends_the_versions_shown(self):
        self.http.on("POST", PILOT_HUB + "/signoff", fp.signed_off())
        at = self.open(pin=PIN)
        shown = fp.brief()
        self.http.on("GET", PILOT_HUB + "/brief", {**fp.brief(), "rubric_version": "a-newer-version"})  # not drawn
        at.button(key="br_signoff").click().run()
        self.assert_clean(at)
        self.assertIn(bv.CONFIRM, self.visible_text(at))
        self.assertEqual(self.http.posts(), [])
        at.text_input(key="dlg_text").set_value("  Looks right  ")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        call = self.posted(PILOT_HUB + "/signoff")
        self.assertEqual((call.body, call.bearer), ({"rubric_version": shown["rubric_version"],
                                                     "catalog_versions": shown["catalog_versions"],
                                                     "note": "Looks right"}, OWNER))
        self.assertIn("Signed off.", self.toasts(at))
        self.assertNotIn("dlg_save", [b.key for b in at.button])

    def test_sign_off_from_staging_says_when_briefings_start(self):
        self.http.on("GET", PILOT_HUB + "/brief", fp.brief(stage="staging", signed_by=None))
        self.http.on("POST", PILOT_HUB + "/signoff", fp.signed_off())
        at = self.open(pin=PIN)
        at.button(key="br_signoff").click().run()
        self.assertIn(bv.CONFIRM_STAGING, self.visible_text(at))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        clock = fmt_clock(fp.signed_off()["effective"]["next_briefing_at"], TZ)
        self.assertIn(f"Signed off. Briefings start at {clock}.", self.toasts(at))
        self.assertNotIn("note", self.posted(PILOT_HUB + "/signoff").body or {})

    def test_a_change_while_reading_reloads_instead_of_signing(self):
        self.http.on("POST", PILOT_HUB + "/signoff", fp.refusal(
            409, "changed_since_viewed", "Coverage or the rubric changed while you were reviewing; reload and sign off "
            "again.", current={"rubric_version": "new", "catalog_versions": {}}))
        at = self.open(pin=PIN)
        at.button(key="br_signoff").click().run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn(bv.CHANGED, self.texts(at, "warning"))
        self.assertEqual(self.texts(at, "error"), [])
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/brief")), 2)
        self.assertNotIn("Signed off.", self.toasts(at))
        self.assertNotIn("dlg_save", [b.key for b in at.button])

    def test_missing_coverage_details_name_the_area(self):
        self.http.on("POST", PILOT_HUB + "/signoff", fp.refusal(
            409, "catalog_missing", "Coverage details for ai-infra appear after the next deploy; sign off then.",
            modules=["ai-infra"]))
        at = self.open(pin=PIN)
        at.button(key="br_signoff").click().run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. Coverage details for AI infrastructure aren't ready yet. The builder is setting them "
                      "up; sign off once they appear.", self.texts(at, "error"))
        self.assertIn("dlg_save", [b.key for b in at.button])  # still open
        self.assert_plain(at)

    def test_suggest_a_change(self):
        self.http.on("POST", PILOT_HUB + "/brief/suggest", fp.suggested())
        at = self.open(pin=PIN)
        at.button(key="br_suggest_s-ai-infrastructure_0").click().run()
        self.assert_clean(at)
        choice = at.selectbox(key="dlg_choice")
        self.assertEqual(choice.value, "L-1a2b3c4d5e")
        self.assertEqual(len(choice.options), 2)
        choice.set_value("L-2b3c4d5e6f")
        at.text_area(key="dlg_text").set_value("Short")
        at.button(key="dlg_save").click().run()
        self.assertIn(bv.SUGGEST_SHORT, self.texts(at, "info"))
        self.assertEqual(self.http.posts(), [])
        at.text_area(key="dlg_text").set_value("Interconnection approvals of 50 MW or more also rank high.")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        call = self.posted(PILOT_HUB + "/brief/suggest")
        self.assertEqual((call.body, call.bearer), ({"line_id": "L-2b3c4d5e6f",
                                                     "text": "Interconnection approvals of 50 MW or more also rank high."},
                                                    OWNER))
        self.assertIn(bv.SUGGEST_SENT, self.toasts(at))

    def test_a_line_that_left_the_page(self):
        self.http.on("POST", PILOT_HUB + "/brief/suggest", fp.refusal(
            404, "unknown_line", "That line is no longer on the page; reload it and try again."))
        at = self.open(pin=PIN)
        at.button(key="br_suggest_s-defense-unmanned_0").click().run()
        at.text_area(key="dlg_text").set_value("Also cover the counter-drone startups.")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn(bv.UNKNOWN_LINE, self.texts(at, "warning"))
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/brief")), 2)

    def test_locked(self):
        at = self.open()
        self.assertTrue(at.button(key="br_signoff").disabled)
        self.assertEqual(at.button(key="br_signoff").help, labels.LOCKED_HELP)
        self.assertTrue(at.button(key="br_suggest_s-ai-infrastructure_0").disabled)
        self.assertEqual(self.http.posts(), [])

    def test_unreadable_and_empty(self):
        self.http.routes.pop(("GET", PILOT_HUB + "/brief"))
        at = self.open()
        self.assert_clean(at)
        self.assertIn("Couldn't load what ZENUX looks for.", self.visible_text(at))
        self.fresh()
        self.http.on("GET", PILOT_HUB + "/brief", {**fp.brief(), "title": None, "sections": []})
        at = self.open()
        self.assert_clean(at)
        self.assertIn(esc(bv.EMPTY_BRIEF), self.html(at))


if __name__ == "__main__":
    unittest.main()
