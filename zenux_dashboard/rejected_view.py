"""Rejected: graded events that did not make an edition (GET /rejected?days=N).

Each row is one decision: rejected, duplicate or already_covered (or a watch-band score), with the score, tier,
reason code, rationale and, for a duplicate, the canonical event it points to. The owner can grade any row.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from . import api, data, grading
from .config import Workspace
from .fmt import (as_int, clip, dicts, domain_of, empty_state, esc, fmt_time, label_of, link, one_line, parse_time,
                  pick, plural)

WINDOWS = [1, 3, 7, 14]
DEFAULT_WINDOW = 3
PAGE_SIZE = 50
ALL = "All"


def rows_of(body: Any) -> list[dict]:
    if isinstance(body, list):
        return dicts(body)
    return dicts(pick(body, "items", "rejected", "decisions", default=[]))


def event_id_of(row: dict) -> Any:
    return pick(row, "event_id", "id")


def module_of(row: dict) -> str:
    return one_line(pick(row, "module", "module_id", "source.module"))


def decision_of(row: dict) -> str:
    return one_line(pick(row, "decision", "status")) or "rejected"


def row_time(row: dict) -> Any:
    return pick(row, "decided_at", "published_at", "observed_at", "received_at", "created_at")


def chips_html(row: dict) -> str:
    chips = [(label_of(decision_of(row)), "decision")]
    tier = pick(row, "tier")
    if one_line(tier):
        chips.append((f"tier {label_of(tier)}", ""))
    score = as_int(row.get("score"))
    if score is not None:
        chips.append((f"score {score}", "score"))
    reason = pick(row, "reason_code", "reason")
    if one_line(reason):
        chips.append((label_of(reason), ""))
    canonical = pick(row, "canonical_event_id")
    if canonical is not None and str(canonical) != str(event_id_of(row)):
        chips.append((f"same event as #{canonical}", ""))
    lane = pick(row, "lane", "source.lane")
    if one_line(lane):
        chips.append((label_of(lane), ""))
    inner = "".join(f'<span class="rejected-chip {css}">{esc(text)}</span>' for text, css in chips if text)
    return f'<div class="rejected-signals">{inner}</div>' if inner else ""


def row_html(row: dict, tz: str) -> str:
    eid = event_id_of(row)
    url = pick(row, "url", "canonical_url")
    source = one_line(pick(row, "source_key", "source.key"))
    meta = " · ".join(p for p in (module_of(row), source, fmt_time(row_time(row), tz)) if p)
    rationale = one_line(pick(row, "rationale", "why"))
    rationale_html = (f'<div class="rejected-rationale"><strong>Grader rationale</strong> · {esc(rationale)}</div>'
                      if rationale else "")
    source_link = link(url, f"{domain_of(url) or 'source'} ↗")
    return (
        '<article class="rejected-item">'
        f'<div class="rejected-id">#{esc(eid if eid is not None else "–")}</div>'
        '<div>'
        f'<div class="rejected-title">{esc(one_line(pick(row, "title", "headline")) or "(untitled event)")}</div>'
        f'<div class="rejected-meta">{esc(meta)}</div>'
        f'{chips_html(row)}{rationale_html}'
        f'<div class="rejected-links">{source_link}{grading.feedback_chips(row.get("feedback"))}</div>'
        '</div></article>'
    )


def render(ws: Workspace) -> None:
    window_col, module_col, decision_col, page_col = st.columns([1, 1.3, 1.3, 1])
    with window_col:
        days = st.selectbox("Window", WINDOWS, index=WINDOWS.index(DEFAULT_WINDOW), key=f"rej_days_{ws.id}",
                            format_func=lambda d: plural(d, "day"))
    try:
        body = data.rejected(ws.id, int(days))
    except api.ApiError as exc:
        st.markdown(empty_state(f"Could not load rejected events from the {ws.label} hub.", str(exc)),
                    unsafe_allow_html=True)
        return
    rows = sorted(rows_of(body), key=lambda r: parse_time(row_time(r)), reverse=True)
    modules = sorted({module_of(r) for r in rows if module_of(r)})
    decisions = sorted({decision_of(r) for r in rows})
    with module_col:
        module = st.selectbox("Module", [ALL] + modules, key=f"rej_module_{ws.id}")
    with decision_col:
        decision = st.selectbox("Decision", [ALL] + decisions, key=f"rej_decision_{ws.id}", format_func=label_of)
    if module != ALL:
        rows = [r for r in rows if module_of(r) == module]
    if decision != ALL:
        rows = [r for r in rows if decision_of(r) == decision]
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    with page_col:
        page = st.selectbox("Page", list(range(1, pages + 1)), key=f"rej_page_{ws.id}_{days}_{module}_{decision}",
                            format_func=lambda p: f"{p} of {pages}")
    start = (int(page) - 1) * PAGE_SIZE
    page_rows = rows[start:start + PAGE_SIZE]
    total = as_int(pick(body, "total")) if module == ALL and decision == ALL else None
    count_text = f"{total} total" if total is not None else f"{len(rows)} loaded"
    st.markdown(
        f'<div class="rejected-summary">Showing {start + 1 if page_rows else 0}–{start + len(page_rows)} of '
        f'{esc(count_text)} · newest first · last {esc(plural(int(days), "day"))}</div>',
        unsafe_allow_html=True,
    )
    if not page_rows:
        st.markdown(empty_state("Nothing rejected in this window."), unsafe_allow_html=True)
        return
    if st.session_state.get("grading_enabled"):
        options = [{
            "key": f"event-{event_id_of(r)}",
            "label": f"#{event_id_of(r)} · {clip(pick(r, 'title', 'headline', default=''), 80)}",
            "event_id": as_int(event_id_of(r)),
        } for r in page_rows if as_int(event_id_of(r)) is not None]
        with st.form(f"grade_rejected_{ws.id}", border=True):
            grading.grade_form(ws, f"rej_{ws.id}", options, "Grade a rejected event")
    st.markdown(f'<div class="rejected-feed">{"".join(row_html(r, ws.timezone) for r in page_rows)}</div>',
                unsafe_allow_html=True)
