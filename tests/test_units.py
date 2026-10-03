"""Unit tests for the pure parts: config, HTTP client, PIN gate, formatting and view shape helpers."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import helpers  # noqa: F401  (puts dashboard/ on sys.path)
import fixtures as fx
import requests

from helpers import FakeHttp, FakeResponse, PILOT_AI, PILOT_HUB, OWNER, PIN, READ, RUN_AI, one_workspace, two_workspaces
from zenux_dashboard import api, diagnostics_view, feed_view, fmt, grading, owner, radar_view, rejected_view, rules_view
from zenux_dashboard.config import Module, Workspace, normalize_url, parse_config


class ConfigTests(unittest.TestCase):
    def test_parses_workspaces_and_modules(self):
        conf = parse_config(two_workspaces())
        self.assertEqual(conf.ids, ["pilot", "beta"])
        self.assertEqual(conf.problems, ())
        pilot = conf.workspace("pilot")
        self.assertEqual([m.id for m in pilot.modules], ["ai-infra", "defense-unmanned"])
        self.assertTrue(pilot.can_read and pilot.can_write)
        self.assertTrue(pilot.module("ai-infra").can_backfill)
        self.assertEqual(pilot.timezone, "America/New_York")
        self.assertEqual(conf.workspace("beta").timezone, "America/New_York")  # the default
        self.assertIsNone(conf.workspace("nope"))

    def test_repr_never_shows_secret_fields(self):
        conf = parse_config(one_workspace())
        text = repr(conf)
        for secret in (READ, OWNER, PIN, RUN_AI):
            self.assertNotIn(secret, text)

    def test_problems_name_fields_never_values(self):
        conf = parse_config({"workspaces": [
            {"id": "Bad Id", "hub_url": "https://x"},
            {"id": "ok", "hub_url": "http://hub.example.com", "read_token": "", "owner_token": "secret-owner-value"},
            {"id": "ok", "hub_url": "https://dup.example.com"},
            {"id": "two", "hub_url": "https://u:p@hub.example.com", "read_token": "r",
             "modules": [{"id": "m1", "url": "https://m.example.com"}, {"id": "m1", "url": "https://m.example.com"},
                         {"id": "", "url": "https://m.example.com"}]},
        ]})
        joined = "\n".join(conf.problems)
        self.assertIn("workspace #1: id is missing or invalid", joined)
        self.assertIn("workspace 'ok': hub_url must use https", joined)
        self.assertIn("workspace 'ok': read_token missing", joined)
        self.assertIn("workspace 'ok': duplicate id", joined)
        self.assertIn("workspace 'two': hub_url must not carry credentials", joined)
        self.assertIn("workspace 'two' module 'm1': duplicate id", joined)
        self.assertIn("workspace 'two' module #3: id is missing or invalid", joined)
        self.assertIn("run_token missing (backfill disabled)", joined)
        self.assertNotIn("secret-owner-value", joined)
        self.assertEqual(conf.ids, ["ok", "two"])
        self.assertEqual(conf.workspace("ok").hub_url, "")  # an unsafe URL is never used

    def test_localhost_http_is_allowed_for_local_dev(self):
        self.assertEqual(normalize_url("http://127.0.0.1:8787/"), ("http://127.0.0.1:8787", None))
        self.assertEqual(normalize_url("http://hub.localhost:8787"), ("http://hub.localhost:8787", None))
        self.assertEqual(normalize_url("https://zenux-pilot-hub.example.workers.dev/")[0],
                         "https://zenux-pilot-hub.example.workers.dev")
        self.assertEqual(normalize_url("ftp://x")[1], "must be an http(s) URL")
        self.assertEqual(normalize_url("https://x.example?token=1")[1], "must not carry a query or fragment")
        self.assertEqual(normalize_url(None)[1], "missing")

    def test_table_of_tables_and_default_pin(self):
        conf = parse_config({"owner_pin": "shared-pin", "workspaces": {
            "pilot": {"hub_url": "https://h.example", "read_token": "r", "owner_token": "o",
                      "modules": {"ai-infra": {"url": "https://m.example", "run_token": "t"}}},
        }})
        ws = conf.workspace("pilot")
        self.assertEqual(ws.owner_pin, "shared-pin")
        self.assertEqual(ws.module("ai-infra").url, "https://m.example")
        self.assertTrue(ws.can_write)

    def test_empty_or_odd_secrets(self):
        self.assertEqual(parse_config(None).workspaces, ())
        self.assertEqual(parse_config({"workspaces": "nope"}).workspaces, ())
        self.assertEqual(parse_config({"workspaces": [1, "x"]}).workspaces, ())


class PinTests(unittest.TestCase):
    def test_pin_matches_is_exact(self):
        self.assertTrue(owner.pin_matches("1234", "1234"))
        self.assertFalse(owner.pin_matches("1235", "1234"))
        self.assertFalse(owner.pin_matches("12345", "1234"))
        self.assertFalse(owner.pin_matches("", ""))
        self.assertFalse(owner.pin_matches("1234", ""))
        self.assertFalse(owner.pin_matches(None, "1234"))
        self.assertTrue(owner.pin_matches("pïn-ü", "pïn-ü"))

    def test_uses_hmac_compare_digest(self):
        with patch("zenux_dashboard.owner.hmac.compare_digest", return_value=True) as compare:
            self.assertTrue(owner.pin_matches("a", "b"))  # the result comes from compare_digest
        compare.assert_called_once()
        a, b = compare.call_args.args
        self.assertEqual((len(a), len(b)), (32, 32))  # fixed-length digests, never the raw PINs

    def test_lock_state_and_token(self):
        ws = parse_config(one_workspace()).workspace("pilot")
        self.assertEqual(owner.lock_state(ws, ""), owner.NO_PIN)
        self.assertEqual(owner.lock_state(ws, "nope"), owner.WRONG_PIN)
        self.assertEqual(owner.lock_state(ws, PIN), owner.UNLOCKED)
        self.assertEqual(owner.owner_token(ws, PIN), OWNER)
        self.assertIsNone(owner.owner_token(ws, "nope"))
        bare = Workspace(id="x", title="", hub_url="https://h.example", read_token="r")
        self.assertEqual(owner.lock_state(bare, PIN), owner.NOT_CONFIGURED)
        self.assertIn("not configured", owner.lock_message(bare, owner.NOT_CONFIGURED))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.http = FakeHttp()
        for name in ("get", "post"):
            patcher = patch(f"requests.{name}", side_effect=getattr(self.http, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ws = parse_config(one_workspace()).workspace("pilot")
        self.module = self.ws.module("ai-infra")

    def test_hub_get_sends_read_token_in_header_only(self):
        self.http.on("GET", PILOT_HUB + "/rejected", {"items": []})
        self.assertEqual(api.hub_get(self.ws, "/rejected", {"days": 3, "skip": None}), {"items": []})
        call = self.http.calls[0]
        self.assertEqual(call.bearer, READ)
        self.assertEqual(call.params, {"days": 3})
        self.assertNotIn(READ, call.url)
        self.assertIn("Zenux-Dashboard", call.headers["User-Agent"])

    def test_error_mapping(self):
        cases = [
            (FakeResponse(401, {"error": "unauthorized"}), "unauthorized", "HTTP 401: token refused"),
            (FakeResponse(404, {"error": "not_found"}), "not_found", "HTTP 404: not_found"),
            (FakeResponse(500, {"error": "internal_error", "message": "boom"}), "http", "HTTP 500: internal_error (boom)"),
            (FakeResponse(200, no_json=True), "bad_response", "HTTP 200: response is not JSON"),
            (requests.Timeout("slow"), "unreachable", "timed out"),
            (requests.ConnectionError("down"), "unreachable", "unreachable (ConnectionError)"),
        ]
        for response, kind, message in cases:
            with self.subTest(kind=kind):
                self.http.on("GET", PILOT_HUB + "/rules", response)
                with self.assertRaises(api.ApiError) as ctx:
                    api.hub_get(self.ws, "/rules")
                self.assertEqual(ctx.exception.kind, kind)
                self.assertEqual(str(ctx.exception), message)
                self.assertNotIn(READ, str(ctx.exception))

    def test_not_configured(self):
        bare = Workspace(id="x", title="", hub_url="")
        with self.assertRaises(api.ApiError) as ctx:
            api.hub_get(bare, "/editions")
        self.assertEqual(ctx.exception.kind, "not_configured")
        with self.assertRaises(api.ApiError):
            api.hub_post(self.ws, "/feedback", {}, "")
        self.assertEqual(self.http.calls, [])

    def test_module_health_accepts_503_body(self):
        self.http.on("GET", PILOT_AI + "/health", FakeResponse(503, {"ok": False, "error": "state_unavailable"}))
        self.assertEqual(api.module_health(self.module)["error"], "state_unavailable")
        self.assertIsNone(self.http.calls[0].bearer)  # public route: no token sent

    def test_start_backfill_validates_and_posts(self):
        self.http.on("POST", PILOT_AI + "/backfill", FakeResponse(202, fx.job()))
        for days in (0, 31, True, 7.5):
            with self.assertRaises(api.ApiError):
                api.start_backfill(self.module, days)
        with self.assertRaises(api.ApiError):
            api.start_backfill(self.module, 7, ["ok-key", "../etc"])
        self.assertEqual(self.http.calls, [])
        job, created = api.start_backfill(self.module, 14, ["b-key", "a-key", "a-key"])
        self.assertEqual((job["id"], created), ("bf-1", True))
        call = self.http.calls[0]
        self.assertEqual(call.body, {"days": 14, "sources": ["a-key", "b-key"]})
        self.assertEqual(call.bearer, RUN_AI)
        self.http.on("POST", PILOT_AI + "/backfill", FakeResponse(200, fx.job("running", 1, 2)))
        job, created = api.start_backfill(self.module, 1)
        self.assertEqual(self.http.calls[1].body, {"days": 1})
        self.assertEqual((job["status"], created), ("running", False))  # the job in flight, left unchanged

    def test_backfill_status_shapes(self):
        self.http.on("GET", PILOT_AI + "/backfill", {"job": None})
        self.assertIsNone(api.backfill_status(self.module))
        self.http.on("GET", PILOT_AI + "/backfill", fx.job("running", 1, 2))
        self.assertEqual(api.backfill_status(self.module)["status"], "running")
        self.http.on("GET", PILOT_AI + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        self.assertIsNone(api.backfill_status(self.module))
        self.assertEqual(self.http.calls[0].bearer, RUN_AI)
        no_token = Module(id="m", url="https://m.example")
        with self.assertRaises(api.ApiError):
            api.backfill_status(no_token)

    def test_segment_quotes_ids_from_data(self):
        self.assertEqual(api.segment("R-0001"), "R-0001")
        self.assertEqual(api.segment("../admin?x=1"), "..%2Fadmin%3Fx%3D1")
        self.assertEqual(api.segment(31), "31")


class FmtTests(unittest.TestCase):
    def test_parse_time_variants(self):
        expected = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        for value in ("2026-10-03T12:00:00Z", "2026-10-03T08:00:00-04:00", "Sat, 03 Oct 2026 12:00:00 GMT",
                      1791028800, 1791028800000, "1791028800", expected):
            with self.subTest(value=value):
                self.assertEqual(fmt.parse_time(value), expected)
        for value in (None, "", "not a date", True, float("inf")):
            self.assertEqual(fmt.parse_time(value), fmt.MIN_TIME)

    def test_fmt_and_relative_time(self):
        self.assertEqual(fmt.fmt_time("2026-10-03T11:30:00Z", "America/New_York"), "Oct 3, 2026 · 7:30 AM ET")
        self.assertEqual(fmt.fmt_time("2026-10-03T11:30:00Z", "UTC"), "Oct 3, 2026 · 11:30 AM UTC")
        self.assertEqual(fmt.fmt_time(None), "time unavailable")
        now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(fmt.relative_time(now - timedelta(seconds=20), now), "just now")
        self.assertEqual(fmt.relative_time(now - timedelta(minutes=5), now), "5m ago")
        self.assertEqual(fmt.relative_time(now - timedelta(hours=30), now), "30h ago")
        self.assertEqual(fmt.relative_time(now - timedelta(days=3), now), "3d ago")
        self.assertEqual(fmt.relative_time(now + timedelta(minutes=30), now), "in 30m")
        self.assertEqual(fmt.relative_time(None, now), "never")

    def test_html_safety(self):
        self.assertEqual(fmt.esc_lines("a <b>\n\n\nc & d"), "a &lt;b&gt;<br>c &amp; d")
        self.assertNotIn("\n", fmt.esc_lines("x\n\ny"))
        self.assertEqual(fmt.safe_url("javascript:alert(1)"), "")
        self.assertEqual(fmt.safe_url("data:text/html,x"), "")
        self.assertEqual(fmt.safe_url("https://example.com/a?b=1"), "https://example.com/a?b=1")
        self.assertEqual(fmt.link("javascript:alert(1)", "x"), '<span class="source-link no-link">x</span>')
        self.assertIn('href="https://example.com/&quot;x"', fmt.link('https://example.com/"x', "t"))
        self.assertEqual(fmt.domain_of("https://www.Example.com/x"), "example.com")
        self.assertEqual(fmt.pill("partial"), '<span class="status-pill warn">partial</span>')
        self.assertEqual(fmt.pill("weird"), '<span class="status-pill idle">weird</span>')

    def test_counts_and_picks(self):
        self.assertEqual(fmt.count_of([1, 2]), 2)
        self.assertEqual(fmt.count_of({"total": "4"}), 4)
        self.assertEqual(fmt.count_of(None), 0)
        self.assertEqual(fmt.pick({"a": {"b": 1}}, "x", "a.b"), 1)
        self.assertEqual(fmt.pick([], "a", default=5), 5)


class ViewShapeTests(unittest.TestCase):
    def test_feed_shapes(self):
        body = fx.editions(1)
        self.assertEqual(len(feed_view.editions_of(body)), 1)
        self.assertEqual(feed_view.editions_of([{"id": 1}]), [{"id": 1}])
        self.assertIsNone(feed_view.next_cursor(body, feed_view.editions_of(body)))  # short page: no more
        self.assertEqual(feed_view.next_cursor({"next_before": 7}, []), "7")
        full = [{"id": n} for n in range(20, 10, -1)]
        self.assertEqual(feed_view.next_cursor({"editions": full}, full), "11")
        item = body["editions"][0]["items"][1]
        self.assertEqual(feed_view.sources_of(item), [("https://www.war.gov/News/Contracts/", "war.gov")])
        self.assertEqual(feed_view.tier_label(1), "Tier 1 · covered")
        self.assertEqual(feed_view.tier_label("read_through"), "Tier 2 · read-through")
        hits = feed_view.search(fx.editions(2)["editions"], "counter-uas army")
        self.assertEqual([len(e["items"]) for e in hits], [1, 1])
        self.assertEqual([len(feed_view.all_items(e)) for e in hits], [2, 2])  # the band still counts every item
        self.assertIn('<b>200 MW</b>', feed_view.metric_html({"label": "Critical IT", "value": "200", "unit": "MW"}))

    def test_module_names_and_tags(self):
        self.assertEqual(fmt.module_name("ai-infra"), "AI infrastructure")
        self.assertEqual(fmt.module_name("defense-unmanned"), "defense unmanned")
        self.assertEqual(fmt.module_name("space-launch_ops"), "space launch ops")
        self.assertEqual(fmt.join_and([]), "")
        self.assertEqual(fmt.join_and(["a"]), "a")
        self.assertEqual(fmt.join_and(["a", "b", "c"]), "a, b and c")
        self.assertEqual(feed_view.item_modules({"module": "ai-infra"}), ["ai-infra"])
        self.assertEqual(feed_view.item_modules({"module": "ai-infra", "modules": []}), ["ai-infra"])
        self.assertEqual(feed_view.item_modules({"module": "ai-infra", "modules": ["defense-unmanned", "ai-infra",
                                                                                   "defense-unmanned", None]}),
                         ["defense-unmanned", "ai-infra"])
        self.assertEqual(feed_view.item_modules({}), [])
        self.assertEqual(feed_view.module_tags_html({"modules": ["ai-infra", "<x>"]}),
                         '<span class="module-tag">AI INFRASTRUCTURE</span><span class="module-tag">&lt;X&gt;</span>')
        self.assertNotIn("score", feed_view.item_html(fx.editions(1)["editions"][0]["items"][0]).lower())

    def test_fallback_summary(self):
        def item(rank, module, headline="Story"):
            return {"rank": rank, "module": module, "headline": headline}

        items = [item(1, "defense-unmanned", "Army orders a new autonomy command.")] + [
            item(n, "ai-infra" if n <= 5 else "defense-unmanned") for n in range(2, 10)]
        self.assertEqual(feed_view.fallback_summary(items),
                         "9 items across AI infrastructure (4) and defense unmanned (5), led by Army orders a new "
                         "autonomy command.")
        three = [item(1, "space-launch", "Lead story"), item(2, "ai-infra"), item(3, "defense-unmanned")]
        self.assertEqual(feed_view.fallback_summary(three),
                         "3 items across AI infrastructure (1), defense unmanned (1) and space launch (1), led by "
                         "Lead story.")
        self.assertEqual(feed_view.fallback_summary([item(1, "ai-infra", "Lead"), item(2, "ai-infra")]),
                         "2 items in AI infrastructure, led by Lead.")
        self.assertEqual(feed_view.fallback_summary([item(1, "ai-infra", "Only one!")]),
                         "1 item in AI infrastructure: Only one!")
        self.assertEqual(feed_view.fallback_summary([{"rank": 1}]), "1 item.")
        self.assertEqual(feed_view.fallback_summary([]), "An empty edition: nothing cleared the bar in this window.")
        # the summary wins when the hub gives one; the fallback is deterministic
        self.assertEqual(feed_view.summary_of({"summary": "  One sentence.  "}, items), "One sentence.")
        self.assertEqual(feed_view.summary_of({"summary": None}, items), feed_view.fallback_summary(list(items)))
        self.assertEqual(feed_view.note_of({"note": "  Rank 2 is paywalled.\n"}), "Rank 2 is paywalled.")
        self.assertEqual(feed_view.note_of({"note": "   "}), "")

    def test_status_pills_and_inline_png(self):
        self.assertEqual(fmt.pill("missing"), '<span class="status-pill missing">missing</span>')
        self.assertEqual(fmt.pill("failed"), '<span class="status-pill bad">failed</span>')
        self.assertTrue(fmt.png_data_uri(str(helpers.DASHBOARD / "assets" / "zenux-mark.png"))
                        .startswith("data:image/png;base64,iVBORw0KGgo"))
        self.assertEqual(fmt.png_data_uri(str(helpers.DASHBOARD / "assets" / "no-such-file.png")), "")

    def test_rejected_rules_radar_shapes(self):
        self.assertEqual(len(rejected_view.rows_of(fx.rejected())), 3)
        self.assertEqual(rejected_view.rows_of({"decisions": [{"event_id": 1}]}), [{"event_id": 1}])
        precedents, drafts = rules_view.lists_of(fx.rules())
        self.assertEqual([p["id"] for p in precedents], ["R-0001", "I-0001", "R-0002"])
        self.assertEqual([d["id"] for d in drafts], [32, 31, 20])
        self.assertEqual(rules_view.kind_of({"id": "I-0004"}), "item")
        self.assertEqual(rules_view.proposal_of({"proposal": "plain text"}), {"text": "plain text"})
        proposal = fx.radar()["requests"][1]["proposal"]
        self.assertIn('<span class="mono">puct-large-load</span>', radar_view.sources_table(proposal))
        self.assertEqual(radar_view.sources_table({}), "")
        self.assertIn(["Source key", "x-key"], radar_view.proposal_rows({"source": {"key": "x-key"}}))
        self.assertEqual(radar_view.requests_of([{"id": 1}]), [{"id": 1}])

    def test_grading_payload(self):
        option = {"key": "item-1201", "item_id": 1201, "event_id": 9001, "edition_id": 12, "item_rank": 1}
        self.assertEqual(grading.build_payload(option, "Lead", None, " note ", "Just a grade"),
                         {"item_id": 1201, "event_id": 9001, "verdict": "lead", "scope": "item", "note": "note"})
        by_rank = {"edition_id": 12, "item_rank": 1, "item_id": None, "event_id": None}
        self.assertEqual(grading.build_payload(by_rank, "Reject", None, "", "Just a grade"),
                         {"edition_id": 12, "item_rank": 1, "verdict": "reject", "scope": "item", "note": ""})
        self.assertEqual(grading.build_payload({"event_id": 7}, "Factual error", 30, "x", "Just a grade")["verdict"],
                         "factual_error")
        exact = grading.build_payload(option, "Lead", 45, "", "Rule")
        self.assertEqual((exact["verdict"], exact["score"], exact["scope"]), ("watch", 45, "rule"))
        self.assertEqual(grading.build_payload(option, "Digest", 150, "", "Worked example")["score"], 100)
        self.assertEqual(grading.verdict_for_score(39), "reject")
        self.assertEqual(grading.verdict_for_score(90), "lead")


class DiagnosticsShapeTests(unittest.TestCase):
    def setUp(self):
        self.conf = parse_config(one_workspace())
        self.ws = self.conf.workspace("pilot")

    def report(self, hub=None, hub_error=None, modules=None):
        return {"fetched_at": fx.iso(0), "hub": {"data": hub, "error": hub_error},
                "modules": modules or {"ai-infra": {"data": fx.module_health("ai-infra"), "error": None},
                                       "defense-unmanned": {"data": fx.module_health("defense-unmanned"), "error": None}}}

    def test_lane_counts_shapes(self):
        self.assertEqual(diagnostics_view.lane_counts({"events": {"24h": {"a": 1, "total": 9}}}, "24h"), {"a": 1})
        self.assertEqual(diagnostics_view.lane_counts({"counts": {"last_7d": [{"lane": "a", "count": 2}]}}, "7d"), {"a": 2})
        self.assertEqual(diagnostics_view.lane_counts({"events_24h": 5}, "24h"), {"all lanes": 5})
        self.assertEqual(diagnostics_view.lane_counts({"lanes": [{"lane": "a", "24h": 1, "7d": 4}]}, "7d"), {"a": 4})
        self.assertEqual(diagnostics_view.lane_counts(None, "7d"), {})

    def test_summary_merges_hub_and_modules(self):
        s = diagnostics_view.summarize(self.ws, self.report(fx.diagnostics()))
        self.assertEqual(s["status"], "degraded")
        self.assertEqual(s["backlog"], 57)
        self.assertTrue(s["lease"]["held"])
        self.assertEqual(s["dead_letters"], 2)
        self.assertEqual(s["last_edition_id"], 12)
        self.assertEqual([(r["module"], r["key"]) for r in s["failing"]], [("defense-unmanned", "sam-opps")])
        self.assertEqual([(r["module"], r["key"]) for r in s["silent"]], [("defense-unmanned", "dod-budget")])
        by_id = {m["id"]: m for m in s["modules"]}
        self.assertEqual(by_id["ai-infra"]["status"], "ok")
        self.assertEqual(by_id["defense-unmanned"]["status"], "degraded")
        self.assertEqual(by_id["ai-infra"]["events_24h"], {"companies": 12, "trade_press": 30})

    def test_summary_hub_down_and_module_down(self):
        s = diagnostics_view.summarize(self.ws, self.report(None, "unreachable (ConnectionError)", {
            "ai-infra": {"data": None, "error": "timed out"},
            "defense-unmanned": {"data": fx.module_health("defense-unmanned", ok=False), "error": None},
        }))
        self.assertEqual(s["status"], "down")
        by_id = {m["id"]: m for m in s["modules"]}
        self.assertEqual((by_id["ai-infra"]["status"], by_id["ai-infra"]["reason"]), ("down", "timed out"))
        self.assertEqual(by_id["defense-unmanned"]["status"], "failed")

    def test_summary_all_ok(self):
        s = diagnostics_view.summarize(self.ws, self.report(fx.diagnostics(failing=False) | {"modules": [
            {"module_id": "ai-infra", "status": "ok"}, {"module_id": "defense-unmanned", "status": "ok"}]}))
        self.assertEqual(s["status"], "ok")

    def test_module_with_no_runs_does_not_degrade_the_workspace(self):
        diag = fx.diagnostics(failing=False) | {"status": "ok", "modules": [
            {"module_id": "ai-infra", "status": "ok"}, {"module_id": "defense-unmanned", "status": "no_runs"}]}
        s = diagnostics_view.summarize(self.ws, self.report(diag))
        self.assertEqual({m["id"]: m["status"] for m in s["modules"]}["defense-unmanned"], "no_runs")
        self.assertEqual(s["status"], "ok")

    def test_lease_expiry_without_held_flag(self):
        now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(diagnostics_view.lease_of({"lease": {"run_id": "r", "expires_at": "2026-10-03T12:10:00Z"}}, now)["held"])
        self.assertFalse(diagnostics_view.lease_of({"lease": {"run_id": "r", "expires_at": "2026-10-03T11:50:00Z"}}, now)["held"])
        self.assertIsNone(diagnostics_view.lease_of({}, now))

    def test_job_progress_and_sources(self):
        self.assertEqual(diagnostics_view.job_counts(fx.job("running", 1, 2)), (1, 3))
        self.assertEqual(diagnostics_view.job_counts({"done": 4, "remaining": 1}), (4, 5))
        self.assertAlmostEqual(diagnostics_view.job_fraction(fx.job("running", 1, 3)), 0.25)
        self.assertEqual(diagnostics_view.job_fraction({"status": "done"}), 1.0)
        self.assertEqual(diagnostics_view.job_fraction({"status": "queued"}), 0.0)
        health = fx.module_health("ai-infra") | {"failing": [{"key": "x-fail"}], "silent": [{"key": "Bad Key"}]}
        self.assertEqual(diagnostics_view.source_keys(health),
                         ["ai-infra-rss", "ai-infra-sitemap", "edgar-8k", "x-fail"])
        self.assertEqual(diagnostics_view.source_keys(None), [])
        self.assertEqual(diagnostics_view.hub_source_keys({"sources": [
            {"source_key": "b"}, {"source_key": "a"}, {"source_key": "gone", "retired": "module_retired"},
            {"source_key": "Bad Key"}]}), ["a", "b"])


if __name__ == "__main__":
    unittest.main()


class UnquotedNumericPinTest(unittest.TestCase):
    def test_integer_pin_from_toml_is_accepted(self):
        from zenux_dashboard.config import usable_pin
        self.assertEqual(usable_pin(12345678), "12345678")
        self.assertEqual(usable_pin("12345678"), "12345678")
        self.assertEqual(usable_pin(True), "")
        self.assertEqual(usable_pin(None), "")


class PinDiagnosticsTest(unittest.TestCase):
    BASE = {"workspaces": [{"id": "pilot", "hub_url": "https://hub.example.workers.dev", "read_token": "r" * 20,
                            "owner_token": "o" * 20,
                            "modules": [{"id": "ai-infra", "url": "https://m.example.workers.dev", "run_token": "t" * 20}]}]}

    def _problems(self, mutate):
        import copy
        from zenux_dashboard.config import parse_config
        data = copy.deepcopy(self.BASE)
        mutate(data)
        return " | ".join(parse_config(data).problems)

    def test_pin_under_module_is_named(self):
        msg = self._problems(lambda d: d["workspaces"][0]["modules"][0].update(owner_pin="12345678"))
        self.assertIn("inside module 'ai-infra'", msg)
        self.assertNotIn("12345678", msg)

    def test_misspelled_key_is_named(self):
        msg = self._problems(lambda d: d["workspaces"][0].update({"Owner_PIN": "12345678"}))
        self.assertIn("'Owner_PIN'", msg)
        self.assertNotIn("12345678", msg)

    def test_missing_token_and_pin_are_reported_separately(self):
        msg = self._problems(lambda d: d["workspaces"][0].pop("owner_token"))
        self.assertIn("owner_token missing", msg)
        self.assertIn("owner_pin missing", msg)

    def test_correct_pin_has_no_owner_problem(self):
        msg = self._problems(lambda d: d["workspaces"][0].update(owner_pin="12345678"))
        self.assertNotIn("owner_", msg)
