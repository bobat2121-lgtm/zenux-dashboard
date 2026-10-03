"""Owner grade form shared by the Feed and Rejected tabs: POST /feedback (bearer OWNER_TOKEN via the PIN).

A grade is a verdict on the firm-core scale (lead 90+, digest 70-89, watch 40-69, reject under 40) or factual_error
(the published text misstates its sources), an optional exact score (its band then decides the verdict, except for
factual_error), an optional note, and a scope. The target is an edition item (item_id, else edition_id + item_rank)
or a graded event (event_id), as the hub's POST /feedback expects. Scopes:

- item: just a grade; it teaches the Grader and the calibration
- case: a worked example the Grader follows for similar stories (it guides, never binds)
- rule: a standing principle; the Zenux Rule refiner drafts it and the owner approves it on the Rules tab
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from . import api, data, owner
from .config import Workspace
from .fmt import esc

PRESETS = {"Lead": ("lead", 92), "Digest": ("digest", 78), "Watch": ("watch", 55), "Reject": ("reject", 20),
           "Factual error": ("factual_error", None)}
DEFAULT_PRESET = "Digest"
BANDS = (("lead", 90, 100), ("digest", 70, 89), ("watch", 40, 69), ("reject", 0, 39))
SAVE_AS = {"Just a grade": "item", "Worked example": "case", "Rule": "rule"}
MIN_RULING = 20
SCALE_HELP = " · ".join(f"{lo}–{hi} {name}" for name, lo, hi in BANDS) + " · factual error: the text misstates a source"


def feedback_chips(rows: Any) -> str:
    """The owner's earlier grades on an item or event, newest last, as small chips (at most 3)."""
    from .fmt import chip, dicts, one_line

    out = []
    for f in dicts(rows)[-3:]:
        verdict = one_line(f.get("verdict")).replace("_", " ")
        score = f.get("score")
        out.append(chip(f"your grade: {verdict}{f' {score}' if score is not None else ''}", "grade"))
    return "".join(out)


def verdict_for_score(score: int) -> str:
    for name, lo, hi in BANDS:
        if lo <= score <= hi:
            return name
    return "watch"


def build_payload(option: dict, preset: str, exact: Any, note: str, save_as: str) -> dict:
    verdict, _ = PRESETS.get(preset, PRESETS[DEFAULT_PRESET])
    payload: dict[str, Any] = {}
    if option.get("item_id") is not None:
        payload["item_id"] = option["item_id"]
    elif option.get("edition_id") is not None and option.get("item_rank") is not None:
        payload["edition_id"] = option["edition_id"]
        payload["item_rank"] = option["item_rank"]
    if option.get("event_id") is not None:
        payload["event_id"] = option["event_id"]
    if exact is not None:
        score = max(0, min(100, int(exact)))
        payload["score"] = score
        if verdict != "factual_error":
            verdict = verdict_for_score(score)
    payload["verdict"] = verdict
    payload["scope"] = SAVE_AS.get(save_as, "item")
    payload["note"] = (note or "").strip()
    return payload


def grade_form(ws: Workspace, key: str, options: list[dict], title: str) -> None:
    """One grade at a time for the chosen option. options: [{key, label, item_id?, edition_id?, item_rank?, event_id?}]."""
    by_id = {str(o["key"]): o for o in options if o.get("key") is not None}
    if not by_id:
        st.caption("Nothing here can be graded: no item carries an event id.")
        return
    with st.container(key=f"zx_grade_{key}"):  # its own block, so the page can style it as a card
        st.markdown(f'<div class="digest-grading-title">{esc(title)}</div>', unsafe_allow_html=True)
        if owner.lock_state(ws) != owner.UNLOCKED:
            st.caption(owner.lock_message(ws, owner.lock_state(ws)))
        st.selectbox("Item", list(by_id), format_func=lambda k: by_id[k]["label"] if k in by_id else str(k),
                     key=f"gitem_{key}")
        st.radio("Grade", list(PRESETS), index=list(PRESETS).index(DEFAULT_PRESET), horizontal=True,
                 key=f"ggrade_{key}", help=SCALE_HELP)
        exact_col, scope_col = st.columns([1, 2])
        exact_col.number_input("Exact score (optional)", min_value=0, max_value=100, step=1, value=None,
                               key=f"gscore_{key}", help=SCALE_HELP)
        scope_col.radio("Save as", list(SAVE_AS), horizontal=True, key=f"gscope_{key}",
                        help="Just a grade teaches the Grader. A worked example guides similar stories. "
                             "A rule becomes a draft for the Zenux Rule refiner; you approve it on the Rules tab.")
        st.text_area("Your ruling (optional for a grade)", key=f"gnote_{key}", height=80,
                     placeholder="Say what the Grader should learn from this, in your own words.")
        if st.form_submit_button("Submit grade", type="primary", key=f"gsubmit_{key}"):
            submit(ws, key, by_id)


def submit(ws: Workspace, key: str, by_id: dict[str, dict]) -> bool:
    token = owner.require_owner(ws)
    if not token:
        return False
    option = by_id.get(str(st.session_state.get(f"gitem_{key}")))
    if not option:
        st.info("Choose an item to grade.")
        return False
    payload = build_payload(
        option,
        st.session_state.get(f"ggrade_{key}") or DEFAULT_PRESET,
        st.session_state.get(f"gscore_{key}"),
        str(st.session_state.get(f"gnote_{key}") or ""),
        st.session_state.get(f"gscope_{key}") or "Just a grade",
    )
    if payload["scope"] in ("rule", "case") and len(payload["note"]) < MIN_RULING:
        noun = "a rule" if payload["scope"] == "rule" else "a worked example"
        st.info(f"To save {noun}, write your ruling ({MIN_RULING} characters or more), or save it as just a grade.")
        return False
    try:
        result = api.hub_post(ws, "/feedback", payload, token)
    except api.ApiError as exc:
        st.error(f"The grade was not stored: {exc}")
        return False
    stored = result.get("id") if isinstance(result, dict) else None
    draft = result.get("draft_id") if isinstance(result, dict) else None
    data.clear_reads()
    flash("success", f"Grade stored{f' #{stored}' if stored is not None else ''} · {payload['verdict'].replace('_', ' ')}"
          + (f" {payload['score']}" if "score" in payload else "")
          + (f" · draft #{draft} queued for the Zenux Rule refiner" if draft
             else " · sent to the Rule refiner" if payload["scope"] in ("rule", "case") else ""))
    return True


def flash(kind: str, message: str) -> None:
    """Show a message after a full rerun, so every list on the page reflects the change."""
    st.session_state["zx_flash"] = (kind, message)
    st.rerun()


def show_flash() -> None:
    entry = st.session_state.pop("zx_flash", None)
    if isinstance(entry, tuple) and len(entry) == 2:
        kind, message = entry
        {"success": st.success, "warning": st.warning}.get(kind, st.info)(message)
