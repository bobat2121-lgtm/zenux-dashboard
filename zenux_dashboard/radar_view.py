"""Radar: every change to what this workspace collects, signed off here (GET /radar).

The owner asks in their own words (POST /radar/requests {kind, text, url?, module?}): track a source, a story we
missed, or new coverage. The Zenux Radar scout routine answers at its next run with a proposal
{summary, sources?: [module source configs], registry_changes?: [...], notes?}; the owner approves or rejects it
(POST /radar/:id/{approve|reject}, with an optional note). Writes need the owner PIN. An approved request becomes
approved_pending_apply: applying it to a module's config or registry is a later, reviewed deploy step. An approval
carries the proposed_at of the proposal shown, so a different proposal is refused (409 proposal_changed) and the page
re-reads it for the owner to review again.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from . import api, data, owner
from .config import Workspace
from .fmt import (as_list, clip, dicts, empty_state, esc, esc_lines, fmt_short, label_of, link, one_line, pick, pill,
                  plural, safe_url, table, unique_by_id)
from .grading import flash

KINDS = {"Track a source": "track_source", "Missed story": "missed_story", "New coverage": "new_coverage"}
KIND_LABEL = {v: k for k, v in KINDS.items()}
MIN_TEXT = 10
ANY_MODULE = "any module"
PROPOSAL_CHANGED = "proposal_changed"
WAITING = ("queued", "pending", "new", "scouting")
YOUR_TURN = ("proposed", "ready")
PROPOSAL_FIELDS = (
    ("action", "Action"), ("module", "Module"), ("source_key", "Source key"), ("key", "Source key"),
    ("connector", "Connector"), ("url", "URL"), ("lane", "Lane"), ("trust", "Trust"), ("cadence_minutes", "Cadence"),
    ("entity_id", "Entity"), ("found", "Found"), ("collected", "Collected"), ("event_id", "Event"),
    ("why_missed", "Why missed"),
)


def requests_of(body: Any) -> list[dict]:
    if isinstance(body, list):
        return dicts(body)
    return dicts(pick(body, "requests", "radar", "items", default=[]))


def status_of(row: dict) -> str:
    return one_line(pick(row, "status", "state")).lower() or "queued"


def kind_of(row: dict) -> str:
    return one_line(pick(row, "kind", "type")).lower() or "track_source"


def proposal_of(row: dict) -> dict:
    proposal = row.get("proposal")
    return proposal if isinstance(proposal, dict) else ({"summary": proposal} if one_line(proposal) else {})


def kind_chip(kind: str) -> str:
    return f'<span class="loop-kind loop-kind-{esc(kind)}">{esc(KIND_LABEL.get(kind, kind.replace("_", " ")))}</span>'


def proposal_rows(proposal: dict) -> list[list[str]]:
    rows = []
    shown: set[str] = set()
    source = proposal.get("source") if isinstance(proposal.get("source"), dict) else {}
    merged = {**source, **{k: v for k, v in proposal.items() if not isinstance(v, (dict, list))}}
    for key, label in PROPOSAL_FIELDS:
        value = merged.get(key)
        if value is None or one_line(value) == "" or label in shown:
            continue
        shown.add(label)
        cell = link(value, one_line(value)) if key == "url" and safe_url(value) else esc(one_line(value))
        rows.append([esc(label), cell])
    config = source.get("config") if isinstance(source.get("config"), dict) else None
    if config and config.get("url") and "URL" not in shown:
        rows.append(["URL", link(config["url"], one_line(config["url"]))])
    return rows


def sources_table(proposal: dict) -> str:
    """The scout's proposed module source configs, one row each."""
    rows = []
    for src in dicts(proposal.get("sources"))[:50]:
        config = src.get("config") if isinstance(src.get("config"), dict) else {}
        url = pick(src, "url") or pick(config, "url", "feed_url", "base_url")
        rows.append([
            esc(one_line(src.get("module"))), f'<span class="mono">{esc(one_line(src.get("key")))}</span>',
            esc(one_line(src.get("connector"))), esc(one_line(src.get("lane"))), esc(one_line(src.get("trust"))),
            link(url, clip(url, 60)) if safe_url(url) else esc(clip(url, 60)),
        ])
    return table(["Module", "Source key", "Connector", "Lane", "Trust", "URL"], rows) if rows else ""


def registry_html(proposal: dict) -> str:
    changes = dicts(proposal.get("registry_changes"))
    if not changes:
        return ""
    names = [one_line(pick(c, "name", "entity_id", "id")) for c in changes[:8]]
    names = [n for n in names if n]
    more = f" and {len(changes) - len(names)} more" if len(changes) > len(names) else ""
    listed = f": {esc(', '.join(names))}{esc(more)}" if names else ""
    return f'<div class="refine-note">{esc(plural(len(changes), "registry change"))}{listed}</div>'


def act(ws: Workspace, path: str, payload: dict, message: str, changed: str | None = None) -> None:
    """One owner write. A 409 proposal_changed (the proposal is not the one shown) re-reads the list and says so."""
    token = owner.require_owner(ws)
    if not token:
        return
    try:
        api.hub_post(ws, path, payload, token)
    except api.ApiError as exc:
        if exc.code == PROPOSAL_CHANGED:
            data.clear_reads()
            flash("warning", changed or f"Not saved: {exc}")
            return
        st.error(f"Not saved: {exc}")
        return
    data.clear_reads()
    flash("success", message)


def render_composer(ws: Workspace) -> None:
    with st.form(f"radar_composer_{ws.id}", border=True):
        st.markdown('<div class="rules-section" style="margin-top:0">New request</div>', unsafe_allow_html=True)
        kind = st.radio("This is", list(KINDS), horizontal=True, key=f"radar_kind_{ws.id}",
                        help="Track a source: a newsroom, feed or register whose items should reach the hub. "
                             "Missed story: a story an edition should have carried; paste its link. "
                             "New coverage: a company, program or sub-sector to start covering.")
        text = st.text_area("In your own words", key=f"radar_text_{ws.id}", height=90,
                            placeholder="e.g. Follow the Texas PUC large-load docket for data-center interconnections")
        url = st.text_input("Link (required for a missed story)", key=f"radar_url_{ws.id}", placeholder="https://…")
        modules = [ANY_MODULE] + [m.id for m in ws.modules]
        module = st.selectbox("Module (optional)", modules, key=f"radar_module_{ws.id}",
                              help="Which module the scout should look at, when you know.")
        if st.form_submit_button("Send to the Radar scout", type="primary", key=f"radar_send_{ws.id}"):
            kind_code, text, url = KINDS.get(kind, "track_source"), (text or "").strip(), (url or "").strip()
            if len(text) < MIN_TEXT:
                st.info(f"Write a few words ({MIN_TEXT} characters or more) so the scout knows what to look for.")
            elif kind_code == "missed_story" and not url:
                st.info("Paste the story's link so the scout can see what was missed.")
            elif url and not safe_url(url):
                st.info("The link must start with https:// or http://.")
            else:
                payload = {"kind": kind_code, "text": text}
                if url:
                    payload["url"] = url
                if module and module != ANY_MODULE:
                    payload["module"] = module
                act(ws, "/radar/requests", payload, "Request sent to the Zenux Radar scout · it answers after its next run")


def render_card(ws: Workspace, row: dict) -> None:
    rid = row.get("id")
    proposal = proposal_of(row)
    summary = one_line(pick(proposal, "summary", "rationale", "why", "text"))
    with st.container(border=True, key=f"zx_card_radar_{ws.id}_{rid}"):
        details = proposal_rows(proposal)
        st.markdown(
            '<div class="radar-body"><div class="loop-card-head">' + kind_chip(kind_of(row)) + pill(status_of(row))
            + f'<span class="rule-meta" style="margin-top:0">#{esc(rid)}'
            + (f' · {esc(row.get("module"))}' if one_line(row.get("module")) else "")
            + f' · {esc(fmt_short(pick(row, "proposed_at", "updated_at", "created_at"), ws.timezone))}</span></div>'
            f'<div class="refine-label">You asked</div><div class="refine-owner">{esc_lines(row.get("text"))}</div>'
            + (f'<div class="refine-note">{link(row.get("url"), one_line(row.get("url")))}</div>' if row.get("url") else "")
            + '<div class="refine-label">Scout proposal</div>'
            + (f'<div class="rule-text">{esc(summary)}</div>' if summary else '<div class="refine-note">No summary given.</div>')
            + (table(["Field", "Value"], details) if details else "")
            + sources_table(proposal)
            + registry_html(proposal)
            + (f'<div class="refine-note">{esc_lines(proposal.get("notes"))}</div>' if one_line(proposal.get("notes")) else "")
            + "</div>",
            unsafe_allow_html=True,
        )
        evidence = as_list(pick(proposal, "evidence", "samples"))
        if proposal:
            with st.expander("Full proposal" + (f" · {len(evidence)} evidence item(s)" if evidence else "")):
                st.json(proposal, expanded=False)
        note = st.text_input("Note (optional)", key=f"radar_note_{ws.id}_{rid}",
                             placeholder="why, or what to change before it is applied")
        approve, reject = st.columns(2)
        if approve.button("Approve", type="primary", key=f"radar_approve_{ws.id}_{rid}"):
            payload = {"note": note.strip()} if note.strip() else {}
            if "proposed_at" in row:
                payload["proposed_at"] = row.get("proposed_at")  # the proposal shown; the hub binds to it
            act(ws, f"/radar/{api.segment(rid)}/approve", payload, f"Approved radar request #{rid}",
                changed=f"The Zenux Radar scout has a newer proposal for radar request #{rid} than the one shown, so "
                        "nothing was approved. Review it again below.")
        if reject.button("Reject", key=f"radar_reject_{ws.id}_{rid}"):
            act(ws, f"/radar/{api.segment(rid)}/reject", {"note": note.strip()} if note.strip() else {},
                f"Rejected radar request #{rid}")


def render_waiting_row(ws: Workspace, row: dict) -> None:
    rid = row.get("id")
    with st.container(border=True, key=f"zx_card_scout_{ws.id}_{rid}"):
        text_col, button_col = st.columns([6, 1])
        text_col.markdown(
            '<div class="loop-card-head">' + kind_chip(kind_of(row)) + pill(status_of(row), "with the scout")
            + f'<span class="rule-meta" style="margin-top:0">#{esc(rid)} · '
            f'{esc(fmt_short(pick(row, "created_at"), ws.timezone))}</span></div>'
            f'<div class="refine-owner">{esc_lines(row.get("text"))}</div>',
            unsafe_allow_html=True,
        )
        if button_col.button("Withdraw", key=f"radar_withdraw_{ws.id}_{rid}"):
            act(ws, f"/radar/{api.segment(rid)}/reject", {"note": "withdrawn by owner"}, f"Withdrew radar request #{rid}")


def render(ws: Workspace) -> None:
    render_composer(ws)
    try:
        body = data.radar(ws.id)
    except api.ApiError as exc:
        st.markdown(empty_state(f"Could not load radar requests from the {ws.label} hub.", str(exc)),
                    unsafe_allow_html=True)
        return
    rows = unique_by_id(requests_of(body))
    your_turn = [r for r in rows if status_of(r) in YOUR_TURN]
    waiting = [r for r in rows if status_of(r) in WAITING]
    decided = [r for r in rows if status_of(r) not in YOUR_TURN + WAITING]
    st.caption(f"{len(your_turn)} for you · {len(waiting)} with the Zenux Radar scout · {len(decided)} decided")
    if your_turn:
        st.markdown(f'<div class="rules-section">Your turn · {len(your_turn)}</div>', unsafe_allow_html=True)
        for row in your_turn:
            render_card(ws, row)
    if waiting:
        st.markdown(f'<div class="rules-section">With the scout · {len(waiting)}</div>', unsafe_allow_html=True)
        for row in waiting:
            render_waiting_row(ws, row)
    if not your_turn and not waiting:
        st.markdown(empty_state("Nothing waiting. Ask above; the scout answers at its next run."), unsafe_allow_html=True)
    if decided:
        with st.expander(f"Decided · {len(decided)}"):
            st.markdown('<div class="rules-list">' + "".join(
                f'<div class="rule-row"><div class="rule-head">{kind_chip(kind_of(r))}{pill(status_of(r))}'
                f'<span class="rule-meta" style="margin-top:0">#{esc(r.get("id"))} · '
                f'{esc(fmt_short(pick(r, "decided_at", "updated_at", "created_at"), ws.timezone))}</span></div>'
                f'<div class="rule-text">{esc_lines(r.get("text"))}</div>'
                + (f'<div class="refine-note">Your note: {esc(clip(r.get("decision_note"), 300))}</div>'
                   if one_line(r.get("decision_note")) else "")
                + "</div>"
                for r in decided[:50]) + "</div>", unsafe_allow_html=True)
