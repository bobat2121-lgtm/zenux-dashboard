"""AppTest: the Coverage tab: coverage areas, the header, search and Show filters, the four columns with lazy groups,
company and source rows, the star and mute switches (through the card-action dialogs), and the company and source
details with Request coverage."""

from __future__ import annotations

import unittest
from typing import Any

import fixtures as fx
import fixtures_coverage as fc
from fixtures_coverage import COREWEAVE, CRUSOE, DCD, ERCOT, EXAMPLE, GENESIS, GN_THEMES, NEBIUS, OLD_PERMITS
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, READ, hub_defaults
from zenux_dashboard import labels, ui

MODULES = PILOT_HUB + "/modules"
INSPECT_AI = PILOT_HUB + "/modules/ai-infra/inspect"
INSPECT_DEF = PILOT_HUB + "/modules/defense-unmanned/inspect"
MUTES = PILOT_HUB + "/mutes"
STARS = PILOT_HUB + "/stars"
RADAR_NEW = PILOT_HUB + "/radar/requests"
# The ai-infra groups by column (largest first, then by label): see fixtures_coverage.inspect_ai.
PUBLIC_AI_CLOUD = "cv_g_public_0"            # CoreWeave, Nebius
PRIVATE_AI_CLOUD = "cv_g_private_0"          # Crusoe, Stargate LLC
PRIVATE_POWER = "cv_g_private_1"             # Tennessee Valley Authority, Example Co
INDUSTRY_COMPANY_NEWS = "cv_g_industry_0"    # SEC filings
INDUSTRY_NEWS_SEARCH = "cv_g_industry_1"     # News search (muted)
INDUSTRY_TRADE_PRESS = "cv_g_industry_2"     # Data Center Dynamics
GOV_PERMITTING = "cv_g_government_0"         # Old county permits (off), Loudoun agendas
GOV_POWER = "cv_g_government_1"              # ERCOT (not responding)
GOV_PROGRAMS = "cv_g_government_2"           # DOE Genesis Mission (a program)
ALL_GROUPS = (PUBLIC_AI_CLOUD, PRIVATE_AI_CLOUD, PRIVATE_POWER, INDUSTRY_COMPANY_NEWS, INDUSTRY_NEWS_SEARCH,
              INDUSTRY_TRADE_PRESS, GOV_PERMITTING, GOV_POWER, GOV_PROGRAMS)


def undo_of(at) -> Any:
    """The pending undo the last write offered (ui.UNDO_KEY), or None."""
    try:
        return at.session_state[ui.UNDO_KEY]
    except KeyError:
        return None


def field(obj: Any, name: str) -> Any:
    return getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)


class CoverageCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        h = self.http
        h.on("GET", MODULES, fc.modules())
        h.on("GET", INSPECT_AI, fc.inspect_ai())
        h.on("GET", INSPECT_DEF, fc.inspect_def())
        h.on("GET", MUTES, fc.mutes())
        h.on("GET", PILOT_HUB + "/settings", fc.settings())
        h.on("GET", PILOT_HUB + "/radar", fc.radar_requests())
        h.on("GET", PILOT_HUB + "/diagnostics", fx.diagnostics())

    def coverage(self, **kwargs):
        return self.app(tab="coverage", **kwargs)

    def opened(self, at, *groups: str):
        """Open lazy groups for the next run (AppTest keeps no expander state between runs) and run."""
        for key in groups:
            self.open_expander(at, key)
        return at.run()

    def click_in(self, at, groups: tuple[str, ...], key: str):
        """Click a row button inside lazy groups: open them to draw the rows, and keep them open in the run that
        receives the click."""
        at = self.opened(at, *groups)
        for group in groups:
            self.open_expander(at, group)
        return at.button(key=key).click().run()

    @staticmethod
    def filters_label(at) -> str:
        """The label of Coverage's Filters popover (the top bar has a popover of its own)."""
        popover = next(p for p in at.get("popover") if str(p.proto.id).endswith("cv_filters"))
        return popover.proto.popover.label

    def row_buttons(self, at) -> list[str]:
        return [b.key for b in at.button if str(b.key or "").startswith(("cv_star_", "cv_mute_s_", "cv_details_"))]


class AreaTests(CoverageCase):
    def test_area_picker_header_and_column_counts(self):
        at = self.coverage()
        self.assert_clean(at)
        area = at.segmented_control(key="cv_area")
        self.assertEqual(area.value, "ai-infra")
        self.assertEqual(list(area.options), ["AI infrastructure", "Defense unmanned"])
        html = self.html(at)
        self.assertIn('<div class="cov-title">AI infrastructure: data centers, colocation, AI cloud, bitcoin miners</div>'
                      '<div class="cov-desc">Data center leases, power deals, AI cloud capacity and miners moving to '
                      'AI.</div>', html)
        self.assertIn('<div class="cov-stats">7 companies · 6 sources on (2 off) · 1840 stories this week (14 in your '
                      'briefings) · 61 in your briefings in 30 days</div><div class="cov-stats">2 muted · 1 on your '
                      'watchlist</div>', html)
        # WF5 AW-13: a jump to the request form at the top, which lands on the form's anchor
        self.assertIn('<div class="zx-jump"><a href="#zx-coverage-requests">Ask for a source, a company or a topic ↓</a></div>',
                      html)
        self.assertIn('<div id="zx-coverage-requests"></div>', html)
        for title, n in (("Public companies", 2), ("Private and state-owned", 4), ("Industry sources", 3),
                         ("Government and public record", 4)):
            self.assertIn(f'<div class="cov-col"><span>{title}</span><span> · {n}</span></div>', html)
        self.assertEqual(self.http.find("GET", MODULES)[0].bearer, READ)
        self.assertEqual(self.http.find("GET", INSPECT_AI)[0].bearer, READ)
        self.assertEqual(self.http.find("GET", INSPECT_DEF), [])  # only the area shown is read
        self.assertIsNotNone(at.button(key="zx_refresh_coverage"))
        self.assert_plain(at)
        self.assert_no_secrets(at)

    def test_switching_area_reads_that_area(self):
        at = self.coverage()
        at.segmented_control(key="cv_area").set_value("defense-unmanned").run()
        self.assert_clean(at)
        self.assertEqual(len(self.http.find("GET", INSPECT_DEF)), 1)
        html = self.html(at)
        self.assertIn('<div class="cov-title">Defense unmanned: drones, counter-drone, autonomy</div>', html)
        self.assertIn("1 company · 1 source on (0 off) · 61 stories this week · 4 in your briefings in 30 days", html)
        self.assertNotIn("muted · ", html)  # no mutes or stars in this area
        self.assertEqual([e.label for e in at.expander], ["Counter-drone: kinetic · 1", "Contracts and solicitations · 1"])
        self.assertEqual(at.selectbox(key="rq_area").value, "defense-unmanned")  # the request composer follows

    def test_module_link_selects_the_area(self):
        at = self.coverage(query={"tab": "coverage", "module": "defense-unmanned"})
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="cv_area").value, "defense-unmanned")
        self.assertEqual(self.http.find("GET", INSPECT_AI), [])

    def test_catalog_missing_says_so_and_requests_still_render(self):
        self.http.on("GET", INSPECT_AI, FakeResponse(404, fc.catalog_missing("ai-infra")))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("Coverage details for AI infrastructure aren't ready yet. The builder is setting them up.",
                      self.texts(at, "info"))
        self.assertIsNotNone(at.button(key="rq_send"))
        self.assertIn("Follow the Texas PUC large-load docket", self.html(at))
        self.assert_plain(at)

    def test_unknown_area_and_other_inspect_errors(self):
        self.http.on("GET", INSPECT_AI, FakeResponse(404, {"error": "unknown_module",
                                                           "message": "No module called ai-infra in this workspace."}))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("AI infrastructure isn't set up in this workspace yet.", self.texts(at, "info"))
        self.fresh()
        self.http.on("GET", INSPECT_AI, FakeResponse(503, {"error": "schema_outdated"}))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("Couldn't load the details of AI infrastructure.", self.visible_text(at))
        self.assertIsNotNone(at.button(key="zx_retry_coverage_area"))
        self.assertIsNotNone(at.button(key="rq_send"))

    def test_coverage_areas_error_box(self):
        self.http.on("GET", MODULES, FakeResponse(503, {"error": "schema_outdated"}))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("Couldn't load coverage areas.", self.visible_text(at))
        self.assertIsNotNone(at.button(key="zx_retry_coverage"))
        self.assertIsNotNone(at.button(key="rq_send"))  # coverage requests still work

    def test_no_coverage_areas_yet(self):
        self.http.on("GET", MODULES, {"modules": []})
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("No coverage areas yet.", self.html(at))

    def test_staging_banner_leads_to_sign_off(self):
        self.http.on("GET", PILOT_HUB + "/settings", fc.settings(stage="staging"))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("Review who and what ZENUX covers here and in My preferences › What ZENUX looks for, then sign "
                      "off.", self.texts(at, "info"))
        at.button(key="cv_signoff").click().run()
        self.assertEqual(at.radio(key="zx_tab").value, "preferences")

    def test_a_failing_settings_read_never_blocks_the_page(self):
        self.http.on("GET", PILOT_HUB + "/settings", FakeResponse(503, {"error": "x"}))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn('<div class="cov-col"><span>Public companies</span><span> · 2</span></div>', self.html(at))


class ColumnTests(CoverageCase):
    def test_groups_are_lazy(self):
        at = self.coverage()
        self.assertEqual([e.label for e in at.expander], [
            "AI cloud · 2", "AI cloud · 2", "Power companies · 2", "Company news and filings · 1", "News search · 1",
            "Trade press · 1", "Local permitting and zoning · 2", "Power and grid · 1", "Programs and agencies · 1"])
        self.assertEqual(self.row_buttons(at), [])  # closed groups draw no rows
        self.assertNotIn("CoreWeave", self.html(at))
        at = self.opened(at, PUBLIC_AI_CLOUD)
        self.assert_clean(at)
        self.assertEqual(self.row_buttons(at), ["cv_star_0", "cv_details_e_0", "cv_star_1", "cv_details_e_1"])

    def test_rows_chips_stats_and_states(self):
        at = self.opened(self.coverage(), *ALL_GROUPS)
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="cov-name">CoreWeave <span class="cov-tickers">NASDAQ:CRWV</span></div>'
                      '<div class="cov-chips"><span class="cov-chip cov-chip-own_feed" title="ZENUX reads its own newsroom, '
                      'investor relations or wire releases.">Own feed</span><span class="cov-chip cov-chip-sec_filings" '
                      'title="ZENUX reads its filings with the SEC.">SEC filings</span></div>'
                      '<div class="cov-stats">9 this week (1 in briefings) · 2 in briefings (30 days)</div>'
                      '<div><span class="zx-chip chip-state chip-starred">On your watchlist</span></div>', html)
        self.assertIn('<span class="cov-chip cov-chip-name_only" title="ZENUX only catches it when another source names it '
                      'in a story.">Name only</span>', html)
        self.assertIn('<span class="cov-chip cov-chip-federal_contracts"', html)
        self.assertIn("Example &lt;b&gt;Co&lt;/b&gt;", html)
        self.assertIn('<span class="zx-chip chip-state chip-muted">Muted</span>', html)
        self.assertIn('<div class="cov-name">ERCOT large-load interconnection reports</div><div class="cov-stats">Page '
                      'watch · Not responding since Oct 1</div>', html)
        self.assertIn("News feed · Turned off: The site blocks automated access from our servers; we will retry from "
                      "another network.", html)
        self.assertIn("Old county permits &lt;page&gt;", html)
        self.assertIn('<div class="cov-name">DOE Genesis Mission</div>', html)  # a program, in Government
        self.assertNotIn("CoreWeave newsroom", html)  # a company's own feeds live in its details
        self.assertNotIn("javascript:", html)
        self.assertEqual(at.button(key=f"cv_star_{COREWEAVE}").label, "Starred")
        self.assertEqual(at.button(key=f"cv_star_{NEBIUS}").label, "Star")
        self.assertEqual(at.button(key=f"cv_mute_s_{GN_THEMES}").label, "Unmute")
        self.assertEqual(at.button(key=f"cv_mute_s_{DCD}").label, "Mute")
        self.assertEqual(sorted(k for k in self.row_buttons(at) if k.startswith("cv_details_e_")),
                         [f"cv_details_e_{n}" for n in range(7)])
        self.assertEqual(sorted(k for k in self.row_buttons(at) if k.startswith("cv_details_s_")),
                         [f"cv_details_s_{n}" for n in range(6)])  # the two entity feeds are not rows
        self.assertIn(labels.STILL_COLLECTED, " ".join(self.texts(at, "caption")))
        # the jargon guard with every group open
        self.assert_plain(at)
        self.assert_no_secrets(at)

    def test_a_muted_company_cannot_be_starred(self):
        at = self.opened(self.coverage(pin=PIN), PRIVATE_POWER)
        self.assert_clean(at)
        star = at.button(key=f"cv_star_{EXAMPLE}")
        self.assertTrue(star.disabled)
        self.assertEqual(star.proto.help, "Example <b>Co</b> is muted. Unmute it first.")

    def test_search_opens_matching_groups(self):
        at = self.coverage()
        at.text_input(key="cv_search").set_value("crusoe").run()
        self.assert_clean(at)
        self.assertIn("1 match", self.texts(at, "caption"))
        self.assertEqual([e.label for e in at.expander], ["AI cloud · 1"])
        self.assertEqual(self.row_buttons(at), [f"cv_star_{CRUSOE}", f"cv_details_e_{CRUSOE}"])  # open at once
        at.text_input(key="cv_search").set_value("CRWV").run()
        self.assertEqual(self.row_buttons(at), [f"cv_star_{COREWEAVE}", f"cv_details_e_{COREWEAVE}"])
        at.text_input(key="cv_search").set_value("center dynamics").run()  # every word, any order
        self.assertEqual(self.row_buttons(at), [f"cv_mute_s_{DCD}", f"cv_details_s_{DCD}"])
        at.text_input(key="cv_search").set_value("power").run()  # a category and a lane both match
        self.assertEqual([e.label for e in at.expander], ["Power companies · 2", "Power and grid · 1"])
        at.text_input(key="cv_search").set_value("zzz").run()
        self.assertIn("0 matches. Try another word, or ask for coverage below.", self.texts(at, "caption"))
        self.assertIn("No matches.", self.texts(at, "caption"))

    def test_show_filters_sit_in_the_filters_popover(self):
        at = self.coverage()
        self.assertEqual(self.filters_label(at), "Filters")
        self.assertEqual(list(at.radio(key="cv_show").options),
                         ["All", "On your watchlist", "Muted", "Name only (gaps)", "Not responding"])
        for show, buttons in (
                ("name_only", [f"cv_star_{CRUSOE}", f"cv_details_e_{CRUSOE}", f"cv_star_{GENESIS}",
                               f"cv_details_e_{GENESIS}"]),
                ("failing", [f"cv_mute_s_{ERCOT}", f"cv_details_s_{ERCOT}"]),
                ("starred", [f"cv_star_{COREWEAVE}", f"cv_details_e_{COREWEAVE}"]),
                ("muted", [f"cv_star_{EXAMPLE}", f"cv_details_e_{EXAMPLE}", f"cv_mute_s_{GN_THEMES}",
                           f"cv_details_s_{GN_THEMES}"])):
            with self.subTest(show=show):
                at.radio(key="cv_show").set_value(show).run()
                self.assert_clean(at)
                self.assertEqual(self.row_buttons(at), buttons)
                self.assertEqual(self.filters_label(at), "Filters · 1 on")
                self.assertIn(f"{len(buttons) // 2} match" + ("" if len(buttons) == 2 else "es"),
                              self.texts(at, "caption"))
        self.assert_plain(at)


class SwitchTests(CoverageCase):
    def test_star_previews_then_saves(self):
        self.http.on("GET", STARS + "/preview", fc.star_preview("nebius", "Nebius"))
        self.http.on("POST", STARS, FakeResponse(201, fc.star_added("nebius", "Nebius")))
        at = self.coverage(pin=PIN)
        at = self.click_in(at, (PUBLIC_AI_CLOUD,), f"cv_star_{NEBIUS}")
        self.assert_clean(at)
        preview = self.http.find("GET", STARS + "/preview")[0]
        self.assertEqual((preview.params, preview.bearer), ({"entity": "nebius"}, READ))
        self.assertIn("9 stories about Nebius in the last 7 days; 2 were in your briefing.", self.visible_text(at))
        self.assertEqual(self.http.posts(), [])  # nothing is sent before the dialog's Star
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", STARS)[0]
        self.assertEqual((post.body, post.bearer), ({"action": "add", "entity_id": "nebius"}, OWNER))
        self.assertTrue(any(t.startswith("Nebius is on your watchlist.") for t in self.toasts(at)))
        self.assertEqual(len(self.http.find("GET", INSPECT_AI)), 2)  # read again after the write

    def test_unstar_is_direct_with_undo(self):
        self.http.on("POST", STARS, fc.star_removed("coreweave", "CoreWeave"))
        at = self.coverage(pin=PIN)
        at = self.click_in(at, (PUBLIC_AI_CLOUD,), f"cv_star_{COREWEAVE}")
        self.assert_clean(at)
        post = self.http.find("POST", STARS)[0]
        self.assertEqual((post.body, post.bearer), ({"action": "remove", "entity_id": "coreweave"}, OWNER))
        self.assertIn("CoreWeave removed from your watchlist.", self.toasts(at))
        undo = undo_of(at)
        self.assertIsNotNone(undo)
        field(undo, "run")(OWNER)
        self.assertEqual(self.http.find("POST", STARS)[-1].body, {"action": "add", "entity_id": "coreweave"})

    def test_source_mute_previews_then_mutes_with_undo(self):
        self.http.on("GET", MUTES + "/preview", fc.mute_preview())
        self.http.on("POST", MUTES, lambda call: FakeResponse(201, fc.mute_added()) if call.body.get("action") == "add"
                     else fc.mute_removed(9, 5))
        at = self.coverage(pin=PIN)
        at = self.click_in(at, (INDUSTRY_TRADE_PRESS,), f"cv_mute_s_{DCD}")
        self.assert_clean(at)
        preview = self.http.find("GET", MUTES + "/preview")[0]
        self.assertEqual((preview.params, preview.bearer),
                         ({"kind": "source", "module": "ai-infra", "ref": "dcd-news"}, READ))
        text = self.visible_text(at)
        self.assertIn("Would have hidden 42 stories in the last 7 days; none were in your briefing; 3 were official "
                      "records.", text)
        self.assertIn(labels.STILL_COLLECTED, text)
        self.assertEqual(self.http.posts(), [])
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", MUTES)[0]
        self.assertEqual((post.body, post.bearer),
                         ({"action": "add", "kind": "source", "module": "ai-infra", "ref": "dcd-news"}, OWNER))
        toast = next(t for t in self.toasts(at) if t.startswith("Muted Data Center Dynamics."))
        self.assertIn(labels.STILL_COLLECTED, toast)
        field(undo_of(at), "run")(OWNER)
        self.assertEqual(self.http.find("POST", MUTES)[-1].body, {"action": "remove", "mute_id": 9, "bring_back_days": 7})

    def test_source_unmute_uses_the_inspectors_mute_reference(self):
        self.http.on("POST", MUTES, fc.mute_removed(4, 12))
        at = self.coverage(pin=PIN)
        at = self.click_in(at, (INDUSTRY_NEWS_SEARCH,), f"cv_mute_s_{GN_THEMES}")
        self.assert_clean(at)
        # the inspector's reference names the mute in full (gap 32): no GET /mutes lookup
        self.assertEqual(self.http.find("GET", MUTES), [])
        self.assertIn("Unmute News search: AI data center themes?", self.visible_text(at))
        preview = self.http.find("GET", MUTES + "/bring-back-preview")[-1]
        self.assertEqual((preview.params.get("mute_id"), preview.bearer), (4, READ))
        self.assertEqual(self.http.posts(), [])
        at.button(key="dlg_save").click().run()  # default: bring back the last 7 days
        self.assert_clean(at)
        post = self.http.find("POST", MUTES)[0]
        self.assertEqual((post.body, post.bearer), ({"action": "remove", "mute_id": 4, "bring_back_days": 7}, OWNER))
        self.assertTrue(any(t.startswith("Unmuted News search: AI data center themes.") for t in self.toasts(at)))

    def test_locked_switches_are_disabled_and_send_nothing(self):
        at = self.opened(self.coverage(), PUBLIC_AI_CLOUD, INDUSTRY_TRADE_PRESS)
        self.assert_clean(at)
        for key in (f"cv_star_{NEBIUS}", f"cv_star_{COREWEAVE}", f"cv_mute_s_{DCD}"):
            button = at.button(key=key)
            self.assertTrue(button.disabled, key)
            self.assertEqual(button.proto.help, labels.LOCKED_HELP)
        self.assertFalse(at.button(key=f"cv_details_e_{NEBIUS}").disabled)  # reading is never locked
        self.assertTrue(at.button(key="rq_send").disabled)
        self.assertIn(":material/lock: " + labels.LOCKED_HELP, self.texts(at, "caption"))
        at = self.click_in(at, (PUBLIC_AI_CLOUD,), f"cv_details_e_{NEBIUS}")
        self.assertTrue(at.button(key="dlg_mute").disabled)
        self.assertEqual(self.http.posts(), [])


class DetailsTests(CoverageCase):
    def test_company_details_name_only_and_request_coverage_prefilled(self):
        self.http.on("POST", RADAR_NEW, FakeResponse(201, fc.radar_created(47, "new_coverage")))
        at = self.coverage(pin=PIN)
        at = self.click_in(at, (PRIVATE_AI_CLOUD,), f"cv_details_e_{CRUSOE}")
        self.assert_clean(at)
        text = self.visible_text(at)
        self.assertIn('<span class="why-label">Name only</span> ZENUX only catches Crusoe when another source names it.',
                      self.html(at))
        self.assertIn("1 story this week · 4 in 30 days · 0 in your briefings (30 days)", text)
        self.assertEqual(at.button(key="dlg_request").proto.type, "primary")  # a gap: asking is the main action
        at.button(key="dlg_request").click().run()
        self.assert_clean(at)
        self.assertEqual(at.text_area(key="dlg_text").value,
                         "Please collect Crusoe's own news: its newsroom, filings or contracts.")
        self.assertEqual(at.selectbox(key="dlg_choice").value, "ai-infra")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", RADAR_NEW)[0]
        self.assertEqual((post.body, post.bearer), ({"kind": "new_coverage", "text": "Please collect Crusoe's own news: "
                                                     "its newsroom, filings or contracts.", "module": "ai-infra"}, OWNER))
        self.assertTrue(any(t.startswith("Sent to the source finder. It answers after its next run") for t in
                            self.toasts(at)))

    def test_company_details_own_feeds_and_starred_company(self):
        self.http.on("GET", MUTES + "/preview", fc.mute_preview("source", "ai-infra", "ent-coreweave-1",
                                                                "CoreWeave newsroom"))
        at = self.coverage(pin=PIN)
        at = self.click_in(at, (PUBLIC_AI_CLOUD,), f"cv_details_e_{COREWEAVE}")
        self.assert_clean(at)
        text, html = self.visible_text(at), self.html(at)
        self.assertIn('<span class="why-label">Own feed</span> ZENUX reads its own newsroom, investor relations or wire '
                      'releases.', html)
        self.assertIn('<span class="why-label">SEC filings</span> ZENUX reads its filings with the SEC.', html)
        self.assertIn("CoreWeave newsroom", text)
        self.assertIn("Turned off: The site blocks automated access.", text)
        mute = at.button(key="dlg_mute")
        self.assertTrue(mute.disabled)
        self.assertEqual(mute.proto.help, "CoreWeave is on your watchlist. Remove the star first.")
        self.assertEqual(at.button(key="dlg_star").label, "Remove from watchlist")
        self.assertEqual(at.button(key="dlg_request").proto.type, "secondary")
        at.button(key="dlg_mute_s_0").click().run()  # mute its newsroom: the mute dialog takes over
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", MUTES + "/preview")[0].params,
                         {"kind": "source", "module": "ai-infra", "ref": "ent-coreweave-1"})
        self.assertIsNone(self._button(at, "dlg_request"))  # one dialog at a time

    def test_mute_company_from_details(self):
        self.http.on("GET", MUTES + "/preview", fc.mute_preview("entity", None, "nebius", "Nebius"))
        self.http.on("POST", MUTES, FakeResponse(201, fc.mute_added(10, "entity", None, "nebius", "Nebius", 0)))
        at = self.coverage(pin=PIN)
        at = self.click_in(at, (PUBLIC_AI_CLOUD,), f"cv_details_e_{NEBIUS}")
        at.button(key="dlg_mute").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", MUTES + "/preview")[0].params, {"kind": "entity", "ref": "nebius"})
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", MUTES)[0].body, {"action": "add", "kind": "entity", "ref": "nebius"})

    def test_source_details(self):
        at = self.coverage()
        at = self.click_in(at, (GOV_POWER,), f"cv_details_s_{ERCOT}")
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<div class="cov-title">ERCOT large-load interconnection reports</div>', html)
        self.assertIn('<span class="why-label">What it is</span> Page watch', html)
        self.assertIn('<span class="why-label">What it covers</span> Power and grid · Grid operators, utility '
                      'commissions and FERC dockets about large loads.', html)
        self.assertIn('<span class="why-label">Health</span> Not responding since Oct 1', html)
        self.assertIn('href="https://example.com/feed"', html)
        self.assert_plain(at)
        self.fresh()
        at = self.coverage()
        at = self.click_in(at, (GOV_PERMITTING,), f"cv_details_s_{OLD_PERMITS}")
        self.assert_clean(at)
        self.assertNotIn("javascript:", self.html(at))
        self.assertIn("Turned off: The site blocks automated access from our servers", self.html(at))

    @staticmethod
    def _button(at, key: str):
        return next((b for b in at.button if b.key == key), None)


if __name__ == "__main__":
    unittest.main()
