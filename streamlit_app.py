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
from zenux_dashboard.fmt import empty_state, esc  # noqa: E402

st.set_page_config(page_title=APP_TITLE, page_icon=":material/radar:", layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>" + (HERE / "feed.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)

VIEWS = ["Feed", "Rejected", "Rules", "Radar", "Diagnostics"]
LIVE_REFRESH_SECONDS = 120


def masthead(ws: Workspace | None) -> None:
    workspace = f'<span class="brand-workspace">{esc(ws.label.upper())}</span>' if ws else ""
    st.markdown(
        '<header class="digest-hero">'
        f'<div class="digest-title" role="heading" aria-level="1" aria-label="{esc(APP_TITLE)}">'
        '<div class="brand-primary"><span class="brand-core">ZENU<span class="brand-accent">X</span></span>'
        '<span class="brand-terminal" aria-hidden="true"></span></div>'
        f'<div class="brand-sub">NEWS INTELLIGENCE{workspace}</div></div></header>',
        unsafe_allow_html=True,
    )


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
    masthead(ws)
    if ws is None:
        st.markdown(empty_state(
            "No Zenux workspace is configured. Add a [[workspaces]] table to dashboard/.streamlit/secrets.toml "
            "(copy secrets.example.toml), or paste it into the app's Secrets on Streamlit Community Cloud."),
            unsafe_allow_html=True)
        for problem in conf.problems:
            st.caption(problem)
        return
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
            with st.popover("Search", width="stretch"):
                st.text_input("Search published stories", placeholder="Company, topic or source", key="feed_search")
    with rest[1]:
        owner_panel(ws)
    # Owner forms (Rules, Radar) and the control room have no page-wide timer, so unsaved input stays put;
    # the control room refreshes its own health panel.
    if view in ("Rules", "Radar", "Diagnostics"):
        render_view(view, conf, ws)
    else:
        render_live(view, ws.id)


main()
