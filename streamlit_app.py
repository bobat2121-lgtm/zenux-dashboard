"""ZENITH: the Zenith news-intelligence dashboard (Streamlit).

Four tabs over a workspace's hub (docs/SPEC-SIMPLIFY.md 2.1): Briefing (daily), Tuning (weekly) and Coverage (setup)
for the analyst, and the Control room for the builder (in the tab list only while the builder is unlocked; it spans
every configured workspace). Old links to the removed tabs land on their successors (links.TAB_ALIASES). Configuration comes only from st.secrets (dashboard/.streamlit/secrets.toml locally, App
settings -> Secrets on Streamlit Community Cloud); see .streamlit/secrets.example.toml. Changes need "Sign in to
edit" (the workspace PIN, once per browser session), which unlocks the workspace's owner_token, unless open access
is on (the beta default; `open_access = false` in the secrets turns the PIN back on).

Every run, top to bottom: page config and stylesheet; config, deep links (read once per session), the workspace,
a PIN preset by a test, the tab (a pending switch applied, the Control room dropped while the builder is locked) and
the queued toasts; the green top bar (masthead, tabs, workspace switcher, sign-in popover); the content band (the
undo bar, then the tab); the footer; the pending dialog; the query string.

This is a Zenith app. It is separate from the legacy PHYSAI news dashboard and never talks to it.
"""

import importlib
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st  # noqa: E402

from zenux_dashboard import APP_TITLE  # noqa: E402
from zenux_dashboard import labels, links, owner, ui  # noqa: E402
from zenux_dashboard.config import Config, Workspace, load_config  # noqa: E402
from zenux_dashboard.fmt import empty_state, esc, md_label, png_data_uri  # noqa: E402

ASSETS = HERE / "assets"
FAVICON = ASSETS / "zenux-favicon.png"  # the browser-tab icon (128 px)
MARK = ASSETS / "zenux-favicon.png"  # the logo mark beside the wordmark: the 128 px file is sharp at about 40 px and 7x lighter than the 512 px mark

st.set_page_config(page_title=APP_TITLE, page_icon=FAVICON, layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>" + (HERE / "feed.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)

FOOTER = "ZENITH · internal research tool · data from public sources"
SIGNIN_KEY = "zx_signin"  # the sign-in popover (its open state)
LOG = logging.getLogger("zenux_dashboard.app")

# Every view module is imported at startup, even for tabs not shown, so every dialog is registered before
# ui.render_dialog() runs. `actions` (the card actions) registers the dialogs the other views share.
VIEW_MODULES = ("actions", "feed_view", "tuning_view", "coverage_view", "control_view")
TAB_VIEWS = {"briefing": "feed_view", "tuning": "tuning_view", "coverage": "coverage_view", "control": "control_view"}


def load_views() -> tuple[dict, dict]:
    """(loaded modules, import errors) by module name. A view that cannot be imported shows a plain error on its tab
    instead of taking every tab down."""
    loaded, failed = {}, {}
    for name in VIEW_MODULES:
        try:
            loaded[name] = importlib.import_module(f"zenux_dashboard.{name}")
        except Exception as exc:  # noqa: BLE001 - shown on the tab, logged here
            LOG.error("could not import zenux_dashboard.%s: %r", name, exc)
            failed[name] = exc
    return loaded, failed


def masthead(ws: Workspace | None) -> None:
    """The wordmark row of the green top bar: the mark and ZENITH, the tagline and the workspace tag."""
    workspace = f'<span class="brand-workspace">{esc(ws.label.upper())}</span>' if ws else ""
    src = png_data_uri(str(MARK))  # inline, so it renders without static-file serving (Streamlit Community Cloud)
    mark = f'<img class="brand-mark" src="{src}" alt="{esc(APP_TITLE)}" width="42" height="42">' if src else ""
    st.markdown(
        '<header class="zx-masthead">'
        f'<div class="brand" role="heading" aria-level="1" aria-label="{esc(APP_TITLE)}">'
        f'<span class="brand-lockup">{mark}<span class="brand-core">{esc(APP_TITLE)}</span></span>'
        f'<span class="brand-sub">NEWS INTELLIGENCE</span>{workspace}</div></header>',
        unsafe_allow_html=True,
    )


def footer() -> None:
    st.markdown(f'<footer class="zx-footer">{esc(FOOTER)}</footer>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------------------------- sign in to edit


def _unlock(workspace_id: str) -> None:
    """The PIN field's on_change (Enter) and Unlock's on_click: check the typed PIN once, then clear the field (the PIN
    is never kept in widget state). An empty field does nothing: after Enter (or leaving the field) checked the PIN,
    the Unlock click that may follow in the same run finds the field cleared and keeps the first answer."""
    pin = st.session_state.get(owner.ENTRY_KEY) or ""
    st.session_state[owner.ENTRY_KEY] = ""
    if not pin.strip():
        return
    if owner.unlock(load_config().workspace(workspace_id), pin) == owner.UNLOCKED:
        st.session_state[SIGNIN_KEY] = False  # close the popover; a wrong PIN keeps it open with its message


def _builder_unlock() -> None:
    """The Builder PIN field's on_change (Enter) and Open the Control room's on_click, as _unlock."""
    pin = st.session_state.get(owner.BUILDER_ENTRY_KEY) or ""
    st.session_state[owner.BUILDER_ENTRY_KEY] = ""
    if not pin.strip():
        return
    if owner.builder_unlock(load_config(), pin) == owner.UNLOCKED:
        st.session_state[SIGNIN_KEY] = False
        links.set_tab(labels.BUILDER_TAB)


def _lock() -> None:
    owner.lock()
    st.session_state[SIGNIN_KEY] = False
    ui.notify("Locked. Editing is off until you unlock again.")
    if links.current_tab() == labels.BUILDER_TAB:
        links.set_tab(links.DEFAULT_TAB)


OPEN_LABEL = "Open for testing"
OPEN_TEXT = ("No PIN is needed: anyone with this link can edit and open the Control room while open access is on. "
             "To require the PIN again, add `open_access = false` at the top of the app's Secrets on Streamlit "
             "Community Cloud (App settings › Secrets).")


def signin_popover(conf: Config, ws: Workspace, builder: bool) -> None:
    """Sign in to edit (locked) / Signed in (unlocked), with the builder's part under a divider; under open access a
    note that says so instead."""
    if owner.is_open(ws):
        with st.popover(OPEN_LABEL, key=SIGNIN_KEY, width="stretch", icon=":material/lock_open:"):
            st.markdown(OPEN_TEXT)
        return
    signed_in = owner.can_edit(ws)
    # on_change="rerun" makes the popover's open state a widget value, so Unlock, Open the Control room and Lock
    # can close it from their callbacks (the page under it is then in view)
    with st.popover("Signed in" if signed_in else "Sign in to edit", key=SIGNIN_KEY, width="stretch",
                    on_change="rerun"):
        if signed_in:
            st.markdown(md_label(f"You can edit {ws.label} in this browser tab until you lock it, reload the page or "
                                 "close the tab."))
            st.button("Lock", key="zx_lock", on_click=_lock, icon=":material/lock:")
        elif not ws.can_write:
            st.caption(owner.lock_message(ws, owner.NOT_CONFIGURED))
        else:
            st.text_input("PIN", type="password", key=owner.ENTRY_KEY, placeholder="Your PIN", on_change=_unlock,
                          args=(ws.id,))
            st.button("Unlock", key="zx_unlock", type="primary", on_click=_unlock, args=(ws.id,))
            st.caption("Unlocks editing in this browser tab until you reload or close it.")
            if owner.last_result(ws) == owner.WRONG_PIN:
                st.error(owner.lock_message(ws, owner.WRONG_PIN))
        if conf.has_builder:
            st.divider()
            st.caption("Builder")
            if builder:
                st.caption("Control room open.")
            else:
                st.text_input("Builder PIN", type="password", key=owner.BUILDER_ENTRY_KEY, on_change=_builder_unlock)
                st.button("Open the Control room", key="zx_builder_unlock", on_click=_builder_unlock)
                if owner.last_result(builder=True) == owner.WRONG_PIN:
                    st.error(owner.lock_message(None, owner.WRONG_PIN))


# ---------------------------------------------------------------------------------------------- page


def navigation(conf: Config, ws: Workspace, builder: bool) -> str:
    """The tabs (a styled radio), the workspace switcher (2+ workspaces) and the sign-in popover."""
    ids = conf.ids
    options = list(labels.ANALYST_TABS) + ([labels.BUILDER_TAB] if builder else [])
    columns = st.columns([4, 1.3, 1.1] if len(ids) > 1 else [4, 1.1], gap="small", vertical_alignment="center")
    with columns[0]:
        tab = st.radio("Dashboard view", options, horizontal=True, label_visibility="collapsed", key=links.TAB_KEY,
                       format_func=labels.tab_label)
    rest = columns[1:]
    if len(ids) > 1:
        with rest[0]:
            st.selectbox("Workspace", ids, key="workspace", label_visibility="collapsed",
                         format_func=lambda i: (conf.workspace(i) or ws).label)
        rest = rest[1:]
    with rest[0], st.container(key="zx_owner"):
        signin_popover(conf, ws, builder)
    return tab if tab in options else links.DEFAULT_TAB


def render_tab(tab: str, conf: Config, ws: Workspace, views: dict, failed: dict) -> None:
    """The tab's render, or a plain error box instead of a traceback."""
    name = TAB_VIEWS.get(tab, TAB_VIEWS[links.DEFAULT_TAB])
    module = views.get(name)
    try:
        if module is None:
            raise failed.get(name) or ImportError(f"zenux_dashboard.{name} is not available")
        if tab == labels.BUILDER_TAB:
            module.render(conf, ws)
        else:
            module.render(ws)
    except Exception as exc:  # noqa: BLE001 - a plain error box; st.rerun/st.stop are not Exceptions
        ui.note_crash(exc)
        ui.error_box("this page", exc, key="page")


def main() -> None:
    st.session_state.pop("zx_page_crash", None)
    conf = load_config()
    links.read_once(conf)
    ids = conf.ids
    if ids and st.session_state.get("workspace") not in ids:
        st.session_state["workspace"] = ids[0]
    ws = conf.workspace(st.session_state.get("workspace")) if ids else None
    owner.adopt_entered_pin(conf, ws)
    builder = owner.is_builder(conf)
    tab, refused = links.resolve(builder)
    if refused:
        ui.notify(links.CONTROL_LOCKED)
    views, failed = load_views()
    ui.flush_toasts()
    with st.container(key="zx_topbar"):  # the full-width green bar: wordmark row, then the navigation row
        masthead(ws)
        if ws is not None:
            tab = navigation(conf, ws, builder)
    if ws is None:
        with st.container(key="zx_view"):
            st.markdown(empty_state(
                "No Zenith workspace is configured. Add a [[workspaces]] table to dashboard/.streamlit/secrets.toml "
                "(copy secrets.example.toml), or paste it into the app's Secrets on Streamlit Community Cloud."),
                unsafe_allow_html=True)
            for problem in conf.problems:
                st.caption(problem)
        footer()
        return
    with st.container(key="zx_view"):  # the content band
        try:
            ui.undo_bar(ws)
        except Exception as exc:  # noqa: BLE001
            ui.note_crash(exc)
            ui.error_box("this page", exc, key="undo")
        render_tab(tab, conf, ws, views, failed)
    footer()
    ui.render_dialog()
    links.sync(tab, ws.id)


main()
