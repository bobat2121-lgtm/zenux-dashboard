"""AppTest: the Coverage tab: coverage areas, How ZENUX covers this area (four steps with live numbers), the
source-health line, What ZENUX watches (Companies or Sources, search, filters, one table whose rows open details),
the star and mute switches in the details (through the card-action dialogs), and Request coverage."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

import fixtures as fx
import fixtures_coverage as fc
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, READ, hub_defaults
from zenux_dashboard import brief_view, coverage_view, labels, ui

MODULES = PILOT_HUB + "/modules"
INSPECT_AI = PILOT_HUB + "/modules/ai-infra/inspect"
INSPECT_DEF = PILOT_HUB + "/modules/defense-unmanned/inspect"
MUTES = PILOT_HUB + "/mutes"
STARS = PILOT_HUB + "/stars"
RADAR_NEW = PILOT_HUB + "/radar/requests"


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

    @staticmethod
    def details(at, kind: str, ident: str, module: str = "ai-infra"):
        """Open a row's details, as clicking its row in the table does (AppTest cannot click a table row; the click
        itself is tested in RowClickTests), and run."""
        args = ({"entity_id": ident} if kind == "company" else {"source_key": ident})
        at.session_state["zx_dialog"] = {"name": kind, "args": {"workspace_id": "pilot", "module_id": module, **args}}
        return at.run()

    @staticmethod
    def table(at):
        frames = list(at.dataframe)
        return frames[0].value if frames else None

    def column(self, at, name: str) -> list:
        frame = self.table(at)
        return [] if frame is None else list(frame[name])


class AreaTests(CoverageCase):
    def test_area_picker_header_and_how_it_works(self):
        at = self.coverage()
        self.assert_clean(at)
        area = at.segmented_control(key="cv_area")
        self.assertEqual(area.value, "ai-infra")
        self.assertEqual(list(area.options), ["AI infrastructure", "Defense unmanned"])
        html = self.html(at)
        self.assertIn('<div class="cov-title">AI infrastructure: data centers, colocation, AI cloud, bitcoin miners</div>'
                      '<div class="cov-desc">Data center leases, power deals, AI cloud capacity and miners moving to '
                      'AI.</div>', html)
        # the four steps, with this area's numbers, the bar and size from How much, and the editor's next run
        flow = next(str(m.value) for m in at.markdown if 'class="cov-flow"' in str(m.value))
        for words in ("Watch", "7 companies · 8 sources (6 on)",
                      "Company news and filings, local permitting and zoning, trade press, power and grid, and news "
                      "search, checked around the clock.",
                      "Collect", "1,840 stories this week", coverage_view.COLLECT_TEXT,
                      "Score", "The ZENUX editor scores each one 0 to 100", "Next run: ",
                      "Brief", "14 in your briefings this week",
                      "Stories scoring 70 or more make your briefing, up to 12 at a time (How much: Standard). The rest "
                      "show under each briefing, in Left out of this briefing."):
            self.assertIn(words, flow)
        self.assertEqual(flow.count('class="cov-step"'), 4)
        self.assertEqual(flow.count('class="cov-arrow"'), 3)
        # WF5 AW-13: a jump to the request form at the top, which lands on the form's anchor
        self.assertIn('<div class="zx-jump"><a href="#zx-coverage-requests">Ask for a source, a company or a topic ↓</a></div>',
                      html)
        self.assertIn('<div id="zx-coverage-requests"></div>', html)
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
        self.assertIn("1 company · 1 source", html)
        self.assertIn("4 in your briefings in 30 days", html)  # an older hub without this week's figure
        self.assertIn("All 1 source on are working.", html)
        self.assertEqual(self.column(at, "Company"), ["Anduril"])
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

    def test_staging_shows_the_sign_off_here(self):
        # docs/SPEC-SIMPLIFY.md 2.4: What ZENUX looks for sits above the area picker, open while staging
        self.http.on("GET", PILOT_HUB + "/brief", fx.brief(stage="staging"))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn(brief_view.STAGING_BANNER, self.texts(at, "info"))
        box = next(e for e in at.expander if str(e.label).startswith("What ZENUX looks for"))
        self.assertEqual(box.label, "What ZENUX looks for · not signed off yet")
        self.assertTrue(box.proto.expanded)
        self.assertEqual(at.button(key="br_signoff").label, "Sign off")
        self.assertEqual([b.key for b in at.button if b.key == "cv_signoff"], [])  # no detour to another tab
        self.assertNotIn("My preferences", self.visible_text(at))

    def test_a_failing_settings_read_never_blocks_the_page(self):
        self.http.on("GET", PILOT_HUB + "/settings", FakeResponse(503, {"error": "x"}))
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn("Stories that clear your bar make your briefing.", self.html(at))
        self.assertEqual(len(self.column(at, "Company")), 7)


class HealthLineTests(CoverageCase):
    def test_a_source_not_responding_is_named_and_shown(self):
        at = self.coverage()
        self.assert_clean(at)
        line = next(str(m.value) for m in at.markdown if 'class="cov-health' in str(m.value))
        self.assertIn('class="cov-health warn"', line)
        self.assertIn("1 source isn&#x27;t responding right now: ERCOT large-load interconnection reports. ZENUX keeps "
                      "trying; everything else is collected as usual. 2 sources are turned off on purpose", line)
        at.button(key="cv_show_failing").click().run()
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="cv_list").value, "sources")
        self.assertEqual(self.column(at, "Source"), ["ERCOT large-load interconnection reports"])
        self.assertEqual(self.column(at, "Status"), ["Not responding since Oct 1"])

    def test_all_working(self):
        body = fc.inspect_ai()
        for source in body["sources"]:
            if source["health"]["state"] == "failing":
                source["health"]["state"] = "ok"
        self.http.on("GET", INSPECT_AI, body)
        at = self.coverage()
        self.assert_clean(at)
        self.assertIn('class="cov-health ok">All 6 sources on are working.', self.html(at))
        self.assertEqual([b.key for b in at.button if b.key == "cv_show_failing"], [])


class ListTests(CoverageCase):
    def test_companies_table(self):
        at = self.coverage()
        self.assert_clean(at)
        self.assertEqual(at.segmented_control(key="cv_list").value, "companies")
        self.assertEqual(list(at.segmented_control(key="cv_list").options), ["Companies · 7", "Sources · 8"])
        frame = self.table(at)
        self.assertEqual(list(frame.columns), ["Company", "Group", "Listed", "Ticker", "How ZENUX follows it",
                                               "This week", "In briefings, 30 days", "You"])
        self.assertEqual(list(frame["Company"]), ["CoreWeave", "Nebius", "Crusoe", "Stargate LLC",
                                                  "Tennessee Valley Authority", "DOE Genesis Mission", "Example <b>Co</b>"])
        first = frame.iloc[0].to_dict()
        self.assertEqual(first, {"Company": "CoreWeave", "Group": "AI cloud", "Listed": "Public", "Ticker": "NASDAQ:CRWV",
                                 "How ZENUX follows it": "Own news, SEC filings", "This week": 9,
                                 "In briefings, 30 days": 2, "You": "★ Watchlist"})
        self.assertEqual(list(frame["How ZENUX follows it"])[2], "By name only")  # Crusoe
        self.assertEqual(list(frame["Listed"])[5], "Program or agency")
        self.assertEqual(list(frame["You"])[6], "Muted")
        self.assertIn("7 companies shown. " + coverage_view.TABLE_HINT, self.texts(at, "caption"))
        self.assertIn(labels.STILL_COLLECTED, coverage_view.TABLE_HINT)
        self.assert_plain(at)
        self.assert_no_secrets(at)

    def test_sources_table(self):
        at = self.coverage()
        at.segmented_control(key="cv_list").set_value("sources").run()
        self.assert_clean(at)
        frame = self.table(at)
        self.assertEqual(list(frame.columns), ["Source", "What it is", "Group", "Status", "This week",
                                               "In briefings, 30 days", "You"])
        self.assertEqual(len(frame), 8)  # the area's own sources and the companies' own feeds
        rows = {r["Source"]: r for r in frame.to_dict("records")}
        self.assertEqual(rows["ERCOT large-load interconnection reports"]["Status"], "Not responding since Oct 1")
        self.assertEqual(rows["Old county permits <page>"]["Status"],
                         "Turned off: The site blocks automated access from our servers; we will retry from another "
                         "network.")
        self.assertEqual(rows["News search: AI data center themes"]["You"], "Muted")
        self.assertEqual(rows["Data Center Dynamics"]["Status"], "Working")
        self.assertNotIn("javascript:", self.html(at))
        self.assert_plain(at)

    def test_filters(self):
        at = self.coverage()
        for code, names in (("starred", ["CoreWeave"]), ("muted", ["Example <b>Co</b>"]),
                            ("name_only", ["Crusoe", "DOE Genesis Mission"]), ("all", None)):
            with self.subTest(code=code):
                at.session_state["cv_filter_companies"] = code
                at.run()
                self.assert_clean(at)
                shown = self.column(at, "Company")
                self.assertEqual(shown, names or shown)
        at.segmented_control(key="cv_list").set_value("sources").run()
        for code, names in (("failing", ["ERCOT large-load interconnection reports"]),
                            ("off", ["Old county permits <page>", "CoreWeave investor relations"]),
                            ("muted", ["News search: AI data center themes"])):
            with self.subTest(code=code):
                at.session_state["cv_filter_sources"] = code
                at.run()
                self.assert_clean(at)
                self.assertEqual(self.column(at, "Source"), names)

    def test_search(self):
        at = self.coverage()
        at.text_input(key="cv_search").set_value("crusoe").run()
        self.assert_clean(at)
        self.assertEqual(self.column(at, "Company"), ["Crusoe"])
        at.text_input(key="cv_search").set_value("CRWV").run()
        self.assertEqual(self.column(at, "Company"), ["CoreWeave"])
        at.text_input(key="cv_search").set_value("power").run()  # a group name matches
        self.assertEqual(self.column(at, "Company"), ["Tennessee Valley Authority", "Example <b>Co</b>"])
        at.segmented_control(key="cv_list").set_value("sources").run()
        at.text_input(key="cv_search").set_value("center dynamics").run()  # every word, any order
        self.assertEqual(self.column(at, "Source"), ["Data Center Dynamics"])
        at.text_input(key="cv_search").set_value("zzz").run()
        self.assert_clean(at)
        self.assertIsNone(self.table(at))
        self.assertIn("Nothing matches. Try another word or filter, or ask for coverage below.", self.html(at))


class RowClickTests(CoverageCase):
    def test_a_clicked_row_opens_its_details_and_resets_the_selection(self):
        state: dict = {"cv_table_companies_0": {"selection": {"rows": [1], "columns": []}}}
        with patch("streamlit.session_state", state):
            coverage_view.open_details("pilot", "ai-infra", "companies", ["coreweave", "nebius"], "cv_table_companies_0")
        self.assertEqual(state["zx_dialog"], {"name": "company", "args": {"workspace_id": "pilot", "module_id": "ai-infra",
                                                                         "entity_id": "nebius"}})
        self.assertEqual(state[coverage_view.TABLE_N_KEY], 1)  # the next table starts with no selection
        state = {"cv_table_sources_3": {"selection": {"rows": [0], "columns": []}}, coverage_view.TABLE_N_KEY: 3}
        with patch("streamlit.session_state", state):
            coverage_view.open_details("pilot", "ai-infra", "sources", ["dcd-news"], "cv_table_sources_3")
        self.assertEqual(state["zx_dialog"]["name"], "source")
        self.assertEqual(state["zx_dialog"]["args"]["source_key"], "dcd-news")
        self.assertEqual(state[coverage_view.TABLE_N_KEY], 4)
        for rows in ([], [5], None):  # nothing picked, or a stale index: nothing opens
            state = {"k": {"selection": {"rows": rows}}}
            with patch("streamlit.session_state", state):
                coverage_view.open_details("pilot", "ai-infra", "companies", ["coreweave"], "k")
            self.assertNotIn("zx_dialog", state)

    def test_the_table_takes_row_clicks(self):
        at = self.coverage()
        self.assert_clean(at)
        frame = at.dataframe[0]
        self.assertEqual(list(frame.proto.selection_mode), [0])  # Arrow.SelectionMode.SINGLE_ROW
        self.assertIn("cv_table_companies_0", frame.proto.id)


class SwitchTests(CoverageCase):
    def test_star_previews_then_saves(self):
        self.http.on("GET", STARS + "/preview", fc.star_preview("nebius", "Nebius"))
        self.http.on("POST", STARS, FakeResponse(201, fc.star_added("nebius", "Nebius")))
        at = self.details(self.coverage(pin=PIN), "company", "nebius")
        at.button(key="dlg_star").click().run()
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

    def test_unstar_is_direct_with_undo(self):
        self.http.on("POST", STARS, fc.star_removed("coreweave", "CoreWeave"))
        at = self.details(self.coverage(pin=PIN), "company", "coreweave")
        at.button(key="dlg_star").click().run()
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
        at = self.details(self.coverage(pin=PIN), "source", "dcd-news")
        at.button(key="dlg_mute").click().run()
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
        at = self.details(self.coverage(pin=PIN), "source", "gn-themes")
        at.button(key="dlg_mute").click().run()
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

    def test_a_muted_company_cannot_be_starred(self):
        at = self.details(self.coverage(pin=PIN), "company", "example-co")
        self.assert_clean(at)
        star = at.button(key="dlg_star")
        self.assertTrue(star.disabled)
        self.assertEqual(star.proto.help, "Example <b>Co</b> is muted. Unmute it first.")

    def test_locked_switches_are_disabled_and_send_nothing(self):
        at = self.coverage()
        self.assert_clean(at)
        self.assertTrue(at.button(key="rq_send").disabled)
        at = self.details(at, "company", "nebius")
        self.assertTrue(at.button(key="dlg_mute").disabled)
        self.assertTrue(at.button(key="dlg_star").disabled)
        self.assertEqual(at.button(key="dlg_star").proto.help, labels.LOCKED_HELP)
        self.assertEqual(self.http.posts(), [])


class DetailsTests(CoverageCase):
    def test_company_details_name_only_and_request_coverage_prefilled(self):
        self.http.on("POST", RADAR_NEW, FakeResponse(201, fc.radar_created(47, "new_coverage")))
        at = self.details(self.coverage(pin=PIN), "company", "crusoe")
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
        at = self.details(self.coverage(pin=PIN), "company", "coreweave")
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
        at = self.details(self.coverage(pin=PIN), "company", "nebius")
        at.button(key="dlg_mute").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", MUTES + "/preview")[0].params, {"kind": "entity", "ref": "nebius"})
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.find("POST", MUTES)[0].body, {"action": "add", "kind": "entity", "ref": "nebius"})

    def test_source_details(self):
        at = self.details(self.coverage(), "source", "ercot-large-load")
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
        at = self.details(self.coverage(), "source", "old-permits")
        self.assert_clean(at)
        self.assertNotIn("javascript:", self.html(at))
        self.assertIn("Turned off: The site blocks automated access from our servers", self.html(at))

    @staticmethod
    def _button(at, key: str):
        return next((b for b in at.button if b.key == key), None)


if __name__ == "__main__":
    unittest.main()
