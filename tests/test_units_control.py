"""Unit tests for the coverage builder's pure helpers: the Control room's health summary and module view
(control_view), coverage requests (radar_view) and the Coverage columns (coverage_view)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import helpers  # noqa: F401  (puts dashboard/ on sys.path)
import fixtures as fx
import fixtures_coverage as fc
from helpers import BUILDER_PIN, one_workspace, two_workspaces
from zenux_dashboard import control_view, coverage_view, labels, radar_view
from zenux_dashboard.config import parse_config

TZ = "America/New_York"


class DiagnosticsShapeTests(unittest.TestCase):
    def setUp(self):
        self.conf = parse_config(one_workspace())
        self.ws = self.conf.workspace("pilot")

    def report(self, hub=None, hub_error=None, modules=None):
        return {"fetched_at": fx.iso(0), "hub": {"data": hub, "error": hub_error},
                "modules": modules or {"ai-infra": {"data": fx.module_health("ai-infra"), "error": None},
                                       "defense-unmanned": {"data": fx.module_health("defense-unmanned"), "error": None}}}

    def test_lane_counts_shapes(self):
        self.assertEqual(control_view.lane_counts({"events": {"24h": {"a": 1, "total": 9}}}, "24h"), {"a": 1})
        self.assertEqual(control_view.lane_counts({"counts": {"last_7d": [{"lane": "a", "count": 2}]}}, "7d"), {"a": 2})
        self.assertEqual(control_view.lane_counts({"events_24h": 5}, "24h"), {"all lanes": 5})
        self.assertEqual(control_view.lane_counts({"lanes": [{"lane": "a", "24h": 1, "7d": 4}]}, "7d"), {"a": 4})
        self.assertEqual(control_view.lane_counts(None, "7d"), {})

    def test_summary_merges_hub_and_modules(self):
        s = control_view.summarize(self.ws, self.report(fx.diagnostics()))
        self.assertEqual(s["level"], "amber")
        self.assertEqual([r["message"] for r in s["reasons"]], ["defense-unmanned/sam-opps is failing (HTTP 429, 3 runs)"])
        self.assertEqual((s["backlog"], s["fresh_backlog"]["now"], s["dead_letters"], s["delivery_failed"]), (57, 21, 2, 0))
        self.assertTrue(s["lease"]["held"])
        self.assertTrue(s["can_ack"])
        self.assertEqual(s["last_edition_id"], 12)
        self.assertEqual([(r["module"], r["key"], r["kind"]) for r in s["failing"]],
                         [("defense-unmanned", "sam-opps", "failing")])
        self.assertEqual([(r["module"], r["key"]) for r in s["silent"]], [("defense-unmanned", "dod-budget")])
        by_id = {m["id"]: m for m in s["modules"]}
        self.assertEqual((by_id["ai-infra"]["status"], by_id["defense-unmanned"]["status"]), ("ok", "degraded"))
        self.assertEqual(by_id["ai-infra"]["events_24h"], {"companies": 12, "trade_press": 30})
        self.assertFalse(control_view.summarize(self.ws, self.report(fx.diagnostics(legacy=True)))["can_ack"])

    def test_summary_hub_down_and_module_down(self):
        s = control_view.summarize(self.ws, self.report(None, "unreachable (ConnectionError)", {
            "ai-infra": {"data": None, "error": "timed out"},
            "defense-unmanned": {"data": fx.module_health("defense-unmanned", ok=False), "error": None},
        }))
        self.assertEqual(s["level"], "red")
        by_id = {m["id"]: m for m in s["modules"]}
        self.assertEqual((by_id["ai-infra"]["status"], by_id["ai-infra"]["reason"]), ("down", "timed out"))
        self.assertEqual(by_id["defense-unmanned"]["status"], "failed")
        self.assertEqual([r["message"] for r in s["reasons"]], ["ai-infra did not answer its health check (timed out)",
                                                                "defense-unmanned reports that its last run failed"])

    def test_summary_all_ok(self):
        s = control_view.summarize(self.ws, self.report(fx.diagnostics(failing=False) | {"modules": [
            {"module_id": "ai-infra", "status": "ok"}, {"module_id": "defense-unmanned", "status": "ok"}]}))
        self.assertEqual((s["level"], s["reasons"]), ("green", []))

    def test_severity_levels_come_from_the_hub(self):
        for level, css, text in (("red", "bad", "needs action"), ("amber", "warn", "needs attention"),
                                 ("green", "ok", "healthy")):
            with self.subTest(level=level):
                diag = fx.diagnostics(failing=False)
                diag["severity"] = {"level": level, "acknowledged": [], "reasons": [] if level == "green" else [
                    {"level": "amber", "code": "fresh_backlog_growing", "message": "More fresh stories wait each run"},
                    {"level": level, "code": "grader_missed", "message": "The Grader did not lease at 12:30 ET"}]}
                s = control_view.summarize(self.ws, self.report(diag))
                self.assertEqual(s["level"], level)
                card = control_view.health_card_html(self.ws, s)
                self.assertIn(f'<div class="health-card {css}">', card)
                self.assertIn(f'<span class="status-pill {css}">{text}</span>', card)
                if level == "red":
                    self.assertEqual([r["message"] for r in s["reasons"]],
                                     ["The Grader did not lease at 12:30 ET", "More fresh stories wait each run"])

    def test_unreachable_configured_module_is_red_whatever_the_hub_says(self):
        s = control_view.summarize(self.ws, self.report(fx.diagnostics(failing=False), modules={
            "ai-infra": {"data": None, "error": "unreachable (ConnectionError)", "kind": "unreachable"},
            "defense-unmanned": {"data": None, "error": "HTTP 401: run token refused", "kind": "unauthorized"}}))
        self.assertEqual(s["level"], "red")
        self.assertEqual([r["message"] for r in s["reasons"]], [
            "ai-infra did not answer its health check (unreachable (ConnectionError))",
            "defense-unmanned refused the dashboard's run token, so its health cannot be read"])
        self.assertEqual(control_view.summarize(self.ws, self.report(None, "HTTP 503: schema_outdated"))["level"], "red")

    def test_configured_module_never_shows_ok_when_the_hub_reports_it_dead(self):
        diag = fx.diagnostics(failing=False)
        diag["modules"][0].update(status="ok", stale=True, minutes_since_run=47)
        diag["modules"][1].update(status="no_runs", last_run=None)
        diag["severity"] = {"level": "red", "acknowledged": [], "reasons": [
            {"level": "red", "code": "module_stale", "module": "ai-infra",
             "message": "ai-infra has not run for 47 minutes (it runs every 10 minutes)"}]}
        s = control_view.summarize(self.ws, self.report(diag))
        by_id = {m["id"]: m for m in s["modules"]}
        self.assertEqual((by_id["ai-infra"]["status"], by_id["ai-infra"]["reason"]),
                         ("stale", "no run for 47 min (it runs every 10 min)"))
        self.assertEqual(control_view._stale_reason({"minutes_since_run": 548, "interval_minutes": 10}),
                         "no run for 9 h (it runs every 10 min)")
        self.assertEqual(control_view._stale_reason({"minutes_since_run": 3000}), "no run for 2 days")
        self.assertEqual(control_view.module_pill(by_id["ai-infra"]), '<span class="status-pill bad">stale</span>')
        self.assertEqual(control_view.module_pill(by_id["defense-unmanned"]),
                         '<span class="status-pill warn">no runs</span>')
        diag["modules"][0].update(stale=False, retired=True)
        s = control_view.summarize(self.ws, self.report(diag))
        self.assertEqual({m["id"]: m["status"] for m in s["modules"]}["ai-infra"], "stale")

    def test_older_hub_without_severity_gets_a_conservative_estimate(self):
        diag = fx.diagnostics(failing=False, legacy=True) | {"status": "ok", "modules": [
            {"module_id": "ai-infra", "status": "ok"}, {"module_id": "defense-unmanned", "status": "no_runs"}]}
        s = control_view.summarize(self.ws, self.report(diag))
        self.assertEqual(s["level"], "amber")
        self.assertEqual([r["message"] for r in s["reasons"]], ["defense-unmanned has not reported a run yet"])
        diag["modules"][0].update(status="ok", stale=True)
        s = control_view.summarize(self.ws, self.report(diag))
        self.assertEqual(s["level"], "red")
        self.assertIsNone(s["fresh_backlog"])
        self.assertIsNone(s["routines"])

    def test_acknowledged_sources_leave_the_failing_list(self):
        diag = fx.diagnostics()
        diag["modules"][1]["failing"][0]["acknowledged"] = {"acked_at": fx.iso(1), "note": "SAM rate limit, known"}
        diag["severity"] = {"level": "amber", "reasons": [
            {"level": "amber", "code": "module_partial", "message": "defense-unmanned: some sources failed"}],
            "acknowledged": [{"module": "ai-infra", "source_key": "sify-news", "kind": "failing",
                              "fingerprint": "failing:error:-", "acked_at": fx.iso(2), "note": "times out"}]}
        s = control_view.summarize(self.ws, self.report(diag))
        self.assertEqual(s["failing"], [])
        self.assertEqual([(a["module"], a["key"], a["note"]) for a in s["acknowledged"]],
                         [("ai-infra", "sify-news", "times out"), ("defense-unmanned", "sam-opps", "SAM rate limit, known")])
        card = control_view.health_card_html(self.ws, s)
        self.assertIn('<div class="tile "><div class="tile-n">0</div><div class="tile-l">Failing sources</div>'
                      '<div class="tile-d">2 acknowledged</div>', card)

    def test_stories_waiting_is_coloured_by_trend_only(self):
        for trend, now, css in (("growing", 40, "warn"), ("steady", 400, ""), ("shrinking", 900, ""), ("unknown", 5, "")):
            with self.subTest(trend=trend):
                diag = fx.diagnostics()
                diag["review"]["backlog"] = 1986
                diag["review"]["fresh_backlog"] = {"now": now, "trend": trend, "recent_runs": []}
                s = control_view.summarize(self.ws, self.report(diag))
                self.assertEqual(control_view.stories_tile(s), control_view.tile(
                    "Stories waiting", now, f"fresh, 7 days · 1986 in all · trend {trend} · 807 auto-rejected as stale",
                    css))
        legacy = control_view.summarize(self.ws, self.report(fx.diagnostics(legacy=True) | {"review": {"backlog": 400}}))
        self.assertEqual(control_view.stories_tile(legacy),
                         control_view.tile("Stories waiting", 400, "in all, waiting for the Grader"))

    def test_aged_out_agreement_and_storage_tiles(self):
        self.assertEqual(control_view.aged_out_tile({"last_24h": 31, "waited_last_24h": 0}),
                         control_view.tile("Aged out unread (24 h)", 31, "0 arrived fresh"))
        self.assertIn('<div class="tile warn"><div class="tile-n">12</div>',
                      control_view.aged_out_tile({"last_24h": 12, "waited_last_24h": 3}))
        self.assertEqual(control_view.aged_out_tile(None), "")
        grading = fx.diagnostics()["grading"]
        self.assertEqual(control_view.agreement_tile(grading), control_view.tile(
            "Grader agreement (30 days)", "68% same band", "n=22 · 95% within one band · 7 days: 67%"))
        empty = {"agreement": {"last_7d": {"n": 0, "same_band_pct": None}, "last_30d": {"n": 0, "same_band_pct": None}}}
        self.assertEqual(control_view.agreement_tile(empty), control_view.tile("Grader agreement (30 days)", "no grades yet"))
        self.assertEqual(control_view.storage_tile({"db_bytes": 41_000_000, "limit_bytes": 10_000_000_000, "used_pct": 0.4}),
                         control_view.tile("Database size", "0.0 GB of 10 GB", "41 MB · 0.4% used"))
        self.assertIn('<div class="tile warn"><div class="tile-n">7.2 GB of 10 GB</div>',
                      control_view.storage_tile({"db_bytes": 7_200_000_000, "limit_bytes": 10_000_000_000, "used_pct": 72}))
        self.assertIn(">unknown<", control_view.storage_tile({"db_bytes": None, "used_pct": None}))

    def test_problem_text_and_dead_letters(self):
        self.assertEqual(control_view.problem_text({"kind": "structural_empty", "empty_streak": 4}), "empty 4 runs in a row")
        self.assertEqual(control_view.problem_text({"kind": "quota_streak", "quota_streak": 3}),
                         "quota used up 3 runs in a row")
        self.assertEqual(control_view.problem_text({}), "")
        diag = fx.diagnostics()
        diag["dead_letters"].update(total=5, delivery_failed=3, by_reason={"invalid": 2, "delivery_failed": 3})
        s = control_view.summarize(self.ws, self.report(diag))
        self.assertEqual(control_view.dead_letters_tile(s),
                         control_view.tile("Dead letters", 5, "delivery failed 3, invalid 2", "bad"))

    def test_routines_table_states(self):
        routines = fx.diagnostics()["routines"]
        html = control_view.routines_html(routines, TZ)
        self.assertIn("<td>Grader</td><td>7:30 AM · 12:30 PM · 4:30 PM ET</td><td>2h ago</td>"
                      '<td><span class="status-pill ok">done</span>', html)
        self.assertIn("<td>Radar scout</td><td>1:00 PM ET</td><td>never</td>"
                      '<td><span class="status-pill idle">never seen</span></td>', html)
        self.assertIn('<span class="status-pill bad">never seen</span>',
                      control_view.routines_html(routines, TZ, ["scout_missed"]))
        self.assertEqual(control_view.routines_html(None, TZ), "")
        self.assertEqual(control_view.clock_label("00:05"), "12:05 AM")

    def test_build_canary_and_lease(self):
        s = control_view.summarize(self.ws, self.report(fx.diagnostics()))
        self.assertIn("<span>cleaned up 5h ago</span>", control_view.footer_html(s))
        self.assertEqual(control_view.build_text({"git_sha": None, "schema_version": 7, "db_schema_version": 6}),
                         "Hub build unknown · schema 7 (database 6)")
        now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(control_view.lease_of({"lease": {"run_id": "r", "expires_at": "2026-10-03T12:10:00Z"}}, now)["held"])
        self.assertIsNone(control_view.lease_of({}, now))

    def test_job_progress_and_sources(self):
        self.assertEqual(control_view.job_counts(fx.job("running", 1, 2)), (1, 3))
        self.assertAlmostEqual(control_view.job_fraction(fx.job("running", 1, 3)), 0.25)
        self.assertEqual(control_view.job_fraction({"status": "done"}), 1.0)
        health = fx.module_health("ai-infra") | {"failing": [{"key": "x-fail"}], "silent": [{"key": "Bad Key"}]}
        self.assertEqual(control_view.source_keys(health), ["ai-infra-rss", "ai-infra-sitemap", "edgar-8k", "x-fail"])
        self.assertEqual(control_view.hub_source_keys({"sources": [
            {"source_key": "b"}, {"source_key": "a"}, {"source_key": "gone", "retired": "module_retired"}]}), ["a", "b"])


class ControlShapeTests(unittest.TestCase):
    def test_stage_of_settings(self):
        self.assertEqual(control_view.stage_of(fc.settings()), ("live", "2026-10-01T12:00:00Z"))
        self.assertEqual(control_view.stage_of(fc.settings("staging"))[0], "staging")
        self.assertEqual(control_view.stage_of({"volume": {}})[0], "")
        self.assertEqual(control_view.stage_of({"stage": {"stage": "paused"}})[0], "")

    def test_builder_pin_line_never_shows_the_value(self):
        self.assertEqual(control_view.builder_pin_line(parse_config(one_workspace())),
                         "Builder PIN: set (owner PIN fallback)")
        conf = parse_config(two_workspaces() | {"builder_pin": BUILDER_PIN})
        self.assertEqual(control_view.builder_pin_line(conf), "Builder PIN: set (builder_pin)")
        self.assertEqual(control_view.builder_pin_line(parse_config(two_workspaces())), "Builder PIN: not set")

    def test_module_view_tables(self):
        insp = fc.inspect_ai()
        card = fc.modules()["modules"][0]
        line = control_view.module_line(insp, card, TZ)
        self.assertTrue(line.startswith("Catalog 0.1.0-3f2a9c1b7d4e · pushed "))
        self.assertTrue(line.endswith(" · git abc123def456 · 8 sources (6 on) · 7 entities"))
        self.assertIn("8 sources (6 on)", control_view.module_line(insp, None, TZ))  # counted from the inspector
        sources = control_view.sources_table_html(insp, TZ)
        self.assertIn("<th>Key</th><th>Label</th><th>Origin</th><th>Entity</th><th>Lane</th><th>Connector</th>", sources)
        self.assertIn('<span class="mono">ent-coreweave-2</span>', sources)  # entity feeds are listed here
        self.assertIn("The site blocks automated access.", sources)
        self.assertNotIn("javascript:", sources)
        self.assertIn("<td>own_feed, sec_filings</td>", control_view.entities_table_html(insp))
        self.assertIn("<td>starred</td>", control_view.entities_table_html(insp))
        self.assertIn("<td>Local permitting and zoning</td><td>government</td><td>2</td><td>7</td>",
                      control_view.lanes_table(insp))
        self.assertIn("old-key", control_view.orphans_table(insp))
        self.assertEqual(control_view.orphans_table({"orphans": []}), "")
        self.assertEqual(control_view.sources_table_html({}, TZ), "")


class RadarShapeTests(unittest.TestCase):
    def setUp(self):
        self.rows = {r["id"]: r for r in fc.radar_requests()["requests"]}

    def test_stage_and_timeline_from_the_hub_or_the_row(self):
        self.assertEqual([radar_view.stage_of(self.rows[i]) for i in (46, 45, 44, 43, 42, 41)],
                         ["asked", "proposal", "approved", "applied", "live", "rejected"])
        legacy = {"id": 9, "status": "approved_pending_apply", "created_at": fx.iso(30), "proposed_at": fx.iso(20),
                  "decided_at": fx.iso(10)}
        self.assertEqual(radar_view.stage_of(legacy), "approved")
        self.assertEqual(list(radar_view.timeline_of(legacy)), ["asked", "proposal", "approved"])
        rejected = {"id": 8, "status": "rejected", "created_at": fx.iso(30), "decided_at": fx.iso(10)}
        self.assertEqual(list(radar_view.timeline_of(rejected)), ["asked", "rejected"])
        self.assertEqual(radar_view.stage_of({"status": "queued"}), "asked")
        self.assertEqual(radar_view.stage_of({}), "asked")

    def test_timeline_html(self):
        html = radar_view.timeline_html(self.rows[45], TZ)
        self.assertEqual(html.count('class="timeline-step'), 5)
        self.assertIn('<div class="timeline-step done">Asked<br><span>', html)
        self.assertIn('<div class="timeline-step current">Proposal ready<br><span>', html)
        self.assertIn('<div class="timeline-step">Live</div>', html)
        rejected = radar_view.timeline_html(self.rows[41], TZ)
        self.assertEqual(rejected.count('class="timeline-step'), 2)
        self.assertIn('<div class="timeline-step current">Not added<br>', rejected)

    def test_first_items_and_decisions(self):
        self.assertEqual(radar_view.first_items_lines(5, TZ), ["5 stories collected from it so far."])
        self.assertEqual(radar_view.first_items_lines(1, TZ), ["1 story collected from it so far."])
        self.assertEqual(radar_view.first_items_lines(0, TZ), ["No stories from it yet."])
        self.assertEqual(radar_view.first_items_lines(None, TZ), [])
        items = [{"title": f"Story {n}", "published_at": "2026-10-02T15:00:00Z"} for n in range(5)]
        self.assertEqual(radar_view.first_items_lines(items, TZ), ["Story 0 (Oct 2)", "Story 1 (Oct 2)", "Story 2 (Oct 2)"])
        self.assertEqual(radar_view.decision_text(self.rows[41]), "You withdrew this request.")
        self.assertEqual(radar_view.decision_text(self.rows[40]), "Paywalled: we cannot read it.")
        self.assertEqual(radar_view.decision_text({}), "")

    def test_plain_text_replaces_area_ids(self):
        names = {"ai-infra": "AI infrastructure", "defense-unmanned": "Defense unmanned"}
        self.assertEqual(radar_view.plain_text("Add the feed to ai-infra.", names),
                         "Add the feed to AI infrastructure.")
        self.assertEqual(radar_view.plain_text("ai-infra-rss stays; defense-unmanned too", names),
                         "ai-infra-rss stays; Defense unmanned too")

    def test_request_card_is_plain(self):
        names = {"ai-infra": "AI infrastructure", "defense-unmanned": "Defense unmanned"}
        for rid, row in self.rows.items():
            with self.subTest(rid=rid):
                html = radar_view.request_html(row, names, TZ)
                for word in ("puct-large-load", "html-list", "power_grid", "ai-infra", "registry", "connector"):
                    self.assertNotIn(word, html)
        html = radar_view.request_html(self.rows[46], names, TZ, focused=True)
        self.assertTrue(html.startswith('<div class="rq-card zx-focus"><div class="refine-label">A missed story · asked '))
        self.assertIn('<a class="source-link" href="https://example.com/missed"', html)
        self.assertNotIn("javascript:", radar_view.request_html({"id": 1, "url": "javascript:alert(1)", "text": "x"},
                                                                names, TZ))

    def test_ordered_and_validate(self):
        rows = list(self.rows.values())
        self.assertEqual([r["id"] for r in radar_view.ordered(rows)], [46, 45, 44, 43, 42, 41, 40])
        self.assertEqual([r["id"] for r in radar_view.ordered(rows, "43")][:2], [43, 46])
        self.assertEqual(radar_view.validate("track_source", "short", ""), radar_view.TEXT_MESSAGE)
        self.assertEqual(radar_view.validate("missed_story", "a long enough text", ""), radar_view.LINK_MISSING)
        self.assertEqual(radar_view.validate("track_source", "a long enough text", "ftp://x"), radar_view.LINK_BAD)
        self.assertIsNone(radar_view.validate("missed_story", "a long enough text", "https://example.com/a"))
        self.assertEqual(radar_view.sent_toast("1:00 PM ET"),
                         "Sent to the source finder. It answers after its next run (about 1:00 PM ET).")
        self.assertEqual(radar_view.sent_toast(""), "Sent to the source finder. It answers after its next run.")

    def test_builder_proposal_tables(self):
        proposal = self.rows[45]["proposal"]
        sources = radar_view.sources_table(proposal)
        self.assertIn("<th>Module</th><th>Source key</th><th>Label</th><th>Connector</th><th>Lane</th><th>Trust</th>",
                      sources)
        self.assertIn('<span class="mono">puct-large-load</span>', sources)
        self.assertEqual(radar_view.sources_table({}), "")
        self.assertIn(["Source key", "x-key"], radar_view.proposal_rows({"source": {"key": "x-key"}}))
        self.assertIn("1 registry change: Oncor Electric Delivery", radar_view.registry_html(proposal))
        self.assertIn("Diagnosis: no_source (No source ZENUX reads covered it.)",
                      radar_view.diagnosis_html(proposal, self.rows[45]))
        self.assertIn("rule draft #77", radar_view.diagnosis_html(self.rows[42]["proposal"], self.rows[42]))
        self.assertEqual(radar_view.diagnosis_html({}, {}), "")
        self.assertEqual(radar_view.requests_of([{"id": 1}]), [{"id": 1}])


class CoverageShapeTests(unittest.TestCase):
    def setUp(self):
        self.insp = fc.inspect_ai()

    def test_week_briefings_from_the_inspector(self):
        # gap 12: how many of this week's stories made a briefing, for sources, companies and the totals
        self.assertEqual(coverage_view.week_briefings({"briefing_7d": 2}), " (2 in briefings)")
        self.assertEqual(coverage_view.week_briefings({"briefing_7d": 0}, " in your briefings"),
                         " (0 in your briefings)")
        self.assertEqual(coverage_view.week_briefings({}), "")  # an older hub: nothing claimed
        self.assertEqual(coverage_view.stats_text({"stats": {"items_7d": 12, "briefing_7d": 3, "briefing_30d": 6}}),
                         "12 this week (3 in briefings) · 6 in briefings (30 days)")

    def test_the_inspector_mute_reference_is_enough_to_unmute(self):
        # gap 32: {mute_id, created_at, note, kind, module, ref, label}; no GET /mutes lookup
        ref = {"mute_id": 4, "created_at": "2026-10-01T00:00:00Z", "note": None, "kind": "source",
               "module": "ai-infra", "ref": "gn-themes", "label": "News search: AI data center themes"}
        row = coverage_view.mute_row(ref, {"kind": "source", "module": "ai-infra", "ref": "x", "label": "x"})
        self.assertEqual({k: row[k] for k in ("id", "kind", "module", "ref", "label", "active")},
                         {"id": 4, "kind": "source", "module": "ai-infra", "ref": "gn-themes",
                          "label": "News search: AI data center themes", "active": True})
        older = coverage_view.mute_row({"mute_id": 5}, coverage_view.entity_mute_fallback({"id": "acme", "name": "Acme"}))
        self.assertEqual((older["id"], older["kind"], older["ref"], older["label"]), (5, "entity", "acme", "Acme"))

    def test_columns_and_groups(self):
        columns = coverage_view.build_columns(self.insp)
        names = {code: [(label, [row.get("name") or row.get("label") for _, row, _ in rows]) for label, rows in groups]
                 for code, groups in columns.items()}
        self.assertEqual(names["public"], [("AI cloud", ["CoreWeave", "Nebius"])])
        self.assertEqual(names["private"], [("AI cloud", ["Crusoe", "Stargate LLC"]),
                                            ("Power companies", ["Tennessee Valley Authority", "Example <b>Co</b>"])])
        self.assertEqual(names["industry"], [("Company news and filings", ["SEC filings: data center and AI cloud companies"]),
                                             ("News search", ["News search: AI data center themes"]),
                                             ("Trade press", ["Data Center Dynamics"])])
        self.assertEqual(names["government"], [
            ("Local permitting and zoning", ["Old county permits <page>", "Loudoun County, VA agendas"]),
            ("Power and grid", ["ERCOT large-load interconnection reports"]),
            ("Programs and agencies", ["DOE Genesis Mission"])])
        # row indexes are the inspector's positions (the widget keys use them)
        self.assertEqual([n for n, _, _ in columns["public"][0][1]], [0, 1])
        self.assertEqual([n for n, _, _ in columns["industry"][2][1]], [0])

    def test_column_rules(self):
        self.assertEqual(coverage_view.entity_column({"ownership": "public"}), "public")
        for ownership in ("private", "subsidiary", "government", None, "unknown"):
            self.assertEqual(coverage_view.entity_column({"ownership": ownership}), "private")
        self.assertEqual(coverage_view.entity_column({"ownership": "public", "role": "program"}), "government")
        self.assertEqual(coverage_view.source_column({"origin": "module", "column": "companies"}), "industry")
        self.assertEqual(coverage_view.source_column({"origin": "module", "column": "industry"}), "industry")
        self.assertEqual(coverage_view.source_column({"origin": "module", "column": "government"}), "government")
        self.assertEqual(coverage_view.source_column({"column": None}), "industry")
        self.assertIsNone(coverage_view.source_column({"origin": "entity", "column": "companies"}))
        self.assertEqual(coverage_view.entity_group({"category": "ai_cloud"}), "Ai cloud")
        self.assertEqual(coverage_view.entity_group({}), "Other companies")
        self.assertEqual(coverage_view.source_group({}), "Other sources")

    def test_search_and_show(self):
        def keys(terms, show="all"):
            cols = coverage_view.build_columns(self.insp, coverage_view.terms_of(terms), show)
            return sorted(row.get("id") or row.get("key") for groups in cols.values() for _, rows in groups
                          for _, row, _ in rows)

        self.assertEqual(keys("Crusoe"), ["crusoe"])
        self.assertEqual(keys("crwv"), ["coreweave"])
        self.assertEqual(keys("  dynamics   center "), ["dcd-news"])
        self.assertEqual(keys("", "starred"), ["coreweave"])
        self.assertEqual(keys("", "muted"), ["example-co", "gn-themes"])
        self.assertEqual(keys("", "name_only"), ["crusoe", "doe-genesis"])
        self.assertEqual(keys("", "failing"), ["ercot-large-load"])
        self.assertEqual(keys("crusoe", "starred"), [])
        self.assertEqual(coverage_view.terms_of("  A  b "), ["a", "b"])

    def test_counts_and_rows(self):
        card = fc.modules()["modules"][0]
        self.assertEqual(coverage_view.counts_line(self.insp, card),
                         "7 companies · 6 sources on (2 off) · 1840 stories this week (14 in your briefings) · 61 in "
                         "your briefings in 30 days")
        self.assertEqual(coverage_view.counts_line(self.insp, None),  # counted from the inspector
                         "7 companies · 6 sources on (2 off) · 1840 stories this week (14 in your briefings) · 61 in "
                         "your briefings in 30 days")
        # WF5 AW-12: the 30-day figure is left out when it only repeats this week's
        same = dict(self.insp, totals=dict(self.insp["totals"], briefing_7d=28, briefing_30d=28))
        self.assertTrue(coverage_view.counts_line(same, None).endswith("stories this week (28 in your briefings)"))
        self.assertEqual(coverage_view.tuning_line(self.insp, card), "2 muted · 1 on your watchlist")
        self.assertEqual(coverage_view.tuning_line(self.insp, None), "2 muted · 1 on your watchlist")
        self.assertEqual(coverage_view.tuning_line(fc.inspect_def(), fc.modules()["modules"][1]), "")
        sources = {s["key"]: s for s in self.insp["sources"]}
        self.assertEqual(coverage_view.health_text(sources["dcd-news"], TZ), "Working")
        self.assertEqual(coverage_view.health_text(sources["ercot-large-load"], TZ), "Not responding since Oct 1")
        self.assertTrue(coverage_view.health_text(sources["old-permits"], TZ).startswith("Turned off: The site blocks"))
        self.assertEqual(coverage_view.health_text({}, TZ), "Not run yet")
        crusoe = self.insp["entities"][2]
        self.assertEqual([flag for flag, _, _ in coverage_view.coverage_flags(crusoe)], ["name_only"])
        self.assertIn('<span class="cov-chip cov-chip-name_only" title="ZENUX only catches it when another source names it '
                      'in a story.">Name only</span>', coverage_view.entity_row_html(crusoe))
        self.assertIn("Example &lt;b&gt;Co&lt;/b&gt;", coverage_view.entity_row_html(self.insp["entities"][6]))
        self.assertIn("Old county permits &lt;page&gt;", coverage_view.source_row_html(sources["old-permits"], TZ))

    def test_every_analyst_string_is_plain(self):
        rendered = " ".join(
            [coverage_view.entity_row_html(e) for e in self.insp["entities"]]
            + [coverage_view.source_row_html(s, TZ) for s in self.insp["sources"]]
            + [coverage_view.counts_line(self.insp, None), coverage_view.tuning_line(self.insp, None)]
            + list(coverage_view.SHOW_CHOICES.values()))
        import re
        text = re.sub(r"<[^>]+>", " ", rendered)
        self.assertEqual(labels.find_jargon(text), [])

    def test_mute_fallbacks(self):
        self.assertEqual(coverage_view.source_mute_fallback("ai-infra", self.insp["sources"][0]),
                         {"kind": "source", "module": "ai-infra", "ref": "dcd-news", "label": "Data Center Dynamics"})
        self.assertEqual(coverage_view.entity_mute_fallback(self.insp["entities"][6])["ref"], "example-co")
        self.assertEqual(coverage_view.catalog_missing_sentence("AI infrastructure"),
                         "Coverage details for AI infrastructure aren't ready yet. The builder is setting them up.")


if __name__ == "__main__":
    unittest.main()
