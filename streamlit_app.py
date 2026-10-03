"""ZENUX: the Zenux news-intelligence dashboard (Streamlit).

Five views over a workspace's hub: Feed (published editions), Rejected, Rules, Radar and Diagnostics (the owner's
control room, spanning every configured workspace). Configuration comes only from st.secrets
(dashboard/.streamlit/secrets.toml locally, App settings -> Secrets on Streamlit Community Cloud); see
.streamlit/secrets.example.toml. Owner writes need the owner PIN, which unlocks the workspace's owner_token.

This is a Zenux app. It is separate from the legacy PHYSAI news dashboard and never talks to it.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st  # noqa: E402

from zenux_dashboard import APP_TITLE  # noqa: E402
from zenux_dashboard import (diagnostics_view, feed_view, grading, owner, radar_view, rejected_view,  # noqa: E402
                             rules_view)
from zenux_dashboard.config import Config, Workspace, load_config  # noqa: E402
from zenux_dashboard.fmt import empty_state, esc, png_data_uri  # noqa: E402

ASSETS = HERE / "assets"
FAVICON = ASSETS / "zenux-favicon.png"  # the browser-tab icon (128 px)
MARK = ASSETS / "zenux-favicon.png"  # the logo mark beside the wordmark: the 128 px file is sharp at about 40 px and 7x lighter than the 512 px mark

st.set_page_config(page_title=APP_TITLE, page_icon=FAVICON, layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>" + (HERE / "feed.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)

VIEWS = ["Feed", "Rejected", "Rules", "Radar", "Diagnostics"]
LIVE_REFRESH_SECONDS = 120
FOOTER = "ZENUX · internal research tool · data from public sources"


def masthead(ws: Workspace | None) -> None:
    """The wordmark row of the green top bar: the mark and ZENUX, the tagline and the workspace tag."""
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


def owner_panel(ws: Workspace) -> None:
    with st.popover("Owner", width="stretch"):
        st.text_input("Owner PIN", type="password", key=owner.PIN_KEY,
                      help="Unlocks owner actions (grades, rules, radar, backfill) for this session only.")
        state = owner.lock_state(ws)
        if state == owner.UNLOCKED:
            st.caption(f"Owner actions unlocked for {ws.id}.")
        elif state != owner.NO_PIN:
            st.caption(owner.lock_message(ws, state))
        st.checkbox("Load grading controls", key="grading_enabled",
                    help="Adds a grade form under each edition and on the Rejected tab.")


def render_view(view: str, conf: Config, ws: Workspace) -> None:
    grading.show_flash()
    if view == "Feed":
        feed_view.render(ws)
    elif view == "Rejected":
        rejected_view.render(ws)
    elif view == "Rules":
        rules_view.render(ws)
    elif view == "Radar":
        radar_view.render(ws)
    else:
        diagnostics_view.render(conf, ws)


@st.fragment(run_every=LIVE_REFRESH_SECONDS)
def render_live(view: str, workspace_id: str) -> None:
    conf = load_config()
    ws = conf.workspace(workspace_id)
    if ws is not None:
        render_view(view, conf, ws)


def main() -> None:
    conf = load_config()
    ids = conf.ids
    if ids and st.session_state.get("workspace") not in ids:
        st.session_state["workspace"] = ids[0]
    ws = conf.workspace(st.session_state.get("workspace")) if ids else None
    view = VIEWS[0]
    with st.container(key="zx_topbar"):  # the full-width green bar: wordmark row, then the navigation row
        masthead(ws)
        if ws is not None:
            view, ws = navigation(conf, ws)
    if ws is None:
        with st.container(key="zx_view"):
            st.markdown(empty_state(
                "No Zenux workspace is configured. Add a [[workspaces]] table to dashboard/.streamlit/secrets.toml "
                "(copy secrets.example.toml), or paste it into the app's Secrets on Streamlit Community Cloud."),
                unsafe_allow_html=True)
            for problem in conf.problems:
                st.caption(problem)
        footer()
        return
    with st.container(key="zx_view"):  # the light-gray content band
        # Owner forms (Rules, Radar) and the control room have no page-wide timer, so unsaved input stays put;
        # the control room refreshes its own health panel.
        if view in ("Rules", "Radar", "Diagnostics"):
            render_view(view, conf, ws)
        else:
            render_live(view, ws.id)
    footer()


def navigation(conf: Config, ws: Workspace) -> tuple[str, Workspace]:
    """The view tabs (a styled radio), the workspace switcher and the Search and Owner popovers."""
    ids = conf.ids
    columns = st.columns([4, 1.3, 1, 1] if len(ids) > 1 else [4, 1, 1], gap="small", vertical_alignment="center")
    with columns[0]:
        view = st.radio("Dashboard view", VIEWS, horizontal=True, label_visibility="collapsed", key="dashboard_view")
    rest = columns[1:]
    if len(ids) > 1:
        with rest[0]:
            st.selectbox("Workspace", ids, key="workspace", label_visibility="collapsed",
                         format_func=lambda i: (conf.workspace(i) or ws).label)
        rest = rest[1:]
        ws = conf.workspace(st.session_state.get("workspace")) or ws
    with rest[0]:
        if view == "Feed":
            with st.container(key="zx_search"), st.popover("Search", width="stretch"):
                st.text_input("Search published stories", placeholder="Company, topic or source", key="feed_search")
    with rest[1]:
        with st.container(key="zx_owner"):
            owner_panel(ws)
    return view, ws


main()
