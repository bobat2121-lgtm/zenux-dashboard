"""ui.py (docs/SPEC-PHASE03-UI.md 1.3 and 3.6): queued toasts, the undo bar, dialogs through the shell, confirmations,
locked write buttons, ui.write and its plain errors, error boxes, and effective_text. Views are stubbed."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import requests
import streamlit as st

import fixtures as fx
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, PIN, hub_defaults, stub_views
from zenux_dashboard import api, fmt, labels, ui
from zenux_dashboard.api import ApiError

MUTES = PILOT_HUB + "/mutes"
TZ = "America/New_York"


def _edit_body(name: str = "") -> None:
    st.markdown(f"Editing {name}")
    st.text_input("Note", key="dlg_text")
    if st.button("Save", key="dlg_save", type="primary"):
        ws = st.session_state["probe_ws"]
        result = ui.write(ws, lambda tok: api.add_mute(ws, tok, kind="source", module="ai-infra", ref="dcd-news",
                                                         note=st.session_state.get("dlg_text")),
                          toast="Saved the note.")
        if result is not None:
            ui.close_dialog()
            st.rerun()
    if st.button("Cancel", key="dlg_cancel"):
        ui.close_dialog()
        st.rerun()


ui.register_dialog("probe_edit", "Edit {name}", _edit_body)


def mute_with_undo(ws) -> None:
    """A stub Briefing: Mute (a write with undo), a plain notify, a dialog and a confirmation."""
    st.session_state["probe_ws"] = ws
    st.markdown("stub briefing")
    if ui.write_button("Mute it", ws=ws, key="probe_mute"):
        result = ui.write(
            ws, lambda tok: api.add_mute(ws, tok, kind="source", module="ai-infra", ref="dcd-news"),
            toast=lambda r: f"Muted {r['mute']['label']}. {labels.STILL_COLLECTED}",
            undo=lambda r: (f"Muted {r['mute']['label']}.",
                            lambda tok: api.remove_mute(ws, tok, r["mute"]["id"], bring_back_days=7),
                            "Unmuted. The stories it hid this week come back."))
        if result is not None:
            st.rerun()
    if ui.write_button("Unstar", ws=ws, key="probe_unstar"):
        if ui.write(ws, lambda tok: api.remove_star(ws, tok, "coreweave"), toast="CoreWeave removed from your watchlist.",
                    undo=lambda r: ("Removed CoreWeave.", lambda tok: api.add_star(ws, tok, "coreweave"))):
            st.rerun()
    if st.button("Say hello", key="probe_notify"):
        ui.notify("Hello there.")
        st.rerun()
    if st.button("Edit", key="probe_open"):
        ui.open_dialog("probe_edit", name="the note")
    if st.button("Remove", key="probe_confirm"):
        ui.ask_confirm("Remove this?", "It goes away.", "Remove it",
                       lambda: ui.write(ws, lambda tok: api.remove_mute(ws, tok, 4), toast="Removed."),
                       detail="You can bring it back later.")
    ui.locked_hint(ws)


class UiCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        self.http.on("POST", MUTES, lambda call: fx.mute_added() if call.body.get("action") == "add"
                     else fx.mute_removed())
        stub_views(self, briefing=mute_with_undo)

    @staticmethod
    def dialog_titles(at) -> list[str]:
        return [n.proto.dialog.title for n in AppCase.walk(at._tree) if getattr(n, "type", "") == "dialog"]


class ToastAndUndoTests(UiCase):
    def test_a_queued_toast_shows_on_the_next_run_only(self):
        at = self.app()
        at.button(key="probe_notify").click().run()
        self.assertEqual(self.toasts(at), ["Hello there."])
        at.run()
        self.assertEqual(self.toasts(at), [])

    def test_a_toast_right_after_another_takes_the_next_place(self):
        # Streamlit draws every toast in its event area and skips one drawn at the place of a toast still showing (a
        # run's first toast always takes the first place there); empty style blocks, which take no room, move each
        # batch on, so a story icon clicked twice says both
        def spacers(at) -> int:
            return sum(1 for el in at.get("html") if str(el.value) == ui.TOAST_SPACER)

        at = self.app()
        at.button(key="probe_notify").click().run()
        self.assertEqual((self.toasts(at), spacers(at), at.session_state[ui.TOAST_SLOT_KEY]), (["Hello there."], 0, 1))
        at.button(key="probe_notify").click().run()
        self.assertEqual((self.toasts(at), spacers(at), at.session_state[ui.TOAST_SLOT_KEY]), (["Hello there."], 1, 2))
        at.run()  # no toast: nothing is drawn and the next place is kept
        self.assertEqual((self.toasts(at), spacers(at), at.session_state[ui.TOAST_SLOT_KEY]), ([], 0, 2))
        self.assertEqual([ui.as_slot(v) for v in (0, 5, ui.TOAST_SLOTS + 1, -1, True, "3", None)],
                         [0, 5, 1, 0, 0, 0, 0])

    def test_write_toasts_and_offers_undo(self):
        at = self.app(pin=PIN)
        at.button(key="probe_mute").click().run()
        self.assert_clean(at)
        post = self.http.posts()[0]
        self.assertEqual((post.url, post.bearer, post.body),
                         (MUTES, OWNER, {"action": "add", "kind": "source", "module": "ai-infra", "ref": "dcd-news"}))
        self.assertEqual(self.toasts(at), [f"Muted Data Center Dynamics. {labels.STILL_COLLECTED}"])
        self.assertIn('<div class="zx-undo">Muted Data Center Dynamics.</div>', self.html(at))
        at.button(key="zx_undo_run").click().run()
        self.assert_clean(at)
        undo = self.http.posts()[1]
        self.assertEqual((undo.bearer, undo.body), (OWNER, {"action": "remove", "mute_id": 9, "bring_back_days": 7}))
        self.assertEqual(self.toasts(at), ["Unmuted. The stories it hid this week come back."])
        self.assertNotIn("zx-undo", self.html(at))

    def test_undo_says_undone_by_default_and_a_new_write_replaces_it(self):
        self.http.on("POST", PILOT_HUB + "/stars", lambda call: fx.star_removed() if call.body["action"] == "remove"
                     else fx.star_added("coreweave", "CoreWeave"))
        at = self.app(pin=PIN)
        at.button(key="probe_mute").click().run()
        at.button(key="probe_unstar").click().run()
        self.assertIn('<div class="zx-undo">Removed CoreWeave.</div>', self.html(at))  # the newest change only
        self.assertNotIn("Muted Data Center Dynamics.</div>", self.html(at))
        # WF5 AW-5: replacing a live Undo is said, with where the earlier change can be reversed
        self.assertIn(ui.REPLACED_UNDO.format(earlier="Muted Data Center Dynamics"), self.toasts(at))
        at.button(key="zx_undo_run").click().run()
        undo = self.http.posts()[-1]
        self.assertEqual((undo.url, undo.bearer, undo.body),
                         (PILOT_HUB + "/stars", OWNER, {"action": "add", "entity_id": "coreweave"}))
        self.assertEqual(self.toasts(at), ["Undone."])

    def test_dismiss_and_expiry(self):
        at = self.app(pin=PIN)
        at.button(key="probe_mute").click().run()
        at.button(key="zx_undo_dismiss").click().run()
        self.assertNotIn("zx-undo", self.html(at))
        at.button(key="probe_mute").click().run()
        self.assertIn("zx-undo", self.html(at))
        with patch.object(ui, "_now", return_value=10 ** 9):
            at.run()
        self.assertNotIn("zx-undo", self.html(at))
        self.assertEqual(len(self.http.posts()), 2)  # nothing undone

    def test_the_undo_bar_belongs_to_one_workspace(self):
        from helpers import BETA_HUB, two_workspaces

        hub_defaults(self.http, BETA_HUB)
        at = self.app(two_workspaces(), pin=PIN)
        at.button(key="probe_mute").click().run()
        self.assertIn("zx-undo", self.html(at))
        at.selectbox(key="workspace").set_value("beta").run()
        self.assertNotIn("zx-undo", self.html(at))
        at.selectbox(key="workspace").set_value("pilot").run()
        self.assertIn("zx-undo", self.html(at))

    def test_warnings_become_more_toasts(self):
        answer = fx.mute_added()
        answer["warnings"] = ["You have 41 active preferences."]
        self.http.on("POST", MUTES, answer)
        at = self.app(pin=PIN)
        at.button(key="probe_mute").click().run()
        self.assertEqual(self.toasts(at)[1:], ["You have 41 active preferences."])

    def test_locked_buttons_are_disabled_and_send_nothing(self):
        at = self.app()
        button = at.button(key="probe_mute")
        self.assertTrue(button.disabled)
        self.assertEqual(button.help, labels.LOCKED_HELP)
        self.assertIn(":material/lock: " + labels.LOCKED_HELP, self.texts(at, "caption"))
        with self.assertRaises(Exception):  # a browser cannot press it, and neither can AppTest
            button.click()
        self.assertEqual(self.http.posts(), [])
        at = self.app(pin=PIN)
        self.assertFalse(at.button(key="probe_mute").disabled)
        self.assertNotIn(":material/lock: " + labels.LOCKED_HELP, self.texts(at, "caption"))

    def test_undo_failure_shows_a_plain_error(self):
        at = self.app(pin=PIN)
        at.button(key="probe_mute").click().run()
        self.http.on("POST", MUTES, FakeResponse(404, {"error": "unknown_mute", "message": "That mute is gone."}))
        at.button(key="zx_undo_run").click().run()
        self.assert_clean(at)
        self.assertIn("Not saved. That mute is gone.", self.texts(at, "error"))


class DialogTests(UiCase):
    def test_a_dialog_opens_keeps_its_widgets_and_closes_on_save(self):
        at = self.app(pin=PIN)
        at.button(key="probe_open").click().run()
        self.assertEqual(self.dialog_titles(at), ["Edit the note"])
        at.text_input(key="dlg_text").set_value("too noisy").run()
        self.assertEqual(at.text_input(key="dlg_text").value, "too noisy")  # still there on the next run
        self.assertEqual(self.dialog_titles(at), ["Edit the note"])
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.dialog_titles(at), [])
        self.assertEqual(self.http.posts()[0].body["note"], "too noisy")
        self.assertEqual(self.toasts(at), ["Saved the note."])
        at.button(key="probe_open").click().run()  # a fresh dialog starts empty
        self.assertEqual(at.text_input(key="dlg_text").value, "")

    def test_cancel_closes_without_sending(self):
        at = self.app(pin=PIN)
        at.button(key="probe_open").click().run()
        at.text_input(key="dlg_text").set_value("draft")
        at.button(key="dlg_cancel").click().run()
        self.assertEqual(self.dialog_titles(at), [])
        self.assertEqual(self.http.posts(), [])
        self.assertNotIn("dlg_text", at.session_state)

    def test_a_refusal_keeps_the_dialog_open_with_a_plain_error(self):
        self.http.on("POST", MUTES, FakeResponse(409, {
            "error": "company_starred", "message": "CoreWeave is on your watchlist. Remove the star first."}))
        at = self.app(pin=PIN)
        at.button(key="probe_open").click().run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.dialog_titles(at), ["Edit the note"])
        self.assertIn("Not saved. CoreWeave is on your watchlist. Remove the star first.", self.texts(at, "error"))

    def test_a_locked_save_is_refused_in_the_dialog(self):
        at = self.app()
        at.button(key="probe_open").click().run()
        at.button(key="dlg_save").click().run()
        self.assertEqual(self.http.posts(), [])
        self.assertIn(labels.LOCKED_HELP, self.texts(at, "warning"))
        self.assertEqual(self.dialog_titles(at), ["Edit the note"])

    def test_confirm_runs_its_action_only_on_confirm(self):
        at = self.app(pin=PIN)
        at.button(key="probe_confirm").click().run()
        self.assertEqual(self.dialog_titles(at), ["Remove this?"])
        self.assertIn("It goes away.", self.visible_text(at))
        self.assertIn("You can bring it back later.", self.texts(at, "caption"))
        at.button(key="dlg_cancel").click().run()
        self.assertEqual(self.http.posts(), [])
        self.assertEqual(self.dialog_titles(at), [])
        at.button(key="probe_confirm").click().run()
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts()[0].body, {"action": "remove", "mute_id": 4, "bring_back_days": 0})
        self.assertEqual(self.dialog_titles(at), [])
        self.assertEqual(self.toasts(at), ["Removed."])

    def test_a_failed_confirmation_stays_open(self):
        self.http.on("POST", MUTES, FakeResponse(500, {"error": "internal_error"}))
        at = self.app(pin=PIN)
        at.button(key="probe_confirm").click().run()
        at.button(key="dlg_save").click().run()
        self.assertEqual(self.dialog_titles(at), ["Remove this?"])
        self.assertIn("Not saved. Something went wrong on the server. Try again in a minute.", self.texts(at, "error"))

    def test_an_unknown_dialog_is_dropped(self):
        at = self.app(state={ui.DIALOG_KEY: {"name": "nope", "args": {}}})
        self.assert_clean(at)
        self.assertEqual(self.dialog_titles(at), [])
        self.assertIsNone(at.session_state.get(ui.DIALOG_KEY))


class ErrorBoxTests(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)

        def briefing(ws):
            from zenux_dashboard import data
            try:
                data.editions(ws.id)
            except ApiError as exc:
                ui.error_box("your briefings", exc, key="briefing")

        stub_views(self, briefing=briefing)

    def box(self, response, *, builder: bool = False):
        self.fresh()
        self.http.on("GET", PILOT_HUB + "/editions", response)
        at = self.app(builder_pin=PIN if builder else None)
        self.assert_clean(at)
        return at

    def test_plain_headlines(self):
        cases = [
            (requests.ConnectionError("down"), "ZENUX can't be reached right now. This is usually brief. Try again in "
                                               "a minute."),
            (requests.Timeout("slow"), "ZENUX took too long to answer. This is usually brief. Try again in a minute."),
            (FakeResponse(401, {"error": "unauthorized"}),
             "The dashboard's access was refused. Tell the builder: the workspace's keys may have changed."),
            # an older hub's technical sentence: the dashboard's words for the code
            (FakeResponse(404, {"error": "unknown_edition", "message": "unknown edition 12"}),
             "That briefing is no longer available. Refresh and try again."),
            (FakeResponse(404, {"error": "unknown_item", "message": "unknown edition item 1201"}),
             "That story is no longer available. Refresh and try again."),
            # the hub's plain sentence (docs/SPEC-PHASE05.md 1.2) as written
            (FakeResponse(404, {"error": "unknown_item", "message": "That story is no longer in that briefing.",
                                "edition_id": 12, "item_rank": 3}),
             "That story is no longer in that briefing. Refresh and try again."),
            (FakeResponse(404, {"error": "not_found"}), "ZENUX couldn't find that. It may have changed meanwhile. "
                                                        "Refresh and try again."),
            (FakeResponse(500, {"error": "internal_error"}), "Something went wrong on the server. Try again in a "
                                                              "minute."),
            (FakeResponse(200, no_json=True), "ZENUX sent an answer the dashboard couldn't read. Tell the builder."),
        ]
        for response, text in cases:
            with self.subTest(text=text):
                at = self.box(response)
                visible = self.visible_text(at)
                self.assertIn("Couldn't load your briefings.", visible)
                self.assertIn(text, visible)
                self.assertNotIn("HTTP", visible)
                self.assertEqual([c.value for c in at.code], [])  # no builder details for the analyst

    def test_builder_details_and_try_again(self):
        at = self.box(FakeResponse(500, {"error": "internal_error", "message": "boom"}), builder=True)
        self.assertIn("HTTP 500: internal_error (boom)", [c.value for c in at.code])
        self.assertIn("Details for the builder", [e.label for e in at.expander])
        calls = len(self.http.find("GET", PILOT_HUB + "/editions"))
        self.http.on("GET", PILOT_HUB + "/editions", fx.editions_v8())
        at.button(key="zx_retry_briefing").click().run()
        self.assert_clean(at)
        self.assertGreater(len(self.http.find("GET", PILOT_HUB + "/editions")), calls)  # the cache was cleared
        self.assertNotIn("Couldn't load your briefings.", self.visible_text(at))


class PureTests(unittest.TestCase):
    def test_effective_text(self):
        now = datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)  # 10:00 AM EDT
        eff = lambda at: {"applies_from": "next_briefing", "next_briefing_at": at, "timezone": TZ}  # noqa: E731
        self.assertEqual(ui.effective_text(eff("2026-10-04T16:30:00.000Z"), TZ, now=now),
                         "Applies from the 12:30 PM briefing.")
        self.assertEqual(ui.effective_text(eff("2026-10-05T11:30:00.000Z"), TZ, now=now),
                         "Applies from tomorrow's 7:30 AM briefing.")
        self.assertEqual(ui.effective_text(eff("2026-10-06T11:30:00.000Z"), TZ, now=now),
                         "Applies from the Tue Oct 6 7:30 AM briefing.")
        self.assertEqual(ui.effective_text(eff(None), TZ, now=now), "Applies from the next briefing.")
        self.assertEqual(ui.effective_text(None, TZ, now=now), "Applies from the next briefing.")
        self.assertEqual(ui.effective_text(eff("2026-10-04T10:00:00.000Z"), TZ, now=now),
                         "Applies from the next briefing.")  # a time already past
        self.assertEqual(ui.effective_text({"applies_from": "after_approval", "next_briefing_at": None}, TZ, now=now),
                         "Takes effect once you approve the wording in My preferences.")

    def test_effective_text_across_the_dst_change(self):
        # 2026-11-01: clocks go back at 2 AM. The evening before (EDT) the next slot is tomorrow 7:30 AM EST.
        before = datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)  # 7:00 PM EDT
        eff = {"applies_from": "next_briefing", "next_briefing_at": "2026-11-01T12:30:00.000Z"}  # 7:30 AM EST
        self.assertEqual(ui.effective_text(eff, TZ, now=before), "Applies from tomorrow's 7:30 AM briefing.")
        after = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)  # 8:00 AM EST
        eff = {"applies_from": "next_briefing", "next_briefing_at": "2026-11-01T17:30:00.000Z"}  # 12:30 PM EST
        self.assertEqual(ui.effective_text(eff, TZ, now=after), "Applies from the 12:30 PM briefing.")

    def test_plain_error_mapping(self):
        self.assertEqual(ui.plain_error(ApiError("unreachable", "timed out"))[0], "ZENUX took too long to answer.")
        self.assertEqual(ui.plain_error(ApiError("not_configured", "x"))[0], "This workspace isn't fully set up yet.")
        self.assertEqual(ui.plain_error(ApiError("invalid", "Write a sentence."))[0], "Write a sentence.")
        # any code: the hub's plain sentence is shown as written (every refusal is one plain sentence since WF5)
        self.assertEqual(ui.plain_error(ApiError("http", "HTTP 409: x", 409, "x", detail="That can't change now.")),
                         ("That can't change now.", None))
        # an unknown code whose sentence fails the guard: the plain default by kind
        self.assertEqual(ui.plain_error(ApiError("http", "HTTP 409: x", 409, "x", detail="lease 7 held by rv-1")),
                         ("ZENUX refused that request.", "Tell the builder if it keeps happening."))
        self.assertEqual(ui.plain_error(ApiError("not_found", "HTTP 404", 404))[0],
                         "ZENUX couldn't find that. It may have changed meanwhile.")
        self.assertEqual(ui.plain_error(ValueError("x"))[0], "Something went wrong on this page.")

    def test_hub_refusals_in_plain_words(self):
        # WF5 (docs/SPEC-PHASE05.md 1): the hub's sentence as written when the guard passes it; an older hub's
        # engine text never shows: the dashboard's words for the code stand in
        def said(code, message, status=409, kind="http", **data):
            exc = ApiError(kind, f"HTTP {status}: {code}", status, code, detail=message, data=data)
            return ui.plain_error(exc)[0]

        cases = {
            ("draft_closed", "rule draft 43 is approved"):
                "This suggestion was already handled meanwhile. Refresh to see where it stands.",
            ("draft_closed", "This suggestion was already approved."): "This suggestion was already approved.",
            ("radar_closed", "radar request 46 is approved"):
                "This request has moved on meanwhile (the builder may have approved it). Refresh to see where it "
                "stands.",
            ("radar_closed", "This request is already approved, waiting for setup."):
                "This request is already approved, waiting for setup.",
            ("superseded", "A newer version, R-0019, replaced this preference. Change that one instead."):
                "A newer wording replaced this preference. Change that one instead.",
            ("unknown_source", "No source dcd-news in ai-infra."): "That source is no longer in your coverage.",
            ("unknown_source", "That source is not in your coverage."): "That source is not in your coverage.",
            ("unknown_event", "No story with id 7101."): "That story is no longer available.",
            ("unknown_item", "unknown edition item 1201"): "That story is no longer available.",
            ("merge_outdated", "A preference this merge replaces has changed since it was proposed. Turn this merge "
                               "down; next month's check suggests a new one."):
                "A preference this merge replaces has changed since it was proposed. Turn this merge down; next "
                "month's check suggests a new one.",
            ("invalid_mute", "This mute is not complete. The coverage area is missing."):
                "This mute is not complete. The coverage area is missing.",
            ("company_starred", "CoreWeave is on your watchlist. Remove the star first."):
                "CoreWeave is on your watchlist. Remove the star first.",
            ("mute_active", "Anduril is muted again. Unmute it first; you can bring its stories back then."):
                "Anduril is muted again. Unmute it first; you can bring its stories back then.",
            ("invalid_preference", "Say what you want more or less of."): "Say what you want more or less of.",
            # engine text inside and no words of the dashboard's for the code: the plain default instead
            ("company_starred", "ent-coreweave-1 is on your watchlist. Remove the star first."):
                "ZENUX refused that request.",
            ("invalid_mute", "Say what to mute: { action, kind, module, ref }."): "ZENUX refused that request.",
            ("invalid_feedback", "rule draft 3 cannot be graded"): "ZENUX refused that request.",
        }
        for (code, message), plain in cases.items():
            with self.subTest(code=code, message=message):
                status = 404 if code.startswith("unknown") else 409
                text = said(code, message, status, "not_found" if status == 404 else "http")
                self.assertEqual(text, plain)
                self.assertEqual(labels.find_jargon(text), [])
        self.assertEqual(said("expired", "This preference ended on 2026-10-01. Reactivate it with a new end date, "
                                         "or none.", expires_at="2026-10-01T04:00:00.000Z"),
                         "This preference already ended on Oct 1, 2026. Bring it back with a new end date, or none.")
        self.assertEqual(said("expired", "This preference ended on Oct 1, 2026. Bring it back with a new end date, or "
                                         "none.", expires_at="2026-10-01T04:00:00.000Z"),
                         "This preference ended on Oct 1, 2026. Bring it back with a new end date, or none.")
        # a gone record keeps the next step; a refusal that is not about a gone record does not
        gone = ApiError("not_found", "HTTP 404: unknown_draft", 404, "unknown_draft",
                        detail="That suggestion is no longer available.", data={"draft_id": 43})
        self.assertEqual(ui.write_error_text(gone),
                         "Not saved. That suggestion is no longer available. Refresh and try again.")
        mute = ApiError("not_found", "HTTP 404: unknown_mute", 404, "unknown_mute", detail="That mute is gone.")
        self.assertEqual(ui.write_error_text(mute), "Not saved. That mute is gone.")
        for message in ("No source dcd-news in ai-infra.", "Not saved: rule draft 43 is approved",
                        "Not saved: radar request 46 is approved", "Coverage details for ai-infra appear after the "
                        "next deploy.", "No story with id 7101.", "unknown edition item 1201"):
            with self.subTest(message=message):
                self.assertNotEqual(labels.find_jargon(message), [])  # CV2: the guard now sees these

    def test_write_errors_keep_the_next_step(self):
        # WF3 review CV10: "Not saved. <headline> <explanation>"
        self.assertEqual(ui.write_error_text(ApiError("unreachable", "unreachable (ConnectionError)")),
                         "Not saved. ZENUX can't be reached right now. This is usually brief. Try again in a minute.")
        self.assertEqual(ui.write_error_text(ApiError("unauthorized", "HTTP 401: token refused", 401)),
                         "Not saved. The dashboard's access was refused. Tell the builder: the workspace's keys may "
                         "have changed.")
        self.assertEqual(ui.write_error_text(ApiError("invalid", "Write a sentence.")), "Not saved. Write a sentence.")

    def test_md_label_escapes_markdown(self):
        # WF3 review CR-4: hub text in a Markdown label is never typeset
        self.assertEqual(fmt.md_label("Neocloud wins $11.9B deal; shares jump $5"),
                         "Neocloud wins \\$11.9B deal; shares jump \\$5")
        self.assertEqual(fmt.md_label("*a* _b_ [c](d) `e` ~f~ <g> |h| \\"),
                         "\\*a\\* \\_b\\_ \\[c\\](d) \\`e\\` \\~f\\~ \\<g\\> \\|h\\| \\\\")
        self.assertEqual(fmt.md_label("Data Center Dynamics (DCD). #1 drone-maker"),
                         "Data Center Dynamics (DCD). #1 drone-maker")
        self.assertEqual(fmt.md_label(None), "")

    def test_dialog_titles(self):
        self.assertEqual(ui._title("Mute {label}?", {"label": "CoreWeave"}), "Mute CoreWeave?")
        self.assertEqual(ui._title("Mute {label}?", {}), "Mute ?")
        self.assertEqual(ui._title(lambda **a: f"Hi {a['x']}", {"x": 1}), "Hi 1")
        self.assertEqual(ui._title("Plain {", {}), "Plain {")

    def test_local_midnight_iso(self):
        from datetime import date

        self.assertEqual(ui.local_midnight_iso(date(2026, 11, 3), TZ), "2026-11-03T05:00:00.000Z")
        self.assertEqual(ui.local_midnight_iso(date(2026, 10, 3), TZ), "2026-10-03T04:00:00.000Z")


if __name__ == "__main__":
    unittest.main()
