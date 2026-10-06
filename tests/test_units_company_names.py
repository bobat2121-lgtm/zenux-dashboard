"""Unit tests: the shapes and the HTML of the suggested company names (docs/SPEC-COMPANY-MAP.md 6.3): which rows are
waiting, what an approval writes, the source finder's result in plain words, the dates of its sources, and the names
drawn as names inside the guarded sentences (6.4)."""

from __future__ import annotations

import json
import unittest

import fixtures_tuning as fp
import helpers  # noqa: F401  (puts dashboard/ on sys.path)

from zenux_dashboard import company_names_view as cnv
from zenux_dashboard import labels

TZ = fp.TZ


class ShapeTests(unittest.TestCase):
    def test_which_rows_are_company_suggestions(self):
        self.assertTrue(cnv.is_suggestion({"id": "CS-6f708192"}))
        self.assertTrue(cnv.is_suggestion({"id": "cs-6F708192"}))
        for row in ({"id": 19}, {"id": "CS-6f70819"}, {"id": "R-0012"}, {}, None, "CS-6f708192"):
            self.assertFalse(cnv.is_suggestion(row), row)
        body = {"company_suggestions": [fp.company_add(), fp.company_add(), fp.company_fix(status="applied"),
                                        fp.company_remove(status=None), {"id": 7}, None]}
        self.assertEqual([r["id"] for r in cnv.proposed(body)], ["CS-6f708192", "CS-7081920a"])
        self.assertEqual(cnv.proposed(None), [])
        self.assertEqual(cnv.proposed({"company_suggestions": "x"}), [])

    def test_what_an_approval_writes(self):
        # the source finder's proposal over what was typed; the analyst's name kept aside when it was renamed
        values = cnv.shown(fp.company_add())
        self.assertEqual(values, {"name": "Army Drone Dominance program", "aliases": ["Drone Dominance"],
                                  "note": "U.S. Army plan to buy small drones in large numbers from 2026.", "big": True,
                                  "basis_text": "Expected: the Army plans to buy about 1 million drones",
                                  "typed": "Drone Dominance"})
        self.assertEqual(cnv.use_of(fp.company_add()), "proposal")
        # approved as typed: only the analyst's words
        typed = cnv.shown(fp.company_add(use="as_typed"))
        self.assertEqual((typed["name"], typed["note"], typed["basis_text"], typed["typed"]),
                         ("Drone Dominance", "Army plan to buy drones at scale", "Management expects big orders", ""))
        self.assertEqual(cnv.use_of(fp.company_add(use="as_typed")), "as_typed")
        # no proposal (a removal the source finder could not confirm): as typed
        self.assertEqual(cnv.use_of(fp.company_remove()), "as_typed")
        self.assertEqual(cnv.shown(fp.company_remove())["name"], "Rekor Scout")
        # a verdict sent as JSON text; a proposal that makes it not big drops the reason
        self.assertEqual(cnv.shown(fp.company_fix())["name"], "Planet Insights")
        small = fp.company_add(verdict={"result": "confirmed", "proposal": {"big": False}})
        self.assertEqual((cnv.shown(small)["big"], cnv.shown(small)["basis_text"]), (False, ""))
        self.assertEqual(cnv.verdict_of({"verdict": "{not json"}), {})
        self.assertEqual(cnv.proposal_of({"verdict": json.dumps({"proposal": "x"})}), {})

    def test_the_company_and_the_change_in_words(self):
        self.assertEqual(cnv.company_of(fp.company_add()), "Red Cat Holdings")
        self.assertEqual(cnv.company_of(fp.company_fix()), "PL")
        self.assertEqual(cnv.company_of({"company": {"name": "Planet Labs"}}), "Planet Labs")
        self.assertEqual(cnv.company_of({}), "a company")
        name = labels.name_html
        self.assertEqual(cnv.change_html(fp.company_add()),
                         f"Add {name('Army Drone Dominance program')} to Customers &amp; programs")
        self.assertEqual(cnv.change_html(fp.company_remove()), f"Remove {name('Rekor Scout')} from Products &amp; brands")
        self.assertEqual(cnv.change_html(fp.company_fix()), f"Fix {name('Planet Insights Platform')} in Products "
                                                            f"&amp; brands: call it {name('Planet Insights')}")
        self.assertEqual(cnv.change_html(fp.company_fix(target_name=None)),
                         f"Fix {name('Planet Insights')} in Products &amp; brands")
        self.assertEqual(cnv.change_html({"action": "x"}), "Change a name")

    def test_the_source_finders_result(self):
        self.assertIn(f'Confirmed: <a class="source-link" href="{fp.DRONE_URL}"', cnv.result_html(fp.company_add(), TZ))
        self.assertEqual(cnv.result_html(fp.company_add(verdict={"result": "confirmed"}), TZ), cnv.CONFIRMED_BARE)
        self.assertEqual(cnv.result_html(fp.company_remove(), TZ), cnv.NOT_CONFIRMED_MORE)
        self.assertEqual(cnv.result_html(fp.company_fix(), TZ), cnv.NOT_CONFIRMED)  # unclear, nothing more to read
        self.assertEqual(cnv.result_html(fp.company_add(verdict=None), TZ), cnv.NOT_CHECKED)
        # a source without a title is named by its site; one with an unsafe link is no link
        untitled = fp.company_add(verdict={"result": "confirmed", "evidence": [
            {"url": "https://www.example.com/a", "date": "2026-09-30"}]})
        self.assertIn(">example.com</a>, Sep 30, 2026", cnv.result_html(untitled, TZ))
        unsafe = fp.company_add(verdict={"result": "confirmed", "evidence": [{"url": "javascript:x"}, {"title": "A"}]})
        self.assertEqual(cnv.result_html(unsafe, TZ), "Confirmed: A")

    def test_big_as_the_hub_stores_it(self):
        # approved as typed (no proposal): the stored 1 or 0 counts like true or false
        for big, expected in ((1, True), (0, False), (True, True), (None, None)):
            row = fp.company_add(verdict=None, big=big)
            self.assertIs(cnv.shown(row)["big"], expected, big)
        one = fp.company_add(verdict=None, big=1)
        self.assertIn("Big customer: Management expects big orders", cnv.card_html(one, TZ))
        self.assertIn("Big customer: Management expects big orders", cnv.details_html(one, TZ))
        self.assertIn("Big customer: Management expects big orders", "".join(cnv.sent_lines(one)))
        zero = fp.company_add(verdict=None, big=0)
        self.assertNotIn("Big customer", cnv.card_html(zero, TZ) + cnv.details_html(zero, TZ))
        # a proposal's 0 wins over the analyst's true, as the builder's tool reads it
        self.assertIs(cnv.shown(fp.company_add(verdict={"result": "confirmed", "proposal": {"big": 0}}))["big"], False)

    def test_names_the_hub_left_out_come_from_the_names_on_file(self):
        files = cnv.on_file(fp.brief())
        self.assertEqual(files["PL"]["name"], "Planet Labs")
        self.assertEqual(files["RCAT"]["entries"][("customers", "c-air-force")], "U.S. Air Force")
        self.assertEqual(cnv.on_file({}), {})
        name = labels.name_html
        # a removal sent without its name and a fix that changes only the big flag: both name the entry on file
        removal = fp.company_remove(name=None, company_name=None, verdict=None)
        big_only = fp.company_row("CS-0b1c2d3e", "RCAT", None, "customers", "change", None, target_id="c-air-force",
                                  big=1, basis_text="Named as a top customer on the Q2 2026 call")
        self.assertEqual(cnv.change_html(removal), "Remove a name from Products &amp; brands")  # nothing to go by
        self.assertTrue(cnv.lacks_names(removal) and cnv.lacks_names(big_only))
        self.assertFalse(cnv.lacks_names(fp.company_add()))
        self.assertFalse(cnv.lacks_names(fp.company_remove()))  # a removal names itself
        reads = []
        removal, big_only = cnv.named([removal, big_only], lambda: reads.append(1) or fp.brief())
        self.assertEqual(len(reads), 1)
        self.assertEqual(cnv.change_html(removal), f"Remove {name('Rekor Scout')} from Products &amp; brands")
        self.assertIn(f"Suggested name for {name('Rekor Systems')}", cnv.card_html(removal, TZ))
        card = cnv.card_html(big_only, TZ)
        self.assertIn(f"Suggested name for {name('Red Cat Holdings')}", card)
        self.assertIn(f'<div class="pref-text">Fix {name("U.S. Air Force")} in Customers &amp; programs</div>', card)
        self.assertIn("Big customer: Named as a top customer on the Q2 2026 call", card)
        # read only when a row lacks a name; a failed read leaves the rows as they are
        rows = [fp.company_add(), fp.company_remove()]
        self.assertEqual(cnv.named(rows, lambda: self.fail("read")), rows)

        def fails():
            raise cnv.api.ApiError("unavailable", "busy")

        self.assertEqual(cnv.named([big_only | {"target_name": None}], fails)[0]["target_name"], None)
        # a ticker not on file keeps standing in
        self.assertIn(f"Suggested name for {name('ZZZ')}",
                      cnv.card_html(cnv.named([fp.company_fix(ticker="ZZZ")], fp.brief)[0], TZ))

    def test_source_dates(self):
        self.assertEqual(cnv.source_date("2026-09-30", TZ), "Sep 30, 2026")  # a day stays that day in New York
        self.assertEqual(cnv.source_date("2026-08", TZ), "Aug 2026")
        self.assertEqual(cnv.source_date("2026-09-30T02:00:00Z", TZ), "Sep 29, 2026")  # a time: its local day
        for value in ("", None, "2026-13-01", "soon"):
            self.assertEqual(cnv.source_date(value, TZ), "", value)


class HtmlTests(unittest.TestCase):
    def test_names_are_data_and_the_sentences_stay_plain(self):
        for row in (fp.company_add(), fp.company_remove(), fp.company_fix(), fp.company_applied()):
            for html in (cnv.card_html(row, TZ), cnv.details_html(row, TZ)):
                with self.subTest(row=row["id"]):
                    self.assertEqual(labels.find_jargon(labels.strip_names(html)), [], html)
        # without the name spans, "Rekor Scout" would trip the guard
        self.assertTrue(labels.find_jargon(cnv.details_html(fp.company_remove(), TZ).replace(labels.NAME_CLASS, "")))

    def test_real_names_pass(self):
        """Every real sheet name (or, until the sheets exist, the verified research's) suggested for its company, as
        typed and as the source finder's version: the names are skipped, the words around them are not (6.4)."""
        from test_app_company_map import real_companies

        items = real_companies()
        if not items:
            self.skipTest("no company sheets or research on this machine")
        for item in items:
            for column, rows in item["columns"].items():
                for entry in rows:
                    proposal = {"name": entry["name"], "aliases": entry.get("aliases") or [], "big": entry.get("big"),
                                "basis_text": entry.get("basis_text")}
                    row = fp.company_row("CS-0a0b0c0d", item["ticker"], item["name"], column, "add",
                                         (entry.get("aliases") or [entry["name"]])[0],
                                         verdict={"result": "confirmed", "proposal": proposal,
                                                  "summary": f"The company names {entry['name']}."})
                    with self.subTest(company=item["ticker"], entry=entry["id"]):
                        html = cnv.card_html(row, TZ) + cnv.details_html(row, TZ)
                        self.assertEqual(labels.find_jargon(labels.strip_names(html)), [], html)

    def test_the_big_reason_only_for_a_big_customer(self):
        self.assertIn("Big customer: Expected: the Army plans", cnv.card_html(fp.company_add(), TZ))
        self.assertNotIn("Big customer", cnv.card_html(fp.company_add(column="units"), TZ))
        self.assertNotIn("Big customer", cnv.card_html(fp.company_add(action="remove"), TZ))
        self.assertIn("Big customer</div>", cnv.card_html(fp.company_add(verdict=None, basis_text=None), TZ))

    def test_a_fix_that_only_takes_big_away_says_so(self):
        # the dialog sends big:false only when the box was unchecked on a big customer: the card, its Details and the
        # Control room say what changes, never just "Fix <name>"
        for big in (False, 0):
            row = fp.company_row("CS-0b1c2d3f", "RCAT", "Red Cat Holdings", "customers", "change", None,
                                 target_id="c-nspa", target_name="NATO Support and Procurement Agency", big=big)
            card, details = cnv.card_html(row, TZ), cnv.details_html(row, TZ)
            self.assertIn('<div class="pref-stats">No longer a big customer</div>', card)
            self.assertIn("Big customer: no", details)
            self.assertEqual(cnv.big_line(row), "No longer a big customer")
        unchanged = fp.company_row("CS-0b1c2d40", "RCAT", "Red Cat Holdings", "customers", "change", "NSPA",
                                   target_id="c-nspa", big=None)
        self.assertNotIn("big customer", (cnv.card_html(unchanged, TZ) + cnv.details_html(unchanged, TZ)).lower())
        self.assertEqual(cnv.big_line(fp.company_add(verdict=None, big=0)), "")  # an add that is not big says nothing

    def test_the_approval_says_what_it_does(self):
        self.assertEqual(cnv.approved_toast(fp.company_add()), cnv.APPROVED)
        self.assertEqual(cnv.approved_toast(fp.company_fix()), cnv.APPROVED_FIX)
        self.assertEqual(cnv.approved_toast(fp.company_remove()),
                         "Approved. The ZENITH editor stops counting it from the next briefing. The builder takes it "
                         "out of story tagging with the next update.")
        for toast in (cnv.APPROVED, cnv.APPROVED_FIX, cnv.APPROVED_REMOVAL):
            self.assertEqual(labels.find_jargon(toast), [], toast)
            self.assertIn("from the next briefing", toast)

    def test_the_source_finders_own_words_only_when_plain(self):
        self.assertEqual(labels.find_jargon("No registry has this name; the entity, rubric and routines"),
                         ["registry", "entity", "rubric", "routines"])
        technical = fp.company_add(verdict={
            "result": "not_confirmed", "summary": "No registry has this name; new entity id drone-dominance.",
            "proposal": {"name": "Army Drone Dominance program", "note": "Matches registry entity army-dd",
                         "big": True, "basis_text": "rubric section 2: forecast"}})
        card, details = cnv.card_html(technical, TZ), cnv.details_html(technical, TZ)
        for html in (card, details):
            self.assertEqual(labels.find_jargon(labels.strip_names(html)), [], html)
        self.assertNotIn("What the source finder found", details)
        self.assertIn('<div class="pref-stats">Big customer</div>', card)  # the reason left out, the fact kept
        self.assertNotIn("army-dd", card)
        self.assertIn(f'<div class="preview-line">{cnv.NOT_CONFIRMED}</div>', card)  # nothing under Details to read
        self.assertIn("What it is: Army plan to buy drones at scale", details)  # what the analyst sent stays
        # the analyst's own note is theirs, shown as typed when the source finder has none
        own = fp.company_add(verdict=None, note="Seen in the defense routine filings")
        self.assertIn("Seen in the defense routine filings", cnv.card_html(own, TZ))
        # the Control room shows the source finder's words as written, and points to no Details
        ws = cnv.Workspace(id="pilot", title="Pilot", hub_url="https://zenux-pilot-hub.test.invalid")
        item = cnv.item_html(ws, technical)
        self.assertIn("What it found: No registry has this name; new entity id drone-dominance.", item)
        self.assertIn("Matches registry entity army-dd", item)
        self.assertIn("Big customer: rubric section 2: forecast", item)
        self.assertIn(f"Source finder: {cnv.NOT_CONFIRMED}</div>", item)

    def test_details_only_when_there_is_more_to_read(self):
        self.assertEqual(cnv.details_html({"id": "CS-6f708192", "verdict": None}, TZ), "")
        details = cnv.details_html(fp.company_add(), TZ)
        for part in ("What the source finder found", "2 sources", "Also known as", "What you sent",
                     "Where you saw it", "Your note: Heard it on the Q2 call."):
            self.assertIn(part, details)


if __name__ == "__main__":
    unittest.main()
