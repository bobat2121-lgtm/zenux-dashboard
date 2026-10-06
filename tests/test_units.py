"""Unit tests for the shell's pure parts: config (with the builder PIN), the sign-in state (bare mode), the HTTP client
and every hub wrapper, formatting, labels (the one vocabulary and the jargon guard), deep-link parsing and the
stylesheet's 12 px floor. View internals are tested by each view's own test_units_<area>.py."""

from __future__ import annotations

import re
import unittest
import zlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import helpers  # noqa: F401  (puts dashboard/ on sys.path)
import fixtures as fx
import requests
import streamlit as st

from helpers import (BUILDER_PIN, FakeHttp, FakeResponse, PILOT_AI, PILOT_HUB, OWNER, PIN, READ, RUN_AI,
                     reset_pin_guard, one_workspace, two_workspaces)
from zenux_dashboard import api, fmt, labels, links, owner
from zenux_dashboard.config import Module, Workspace, normalize_url, parse_config

TZ = "America/New_York"


class ConfigTests(unittest.TestCase):
    def test_parses_workspaces_and_modules(self):
        conf = parse_config(two_workspaces())
        self.assertEqual(conf.ids, ["pilot", "beta"])
        self.assertEqual(conf.problems, ('builder_pin missing: the Control room stays hidden; with two or more '
                                         'workspaces no owner PIN opens it (add builder_pin = "..." at the top of the '
                                         'secrets)',))
        pilot = conf.workspace("pilot")
        self.assertEqual([m.id for m in pilot.modules], ["ai-infra", "defense-unmanned"])
        self.assertTrue(pilot.can_read and pilot.can_write)
        self.assertTrue(pilot.module("ai-infra").can_backfill)
        self.assertEqual(pilot.timezone, "America/New_York")
        self.assertEqual(conf.workspace("beta").timezone, "America/New_York")  # the default
        self.assertIsNone(conf.workspace("nope"))

    def test_repr_never_shows_secret_fields(self):
        conf = parse_config({"builder_pin": BUILDER_PIN, **one_workspace()})
        text = repr(conf)
        for secret in (READ, OWNER, PIN, RUN_AI, BUILDER_PIN):
            self.assertNotIn(secret, text)
        self.assertIn("builder_pin_source='builder_pin'", text)

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
        self.assertIn("run_token missing (backfill disabled; its health shows the hub's view only)", joined)
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
        self.assertFalse(parse_config(None).has_builder)


class BuilderPinConfigTests(unittest.TestCase):
    def pin(self, secrets: dict) -> tuple[str, str, tuple]:
        conf = parse_config(secrets)
        return conf.builder_pin, conf.builder_pin_source, conf.problems

    def test_an_explicit_builder_pin_wins(self):
        self.assertEqual(self.pin({"builder_pin": BUILDER_PIN, **two_workspaces()}), (BUILDER_PIN, "builder_pin", ()))
        self.assertEqual(self.pin({"builder_pin": 24681357, **one_workspace()})[:2], ("24681357", "builder_pin"))

    def test_fallbacks(self):
        # one workspace: the top-level owner_pin, then the workspace's own PIN; two workspaces: only builder_pin
        self.assertEqual(self.pin({"owner_pin": "a-default-pin", **one_workspace()})[:2],
                         ("a-default-pin", "owner_pin"))
        self.assertEqual(self.pin(one_workspace()), (PIN, "workspace", ()))
        missing = ('builder_pin missing: the Control room stays hidden; with two or more workspaces no owner PIN opens '
                   'it (add builder_pin = "..." at the top of the secrets)')
        for secrets in (two_workspaces(), {"owner_pin": "a-default-pin", **two_workspaces()}):
            builder, source, problems = self.pin(secrets)
            self.assertEqual((builder, source), ("", ""))
            self.assertIn(missing, problems)
        self.assertEqual(self.pin({}), ("", "", ()))

    def test_placeholders_count_as_unset_and_short_pins_hide_the_control_room(self):
        for placeholder in ("REPLACE_WITH_A_BUILDER_PIN_OF_8_OR_MORE_CHARACTERS", "...", "<your PIN>"):
            self.assertEqual(self.pin({"builder_pin": placeholder, **one_workspace()})[:2], (PIN, "workspace"))
        builder, source, problems = self.pin({"builder_pin": "short", **one_workspace()})
        self.assertEqual((builder, source), ("", ""))  # given but too short: no fallback
        self.assertIn("builder_pin is shorter than 8 characters (the Control room stays hidden)", problems)
        self.assertFalse(any("short" in p and "builder_pin is" not in p for p in problems))

    def test_the_example_has_no_builder_pin(self):
        import tomllib

        with open(helpers.DASHBOARD / ".streamlit" / "secrets.example.toml", "rb") as handle:
            conf = parse_config(tomllib.load(handle))
        self.assertFalse(conf.has_builder)
        text = (helpers.DASHBOARD / ".streamlit" / "secrets.example.toml").read_text(encoding="utf-8")
        self.assertIn('# builder_pin = "REPLACE_WITH_A_BUILDER_PIN_OF_8_OR_MORE_CHARACTERS"', text)


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

    def test_lock_messages_are_plain(self):
        self.assertEqual(owner.lock_message(None, owner.NO_PIN), "Unlock to edit: use Sign in to edit at the top right.")
        self.assertEqual(owner.lock_message(None, owner.WRONG_PIN),
                         "That PIN doesn't match. After 5 wrong tries every PIN is refused for a while, so wait a few "
                         "minutes before trying again.")
        self.assertEqual(owner.lock_message(None, owner.NOT_CONFIGURED),
                         "Editing is turned off for this workspace until the builder finishes its setup.")


class SessionUnlockTests(unittest.TestCase):
    """owner.unlock / lock / token / builder in bare mode: st.session_state stands in for one browser session, and
    load_config is patched (bare-mode tests never read st.secrets)."""

    def setUp(self):
        reset_pin_guard()
        self.addCleanup(reset_pin_guard)
        for patcher in (patch.object(owner, "_pause"), patch.object(owner, "load_config", side_effect=self.conf)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.secrets = two_workspaces()

    def conf(self):
        return parse_config(self.secrets)

    def ws(self, workspace_id: str = "pilot") -> Workspace:
        return self.conf().workspace(workspace_id)

    def test_unlock_lock_and_token(self):
        pilot, beta = self.ws(), self.ws("beta")
        self.assertEqual(owner.lock_state(pilot), owner.NO_PIN)
        self.assertIsNone(owner.token(pilot))
        self.assertEqual(owner.unlock(pilot, ""), owner.NO_PIN)
        self.assertEqual(owner.unlock(pilot, "nope-nope"), owner.WRONG_PIN)
        self.assertEqual(owner.last_result(pilot), owner.WRONG_PIN)
        self.assertEqual(owner.unlock(pilot, f"  {PIN} "), owner.UNLOCKED)
        self.assertIsNone(owner.last_result(pilot))
        self.assertTrue(owner.is_unlocked(pilot) and owner.can_edit(pilot))
        self.assertEqual(owner.token(pilot), OWNER)
        self.assertEqual(owner.lock_state(pilot), owner.UNLOCKED)
        self.assertIsNone(owner.token(beta))  # a PIN unlocks its own workspace only
        self.assertEqual(owner.unlock(beta, PIN), owner.WRONG_PIN)
        stored = repr(dict(st.session_state))
        self.assertNotIn(PIN, stored)
        owner.lock(pilot)
        self.assertIsNone(owner.token(pilot))
        owner.unlock(pilot, PIN)
        owner.lock()
        self.assertFalse(owner.is_unlocked(pilot))

    def test_a_changed_pin_locks_again(self):
        owner.unlock(self.ws(), PIN)
        self.assertTrue(owner.is_unlocked(self.ws()))
        self.secrets["workspaces"][0]["owner_pin"] = "a-new-pin-entirely"
        self.assertFalse(owner.is_unlocked(self.ws()))

    def test_builder_unlock_and_its_reach(self):
        self.secrets = {"builder_pin": BUILDER_PIN, **two_workspaces()}
        conf = self.conf()
        self.assertFalse(owner.is_builder(conf))
        self.assertEqual(owner.builder_unlock(conf, "nope-nope"), owner.WRONG_PIN)
        self.assertEqual(owner.last_result(builder=True), owner.WRONG_PIN)
        self.assertEqual(owner.builder_unlock(conf, BUILDER_PIN), owner.UNLOCKED)
        self.assertTrue(owner.is_builder(conf) and owner.is_builder())
        self.assertEqual(owner.token(self.ws("beta")), "test-owner-token-beta")  # the builder writes everywhere
        self.assertEqual(owner.lock_state(self.ws()), owner.UNLOCKED)
        owner.lock()
        self.assertFalse(owner.is_builder(conf))
        self.assertEqual(owner.builder_unlock(parse_config(two_workspaces()), BUILDER_PIN), owner.NOT_CONFIGURED)

    def test_owner_unlock_opens_the_builder_only_with_the_same_pin(self):
        self.secrets = {"builder_pin": BUILDER_PIN, **one_workspace()}
        owner.unlock(self.ws(), PIN)
        self.assertFalse(owner.is_builder())
        owner.lock()
        self.secrets = one_workspace()  # the pilot: the builder PIN is the owner PIN
        owner.unlock(self.ws(), PIN)
        self.assertTrue(owner.is_builder())

    def test_adopt_entered_pin_consumes_the_presets(self):
        self.secrets = {"builder_pin": BUILDER_PIN, **two_workspaces()}
        st.session_state[owner.PIN_KEY] = PIN
        st.session_state[owner.BUILDER_PIN_KEY] = BUILDER_PIN
        owner.adopt_entered_pin(self.conf(), self.ws())
        self.assertNotIn(owner.PIN_KEY, st.session_state)
        self.assertNotIn(owner.BUILDER_PIN_KEY, st.session_state)
        self.assertTrue(owner.is_unlocked(self.ws()) and owner.is_builder())

    def test_not_configured(self):
        bare = Workspace(id="x", title="", hub_url="https://h.example", read_token="r")
        self.assertEqual(owner.lock_state(bare), owner.NOT_CONFIGURED)
        self.assertEqual(owner.unlock(bare, PIN), owner.NOT_CONFIGURED)
        self.assertEqual(owner.lock_state(None), owner.NOT_CONFIGURED)
        self.assertIsNone(owner.token(None))


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
        self.assertIn("Zenith-Dashboard", call.headers["User-Agent"])

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

    def test_error_detail_errors_and_data(self):
        self.http.on("POST", PILOT_HUB + "/signoff", FakeResponse(409, {
            "error": "changed_since_viewed", "message": "Coverage changed while you were reviewing. " + "x" * 400,
            "current": {"rubric_version": "r2", "catalog_versions": {}}}))
        with self.assertRaises(api.ApiError) as ctx:
            api.sign_off(self.ws, OWNER, rubric_version="r1", catalog_versions={})
        exc = ctx.exception
        self.assertEqual((exc.kind, exc.status, exc.code), ("http", 409, "changed_since_viewed"))
        self.assertTrue(exc.detail.startswith("Coverage changed while you were reviewing."))
        self.assertLessEqual(len(exc.detail), 300)
        self.assertEqual(exc.data["current"]["rubric_version"], "r2")
        self.assertEqual(exc.errors, [])
        self.http.on("POST", PILOT_HUB + "/preferences", FakeResponse(400, {
            "error": "invalid_preference", "message": "The preference is not valid.",
            "errors": ["text: at least 10 characters", 5, "y" * 300]}))
        with self.assertRaises(api.ApiError) as ctx:
            api.add_preference(self.ws, OWNER, direction="less", scope="standing", text="ten chars!!")
        self.assertEqual(ctx.exception.errors[0], "text: at least 10 characters")
        self.assertEqual(len(ctx.exception.errors), 2)
        self.assertLessEqual(len(ctx.exception.errors[1]), 200)
        self.http.on("GET", PILOT_HUB + "/rules", requests.ConnectionError("down"))
        with self.assertRaises(api.ApiError) as ctx:
            api.rules(self.ws)
        self.assertEqual((ctx.exception.detail, ctx.exception.errors, ctx.exception.data), (None, [], {}))

    def test_not_configured(self):
        bare = Workspace(id="x", title="", hub_url="")
        with self.assertRaises(api.ApiError) as ctx:
            api.hub_get(bare, "/editions")
        self.assertEqual(ctx.exception.kind, "not_configured")
        with self.assertRaises(api.ApiError):
            api.hub_post(self.ws, "/feedback", {}, "")
        self.assertEqual(self.http.calls, [])

    def read(self, fn, path: str, *args, body=None, **kwargs):
        self.http.calls.clear()
        self.http.on("GET", PILOT_HUB + path, body if body is not None else {"ok": True})
        out = fn(self.ws, *args, **kwargs)
        call = self.http.calls[-1]
        self.assertEqual((call.method, call.url, call.bearer), ("GET", PILOT_HUB + path, READ))
        return out, call.params

    def test_read_wrappers(self):
        self.assertEqual(self.read(api.editions, "/editions")[1], {"limit": 5})
        self.assertEqual(self.read(api.editions, "/editions", before=12, limit=1)[1], {"limit": 1, "before": 12})
        self.assertEqual(self.read(api.rejected, "/rejected")[1], {"days": 3, "filter": "all"})
        self.assertEqual(self.read(api.rejected, "/rejected", days=7, filter="near_miss", include_auto=True)[1],
                         {"days": 7, "filter": "near_miss", "include_auto": 1})
        self.assertEqual(self.read(api.modules, "/modules")[1], {})
        self.assertEqual(self.read(api.inspect_module, "/modules/ai-infra/inspect", "ai-infra")[1], {})
        self.assertEqual(self.read(api.mutes, "/mutes")[1], {})
        self.assertEqual(self.read(api.mutes, "/mutes", include_removed=True)[1], {"all": 1})
        self.assertEqual(self.read(api.mute_preview, "/mutes/preview", "source", "dcd-news", "ai-infra")[1],
                         {"kind": "source", "module": "ai-infra", "ref": "dcd-news"})
        self.assertEqual(self.read(api.mute_preview, "/mutes/preview", "entity", "coreweave")[1],
                         {"kind": "entity", "ref": "coreweave"})
        self.assertEqual(self.read(api.stars, "/stars")[1], {})
        self.assertEqual(self.read(api.star_preview, "/stars/preview", "coreweave")[1], {"entity": "coreweave"})
        for fn, path in ((api.preferences, "/preferences"), (api.rules, "/rules"), (api.settings, "/settings"),
                         (api.brief, "/brief"), (api.radar, "/radar"), (api.repairs, "/repairs"),
                         (api.diagnostics, "/diagnostics")):
            self.assertEqual(self.read(fn, path)[1], {})
        self.assertEqual(self.read(api.volume_preview, "/settings/volume/preview", "top")[1], {"mode": "top"})
        self.assertEqual(self.read(api.volume_preview, "/settings/volume/preview", "broad", True)[1],
                         {"mode": "broad", "near_miss_shelf": 1})
        self.assertEqual(self.read(api.volume_preview, "/settings/volume/preview", "top", False)[1],
                         {"mode": "top", "near_miss_shelf": 0})
        with self.assertRaises(api.ApiError):
            api.inspect_module(self.ws, "../admin")
        with self.assertRaises(api.ApiError):
            api.rejected(self.ws, filter="everything")

    def test_one_edition_by_id(self):
        # GET /editions/<id> (gap 1); 404 unknown_edition is None, any other refusal is raised
        found, params = self.read(api.edition, "/editions/7", 7, body=fx.edition_single(7))
        self.assertEqual((found["id"], params), (7, {}))
        self.http.on("GET", PILOT_HUB + "/editions/9", FakeResponse(404, {
            "error": "unknown_edition", "message": "That briefing is no longer available.", "edition_id": 9}))
        self.assertIsNone(api.edition(self.ws, 9))
        self.http.on("GET", PILOT_HUB + "/editions/9", FakeResponse(404, {"error": "not_found"}))
        with self.assertRaises(api.ApiError):
            api.edition(self.ws, 9)
        with self.assertRaises(api.ApiError):
            api.edition(self.ws, 0)

    def test_wf5_read_wrappers(self):
        latest, params = self.read(api.latest_edition, "/editions/latest", body=fx.latest())
        self.assertEqual((latest["latest_edition_id"], params), (12, {}))
        self.assertEqual(self.read(api.search_editions, "/editions/search", "  grid   power ")[1],
                         {"q": "grid power", "days": 90, "limit": 50})
        self.assertEqual(self.read(api.search_editions, "/editions/search", "grid", days=30, limit=10, offset=50)[1],
                         {"q": "grid", "days": 30, "limit": 10, "offset": 50})
        self.assertEqual(self.read(api.status, "/status", body=fx.status())[1], {})
        self.assertEqual(self.read(api.bring_back_preview, "/mutes/bring-back-preview", 4)[1],
                         {"mute_id": 4, "days": 7})
        self.assertEqual(self.read(api.rejected, "/rejected", filter="same_story", q=" coreweave  texas ",
                                   module="ai-infra", offset=500)[1],
                         {"days": 3, "filter": "same_story", "q": "coreweave texas", "module": "ai-infra",
                          "offset": 500})
        self.assertEqual(self.read(api.rejected, "/rejected", filter="old_news")[1], {"days": 3, "filter": "old_news"})
        self.http.calls.clear()
        for bad in (lambda: api.search_editions(self.ws, "   "), lambda: api.bring_back_preview(self.ws, 0),
                    lambda: api.rejected(self.ws, module="../x")):
            with self.assertRaises(api.ApiError):
                bad()
        self.assertEqual(self.http.calls, [])  # refused before anything was sent

    def test_schema_11_read_wrappers(self):
        # docs/SPEC-SIMPLIFY.md 1.3 and 1.5: a briefing's left-out list (whatever `days` says: none is sent), the
        # left-out search over 90 days, and the weekly tune-up
        self.assertEqual(self.read(api.rejected, "/rejected", days=None, edition_id=12)[1],
                         {"filter": "all", "edition_id": 12})
        self.assertEqual(self.read(api.rejected, "/rejected", days=None, edition_id=12, offset=500)[1],
                         {"filter": "all", "edition_id": 12, "offset": 500})
        self.assertEqual(self.read(api.rejected, "/rejected", days=90, q="grid", limit=20)[1],
                         {"days": 90, "filter": "all", "q": "grid", "limit": 20})
        body, params = self.read(api.tuneup, "/tuneup", body=fx.tuneup_due())
        self.assertEqual((body["due"], len(body["items"]), params), (True, 5, {}))
        self.http.calls.clear()
        for bad in (lambda: api.rejected(self.ws, edition_id=0), lambda: api.rejected(self.ws, edition_id="x")):
            with self.assertRaises(api.ApiError):
                bad()
        self.assertEqual(self.http.calls, [])

    def test_schema_11_write_wrappers(self):
        self.assertEqual(self.post(api.dismiss_tuneup, "/tuneup/dismiss"), {})
        for role in ("grader", "refiner", "scout"):
            self.assertEqual(self.post(api.allow_once, "/admin/routines/allow-once", role), {"role": role})
        self.http.calls.clear()
        with self.assertRaises(api.ApiError) as ctx:
            api.allow_once(self.ws, OWNER, "everyone")
        self.assertEqual(ctx.exception.kind, "invalid")
        self.assertEqual(self.http.calls, [])

    def post(self, fn, path: str, *args, **kwargs):
        self.http.calls.clear()
        self.http.on("POST", PILOT_HUB + path, {"ok": True})
        fn(self.ws, OWNER, *args, **kwargs)
        call = self.http.calls[-1]
        self.assertEqual((call.method, call.url, call.bearer), ("POST", PILOT_HUB + path, OWNER))
        return call.body

    def test_write_wrappers(self):
        self.assertEqual(self.post(api.add_preference, "/preferences", direction="more", scope="similar",
                                   text="  production   orders ", item_id=1201, event_id=9001,
                                   expires_at="2026-11-03T05:00:00.000Z"),
                         {"direction": "more", "scope": "similar", "text": "production orders", "item_id": 1201,
                          "expires_at": "2026-11-03T05:00:00.000Z"})
        self.assertEqual(self.post(api.add_preference, "/preferences", direction="less", scope="this_story",
                                   event_id=9001, note="why"),
                         {"direction": "less", "scope": "this_story", "event_id": 9001, "note": "why"})
        self.assertEqual(self.post(api.add_preference, "/preferences", direction="exact", scope="standing",
                                   text="Rank grid approvals high."),
                         {"direction": "exact", "scope": "standing", "text": "Rank grid approvals high."})
        self.assertEqual(self.post(api.rule_action, "/rules/R-0014/end-date", "R-0014", "end-date",
                                   {"expires_at": None}), {"expires_at": None})
        self.assertEqual(self.post(api.rule_action, "/rules/31/approve", 31, "approve",
                                   {"proposed_at": "t", "retire": ["R-1"]}), {"proposed_at": "t", "retire": ["R-1"]})
        self.assertEqual(self.post(api.rule_action, "/rules/I-0003/pause", "I-0003", "pause"), {})
        self.assertEqual(self.post(api.rule_action, "/rules/43/reopen", 43, "reopen"), {})  # undo "Not now"
        self.assertEqual(self.post(api.add_feedback, "/feedback", verdict="factual_error", item_id=1201,
                                   note="It was $48M."),
                         {"verdict": "factual_error", "scope": "item", "item_id": 1201, "note": "It was $48M."})
        self.assertEqual(self.post(api.add_feedback, "/feedback", verdict="watch", event_id=7101),
                         {"verdict": "watch", "scope": "item", "event_id": 7101})
        self.assertEqual(self.post(api.add_feedback, "/feedback", verdict="lead", edition_id=12, item_rank=2, score=91),
                         {"verdict": "lead", "scope": "item", "edition_id": 12, "item_rank": 2, "score": 91})
        self.assertEqual(self.post(api.add_mute, "/mutes", kind="source", module="ai-infra", ref="dcd-news"),
                         {"action": "add", "kind": "source", "module": "ai-infra", "ref": "dcd-news"})
        self.assertEqual(self.post(api.add_mute, "/mutes", kind="entity", ref="coreweave", module="ai-infra",
                                   note="noise"),
                         {"action": "add", "kind": "entity", "ref": "coreweave", "note": "noise"})
        self.assertEqual(self.post(api.add_mute, "/mutes", kind="story", ref="s-100"),
                         {"action": "add", "kind": "story", "ref": "s-100"})
        self.assertEqual(self.post(api.remove_mute, "/mutes", 4, bring_back_days=7),
                         {"action": "remove", "mute_id": 4, "bring_back_days": 7})
        self.assertEqual(self.post(api.remove_mute, "/mutes", 4), {"action": "remove", "mute_id": 4,
                                                                    "bring_back_days": 0})
        self.assertEqual(self.post(api.bring_back, "/mutes", 3), {"action": "bring_back", "mute_id": 3, "days": 7})
        self.assertEqual(self.post(api.add_star, "/stars", "nebius", note="watch it"),
                         {"action": "add", "entity_id": "nebius", "note": "watch it"})
        self.assertEqual(self.post(api.remove_star, "/stars", "nebius"), {"action": "remove", "entity_id": "nebius"})
        self.assertEqual(self.post(api.promote, "/promote", 7101, " it matters "),
                         {"event_id": 7101, "note": "it matters"})
        self.assertEqual(self.post(api.set_volume, "/settings/volume", "top"), {"mode": "top"})
        self.assertEqual(self.post(api.set_volume, "/settings/volume", "broad", near_miss_shelf=True),
                         {"mode": "broad", "near_miss_shelf": True})
        self.assertEqual(self.post(api.suggest_brief_change, "/brief/suggest", "L-1a2b3c4d5e",
                                   "Signed capacity of 50 MW or more."),
                         {"line_id": "L-1a2b3c4d5e", "text": "Signed capacity of 50 MW or more."})
        self.assertEqual(self.post(api.sign_off, "/signoff", rubric_version="r1", catalog_versions={"ai-infra": "v1"},
                                   note="ok"),
                         {"rubric_version": "r1", "catalog_versions": {"ai-infra": "v1"}, "note": "ok"})
        self.assertEqual(self.post(api.sign_off, "/signoff", rubric_version=None, catalog_versions={}),
                         {"rubric_version": None, "catalog_versions": {}})
        self.assertEqual(self.post(api.set_stage, "/admin/stage", "staging"), {"stage": "staging"})
        self.assertEqual(self.post(api.add_radar_request, "/radar/requests", kind="missed_story",
                                   text="We missed the drone award", url="https://example.com/x", module="ai-infra"),
                         {"kind": "missed_story", "text": "We missed the drone award", "url": "https://example.com/x",
                          "module": "ai-infra"})
        self.assertEqual(self.post(api.add_radar_request, "/radar/requests", kind="track_source",
                                   text="Follow the Texas docket"),
                         {"kind": "track_source", "text": "Follow the Texas docket"})
        self.assertEqual(self.post(api.radar_action, "/radar/41/approve", 41, "approve", proposed_at="t1"),
                         {"proposed_at": "t1"})
        self.assertEqual(self.post(api.radar_action, "/radar/41/approve", 41, "approve", proposed_at=None),
                         {"proposed_at": None})  # a draft with no proposal binds to "none"
        self.assertEqual(self.post(api.radar_action, "/radar/41/reject", 41, "reject", note="withdrawn by owner"),
                         {"note": "withdrawn by owner"})
        # source repairs (docs/SPEC-REPAIR-PHASE-B.md 1.2): {note?}, the owner token
        self.assertEqual(self.post(api.repair_action, "/repairs/21/approve", 21, "approve", note="  looks   right "),
                         {"note": "looks right"})
        self.assertEqual(self.post(api.repair_action, "/repairs/21/reject", "21", "reject", note="  "), {})
        self.assertEqual(self.post(api.repair_action, "/repairs/17/withdraw", 17, "withdraw"), {})

    def test_writes_validate_before_sending(self):
        bad = [
            lambda: api.add_preference(self.ws, OWNER, direction="up", scope="similar", item_id=1),
            lambda: api.add_preference(self.ws, OWNER, direction="more", scope="all", item_id=1),
            lambda: api.add_preference(self.ws, OWNER, direction="more", scope="similar"),  # no story
            lambda: api.add_preference(self.ws, OWNER, direction="exact", scope="similar", item_id=1, text="short"),
            lambda: api.add_preference(self.ws, OWNER, direction="less", scope="standing", text="too short"),
            lambda: api.add_preference(self.ws, OWNER, direction="less", scope="similar", item_id=1, text="x" * 501),
            lambda: api.rule_action(self.ws, OWNER, "R-0014", "delete"),
            lambda: api.rule_action(self.ws, OWNER, "../x", "pause"),
            lambda: api.add_feedback(self.ws, OWNER, verdict="great", item_id=1),
            lambda: api.add_feedback(self.ws, OWNER, verdict="lead"),
            lambda: api.add_feedback(self.ws, OWNER, verdict="factual_error", item_id=1),
            lambda: api.add_feedback(self.ws, OWNER, verdict="lead", item_id=1, score=101),
            lambda: api.add_mute(self.ws, OWNER, kind="lane", ref="x"),
            lambda: api.add_mute(self.ws, OWNER, kind="source", ref="dcd-news"),  # a source needs its module
            lambda: api.remove_mute(self.ws, OWNER, 4, bring_back_days=8),
            lambda: api.bring_back(self.ws, OWNER, 4, days=0),
            lambda: api.add_star(self.ws, OWNER, " "),
            lambda: api.promote(self.ws, OWNER, 7101, "no"),
            lambda: api.promote(self.ws, OWNER, 0, "a fine note"),
            lambda: api.set_volume(self.ws, OWNER, "huge"),
            lambda: api.suggest_brief_change(self.ws, OWNER, "L-1", "short"),
            lambda: api.set_stage(self.ws, OWNER, "paused"),
            lambda: api.add_radar_request(self.ws, OWNER, kind="track_source", text="short"),
            lambda: api.add_radar_request(self.ws, OWNER, kind="missed_story", text="We missed the drone award"),
            lambda: api.add_radar_request(self.ws, OWNER, kind="missed_story", text="We missed the drone award",
                                          url="javascript:alert(1)"),
            lambda: api.radar_action(self.ws, OWNER, 41, "delete"),
            lambda: api.repair_action(self.ws, OWNER, 21, "applied"),  # zenux repair apply marks it, not the dashboard
            lambda: api.repair_action(self.ws, OWNER, 0, "approve"),
            lambda: api.repair_action(self.ws, OWNER, "../x", "approve"),
            lambda: api.repair_action(self.ws, OWNER, 21, "reject", note="n" * (api.LONG_TEXT_MAX + 1)),
        ]
        for n, call in enumerate(bad):
            with self.subTest(n=n):
                with self.assertRaises(api.ApiError) as ctx:
                    call()
                self.assertEqual(ctx.exception.kind, "invalid")
                self.assertTrue(ctx.exception.detail)  # a plain sentence for "Not saved: ..."
        self.assertEqual(self.http.calls, [])
        with self.assertRaises(api.ApiError) as ctx:
            api.add_radar_request(self.ws, OWNER, kind="missed_story", text="We missed the drone award")
        self.assertEqual(ctx.exception.detail, "Paste the story's link so the source finder can see what was missed.")

    def test_module_health_accepts_503_body(self):
        self.http.on("GET", PILOT_AI + "/health", FakeResponse(503, {"ok": False, "error": "state_unavailable"}))
        self.assertEqual(api.module_health(self.module)["error"], "state_unavailable")
        self.assertEqual(self.http.calls[0].bearer, RUN_AI)

    def test_module_health_sends_the_run_token_when_configured(self):
        self.http.on("GET", PILOT_AI + "/health", fx.module_health("ai-infra"))
        self.assertEqual(api.module_health(self.module)["last_run"]["status"], "ok")
        call = self.http.calls[0]
        self.assertEqual(call.bearer, RUN_AI)
        self.assertNotIn(RUN_AI, call.url)
        self.http.on("GET", PILOT_AI + "/health", fx.module_liveness("ai-infra"))
        bare = Module(id="ai-infra", url=PILOT_AI)
        self.assertEqual(api.module_health(bare)["service"], "zenux-module")
        self.assertNotIn("Authorization", self.http.calls[1].headers)

    def test_module_health_refused_token(self):
        self.http.on("GET", PILOT_AI + "/health", FakeResponse(401, {"error": "unauthorized"}))
        with self.assertRaises(api.ApiError) as ctx:
            api.module_health(self.module)
        self.assertEqual((ctx.exception.kind, str(ctx.exception)), ("unauthorized", "HTTP 401: run token refused"))

    def test_backfill(self):
        self.http.on("POST", PILOT_AI + "/backfill", FakeResponse(202, fx.job()))
        for days in (0, 31, True, 7.5):
            with self.assertRaises(api.ApiError):
                api.start_backfill(self.module, days)
        with self.assertRaises(api.ApiError):
            api.start_backfill(self.module, 7, ["ok-key", "../etc"])
        self.assertEqual(self.http.calls, [])
        job, created = api.start_backfill(self.module, 14, ["b-key", "a-key", "a-key"], ignore_seen=True)
        self.assertEqual((job["id"], created), ("bf-1", True))
        self.assertEqual(self.http.calls[0].body, {"days": 14, "sources": ["a-key", "b-key"], "ignore_seen": True})
        self.http.on("GET", PILOT_AI + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        self.assertIsNone(api.backfill_status(self.module))

    def test_ack_and_unack_bodies(self):
        self.http.on("POST", PILOT_HUB + "/admin/sources/ack", {"module": "ai-infra", "source_key": "x"})
        self.http.on("POST", PILOT_HUB + "/admin/sources/unack", {"removed": True})
        api.ack_source(self.ws, "ai-infra", "sify-news", "  times out\nfrom Worker egress ", OWNER)
        api.ack_source(self.ws, "ai-infra", "sify-news", "n" * 900, OWNER)
        self.assertEqual(api.unack_source(self.ws, "ai-infra", "sify-news", OWNER), {"removed": True})
        bodies = [c.body for c in self.http.calls]
        self.assertEqual(bodies[0], {"module": "ai-infra", "source_key": "sify-news",
                                     "note": "times out from Worker egress"})
        self.assertEqual(len(bodies[1]["note"]), api.ACK_NOTE_MAX)
        self.assertEqual(bodies[2], {"module": "ai-infra", "source_key": "sify-news"})

    def test_segment_quotes_ids_from_data(self):
        self.assertEqual(api.segment("R-0001"), "R-0001")
        self.assertEqual(api.segment("../admin?x=1"), "..%2Fadmin%3Fx%3D1")


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
        self.assertEqual(fmt.fmt_time("2026-10-03T11:30:00Z", TZ), "Oct 3, 2026 · 7:30 AM ET")
        self.assertEqual(fmt.fmt_time(None), "time unavailable")
        now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(fmt.relative_time(now - timedelta(seconds=20), now), "just now")
        self.assertEqual(fmt.relative_time(now - timedelta(minutes=5), now), "5m ago")
        self.assertEqual(fmt.relative_time(now - timedelta(days=3), now), "3d ago")
        self.assertEqual(fmt.relative_time(now + timedelta(minutes=30), now), "in 30m")

    def test_clock_day_and_date(self):
        at = "2026-10-04T16:30:00Z"
        self.assertEqual(fmt.fmt_clock(at, TZ), "12:30 PM ET")
        self.assertEqual(fmt.clock_text(at, TZ), "12:30 PM")
        self.assertEqual(fmt.fmt_day(at, TZ), "Sun Oct 4")
        self.assertEqual(fmt.fmt_date(at, TZ), "Oct 4")
        self.assertEqual(fmt.fmt_clock("2026-10-04T16:30:00Z", "UTC"), "4:30 PM UTC")
        for fn in (fmt.fmt_clock, fmt.fmt_day, fmt.fmt_date, fmt.clock_text):
            self.assertEqual(fn(None, TZ), "—")

    def test_next_slot(self):
        now = datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)  # 10:00 AM EDT
        self.assertEqual(fmt.next_slot(fmt.DEFAULT_GRADER_TIMES, TZ, now),
                         datetime(2026, 10, 4, 16, 30, tzinfo=timezone.utc))
        late = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)  # 9:00 PM EDT
        self.assertEqual(fmt.next_slot(["16:30", "07:30"], TZ, late), datetime(2026, 10, 5, 11, 30, tzinfo=timezone.utc))
        # across the DST change (2026-11-01, 2 AM): 7:30 AM is 11:30 UTC before, 12:30 UTC after
        evening = datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(fmt.next_slot(["07:30"], TZ, evening), datetime(2026, 11, 1, 12, 30, tzinfo=timezone.utc))
        self.assertEqual(fmt.next_slot(["12:30"], TZ, datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)),
                         datetime(2026, 11, 1, 17, 30, tzinfo=timezone.utc))
        self.assertIsNone(fmt.next_slot(["noon", "25:00", 7], TZ, now))
        self.assertIsNone(fmt.next_slot(None, TZ, now))
        self.assertEqual(fmt.next_slot(["07:30"], "Not/AZone", now), datetime(2026, 10, 5, 7, 30, tzinfo=timezone.utc))

    def test_html_safety(self):
        self.assertEqual(fmt.esc_lines("a <b>\n\n\nc & d"), "a &lt;b&gt;<br>c &amp; d")
        self.assertEqual(fmt.safe_url("javascript:alert(1)"), "")
        self.assertEqual(fmt.safe_url("https://example.com/a?b=1"), "https://example.com/a?b=1")
        self.assertEqual(fmt.link("javascript:alert(1)", "x"), '<span class="source-link no-link">x</span>')
        self.assertEqual(fmt.domain_of("https://www.Example.com/x"), "example.com")
        self.assertEqual(fmt.pill("partial"), '<span class="status-pill warn">partial</span>')

    def test_counts_and_picks(self):
        self.assertEqual(fmt.count_of([1, 2]), 2)
        self.assertEqual(fmt.count_of({"total": "4"}), 4)
        self.assertEqual(fmt.pick({"a": {"b": 1}}, "x", "a.b"), 1)
        self.assertEqual(fmt.join_and(["a", "b", "c"]), "a, b and c")

    def test_module_colors(self):
        self.assertEqual(fmt.module_color("ai-infra"), "#A78BFA")  # violet
        self.assertEqual(fmt.module_color("defense-unmanned"), "#2DD4BF")  # teal
        # every area of the pilot has its own colour, and every named area a colour
        self.assertEqual(set(fmt.MODULE_COLORS), set(fmt.MODULE_NAMES))
        self.assertEqual(len(set(fmt.MODULE_COLORS.values())), len(fmt.MODULE_COLORS))
        self.assertEqual(fmt.module_color("conferences"), "#E879F9")  # fuchsia
        others = ["space-launch", "grid-power", "biotech", "nuclear", "shipbuilding", "x"]
        for mid in others:  # any other module: a palette colour, the same in every process (no salted hash())
            self.assertEqual(fmt.module_color(mid),
                             fmt.TAG_COLORS[zlib.crc32(mid.encode("utf-8")) % len(fmt.TAG_COLORS)])
        self.assertEqual(fmt.tag_style("#2DD4BF"),
                         "color:#2DD4BF;border-color:rgba(45,212,191,0.55);background:rgba(45,212,191,0.14)")

    def test_tag_text_stays_readable_on_its_tinted_fill(self):
        """WCAG: small text needs 4.5:1. A pill's fill is its colour at TAG_FILL over the dark surfaces."""
        def channel(c: float) -> float:
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        def luminance(rgb) -> float:
            r, g, b = (channel(c) for c in rgb)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        def rgb(hex_color: str) -> tuple[int, int, int]:
            h = hex_color.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        css_pills = ("#34D399", "#FBBF24", "#F87171", "#38BDF8")
        for surface in ("#0A0A0A", "#141414", "#1A1A1A"):
            for colour in list(fmt.MODULE_COLORS.values()) + list(fmt.TAG_COLORS) + list(css_pills):
                fill = tuple(round(fmt.TAG_FILL * c + (1 - fmt.TAG_FILL) * s) for c, s in zip(rgb(colour), rgb(surface)))
                hi, lo = sorted((luminance(rgb(colour)), luminance(fill)), reverse=True)
                with self.subTest(colour=colour, surface=surface):
                    self.assertGreaterEqual((hi + 0.05) / (lo + 0.05), 4.5)

    def test_inline_png(self):
        self.assertTrue(fmt.png_data_uri(str(helpers.DASHBOARD / "assets" / "zenux-mark.png"))
                        .startswith("data:image/png;base64,iVBORw0KGgo"))
        self.assertEqual(fmt.png_data_uri(str(helpers.DASHBOARD / "assets" / "no-such-file.png")), "")


class StylesheetTests(unittest.TestCase):
    def setUp(self):
        self.css = (helpers.DASHBOARD / "feed.css").read_text(encoding="utf-8")

    def test_twelve_pixel_minimum(self):
        sizes = re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", self.css)
        sizes += re.findall(r"font:\s*\d{3}\s+(\d+(?:\.\d+)?)px", self.css)
        self.assertTrue(sizes)
        self.assertEqual([s for s in sizes if float(s) < 12], [])

    def test_the_new_classes_are_styled(self):
        for cls in ("zx-status", "zx-dot", "st-key-zx_undo", "zx-undo", "zx-new-briefing", "zx-error", "feed-dateline",
                    "badge-top", "chip-state", "chip-flagged", "chip-corrected", "chip-upheld", "chip-requested",
                    "chip-muted", "chip-starred", "st-key-zx_item_", "st-key-zx_row_", "st-key-zx_actions_",
                    "why-block", "why-row", "why-label", "shelf", "shelf-title", "shelf-row", "correction-note",
                    "zx-focus", "filtered-row", "pref-card", "pref-text", "pref-stats", "pref-meta", "preview-line",
                    "preview-plus", "preview-minus", "brief-part", "brief-line", "cov-head", "cov-col", "cov-row",
                    "cov-name", "cov-chip", "cov-chip-own_feed", "cov-chip-sec_filings", "cov-chip-federal_contracts",
                    "cov-chip-news_search", "cov-chip-name_only", "cov-stats", "timeline", "timeline-step",
                    "zx-locked",
                    # docs/SPEC-SIMPLIFY.md: the banners, the tune-up, the receipt, the groups, the left-out section,
                    # Tuning's rows, What ZENITH looks for on Coverage and the routines' lines
                    "st-key-zx_ok_banner", "st-key-zx_tuneup_banner", "zx-banner-text", "st-key-zx_tu_", "tu-row",
                    "tu-editor", "tu-done", "edition-receipt", "zx-group-title", "zx-group-empty", "st-key-zx_leftout_",
                    "zx-leftout-auto", "tn-title", "tn-rule", "tn-hint", "st-key-zx_rule_", "st-key-zx_how_much",
                    "st-key-zx_rules_bar", "st-key-zx_ended_", "brief-title", "st-key-zx_routine_",
                    # docs/SPEC-MIGRATION-BUILD.md section 7: the Friday "Conferences coming up" card
                    "st-key-zx_conf_", "conf-card", "conf-title", "conf-summary", "conf-month", "conf-month-label",
                    "conf-lines", "conf-line", "conf-flag", "conf-link", "conf-more", "conf-text-block"):
            with self.subTest(cls=cls):
                self.assertIn(cls, self.css)
        for colour in ("#34d399", "#fbbf24", "#f87171", "#38bdf8"):  # the pill colours of the contrast test
            self.assertIn(colour, self.css.lower())

    def test_brief_line_padding_beats_streamlit_markdown_li(self):
        # WF5 AW-9: Streamlit's "<class> li { padding: 0 0 0 .3em }" is more specific than ".brief-line"; the dot overlapped
        self.assertRegex(self.css, r"\.brief-lines \.brief-line[^{]*\{[^}]*padding: 0 0 0 14px !important")

    def test_the_skin_stays(self):
        for rule in ("--zx-green: #006341;", "--zx-bg: #0a0a0a;", ".brand-mark { display: block; flex: none; width: 42px;"):
            self.assertIn(rule, self.css)
        self.assertNotIn("st-key-zx_search", self.css)  # the top-bar Search popover is gone


class LabelsTests(unittest.TestCase):
    def test_tabs(self):
        # docs/SPEC-SIMPLIFY.md 2.1: Briefing (daily), Tuning (weekly), Coverage (setup), the builder's Control room
        self.assertEqual([labels.tab_label(s) for s, _ in labels.TABS],
                         ["Briefing", "Tuning", "Coverage", "Control room"])
        self.assertEqual(labels.ANALYST_TABS, ("briefing", "tuning", "coverage"))
        self.assertEqual(labels.tab_label("nope"), "Briefing")

    def test_reason_labels(self):
        self.assertEqual(len(labels.REASON_LABELS), 24)
        self.assertEqual(labels.reason_label("edition_limit"), "Cut for space")
        self.assertEqual(labels.reason_label("edition_limit", "Cut for space today"), "Cut for space today")
        # a hub label equal to the code; WF5 SA-3: the watch band is "Worth watching", the hub says "Near miss" for a
        # row within 10 of the bar
        self.assertEqual(labels.reason_label("watch", "watch"), "Worth watching")
        self.assertEqual(labels.reason_label("watch", "Near miss"), "Near miss")
        self.assertEqual(labels.reason_label("brand_new_code"), "Left out")
        self.assertEqual(labels.reason_label(None, ""), "Left out")
        for code in labels.SAME_STORY_REASONS + labels.NEAR_MISS_REASONS:
            self.assertIn(code, labels.REASON_LABELS)

    def test_band_and_tier(self):
        self.assertEqual([labels.band_of(s) for s in (95, 90, 89, 70, 69, 40, 39, 0, None, "x")],
                         ["lead", "lead", "digest", "digest", "watch", "watch", "reject", "reject", None, None])
        self.assertEqual(labels.tier_label(1), "Your coverage")
        self.assertEqual(labels.tier_label("read_through"), "Read-through")
        self.assertEqual(labels.tier_label(3), "Industry and policy")
        self.assertEqual(labels.tier_label("catalyst"), "Industry and policy")
        self.assertEqual(labels.tier_label("2"), "Read-through")
        for odd in (None, 4, "x", True):
            self.assertEqual(labels.tier_label(odd), "")

    def test_scope_and_direction(self):
        self.assertEqual(labels.scope_label("this_story"), "Just this story")
        self.assertEqual(labels.scope_label(None), "Standing preference")
        self.assertEqual(labels.direction_label("less"), "Show me less like this")
        self.assertEqual(labels.direction_label(None), "Exactly as I write it")

    def test_preference_text_strips_the_hub_built_parts(self):
        built = ('Show me less like this: fewer stock-move articles. Example: event #1234 "CoreWeave shares jump: '
                 'what it means" from Data Center Dynamics. Applies only to updates of story s-100 ("Neocloud deal").')
        self.assertEqual(labels.preference_text({"text": built}), "Fewer stock-move articles.")
        self.assertEqual(labels.preference_text({"text": "Show me more like this: stories like this example. "
                                                         "Example: event #9 \"X\" from Y."}),
                         "Stories like this example.")
        self.assertEqual(labels.preference_text({"text": "Competitive resizing ranks above people."}),
                         "Competitive resizing ranks above people.")
        self.assertEqual(labels.preference_text({"text": "Rank items like event #1234 lower."}),
                         "Rank items like another story lower.")
        self.assertEqual(labels.preference_text({"text": None}), "")
        for text in (built, "Same as #9002 and #12."):
            self.assertEqual(re.findall(r"#\d", labels.preference_text({"text": text})), [])

    def test_clean_rationale(self):
        self.assertEqual(labels.clean_rationale("Signed 15-year lease (calibrated: owner grade #41)."),
                         "Signed 15-year lease.")
        self.assertEqual(labels.clean_rationale("Routine update; calibrated: owner grades #41, #42 and #43."),
                         "Routine update.")
        self.assertEqual(labels.clean_rationale("Same award as #9002."), "Same award as another story.")
        self.assertEqual(labels.clean_rationale("Published 2026-09-01, 33 days before 2026-10-04; older than the "
                                                "21-day freshness line (rule stale_backlog)."),
                         "Published 2026-09-01, 33 days before 2026-10-04; older than the 21-day freshness line.")
        self.assertEqual(labels.clean_rationale("calibrated: owner grade #41. Strong evidence."), "Strong evidence.")
        self.assertEqual(labels.clean_rationale(None), "")

    def test_clean_rationale_names_preferences_instead_of_ids(self):
        # the editor and the wording assistant cite preference ids ("R-0012"); the analyst sees their own words
        names = {"R-0001": "Stock-price move articles with no new company facts.", "R-0006": "Recaps " + "x" * 80}
        self.assertEqual(labels.clean_rationale("R-0001 and R-0006 ask for less of the same kind of article.", names),
                         "“Stock-price move articles with no new company facts” and “Recaps " + "x" * 52
                         + "…” ask for less of the same kind of article.")
        self.assertEqual(labels.clean_rationale("Stock-move piece; the analyst's preference R-0012 asks for less."),
                         "Stock-move piece; one of your preferences asks for less.")
        self.assertEqual(labels.clean_rationale("R-0012 was cited."), "One of your preferences was cited.")
        self.assertEqual(labels.clean_rationale("A preference: R-0012 applies.", {"R-0012": "Less hype."}),
                         "A preference: “Less hype” applies.")
        self.assertEqual(labels.clean_rationale("Raised by your rule R-0012.", {"R-0012": "More grid deals."}),
                         "Raised by “More grid deals”.")
        self.assertEqual(labels.find_jargon("see R-0012 and I-0003"), ["R-0012", "I-0003"])

    def test_volume_help(self):
        self.assertEqual(labels.volume_help("top", 8), "Up to 8 stories, only the most significant.")
        self.assertEqual(labels.volume_help("standard", None), "Up to 12 stories that clear the usual bar.")
        self.assertEqual(labels.volume_help("broad", 25), "Up to 25 stories, including smaller news worth knowing.")

    def test_area_name(self):
        self.assertEqual(labels.area_name("ai-infra", "AI infrastructure: data centers, colocation"),
                         "AI infrastructure")
        self.assertEqual(labels.area_name("ai-infra"), "AI infrastructure")
        self.assertEqual(labels.area_name("defense-unmanned"), "Defense tech")
        # a known area keeps the name the Briefing's tags use, whatever its catalog title says
        self.assertEqual(labels.area_name("defense-unmanned", "Defense unmanned: drones, counter-drone and autonomy"),
                         "Defense tech")
        # the nine areas of docs/SPEC-MIGRATION-BUILD.md section 2: each module title's part before ":"
        for mid, name in (("coverage", "Your coverage"), ("ai-infra", "AI infrastructure"),
                          ("defense-unmanned", "Defense tech"), ("drones-aviation", "Drones and aviation autonomy"),
                          ("autonomous-vehicles", "Autonomous vehicles"),
                          ("robotics-automation", "Robotics and automation"),
                          ("public-safety", "Public safety and security"),
                          ("space-eo", "Space and Earth observation"), ("conferences", "Conferences")):
            with self.subTest(mid=mid):
                self.assertEqual(labels.area_name(mid), name)
                self.assertEqual(labels.find_jargon(name), [])
        self.assertEqual(labels.area_name("space-launch", "Space launch: rockets and pads"), "Space launch")
        self.assertEqual(labels.area_name("space-launch_ops"), "Space launch ops")
        self.assertEqual(labels.area_name(""), "Coverage area")

    def test_edition_label(self):
        for at, expected in (("2026-10-04T11:41:00Z", "Sun Oct 4 · morning briefing"),
                             ("2026-10-04T16:35:00Z", "Sun Oct 4 · midday briefing"),
                             ("2026-10-04T20:40:00Z", "Sun Oct 4 · afternoon briefing"),
                             ("2026-10-05T01:30:00Z", "Sun Oct 4 · evening briefing"),
                             # DST: 7:41 AM EST on Nov 2 is 12:41 UTC, still a morning briefing
                             ("2026-11-02T12:41:00Z", "Mon Nov 2 · morning briefing"),
                             ("2026-11-02T15:59:00Z", "Mon Nov 2 · morning briefing"),
                             ("2026-11-02T16:00:00Z", "Mon Nov 2 · midday briefing"),
                             (None, "Briefing"), ("junk", "Briefing")):
            with self.subTest(at=at):
                self.assertEqual(labels.edition_label(at, TZ), expected)

    def test_honest_copy(self):
        self.assertEqual(labels.STILL_COLLECTED, "Still collected, kept out of your briefing.")
        self.assertEqual(labels.RATING_HONEST, "Your rating is used to calibrate the next briefing when it differs from "
                                               "the ZENITH editor's score.")
        for text in (labels.STAR_PROMISE, labels.RATING_HONEST, labels.LOCKED_HELP, labels.NO_UNDO):
            self.assertEqual(labels.find_jargon(text), [])

    def test_find_jargon(self):
        positives = ["event #12", "see #9002", "the lease expired", "the cursor moved", "3 dead letters",
                     "the Rule refiner", "Radar scout", "the hub is down", "the Grader", "two lanes", "Tier 1",
                     "a source key", "reason codes", "the ai-infra module", "Backfill now", "below_materiality"]
        for text in positives:
            with self.subTest(text=text):
                self.assertTrue(labels.find_jargon(text))
        negatives = ["Briefing", "Left out of this briefing · Near misses", "Applies from the 12:30 PM briefing.",
                     "Still collected, kept out of your briefing.", "Coverage area", "Top story", "release",
                     "airplanes", "hubbub", "Cursory look", "#12", "scouting"]
        for text in negatives:
            with self.subTest(text=text):
                self.assertEqual(labels.find_jargon(text), [])
        # every hyphenated coverage-area id; "coverage" and "conferences" are plain words, and so is "public-safety"
        # before a noun
        for mid in ("ai-infra", "defense-unmanned", "drones-aviation", "autonomous-vehicles", "robotics-automation",
                    "public-safety", "space-eo"):
            with self.subTest(mid=mid):
                self.assertEqual(labels.find_jargon(f"Added to {mid}."), [mid])
                self.assertEqual(labels.find_jargon(f"area {mid}"), [mid])
        for text in ("Sheriff buyers of plate readers and public-safety drones.", "Your coverage", "Conferences coming up"):
            with self.subTest(text=text):
                self.assertEqual(labels.find_jargon(text), [])

    def test_every_plain_label_passes_the_jargon_guard(self):
        texts = (list(labels.REASON_LABELS.values()) + list(labels.VERDICT_LABELS.values())
                 + list(labels.BAND_LABELS.values()) + list(labels.SCOPE_LABELS.values())
                 + list(labels.SCOPE_HELP.values()) + list(labels.DIRECTION_LABELS.values())
                 + list(labels.STATUS_LABELS.values()) + list(labels.ROUTINE_NAMES.values())
                 + list(labels.VOLUME_LABELS.values()) + list(labels.MUTE_KIND_LABELS.values())
                 + list(labels.SOURCE_STATE_LABELS.values()) + [x for c in labels.COVERAGE_ICONS for x in c[1:]]
                 + [c[1] for c in labels.COLUMNS] + list(labels.RADAR_KIND_LABELS.values())
                 + [s[1] for s in labels.RADAR_STAGES] + list(labels.RADAR_SOURCE_STATES.values())
                 + list(labels.DIAGNOSIS_LABELS.values()) + list(labels.STATUS_TEXT.values()) + [t[1] for t in labels.TABS])
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(labels.find_jargon(text), [])


class LinksTests(unittest.TestCase):
    def test_parse_validates_every_parameter(self):
        conf = parse_config(two_workspaces())
        good = {"tab": "tuning", "ws": "beta", "edition": "12", "item": "1203", "rules": "muted", "pref": "R-0012",
                "module": "ai-infra", "request": "41"}
        self.assertEqual(links.parse(good, conf), {**good, "edition": 12, "item": 1203, "request": 41})
        bad = {"tab": "rules", "ws": "gamma", "edition": "0", "item": "12a", "rules": "rejected", "section": "rules",
               "pref": "R-12", "module": "AI Infra", "request": "-4", "token": "x", "view": "muted"}
        self.assertEqual(links.parse(bad, conf), {})
        self.assertEqual(links.parse({"tab": ["coverage", "briefing"]}, conf), {"tab": "coverage"})
        self.assertEqual(links.parse({"ws": "pilot"}, None), {})

    def test_old_links_are_translated(self):
        # docs/SPEC-SIMPLIFY.md 2.1: tab=preferences opens Tuning, tab=filtered opens Briefing; the old section= of My
        # preferences picks the part of Tuning, or opens Coverage for What ZENITH looks for; it is never kept
        self.assertEqual(links.parse({"tab": "preferences", "pref": "R-0012", "section": "active"}, None),
                         {"tab": "tuning", "pref": "R-0012"})
        self.assertEqual(links.parse({"tab": "preferences", "section": "muted"}, None), {"tab": "tuning", "rules": "muted"})
        self.assertEqual(links.parse({"tab": "preferences", "section": "watchlist", "rules": "less"}, None),
                         {"tab": "tuning", "rules": "less"})
        self.assertEqual(links.parse({"tab": "preferences", "section": "looks_for", "pref": "R-0012"}, None),
                         {"tab": "coverage"})
        self.assertEqual(links.parse({"tab": "filtered", "view": "muted"}, None), {"tab": "briefing"})
        self.assertEqual(links.parse({"tab": "briefing", "section": "muted"}, None), {"tab": "briefing"})
        self.assertEqual((links.tab_slug("preferences"), links.tab_slug("filtered"), links.tab_slug("nope")),
                         ("tuning", "briefing", None))

    def test_href(self):
        self.assertEqual(links.href("briefing", edition=12, item=1203), "?tab=briefing&edition=12&item=1203")
        self.assertEqual(links.href("tuning", pref="R-0012", rules="less", ws=None), "?tab=tuning&rules=less&pref=R-0012")
        self.assertEqual(links.href("tuning", section="muted"), "?tab=tuning")  # section is only ever read
        self.assertEqual(links.href("coverage"), "?tab=coverage")

    def test_the_params_cover_the_tabs(self):
        self.assertEqual(set(links.TAB_PARAMS), {slug for slug, _ in labels.TABS})
        self.assertEqual(set(links.FOCUS_PARAMS), {p for ps in links.TAB_PARAMS.values() for p in ps})


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


if __name__ == "__main__":
    unittest.main()
