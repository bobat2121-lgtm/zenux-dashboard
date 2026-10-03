"""Rules: the workspace's learned layer (layer 4 of the rubric), read with GET /rules.

The loop: the owner writes a rule or a worked example in their own words (POST /rules/drafts) or saves a grade
as a rule; the Zenux Rule refiner routine proposes a universal wording at its next run; the owner approves it
(optionally edited), rejects it, or later retires an active rule. Writes need the owner PIN:

    POST /rules/drafts                       {text, kind}
    POST /rules/:id/approve                  {text?, kind?, proposed_at}   a refiner proposal or a waiting draft
    POST /rules/:id/reject                   {note?}
    POST /rules/:id/retire                   {}           an active R-NNNN or I-NNNN

An approval names the proposal the owner reviewed: proposed_at exactly as GET /rules returned it (null when the draft
had no proposal yet). If the refiner proposed since this page read the list, the hub answers 409 proposal_changed and
activates nothing; the page then re-reads and asks the owner to review again. "Approve as written" also sends the
owner's own text and kind, so it can only ever activate the words shown.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from . import api, data, owner
from .config import Workspace
from .fmt import as_list, clip, dicts, empty_state, esc, esc_lines, fmt_short, link, one_line, pick, pill, unique_by_id
from .grading import flash

KINDS = {"Rule": "rule", "Worked example": "item"}
MIN_TEXT = 20
PROPOSAL_CHANGED = "proposal_changed"
WAITING = ("queued", "pending", "new", "refining")
YOUR_TURN = ("proposed", "ready", "draft")


def lists_of(body: Any) -> tuple[list[dict], list[dict]]:
    """(precedents, drafts) from {rules|precedents, drafts|rule_drafts}, or one combined list."""
    if isinstance(body, list):
        rows = dicts(body)
        return [r for r in rows if not is_draft_row(r)], [r for r in rows if is_draft_row(r)]
    precedents = dicts(pick(body, "rules", "precedents", default=[]))
    items = dicts(pick(body, "items", default=[]))
    drafts = dicts(pick(body, "drafts", "rule_drafts", default=[]))
    return precedents + [i for i in items if i not in precedents], drafts


def is_draft_row(row: dict) -> bool:
    return "proposal" in row or "owner_text" in row


def kind_of(row: dict) -> str:
    kind = one_line(pick(row, "kind", "type")).lower()
    rid = one_line(row.get("id")).upper()
    if kind in ("item", "case", "example") or rid.startswith("I-"):
        return "item"
    return "rule"


def status_of(row: dict, default: str = "active") -> str:
    return one_line(pick(row, "status", "state")).lower() or default


def proposal_of(draft: dict) -> dict:
    proposal = draft.get("proposal")
    if isinstance(proposal, dict):
        return proposal
    if isinstance(proposal, str) and proposal.strip():
        return {"text": proposal}
    return {}


def context_html(row: dict) -> str:
    """For a draft born from a grade: the story it was about and the grade given."""
    context = row.get("context")
    if not isinstance(context, dict):
        return ""
    about = one_line(pick(context, "headline", "title"))
    verdict = one_line(context.get("verdict")).replace("_", " ")
    score = context.get("score")
    grade = f" · your grade: {verdict}{f' {score}' if score is not None and verdict else ''}" if verdict else ""
    link_html = link(context.get("url"), "source ↗") if context.get("url") else ""
    return (f'<div class="refine-note">From a grade on: {esc(about) or "an event"}{esc(grade)} {link_html}</div>'
            if about or verdict else "")


def kind_chip(kind: str) -> str:
    return f'<span class="loop-kind loop-kind-{esc(kind)}">{"Worked example" if kind == "item" else "Rule"}</span>'


def act(ws: Workspace, path: str, payload: dict, message: str, changed: str | None = None,
        reset_keys: tuple[str, ...] = ()) -> None:
    """One owner write. A 409 proposal_changed (the proposal is not the one shown) re-reads the lists and says so."""
    token = owner.require_owner(ws)
    if not token:
        return
    try:
        api.hub_post(ws, path, payload, token)
    except api.ApiError as exc:
        if exc.code == PROPOSAL_CHANGED:
            for key in reset_keys:  # an edit box shows the new proposal, not the one it was opened with
                st.session_state.pop(key, None)
            data.clear_reads()
            flash("warning", changed or f"Not saved: {exc}")
            return
        st.error(f"Not saved: {exc}")
        return
    data.clear_reads()
    flash("success", message)


def reviewed(row: dict) -> dict:
    """{proposed_at} as the owner saw it, for an approval the hub binds to that proposal (null: none was shown)."""
    return {"proposed_at": row.get("proposed_at")}


# ---------------------------------------------------------------------------------------------- sections


def render_composer(ws: Workspace) -> None:
    with st.form(f"rules_composer_{ws.id}", border=True):
        st.markdown('<div class="rules-section" style="margin-top:0">New rule or worked example</div>', unsafe_allow_html=True)
        kind = st.radio("This is", list(KINDS), horizontal=True, key=f"rules_kind_{ws.id}",
                        help="Rule: a standing principle. Worked example: one story and your ruling; it guides "
                             "similar stories and never binds.")
        text = st.text_area("In your own words", key=f"rules_text_{ws.id}", height=90,
                            placeholder="e.g. Counter-drone orders under $1M are watch-band unless the buyer is new.")
        if st.form_submit_button("Send to the Rule refiner", type="primary", key=f"rules_send_{ws.id}"):
            text = (text or "").strip()
            if len(text) < MIN_TEXT:
                st.info(f"Write at least a sentence ({MIN_TEXT} characters) so the refiner has something to work with.")
            else:
                act(ws, "/rules/drafts", {"text": text, "kind": KINDS.get(kind, "rule")},
                    "Draft sent to the Zenux Rule refiner · it comes back here after its next run")


def render_proposal_card(ws: Workspace, row: dict, is_precedent: bool) -> None:
    rid = row.get("id")
    proposal = proposal_of(row)
    kind = kind_of({**row, **({"kind": proposal.get("kind")} if proposal.get("kind") else {})})
    owner_text = pick(row, "owner_text", "text") if not is_precedent else None
    proposed = one_line(pick(proposal, "text")) or one_line(row.get("text"))
    name = str(rid) if is_precedent else f"draft #{rid}"
    with st.container(border=True):
        origin = one_line(pick(row, "origin", "source")) or ("refiner" if proposal else "owner")
        st.markdown(
            '<div class="loop-card-head">' + kind_chip(kind) + pill(status_of(row))
            + f'<span class="rule-meta" style="margin-top:0">{esc(name)} · from {esc(origin)} · '
            f'{esc(fmt_short(pick(row, "updated_at", "created_at"), ws.timezone))}</span></div>'
            + (f'<div class="refine-label">Your words</div><div class="refine-owner">{esc_lines(owner_text)}</div>'
               if owner_text and one_line(owner_text) != proposed else "")
            + context_html(row)
            + (f'<div class="refine-note">{esc(one_line(proposal.get("rationale")))}</div>' if proposal.get("rationale") else "")
            + (f'<div class="refine-note">Replaces {esc(one_line(proposal.get("supersedes")))}</div>'
               if proposal.get("supersedes") else ""),
            unsafe_allow_html=True,
        )
        edit_key = f"rule_edit_{ws.id}_{rid}"
        edited = st.text_area("Refiner's version (edit it, then approve)" if proposal else "Draft text",
                              value=proposed, key=edit_key, height=100)
        approve, reject = st.columns(2)
        if approve.button("Approve", type="primary", key=f"rule_approve_{ws.id}_{rid}"):
            payload = {"text": edited.strip()} if one_line(edited) and one_line(edited) != proposed else {}
            if not is_precedent and "proposed_at" in row:
                payload.update(reviewed(row))
            act(ws, f"/rules/{api.segment(rid)}/approve", payload,
                f"Approved {name} · the Grader uses it from its next run",
                changed=f"The Zenux Rule refiner has a newer proposal for {name} than the one shown, so nothing was "
                        "approved. Review it again below.",
                reset_keys=(edit_key,))
        if reject.button("Reject", key=f"rule_reject_{ws.id}_{rid}"):
            act(ws, f"/rules/{api.segment(rid)}/reject", {}, f"Rejected {name}")


def as_written(row: dict) -> dict:
    """The approve body for "Approve as written": the owner's words and kind as shown, bound to no proposal."""
    payload: dict[str, Any] = {"kind": kind_of(row)}
    text = pick(row, "owner_text", "text")
    if isinstance(text, str) and text.strip():
        payload["text"] = text.strip()
    payload.update(reviewed(row))
    return payload


def render_waiting_row(ws: Workspace, row: dict) -> None:
    rid = row.get("id")
    kind = kind_of(row)
    with st.container(border=True):
        text_col, button_col = st.columns([5, 2])
        text_col.markdown(
            '<div class="loop-card-head">' + kind_chip(kind) + pill(status_of(row, "queued"), "with the refiner")
            + f'<span class="rule-meta" style="margin-top:0">draft #{esc(rid)} · '
            f'{esc(fmt_short(pick(row, "created_at"), ws.timezone))}</span></div>'
            f'<div class="refine-owner">{esc_lines(pick(row, "owner_text", "text", default=""))}</div>'
            + context_html(row),
            unsafe_allow_html=True,
        )
        if button_col.button("Approve as written", key=f"rule_approve_now_{ws.id}_{rid}",
                             help="Make your words a rule now, without waiting for the refiner."):
            act(ws, f"/rules/{api.segment(rid)}/approve", as_written(row), f"Approved draft #{rid} as written",
                changed=f"The Zenux Rule refiner proposed a wording for draft #{rid} after this page loaded, so nothing "
                        "was approved. Review its proposal under Your turn.")
        if button_col.button("Withdraw", key=f"rule_withdraw_{ws.id}_{rid}"):
            act(ws, f"/rules/{api.segment(rid)}/reject", {"note": "withdrawn by owner"}, f"Withdrew draft #{rid}")


def rule_row_html(row: dict, tz: str) -> str:
    status = status_of(row)
    origin = one_line(pick(row, "origin", "source"))
    dates = fmt_short(pick(row, "activated_at", "approved_at", "updated_at", "created_at"), tz)
    return (
        f'<div class="rule-row{" inactive" if status == "retired" else ""}">'
        f'<div class="rule-head"><span class="rule-id">{esc(row.get("id"))}</span>{kind_chip(kind_of(row))}{pill(status)}</div>'
        f'<div class="rule-text">{esc_lines(pick(row, "text", default=""))}</div>'
        f'<div class="rule-meta">{esc(" · ".join(p for p in (("from " + origin) if origin else "", dates) if p and p != "—"))}</div>'
        '</div>'
    )


def render(ws: Workspace) -> None:
    render_composer(ws)
    try:
        body = data.rules(ws.id)
    except api.ApiError as exc:
        st.markdown(empty_state(f"Could not load rules from the {ws.label} hub.", str(exc)), unsafe_allow_html=True)
        return
    precedents, drafts = lists_of(body)
    precedents, drafts = unique_by_id(precedents), unique_by_id(drafts)
    your_turn = [d for d in drafts if status_of(d, "queued") in YOUR_TURN]
    waiting = [d for d in drafts if status_of(d, "queued") in WAITING]
    draft_precedents = [p for p in precedents if status_of(p) == "draft"]
    active = [p for p in precedents if status_of(p) == "active"]
    retired = [p for p in precedents if status_of(p) == "retired"]
    st.caption(f"{len(your_turn) + len(draft_precedents)} for you · {len(waiting)} with the Zenux Rule refiner · "
               f"{len(active)} active")
    if your_turn or draft_precedents:
        st.markdown(f'<div class="rules-section">Your turn · {len(your_turn) + len(draft_precedents)}</div>',
                    unsafe_allow_html=True)
        for draft in your_turn:
            render_proposal_card(ws, draft, is_precedent=False)
        for precedent in draft_precedents:
            render_proposal_card(ws, precedent, is_precedent=True)
    if waiting:
        st.markdown(f'<div class="rules-section">With the refiner · {len(waiting)}</div>', unsafe_allow_html=True)
        for draft in waiting:
            render_waiting_row(ws, draft)
    st.markdown(f'<div class="rules-section">Active rules and worked examples · {len(active)}</div>',
                unsafe_allow_html=True)
    if not active:
        st.markdown(empty_state("No learned rules yet. They sit on top of the firm core, the lane packs and the "
                                "workspace one-pager once you approve them."), unsafe_allow_html=True)
    for row in active:
        text_col, button_col = st.columns([6, 1])
        text_col.markdown(rule_row_html(row, ws.timezone), unsafe_allow_html=True)
        if button_col.button("Retire", key=f"rule_retire_{ws.id}_{row.get('id')}"):
            act(ws, f"/rules/{api.segment(row.get('id'))}/retire", {}, f"Retired {row.get('id')}")
    if retired:
        with st.expander(f"Retired · {len(retired)}"):
            st.markdown('<div class="rules-list">' + "".join(rule_row_html(r, ws.timezone) for r in retired) + "</div>",
                        unsafe_allow_html=True)
    decided = [d for d in drafts if status_of(d, "queued") in ("approved", "rejected")]
    if decided:
        with st.expander(f"Decided drafts · {len(decided)}"):
            st.markdown('<div class="rules-list">' + "".join(
                f'<div class="rule-row"><div class="rule-head"><span class="rule-id">draft #{esc(d.get("id"))}</span>'
                f'{pill(status_of(d))}'
                + (f'<span class="rule-meta" style="margin-top:0">became {esc(d.get("precedent_id"))}</span>' if d.get("precedent_id") else "")
                + (f'<span class="rule-meta" style="margin-top:0">{esc(clip(d.get("decision_note"), 120))}</span>' if d.get("decision_note") else "")
                + '</div><div class="rule-text">'
                f'{esc_lines(pick(proposal_of(d), "text") or pick(d, "owner_text", "text", default=""))}</div></div>'
                for d in decided[:50]) + "</div>", unsafe_allow_html=True)
    if as_list(pick(body, "conflicts")):
        st.warning("Conflicting rules: " + ", ".join(one_line(c) for c in as_list(body.get("conflicts"))[:10]))
