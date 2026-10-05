"""Open access (beta testing): with `open_access` on, no PIN is asked, every write uses the owner token and the
Control room is open; `open_access = false` brings the PIN gate back. The beta default (config.OPEN_ACCESS_DEFAULT)
is on; the test harness pins it off, so these tests turn it on through the secrets."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import fixtures_briefing as fb
from helpers import AppCase, FakeResponse, OWNER, PILOT_HUB, hub_defaults, one_workspace, pilot_secrets
from zenux_dashboard import config, labels, owner

FEEDBACK = PILOT_HUB + "/feedback"


def open_secrets(**extra) -> dict:
    secrets = one_workspace()
    secrets["open_access"] = True
    secrets.update(extra)
    return secrets


class ConfigTests(unittest.TestCase):
    def test_the_switch(self):
        ws = pilot_secrets()
        for raw, expected in ((True, True), (False, False), ("true", True), ("false", False), ("off", False),
                              ("yes", True), (1, True), (0, False)):
            with self.subTest(raw=raw):
                conf = config.parse_config({"open_access": raw, "workspaces": [copy.deepcopy(ws)]})
                self.assertIs(conf.open_access, expected)
                self.assertIs(conf.workspaces[0].open_access, expected)
        with patch.object(config, "OPEN_ACCESS_DEFAULT", True):  # the beta default, when the secrets say nothing
            self.assertTrue(config.parse_config({"workspaces": [copy.deepcopy(ws)]}).open_access)
            self.assertTrue(config.parse_config({"open_access": "maybe", "workspaces": [copy.deepcopy(ws)]}).open_access)
        with patch.object(config, "OPEN_ACCESS_DEFAULT", False):
            self.assertFalse(config.parse_config({"workspaces": [copy.deepcopy(ws)]}).open_access)

    def test_no_pin_needed_to_write(self):
        ws = pilot_secrets()
        ws.pop("owner_pin")
        conf = config.parse_config({"open_access": True, "workspaces": [ws]})
        self.assertTrue(conf.workspaces[0].can_write)
        self.assertEqual([p for p in conf.problems if "owner_pin" in p], [])  # nothing to complain about
        locked = config.parse_config({"open_access": False, "workspaces": [copy.deepcopy(ws)]})
        self.assertFalse(locked.workspaces[0].can_write)
        self.assertTrue(any("owner_pin missing" in p for p in locked.problems))

    def test_the_token_and_the_builder(self):
        conf = config.parse_config(open_secrets())
        ws = conf.workspaces[0]
        self.assertTrue(owner.is_open(ws))
        self.assertEqual(owner.token(ws), ws.owner_token)
        self.assertTrue(owner.is_builder(conf))
        closed = config.parse_config(one_workspace() | {"open_access": False})
        self.assertFalse(owner.is_open(closed.workspaces[0]))
        self.assertIsNone(owner.token(closed.workspaces[0]))
        self.assertFalse(owner.is_builder(closed))


class AppTests(AppCase):
    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        self.http.on("GET", PILOT_HUB + "/editions", fb.editions(1))

    def test_no_pin_anywhere_and_the_control_room_is_open(self):
        at = self.app(open_secrets())
        self.assert_clean(at)
        text = self.visible_text(at)
        self.assertIn("Open for testing", text)
        self.assertNotIn("Your PIN", text)
        self.assertNotIn(labels.LOCKED_HELP, text)
        self.assertIn("Control room", list(at.radio(key="zx_tab").options))
        self.assertFalse(at.button(key="act_more_i1201").disabled)
        self.assertFalse(at.button(key="act_rate_i1201").disabled)
        self.assert_no_secrets(at)

    def test_a_write_uses_the_owner_token(self):
        self.http.on("POST", FEEDBACK, FakeResponse(201, fb.feedback_stored()))
        at = self.app(open_secrets())
        at.button(key="act_rate_i1202").click().run()  # not rated yet: the star opens the rating dialog
        at.button(key="dlg_save").click().run()
        self.assert_clean(at)
        post = self.http.find("POST", FEEDBACK)[-1]
        self.assertEqual((post.bearer, post.body["verdict"]), (OWNER, "digest"))

    def test_open_access_false_brings_the_pin_back(self):
        at = self.app(open_secrets(open_access=False))
        self.assert_clean(at)
        self.assertIn("Your PIN", self.visible_text(at))
        self.assertTrue(at.button(key="act_more_i1201").disabled)
        self.assertNotIn("Control room", list(at.radio(key="zx_tab").options))


if __name__ == "__main__":
    unittest.main()
