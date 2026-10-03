"""Owner PIN gate.

The owner types a PIN in the Owner popover. It never leaves this server: it is compared, in constant time, with
the workspace's `owner_pin` from st.secrets, and a match unlocks that workspace's `owner_token`, which is the
bearer for hub writes. Module backfills (bearer `run_token`) sit behind the same gate. The PIN is kept only in
this browser session's widget state and is never logged, cached or sent anywhere.

Guessing is throttled for the whole server, not per session (a script can open as many sessions as it likes):

- Every new PIN tried against an owner_pin counts as an attempt in a server-wide guard (st.cache_resource), shared
  by every workspace configured with that same PIN. The attempt is counted before the compare, so parallel guesses
  cannot overshoot the limit; the right PIN clears the count.
- After MAX_FAILURES wrong PINs (misses are forgotten after FAILURE_WINDOW seconds without one), every check of that
  PIN is refused, right or wrong, for a lockout that doubles each time (LOCK_BASE up to LOCK_MAX seconds); the
  escalation is forgotten LOCK_MEMORY seconds after the last lockout ends. A patient guesser gets about
  MAX_FAILURES guesses per LOCK_MAX.
- A wrong or refused PIN waits FAIL_DELAY seconds, and both show the same message, so a page never tells whether a
  PIN typed during a lockout was right.
- Each session remembers the verdict for what it has already checked (a keyed HMAC of workspace, configured PIN and
  typed PIN, never the PIN itself), so the many reruns of one entry count, and wait, once. A session that already
  proved the PIN stays unlocked during a lockout; a changed PIN in st.secrets needs a new check.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import time

import streamlit as st

from .config import MIN_PIN_LENGTH, Workspace

PIN_KEY = "owner_pin"
MEMO_KEY = "zx_owner_checks"

UNLOCKED = "unlocked"
NO_PIN = "no_pin"
WRONG_PIN = "wrong_pin"  # also a PIN refused during a lockout: the two look the same on the page
NOT_CONFIGURED = "not_configured"

MAX_FAILURES = 5
FAILURE_WINDOW = 24 * 60 * 60
LOCK_BASE = 60
LOCK_MAX = 60 * 60
LOCK_MEMORY = 24 * 60 * 60
FAIL_DELAY = 1.0


def pin_matches(entered: str | None, expected: str | None) -> bool:
    """Constant-time: both sides are hashed to fixed-length digests, then hmac.compare_digest compares them."""
    a = hashlib.sha256(str(entered or "").encode("utf-8")).digest()
    b = hashlib.sha256(str(expected or "").encode("utf-8")).digest()
    same = hmac.compare_digest(a, b)  # always runs, whatever the inputs look like
    return same and bool(expected) and bool(entered)


class PinGuard:
    """Server-wide attempt counter, one slot per configured owner PIN (keyed by an HMAC of it, never the PIN)."""

    def __init__(self) -> None:
        self.key = secrets.token_bytes(32)  # per process; fingerprints mean nothing outside it
        self._lock = threading.Lock()
        self._slots: dict[bytes, dict[str, float]] = {}

    def fingerprint(self, *parts: str) -> bytes:
        return hmac.new(self.key, "\x00".join(parts).encode("utf-8"), hashlib.sha256).digest()

    def begin(self, slot: bytes, now: float) -> float:
        """Count one attempt. 0.0 when it may be checked, else the time (monotonic) its lockout ends."""
        with self._lock:
            s = self._slots.setdefault(slot, {"failures": 0, "last": -math.inf, "lockouts": 0, "until": -math.inf})
            if now < s["until"]:
                return s["until"]
            if now - s["last"] > FAILURE_WINDOW:
                s["failures"] = 0
            if s["lockouts"] and now - s["until"] > LOCK_MEMORY:
                s["lockouts"] = 0
            if s["failures"] >= MAX_FAILURES:  # the allowance is spent: this check and the next ones wait
                s["lockouts"] += 1
                s["until"] = now + min(LOCK_BASE * 2 ** (s["lockouts"] - 1), LOCK_MAX)
                s["failures"] = 0
                return s["until"]
            s["failures"] += 1
            s["last"] = now
            return 0.0

    def succeeded(self, slot: bytes) -> None:
        """The right PIN: the attempts counted so far are forgotten (the lockout escalation is not)."""
        with self._lock:
            s = self._slots.get(slot)
            if s is not None:
                s["failures"] = 0


@st.cache_resource(show_spinner=False)
def guard() -> PinGuard:
    """One guard for every session of this app process."""
    return PinGuard()


def _now() -> float:
    return time.monotonic()


def _pause() -> None:
    if FAIL_DELAY > 0:
        time.sleep(FAIL_DELAY)


def _memo() -> dict | None:
    """This session's verdicts: {workspace id: (check fingerprint, state, recheck after)}; None outside a session."""
    try:
        memo = st.session_state.get(MEMO_KEY)
        if not isinstance(memo, dict):
            memo = {}
            st.session_state[MEMO_KEY] = memo
        return memo
    except Exception:
        return None


def entered_pin() -> str:
    value = st.session_state.get(PIN_KEY)
    return value.strip() if isinstance(value, str) else ""


def check_pin(ws: Workspace, pin: str) -> str:
    """UNLOCKED or WRONG_PIN for a non-empty PIN, through the server-wide guard and this session's memo."""
    g = guard()
    now = _now()
    check = g.fingerprint("check", ws.id, ws.owner_pin, pin)
    memo = _memo()
    seen = memo.get(ws.id) if memo is not None else None
    if isinstance(seen, tuple) and len(seen) == 3 and hmac.compare_digest(seen[0], check) and now < seen[2]:
        return seen[1]
    slot = g.fingerprint("slot", ws.owner_pin)
    locked_until = g.begin(slot, now)
    if locked_until:
        state, recheck = WRONG_PIN, locked_until  # refused unchecked; checked again once the lockout ends
    elif pin_matches(pin, ws.owner_pin):
        g.succeeded(slot)
        state, recheck = UNLOCKED, math.inf
    else:
        state, recheck = WRONG_PIN, math.inf
    if state != UNLOCKED:
        _pause()
    if memo is not None:
        memo[ws.id] = (check, state, recheck)
    return state


def lock_state(ws: Workspace | None, pin: str | None = None) -> str:
    if ws is None or not ws.can_write:
        return NOT_CONFIGURED
    pin = entered_pin() if pin is None else pin
    if not pin:
        return NO_PIN
    return check_pin(ws, pin)


def owner_token(ws: Workspace | None, pin: str | None = None) -> str | None:
    """The workspace's owner_token when the PIN matches, else None."""
    return ws.owner_token if lock_state(ws, pin) == UNLOCKED else None


def lock_message(ws: Workspace | None, state: str) -> str:
    name = f"'{ws.id}'" if ws else "this workspace"
    if state == NOT_CONFIGURED:
        return (f"Owner actions are disabled for {name}: owner_token or owner_pin is not configured "
                f"(the PIN needs {MIN_PIN_LENGTH} or more characters and cannot be the example placeholder).")
    if state == WRONG_PIN:
        return (f"That PIN does not unlock workspace {name}. After {MAX_FAILURES} wrong PINs every PIN is refused "
                "for a while, so wait a few minutes before trying again.")
    return f"Owner actions are locked. Enter the owner PIN for workspace {name} under Owner (top right)."


def require_owner(ws: Workspace | None) -> str | None:
    """The owner token, or None after drawing why the action is locked."""
    state = lock_state(ws)
    if state == UNLOCKED:
        return ws.owner_token  # type: ignore[union-attr]
    (st.error if state == WRONG_PIN else st.warning)(lock_message(ws, state))
    return None
