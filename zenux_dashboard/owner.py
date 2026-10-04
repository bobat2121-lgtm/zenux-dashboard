"""Sign in to edit: the owner PIN gate and builder access (docs/SPEC-PHASE03-UI.md 1.2).

Open access (config.OPEN_ACCESS_DEFAULT, or `open_access = true` in the secrets) switches the gate off for the beta:
every session gets the workspace's owner_token and the Control room, and nothing below asks for a PIN. With
`open_access = false` the PIN gate works exactly as described next.

The analyst types the workspace's PIN once per browser session under "Sign in to edit" (top right) and presses
Unlock. The PIN never leaves this server: it is checked once, in constant time, against the workspace's `owner_pin`
from st.secrets through the server-wide guard below, and the field is cleared right away (the PIN is never kept in
widget state). On a match the session remembers an HMAC fingerprint of (workspace id, configured PIN) in
st.session_state["zx_unlocked"], never the PIN itself, so a changed PIN in st.secrets locks the session again. While
unlocked, the workspace's `owner_token` is the bearer for hub writes (module backfills use their `run_token` behind
the same gate). Lock forgets every fingerprint. A browser reload is a new Streamlit session and asks again (identity
sign-in, later, removes this).

The builder (who sees the Control room) unlocks with the builder PIN (`Config.builder_pin`, with its fallbacks),
checked through the same guard. When the builder PIN equals the workspace's owner PIN (the two configured values are
compared in constant time, with no guard attempt), a successful owner unlock opens the Control room too, so the pilot
owner types one PIN. A builder may write to every configured workspace: the hub has one OWNER_TOKEN, so the roles are
the dashboard's alone (gap 11).

Guessing is throttled for the whole server, not per session (a script can open as many sessions as it likes):

- Every new PIN tried against a configured PIN counts as an attempt in a server-wide guard (st.cache_resource), shared
  by every workspace configured with that same PIN (and by the builder when its PIN is the same). The attempt is
  counted before the compare, so parallel guesses cannot overshoot the limit; the right PIN clears the count.
- After MAX_FAILURES wrong PINs (misses are forgotten after FAILURE_WINDOW seconds without one), every check of that
  PIN is refused, right or wrong, for a lockout that doubles each time (LOCK_BASE up to LOCK_MAX seconds); the
  escalation is forgotten LOCK_MEMORY seconds after the last lockout ends. A patient guesser gets about
  MAX_FAILURES guesses per LOCK_MAX.
- A wrong or refused PIN waits FAIL_DELAY seconds, and both show the same message, so a page never tells whether a
  PIN typed during a lockout was right.
- Each session remembers the verdict for what it has already checked (a keyed HMAC of workspace, configured PIN and
  typed PIN, never the PIN itself), so the same entry checked again counts, and waits, once.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import time
from typing import Any

import streamlit as st

from .config import Config, Workspace, load_config

PIN_KEY = "owner_pin"  # a test may preset it; adopt_entered_pin() consumes it once
BUILDER_PIN_KEY = "zx_builder_pin"  # the same for the builder PIN
ENTRY_KEY = "zx_pin_entry"  # the popover's PIN field (cleared after every Unlock)
BUILDER_ENTRY_KEY = "zx_builder_pin_entry"
UNLOCK_KEY = "zx_unlocked"  # {workspace id: fingerprint}
BUILDER_KEY = "zx_builder"  # fingerprint of the builder PIN
RESULT_KEY = "zx_pin_result"  # {workspace id | BUILDER_SLOT: the last refused unlock}, drawn under the PIN field
MEMO_KEY = "zx_owner_checks"
BUILDER_SLOT = "\x00builder"  # the builder's memo and result slot (never a workspace id)

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

MESSAGES = {
    NO_PIN: "Unlock to edit: use Sign in to edit at the top right.",
    WRONG_PIN: (f"That PIN doesn't match. After {MAX_FAILURES} wrong tries every PIN is refused for a while, so wait a "
                "few minutes before trying again."),
    NOT_CONFIGURED: "Editing is turned off for this workspace until the builder finishes its setup.",
}


def pin_matches(entered: str | None, expected: str | None) -> bool:
    """Constant-time: both sides are hashed to fixed-length digests, then hmac.compare_digest compares them."""
    a = hashlib.sha256(str(entered or "").encode("utf-8")).digest()
    b = hashlib.sha256(str(expected or "").encode("utf-8")).digest()
    same = hmac.compare_digest(a, b)  # always runs, whatever the inputs look like
    return same and bool(expected) and bool(entered)


class PinGuard:
    """Server-wide attempt counter, one slot per configured PIN (keyed by an HMAC of it, never the PIN)."""

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


def _session() -> Any:
    """This browser session's state, or None outside a session."""
    try:
        state = st.session_state
        state.get(UNLOCK_KEY)  # raises outside a session in some modes
        return state
    except Exception:
        return None


def _memo() -> dict | None:
    """This session's verdicts: {slot id: (check fingerprint, state, recheck after)}; None outside a session."""
    try:
        memo = st.session_state.get(MEMO_KEY)
        if not isinstance(memo, dict):
            memo = {}
            st.session_state[MEMO_KEY] = memo
        return memo
    except Exception:
        return None


def _check(slot_id: str, expected: str, pin: str) -> str:
    """UNLOCKED or WRONG_PIN for a non-empty PIN, through the server-wide guard and this session's memo."""
    g = guard()
    now = _now()
    check = g.fingerprint("check", slot_id, expected, pin)
    memo = _memo()
    seen = memo.get(slot_id) if memo is not None else None
    if isinstance(seen, tuple) and len(seen) == 3 and hmac.compare_digest(seen[0], check) and now < seen[2]:
        return seen[1]
    slot = g.fingerprint("slot", expected)
    locked_until = g.begin(slot, now)
    if locked_until:
        state, recheck = WRONG_PIN, locked_until  # refused unchecked; checked again once the lockout ends
    elif pin_matches(pin, expected):
        g.succeeded(slot)
        state, recheck = UNLOCKED, math.inf
    else:
        state, recheck = WRONG_PIN, math.inf
    if state != UNLOCKED:
        _pause()
    if memo is not None:
        memo[slot_id] = (check, state, recheck)
    return state


def check_pin(ws: Workspace, pin: str) -> str:
    """UNLOCKED or WRONG_PIN for a non-empty PIN typed for this workspace (counted by the guard)."""
    return _check(ws.id, ws.owner_pin, pin)


def _fingerprint(*parts: str) -> bytes:
    return guard().fingerprint("unlocked", *parts)


def _same(stored: Any, expected: bytes) -> bool:
    return isinstance(stored, bytes) and hmac.compare_digest(stored, expected)


def _remember(slot_id: str, state: str) -> None:
    s = _session()
    if s is None:
        return
    results = dict(s.get(RESULT_KEY) or {})
    if state in (UNLOCKED, NO_PIN):
        results.pop(slot_id, None)
    else:
        results[slot_id] = state
    s[RESULT_KEY] = results


def last_result(ws: Workspace | None = None, *, builder: bool = False) -> str | None:
    """The last refused unlock (WRONG_PIN or NOT_CONFIGURED) for this workspace or the builder, else None."""
    s = _session()
    if s is None:
        return None
    key = BUILDER_SLOT if builder else (ws.id if ws is not None else "")
    return (s.get(RESULT_KEY) or {}).get(key)


def _clean(pin: Any) -> str:
    if isinstance(pin, int) and not isinstance(pin, bool):
        pin = str(pin)
    return pin.strip() if isinstance(pin, str) else ""


def _unlock(conf: Config, ws: Workspace | None, pin: Any) -> str:
    if ws is None or not ws.can_write:
        state = NOT_CONFIGURED
    else:
        pin = _clean(pin)
        state = check_pin(ws, pin) if pin else NO_PIN
    s = _session()
    if state == UNLOCKED and s is not None:
        unlocked = dict(s.get(UNLOCK_KEY) or {})
        unlocked[ws.id] = _fingerprint("owner", ws.id, ws.owner_pin)  # type: ignore[union-attr]
        s[UNLOCK_KEY] = unlocked
        # The pilot: the owner is the builder. Compared between the two configured values, no guard attempt.
        if conf.has_builder and pin_matches(conf.builder_pin, ws.owner_pin):  # type: ignore[union-attr]
            s[BUILDER_KEY] = _fingerprint("builder", conf.builder_pin)
            _remember(BUILDER_SLOT, UNLOCKED)
    _remember(ws.id if ws is not None else "", state)
    return state


def unlock(ws: Workspace | None, pin: str) -> str:
    """UNLOCKED | WRONG_PIN | NO_PIN | NOT_CONFIGURED. On UNLOCKED this session can edit ws (and, when the builder PIN
    equals ws.owner_pin, the builder is unlocked too)."""
    return _unlock(load_config(), ws, pin)


def builder_unlock(conf: Config, pin: str) -> str:
    """UNLOCKED | WRONG_PIN | NO_PIN | NOT_CONFIGURED, through the same guard (slot keyed by the builder PIN)."""
    if not conf.has_builder:
        state = NOT_CONFIGURED
    else:
        pin = _clean(pin)
        state = _check(BUILDER_SLOT, conf.builder_pin, pin) if pin else NO_PIN
    s = _session()
    if state == UNLOCKED and s is not None:
        s[BUILDER_KEY] = _fingerprint("builder", conf.builder_pin)
    _remember(BUILDER_SLOT, state)
    return state


def lock(ws: Workspace | None = None) -> None:
    """Forget the unlock of ws, or (None) of every workspace and the builder."""
    s = _session()
    if s is None:
        return
    if ws is None:
        for key in (UNLOCK_KEY, BUILDER_KEY, RESULT_KEY):
            s.pop(key, None)
        return
    unlocked = dict(s.get(UNLOCK_KEY) or {})
    unlocked.pop(ws.id, None)
    s[UNLOCK_KEY] = unlocked


def is_unlocked(ws: Workspace | None) -> bool:
    """This session unlocked ws with its current PIN (a changed PIN in the secrets no longer matches)."""
    if ws is None or not ws.can_write:
        return False
    s = _session()
    if s is None:
        return False
    return _same((s.get(UNLOCK_KEY) or {}).get(ws.id), _fingerprint("owner", ws.id, ws.owner_pin))


def is_builder(conf: Config | None = None) -> bool:
    """Open access is on, or the builder unlocked this session with the current builder PIN."""
    conf = conf if conf is not None else load_config()
    if conf.open_access:
        return True
    s = _session()
    stored = s.get(BUILDER_KEY) if s is not None else None
    if stored is None:
        return False
    return conf.has_builder and _same(stored, _fingerprint("builder", conf.builder_pin))


def is_open(ws: Workspace | None) -> bool:
    """Open access: this workspace is editable by every visitor, with no PIN."""
    return ws is not None and ws.open_access and ws.can_write


def token(ws: Workspace | None) -> str | None:
    """The workspace's owner_token under open access, or while the workspace or the builder is unlocked, else None."""
    if ws is None or not (ws.hub_url and ws.owner_token):
        return None
    if ws.open_access:
        return ws.owner_token
    return ws.owner_token if is_unlocked(ws) or is_builder() else None


def can_edit(ws: Workspace | None) -> bool:
    return token(ws) is not None


def adopt_entered_pin(conf: Config, ws: Workspace | None) -> None:
    """Once per run, before anything reads the lock: a PIN preset in PIN_KEY or BUILDER_PIN_KEY (tests) is consumed
    and checked once, as if typed and unlocked in the popover."""
    s = _session()
    if s is None:
        return
    pin = s.pop(PIN_KEY, None) if PIN_KEY in s else None
    if _clean(pin):
        _unlock(conf, ws, pin)
    builder_pin = s.pop(BUILDER_PIN_KEY, None) if BUILDER_PIN_KEY in s else None
    if _clean(builder_pin):
        builder_unlock(conf, builder_pin)


def lock_state(ws: Workspace | None) -> str:
    """UNLOCKED while ws or the builder is unlocked; else NO_PIN, or NOT_CONFIGURED when ws cannot be edited."""
    if token(ws) is not None:
        return UNLOCKED
    if ws is None or not ws.can_write:
        return NOT_CONFIGURED
    return NO_PIN


def lock_message(ws: Workspace | None, state: str) -> str:
    """A plain sentence for a lock state (the technical reason stays in the Control room's Configuration notes)."""
    return MESSAGES.get(state, MESSAGES[NO_PIN])


def require_owner(ws: Workspace | None) -> str | None:
    """The owner token, or None after drawing why the action is locked."""
    tok = token(ws)
    if tok is not None:
        return tok
    state = lock_state(ws)
    st.warning(lock_message(ws, state))
    return None
