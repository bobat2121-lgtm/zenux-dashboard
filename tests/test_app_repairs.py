"""AppTest: source repairs (docs/SPEC-REPAIR-PHASE-B.md section 3). In the Control room, after the coverage requests:
each proposed repair with its before and after and the probe's evidence, Approve and Reject (a toast, no undo; Reject
asks first), the approved list with the apply command and Withdraw, the applied, recovered, rejected and withdrawn
lists, the hub refusing or failing, who may write (the builder, open access, a workspace without an owner token),
every workspace, and the source-health window's line. On Coverage, the plain line about the sources ZENUX is fixing."""

from __future__ import annotations

import unittest
from typing import Any

import fixtures as fx
import fixtures_coverage as fc
import fixtures_repairs as fr
from helpers import (AppCase, BETA_COV, BETA_HUB, BETA_OWNER, BETA_READ, BUILDER_PIN, FakeResponse, OWNER, PILOT_AI,
                     PILOT_DEF, PILOT_HUB, PIN, READ, hub_defaults, one_workspace, two_workspaces)
from zenux_dashboard import labels, repairs_view, ui
from zenux_dashboard.fmt import esc

REPAIRS = PILOT_HUB + "/repairs"
INSPECT_AI = PILOT_HUB + "/modules/ai-infra/inspect"
INSPECT_DEF = PILOT_HUB + "/modules/defense-unmanned/inspect"
CONFIRM = "dlg_save"  # the confirm button of ui.ask_confirm (dialog keys are dlg_*)
LIGHT_DEF = "cr_light_warn_pilot_defense-unmanned"  # the degraded module's status light (fx.diagnostics: sam-opps)


def undo_of(at) -> Any:
    try:
        return at.session_state[ui.UNDO_KEY]
    except KeyError:
        return None


def with_builder(secrets: dict) -> dict:
    return {**secrets, "builder_pin": BUILDER_PIN}


def post_of(http, url: str):
    calls = http.find("POST", url)
    return calls[0] if calls else None


class RepairsCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        h = self.http
        h.on("GET", PILOT_HUB + "/diagnostics", fx.diagnostics())
        h.on("GET", PILOT_HUB + "/snapshot", fx.snapshot())
        h.on("GET", PILOT_AI + "/health", fx.module_health("ai-infra"))
        h.on("GET", PILOT_DEF + "/health", fx.module_health("defense-unmanned"))
        h.on("GET", PILOT_HUB + "/sources", {"sources": []})
        h.on("GET", PILOT_AI + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        h.on("GET", PILOT_DEF + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        h.on("GET", PILOT_HUB + "/settings", fc.settings())
        h.on("GET", PILOT_HUB + "/radar", fc.radar_requests())
        h.on("GET", PILOT_HUB + "/modules", fc.modules())
        h.on("GET", PILOT_HUB + "/mutes", fc.mutes())
        h.on("GET", INSPECT_AI, fc.inspect_ai())
        h.on("GET", INSPECT_DEF, fc.inspect_def())
        self.rows = fr.repairs_list()
        h.on("GET", REPAIRS, fr.repairs(self.rows))

    def control(self, secrets: dict | None = None, **kwargs):
        """The Control room, unlocked with the builder PIN (the pilot's owner PIN is the fallback for one workspace)."""
        kwargs.setdefault("builder_pin", PIN if secrets is None else BUILDER_PIN)
        return self.app(secrets, tab="control", **kwargs)

    def beta_routes(self, rows: list[dict] | None = None) -> None:
        self.http.on("GET", BETA_HUB + "/diagnostics", fx.diagnostics("beta", failing=False) | {"modules": []})
        self.http.on("GET", BETA_COV + "/health", fx.module_health("coverage"))
        self.http.on("GET", BETA_COV + "/backfill", FakeResponse(404, {"error": "no_backfill_job"}))
        self.http.on("GET", BETA_HUB + "/settings", fc.settings())
        self.http.on("GET", BETA_HUB + "/radar", {"requests": []})
        self.http.on("GET", BETA_HUB + "/repairs", fr.repairs(rows or []))

    @staticmethod
    def card(at, rid: int, ws: str = "pilot") -> str:
        """The HTML of one proposed repair's card."""
        return next(v for v in (str(m.value) for m in at.markdown) if f"{ws} #{rid} · " in v and "Before and after" in v)

    @staticmethod
    def repair_buttons(at) -> list[str]:
        return sorted(str(b.key) for b in at.button if str(b.key or "").startswith("cr_repair_"))


class ReviewTests(RepairsCase):
    def test_every_proposed_repair_with_its_before_after_and_evidence(self):
        at = self.control()
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", REPAIRS)[0].bearer, READ)
        html = self.html(at)
        self.assertLess(html.index("<span>Coverage requests to review</span>"),
                        html.index("<span>Source repairs to review</span>"))
        self.assertIn("Pilot: 4 to review · 1 approved, waiting to be applied · 1 applied, waiting for the source to "
                      "report ok · 1 recovered · 2 rejected or withdrawn", self.texts(at, "caption"))
        # replace: the catalog's entry against the new definition, the probe's answer and up to 5 titles as links
        card = self.card(at, 21)
        self.assertIn('<span class="loop-kind loop-kind-replace">Replace the source</span>'
                      '<span class="status-pill warn">proposed</span>', card)
        self.assertIn("pilot #21 · defense-unmanned · ", card)
        self.assertIn('<span class="failing-name">HavocAI blog (Medium)</span><span class="mono">havocai-medium</span>',
                      card)
        self.assertIn('<div class="refine-note">The site shows our servers a bot check</div>', card)
        self.assertIn("Medium shows Cloudflare&#x27;s servers a bot check; HavocAI posts the same news", card)
        self.assertIn("<th>Before</th><th>After</th>", card)
        self.assertIn(f'<td><span class="mono">{esc(repairs_view.compact_json(fr.HAVOC_BEFORE))}</span></td>'
                      f'<td><span class="mono">{esc(repairs_view.compact_json(fr.HAVOC_AFTER))}</span></td>', card)
        self.assertNotIn("&quot;off_reason&quot;", card)  # the catalog's empty fields are left out
        self.assertIn('<span class="status-pill ok">ok</span> HTTP 200 · 7 items found · probed ', card)
        self.assertIn('href="https://www.havocai.com/news/rampage"', card)
        self.assertIn("HavocAI unveils the &lt;b&gt;Rampage&lt;/b&gt; autonomous boat", card)
        self.assertIn("HavocAI joins the Navy&#x27;s swarm trials", card)  # listed, but never as a javascript: link
        self.assertNotIn("javascript:", card)
        self.assertNotIn("A sixth item the hub never keeps", card)
        self.assertIn("Notes: preview", card)
        # turn_off: on against off, the off reason and the alternates by their catalog labels
        card = self.card(at, 20)
        self.assertIn('<span class="loop-kind loop-kind-turn_off">Turn it off</span>', card)
        self.assertIn('<span class="failing-name">Finnish defence ministry &lt;news&gt;</span>', card)
        self.assertIn('<td>On<br><span class="mono">https://www.defmin.fi/en/news</span></td>', card)
        self.assertIn("<td>Off: " + esc(fr.FI_OFF_REASON) + '<br>Alternates: NATO newsroom <span class="mono">'
                      'nato-news</span>, European Defence Agency news <span class="mono">eda-news</span></td>', card)
        self.assertIn('<span class="status-pill bad">blocked</span> HTTP 403 · no items found · probed ', card)
        self.assertIn("Notes: challenge page", card)
        # slow_down: the cadence now and after, in words; no probe
        card = self.card(at, 19)
        self.assertIn('<span class="loop-kind loop-kind-slow_down">Check it less often</span>', card)
        self.assertIn("<td>Checked every 2 h</td><td>Checked every 6 h</td>", card)
        self.assertIn("No probe evidence.", card)
        # add: the old source stays, the new one goes next to it
        card = self.card(at, 18)
        self.assertIn('<span class="loop-kind loop-kind-add">Add a source</span>', card)
        self.assertIn('<td>Stays as it is:<br><span class="mono">' + esc(repairs_view.compact_json(fr.ERCOT_BEFORE)),
                      card)
        self.assertIn('<td>Added next to it:<br><span class="mono">' + esc(repairs_view.compact_json(fr.ERCOT_AFTER)),
                      card)
        self.assertIn("HTTP 200 · 2 items found", card)
        # a note and Approve and Reject on each proposed repair only; Withdraw on the approved and the applied one
        self.assertEqual(self.repair_buttons(at), sorted(
            [f"cr_repair_{verb}_pilot_{rid}" for rid in (21, 20, 19, 18) for verb in ("approve", "reject")]
            + ["cr_repair_withdraw_pilot_17", "cr_repair_withdraw_pilot_16"]))
        self.assertEqual(at.text_input(key="cr_repair_note_pilot_21").value, "")
        self.assertFalse(at.button(key="cr_repair_approve_pilot_21").disabled)
        self.assert_no_secrets(at)

    def test_the_lists_below_the_cards(self):
        at = self.control()
        self.assert_clean(at)
        html = self.html(at)
        expanders = [e.label for e in at.expander]
        for label in ("pilot · repairs approved, waiting to be applied · 1",
                      "pilot · repairs applied, waiting for the source to report ok · 1",
                      "pilot · repairs recovered · 1", "pilot · repairs rejected or withdrawn · 2"):
            self.assertIn(label, expanders)
        blocks = [str(m.value) for m in at.markdown]

        def block(rid: int) -> str:
            return next(v for v in blocks if f"pilot #{rid} · " in v)

        # approved: the command that applies it, then the deploy
        self.assertIn(fr.APPLY, [c.value for c in at.code])
        self.assertIn('then deploy: <span class="mono">node deploy/workspace.mjs pilot</span>', html)
        self.assertIn(repairs_view.APPLY_HINT, self.texts(at, "caption"))
        self.assertIn('<span class="loop-kind loop-kind-replace">Replace the source</span><span class="status-pill ok">'
                      'approved</span>', block(17))
        self.assertIn('<span class="failing-name">Data Center Dynamics</span><span class="mono">dcd-news</span>',
                      block(17))
        self.assertIn("Note: Checked the new feed by hand.", block(17))
        # applied and recovered
        self.assertIn('<span class="status-pill ok">applied</span>', block(16))
        self.assertIn("; it counts as recovered once the source reports ok after that.", block(16))
        self.assertIn('<span class="status-pill ok">recovered</span>', block(15))
        self.assertIn(": the source reported ok after the fix.", block(15))
        # rejected and withdrawn in one list, most recent first
        closed = block(14)
        self.assertIn('<span class="status-pill bad">rejected</span>', closed)
        self.assertIn("Note: Loudoun is back; keep it on.", closed)
        self.assertIn('<span class="status-pill idle">withdrawn</span>', closed)
        self.assertLess(closed.index("pilot #14 · "), closed.index("pilot #13 · "))
        # the hub counts more than it lists: the label says so
        self.fresh()
        self.http.on("GET", REPAIRS, fr.repairs(self.rows, counts={"proposed": 4, "approved": 1, "applied": 1,
                                                                  "recovered": 140, "rejected": 30, "withdrawn": 2}))
        at = self.control()
        self.assertIn("pilot · repairs recovered · 1 of 140", [e.label for e in at.expander])
        self.assertIn("pilot · repairs rejected or withdrawn · 2 of 32", [e.label for e in at.expander])
        self.assertNotIn("proposed repairs are shown here", " ".join(self.texts(at, "caption")))
        # a proposed repair beyond the hub's newest 100 is never silently missing
        self.fresh()
        self.http.on("GET", REPAIRS, fr.repairs(self.rows, counts={"proposed": 6, "approved": 1, "applied": 1,
                                                                  "recovered": 1, "rejected": 1, "withdrawn": 1}))
        at = self.control()
        self.assertIn("4 of the 6 proposed repairs are shown here: the hub lists its newest 100 repairs.",
                      self.texts(at, "caption"))

    def test_nothing_yet_is_one_quiet_line(self):
        self.http.on("GET", REPAIRS, fx.repairs_v9())
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Pilot: no source repairs yet.", self.texts(at, "caption"))
        self.assertIn("<span>Source repairs to review</span>", self.html(at))
        self.assertEqual(self.repair_buttons(at), [])
        self.assertEqual([e.label for e in at.expander if " · repairs " in e.label], [])

    def test_only_decided_repairs_leave_no_card(self):
        self.http.on("GET", REPAIRS, fr.repairs([r for r in self.rows if r["status"] != "proposed"]))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Pilot: 0 to review · 1 approved, waiting to be applied · 1 applied, waiting for the source to "
                      "report ok · 1 recovered · 2 rejected or withdrawn", self.texts(at, "caption"))
        self.assertEqual(self.repair_buttons(at), ["cr_repair_withdraw_pilot_16", "cr_repair_withdraw_pilot_17"])


class DecisionTests(RepairsCase):
    def test_approve_with_a_note_then_the_list_is_read_again(self):
        def approve(call):
            self.http.on("GET", REPAIRS, fr.moved_on(self.rows, 21, "approved"))  # the hub now lists it approved
            return fr.answer(21, "approved", call.body.get("note"))

        self.http.on("POST", PILOT_HUB + "/repairs/21/approve", approve)
        at = self.control()
        at.text_input(key="cr_repair_note_pilot_21").set_value("  Use the newsroom;   Medium stays blocked ")
        at.button(key="cr_repair_approve_pilot_21").click().run()
        self.assert_clean(at)
        post = post_of(self.http, PILOT_HUB + "/repairs/21/approve")
        self.assertEqual((post.body, post.bearer), ({"note": "Use the newsroom; Medium stays blocked"}, OWNER))
        self.assertIn("Approved source repair #21 for Pilot. Apply it with the command under approved, then deploy.",
                      self.toasts(at))
        self.assertIsNone(undo_of(at))  # no route reverses an approval (Withdraw does, until it is applied)
        self.assertEqual(len(self.http.find("GET", REPAIRS)), 2)  # read again
        self.assertNotIn("cr_repair_approve_pilot_21", self.repair_buttons(at))
        self.assertIn("node tools/zenux.js repair apply pilot 21", [c.value for c in at.code])
        self.assertIn("pilot · repairs approved, waiting to be applied · 2", [e.label for e in at.expander])

    def test_approve_without_a_note_sends_an_empty_body(self):
        self.http.on("POST", PILOT_HUB + "/repairs/19/approve", fr.answer(19, "approved"))
        at = self.control()
        at.button(key="cr_repair_approve_pilot_19").click().run()
        self.assert_clean(at)
        self.assertEqual(post_of(self.http, PILOT_HUB + "/repairs/19/approve").body, {})

    def test_reject_asks_first_then_sends_the_note(self):
        self.http.on("POST", PILOT_HUB + "/repairs/20/reject", lambda call: fr.answer(20, "rejected", call.body["note"]))
        at = self.control()
        at.text_input(key="cr_repair_note_pilot_20").set_value("The ministry has an RSS feed after all")
        at.button(key="cr_repair_reject_pilot_20").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])  # a confirmation first
        text = self.visible_text(at)
        self.assertIn("Reject source repair #20?", text)
        self.assertIn(repairs_view.REJECT_TEXT, text)
        self.assertIn("Your note: The ministry has an RSS feed after all", self.texts(at, "caption"))
        at.button(key=CONFIRM).click().run()
        self.assert_clean(at)
        post = post_of(self.http, PILOT_HUB + "/repairs/20/reject")
        self.assertEqual((post.body, post.bearer), ({"note": "The ministry has an RSS feed after all"}, OWNER))
        self.assertIn("Rejected source repair #20 for Pilot.", self.toasts(at))
        self.assertIsNone(undo_of(at))
        self.assertNotIn("zx_dialog", at.session_state)

    def test_cancel_sends_nothing(self):
        at = self.control()
        at.button(key="cr_repair_reject_pilot_21").click().run()
        at.button(key="dlg_cancel").click().run()
        at.button(key="cr_repair_withdraw_pilot_17").click().run()
        at.button(key="dlg_cancel").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])

    def test_withdraw_an_approved_repair_asks_first(self):
        self.http.on("POST", PILOT_HUB + "/repairs/17/withdraw", fr.answer(17, "withdrawn"))
        at = self.control()
        at.button(key="cr_repair_withdraw_pilot_17").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertIn("Withdraw source repair #17?", self.visible_text(at))
        self.assertIn(repairs_view.WITHDRAW_TEXT, self.visible_text(at))
        self.assertIn(labels.NO_UNDO, self.texts(at, "caption"))
        at.button(key=CONFIRM).click().run()
        self.assert_clean(at)
        post = post_of(self.http, PILOT_HUB + "/repairs/17/withdraw")
        self.assertEqual((post.body, post.bearer), ({}, OWNER))
        self.assertIn("Withdrew source repair #17 for Pilot. It will not be applied.", self.toasts(at))
        self.assertIsNone(undo_of(at))

    def test_withdraw_an_applied_fix_that_did_not_work(self):
        self.http.on("POST", PILOT_HUB + "/repairs/16/withdraw", fr.answer(16, "withdrawn"))
        at = self.control()
        at.button(key="cr_repair_withdraw_pilot_16").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts(), [])
        self.assertIn("Withdraw source repair #16?", self.visible_text(at))
        self.assertIn(repairs_view.WITHDRAW_APPLIED_TEXT, self.visible_text(at))
        at.button(key=CONFIRM).click().run()
        self.assert_clean(at)
        post = post_of(self.http, PILOT_HUB + "/repairs/16/withdraw")
        self.assertEqual((post.body, post.bearer), ({}, OWNER))
        self.assertIn("Withdrew source repair #16 for Pilot. The change stays in the module; the Radar scout may "
                      "propose another fix.", self.toasts(at))
        self.assertIsNone(undo_of(at))

    def test_the_hubs_plain_refusal_is_said_in_place_and_the_list_read_again(self):
        self.http.on("POST", PILOT_HUB + "/repairs/21/approve", FakeResponse(409, {
            "error": "repair_closed", "message": "This repair was withdrawn meanwhile.", "status": "withdrawn"}))
        at = self.control()
        reads = len(self.http.find("GET", REPAIRS))
        at.button(key="cr_repair_approve_pilot_21").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. This repair was withdrawn meanwhile.", self.texts(at, "error"))
        self.assertEqual(self.toasts(at), [])
        at.run()
        self.assertGreater(len(self.http.find("GET", REPAIRS)), reads)  # the repair moved on: read again

    def test_a_refused_reject_keeps_the_confirmation_open(self):
        self.http.on("POST", PILOT_HUB + "/repairs/20/reject", FakeResponse(409, {
            "error": "repair_closed", "message": "This repair is already approved."}))
        at = self.control()
        at.button(key="cr_repair_reject_pilot_20").click().run()
        at.button(key=CONFIRM).click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. This repair is already approved.", self.texts(at, "error"))
        self.assertEqual(at.session_state["zx_dialog"]["name"], ui.CONFIRM)
        self.assertEqual(self.toasts(at), [])


class ReadFailureTests(RepairsCase):
    def test_a_failing_read_is_one_plain_line(self):
        self.http.on("GET", REPAIRS, FakeResponse(503, {"error": "unavailable", "message": "The database is busy."}))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Could not load source repairs from Pilot (HTTP 503: unavailable (The database is busy.)).",
                      self.texts(at, "caption"))
        self.assertEqual(self.repair_buttons(at), [])
        self.assertIn("<span>Coverage requests to review</span>", self.html(at))  # the rest of the room still works
        self.assertTrue(any(e.label.startswith("Configuration · ") for e in at.expander))

    def test_an_older_hub_and_an_unreachable_one(self):
        self.http.on("GET", REPAIRS, FakeResponse(404, {"error": "not_found", "message": "ZENUX has no such page."}))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Pilot: this hub does not list source repairs yet; deploy the hub (schema 9) to add them.",
                      self.texts(at, "caption"))
        self.fresh()
        self.http.routes.pop(("GET", REPAIRS))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Could not load source repairs from Pilot (unreachable (ConnectionError)).",
                      self.texts(at, "caption"))

    def test_malformed_bodies_never_crash(self):
        for body in ({"repairs": "x"}, {"repairs": [None, 7, {"id": "x"}]}, {"counts": "x"}):
            with self.subTest(body=body):
                self.fresh()
                self.http.on("GET", REPAIRS, body)
                at = self.control()
                self.assert_clean(at)
                self.assertIn("Pilot: no source repairs yet.", self.texts(at, "caption"))
        self.fresh()
        self.http.on("GET", REPAIRS, {"repairs": [{"id": 5, "status": "proposed", "action": "replace", "proposal": "x",
                                                   "evidence": "x", "alternates": "x", "diagnosis": None},
                                                  {"id": 6, "status": "approved"}], "counts": "x"})
        at = self.control()
        self.assert_clean(at)
        card = self.card(at, 5)
        for words in ("Not in the catalog.", "No source definition was sent.", "No probe evidence.",
                      "No diagnosis given."):
            self.assertIn(words, card)
        self.assertIn("node tools/zenux.js repair apply pilot 6", [c.value for c in at.code])
        self.fresh()
        self.http.on("GET", REPAIRS, FakeResponse(200, no_json=True))
        at = self.control()
        self.assert_clean(at)
        self.assertIn("Could not load source repairs from Pilot (HTTP 200: response is not JSON).",
                      self.texts(at, "caption"))


class AccessTests(RepairsCase):
    def test_hidden_without_the_builder(self):
        at = self.app(tab="control")  # open access is off in the tests, and no PIN was typed
        self.assert_clean(at)
        self.assertNotIn("Source repairs to review", self.html(at))
        self.assertEqual(self.http.find("GET", REPAIRS), [])

    def test_open_access_opens_the_review_and_writes_with_the_owner_token(self):
        secrets = one_workspace()
        secrets["open_access"] = True
        self.http.on("POST", PILOT_HUB + "/repairs/19/approve", fr.answer(19, "approved"))
        at = self.app(secrets, tab="control")
        self.assert_clean(at)
        self.assertFalse(at.button(key="cr_repair_approve_pilot_19").disabled)
        self.assertFalse(at.button(key="cr_repair_withdraw_pilot_17").disabled)
        at.button(key="cr_repair_approve_pilot_19").click().run()
        self.assert_clean(at)
        post = post_of(self.http, PILOT_HUB + "/repairs/19/approve")
        self.assertEqual((post.body, post.bearer), ({}, OWNER))
        self.assert_no_secrets(at)

    def test_a_workspace_without_an_owner_token_is_read_only(self):
        secrets = with_builder(one_workspace())
        secrets["workspaces"][0].pop("owner_token")
        at = self.control(secrets)
        self.assert_clean(at)
        self.assertIn("HavocAI blog (Medium)", self.html(at))  # the builder still reads it
        for key in ("cr_repair_approve_pilot_21", "cr_repair_reject_pilot_21", "cr_repair_withdraw_pilot_17",
                    "cr_repair_withdraw_pilot_16"):
            with self.subTest(key=key):
                self.assertTrue(at.button(key=key).disabled)
                self.assertEqual(at.button(key=key).proto.help, labels.LOCKED_HELP)
        self.assertEqual(self.http.posts(), [])

    def test_every_workspace_is_listed_and_written_with_its_own_token(self):
        beta = fr.repair(31, "proposed", "slow_down", module="coverage", source_key="trade-wire",
                         source_label="Trade wire", cls="quota",
                         diagnosis="The wire allows 50 calls a day; checking every 2 hours stays inside it.",
                         before=fr.current("trade-wire", "Trade wire", cadence_minutes=60), cadence_minutes=120)
        self.beta_routes([beta])
        self.http.on("POST", BETA_HUB + "/repairs/31/approve", {"repair": dict(beta, status="approved")})
        at = self.control(with_builder(two_workspaces()))
        self.assert_clean(at)
        self.assertEqual(self.http.find("GET", BETA_HUB + "/repairs")[0].bearer, BETA_READ)
        captions = self.texts(at, "caption")
        self.assertIn("Pilot: 4 to review · 1 approved, waiting to be applied · 1 applied, waiting for the source to "
                      "report ok · 1 recovered · 2 rejected or withdrawn", captions)
        self.assertIn("Beta analyst: 1 to review · 0 approved, waiting to be applied · 0 applied, waiting for the "
                      "source to report ok · 0 recovered · 0 rejected or withdrawn", captions)
        self.assertIn("<td>Checked every 1 h</td><td>Checked every 2 h</td>", self.card(at, 31, "beta"))
        at.button(key="cr_repair_approve_beta_31").click().run()
        self.assert_clean(at)
        post = post_of(self.http, BETA_HUB + "/repairs/31/approve")
        self.assertEqual((post.body, post.bearer), ({}, BETA_OWNER))
        self.assertIn("Approved source repair #31 for Beta analyst. Apply it with the command under approved, then "
                      "deploy.", self.toasts(at))
        self.assert_no_secrets(at)


class SourceHealthWindowTests(RepairsCase):
    def test_a_failing_source_with_a_proposed_fix(self):
        at = self.control()
        at.button(key=LIGHT_DEF).click().run()
        self.assert_clean(at)
        text = self.visible_text(at)
        self.assertIn("Source health · defense-unmanned", text)
        self.assertIn("Repair A fix is proposed (repair #19): review it under Source repairs to review.", text)

    def test_approved_and_applied_fixes_on_failing_and_retrying_sources(self):
        diag = fx.diagnostics()
        diag["retrying"] = [{"module_id": "defense-unmanned", "source_key": "havocai-medium", "health": "degraded",
                             "last_status": "blocked", "last_http_status": 403, "consecutive_failures": 1,
                             "last_ok_at": fx.iso(30)}]
        self.http.on("GET", PILOT_HUB + "/diagnostics", diag)
        rows = [dict(r, status={19: "approved", 21: "applied"}.get(r["id"], r["status"])) for r in self.rows]
        self.http.on("GET", REPAIRS, fr.repairs(rows))
        at = self.control()
        at.button(key=LIGHT_DEF).click().run()
        self.assert_clean(at)
        text = self.visible_text(at)
        self.assertIn("A fix is approved (repair #19); waiting for the builder to apply it.", text)  # failing sam-opps
        self.assertIn("A fix is applied (repair #21); waiting for the source to report ok.", text)  # retrying source

    def test_no_line_without_an_open_repair_or_when_repairs_cannot_be_read(self):
        rows = [dict(r, status="rejected") if r["id"] == 19 else r for r in self.rows]
        self.http.on("GET", REPAIRS, fr.repairs(rows))
        at = self.control()
        at.button(key=LIGHT_DEF).click().run()
        self.assert_clean(at)
        self.assertNotIn("A fix is", self.visible_text(at))
        self.fresh()
        self.http.on("GET", REPAIRS, FakeResponse(404, {"error": "not_found"}))
        at = self.control()
        at.button(key=LIGHT_DEF).click().run()
        self.assert_clean(at)
        text = self.visible_text(at)
        self.assertIn("The site asked ZENUX to slow down (HTTP 429, too many requests).", text)
        self.assertNotIn("A fix is", text)


class CoverageLineTests(RepairsCase):
    def test_coverage_says_how_many_sources_zenux_is_fixing(self):
        self.http.on("GET", PILOT_HUB + "/modules", fr.modules(ai_open=1, def_open=3))
        at = self.app(tab="coverage")
        self.assert_clean(at)
        line = next(str(m.value) for m in at.markdown if 'class="cov-health' in str(m.value))
        self.assertIn("ZENUX keeps trying; everything else is collected as usual. ZENUX is fixing 1 source. 2 sources "
                      "are turned off on purpose", line)
        self.assert_plain(at)
        self.assertEqual(self.http.find("GET", REPAIRS), [])  # the count comes with GET /modules
        at.segmented_control(key="cv_area").set_value("defense-unmanned").run()
        self.assert_clean(at)
        self.assertIn('class="cov-health ok">All 1 source on are working. ZENUX is fixing 3 sources.</div>',
                      self.html(at))
        self.assert_plain(at)

    def test_no_line_while_nothing_is_being_fixed_or_from_an_older_hub(self):
        for ai_open in (0, None):
            with self.subTest(ai_open=ai_open):
                self.fresh()
                self.http.on("GET", PILOT_HUB + "/modules", fr.modules(ai_open=ai_open, def_open=None))
                at = self.app(tab="coverage")
                self.assert_clean(at)
                self.assertNotIn("ZENUX is fixing", self.html(at))


if __name__ == "__main__":
    unittest.main()
