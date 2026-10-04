"""Unit tests for the source repairs' pure helpers (repairs_view, docs/SPEC-REPAIR-PHASE-B.md section 3): the action in
plain words, before and after for each action, the probe's evidence, the source-health window's line, the lists'
counts and order, the plain lines for a failed read; and Coverage's line about the sources ZENUX is fixing
(coverage_view.fixing_text and health_line), which the jargon guard passes."""

from __future__ import annotations

import unittest

import helpers  # noqa: F401  (puts dashboard/ on sys.path)
import fixtures_coverage as fc
import fixtures_repairs as fr
from helpers import one_workspace
from zenux_dashboard import api, coverage_view, labels, repairs_view as rv
from zenux_dashboard.config import parse_config
from zenux_dashboard.fmt import esc, every_text

TZ = "America/New_York"


class ShapeTests(unittest.TestCase):
    def setUp(self):
        self.rows = {r["id"]: r for r in fr.repairs_list()}
        self.ws = parse_config(one_workspace()).workspace("pilot")

    def test_the_action_in_plain_words(self):
        self.assertEqual([rv.action_text(a) for a in ("replace", "turn_off", "slow_down", "add")],
                         ["Replace the source", "Turn it off", "Check it less often", "Add a source"])
        self.assertEqual(rv.action_text(" REPLACE "), "Replace the source")
        self.assertEqual(rv.action_text("split_feed"), "Split feed")  # a newer hub's action, never a crash
        self.assertEqual(rv.action_text(None), "A change")

    def test_rows_newest_first_and_tolerant(self):
        body = {"repairs": [{"id": 3}, {"id": "11"}, None, 7, {"id": "x"}, {"id": 3, "status": "again"}, {"no": 1}]}
        self.assertEqual([r["id"] for r in rv.repairs_of(body)], ["11", 3])
        self.assertEqual(rv.repairs_of(body)[1].get("status"), None)  # the first of an id wins
        self.assertEqual([r["id"] for r in rv.repairs_of([{"id": 1}, {"id": 2}])], [2, 1])
        for bad in ({"repairs": "x"}, None, "x", {}):
            self.assertEqual(rv.repairs_of(bad), [])

    def test_compact_json_on_one_line_without_nulls(self):
        self.assertEqual(rv.compact_json({"key": "x", "off_reason": None, "enabled": False, "n": 0, "gates": []}),
                         '{"key": "x", "enabled": false, "n": 0, "gates": []}')
        self.assertEqual(rv.compact_json({"label": "Café <b>"}), '{"label": "Café <b>"}')  # escaped where it is drawn
        self.assertNotIn("\n", rv.compact_json(fr.HAVOC_AFTER))
        self.assertEqual(rv.compact_json({"x": {1, 2}}), "{'x': {1, 2}}")  # not JSON: shown as text, never a crash

    def test_before_and_after_for_each_action(self):
        replace = rv.change_html(self.rows[21])
        self.assertIn("<th>Before</th><th>After</th>", replace)
        self.assertIn(f'<td><span class="mono">{esc(rv.compact_json(fr.HAVOC_BEFORE))}</span></td>'
                      f'<td><span class="mono">{esc(rv.compact_json(fr.HAVOC_AFTER))}</span></td>', replace)
        turn_off = rv.change_html(self.rows[20])
        self.assertIn('<td>On<br><span class="mono">https://www.defmin.fi/en/news</span></td>', turn_off)
        self.assertIn("<td>Off: " + esc(fr.FI_OFF_REASON) + '<br>Alternates: NATO newsroom <span class="mono">'
                      'nato-news</span>, European Defence Agency news <span class="mono">eda-news</span></td>', turn_off)
        self.assertEqual(rv.cadence_change(self.rows[19]), ("Checked every 2 h", "Checked every 6 h"))
        self.assertIn("<td>Checked every 2 h</td><td>Checked every 6 h</td>", rv.change_html(self.rows[19]))
        add = rv.change_html(self.rows[18])
        self.assertIn('<td>Stays as it is:<br><span class="mono">' + esc(rv.compact_json(fr.ERCOT_BEFORE)), add)
        self.assertIn('<td>Added next to it:<br><span class="mono">' + esc(rv.compact_json(fr.ERCOT_AFTER)), add)
        # what a hub should never send is said plainly
        self.assertIn("Not in the catalog.", rv.change_html({"action": "replace", "proposal": {"source": {"key": "a"}}}))
        self.assertIn("No source definition was sent.", rv.change_html({"action": "add", "proposal": {}}))
        self.assertIn("<td>On</td><td>Off: no reason given.<br>Alternates: none named.</td>",
                      rv.change_html({"action": "turn_off"}))
        self.assertEqual(rv.cadence_change({"action": "slow_down", "proposal": {"cadence_minutes": 1440}}),
                         ("Checked at the module's default pace", "Checked every day"))
        self.assertEqual(rv.cadence_change({"proposal": {"current": {"cadence_minutes": 90}}}),
                         ("Checked every 90 min", "No new pace given"))
        self.assertEqual(rv.change_html({"action": "rename"}), "")

    def test_alternates_by_label_then_the_keys_the_hub_did_not_resolve(self):
        self.assertEqual(rv.alternates_of(self.rows[20]),
                         [("NATO newsroom", "nato-news"), ("European Defence Agency news", "eda-news")])
        row = {"alternates": [{"key": "a", "label": "A feed"}, "x"], "proposal": {"alternates": ["a", "b", ""]}}
        self.assertEqual(rv.alternates_of(row), [("A feed", "a"), ("", "b")])
        self.assertEqual(rv.alternates_of({"alternates": "x", "proposal": "x"}), [])
        self.assertIn('Alternates: A feed <span class="mono">a</span>, <span class="mono">b</span></td>',
                      rv.change_html(dict(row, action="turn_off")))

    def test_the_probes_evidence(self):
        evidence = self.rows[21]["evidence"]
        facts = rv.evidence_facts(evidence, TZ)
        self.assertEqual(facts[:2], ["HTTP 200", "7 items found"])
        self.assertTrue(facts[2].startswith("probed "))
        html = rv.evidence_html(evidence, TZ)
        self.assertEqual(html.count("<tr><td>"), 5)  # at most 5 titles
        self.assertIn('<th>Found by the probe</th><th>Published</th>', html)
        self.assertIn('<a class="" href="https://www.havocai.com/news/rampage"', html)
        self.assertIn("HavocAI unveils the &lt;b&gt;Rampage&lt;/b&gt; autonomous boat", html)
        self.assertNotIn("javascript:", html)
        self.assertIn('<div class="refine-note">Notes: preview</div>', html)
        blocked = rv.evidence_html(self.rows[20]["evidence"], TZ)
        self.assertIn('<span class="status-pill bad">blocked</span> HTTP 403 · no items found · probed ', blocked)
        self.assertNotIn("<table", blocked)
        self.assertEqual(rv.evidence_html(None, TZ), '<div class="refine-note">No probe evidence.</div>')
        self.assertEqual(rv.evidence_html({}, TZ), '<div class="refine-note"><span class="status-pill idle">unknown'
                                                   '</span></div>')
        self.assertIn('<span class="status-pill ok">not modified</span>', rv.evidence_html({"status": "not_modified"},
                                                                                            TZ))
        self.assertEqual(rv.evidence_facts({"items_total": 1}, TZ), ["1 item found"])
        self.assertEqual(rv.evidence_facts("x", TZ), [])
        self.assertEqual(rv.evidence_notes({"notes": " one   note "}), "one note")
        self.assertEqual(rv.evidence_notes({"notes": ["a", "", None, "b"]}), "a, b")
        self.assertIn("Untitled item", rv.evidence_html({"status": "ok", "items": [{"url": "https://example.com/x"}]}, TZ))

    def test_the_source_health_windows_line(self):
        self.assertEqual(rv.window_line(self.rows[19]),
                         "A fix is proposed (repair #19): review it under Source repairs to review.")
        self.assertEqual(rv.window_line(self.rows[17]),
                         "A fix is approved (repair #17); waiting for the builder to apply it.")
        self.assertEqual(rv.window_line(self.rows[16]),
                         "A fix is applied (repair #16); waiting for the source to report ok.")
        for rid in (15, 14, 13):  # recovered, rejected and withdrawn repairs are not under way
            self.assertEqual(rv.window_line(self.rows[rid]), "")
        self.assertEqual(rv.window_line(None), "")

    def test_the_open_repair_of_each_source(self):
        fixes = rv.open_by_source(rv.repairs_of(fr.repairs()))
        self.assertEqual(sorted(fixes), [("ai-infra", "dcd-news"), ("ai-infra", "ercot-large-load"),
                                         ("defense-unmanned", "defense-post"), ("defense-unmanned", "fi-defmin"),
                                         ("defense-unmanned", "havocai-medium"), ("defense-unmanned", "sam-opps")])
        older = dict(self.rows[19], id=9, status="approved")
        self.assertEqual(rv.open_by_source(rv.repairs_of([older, self.rows[19]]))[("defense-unmanned", "sam-opps")]["id"],
                         19)  # the newest, when a hub lists two
        self.assertEqual(rv.open_by_source([{"id": 1, "status": "proposed", "module_id": "m"}]), {})  # no source key

    def test_counts_order_and_lines(self):
        body = fr.repairs()
        rows = rv.repairs_of(body)
        counts = rv.counts_of(body, rows)
        self.assertEqual(counts, {"proposed": 4, "approved": 1, "applied": 1, "recovered": 1, "rejected": 1,
                                  "withdrawn": 1})
        self.assertEqual(rv.counts_of({"counts": {"recovered": 140, "approved": "x", "rejected": -1}}, rows),
                         dict(counts, recovered=140))  # the hub's count where it gives a usable one
        self.assertEqual(rv.counts_of({}, []), dict.fromkeys(rv.STATUSES, 0))
        self.assertEqual((rv.count_text(3, 140), rv.count_text(3, 3), rv.count_text(3, 1)), ("3 of 140", "3", "3"))
        self.assertEqual([r["id"] for r in rv.recent_first([self.rows[13], self.rows[14], self.rows[15]])], [15, 14, 13])
        self.assertEqual(rv.summary_line(self.ws, counts),
                         "Pilot: 4 to review · 1 approved, waiting to be applied · 1 applied, waiting for the source "
                         "to report ok · 1 recovered · 2 rejected or withdrawn")
        older = api.ApiError("not_found", "HTTP 404: not_found", 404, "not_found")
        self.assertEqual(rv.read_error_line(self.ws, older),
                         "Pilot: this hub does not list source repairs yet; deploy the hub (schema 9) to add them.")
        self.assertEqual(rv.read_error_line(self.ws, api.ApiError("unreachable", "timed out")),
                         "Could not load source repairs from Pilot (timed out).")

    def test_the_card_and_the_list_entries(self):
        html = rv.card_html(self.ws, self.rows[21])
        self.assertTrue(html.startswith('<div class="radar-body"><div class="loop-card-head"><span class="loop-kind '
                                        'loop-kind-replace">Replace the source</span><span class="status-pill warn">'
                                        'proposed</span><span class="rule-meta" style="margin-top:0">pilot #21 · '
                                        'defense-unmanned · '))
        for part in ('<div class="failing-title"><span class="failing-name">HavocAI blog (Medium)</span>'
                     '<span class="mono">havocai-medium</span></div>',
                     '<div class="refine-label">Why it broke</div><div class="refine-note">The site shows our servers '
                     'a bot check</div><div class="rule-text">Medium shows Cloudflare&#x27;s servers',
                     '<div class="refine-label">Before and after</div>', '<div class="refine-label">Probe from the '
                     'module</div>'):
            self.assertIn(part, html)
        odd = rv.card_html(self.ws, {"id": 5, "status": "", "action": "x<y", "proposal": "x", "evidence": "x"})
        self.assertIn('<span class="loop-kind">X&lt;y</span><span class="status-pill idle">unknown</span>', odd)
        for words in ("No diagnosis given.", "No change described.", "No probe evidence."):
            self.assertIn(words, odd)
        self.assertNotIn("failing-name", odd)
        listed = rv.listed_html(self.ws, self.rows[14])
        self.assertIn('<span class="loop-kind loop-kind-turn_off">Turn it off</span><span class="status-pill bad">'
                      'rejected</span>', listed)
        self.assertIn('<div class="refine-note">Note: Loudoun is back; keep it on.</div>', listed)
        self.assertNotIn("Before and after", listed)
        self.assertIn("Applied ", rv.applied_html(self.rows[16], TZ))
        self.assertIn("Recovered ", rv.recovered_html(self.rows[15], TZ))

    def test_every_text_is_shared_with_the_slowed_sources(self):
        self.assertEqual([every_text(m) for m in (90, 120, 1440, 2880, None)],
                         ["every 90 min", "every 2 h", "every day", "every 2 days", "less often"])


class CoverageLineTests(unittest.TestCase):
    def test_fixing_text(self):
        self.assertEqual(coverage_view.fixing_text({"repairs_open": 1}), "ZENUX is fixing 1 source.")
        self.assertEqual(coverage_view.fixing_text({"repairs_open": "3"}), "ZENUX is fixing 3 sources.")
        for card in ({"repairs_open": 0}, {"repairs_open": None}, {"repairs_open": "x"}, {"repairs_open": -2}, {},
                     None, "x"):
            with self.subTest(card=card):
                self.assertEqual(coverage_view.fixing_text(card), "")

    def test_the_health_line_says_it_after_the_sources_not_responding(self):
        ai, defense = fr.modules(ai_open=2, def_open=1)["modules"]
        css, sentence, failing = coverage_view.health_line(fc.inspect_ai(), ai)
        self.assertEqual((css, failing), ("warn", ["ERCOT large-load interconnection reports"]))
        self.assertIn("everything else is collected as usual. ZENUX is fixing 2 sources. 2 sources are turned off on "
                      "purpose", sentence)
        self.assertEqual(coverage_view.health_line(fc.inspect_def(), defense),
                         ("ok", "All 1 source on are working. ZENUX is fixing 1 source.", []))
        self.assertEqual(coverage_view.health_line(fc.inspect_def(), fc.modules()["modules"][1])[1],
                         "All 1 source on are working.")  # an older hub sends no repairs_open
        self.assertEqual(labels.find_jargon(sentence + " " + coverage_view.fixing_text({"repairs_open": 3})), [])


if __name__ == "__main__":
    unittest.main()
