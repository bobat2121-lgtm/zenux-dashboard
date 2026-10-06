"""Deep links and in-app navigation (docs/SPEC-PHASE03-UI.md 1.7 and 3.7; the tabs of docs/SPEC-SIMPLIFY.md 2.1).

Query parameters, all optional and validated (an invalid one is ignored): `tab` (a tab slug: briefing, tuning,
coverage, control), `ws` (a configured workspace id), `edition`, `item`, `request` (positive ints), `rules` (Tuning's
filter of Your rules: all, more, less, muted, watchlist), `pref` (R-NNNN / I-NNNN), `module` (a coverage area id). The
shell reads them once per session into session state (read_once) and writes the current state back at the end of every
run (sync), so a reload or a shared link lands on the same tab and object.

Old links keep working (TAB_ALIASES): `tab=preferences` opens Tuning (a `pref=` link still highlights its rule; the
old `section=` says which part: `looks_for` opens Coverage, where What ZENITH looks for now lives, and `muted` or
`watchlist` picks that filter of Your rules), and `tab=filtered` (with any `view=`) opens Briefing. `section` is only
ever read, never written.

Focus values live in st.session_state["zx_focus"]; each tab mirrors only its own parameters (TAB_PARAMS), so another
tab's focus is kept for when the analyst comes back to it. Internal navigation uses go() from a button, never an
`<a href="?...">` anchor: an anchor reload starts a new Streamlit session and loses the unlock.

The tab radio (key "zx_tab") is drawn early in the run, so its value can only change before it is drawn: go() and
set_tab() leave the wanted tab pending and the shell applies it on the next run (resolve) before drawing the radio.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlencode

import streamlit as st

from . import labels
from .config import MODULE_ID_RE, Config, load_config

PARAMS = ("tab", "ws", "edition", "item", "rules", "pref", "module", "request", "section")
FOCUS_PARAMS = ("edition", "item", "rules", "pref", "module", "request")
TAB_KEY = "zx_tab"
FOCUS_KEY = "zx_focus"
READ_KEY = "zx_links_read"
PENDING_KEY = "zx_tab_pending"
RULE_FILTERS = ("all", "more", "less", "muted", "watchlist")
OLD_SECTIONS = ("ok", "active", "looks_for", "muted", "watchlist", "how_much")  # My preferences' sections (old links)
TAB_ALIASES = {"preferences": "tuning", "filtered": "briefing"}  # the tabs docs/SPEC-SIMPLIFY.md removed
PREF_RE = re.compile(r"^[RI]-\d{4,9}$")
INT_RE = re.compile(r"^[1-9]\d{0,8}$")
TAB_PARAMS: dict[str, tuple[str, ...]] = {
    "briefing": ("edition", "item"),
    "tuning": ("rules", "pref"),
    "coverage": ("module", "request"),
    "control": ("module",),
}
SLUGS = tuple(slug for slug, _ in labels.TABS)
DEFAULT_TAB = "briefing"
CONTROL_LOCKED = "The Control room is for the builder. Unlock it under Sign in to edit."


def _first(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value).strip() if value is not None else ""


def tab_slug(value: Any) -> str | None:
    """A tab slug, an old tab's slug mapped to its successor (TAB_ALIASES), or None."""
    text = _first(value)
    if text in SLUGS:
        return text
    return TAB_ALIASES.get(text)


def _valid(name: str, value: str, conf: Config | None) -> Any:
    """The validated value of one parameter, or None."""
    if not value:
        return None
    if name == "tab":
        return tab_slug(value)
    if name == "ws":
        return value if conf is not None and value in conf.ids else None
    if name in ("edition", "item", "request"):
        return int(value) if INT_RE.match(value) else None
    if name == "rules":
        return value if value in RULE_FILTERS else None
    if name == "section":
        return value if value in OLD_SECTIONS else None
    if name == "pref":
        return value if PREF_RE.match(value) else None
    if name == "module":
        return value if MODULE_ID_RE.match(value) else None
    return None


def parse(params: Mapping[str, Any], conf: Config | None) -> dict[str, Any]:
    """The valid parameters among params (pure; invalid and unknown ones are dropped, an old tab is mapped to its
    successor, and an old My preferences `section` is translated: looks_for opens Coverage, muted and watchlist pick
    that filter of Your rules)."""
    out: dict[str, Any] = {}
    for name in PARAMS:
        if name in params:
            value = _valid(name, _first(params.get(name)), conf)
            if value is not None:
                out[name] = value
    section = out.pop("section", None)
    if section and out.get("tab") == "tuning":
        if section == "looks_for":
            out["tab"] = "coverage"
            out.pop("pref", None)
        elif section in ("muted", "watchlist") and "rules" not in out:
            out["rules"] = section
    return out


def href(tab: str, **params: Any) -> str:
    """"?tab=briefing&edition=12&item=1203" (copyable text and tests; never a link the page navigates by)."""
    names = [name for name in PARAMS[1:] if name != "section"]
    pairs = [("tab", tab)] + [(name, params[name]) for name in names if params.get(name) is not None]
    return "?" + urlencode([(k, str(v)) for k, v in pairs])


# ---------------------------------------------------------------------------------------------- session state


def _focus_map() -> dict[str, Any]:
    value = st.session_state.get(FOCUS_KEY)
    return dict(value) if isinstance(value, dict) else {}


def read_once(conf: Config) -> None:
    """First run of a session only: valid query parameters into session state (tab, workspace, focus)."""
    if st.session_state.get(READ_KEY):
        return
    st.session_state[READ_KEY] = True
    try:
        raw = st.query_params.to_dict()
    except Exception:
        raw = {}
    parsed = parse(raw, conf)
    if "ws" in parsed:
        st.session_state["workspace"] = parsed["ws"]
    if "tab" in parsed:
        st.session_state[PENDING_KEY] = parsed["tab"]
    focus = {name: parsed[name] for name in FOCUS_PARAMS if name in parsed}
    if focus:
        st.session_state[FOCUS_KEY] = {**_focus_map(), **focus}


def resolve(builder: bool) -> tuple[str, bool]:
    """Shell, before the tab radio: apply a pending tab (go, set_tab, a deep link) and drop the Control room when the
    builder is locked. Returns (tab, refused): refused is True when a Control room request fell back to Briefing (the
    shell then shows CONTROL_LOCKED)."""
    pending = tab_slug(st.session_state.pop(PENDING_KEY, None))
    tab = pending or tab_slug(st.session_state.get(TAB_KEY))
    if tab not in SLUGS:
        tab = DEFAULT_TAB
    refused = False
    if tab == labels.BUILDER_TAB and not builder:
        refused = pending == labels.BUILDER_TAB
        tab = DEFAULT_TAB
    st.session_state[TAB_KEY] = tab
    return tab, refused


def current_tab() -> str:
    tab = st.session_state.get(TAB_KEY)
    return tab if tab in SLUGS else DEFAULT_TAB


def set_tab(tab: str) -> None:
    """Switch to tab on the next run without rerunning now (for callbacks; go() reruns)."""
    st.session_state[PENDING_KEY] = tab_slug(tab) or DEFAULT_TAB


def focus(name: str) -> Any:
    return _focus_map().get(name)


def set_focus(**focus_values: Any) -> None:
    """Update focus values without a rerun; None removes one."""
    current = _focus_map()
    for name, value in focus_values.items():
        if value is None:
            current.pop(name, None)
        else:
            current[name] = value
    st.session_state[FOCUS_KEY] = current


def clear_focus(*names: str) -> None:
    current = _focus_map()
    for name in names:
        current.pop(name, None)
    st.session_state[FOCUS_KEY] = current


def go(tab: str, **focus_values: Any) -> None:
    """Open tab with this focus: the tab's other parameters are cleared, the query string is written, and the app
    reruns (st.rerun; from a button's callback, after which Streamlit reruns anyway, that call does nothing)."""
    tab = tab_slug(tab) or DEFAULT_TAB
    current = _focus_map()
    for name in TAB_PARAMS.get(tab, ()):
        if name not in focus_values:
            current.pop(name, None)
    for name, value in focus_values.items():
        if value is None:
            current.pop(name, None)
        else:
            current[name] = value
    st.session_state[FOCUS_KEY] = current
    st.session_state[PENDING_KEY] = tab
    _write(tab, st.session_state.get("workspace"))
    st.rerun()


def _wanted(tab: str, workspace_id: str | None, multi: bool) -> dict[str, str]:
    want = {"tab": tab}
    if multi and workspace_id:
        want["ws"] = str(workspace_id)
    current = _focus_map()
    for name in TAB_PARAMS.get(tab, ()):
        value = current.get(name)
        if value is not None and _valid(name, str(value), None) is not None:
            want[name] = str(value)
    return want


def _write(tab: str, workspace_id: str | None) -> None:
    want = _wanted(tab, workspace_id, len(load_config().ids) > 1)
    try:
        if st.query_params.to_dict() != want:
            st.query_params.from_dict(want)
    except Exception:  # outside a session
        pass


def sync(tab: str, workspace_id: str | None) -> None:
    """Shell, end of every run: mirror the tab, the workspace (only with 2+ workspaces) and the tab's focus into
    st.query_params."""
    _write(tab, workspace_id)
