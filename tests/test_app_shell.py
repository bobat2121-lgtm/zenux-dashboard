"""AppTest: the shell (docs/SPEC-PHASE03-UI.md section 4): tabs and who sees them, sign in to edit, builder access,
deep links, the page-level error box and the jargon guard on the shell itself. The views are stubbed (helpers.
stub_views), so these tests do not depend on them."""

from __future__ import annotations

import base64
import re
import tomllib
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import streamlit as st

from helpers import (AppCase, BETA_HUB, BETA_PIN, BETA_READ, BUILDER_PIN, DASHBOARD, PIN, SECRETS, beta_secrets,
                     hub_defaults, one_workspace, pilot_secrets, stub_views, two_workspaces)
from zenux_dashboard import labels, links, owner, ui

ANALYST = ["Briefing", "Filtered out", "My preferences", "Coverage"]
WITH_CONTROL = ANALYST + ["Control room"]


def write_probe(ws):
    """A stub Briefing with one write button, so a test can see whether this session may edit."""
    st.markdown("stub briefing")
    ui.write_button("Save it", ws=ws, key="probe_write")


def with_builder(secrets: dict, pin: str = BUILDER_PIN) -> dict:
    return {"builder_pin": pin, **secrets}


class ShellCase(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)

    def stub(self, **renders):
        renders.setdefault("briefing", write_probe)
        return stub_views(self, **renders)

    @staticmethod
    def tabs(at) -> list[str]:
        return list(at.radio(key=links.TAB_KEY).options)

    @staticmethod
    def popover_labels(at) -> list[str]:
        return [n.proto.popover.label for n in AppCase.walk(at._tree) if getattr(n, "type", "") == "popover"]

    @staticmethod
    def write_disabled(at) -> bool:
        return at.button(key="probe_write").disabled

    def unlock(self, at, pin: str = PIN):
        at.text_input(key=owner.ENTRY_KEY).set_value(pin)
        return at.button(key="zx_unlock").click().run()


class TabTests(ShellCase):
    def test_four_analyst_tabs_while_locked(self):
        self.stub()
        at = self.app()
        self.assert_clean(at)
        self.assertEqual(self.tabs(at), ANALYST)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "briefing")
        self.assertIn("stub briefing", self.html(at))
        self.assertIn("Sign in to edit", self.popover_labels(at))
        self.assertTrue(self.write_disabled(at))
        self.assertEqual(at.button(key="probe_write").help, labels.LOCKED_HELP)

    def test_each_tab_renders_its_view(self):
        self.stub()
        at = self.app()
        for slug in ("filtered", "preferences", "coverage"):
            at.radio(key=links.TAB_KEY).set_value(slug).run()
            self.assert_clean(at)
            self.assertIn(f"stub {slug}", self.html(at))
            self.assertEqual(at.query_params.get("tab"), slug)

    def test_builder_pin_opens_the_control_room(self):
        self.stub()
        at = self.app(with_builder(two_workspaces()))
        self.assertEqual(self.tabs(at), ANALYST)
        at.text_input(key=owner.BUILDER_ENTRY_KEY).set_value(BUILDER_PIN)
        at.button(key="zx_builder_unlock").click().run()
        self.assert_clean(at)
        self.assertEqual(self.tabs(at), WITH_CONTROL)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "control")  # the shell switches to it
        self.assertIn("stub control", self.html(at))
        self.assertNotIn(owner.BUILDER_ENTRY_KEY, [t.key for t in at.text_input])  # the field is gone
        self.assertIn("Control room open.", self.texts(at, "caption"))
        # a builder may write to every configured workspace
        at.radio(key=links.TAB_KEY).set_value("briefing").run()
        self.assertFalse(self.write_disabled(at))
        at.selectbox(key="workspace").set_value("beta").run()
        self.assertFalse(self.write_disabled(at))

    def test_single_workspace_falls_back_to_the_owner_pin(self):
        self.stub()
        at = self.app()  # one workspace, no builder_pin: the pilot owner is the builder
        self.assertEqual(self.tabs(at), ANALYST)
        at = self.unlock(at)
        self.assert_clean(at)
        self.assertEqual(self.tabs(at), WITH_CONTROL)  # one PIN for both
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "briefing")

    def test_two_workspaces_without_a_builder_pin_never_show_the_control_room(self):
        self.stub()
        at = self.app(two_workspaces())
        self.assertNotIn("Builder PIN", [t.label for t in at.text_input])
        at = self.unlock(at)
        self.assertEqual(self.tabs(at), ANALYST)
        at.selectbox(key="workspace").set_value("beta").run()
        at = self.unlock(at, BETA_PIN)
        self.assertEqual(self.tabs(at), ANALYST)
        at = self.app(two_workspaces(), query={"tab": "control"}, builder_pin=PIN)
        self.assertEqual(self.tabs(at), ANALYST)

    def test_a_shared_default_pin_never_opens_the_control_room_with_two_workspaces(self):
        # WF3 review CR-1: the pilot analyst's PIN is the firm-wide default; beta has its own PIN
        self.stub()
        pilot = pilot_secrets()
        del pilot["owner_pin"]
        at = self.app({"owner_pin": "firm-default-pin", "workspaces": [pilot, beta_secrets()]})
        self.assertNotIn("Builder PIN", [t.label for t in at.text_input])
        at = self.unlock(at, "firm-default-pin")
        self.assert_clean(at)
        self.assertFalse(self.write_disabled(at))  # the pilot is unlocked
        self.assertEqual(self.tabs(at), ANALYST)  # but no Control room
        at.selectbox(key="workspace").set_value("beta").run()
        self.assertTrue(self.write_disabled(at))  # and beta stays locked
        self.assertIn("Sign in to edit", self.popover_labels(at))

    def test_owner_unlock_opens_the_builder_only_when_the_pins_are_equal(self):
        self.stub()
        at = self.unlock(self.app(with_builder(one_workspace())))
        self.assertFalse(self.write_disabled(at))
        self.assertEqual(self.tabs(at), ANALYST)  # a different builder PIN still has to be typed
        at = self.unlock(self.app(with_builder(one_workspace(), PIN)))
        self.assertEqual(self.tabs(at), WITH_CONTROL)

    def test_a_locked_builder_never_keeps_the_control_room(self):
        self.stub()
        at = self.app(tab="control")
        self.assert_clean(at)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "briefing")
        self.assertIn("stub briefing", self.html(at))


class SignInTests(ShellCase):
    def test_unlock_lock_and_the_cleared_field(self):
        self.stub()
        at = self.app()
        self.assertIn("Unlocks editing in this browser tab until you reload or close it.", self.texts(at, "caption"))
        self.assertEqual(at.text_input(key=owner.ENTRY_KEY).placeholder, "Your PIN")
        at = self.unlock(at)
        self.assert_clean(at)
        self.assertIn("Signed in", self.popover_labels(at))
        self.assertIn("You can edit Pilot in this browser tab until you lock it, reload the page or close the tab.",
                      self.html(at))
        self.assertNotIn(PIN, str(at.session_state.to_dict()))  # the PIN is never kept
        self.assertFalse(self.write_disabled(at))
        at.run()  # stays unlocked for the session
        self.assertFalse(self.write_disabled(at))
        at.button(key="zx_lock").click().run()
        self.assert_clean(at)
        self.assertIn("Sign in to edit", self.popover_labels(at))
        self.assertTrue(self.write_disabled(at))
        self.assertIn("Locked. Editing is off until you unlock again.", self.toasts(at))

    def test_enter_in_the_pin_field_unlocks(self):
        # WF3 review CR-2: typing the PIN and pressing Enter is the normal action
        self.stub()
        at = self.app(state={"zx_signin": True})
        at.text_input(key=owner.ENTRY_KEY).input(PIN).run()  # Enter, no click
        self.assert_clean(at)
        self.assertFalse(self.write_disabled(at))
        self.assertIn("Signed in", self.popover_labels(at))
        self.assertIs(at.session_state["zx_signin"], False)
        self.assertNotIn(PIN, str(at.session_state.to_dict()))  # the field was cleared at once

    def test_enter_with_a_wrong_pin_says_why_and_a_click_on_the_empty_field_keeps_it(self):
        self.stub()
        pause = MagicMock()
        with patch.object(owner, "_pause", pause):
            at = self.app()
            at.text_input(key=owner.ENTRY_KEY).input("not-the-pin").run()
            self.assertIn(owner.lock_message(None, owner.WRONG_PIN), self.texts(at, "error"))
            self.assertEqual(at.text_input(key=owner.ENTRY_KEY).value, "")
            at.button(key="zx_unlock").click().run()  # the field is empty now: nothing is checked again
            self.assertIn(owner.lock_message(None, owner.WRONG_PIN), self.texts(at, "error"))
            self.assertEqual(pause.call_count, 1)
            self.assertTrue(self.write_disabled(at))
            # typing and clicking Unlock (both callbacks fire in one run) checks the PIN once
            at.text_input(key=owner.ENTRY_KEY).set_value(PIN)
            at.button(key="zx_unlock").click().run()
        self.assertFalse(self.write_disabled(at))
        self.assertEqual(self.texts(at, "error"), [])

    def test_enter_in_the_builder_pin_field_opens_the_control_room(self):
        self.stub()
        at = self.app(with_builder(two_workspaces()))
        at.text_input(key=owner.BUILDER_ENTRY_KEY).input(BUILDER_PIN).run()
        self.assert_clean(at)
        self.assertEqual(self.tabs(at), WITH_CONTROL)
        self.assertNotIn(BUILDER_PIN, str(at.session_state.to_dict()))  # the field was cleared at once

    def test_lock_disables_a_pending_undo(self):
        # WF3 review CR-3: a write control is drawn locked, never refused after the click
        def probe(ws):
            write_probe(ws)
            if st.button("make undo", key="probe_undo"):
                ui.offer_undo(ws, "Muted X.", lambda token: {"ok": True})
                st.rerun()

        self.stub(briefing=probe)
        at = self.app(pin=PIN)
        at.button(key="probe_undo").click().run()
        self.assertFalse(at.button(key="zx_undo_run").disabled)
        at.button(key="zx_lock").click().run()
        self.assert_clean(at)
        self.assertTrue(at.button(key="zx_undo_run").disabled)
        self.assertEqual(at.button(key="zx_undo_run").help, labels.LOCKED_HELP)
        at = self.unlock(at)
        self.assertFalse(at.button(key="zx_undo_run").disabled)  # still there after unlocking again

    def test_the_popover_closes_after_unlock_and_lock_but_not_after_a_wrong_pin(self):
        self.stub()
        at = self.app(state={"zx_signin": True})
        at = self.unlock(at, "not-the-pin")
        self.assertIs(at.session_state["zx_signin"], True)  # stays open to show why
        at = self.unlock(at)
        self.assertIs(at.session_state["zx_signin"], False)  # the page under it is in view again
        at.session_state["zx_signin"] = True
        at.button(key="zx_lock").click().run()
        self.assertIs(at.session_state["zx_signin"], False)

    def test_the_entry_field_is_cleared_after_unlock(self):
        self.stub()
        at = self.app()
        at.text_input(key=owner.ENTRY_KEY).set_value("not-the-pin")
        at.button(key="zx_unlock").click().run()
        self.assertEqual(at.text_input(key=owner.ENTRY_KEY).value, "")
        self.assertIn(owner.lock_message(None, owner.WRONG_PIN), self.texts(at, "error"))
        self.assertTrue(self.write_disabled(at))

    def test_a_wrong_pin_counts_once_per_entry(self):
        self.stub()
        pause = MagicMock()
        with patch.object(owner, "_pause", pause):
            at = self.app()
            for _ in range(4):
                at.text_input(key=owner.ENTRY_KEY).set_value("not-the-pin")
                at.button(key="zx_unlock").click().run()
                at.run()
            self.assertEqual(pause.call_count, 1)  # one entry, one check, one wait
            at = self.unlock(at)
        self.assertFalse(self.write_disabled(at))
        self.assertEqual(self.texts(at, "error"), [])

    def test_lockout_refuses_the_right_pin_with_the_same_message(self):
        self.stub()
        for i in range(owner.MAX_FAILURES):
            at = self.app()  # a fresh session per guess
            at = self.unlock(at, f"guess-{i:04d}")
        at = self.unlock(self.app())
        self.assertTrue(self.write_disabled(at))
        self.assertIn(owner.lock_message(None, owner.WRONG_PIN), self.texts(at, "error"))

    def test_a_pilot_pin_does_not_unlock_beta(self):
        self.stub()
        at = self.unlock(self.app(two_workspaces()))
        self.assertFalse(self.write_disabled(at))
        at.selectbox(key="workspace").set_value("beta").run()
        self.assert_clean(at)
        self.assertTrue(self.write_disabled(at))
        self.assertIn("Sign in to edit", self.popover_labels(at))
        at = self.unlock(at, PIN)  # the pilot PIN typed for beta
        self.assertTrue(self.write_disabled(at))
        at = self.unlock(at, BETA_PIN)
        self.assertFalse(self.write_disabled(at))

    def test_a_changed_pin_in_the_secrets_locks_the_session(self):
        self.stub()
        at = self.unlock(self.app())
        self.assertFalse(self.write_disabled(at))
        at.secrets["workspaces"][0]["owner_pin"] = "a-brand-new-pin-1"
        at.run()
        self.assert_clean(at)
        self.assertTrue(self.write_disabled(at))
        self.assertIn("Sign in to edit", self.popover_labels(at))

    def test_a_preset_pin_is_adopted_once(self):
        self.stub()
        at = self.app(pin=PIN)
        self.assertFalse(self.write_disabled(at))
        self.assertNotIn(owner.PIN_KEY, at.session_state)

    def test_not_configured_shows_no_field(self):
        self.stub()
        secrets = one_workspace()
        del secrets["workspaces"][0]["owner_pin"]
        at = self.app(secrets)
        self.assert_clean(at)
        self.assertNotIn(owner.ENTRY_KEY, [t.key for t in at.text_input])
        self.assertIn(owner.lock_message(None, owner.NOT_CONFIGURED), self.texts(at, "caption"))
        self.assertTrue(self.write_disabled(at))

    def test_builder_wrong_pin(self):
        self.stub()
        at = self.app(with_builder(two_workspaces()))
        at.text_input(key=owner.BUILDER_ENTRY_KEY).set_value("not-the-builder")
        at.button(key="zx_builder_unlock").click().run()
        self.assertEqual(self.tabs(at), ANALYST)
        self.assertIn(owner.lock_message(None, owner.WRONG_PIN), self.texts(at, "error"))
        self.assertEqual(at.text_input(key=owner.BUILDER_ENTRY_KEY).value, "")

    def test_lock_leaves_the_control_room(self):
        self.stub()
        at = self.app(builder_pin=PIN, tab="control")
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "control")
        at.button(key="zx_lock").click().run()
        self.assert_clean(at)
        self.assertEqual(self.tabs(at), ANALYST)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "briefing")


class DeepLinkTests(ShellCase):
    def test_tab_and_workspace_from_the_query(self):
        self.stub()
        at = self.app(query={"tab": "filtered"})
        self.assert_clean(at)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "filtered")
        self.assertIn("stub filtered", self.html(at))
        at = self.app(two_workspaces(), query={"ws": "beta", "tab": "coverage"})
        self.assertEqual(at.selectbox(key="workspace").value, "beta")
        self.assertEqual(at.query_params, {"tab": "coverage", "ws": "beta"})

    def test_focus_values_reach_the_views_and_are_mirrored(self):
        seen = {}

        def briefing(ws):
            seen.update(edition=links.focus("edition"), item=links.focus("item"))
            st.markdown("stub briefing")

        self.stub(briefing=briefing)
        at = self.app(query={"tab": "briefing", "edition": "12", "item": "1201", "view": "muted"})
        self.assertEqual(seen, {"edition": 12, "item": 1201})
        self.assertEqual(at.query_params, {"tab": "briefing", "edition": "12", "item": "1201"})
        at.radio(key=links.TAB_KEY).set_value("filtered").run()
        self.assertEqual(at.query_params, {"tab": "filtered", "view": "muted"})  # each tab mirrors its own

    def test_invalid_values_are_ignored(self):
        seen = {}

        def briefing(ws):
            seen.update({name: links.focus(name) for name in links.FOCUS_PARAMS})
            st.markdown("stub briefing")

        self.stub(briefing=briefing)
        at = self.app(two_workspaces(), query={
            "tab": "nope", "ws": "zzz", "edition": "abc", "item": "-1", "view": "bad", "section": "x",
            "pref": "X-1", "module": "Bad Id", "request": "0"})
        self.assert_clean(at)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "briefing")
        self.assertEqual(at.selectbox(key="workspace").value, "pilot")
        self.assertEqual(set(seen.values()), {None})
        self.assertEqual(at.query_params, {"tab": "briefing", "ws": "pilot"})

    def test_a_control_room_link_while_locked_opens_briefing_with_a_toast(self):
        self.stub()
        at = self.app(with_builder(two_workspaces()), query={"tab": "control"})
        self.assert_clean(at)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "briefing")
        self.assertIn(links.CONTROL_LOCKED, self.toasts(at))
        at = self.app(with_builder(two_workspaces()), query={"tab": "control"}, builder_pin=BUILDER_PIN)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "control")
        self.assertIn("stub control", self.html(at))

    def test_go_switches_tab_and_focus(self):
        def briefing(ws):
            if st.button("Open the sign-off", key="probe_go"):
                links.go("preferences", section="looks_for")

        self.stub(briefing=briefing,
                  preferences=lambda ws: st.markdown(f"stub preferences {links.focus('section')}"))
        at = self.app()
        at.button(key="probe_go").click().run()
        self.assert_clean(at)
        self.assertEqual(at.radio(key=links.TAB_KEY).value, "preferences")
        self.assertIn("stub preferences looks_for", self.html(at))
        self.assertEqual(at.query_params, {"tab": "preferences", "section": "looks_for"})

    def test_the_query_never_holds_a_secret(self):
        self.stub()
        at = self.app(two_workspaces(), pin=PIN, query={"tab": "coverage", "ws": "pilot", "module": "ai-infra"})
        for slug in ("briefing", "filtered", "preferences", "coverage"):
            at.radio(key=links.TAB_KEY).set_value(slug).run()
            for secret in SECRETS:
                self.assertNotIn(secret, str(at.query_params))
        self.assert_no_secrets(at)


class PageErrorTests(ShellCase):
    def test_a_crashing_tab_shows_a_plain_error_box(self):
        def broken(ws):
            raise RuntimeError("boom in the view")

        self.stub(briefing=broken)
        at = self.app()
        self.assertEqual([e.value for e in at.exception], [])  # no traceback on the page
        text = self.visible_text(at)
        self.assertIn("Couldn't load this page.", text)
        self.assertIn("Something went wrong on this page.", text)
        self.assertNotIn("boom", text)  # builder details only for the builder
        self.assertIsNotNone(at.button(key="zx_retry_page"))
        self.assertIn("RuntimeError", at.session_state.get("zx_page_crash"))  # assert_clean catches it
        with self.assertRaises(AssertionError):
            self.assert_clean(at)
        at = self.app(builder_pin=PIN)
        self.assertIn("RuntimeError: boom in the view", [c.value for c in at.code])

    def test_a_missing_view_module_spoils_only_its_tab(self):
        import sys

        self.stub()
        previous = sys.modules.get("zenux_dashboard.filtered_view")
        sys.modules["zenux_dashboard.filtered_view"] = None  # importing it raises ImportError
        self.addCleanup(lambda: sys.modules.__setitem__("zenux_dashboard.filtered_view", previous))
        at = self.app(tab="filtered")
        self.assertEqual([e.value for e in at.exception], [])
        self.assertIn("Couldn't load this page.", self.visible_text(at))
        at.radio(key=links.TAB_KEY).set_value("briefing").run()
        self.assert_clean(at)
        self.assertIn("stub briefing", self.html(at))

    def test_no_workspace_configured(self):
        self.stub()
        at = self.app({})
        self.assert_clean(at)
        self.assertIn("No Zenux workspace is configured.", self.html(at))
        self.assertEqual(self.http.calls, [])


class PlainShellTests(ShellCase):
    def test_the_shell_speaks_plainly_and_leaks_nothing(self):
        from zenux_dashboard import status

        def briefing(ws):
            status.status_line(ws)
            write_probe(ws)

        self.stub(briefing=briefing)
        at = self.app(with_builder(two_workspaces()))
        self.assert_clean(at)
        self.assert_plain(at)
        self.assert_no_secrets(at)
        at = self.unlock(at)
        self.assert_plain(at)
        self.assert_no_secrets(at)

    def test_the_masthead_is_unchanged(self):
        self.stub()
        at = self.app()
        html = self.html(at)
        self.assertIn('<header class="zx-masthead"><div class="brand" role="heading" aria-level="1" '
                      'aria-label="ZENUX"><span class="brand-lockup"><img class="brand-mark" '
                      'src="data:image/png;base64,..." alt="ZENUX" width="42" height="42"><span class="brand-core">'
                      'ZENUX</span></span><span class="brand-sub">NEWS INTELLIGENCE</span>'
                      '<span class="brand-workspace">PILOT</span></div></header>', html)
        self.assertIn('<footer class="zx-footer">ZENUX · internal research tool · data from public sources</footer>',
                      html)

    def test_there_is_no_page_wide_timer(self):
        from helpers import APP_PATH

        source = APP_PATH.read_text(encoding="utf-8")
        self.assertNotIn("run_every", source)
        self.stub()
        self.assertEqual(self.popover_labels(self.app()), ["Sign in to edit"])  # no Search popover in the bar


FOOTER = '<footer class="zx-footer">ZENUX · internal research tool · data from public sources</footer>'


class BrandAndConfigTests(ShellCase):
    """Carried over from the old Feed tests: the logo, page icon, theme, footer and configuration states."""

    def test_masthead_shows_the_logo_mark_inline(self):
        self.stub()
        at = self.app()
        self.assert_clean(at)
        masthead = next(str(m.value) for m in at.markdown if str(m.value).startswith('<header class="zx-masthead">'))
        match = re.search(r'<span class="brand-lockup"><img class="brand-mark" src="data:image/png;base64,'
                          r'([A-Za-z0-9+/=]+)" alt="ZENUX" width="42" height="42"><span class="brand-core">ZENUX'
                          r'</span></span>', masthead)
        self.assertIsNotNone(match, "the mark sits immediately left of the wordmark")
        self.assertEqual(base64.b64decode(match.group(1)), (DASHBOARD / "assets" / "zenux-favicon.png").read_bytes())
        self.assertNotIn("brand-accent", masthead)

    def test_page_icon_is_the_favicon_file(self):
        self.stub()
        with patch("streamlit.set_page_config", wraps=st.set_page_config) as spy:
            at = self.app()
        self.assert_clean(at)
        icon = Path(spy.call_args.kwargs["page_icon"])
        self.assertEqual(icon.resolve(), (DASHBOARD / "assets" / "zenux-favicon.png").resolve())
        self.assertTrue(icon.is_file())
        self.assertEqual(spy.call_args.kwargs["page_title"], "ZENUX")

    def test_theme_is_black_with_the_brand_green(self):
        with open(DASHBOARD / ".streamlit" / "config.toml", "rb") as handle:
            theme = tomllib.load(handle)["theme"]
        self.assertEqual(
            {k: theme[k] for k in ("base", "primaryColor", "backgroundColor", "secondaryBackgroundColor", "textColor",
                                   "font")},
            {"base": "dark", "primaryColor": "#006341", "backgroundColor": "#0A0A0A",
             "secondaryBackgroundColor": "#141414", "textColor": "#EDEDED", "font": "sans serif"})
        css = (DASHBOARD / "feed.css").read_text(encoding="utf-8")
        tokens = dict(re.findall(r"(--zx-[a-z-]+):\s*(#[0-9a-f]{6})", css))
        self.assertEqual(tokens["--zx-bg"], theme["backgroundColor"].lower())
        self.assertEqual(tokens["--zx-card"], theme["secondaryBackgroundColor"].lower())
        self.assertEqual(tokens["--zx-text"], theme["textColor"].lower())
        self.assertEqual(tokens["--zx-green"], "#006341")

    def test_footer_on_every_tab(self):
        self.stub()
        for tab in ("briefing", "filtered", "preferences", "coverage"):
            with self.subTest(tab=tab):
                at = self.app(tab=tab)
                self.assert_clean(at)
                self.assertTrue(self.html(at).endswith(FOOTER))
        at = self.app({"zenux": {"note": "no workspaces here"}})
        self.assertIn(FOOTER, self.html(at))
        self.assertIn("No Zenux workspace is configured", self.html(at))

    def test_invalid_configuration_lists_problems_without_values(self):
        self.stub()
        at = self.app({"workspaces": [{"id": "Bad Id", "read_token": "not-shown-value"}]})
        self.assert_clean(at)
        captions = "\n".join(self.texts(at, "caption"))
        self.assertIn("workspace #1: id is missing or invalid", captions)
        self.assertNotIn("not-shown-value", captions + self.html(at))

    def test_workspace_switcher_moves_the_page_to_the_other_workspace(self):
        seen = []

        def briefing(ws):
            seen.append(ws.id)
            st.markdown(f"stub briefing for {ws.label}")

        hub_defaults(self.http, BETA_HUB)
        self.stub(briefing=briefing)
        at = self.app(two_workspaces())
        self.assert_clean(at)
        switcher = at.selectbox(key="workspace")
        self.assertEqual(list(switcher.options), ["Pilot", "Beta analyst"])
        switcher.set_value("beta").run()
        self.assert_clean(at)
        html = self.html(at)
        self.assertIn("stub briefing for Beta analyst", html)
        self.assertIn('<span class="brand-workspace">BETA ANALYST</span>', html)
        self.assertEqual(seen[-1], "beta")


if __name__ == "__main__":
    unittest.main()
