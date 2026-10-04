"""The analyst's status line and the new-briefing check (docs/SPEC-PHASE03-UI.md 1.4, 3.7 and 4.3; the hub routes of
docs/SPEC-PHASE05.md sections 4 and 5).

status_line(ws) draws one plain line at the top of Briefing: "Healthy · last briefing 2h ago · next 12:30 PM ET",
the late text when a scheduled briefing was missed, and a Refresh button. It reads GET /status (cached 60 s), the
hub's light read made for this line: the level from the Control room's own checks limited to what the analyst sees,
the stage, the last and the next briefing and the late text. When the hub gives no next time (it never does while
staging) the line falls back to the default schedule. Never a technical word: the builder sees the reasons in the
Control room.

new_briefing_watch(ws, shown_latest_id) is a small fragment with no inputs that checks every two minutes whether a
newer briefing exists than the one at the top of the page (GET /editions/latest: the id only, no items) and, if so,
offers "Show it". It never reruns the page by itself, so an open dialog or half-typed text is never touched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

import streamlit as st

from . import data, labels, links
from .api import ApiError
from .config import Workspace
from .fmt import (DEFAULT_GRADER_TIMES, MIN_TIME, UTC, dicts, esc, fmt_clock, next_slot, one_line, parse_time, pick,
                  relative_time, zone)

NEW_BRIEFING_SECONDS = 120
LATE_CODE = "briefing_late"
STAGING_CODE = "awaiting_signoff"
LEVELS = ("green", "amber", "red")
WORKING = "the editor is preparing your next briefing"


def _block(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _next_text(next_at: datetime | None, tz: str, now: datetime) -> str | None:
    if next_at is None:
        return None
    tzinfo = zone(tz)
    days = (next_at.astimezone(tzinfo).date() - now.astimezone(tzinfo).date()).days
    clock = fmt_clock(next_at, tz)
    if days <= 0:
        return f"next {clock}"
    if days == 1:
        return f"next {clock} tomorrow"
    local = next_at.astimezone(tzinfo)
    return f"next {local:%a} {clock}"


def summary(ws: Workspace, *, now: datetime | None = None) -> dict:
    """{level: green|amber|red|staging|unreachable|unknown, text, last_at, next_at, late, late_text}.

    From GET /status: level (staging when the stage is staging or a reason is awaiting_signoff), unreachable when the
    hub cannot be reached, unknown for any other failure. last_at: the last briefing's time; next_at: the hub's
    next_briefing_at, else the next slot of the default schedule (07:30, 12:30, 16:30) in the hub's time zone. late:
    a red briefing_late reason; late_text the hub's sentence ("The 12:30 PM ET briefing is late.")."""
    clock = parse_time(now or datetime.now(UTC))
    out: dict[str, Any] = {"level": "unknown", "text": labels.STATUS_TEXT["unknown"], "last_at": None,
                           "next_at": None, "late": False, "late_text": None}
    try:
        body = data.status(ws.id)
    except ApiError as exc:
        level = "unreachable" if exc.kind == "unreachable" else "unknown"
        out.update(level=level, text=labels.STATUS_TEXT[level])
        return out
    body = _block(body)
    level = one_line(body.get("level")) if body.get("level") in LEVELS else "unknown"
    reasons = dicts(body.get("reasons"))
    codes = {one_line(r.get("code")) for r in reasons} | {one_line(body.get("code"))}
    staging = one_line(body.get("stage")).lower() == "staging" or STAGING_CODE in codes
    schedule_tz = one_line(body.get("timezone")) or ws.timezone
    last = parse_time(pick(body, "last_briefing.published_at"))
    due = parse_time(body.get("next_briefing_at"))
    if not staging and (due == MIN_TIME or due <= clock):
        due = next_slot(list(DEFAULT_GRADER_TIMES), schedule_tz, clock) or MIN_TIME
    late = body.get("late") is True or any(r.get("level") == "red" and r.get("code") == LATE_CODE for r in reasons)
    late_text = None
    if late:
        hub_text = one_line(body.get("late_text")) or next(
            (one_line(r.get("text")) for r in reasons if r.get("code") == LATE_CODE), "")
        late_text = hub_text or "The latest briefing is late."
    out.update(level="staging" if staging else level,
               last_at=None if last == MIN_TIME else last,
               next_at=None if staging or due == MIN_TIME else due,
               late=late, late_text=late_text)
    if staging:
        out["text"] = labels.STATUS_TEXT["staging"]
        return out
    parts = [labels.STATUS_TEXT.get(level, labels.STATUS_TEXT["unknown"])]
    if out["last_at"] is not None:
        parts.append(f"last briefing {relative_time(out['last_at'], clock)}")
    next_part = _next_text(out["next_at"], ws.timezone, clock)
    if next_part:
        parts.append(next_part)
    hint = status_hint(level, codes, late, working=body.get("editor_working") is True)
    if hint:
        parts.append(hint)
    out["text"] = " · ".join(parts)
    return out


def status_hint(level: str, codes: set[str], late: bool, *, working: bool = False) -> str:
    """Why amber or red, in words the analyst can act on (there are no alerts): amber with sources not responding
    points to Coverage, other amber says it is minor; red says what to expect and when to tell the builder (when a
    briefing is late, the late text already says so); green while the editor holds a run says so."""
    if level == "amber":
        if labels.EDITOR_STOPPED_CODE in codes:
            return labels.STATUS_HINTS["editor_stopped"]
        if codes & set(labels.SOURCE_REASON_CODES):
            return labels.STATUS_HINTS["sources"]
        return labels.STATUS_HINTS["amber"]
    if level == "red" and not late:
        return labels.STATUS_HINTS["red"]
    if level == "green" and working:
        return WORKING
    return ""


def status_line(ws: Workspace) -> None:
    """One line at the top of Briefing: a coloured dot, the plain status, the late text, and Refresh (or "Review and
    sign off" while staging, "Try again" while ZENUX cannot be reached)."""
    s = summary(ws)
    level = s["level"]
    late = f'<span class="zx-status-late">{esc(s["late_text"])}</span>' if s.get("late_text") else ""
    with st.container(key="zx_status", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f'<div class="zx-status zx-status-{esc(level)}"><span class="zx-dot"></span>'
                    f'<span>{esc(s["text"])}</span>{late}</div>', unsafe_allow_html=True)
        signoff = st.button("Review and sign off", key="zx_status_signoff", type="tertiary") \
            if level == "staging" else False
        refresh = st.button("Try again" if level == "unreachable" else "Refresh", key="zx_refresh_status",
                            type="tertiary", icon=":material/refresh:")
    if signoff:
        links.go("preferences", section="looks_for")
    if refresh:
        data.clear_reads()
        st.rerun()


@st.fragment(run_every=NEW_BRIEFING_SECONDS)
def new_briefing_watch(ws: Workspace, shown_latest_id: int | None) -> None:
    """Every two minutes: "A new briefing is ready." with Show it, when a newer briefing exists than the one shown."""
    try:
        latest = data.latest_edition_id(ws.id)
    except ApiError:
        return
    if latest is None or (shown_latest_id is not None and latest <= shown_latest_id):
        return
    with st.container(key="zx_new_briefing", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown('<div class="zx-new-briefing">A new briefing is ready.</div>', unsafe_allow_html=True)
        show = st.button("Show it", key="zx_show_new_briefing", type="primary")
    if show:
        data.clear_reads()
        st.rerun(scope="app")
