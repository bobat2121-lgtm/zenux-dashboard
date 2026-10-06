"""AppTest: "Your companies' big names" in What ZENITH looks for (docs/SPEC-COMPANY-MAP.md 6.1, 6.2 and 6.4): right after
the "Your coverage" section, one row per company in ticker order with only the big names by default, a big customer's
reason on hover, the ☎ mark and its legend, "None on file", a lazy Show all, the suggestions not built in yet, Find a
name, Suggest a change (the body and the OWNER bearer, the toast, the hub's refusals, locked) and the jargon guard,
which skips names (fixtures that trip it today, and the real sheets or research)."""

from __future__ import annotations

import json
import re
import unittest

import fixtures_tuning as fp
from helpers import AppCase, DASHBOARD, OWNER, PILOT_HUB, PIN, hub_defaults

from zenux_dashboard import api, labels, ui
from zenux_dashboard import company_map_view as cm
from zenux_dashboard.config import Workspace
from zenux_dashboard.fmt import esc

SUGGEST = PILOT_HUB + "/companies/suggestions"
REPO = DASHBOARD.parent
SHEETS = REPO / "workspaces" / "pilot" / "companies"
RESEARCH = REPO / "research" / "coverage-universe"


def name(text: str) -> str:
    return labels.name_html(text)


def chip(text: str, *, reason: str = "", hit: bool = False, call: bool = False) -> str:
    css = "cm-chip" + (" cm-hit" if hit else "") + (" cm-reason" if reason else "")
    title = f' title="{esc(reason)}"' if reason else ""
    mark = f'<span class="cm-call" title="{cm.CALL_ONLY}">☎</span>' if call else ""
    return f'<span class="{css}"{title}>{name(text)}{mark}</span>'


def ticker(text: str) -> str:
    return f'<span class="cm-ticker">{text}</span>'


class CompanyMapCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        fp.route_reads(self.http)

    def open(self, *, pin: str | None = None):
        return self.app(tab="coverage", pin=pin)

    def with_companies(self, companies) -> None:
        body = fp.brief()
        if companies is None:
            body.pop("companies")
        else:
            body["companies"] = companies
        self.http.on("GET", PILOT_HUB + "/brief", body)

    def suggest(self, ticker_: str):
        at = self.open(pin=PIN)
        at.button(key=f"cm_suggest_{ticker_}").click().run()
        self.assert_clean(at)
        return at

    def posted(self):
        calls = self.http.find("POST", SUGGEST)
        self.assertTrue(calls, "nothing was posted")
        return calls[-1]


class MapTests(CompanyMapCase):
    def test_right_after_your_coverage_in_ticker_order(self):
        at = self.open()
        self.assert_clean(at)
        html = self.html(at)
        heading = '<div class="rules-section">Your companies&#x27; big names</div>'
        self.assertLess(html.index("Your coverage: the covered companies"), html.index(heading))
        self.assertLess(html.index(heading),
                        html.index('<div class="rules-section">Defense unmanned: drones and counter-drone systems'))
        self.assertIn(cm.LEDE, self.visible_text(at))
        self.assertEqual(sorted([html.index(ticker(t)) for t in ("PL", "RCAT", "REKR")]),
                         [html.index(ticker(t)) for t in ("PL", "RCAT", "REKR")])
        self.assertIn(f'{ticker("RCAT")}{name("Red Cat Holdings")}', html)
        # a name in a sentence of the sheet is drawn as a name
        self.assertIn(f'<div class="cm-summary">Small military reconnaissance drones ({name("Black Widow")}) and '
                      'uncrewed boats.</div>', html)
        for column in ("Products &amp; brands", "Units &amp; acquisitions", "Big customers &amp; programs",
                       "Read-through"):
            self.assertIn(f'<div class="cm-col">{column}</div>', html)
        for key in ("cm_suggest_PL", "cm_suggest_RCAT", "cm_suggest_REKR"):
            self.assertEqual(at.button(key=key).label, cm.SUGGEST_LABEL)
        self.assert_plain(at)
        self.assert_no_secrets(at)

    def test_only_the_big_names_with_reasons_and_the_call_only_mark(self):
        at = self.open()
        html = self.html(at)
        for big in ("Black Widow", "Hellcat", "Teal Drones", "AeroVironment", "Skydio", "Sentinel Hub", "Rekor Scout"):
            self.assertIn(chip(big), html)
        for small in ("FANG", "Blue Ops", "U.S. Air Force", "Parrot", "ICEYE", "Rekor Command"):
            self.assertNotIn(name(small), html)  # only in Show all
        # a big customer's reason on hover; ☎ for one named only on calls or in filings
        self.assertIn(chip("U.S. Army SRR program", reason="73% of 2025 revenue"), html)
        # Japan has its own release: ranked on the call, but not named only there (as the real sheet says)
        self.assertIn(chip("Japan Ground Self-Defense Force", reason="#2 customer in H1 2026, named on the call"), html)
        self.assertIn(chip("Spetstechnoexport (Ukraine)", reason="Expected: Ukraine asked for 100,000+ drones",
                           call=True), html)
        self.assertIn(chip("Customer A", reason="40% of Q2 2026 revenue", call=True), html)  # unnamed, still shown
        visible = self.visible_text(at)
        self.assertIn("73% of 2025 revenue", visible)  # the tooltip is read like text
        self.assertIn("☎ Named only on calls or in filings", visible)  # the legend
        # REKR has no units
        self.assertIn('<div class="cm-col">Units &amp; acquisitions</div><div class="cm-chips">'
                      '<span class="cm-none">None on file</span></div>', html)
        self.assertEqual([e.label for e in at.expander if e.label.startswith("Show all")],
                         ["Show all 8", "Show all 13", "Show all 7"])

    def test_suggestions_not_built_in_yet(self):
        at = self.open()
        html = self.html(at)
        self.assertIn('<span class="cm-pending-state">Being checked</span><span>Add '
                      f'{name("Drone Dominance program")} to Customers &amp; programs as a big customer</span>', html)
        # no status_label from the hub: the dashboard's words for "proposed"
        self.assertIn('<span class="cm-pending-state">Needs your OK</span><span>Fix '
                      f'{name("Planet Insights Platform")} in Products &amp; brands</span>', html)
        # an approved removal stops counting: never "uses it"
        self.assertIn('<span class="cm-pending-state">Approved: the ZENITH editor stops counting it from the next '
                      f'briefing</span><span>Remove {name("SoundThinking")} from Read-through</span>', html)
        self.assertNotIn("Rekor Edge", html)  # live: built in, no longer pending
        self.fresh()
        body = fp.brief_companies()
        body["items"][1]["pending"][0]["status_label"] = "In the scout queue"  # not plain: the dashboard's words
        self.with_companies(body)
        at = self.open()
        self.assertIn('<span class="cm-pending-state">Needs your OK</span>', self.html(at))
        self.assert_plain(at)

    def test_a_removal_or_fix_names_the_entry_on_file(self):
        """A pending removal or fix without a name (a big-only fix sends none) is named by the hub's target_name, else
        by the entry on file with its target_id; a closed one never shows, whatever its label says."""
        body = fp.brief_companies()
        rcat, pl = body["items"][0], body["items"][1]
        rcat["pending"] = [
            {"id": "CS-5e6f7081", "column": "customers", "action": "change", "name": None, "target_id": "c-air-force",
             "status": "proposed", "status_label": None, "big": 1},  # big as the hub's database stores it
            {"id": "CS-5e6f7082", "column": "products", "action": "add", "name": "Hellcat Mk2", "status": "live",
             "status_label": "Built in", "big": None},
            {"id": "CS-5e6f7083", "column": "products", "action": "add", "name": "Wasp", "status": "rejected",
             "status_label": "Turned down", "big": 0}]
        pl["pending"] = [
            {"id": "CS-6f708193", "column": "units", "action": "remove", "name": None, "target_id": "u-sentinel-hub",
             "status": "queued", "status_label": "Being checked", "big": None},
            {"id": "CS-6f708194", "column": "products", "action": "change", "name": "Planet Insights",
             "target_id": "p-insights", "status": "approved", "status_label": None, "big": None},
            {"id": "CS-6f708195", "column": "read_through", "action": "change", "name": None,
             "target_name": "BlackSky Technology", "target_id": "r-gone", "status": "queued", "big": None},
            {"id": "CS-6f708196", "column": "products", "action": "change", "name": None, "target_id": "p-gone",
             "status": "queued", "big": None}]
        self.with_companies(body)
        at = self.open()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn('<span class="cm-pending-state">Needs your OK</span><span>Fix '
                      f'{name("U.S. Air Force")} in Customers &amp; programs as a big customer</span>', html)
        self.assertIn('<span class="cm-pending-state">Being checked</span><span>Remove '
                      f'{name("Sentinel Hub")} from Units &amp; acquisitions</span>', html)
        self.assertIn('<span class="cm-pending-state">Approved: the ZENITH editor uses it from the next briefing'
                      '</span><span>Fix '
                      f'{name("Planet Insights Platform")} in Products &amp; brands: call it '
                      f'{name("Planet Insights")}</span>', html)
        self.assertIn(f'<span>Fix {name("BlackSky Technology")} in Read-through</span>', html)
        self.assertIn("<span>Fix a name in Products &amp; brands</span>", html)  # not on file: still listed
        for closed in ("Hellcat Mk2", "Wasp", "Built in", "Turned down"):
            self.assertNotIn(closed, html)
        self.assert_plain(at)

    def test_the_same_company_twice_is_drawn_once(self):
        body = fp.brief_companies()
        body["items"] += [{**body["items"][0], "name": "Red Cat again"}, {**body["items"][1], "ticker": "pl"}]
        self.with_companies(body)
        at = self.open()
        self.assert_clean(at)
        html = self.html(at)
        self.assertEqual((html.count(ticker("RCAT")), html.count(ticker("PL"))), (1, 1))
        self.assertNotIn("Red Cat again", html)
        self.assertEqual([e.label for e in at.expander if e.label.startswith("Show all")],
                         ["Show all 8", "Show all 13", "Show all 7"])

    def test_show_all_lists_every_name_lazily(self):
        at = self.open()
        self.assertNotIn("cm-all", self.html(at))  # closed: nothing drawn
        self.open_expander(at, "cm_all_RCAT")
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        for small in ("FANG", "Blue Ops", "U.S. Air Force", "Parrot"):
            self.assertIn(name(small), html)
        self.assertIn('<div class="cm-col">Customers &amp; programs · 5</div>', html)
        self.assertIn('<div class="cm-entry cm-big"><div class="cm-entry-name">'
                      f'{name("U.S. Army SRR program")}</div><div class="cm-entry-reason">Big customer: 73% of 2025 '
                      'revenue</div><div class="cm-entry-meta">Program · Filing</div></div>', html)
        self.assertIn(f'<div class="cm-entry-aka">Also: {name("Teal Drones, Inc.")}, {name("Teal 2")}</div>', html)
        # what each date is: a company bought says its month once, in what it is; a customer when it was first named
        self.assertIn('<div class="cm-entry-meta">Bought Aug 2021 · Filing</div>', html)
        self.assertIn('<div class="cm-entry-meta">Bought Jan 2025 · Press release</div>', html)
        self.assertEqual(html.count("Jan 2025"), 1)
        self.assertIn('<div class="cm-entry-meta">Government buyer · News · First named Apr 2025</div>', html)
        self.assertIn('<div class="cm-entry-meta">Product · Press release · Since May 2025</div>', html)
        self.assertIn(f"to replace the {name('Teal 2')} (Apr 2, 2025).</div>", html)  # the sheet's date, plain
        self.assertNotIn("2025-04-02", html)
        self.assertIn('<div class="cm-entry-meta">Product · Press release · Not used to tag stories</div>', html)
        self.assertIn("Government buyer · Earnings call · Named only on calls or in filings", html)
        self.assertNotIn(name("Rekor Command"), html)  # only the company opened
        self.open_expander(at, "cm_all_REKR")
        at.run()
        html = self.html(at)
        self.assertIn("Customer · Filing · Not named by the company · Named only on calls or in filings · Not used to "
                      "tag stories", html)
        self.assertIn('<div class="cm-col">Units &amp; acquisitions · 0</div><div class="cm-none">None on file</div>',
                      html)
        self.assert_plain(at)

    def test_find_a_name(self):
        at = self.open()
        at.text_input(key=cm.FIND_KEY).set_value("Teal").run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn(ticker("RCAT"), html)
        self.assertNotIn(ticker("PL"), html)
        self.assertNotIn(ticker("REKR"), html)
        self.assertNotIn("cm_suggest_PL", [b.key for b in at.button])
        self.assertIn(chip("Teal Drones", hit=True), html)  # "Teal 2" is one of its other names
        self.assertIn(chip("Black Widow", hit=True), html)  # "Teal Black Widow"
        self.assertIn(chip("Hellcat"), html)  # big, not a match
        # a name that is not big shows while it matches; another name finds its entry; a company finds its row
        at.text_input(key=cm.FIND_KEY).set_value("air force").run()
        self.assertIn(chip("U.S. Air Force", hit=True), self.html(at))
        at.text_input(key=cm.FIND_KEY).set_value("sinergise").run()
        html = self.html(at)
        self.assertIn(chip("Sentinel Hub", hit=True), html)
        self.assertEqual([t for t in ("PL", "RCAT", "REKR") if ticker(t) in html], ["PL"])
        at.text_input(key=cm.FIND_KEY).set_value("Rekor Systems").run()
        html = self.html(at)
        self.assertEqual([t for t in ("PL", "RCAT", "REKR") if ticker(t) in html], ["REKR"])
        self.assertNotIn("cm-hit", html)
        at.text_input(key=cm.FIND_KEY).set_value("zzzz").run()
        self.assert_clean(at)
        self.assertIn(esc(cm.NO_MATCH), self.html(at))
        self.assert_plain(at)

    def test_an_older_hub_and_no_names_yet(self):
        self.with_companies(None)
        at = self.open()
        self.assert_clean(at)
        self.assertNotIn("big names", self.html(at))
        self.assertIn("What ranks high", self.html(at))  # the rest of the page as before
        self.fresh()
        self.with_companies({"items": [], "pending_total": 0})
        at = self.open()
        self.assert_clean(at)
        self.assertIn(esc(cm.EMPTY), self.html(at))
        self.assertNotIn(cm.FIND_KEY, [t.key for t in at.text_input])

    def test_drawn_at_the_end_without_a_your_coverage_section(self):
        body = fp.brief()
        body["sections"] = [s for s in body["sections"] if s["id"] != "s-your-coverage"]
        self.http.on("GET", PILOT_HUB + "/brief", body)
        at = self.open()
        self.assert_clean(at)
        html = self.html(at)
        self.assertLess(html.index("Who is covered"), html.index("Your companies&#x27; big names"))
        self.assertEqual(html.count("Your companies&#x27; big names"), 1)


class GuardTests(CompanyMapCase):
    def test_names_are_data_the_guard_skips(self):
        at = self.open()
        self.assert_clean(at)
        visible = self.visible_text(at)
        for real in ("Sentinel Hub", "Rekor Scout"):
            self.assertIn(real, visible)
        # these real names trip the guard today; drawn as names, they pass it
        self.assertEqual(sorted(set(labels.find_jargon(visible))), ["Hub", "Scout"])
        self.assert_plain(at)
        self.open_expander(at, "cm_all_PL")
        self.open_expander(at, "cm_all_REKR")
        at.run()
        html = self.html(at)
        self.assertIn(name("Sinergise (Sentinel Hub)"), html)
        # a note that names one: the name is skipped, the rest of the sentence is not
        self.assertIn(f'<div class="cm-entry-note">{name("Sentinel Hub")} keeps its own brand: a satellite data '
                      'platform from Slovenia.</div>', html)
        self.assert_plain(at)

    def test_the_words_around_the_names_stay_guarded(self):
        self.assertEqual(labels.strip_names(f"Add {name('Sentinel Hub')} to Units"), "Add   to Units")
        self.assertEqual(labels.find_jargon(labels.strip_names(chip("Rekor Scout"))), [])
        self.assertEqual(labels.find_jargon(labels.strip_names(f"{name('Rekor Scout')} is a lane")), ["lane"])
        self.assertEqual(name("<b>A & B</b>"), '<span class="co-name">&lt;b&gt;A &amp; B&lt;/b&gt;</span>')
        self.assertFalse(ui.looks_technical(f"{name('Sentinel Hub')} already has a suggestion."))
        self.assertTrue(ui.looks_technical("Sentinel Hub already has a suggestion."))

    def test_real_names_pass(self):
        """The real company sheets (or, until they exist, the verified research's names) drawn through the page: the
        names are skipped, the sheets' sentences (summaries, notes, reasons) are not, so each is checked first and a
        failure names the sheet entry to reword."""
        items = real_companies()
        if not items:
            self.skipTest("no company sheets or research on this machine")
        for item in items:
            pattern = cm.name_pattern(item)
            texts = [("summary", item.get("summary"))] + [
                (f"{e['id']} {field}", e.get(field)) for rows in item["columns"].values() for e in rows
                for field in ("note", "basis_text")]
            for where, text in texts:
                with self.subTest(company=item["ticker"], where=where):
                    self.assertEqual(labels.find_jargon(labels.strip_names(cm.marked(text, pattern))), [], text)
        self.with_companies({"items": items, "pending_total": 0})
        at = self.open()
        self.assert_clean(at)
        for item in items:
            self.open_expander(at, f"cm_all_{cm.key_of(item['ticker'])}")
        at.run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertEqual(len(re.findall(r'<div class="cm-entry(?: cm-big)?">', html)),
                         sum(len(v) for i in items for v in i["columns"].values()))
        self.assert_plain(at)


class SuggestTests(CompanyMapCase):
    def test_add_a_big_customer(self):
        self.http.on("POST", SUGGEST, fp.company_suggested())
        at = self.suggest("RCAT")
        self.assertIn(name("Red Cat Holdings"), self.html(at))
        self.assertEqual(at.radio(key="dlg_action").value, "add")
        self.assertEqual(at.radio(key="dlg_action").options, list(cm.ACTIONS.values()))
        at.selectbox(key="dlg_column").set_value("customers").run()
        self.assertEqual([c.key for c in at.checkbox], ["dlg_big_new"])
        self.assertEqual(at.checkbox(key="dlg_big_new").label, cm.BIG_LABEL)
        at.checkbox(key="dlg_big_new").check().run()
        at.text_input(key="dlg_name").set_value("  Spetstechnoexport ")
        at.text_input(key="dlg_note").set_value("Ukraine's state arms exporter")
        at.text_input(key="dlg_reason").set_value("Expected: Ukraine asked for 100,000+ drones")
        at.text_input(key="dlg_link").set_value("www.example.com/rcat-q2-call")
        self.assertEqual(self.http.posts(), [])
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        call = self.posted()
        self.assertEqual((call.body, call.bearer), ({
            "ticker": "RCAT", "column": "customers", "action": "add", "name": "Spetstechnoexport",
            "note": "Ukraine's state arms exporter", "big": True,
            "basis_text": "Expected: Ukraine asked for 100,000+ drones",
            "link": "https://www.example.com/rcat-q2-call"}, OWNER))
        self.assertIn(cm.SUGGEST_SENT, self.toasts(at))
        self.assertNotIn("dlg_save", [b.key for b in at.button])  # closed
        self.assertEqual(len(self.http.find("GET", PILOT_HUB + "/brief")), 2)  # read again: the new suggestion shows

    def test_add_a_product_sends_no_big(self):
        self.http.on("POST", SUGGEST, fp.company_suggested(column="products", name="Hellcat Mk2"))
        at = self.suggest("RCAT")
        self.assertEqual([c.key for c in at.checkbox], [])  # big is for customers only
        at.text_input(key="dlg_name").set_value("Hellcat Mk2")
        at.button(key="dlg_save").click().run()
        self.assertEqual(self.posted().body, {"ticker": "RCAT", "column": "products", "action": "add",
                                              "name": "Hellcat Mk2"})

    def test_an_empty_name_is_not_sent(self):
        at = self.suggest("RCAT")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertIn("Not saved. Write the name to add.", self.texts(at, "error"))
        self.assertIn("dlg_save", [b.key for b in at.button])  # still open

    def test_remove_a_name(self):
        self.http.on("POST", SUGGEST, fp.company_suggested(ticker="PL", column="units", action="remove"))
        at = self.suggest("PL")
        at.radio(key="dlg_action").set_value("remove").run()
        at.selectbox(key="dlg_column").set_value("units").run()
        self.assertEqual(at.selectbox(key="dlg_target").options, ["Sentinel Hub"])
        self.assertEqual(at.text_input(key="dlg_note").label, "Why it no longer counts (one line)")
        self.assertEqual([c.key for c in at.checkbox], [])
        at.text_input(key="dlg_note").set_value("Sold in 2026")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        # the name on file goes with its id, so the card, the line under the company and the hub can say which
        self.assertEqual(self.posted().body, {"ticker": "PL", "column": "units", "action": "remove",
                                              "name": "Sentinel Hub", "target_id": "u-sentinel-hub",
                                              "note": "Sold in 2026"})
        self.assertIn(cm.SUGGEST_SENT, self.toasts(at))

    def test_fix_a_name(self):
        self.http.on("POST", SUGGEST, fp.company_suggested(action="change"))
        at = self.suggest("RCAT")
        at.radio(key="dlg_action").set_value("change").run()
        at.selectbox(key="dlg_column").set_value("customers").run()
        at.selectbox(key="dlg_target").set_value("c-nspa").run()
        self.assertTrue(at.checkbox(key="dlg_big_c-nspa").value)  # as on file
        at.button(key="dlg_save").click().run()
        self.assertIn(cm.FIX_EMPTY, self.texts(at, "info"))  # nothing to change yet
        self.assertEqual(self.http.posts(), [])
        at.text_input(key="dlg_name").set_value("NATO Support and Procurement Agency")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.posted().body, {"ticker": "RCAT", "column": "customers", "action": "change",
                                              "name": "NATO Support and Procurement Agency",
                                              "target_id": "c-nspa"})  # big unchanged: not sent
        at = self.suggest("RCAT")
        at.radio(key="dlg_action").set_value("change").run()
        at.selectbox(key="dlg_column").set_value("customers").run()
        at.selectbox(key="dlg_target").set_value("c-air-force").run()
        at.checkbox(key="dlg_big_c-air-force").check().run()
        at.text_input(key="dlg_reason").set_value("Named as a top customer on the Q2 2026 call")
        at.button(key="dlg_save").click().run()
        self.assertEqual(self.posted().body, {"ticker": "RCAT", "column": "customers", "action": "change",
                                              "target_id": "c-air-force", "big": True,
                                              "basis_text": "Named as a top customer on the Q2 2026 call"})

    def test_a_column_with_nothing_on_file(self):
        at = self.suggest("REKR")
        at.radio(key="dlg_action").set_value("remove").run()
        at.selectbox(key="dlg_column").set_value("units").run()
        self.assertIn(cm.NOTHING_THERE, self.texts(at, "info"))
        at.button(key="dlg_save").click().run()
        self.assertEqual(self.http.posts(), [])

    def test_already_suggested_and_a_name_gone_meanwhile(self):
        self.http.on("POST", SUGGEST, fp.refusal(409, "suggestion_exists",
                                                 "Sentinel Hub already has an open suggestion."))
        at = self.suggest("PL")
        at.text_input(key="dlg_name").set_value("Tanager")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn(cm.EXISTS, self.texts(at, "info"))
        self.assertEqual(self.texts(at, "error"), [])
        self.assertIn("dlg_save", [b.key for b in at.button])  # still open
        self.http.on("POST", SUGGEST, fp.refusal(404, "unknown_entry", "That entry is not on the sheet."))
        at.radio(key="dlg_action").set_value("remove").run()
        at.selectbox(key="dlg_column").set_value("units").run()
        reads = len(self.http.find("GET", PILOT_HUB + "/brief"))
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn(cm.GONE_ENTRY, self.texts(at, "info"))
        at.button(key="dlg_cancel").click().run()
        self.assertGreater(len(self.http.find("GET", PILOT_HUB + "/brief")), reads)  # read again

    def test_a_refusal_in_plain_words(self):
        self.http.on("POST", SUGGEST, fp.refusal(404, "unknown_company", "unknown_company: RCAT"))
        at = self.suggest("RCAT")
        at.text_input(key="dlg_name").set_value("Hellcat Mk2")
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. That company is no longer in your coverage. Refresh and try again.",
                      self.texts(at, "error"))

    def test_locked(self):
        at = self.open()
        for key in ("cm_suggest_PL", "cm_suggest_RCAT", "cm_suggest_REKR"):
            self.assertTrue(at.button(key=key).disabled)
            self.assertEqual(at.button(key=key).help, labels.LOCKED_HELP)
        self.assertEqual(self.http.posts(), [])


class StyleTests(unittest.TestCase):
    def test_one_column_per_company_on_phones(self):
        css = (DASHBOARD / "feed.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.cm-grid \{ display: grid; grid-template-columns: repeat\(4, minmax\(0,1fr\)\)")
        self.assertRegex(css, r"@media \(max-width: 900px\) \{\s*\.cm-grid, \.cm-all \{ grid-template-columns: "
                              r"minmax\(0,1fr\)")


class ShapeTests(unittest.TestCase):
    def test_yes_and_no_as_the_hub_stores_them(self):
        for value, expected in ((True, True), (1, True), (False, False), (0, False), (None, None), ("yes", None),
                                (2, None), (1.0, None)):
            self.assertIs(cm.flag(value), expected, value)
        entry = {"id": "c-x", "name": "Army SRR", "big": 1, "basis_text": "73% of 2025 revenue", "call_only": 1}
        self.assertEqual(cm.chip_html(entry), chip("Army SRR", reason="73% of 2025 revenue", call=True))
        self.assertEqual([e["name"] for e in cm.entries({"columns": {"customers": [
            {"name": "A", "big": 0}, {"name": "B", "big": 1}]}}, "customers")], ["B", "A"])
        self.assertEqual(cm.choices_of({"columns": {"customers": [entry]}})["customers"], [["c-x", "Army SRR", True]])

    def test_only_open_suggestions_have_a_status(self):
        for status, label, expected in (("queued", "Being checked", "Being checked"),
                                        ("proposed", None, "Needs your OK"),
                                        ("applied", "In the scout queue", cm.STATUS_LABELS["applied"]),
                                        ("live", "Built in", ""), ("rejected", "Not added", ""),
                                        ("withdrawn", None, ""), (None, "Being checked", "")):
            self.assertEqual(cm.status_text({"status": status, "status_label": label}), expected, status)
        # an approved removal stops counting, also in the dashboard's own words
        for status in ("approved", "applied"):
            self.assertEqual(cm.status_text({"status": status, "action": "remove", "status_label": None}),
                             "Approved: the ZENITH editor stops counting it from the next briefing")
        self.assertEqual(cm.status_text({"status": "approved", "action": "add"}),
                         "Approved: the ZENITH editor uses it from the next briefing")

    def test_a_fix_that_only_takes_big_away_says_so(self):
        company = {"columns": {"customers": [{"id": "c-nspa", "name": "NATO Support and Procurement Agency",
                                               "big": True}]}}
        fix = {"id": "CS-1", "column": "customers", "action": "change", "name": None, "target_id": "c-nspa",
               "status": "proposed", "big": False}
        for big in (False, 0):
            html = cm.pending_html({**company, "pending": [{**fix, "big": big}]})
            self.assertIn(f'<span>Fix {name("NATO Support and Procurement Agency")} in Customers &amp; programs as '
                          'no longer a big customer</span>', html)
        self.assertNotIn("no longer", cm.pending_html({**company, "pending": [{**fix, "big": None}]}))
        self.assertNotIn("no longer", cm.pending_html({**company, "pending": [{**fix, "action": "add", "big": False}]}))

    def test_the_sheets_dates_in_plain_words(self):
        self.assertEqual(cm.plain_dates("launched 2026-06-15; Contract (2025-12): 30 trucks in 2026"),
                         "launched Jun 15, 2026; Contract (Dec 2025): 30 trucks in 2026")
        for kept in ("2027-28", "2026-2028", "FY2026-27", "2026-13", "a 2026-06-155 code", "Q3 2026", "SRR-2024-01"):
            self.assertEqual(cm.plain_dates(kept), kept)
        self.assertEqual(cm.marked("Bought 2024-09-05 for $14.8M", None), "Bought Sep 5, 2024 for $14.8M")
        entry = {"id": "c-x", "name": "Exol", "big": True, "basis_text": "~$240M ordered by 2026-08"}
        self.assertEqual(cm.chip_html(entry), chip("Exol", reason="~$240M ordered by Aug 2026"))

    def test_companies_once_each_in_ticker_order(self):
        brief = {"companies": {"items": [{"ticker": "rekr", "name": "A"}, {"ticker": "PL"}, {"ticker": "REKR",
                                                                                            "name": "B"},
                                         {"ticker": ""}, None]}}
        self.assertEqual([(c["ticker"], c.get("name")) for c in cm.companies_of(brief)], [("PL", None), ("rekr", "A")])
        self.assertIsNone(cm.companies_of({}))


class ApiTests(unittest.TestCase):
    """api.suggest_company_change refuses a bad suggestion before anything is sent."""

    WS = Workspace(id="pilot", title="Pilot", hub_url="https://zenux-pilot-hub.test.invalid")

    def refused(self, **values) -> str:
        base = {"ticker": "RCAT", "column": "customers", "action": "add", "name": "Spetstechnoexport"}
        with self.assertRaises(api.ApiError) as caught:
            api.suggest_company_change(self.WS, "token", **{**base, **values})
        self.assertEqual(caught.exception.kind, "invalid")
        return caught.exception.detail

    def test_refusals(self):
        self.assertEqual(self.refused(ticker="red cat!"), "Choose the company.")
        self.assertEqual(self.refused(column="customer"), "Choose the column.")
        self.assertEqual(self.refused(action="rename"), "Choose whether to add, remove or fix a name.")
        self.assertEqual(self.refused(name="  "), "Write the name to add.")
        self.assertEqual(self.refused(action="remove", name=None), "Choose the name to remove or fix.")
        self.assertEqual(self.refused(name="x" * 61), "Keep the name to 60 characters or fewer.")
        self.assertEqual(self.refused(column="products", big=True, basis_text="Big"), "Only customers are marked as big.")
        self.assertEqual(self.refused(big=True), "Say why it is a big customer, for example its share of revenue.")
        self.assertEqual(self.refused(big=True, basis_text="x" * 81), "Keep the reason to 80 characters or fewer.")
        self.assertEqual(self.refused(note="x" * 141), "Keep the note to 140 characters or fewer.")
        self.assertEqual(self.refused(link="javascript:alert(1)"), "The link must start with https:// or http://.")


# ---------------------------------------------------------------------------------------------- real names


KIND_LABELS = {"subsidiary": "Unit", "acquired_company": "Bought", "joint_venture": "Joint venture",
               "equity_stake": "Stake", "government": "Government buyer", "channel_partner": "Sales channel",
               "end_user": "End user"}
DISCLOSED_LABELS = {"press_release": "Press release", "filing": "Filing", "earnings_call": "Earnings call",
                    "investor_deck": "Investor deck", "news": "News"}


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SINCE_WORDS = {"products": "Since", "units": "Since", "customers": "First named", "read_through": "First named"}


def _label(kind) -> str:
    text = str(kind or "")
    return KIND_LABELS.get(text) or text.replace("_", " ").capitalize()


def _kind_and_since(column: str, entry: dict) -> tuple[str, str | None]:
    """kind_label and since_label as the hub words them (hub/src/tuning.js companyItem)."""
    kind, since = _label(entry.get("kind") or entry.get("relation")), None
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", str(entry.get("since") or ""))
    if m:
        month = f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
        since = f"{MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(1)}" if m.group(3) else month
        since = f"{SINCE_WORDS[column]} {since}"
        if entry.get("kind") == "acquired_company":
            kind = f"Agreed to buy {month}" if entry.get("pending") is True else f"Bought {month}"
    if entry.get("kind") == "acquired_company":
        since = None
    return kind, since


def _item(eid: str, entry: dict, *, big: bool, column: str, name_key: str = "name") -> dict:
    kind, since = _kind_and_since(column, entry)
    return {"id": eid, "name": entry.get(name_key), "aliases": entry.get("aliases") or [], "big": big,
            "kind_label": kind, "note": entry.get("note"),
            "basis": entry.get("basis") if big else None, "basis_text": entry.get("basis_text") if big else None,
            "disclosed_label": DISCLOSED_LABELS.get(entry.get("disclosed")), "call_only": entry.get("call_only") is True,
            "unnamed": entry.get("unnamed") is True, "since_label": since,
            "tags_stories": bool(entry.get("terms") or entry.get("entity_id"))}


def _from_sheet(sheet: dict) -> dict:
    columns = {c: [_item(e.get("id") or f"{c}-{n}", e, big=e.get("big") is True, column=c)
                   for n, e in enumerate(sheet.get(c) or [])] for c in cm.COLUMNS}
    return {"ticker": sheet.get("ticker"), "name": sheet.get("name"), "summary": sheet.get("summary"),
            "columns": columns, "counts": {c: len(v) for c, v in columns.items()}, "pending": []}


def _from_research(research: dict) -> dict:
    """The verified research's names as a sheet would hold them: the first name of each column big."""
    subs = research.get("subsidiaries") or []
    groups = {"products": [s for s in subs if s.get("kind") in ("product", "brand")],
              "units": [s for s in subs if s.get("kind") not in ("product", "brand")],
              "customers": research.get("customers") or [], "read_through": research.get("read_through") or []}
    columns = {c: [_item(f"{c}-{n}", e, big=n == 0, column=c, name_key="company" if c == "read_through" else "name")
                   for n, e in enumerate(rows)] for c, rows in groups.items()}
    return {"ticker": research.get("ticker"), "name": research.get("company"), "summary": None, "columns": columns,
            "counts": {c: len(v) for c, v in columns.items()}, "pending": []}


def real_companies() -> list[dict]:
    """GET /brief companies items built from workspaces/pilot/companies/*.json, else from the verified research."""
    sheets = sorted(SHEETS.glob("*.json")) if SHEETS.is_dir() else []
    if sheets:
        return [_from_sheet(json.loads(p.read_text(encoding="utf-8"))) for p in sheets]
    research = sorted(RESEARCH.glob("*.verified.json")) if RESEARCH.is_dir() else []
    return [_from_research(json.loads(p.read_text(encoding="utf-8"))) for p in research]


if __name__ == "__main__":
    unittest.main()
