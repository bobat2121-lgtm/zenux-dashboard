"""The PIN gate: server-wide guessing limits, the wrong-PIN wait, the session memo, and PINs that must never unlock
anything (placeholders from the committed example and docs, and short PINs). The sign-in popover's own flow is in
test_app_shell."""

from __future__ import annotations

import hashlib
import tomllib
import unittest
from unittest.mock import MagicMock, patch

import helpers  # noqa: F401  (puts dashboard/ on sys.path)
import streamlit as st

from helpers import (BUILDER_PIN, DASHBOARD, OWNER, PIN, AppCase, hub_defaults, reset_pin_guard, stub_views,
                     two_workspaces)
from zenux_dashboard import api, owner, ui
from zenux_dashboard.config import MIN_PIN_LENGTH, parse_config


class Clock:
    def __init__(self, start: float = 10_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = owner.PinGuard()
        self.slot = self.guard.fingerprint("slot", PIN)

    def fail(self, times: int, now: float) -> list[float]:
        return [self.guard.begin(self.slot, now) for _ in range(times)]

    def test_locks_after_max_failures_with_a_doubling_backoff(self):
        t = 1000.0
        self.assertEqual(self.fail(owner.MAX_FAILURES, t), [0.0] * owner.MAX_FAILURES)  # the 5th is still checked
        self.assertEqual(self.guard.begin(self.slot, t + 1), t + 1 + owner.LOCK_BASE)  # then every check is refused
        self.assertEqual(self.guard.begin(self.slot, t + owner.LOCK_BASE), t + 1 + owner.LOCK_BASE)
        t2 = t + 1 + owner.LOCK_BASE
        self.assertEqual(self.fail(owner.MAX_FAILURES, t2), [0.0] * owner.MAX_FAILURES)
        self.assertEqual(self.guard.begin(self.slot, t2), t2 + 2 * owner.LOCK_BASE)  # doubled
        t = t2 + 2 * owner.LOCK_BASE
        for _ in range(12):  # the backoff stops growing at LOCK_MAX
            self.fail(owner.MAX_FAILURES, t)
            until = self.guard.begin(self.slot, t)
            self.assertLessEqual(until - t, owner.LOCK_MAX)
            t = until
        self.fail(owner.MAX_FAILURES, t)
        self.assertEqual(self.guard.begin(self.slot, t), t + owner.LOCK_MAX)

    def test_slow_guessing_still_locks(self):
        t = 1000.0
        for _ in range(owner.MAX_FAILURES):  # one guess every 3 hours: still within the window
            self.assertEqual(self.guard.begin(self.slot, t), 0.0)
            t += 3 * 60 * 60
        self.assertEqual(self.guard.begin(self.slot, t), t + owner.LOCK_BASE)

    def test_old_misses_and_old_lockouts_are_forgotten(self):
        t = 1000.0
        self.fail(owner.MAX_FAILURES - 1, t)
        t += owner.FAILURE_WINDOW + 1  # a quiet window: the count starts again
        self.assertEqual(self.fail(owner.MAX_FAILURES, t), [0.0] * owner.MAX_FAILURES)
        self.assertEqual(self.guard.begin(self.slot, t), t + owner.LOCK_BASE)
        self.fail(owner.MAX_FAILURES, t + owner.LOCK_BASE)
        t += owner.LOCK_BASE + owner.LOCK_MEMORY + 1  # a quiet day after the lockout: the escalation starts again
        self.fail(owner.MAX_FAILURES, t)
        self.assertEqual(self.guard.begin(self.slot, t), t + owner.LOCK_BASE)

    def test_the_right_pin_clears_the_count(self):
        self.fail(owner.MAX_FAILURES - 1, 1000.0)
        self.assertEqual(self.guard.begin(self.slot, 1000.0), 0.0)  # the 5th attempt is the right PIN
        self.guard.succeeded(self.slot)
        self.assertEqual(self.fail(owner.MAX_FAILURES, 1001.0), [0.0] * owner.MAX_FAILURES)  # no lockout pending
        self.assertEqual(self.guard.begin(self.slot, 1001.0), 1001.0 + owner.LOCK_BASE)

    def test_slots_are_keyed_fingerprints(self):
        other = owner.PinGuard()
        self.assertNotEqual(self.slot, other.fingerprint("slot", PIN))  # a random key per guard (per process)
        self.assertEqual(len(self.slot), 32)
        self.assertNotEqual(self.slot, hashlib.sha256(PIN.encode()).digest())


class CheckPinTests(unittest.TestCase):
    """check_pin and unlock in bare mode: st.session_state stands in for one browser session (load_config is patched,
    so no secrets file is ever read)."""

    def setUp(self):
        reset_pin_guard()
        self.addCleanup(reset_pin_guard)
        self.clock = Clock()
        self.pause = MagicMock()
        self.secrets = {"workspaces": [helpers.pilot_secrets(), {**helpers.beta_secrets(), "owner_pin": PIN}]}
        for patcher in (patch.object(owner, "_now", self.clock), patch.object(owner, "_pause", self.pause),
                        patch.object(owner, "load_config", side_effect=lambda: parse_config(self.secrets))):
            patcher.start()
            self.addCleanup(patcher.stop)
        conf = parse_config(self.secrets)
        self.ws, self.beta = conf.workspace("pilot"), conf.workspace("beta")

    @staticmethod
    def new_session() -> None:
        for key in (owner.MEMO_KEY, owner.UNLOCK_KEY, owner.BUILDER_KEY, owner.RESULT_KEY):
            st.session_state.pop(key, None)

    def lock_out(self) -> None:
        for i in range(owner.MAX_FAILURES):
            self.new_session()
            self.assertEqual(owner.unlock(self.ws, f"wrong-pin-{i}"), owner.WRONG_PIN)
        self.new_session()

    def test_a_wrong_pin_waits_once_and_counts_once(self):
        for _ in range(20):  # the same entry pressed again and again
            self.assertEqual(owner.unlock(self.ws, "wrong-pin-0"), owner.WRONG_PIN)
        self.assertEqual(self.pause.call_count, 1)
        for i in range(1, owner.MAX_FAILURES - 1):
            owner.unlock(self.ws, f"wrong-pin-{i}")
        self.assertEqual(owner.unlock(self.ws, PIN), owner.UNLOCKED)  # the 5th attempt, and the right one
        self.assertEqual(self.pause.call_count, owner.MAX_FAILURES - 1)  # the right PIN does not wait
        self.new_session()
        self.assertEqual(owner.unlock(self.beta, "wrong-pin-9"), owner.WRONG_PIN)  # the count was cleared

    def test_after_max_failures_even_the_right_pin_is_refused_with_the_same_message(self):
        self.lock_out()
        self.pause.reset_mock()
        self.assertEqual(owner.unlock(self.ws, PIN), owner.WRONG_PIN)
        self.assertIsNone(owner.token(self.ws))
        self.assertEqual(self.pause.call_count, 1)  # the same wait as a wrong PIN
        self.new_session()
        self.assertEqual(owner.unlock(self.beta, PIN), owner.WRONG_PIN)  # the same PIN elsewhere: same guard
        self.clock.now += owner.LOCK_BASE + 1
        self.assertEqual(owner.unlock(self.ws, PIN), owner.UNLOCKED)  # the lockout is over
        self.assertEqual(owner.token(self.ws), OWNER)

    def test_a_session_that_unlocked_stays_unlocked_during_a_lockout(self):
        self.assertEqual(owner.unlock(self.ws, PIN), owner.UNLOCKED)
        kept = {k: st.session_state[k] for k in (owner.MEMO_KEY, owner.UNLOCK_KEY)}
        self.lock_out()  # other sessions guess meanwhile
        for key, value in kept.items():
            st.session_state[key] = value
        self.assertTrue(owner.is_unlocked(self.ws))
        self.assertEqual(owner.unlock(self.ws, "another-guess"), owner.WRONG_PIN)  # a new entry is refused

    def test_the_builder_pin_shares_the_guard_of_the_same_pin(self):
        self.secrets = {"builder_pin": BUILDER_PIN, **two_workspaces()}
        conf = parse_config(self.secrets)
        for i in range(owner.MAX_FAILURES):
            self.new_session()
            self.assertEqual(owner.builder_unlock(conf, f"wrong-{i}"), owner.WRONG_PIN)
        self.new_session()
        self.assertEqual(owner.builder_unlock(conf, BUILDER_PIN), owner.WRONG_PIN)  # locked out too
        self.clock.now += owner.LOCK_BASE + 1
        self.assertEqual(owner.builder_unlock(conf, BUILDER_PIN), owner.UNLOCKED)

    def test_the_session_never_holds_the_pin(self):
        owner.unlock(self.ws, PIN)
        owner.unlock(self.beta, "wrong-pin-0")
        stored = repr({k: st.session_state.get(k) for k in (owner.MEMO_KEY, owner.UNLOCK_KEY, owner.RESULT_KEY)})
        for value in (PIN, "wrong-pin-0", hashlib.sha256(PIN.encode()).hexdigest(),
                      repr(hashlib.sha256(PIN.encode()).digest())):
            self.assertNotIn(value, stored)


class PauseTests(unittest.TestCase):
    def test_a_failed_check_really_waits(self):
        self.assertGreaterEqual(owner.FAIL_DELAY, 0.5)
        with patch("zenux_dashboard.owner.time.sleep") as sleep:
            owner._pause()
        sleep.assert_called_once_with(owner.FAIL_DELAY)


class PinGuardAppTests(AppCase):
    """Through the page: every session of the app shares the guard, and nothing is sent while locked."""

    def setUp(self):
        super().setUp()
        hub_defaults(self.http)
        self.http.on("POST", helpers.PILOT_HUB + "/stars", {"star": {}, "removed": True})
        self.clock = Clock()
        clock = patch.object(owner, "_now", self.clock)
        clock.start()
        self.addCleanup(clock.stop)

        def briefing(ws):
            if ui.write_button("Remove CoreWeave", ws=ws, key="probe_write"):
                if ui.write(ws, lambda tok: api.remove_star(ws, tok, "coreweave"),
                            toast="Removed."):
                    st.rerun()

        stub_views(self, briefing=briefing)

    def guess(self, at, pin: str):
        at.text_input(key=owner.ENTRY_KEY).set_value(pin)
        return at.button(key="zx_unlock").click().run()

    def test_guessing_from_many_sessions_locks_every_session(self):
        for i in range(owner.MAX_FAILURES):  # a script opening a fresh session per guess
            self.guess(self.app(), f"guess-{i:04d}")
        at = self.guess(self.app(), PIN)  # the right PIN, typed during the lockout
        self.assert_clean(at)
        self.assertIn(helpers.wrong_pin("pilot"), self.texts(at, "error"))  # same message as a wrong PIN
        self.assertTrue(at.button(key="probe_write").disabled)
        self.assertEqual(self.http.posts(), [])
        self.clock.now += owner.LOCK_BASE + 1
        at = self.guess(at, PIN)
        self.assertFalse(at.button(key="probe_write").disabled)
        at.button(key="probe_write").click().run()
        self.assert_clean(at)
        self.assertEqual(self.http.posts()[0].bearer, OWNER)


class PinConfigTests(unittest.TestCase):
    def setUp(self):
        reset_pin_guard()
        self.addCleanup(reset_pin_guard)

    def test_the_committed_example_never_unlocks_anything(self):
        with open(DASHBOARD / ".streamlit" / "secrets.example.toml", "rb") as handle:
            conf = parse_config(tomllib.load(handle))
        ws = conf.workspace("pilot")
        self.assertEqual(ws.owner_pin, "")
        self.assertFalse(ws.can_write)
        self.assertFalse(conf.has_builder)
        self.assertIn("workspace 'pilot': owner_pin is the example placeholder, which anyone can read "
                      "(owner writes disabled)", conf.problems)
        with patch.object(owner, "load_config", return_value=conf):
            self.assertEqual(owner.unlock(ws, "REPLACE_WITH_THE_PIN_YOU_TYPE"), owner.NOT_CONFIGURED)
            self.assertEqual(owner.builder_unlock(conf, "REPLACE_WITH_THE_PIN_YOU_TYPE"), owner.NOT_CONFIGURED)
            self.assertIsNone(owner.token(ws))

    def test_placeholders_from_the_docs_count_as_unset(self):
        base = {"id": "pilot", "hub_url": "https://h.example", "read_token": "r", "owner_token": "o"}
        for placeholder in ("...", "<your PIN>", "choose-a-pin", "replace_with_your_pin", " REPLACE_WITH_X "):
            conf = parse_config({"workspaces": [{**base, "owner_pin": placeholder}]})
            self.assertFalse(conf.workspace("pilot").can_write, placeholder)
            self.assertTrue(any("example placeholder" in p for p in conf.problems), placeholder)
            conf = parse_config({"owner_pin": placeholder, "workspaces": [base]})
            self.assertFalse(conf.workspace("pilot").can_write, placeholder)
            # A placeholder left in a workspace block gives way to a real default PIN (as the deploy tool reads it).
            conf = parse_config({"owner_pin": "a-real-default-pin", "workspaces": [{**base, "owner_pin": placeholder}]})
            self.assertEqual(conf.workspace("pilot").owner_pin, "a-real-default-pin")
            self.assertEqual(conf.problems, ())

    def test_short_pins_turn_owner_writes_off(self):
        base = {"id": "pilot", "hub_url": "https://h.example", "read_token": "r", "owner_token": "o"}
        short = "7" * (MIN_PIN_LENGTH - 1)
        for secrets in ({"workspaces": [{**base, "owner_pin": short}]}, {"owner_pin": "1234", "workspaces": [base]}):
            conf = parse_config(secrets)
            self.assertFalse(conf.workspace("pilot").can_write)
            self.assertFalse(conf.has_builder)  # a short PIN is no builder fallback either
            self.assertIn(f"workspace 'pilot': owner_pin is shorter than {MIN_PIN_LENGTH} characters "
                          "(owner writes disabled)", conf.problems)
            self.assertFalse(any("1234" in p or short in p for p in conf.problems))
        conf = parse_config({"workspaces": [{**base, "owner_pin": "8" * MIN_PIN_LENGTH}]})
        self.assertTrue(conf.workspace("pilot").can_write)
        self.assertEqual(conf.problems, ())


if __name__ == "__main__":
    unittest.main()
