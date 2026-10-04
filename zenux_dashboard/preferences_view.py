"""My preferences: everything the analyst tunes, in one tab (docs/SPEC-PHASE03-UI.md section 7).

Six sections behind one segmented control (`pf_section`, mirrored as `section` in the page link):

    ok          Needs your OK: suggested wordings, suggestions from the analyst's ratings, merges and brief or coverage
                suggestions (GET /preferences `suggestions`, plus legacy proposed drafts from GET /rules), each with its
                14-day preview and the stories it moves (`preview_items`). Approve: POST /rules/<draft>/approve
                {proposed_at, text?, retire?, as_new?}; Not now: POST /rules/<draft>/reject {}, with Undo (POST
                /rules/<draft>/reopen).
    active      Active and paused preferences with what they did (GET /preferences), the Add form (POST /preferences
                {direction, scope: "standing", text, expires_at?}), and Pause, Resume, Edit, End date, Remove and
                Bring back (POST /rules/<id>/<pause|resume|edit|end-date|retire|reactivate>).
    looks_for   What ZENUX looks for and the sign-off (brief_view.render_brief).
    muted       Mutes (GET /mutes?all=1) with Unmute and Bring back, through the card actions (actions.py).
    watchlist   Stars (GET /stars) with Remove (actions.unstar).
    how_much    The "how much" dial: GET /settings, GET /settings/volume/preview, POST /settings/volume.

Every write goes through ui.write: the owner token from the PIN, a toast that says when the change takes effect (from
the answer's `effective`), and an undo where the hub has an inverse route. An approval names the proposal shown
(`proposed_at`); a 409 proposal_changed, merge_outdated or target_retired is answered on the card in plain words
instead of as an error (brief_view.write_or_handle). Each section reads only what it needs, so one failing route never
blanks the others; the section labels carry counts from the reads that worked.

The analyst never sees an id, a source key or a module id here: the hub sends plain words beside every stored text
(`plain_text`, `proposal_plain`, `replaces_detail`, `soft_cap.warning`, `with_assistant`; docs/SPEC-PHASE05.md 3.2);
labels.preference_text keeps the analyst's own words of a preference (without the lead the chip says and the example
the card shows on its own line), labels.clean_rationale stays the last guard on reasoning, and the end reason, scope
and direction go through their plain labels.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

import streamlit as st

from . import actions, api, brief_view, data, labels, links, owner, ui
from .config import Workspace, load_config
from .fmt import (MIN_TIME, UTC, as_int, as_list, chip, clip, dicts, empty_state, esc, fmt_date, one_line, md_label,
                  parse_time, pick, plural, relative_time, unique_by_id, zone)

SECTION_KEY = "pf_section"
SECTIONS: tuple[str, ...] = tuple(links.PREFERENCE_SECTIONS)  # ok, active, looks_for, muted, watchlist, how_much
SECTION_NAMES = {"ok": "Needs your OK", "active": "Active", "looks_for": "What ZENUX looks for", "muted": "Muted",
                 "watchlist": "Watchlist", "how_much": "How much"}
COUNTED = ("ok", "active", "muted", "watchlist")

NOTICE_KEY = "pf_notice"          # a plain warning for the top of Needs your OK, after a 409 re-read
AS_NEW_KEY = "pf_as_new"          # {draft id: the hub's sentence}: suggestions whose preference has ended
ENDED_KEY = "pf_ended"            # the lazy "Ended preferences" expander
ENDED_FOCUS_KEY = "pf_ended_focus"
REMOVED_MUTES_KEY = "pf_removed_mutes"
VOLUME_MODE_KEY = "pf_volume_mode"
VOLUME_SHELF_KEY = "pf_volume_shelf"
VOLUME_SEEN_KEY = "pf_volume_seen"

DIRECTIONS = ("more", "less", "exact")
SCOPES = ("this_story", "similar", "standing")
LIVE = ("active", "paused")
TEXT_MIN = 10
ADD_TEXT_MAX = 500
EDIT_TEXT_MAX = 2000
UNTIL_DEFAULT_DAYS = 30
UNTIL_MAX_DAYS = 366
GRADE_LINES = 5
ENDED_MAX = 100
VOLUME_ORDER = ("top", "standard", "broad")

# ---------------------------------------------------------------------------------------------- copy (spec 7)

SUMMARY_NONE = "Your preferences haven't changed anything this week."
EMPTY_OK = ("Nothing needs your OK. Suggestions from your ratings and clearer wordings for your preferences appear "
            "here.")
EMPTY_ACTIVE = "No preferences yet. Use More like this or Less like this on any story, or add one above."
EMPTY_MUTED = "Nothing muted. Use Mute on any story, or Mute on a source or company in Coverage."
EMPTY_WATCHLIST = "No companies on your watchlist. Use Star on a story or in Coverage."
MUTED_CAPTION = ("Muted sources, companies and stories are still collected, kept out of your briefing. Find what they "
                 "hid under Filtered out › Muted.")
PROPOSAL_CHANGED = ("The wording assistant changed this suggestion after the page loaded, so nothing was approved. "
                    "Look at it again below.")
MERGE_OUTDATED = ("One of these preferences changed meanwhile, so nothing was merged. The list has been reloaded.")
MERGE_STALE = ("One of these preferences has changed since this merge was suggested, so it can't be merged. Keep them "
               "separate; the wording assistant suggests a fresh merge next month.")
TARGET_RETIRED = "The preference this wording was for has ended. Approve it as a new preference instead."
PAUSED_TOAST = "Paused. The editor ignores it from the next briefing until you resume it."
REMOVE_TITLE = "Remove this preference?"
REMOVE_MESSAGE = ("The editor stops using it from the next briefing. You can bring it back from Ended preferences.")
TOO_SHORT = f"Write at least {TEXT_MIN} characters so the editor knows what you mean."
EMPTY_WORDING = "The wording is empty. Write it, or reload the page to see the suggestion again."
NOTHING_CHANGED = "Nothing changed."
WORDING_LABEL = "Wording (edit before approving if you like)"
VOLUME_CAPTION = ("This changes how many stories make the briefing, never how stories are scored or what is "
                  "collected.")
VOLUME_CURRENT = "This is your current setting."
VOLUME_NO_PREVIEW = "No briefings in the last 7 days to compare."
ADD_PLACEHOLDER = "e.g. Less coverage of bitcoin price moves unless a miner announces AI hosting"

SUGGESTION_HEADS = {
    "grades": "Suggested from your ratings",
    "preference": "Suggested wording for your preference",
    "brief": "Your suggested change to What ZENUX looks for",
    "radar": "From a coverage request",
}
LEGACY_HEAD = "Your draft, worded by the wording assistant"
BUTTONS = {"preference": ("Use this wording", "Keep mine"), "consolidation": ("Merge them", "Keep them separate")}
DEFAULT_BUTTONS = ("Approve", "Not now")
WAITING_ORIGINS = ("brief", "owner", "feedback")  # drafts the analyst sent that wait for the wording assistant
DECISION_WORDS = {"selected": "in the briefing", "rejected": "left out", "duplicate": "same story",
                  "already_covered": "already reported"}
ENDED_REASONS = {
    "owner": "You removed it",
    "undone": "Undone",
    "superseded": "Replaced by a newer wording",
    "conflict": "Ended by a newer preference",
    "consolidated": "Merged into another preference",
    "expired": "Its end date passed",
}
MUTE_GROUPS = (("source", "Sources"), ("entity", "Companies"), ("story", "Stories"))


# ---------------------------------------------------------------------------------------------- pure helpers


def attempt(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, api.ApiError | None]:
    """(body, None) or (None, the ApiError): one failing read never stops the other sections."""
    try:
        return fn(*args, **kwargs), None
    except api.ApiError as exc:
        return None, exc


def status_of(row: Mapping, default: str = "active") -> str:
    return one_line(pick(row, "status", "state")).lower() or default


def origin_of(row: Mapping) -> str:
    return one_line(pick(row, "origin", "source")).lower()


def proposal_of(draft: Mapping) -> dict:
    proposal = draft.get("proposal")
    if isinstance(proposal, Mapping):
        return dict(proposal)
    if isinstance(proposal, str) and proposal.strip():
        return {"text": proposal}
    return {}


def proposal_text(draft: Mapping) -> str:
    return str(pick(proposal_of(draft), "text") or draft.get("text") or "").strip()


def shown_text(draft: Mapping) -> str:
    """The proposal as the card shows and lets the analyst edit it: the hub's plain words (`proposal_plain.text`,
    preference ids turned into their words), else the stored text."""
    plain = draft.get("proposal_plain")
    text = str(plain.get("text") or "").strip() if isinstance(plain, Mapping) else ""
    return text or proposal_text(draft)


def shown_rationale(draft: Mapping, by_id: Mapping[str, Mapping]) -> str:
    """The wording assistant's reasoning in plain words (`proposal_plain.rationale`), guarded by clean_rationale (which
    also names a cited preference by its words when an older hub sends ids)."""
    plain = draft.get("proposal_plain")
    text = plain.get("rationale") if isinstance(plain, Mapping) and one_line(plain.get("rationale")) else None
    return labels.clean_rationale(text or proposal_of(draft).get("rationale"),
                                  {pid: labels.preference_text(pref) for pid, pref in by_id.items()})


def drafts_of(rules_body: Any) -> list[dict]:
    """GET /rules drafts ({drafts|rule_drafts}), first occurrence of each id."""
    return unique_by_id(dicts(pick(rules_body, "drafts", "rule_drafts", default=[])))


def preference_rows(prefs_body: Any) -> list[dict]:
    return unique_by_id(dicts(pick(prefs_body, "preferences", default=[])))


def preferences_by_id(prefs_body: Any) -> dict[str, dict]:
    return {one_line(p.get("id")): p for p in preference_rows(prefs_body)}


def live_preferences(prefs_body: Any) -> list[dict]:
    """Active and paused preferences, in the hub's order (newest first)."""
    return [p for p in preference_rows(prefs_body) if status_of(p) in LIVE]


def ended_preferences(prefs_body: Any) -> list[dict]:
    """Ended (retired) preferences, most recently ended first."""
    ended = [p for p in preference_rows(prefs_body) if status_of(p) == "retired"]
    return sorted(ended, key=lambda p: parse_time(pick(p, "retired_at", "created_at")), reverse=True)


def needs_ok(prefs_body: Any, rules_body: Any) -> list[dict]:
    """GET /preferences suggestions plus the legacy proposed drafts of GET /rules that are not among them, newest
    first (by when the proposal arrived, then by id)."""
    suggestions = [d for d in unique_by_id(dicts(pick(prefs_body, "suggestions", default=[])))
                   if status_of(d, "proposed") == "proposed"]
    seen = {one_line(d.get("id")) for d in suggestions}
    legacy = [d for d in drafts_of(rules_body)
              if status_of(d, "queued") == "proposed" and one_line(d.get("id")) not in seen]
    cards = suggestions + legacy
    return sorted(cards, key=lambda d: (parse_time(pick(d, "proposed_at", "updated_at", "created_at")),
                                        as_int(d.get("id")) or 0), reverse=True)


def waiting_count(prefs_body: Any) -> int:
    """How many drafts the analyst sent (brief suggestions, own drafts, ratings) wait for the wording assistant: GET
    /preferences `with_assistant.by_origin` (gap 29)."""
    by_origin = pick(prefs_body, "with_assistant.by_origin")
    if not isinstance(by_origin, Mapping):
        return 0
    return sum(max(as_int(by_origin.get(origin)) or 0, 0) for origin in WAITING_ORIGINS)


def active_mutes(body: Any) -> list[dict]:
    return [m for m in unique_by_id(dicts(pick(body, "mutes", default=[])))
            if m.get("active") is not False and not m.get("removed_at")]


def removed_mutes(body: Any) -> list[dict]:
    active = {one_line(m.get("id")) for m in active_mutes(body)}
    rows = [m for m in unique_by_id(dicts(pick(body, "mutes", default=[]))) if one_line(m.get("id")) not in active]
    return sorted(rows, key=lambda m: parse_time(pick(m, "removed_at", "created_at")), reverse=True)


def active_stars(body: Any) -> list[dict]:
    return [s for s in unique_by_id(dicts(pick(body, "stars", default=[])))
            if s.get("active") is not False and not s.get("removed_at")]


def default_section(counts: Mapping[str, int | None]) -> str:
    """Needs your OK when it has something, else Active."""
    return "ok" if counts.get("ok") else "active"


def section_label(slug: str, counts: Mapping[str, int | None]) -> str:
    name = SECTION_NAMES.get(slug, slug)
    n = counts.get(slug)
    return f"{name} · {n}" if slug in COUNTED and n is not None else name


def summary_sentence(summary: Any) -> str:
    """'This week your preferences changed 23 decisions: 4 brought into a briefing, 15 kept out, 3 raised, 1 lowered.'
    Parts with 0 are dropped; nothing at all: SUMMARY_NONE."""
    hits = as_int(pick(summary, "hits")) or 0
    if hits <= 0:
        return SUMMARY_NONE
    parts = [(as_int(pick(summary, key)) or 0, words) for key, words in (
        ("promoted", "brought into a briefing"), ("suppressed", "kept out"), ("raised", "raised"),
        ("lowered", "lowered"))]
    detail = ", ".join(f"{n} {words}" for n, words in parts if n > 0)
    head = f"This week your preferences changed {plural(hits, 'decision')}"
    return f"{head}: {detail}." if detail else f"{head}."


def stats_line(pref: Mapping, now: datetime | None = None) -> str:
    """What a preference did in 30 days, read by its direction (SPEC-PHASE02 section 12): a `more` preference raises
    (some made the briefing), a `less` one lowers (some were kept out), an `exact` or legacy one brought in and kept
    out. Never the word "suppressed"."""
    stats = pref.get("stats") if isinstance(pref.get("stats"), Mapping) else {}

    def n(key: str) -> int:
        return max(as_int(stats.get(key)) or 0, 0)

    direction = one_line(pref.get("direction")).lower()
    if direction == "more":
        effect = (f"Raised {plural(n('promoted_30d') + n('raised_under_bar_30d'), 'story', 'stories')} in 30 days "
                  f"({n('promoted_30d')} made the briefing)")
    elif direction == "less":
        effect = (f"Lowered {plural(n('suppressed_30d') + n('lowered_in_briefing_30d'), 'story', 'stories')} in 30 "
                  f"days ({n('suppressed_30d')} kept out)")
    else:
        effect = f"Brought in {n('promoted_30d')} · kept out {n('suppressed_30d')} in 30 days"
    last = stats.get("last_hit_at")
    used = f"last used {relative_time(last, now)}" if parse_time(last) != MIN_TIME else "not used yet"
    return f"{effect} · {used}"


def status_text(pref: Mapping, tz: str) -> str:
    if status_of(pref) == "paused":
        since = fmt_date(pref.get("paused_at"), tz) if pref.get("paused_at") else ""
        return f"Paused since {since}" if since and since != "—" else "Paused"
    return labels.STATUS_LABELS.get(status_of(pref), "Active")


def head_meta(pref: Mapping, tz: str) -> str:
    """'Stories like this · Active · until Nov 3'."""
    parts = [labels.scope_label(pref.get("scope")), status_text(pref, tz)]
    if pref.get("expires_at"):
        parts.append(f"until {fmt_date(pref.get('expires_at'), tz)}")
    return " · ".join(p for p in parts if p)


def example_line(pref: Mapping) -> str:
    example = pref.get("example")
    title = one_line(pick(example, "title"))
    if not title:
        return ""
    source = one_line(pick(example, "source_label"))
    return f"Example: {title} ({source})" if source else f"Example: {title}"


def looks_like_mute_text(mute: Mapping) -> str:
    share = pick(mute, "share")
    try:
        pct = round(float(share) * 100)
    except (TypeError, ValueError):
        pct = None
    label = one_line(pick(mute, "label", "ref"))
    lead = f"{pct}% of what it kept out" if pct is not None else "Most of what it kept out"
    return f"{lead} came from {label}. Mute it instead?"


def mostly_kept_out(stats: Any) -> str:
    names = [one_line(pick(s, "label", "source_key")) for s in dicts(pick(stats, "top_suppressed_sources", default=[]))]
    names += [one_line(pick(c, "name", "entity_id")) for c in dicts(pick(stats, "top_suppressed_companies", default=[]))]
    return ", ".join(n for n in names if n)


def ended_reason(pref: Mapping) -> str:
    return ENDED_REASONS.get(one_line(pref.get("retired_reason")).lower(), "Ended")


def needs_new_end_date(pref: Mapping, now: datetime | None = None) -> bool:
    """Bringing it back needs a new end date (or none): it expired, or its end date has passed since."""
    if one_line(pref.get("retired_reason")).lower() == "expired":
        return True
    expires = parse_time(pref.get("expires_at"))
    return expires != MIN_TIME and expires <= (now or datetime.now(UTC))


def suggestion_head(draft: Mapping) -> str:
    origin = origin_of(draft)
    if origin == "consolidation":
        return f"Suggested merge of {plural(len(replaces_of(draft)), 'preference')}"
    return SUGGESTION_HEADS.get(origin, LEGACY_HEAD)


def replaces_of(draft: Mapping) -> list[str]:
    return [one_line(x) for x in as_list(pick(proposal_of(draft), "replaces", default=[])) if one_line(x)]


def conflicts_of(draft: Mapping) -> list[str]:
    return [one_line(x) for x in as_list(pick(proposal_of(draft), "conflicts", default=[])) if one_line(x)]


def merge_is_stale(draft: Mapping, by_id: Mapping[str, Mapping]) -> bool:
    """A merge one of whose preferences has ended (or changed) since it was suggested, so the hub would refuse it:
    the hub's `outdated` (gap 28), else worked out from the preferences loaded."""
    if origin_of(draft) != "consolidation":
        return False
    if isinstance(draft.get("outdated"), bool):
        return draft["outdated"]
    return any(rid not in by_id or status_of(by_id[rid]) not in LIVE for rid in replaces_of(draft))


def replaced_lines(draft: Mapping, by_id: Mapping[str, Mapping]) -> list[str]:
    """The preferences a merge replaces, in their words, "(ended)" on those that have ended: the hub's
    `replaces_detail`, else the preferences loaded."""
    detail = dicts(draft.get("replaces_detail"))
    if detail:
        return [labels.preference_text(r) + (" (ended)" if r.get("ended") is True else "")
                for r in detail if one_line(r.get("plain_text")) or one_line(r.get("text"))]
    return [labels.preference_text(by_id[rid]) + ("" if status_of(by_id[rid]) in LIVE else " (ended)")
            for rid in replaces_of(draft) if rid in by_id]


def button_labels(draft: Mapping) -> tuple[str, str]:
    return BUTTONS.get(origin_of(draft), DEFAULT_BUTTONS)


def grade_lines(draft: Mapping) -> tuple[list[str], int]:
    """Up to GRADE_LINES '<title> · you: <rating> · editor: <score or decision>' lines, and how many more."""
    context = draft.get("context")
    grades = dicts(context.get("grades")) if isinstance(context, Mapping) else []
    lines = []
    for grade in grades[:GRADE_LINES]:
        title = clip(pick(grade, "title", default="") or "A story", 120)
        verdict = one_line(grade.get("verdict")).lower()
        you = labels.VERDICT_LABELS.get(verdict) or one_line(verdict).replace("_", " ") or "?"
        score = as_int(grade.get("grader_score"))
        decision = one_line(grade.get("grader_decision")).lower()
        editor = str(score) if score is not None else DECISION_WORDS.get(decision, "not rated")
        lines.append(f"{title} · you: {you} · editor: {editor}")
    return lines, max(len(grades) - len(lines), 0)


def preview_counts(draft: Mapping) -> tuple[int, int, int] | None:
    """(added, removed, window days) from the proposal's preview_summary, or None when it has no preview."""
    summary = draft.get("preview_summary")
    if not isinstance(summary, Mapping):
        summary = proposal_of(draft).get("preview_summary")
    if not isinstance(summary, Mapping):
        return None
    added = max(as_int(summary.get("added")) or 0, 0)
    removed = max(as_int(summary.get("removed")) or 0, 0)
    return added, removed, as_int(summary.get("window_days")) or 14


def preview_text(draft: Mapping) -> str:
    """'+3 / -9 in the last 14 days', or 'No preview yet.'"""
    counts = preview_counts(draft)
    if counts is None:
        return "No preview yet."
    added, removed, days = counts
    return f"+{added} / -{removed} in the last {days} days"


def preview_caption(draft: Mapping) -> str:
    counts = preview_counts(draft)
    if counts is None:
        return ""
    added, removed, _ = counts
    return f"Would have added {plural(added, 'story', 'stories')} to your briefings and removed {removed}."


def local_today(tz: str, now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(zone(tz)).date()


def local_day(value: Any, tz: str) -> date | None:
    parsed = parse_time(value)
    return None if parsed == MIN_TIME else parsed.astimezone(zone(tz)).date()


def expires_iso(day: date, tz: str) -> str:
    """The end of a preference 'until <day>': local midnight of that day, as a UTC ISO time (as the card actions
    send it)."""
    return ui.local_midnight_iso(day, tz)


def day_bounds(tz: str, now: datetime | None = None) -> tuple[date, date, date]:
    """(earliest, default, latest) for an end date: tomorrow, today + 30 days, today + 366 days (the hub's limit)."""
    today = local_today(tz, now)
    return today + timedelta(days=1), today + timedelta(days=UNTIL_DEFAULT_DAYS), today + timedelta(days=UNTIL_MAX_DAYS)


def clamp_day(day: date | None, tz: str) -> date:
    earliest, default, latest = day_bounds(tz)
    return min(max(day or default, earliest), latest)


def soft_cap_text(soft: Any) -> str:
    """The hub's soft-cap sentence (GET /preferences soft_cap.warning, gap 29)."""
    return one_line(pick(soft, "warning"))


def join(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def effective(result: Any, ws: Workspace) -> str:
    return ui.effective_text(pick(result, "effective"), ws.timezone)


def workspace_of(workspace_id: Any) -> Workspace | None:
    return load_config().workspace(one_line(workspace_id))


def ws_missing() -> None:
    st.error("This workspace is no longer configured. Close this and reload the page.")


# ---------------------------------------------------------------------------------------------- the tab


def render(ws: Workspace) -> None:
    prefs, prefs_error = attempt(data.preferences, ws.id)
    rules, _ = attempt(data.rules, ws.id)
    mutes, mutes_error = attempt(data.mutes, ws.id, include_removed=True)
    stars, stars_error = attempt(data.stars, ws.id)
    header(ws, prefs)
    counts: dict[str, int | None] = {
        "ok": len(needs_ok(prefs, rules)) if prefs_error is None else None,
        "active": len(live_preferences(prefs)) if prefs_error is None else None,
        "muted": len(active_mutes(mutes)) if mutes_error is None else None,
        "watchlist": len(active_stars(stars)) if stars_error is None else None,
    }
    section = section_control(counts)
    if section != "active":  # Active has the hint under its Add form
        ui.locked_hint(ws)
    if section == "ok":
        render_ok(ws, prefs, prefs_error, rules)
    elif section == "active":
        render_active(ws, prefs, prefs_error)
    elif section == "looks_for":
        brief_view.render_brief(ws)
    elif section == "muted":
        render_muted(ws, mutes, mutes_error)
    elif section == "watchlist":
        render_watchlist(ws, stars, stars_error)
    else:
        render_how_much(ws)


def header(ws: Workspace, prefs: Any) -> None:
    """'This week your preferences changed ...' and the Refresh button."""
    text_col, button_col = st.columns([6, 1], vertical_alignment="center")
    with text_col:
        if prefs is not None:
            st.markdown(f'<div class="pref-text">{esc(summary_sentence(pick(prefs, "summary_7d")))}</div>',
                        unsafe_allow_html=True)
    with button_col:
        ui.refresh_button("preferences")


def _section_changed() -> None:
    value = st.session_state.get(SECTION_KEY)
    links.set_focus(section=value if value in SECTIONS else None, pref=None)


def select_section(section: str) -> None:
    """A button callback: switch to another section (the control is not drawn yet when callbacks run)."""
    st.session_state[SECTION_KEY] = section
    links.set_focus(section=section, pref=None)


def section_control(counts: Mapping[str, int | None]) -> str:
    """The section picker. A link (`section`, or `pref`, which means Active) wins over the remembered choice when it
    changes; otherwise the choice stays; the first visit opens Needs your OK when it has something, else Active."""
    want = links.focus("section")
    if want not in SECTIONS:
        want = "active" if links.focus("pref") else None
    current = st.session_state.get(SECTION_KEY)
    if want and current != want:
        st.session_state[SECTION_KEY] = want
    elif current not in SECTIONS:
        st.session_state[SECTION_KEY] = default_section(counts)
    st.segmented_control("Section", list(SECTIONS), key=SECTION_KEY, required=True,
                         format_func=lambda slug: section_label(slug, counts), on_change=_section_changed,
                         label_visibility="collapsed")
    value = st.session_state.get(SECTION_KEY)
    if value not in SECTIONS:
        value = default_section(counts)
    links.set_focus(section=value)
    return value


# ---------------------------------------------------------------------------------------------- Needs your OK


def render_ok(ws: Workspace, prefs: Any, prefs_error: api.ApiError | None, rules: Any) -> None:
    notice = st.session_state.pop(NOTICE_KEY, None)
    if notice:
        st.warning(notice)
    if prefs_error is not None:
        ui.error_box("your preferences", prefs_error, key="preferences")
        return
    n = waiting_count(prefs)
    if n:
        st.caption(f"{plural(n, 'suggestion')} you sent {'is' if n == 1 else 'are'} with the wording assistant. "
                   f"{'It comes' if n == 1 else 'They come'} back here once worded.")
    cards = needs_ok(prefs, rules)
    if not cards:
        st.markdown(empty_state(EMPTY_OK), unsafe_allow_html=True)
        return
    by_id = preferences_by_id(prefs)
    lines = brief_lines(ws) if any(origin_of(d) == "brief" for d in cards) else {}
    for draft in cards:
        suggestion_card(ws, draft, by_id, lines)


def brief_lines(ws: Workspace) -> dict[str, str]:
    """{line id: the line as What ZENUX looks for shows it} from GET /brief (cached), so a suggested change names its
    line in the approved words (the draft's context keeps the original words for the wording assistant)."""
    brief, _ = attempt(data.brief, ws.id)
    out: dict[str, str] = {}
    for section in dicts(pick(brief, "sections", default=[])):
        for part in dicts(section.get("parts")):
            for line in dicts(part.get("lines")):
                if one_line(line.get("id")) and one_line(line.get("text")):
                    out[one_line(line.get("id"))] = one_line(line.get("text"))
    return out


def suggestion_html(draft: Mapping, by_id: Mapping[str, dict], tz: str, lines: Mapping[str, str] | None = None) -> str:
    """The card's head and body by origin (spec 7.2), escaped."""
    origin = origin_of(draft)
    proposed = shown_text(draft)
    when = fmt_date(pick(draft, "proposed_at", "updated_at", "created_at"), tz)
    head = ('<div class="loop-card-head">' + chip(suggestion_head(draft), "suggested")
            + (f'<span class="pref-meta">{esc(when)}</span>' if when and when != "—" else "") + "</div>")
    if origin == "grades":
        lines, more = grade_lines(draft)
        body = f'<div class="pref-text">{esc(proposed)}</div>'
        if lines:
            body += ('<div class="refine-label">Your ratings behind it</div><div class="grade-lines">'
                     + "".join(f'<div class="grade-line">{esc(line)}</div>' for line in lines) + "</div>"
                     + (f'<div class="refine-note">and {more} more</div>' if more else ""))
    elif origin == "preference":
        target = by_id.get(one_line(draft.get("target_precedent_id")))
        yours = labels.preference_text(target) if target else labels.preference_text({"text": draft.get("text")})
        body = (f'<div class="refine-owner">Yours: {esc(yours)}</div>'
                f'<div class="pref-text">Suggested: {esc(proposed)}</div>')
    elif origin == "consolidation":
        replaced = replaced_lines(draft, by_id)
        body = f'<div class="pref-text">{esc(proposed)}</div>'
        if replaced:
            body += ('<div class="refine-label">It replaces:</div><div class="grade-lines">'
                     + "".join(f'<div class="grade-line">{esc(text)}</div>' for text in replaced) + "</div>")
    elif origin == "brief":
        line = (lines or {}).get(one_line(pick(draft, "context.brief_line.line_id"))) or one_line(
            pick(draft, "context.brief_line.text"))
        body = ((f'<div class="refine-owner">Line: {esc(line)}</div>' if line else "")
                + f'<div class="pref-text">Suggested: {esc(proposed)}</div>')
    elif origin == "radar":
        body = f'<div class="pref-text">{esc(proposed)}</div>'
    else:
        words = one_line(pick(draft, "owner_text", "plain_text", "text"))
        body = ((f'<div class="refine-owner">Your words: {esc(words)}</div>' if words else "")
                + f'<div class="pref-text">Suggested: {esc(proposed)}</div>')
    counts = preview_counts(draft)
    if counts:
        added, removed, days = counts
        line_html = (f'<div class="preview-line"><span class="preview-plus">+{added}</span> / '
                     f'<span class="preview-minus">-{removed}</span> in the last {days} days</div>')
    else:
        line_html = f'<div class="preview-line">{esc(preview_text(draft))}</div>'
    return f'<div class="pref-card">{head}{body}{line_html}</div>'


def preview_item_line(item: Mapping) -> str:
    """'<title> · <source>' for one story of a proposal's preview (gap 2: the hub sends titles and plain source
    names)."""
    title = one_line(item.get("title")) or "A story no longer available"
    source = one_line(item.get("source_label"))
    return " · ".join(p for p in (title, source) if p)


def which_stories(draft: Mapping, did: str) -> None:
    """The lazy "Which stories" list: the stories the proposal would bring in and drop out (`preview_items`, at most
    50; `preview_more` counts the rest)."""
    items = dicts(draft.get("preview_items"))
    if not items:
        return
    box = st.expander("Which stories", key=f"sg_list_{did}", on_change="rerun")
    if not box.open:
        return
    html = ""
    for heading, to in (("Would come in", "in"), ("Would drop out", "out")):
        group = [e for e in items if one_line(e.get("to")).lower() == to]
        if not group:
            continue
        html += (f'<div class="refine-label">{esc(heading)} · {len(group)}</div><div class="grade-lines">'
                 + "".join(f'<div class="grade-line">{esc(preview_item_line(e))}</div>' for e in group) + "</div>")
    more = as_int(draft.get("preview_more")) or 0
    if more > 0:
        html += f'<div class="refine-note">and {plural(more, "more story", "more stories")}</div>'
    with box:
        st.markdown(html or '<div class="refine-note">No stories listed.</div>', unsafe_allow_html=True)


def conflict_choices(draft: Mapping, did: str, by_id: Mapping[str, dict]) -> list[str]:
    """The live preferences a proposal may conflict with, each with "End this one when I approve" (on by default).
    -> the ids to retire."""
    live = [(n, cid, by_id[cid]) for n, cid in enumerate(conflicts_of(draft))
            if cid in by_id and status_of(by_id[cid]) in LIVE]
    if not live:
        return []
    st.markdown('<div class="refine-label">It may conflict with:</div>', unsafe_allow_html=True)
    chosen = []
    for n, cid, pref in live:
        st.markdown(f'<div class="refine-owner">{esc(labels.preference_text(pref))}</div>', unsafe_allow_html=True)
        if st.checkbox("End this one when I approve", value=True, key=f"sg_retire_{did}_{n}"):
            chosen.append(cid)
    return chosen


def suggestion_card(ws: Workspace, draft: Mapping, by_id: Mapping[str, dict],
                    lines: Mapping[str, str] | None = None) -> None:
    did = one_line(draft.get("id"))
    approve_label, reject_label = button_labels(draft)
    as_new = st.session_state.get(AS_NEW_KEY, {}).get(did) if isinstance(st.session_state.get(AS_NEW_KEY), dict) else None
    stale = merge_is_stale(draft, by_id)
    with st.container(border=True, key=f"zx_card_sg_{did}"):
        st.markdown(suggestion_html(draft, by_id, ws.timezone, lines), unsafe_allow_html=True)
        caption = preview_caption(draft)
        if caption:
            st.caption(md_label(caption))
        which_stories(draft, did)
        rationale = shown_rationale(draft, by_id)
        if rationale:
            st.caption(md_label(rationale))
        if stale:
            st.caption(MERGE_STALE)
        retire = conflict_choices(draft, did, by_id)
        edited = st.text_area(WORDING_LABEL, value=shown_text(draft), key=f"sg_text_{did}", height=100,
                              max_chars=EDIT_TEXT_MAX, disabled=stale)
        with st.container(horizontal=True, key=f"zx_actions_sg_{did}"):
            if stale:  # approving would be refused (merge_outdated): only turning it down is offered
                approve = False
            else:
                approve = ui.write_button(approve_label, ws=ws, key=f"sg_approve_{did}", type="primary")
            reject = ui.write_button(reject_label, ws=ws, key=f"sg_reject_{did}",
                                     type="primary" if stale else "tertiary")
        approve_new = False
        if as_new:
            st.info(as_new)
            approve_new = ui.write_button("Approve as a new preference", ws=ws, key=f"sg_as_new_{did}", type="primary")
        if approve or approve_new:
            approve_suggestion(ws, draft, edited, retire, as_new=approve_new)
        elif reject:
            reject_suggestion(ws, draft)


def approve_body(draft: Mapping, edited: str, retire: list[str], *, as_new: bool = False) -> dict:
    """{proposed_at} as shown, plus the edited text only when it differs from the wording shown (the plain words; an
    unedited approval keeps the proposal as stored), the conflicts to end, and as_new."""
    body: dict[str, Any] = {"proposed_at": draft.get("proposed_at")}
    text = (edited or "").strip()
    if text and one_line(text) not in (one_line(shown_text(draft)), one_line(proposal_text(draft))):
        body["text"] = text
    if retire:
        body["retire"] = list(retire)
    if as_new:
        body["as_new"] = True
    return body


def forget_card(did: str) -> None:
    store = st.session_state.get(AS_NEW_KEY)
    if isinstance(store, dict):
        store.pop(did, None)
    st.session_state.pop(f"sg_text_{did}", None)


def approve_suggestion(ws: Workspace, draft: Mapping, edited: str, retire: list[str], *, as_new: bool = False) -> None:
    did = one_line(draft.get("id"))
    if not one_line(edited):
        st.info(EMPTY_WORDING)
        return
    body = approve_body(draft, edited, retire, as_new=as_new)
    rule_id = draft.get("id")
    result, handled = brief_view.write_or_handle(
        ws, lambda token: api.rule_action(ws, token, rule_id, "approve", body),
        toast=lambda answer: join("Approved.", effective(answer, ws)),
        codes=("proposal_changed", "merge_outdated", "target_retired"))
    if handled is not None:
        answer_conflict(did, handled)
        return
    if result is None:
        return
    new_id = one_line(pick(result, "preference.id", "precedent.id"))
    if new_id:
        restored = bool(pick(result, "superseded"))
        ui.offer_undo(ws, "Approved a suggestion.",
                      lambda token: api.rule_action(ws, token, new_id, "retire", {"reason": "undone"}),
                      done="Undone. Your earlier wording is back." if restored else "Undone.")
    forget_card(did)
    st.rerun()


def answer_conflict(did: str, exc: api.ApiError) -> None:
    """A 409 the card answers itself: re-read and say so in plain words, or offer "Approve as a new preference"."""
    data.clear_reads()
    if exc.code == "target_retired":
        store = st.session_state.get(AS_NEW_KEY)
        if not isinstance(store, dict):
            store = {}
        store[did] = getattr(exc, "detail", None) or TARGET_RETIRED
        st.session_state[AS_NEW_KEY] = store
    else:
        st.session_state.pop(f"sg_text_{did}", None)  # the text box shows the new proposal, not the one approved
        st.session_state[NOTICE_KEY] = PROPOSAL_CHANGED if exc.code == "proposal_changed" else MERGE_OUTDATED
    st.rerun()


def reject_suggestion(ws: Workspace, draft: Mapping) -> None:
    """Not now (or Keep mine, Keep them separate): POST /rules/<draft>/reject {}; Undo puts it back (POST
    /rules/<draft>/reopen)."""
    rule_id = draft.get("id")
    result = ui.write(ws, lambda token: api.rule_action(ws, token, rule_id, "reject", {}), toast="Set aside.",
                      undo=lambda answer: ("Set a suggestion aside.",
                                           lambda token: api.rule_action(ws, token, rule_id, "reopen", {}),
                                           "It is back under Needs your OK."))
    if result is not None:
        forget_card(one_line(rule_id))
        st.rerun()


# ---------------------------------------------------------------------------------------------- Active


def render_active(ws: Workspace, prefs: Any, prefs_error: api.ApiError | None) -> None:
    add_form(ws)
    if prefs_error is not None:
        ui.error_box("your preferences", prefs_error, key="preferences")
        return
    warning = soft_cap_text(pick(prefs, "soft_cap"))
    if warning:
        st.info(md_label(warning))
    live = live_preferences(prefs)
    focus = one_line(links.focus("pref"))
    if focus:
        live.sort(key=lambda p: one_line(p.get("id")) != focus)  # stable: the linked one first, the rest in order
    if not live:
        st.markdown(empty_state(EMPTY_ACTIVE), unsafe_allow_html=True)
    for pref in live:
        preference_card(ws, pref, focused=bool(focus) and one_line(pref.get("id")) == focus)
    ended_list(ws, ended_preferences(prefs), focus)


def add_form(ws: Workspace) -> None:
    """A standing preference in the analyst's words, active at once."""
    earliest, default, latest = day_bounds(ws.timezone)
    with st.form("pf_add", border=True):
        st.markdown('<div class="rules-section" style="margin-top:0">Add a preference</div>', unsafe_allow_html=True)
        direction = st.radio("What do you want?", DIRECTIONS, key="pf_add_dir", horizontal=True,
                             format_func=labels.direction_label)
        text = st.text_area("In your own words", key="pf_add_text", height=90, max_chars=ADD_TEXT_MAX,
                            placeholder=ADD_PLACEHOLDER)
        # A form cannot reveal the date when the box is ticked, so the two sit side by side.
        box_col, date_col = st.columns([1, 1], vertical_alignment="bottom")
        until_on = box_col.checkbox("Only for a while", key="pf_add_until_on")
        until = date_col.date_input("Until", value=default, min_value=earliest, max_value=latest, key="pf_add_until",
                                    help="Used only when 'Only for a while' is ticked.")
        submitted = st.form_submit_button("Add", key="pf_add_save", type="primary", disabled=not owner.can_edit(ws))
        st.caption(actions.ACTIVE_AT_ONCE)
    ui.locked_hint(ws)
    if not submitted:
        return
    clean = (text or "").strip()
    if len(one_line(clean)) < TEXT_MIN:
        st.info(TOO_SHORT)
        return
    expires = expires_iso(until, ws.timezone) if until_on and isinstance(until, date) else None
    chosen = direction if direction in DIRECTIONS else "more"
    result = ui.write(
        ws, lambda token: api.add_preference(ws, token, direction=chosen, scope="standing", text=clean,
                                             expires_at=expires),
        toast=lambda answer: join(f"Added: {labels.direction_label(chosen)}.", effective(answer, ws)),
        undo=lambda answer: _undo_new(ws, answer, "Added a preference."))
    if result is not None:
        st.session_state.pop("pf_add_text", None)
        st.rerun()


def _undo_new(ws: Workspace, answer: Any, text: str) -> tuple[str, Callable[[str], Any]] | None:
    """Undo a new preference: retire it as undone."""
    new_id = one_line(pick(answer, "preference.id", "precedent.id"))
    if not new_id:
        return None
    return text, lambda token: api.rule_action(ws, token, new_id, "retire", {"reason": "undone"})


def preference_html(pref: Mapping, tz: str, focused: bool = False) -> str:
    example = example_line(pref)
    return (
        f'<div class="pref-card{" zx-focus" if focused else ""}">'
        '<div class="loop-card-head">' + chip(labels.direction_label(pref.get("direction")), "suggested")
        + f'<span class="pref-meta">{esc(head_meta(pref, tz))}</span></div>'
        f'<div class="pref-text">{esc(labels.preference_text(pref))}</div>'
        + (f'<div class="pref-meta">{esc(example)}</div>' if example else "")
        + f'<div class="pref-stats">{esc(stats_line(pref))}</div></div>'
    )


def preference_card(ws: Workspace, pref: Mapping, *, focused: bool = False) -> None:
    pid = one_line(pref.get("id"))
    status = status_of(pref)
    stats = pref.get("stats") if isinstance(pref.get("stats"), Mapping) else {}
    clicked: str | None = None
    with st.container(border=True, key=f"zx_card_pf_{pid}"):
        st.markdown(preference_html(pref, ws.timezone, focused), unsafe_allow_html=True)
        if stats.get("dormant") and status == "active":
            st.markdown('<div class="pref-meta">Not used in 30 days. Still useful?</div>', unsafe_allow_html=True)
            if ui.write_button("End it", ws=ws, key=f"pf_end_it_{pid}", type="tertiary"):
                clicked = "remove"
        mute = stats.get("looks_like_mute")
        if isinstance(mute, Mapping) and one_line(mute.get("ref")) and one_line(mute.get("kind")):
            label = one_line(pick(mute, "label", "ref"))
            st.markdown(f'<div class="pref-meta">{esc(looks_like_mute_text(mute))}</div>', unsafe_allow_html=True)
            if ui.write_button(f"Mute {label}", ws=ws, key=f"pf_mute_instead_{pid}", type="tertiary"):
                actions.open_mute(ws, kind=one_line(mute.get("kind")), ref=one_line(mute.get("ref")), label=label,
                                  module=one_line(mute.get("module")) or None)
        kept = mostly_kept_out(stats)
        if kept:
            st.caption(md_label(f"Mostly kept out: {kept}"))
        wording = pref.get("wording")
        if isinstance(wording, Mapping) and status_of(wording, "queued") == "proposed":
            st.markdown('<div class="pref-meta">A clearer wording is waiting in Needs your OK.</div>',
                        unsafe_allow_html=True)
            st.button("See it", key=f"pf_wording_{pid}", type="tertiary", on_click=select_section, args=("ok",))
        with st.container(horizontal=True, key=f"zx_actions_pf_{pid}"):
            if status == "paused":
                if ui.write_button("Resume", ws=ws, key=f"pf_resume_{pid}", type="tertiary"):
                    clicked = "resume"
            elif ui.write_button("Pause", ws=ws, key=f"pf_pause_{pid}", type="tertiary"):
                clicked = "pause"
            if ui.write_button("Edit", ws=ws, key=f"pf_edit_{pid}", type="tertiary"):
                clicked = "edit"
            if ui.write_button("End date", ws=ws, key=f"pf_end_{pid}", type="tertiary"):
                clicked = "end"
            if ui.write_button("Remove", ws=ws, key=f"pf_remove_{pid}", type="tertiary"):
                clicked = "remove"
        if clicked:
            card_action(ws, pref, clicked)


def card_action(ws: Workspace, pref: Mapping, action: str) -> None:
    """One card button; writes run below the buttons, so an error shows in the card, not squeezed into the row."""
    pid = one_line(pref.get("id"))
    if action == "edit":
        ui.open_dialog("pref_edit", workspace_id=ws.id, pref=dict(pref))
    elif action == "end":
        ui.open_dialog("pref_end", workspace_id=ws.id, pref=dict(pref))
    elif action == "remove":
        confirm_remove(ws, pref)
    elif action == "pause":
        result = ui.write(ws, lambda token: api.rule_action(ws, token, pid, "pause", {}), toast=PAUSED_TOAST,
                          undo=lambda answer: ("Paused a preference.",
                                               lambda token: api.rule_action(ws, token, pid, "resume", {})))
        if result is not None:
            st.rerun()
    elif action == "resume":
        result = ui.write(ws, lambda token: api.rule_action(ws, token, pid, "resume", {}),
                          toast=lambda answer: join("Resumed.", effective(answer, ws)),
                          undo=lambda answer: ("Resumed a preference.",
                                               lambda token: api.rule_action(ws, token, pid, "pause", {})))
        if result is not None:
            st.rerun()


def confirm_remove(ws: Workspace, pref: Mapping) -> None:
    pid = one_line(pref.get("id"))

    def remove() -> None:
        ui.write(ws, lambda token: api.rule_action(ws, token, pid, "retire", {}), toast="Removed.",
                 undo=lambda answer: ("Removed a preference.",
                                      lambda token: api.rule_action(ws, token, pid, "reactivate", {})))

    ui.ask_confirm(REMOVE_TITLE, REMOVE_MESSAGE, "Remove", remove, danger=True, detail=remove_detail(pref))


def remove_detail(pref: Mapping) -> str:
    """Which preference Remove ends, in full (WF5 AW-3): its direction, its words and its example story, so a "more"
    and a "less" made from the same story can be told apart: 'Remove "Show me less like this: Stories like this
    example. (Example: The Hidden Failure Domain ...)"?'"""
    words = clip(labels.preference_text(pref), 200).rstrip()
    head = labels.direction_label(pref.get("direction"))
    example = one_line(pick(pref.get("example"), "title"))
    text = f"{head}: {words}" if words else head
    if example:
        text += f" (Example: {clip(example, 120)})"
    return f"Remove “{text}”?"


def ended_list(ws: Workspace, ended: list[dict], focus: str) -> None:
    if not ended:
        return
    ids = [one_line(p.get("id")) for p in ended]
    if focus and focus in ids and st.session_state.get(ENDED_FOCUS_KEY) != focus:
        st.session_state[ENDED_KEY] = True  # a link to an ended preference opens the list once
        st.session_state[ENDED_FOCUS_KEY] = focus
    box = st.expander(f"Ended preferences · {len(ended)}", key=ENDED_KEY, on_change="rerun")
    if not box.open:
        return
    if focus in ids:
        ended = sorted(ended, key=lambda p: one_line(p.get("id")) != focus)
    with box:
        for pref in ended[:ENDED_MAX]:
            pid = one_line(pref.get("id"))
            when = fmt_date(pref.get("retired_at"), ws.timezone) if pref.get("retired_at") else ""
            meta = " · ".join(p for p in (ended_reason(pref), when if when != "—" else "") if p)
            text_col, button_col = st.columns([5, 1], vertical_alignment="center")
            text_col.markdown(
                f'<div class="pref-card{" zx-focus" if pid == focus else ""}">'
                f'<div class="pref-text">{esc(labels.preference_text(pref))}</div>'
                f'<div class="pref-meta">{esc(meta)}</div></div>', unsafe_allow_html=True)
            with button_col:
                if ui.write_button("Bring back", ws=ws, key=f"pf_bring_back_{pid}", type="tertiary"):
                    bring_back_preference(ws, pref)
        if len(ended) > ENDED_MAX:
            st.caption(f"and {len(ended) - ENDED_MAX} more ended earlier")


def bring_back_preference(ws: Workspace, pref: Mapping) -> None:
    pid = one_line(pref.get("id"))
    if needs_new_end_date(pref):
        ui.open_dialog("pref_reactivate", workspace_id=ws.id, pref=dict(pref))
        return
    result = ui.write(ws, lambda token: api.rule_action(ws, token, pid, "reactivate", {}),
                      toast=lambda answer: join("Brought back.", effective(answer, ws)),
                      undo=lambda answer: ("Brought back a preference.",
                                           lambda token: api.rule_action(ws, token, pid, "retire", {})))
    if result is not None:
        st.rerun()


# ---------------------------------------------------------------------------------------------- dialogs


def dialog_buttons(ws: Workspace, save_label: str) -> tuple[bool, bool]:
    with st.container(horizontal=True):
        save = ui.write_button(save_label, ws=ws, key="dlg_save", type="primary")
        cancel = st.button("Cancel", key="dlg_cancel")
    return save, cancel


def close_and_rerun() -> None:
    ui.close_dialog()
    st.rerun()


def edit_dialog(workspace_id: str, pref: dict) -> None:
    """Edit: a new version with the analyst's words, kind, scope and end date (Undo puts the old one back)."""
    ws = workspace_of(workspace_id)
    if ws is None:
        ws_missing()
        return
    pid = one_line(pref.get("id"))
    tz = ws.timezone
    earliest, _, latest = day_bounds(tz)
    original = labels.preference_text(pref)
    text = st.text_area("Your words", value=original, key="dlg_text", height=110, max_chars=EDIT_TEXT_MAX)
    direction_now = one_line(pref.get("direction")).lower()
    direction_now = direction_now if direction_now in DIRECTIONS else "exact"
    direction = st.radio("What kind?", DIRECTIONS, index=DIRECTIONS.index(direction_now), key="dlg_direction",
                         format_func=labels.direction_label)
    scope_now = one_line(pref.get("scope")).lower()
    scopes = [s for s in SCOPES if s != "this_story" or pref.get("story_id") or scope_now == "this_story"]
    scope_now = scope_now if scope_now in scopes else "standing"
    scope = st.radio("Apply to", scopes, index=scopes.index(scope_now), key="dlg_scope",
                     format_func=labels.scope_label, captions=[labels.SCOPE_HELP.get(s, "") for s in scopes])
    day_now = local_day(pref.get("expires_at"), tz) if pref.get("expires_at") else None
    until_on = st.checkbox("Only for a while", value=day_now is not None, key="dlg_until_on")
    until = None
    if until_on:
        until = st.date_input("Until", value=clamp_day(day_now, tz), min_value=earliest, max_value=latest,
                              key="dlg_until")
    st.caption("Saving makes a new version; the editor uses it from the next briefing. Undo puts this one back.")
    save, cancel = dialog_buttons(ws, "Save")
    if cancel:
        close_and_rerun()
    if not save:
        return
    clean = (text or "").strip()
    if len(one_line(clean)) < TEXT_MIN:
        st.info(TOO_SHORT)
        return
    day_new = until if until_on and isinstance(until, date) else None
    body: dict[str, Any] = {"text": clean}
    if direction != direction_now:
        body["direction"] = direction
    if scope != scope_now:
        body["scope"] = scope
    if day_new != day_now:
        body["expires_at"] = expires_iso(day_new, tz) if day_new else None
    if len(body) == 1 and one_line(clean) == one_line(original):
        st.info(NOTHING_CHANGED)
        return
    result = ui.write(ws, lambda token: api.rule_action(ws, token, pid, "edit", body),
                      toast=lambda answer: join("Saved your new wording.", effective(answer, ws)))
    if result is None:
        return
    new_id = one_line(pick(result, "preference.id"))
    if new_id:
        ui.offer_undo(ws, "Edited a preference.",
                      lambda token: api.rule_action(ws, token, new_id, "retire", {"reason": "undone"}),
                      done="Undone. Your earlier wording is back.")
    close_and_rerun()


def end_date_dialog(workspace_id: str, pref: dict) -> None:
    """End date: a date, or no end date (Undo puts the previous one back)."""
    ws = workspace_of(workspace_id)
    if ws is None:
        ws_missing()
        return
    pid = one_line(pref.get("id"))
    tz = ws.timezone
    earliest, _, latest = day_bounds(tz)
    st.markdown(f'<div class="refine-owner">{esc(labels.preference_text(pref))}</div>', unsafe_allow_html=True)
    choice = st.radio("When should it end?", ("date", "none"), key="dlg_choice", horizontal=True,
                      format_func={"date": "On a date", "none": "No end date"}.get)
    day_now = local_day(pref.get("expires_at"), tz) if pref.get("expires_at") else None
    day = None
    if choice == "date":
        day = st.date_input("Ends on", value=clamp_day(day_now, tz), min_value=earliest, max_value=latest,
                            key="dlg_until")
    save, cancel = dialog_buttons(ws, "Save")
    if cancel:
        close_and_rerun()
    if not save:
        return
    day_new = day if choice == "date" and isinstance(day, date) else None
    if day_new == day_now:
        st.info(NOTHING_CHANGED)
        return
    expires = expires_iso(day_new, tz) if day_new else None
    previous = pref.get("expires_at")
    result = ui.write(
        ws, lambda token: api.rule_action(ws, token, pid, "end-date", {"expires_at": expires}),
        toast=f"It ends on {fmt_date(expires, tz)}." if expires else "No end date.",
        undo=lambda answer: ("Changed an end date.",
                             lambda token: api.rule_action(ws, token, pid, "end-date", {"expires_at": previous})))
    if result is not None:
        close_and_rerun()


def reactivate_dialog(workspace_id: str, pref: dict) -> None:
    """Bring back a preference whose end date passed: a new end date, or none."""
    ws = workspace_of(workspace_id)
    if ws is None:
        ws_missing()
        return
    pid = one_line(pref.get("id"))
    tz = ws.timezone
    earliest, _, latest = day_bounds(tz)
    st.markdown(f'<div class="refine-owner">{esc(labels.preference_text(pref))}</div>', unsafe_allow_html=True)
    st.caption("Its end date passed. Give it a new end date, or none, to bring it back.")
    choice = st.radio("Until when?", ("none", "date"), key="dlg_choice", horizontal=True,
                      format_func={"none": "No end date", "date": "Until a date"}.get)
    day = None
    if choice == "date":
        day = st.date_input("Until", value=clamp_day(None, tz), min_value=earliest, max_value=latest, key="dlg_until")
    save, cancel = dialog_buttons(ws, "Bring back")
    if cancel:
        close_and_rerun()
    if not save:
        return
    expires = expires_iso(day, tz) if choice == "date" and isinstance(day, date) else None
    result = ui.write(ws, lambda token: api.rule_action(ws, token, pid, "reactivate", {"expires_at": expires}),
                      toast=lambda answer: join("Brought back.", effective(answer, ws)),
                      undo=lambda answer: ("Brought back a preference.",
                                           lambda token: api.rule_action(ws, token, pid, "retire", {})))
    if result is not None:
        close_and_rerun()


# ---------------------------------------------------------------------------------------------- Muted, Watchlist


def mute_meta(mute: Mapping, tz: str) -> str:
    """'since Oct 2 · hid 12 this week (30 in all) · <note>'."""
    parts = []
    since = fmt_date(mute.get("created_at"), tz) if mute.get("created_at") else ""
    if since and since != "—":
        parts.append(f"since {since}")
    parts.append(f"hid {as_int(mute.get('hidden_7d')) or 0} this week ({as_int(mute.get('hidden_total')) or 0} in all)")
    note = one_line(mute.get("note"))
    if note:
        parts.append(note)
    return " · ".join(parts)


def render_muted(ws: Workspace, body: Any, error: api.ApiError | None) -> None:
    st.caption(MUTED_CAPTION)
    if st.button("Show what they hid", key="pf_show_hidden", type="tertiary"):
        links.go("filtered", view="muted")
    if error is not None:
        ui.error_box("your mutes", error, key="pf_mutes")
        return
    active = active_mutes(body)
    if pick(body, "has_more") is True:
        listed = len(dicts(pick(body, "mutes", default=[])))
        st.caption(f"The newest {listed} of {plural(as_int(pick(body, 'total')) or listed, 'mute')} are listed.")
    if not active:
        st.markdown(empty_state(EMPTY_MUTED), unsafe_allow_html=True)
    known = {kind for kind, _ in MUTE_GROUPS}
    groups = [(title, [m for m in active if one_line(m.get("kind")).lower() == kind]) for kind, title in MUTE_GROUPS]
    groups.append(("Other", [m for m in active if one_line(m.get("kind")).lower() not in known]))
    for title, group in groups:
        if not group:
            continue
        st.markdown(f'<div class="rules-section">{esc(title)} · {len(group)}</div>', unsafe_allow_html=True)
        for mute in group:
            mid = one_line(mute.get("id"))
            text_col, button_col = st.columns([5, 1], vertical_alignment="center")
            text_col.markdown(
                f'<div class="pref-text">{esc(one_line(pick(mute, "label", "ref")))}</div>'
                f'<div class="pref-meta">{esc(mute_meta(mute, ws.timezone))}</div>', unsafe_allow_html=True)
            with button_col:
                if ui.write_button("Unmute", ws=ws, key=f"pf_unmute_{mid}", type="tertiary"):
                    actions.open_unmute(ws, mute)
    removed = removed_mutes(body)
    if not removed:
        return
    box = st.expander(f"Removed mutes · {len(removed)}", key=REMOVED_MUTES_KEY, on_change="rerun")
    if not box.open:
        return
    with box:
        for mute in removed:
            mid = one_line(mute.get("id"))
            when = fmt_date(mute.get("removed_at"), ws.timezone) if mute.get("removed_at") else ""
            meta = " · ".join(p for p in (one_line(labels.MUTE_KIND_LABELS.get(one_line(mute.get("kind")), "")),
                                          f"removed {when}" if when and when != "—" else "") if p)
            text_col, button_col = st.columns([5, 2], vertical_alignment="center")
            text_col.markdown(
                f'<div class="pref-text">{esc(one_line(pick(mute, "label", "ref")))}</div>'
                f'<div class="pref-meta">{esc(meta)}</div>', unsafe_allow_html=True)
            with button_col:
                if mute.get("brought_back"):
                    st.caption("Brought back")
                elif ui.write_button("Bring back the last 7 days", ws=ws, key=f"pf_bring_back_m{mid}",
                                     type="tertiary"):
                    actions.bring_back(ws, mute)


def star_meta(star: Mapping) -> str:
    parts = [f"{plural(as_int(star.get('matches_7d')) or 0, 'story', 'stories')} this week, "
             f"{as_int(star.get('in_briefing_7d')) or 0} in your briefing"]
    note = one_line(star.get("note"))
    if note:
        parts.append(note)
    return " · ".join(parts)


def render_watchlist(ws: Workspace, body: Any, error: api.ApiError | None) -> None:
    st.caption(labels.STAR_PROMISE)
    if st.button("Find companies in Coverage", key="pf_find_coverage", type="tertiary"):
        links.go("coverage")
    if error is not None:
        ui.error_box("your watchlist", error, key="pf_stars")
        return
    stars = active_stars(body)
    if not stars:
        st.markdown(empty_state(EMPTY_WATCHLIST), unsafe_allow_html=True)
        return
    for star in stars:
        sid = one_line(star.get("id"))
        entity_id = one_line(star.get("entity_id"))
        name = one_line(pick(star, "label", "name", "entity_id"))
        text_col, button_col = st.columns([5, 1], vertical_alignment="center")
        text_col.markdown(f'<div class="pref-text">{esc(name)}</div>'
                          f'<div class="pref-meta">{esc(star_meta(star))}</div>', unsafe_allow_html=True)
        with button_col:
            if ui.write_button("Remove", ws=ws, key=f"pf_unstar_{sid}", type="tertiary") and entity_id:
                actions.unstar(ws, entity_id, name)


# ---------------------------------------------------------------------------------------------- How much


def volume_modes(volume: Mapping) -> tuple[list[str], dict[str, int | None], dict[str, str]]:
    """(modes in the hub's order, cap per mode, hub label per mode); the three known modes when the hub sends none."""
    rows = [m for m in dicts(volume.get("modes")) if one_line(m.get("mode"))]
    modes = [one_line(m.get("mode")) for m in rows] or [m for m in VOLUME_ORDER]
    caps = {one_line(m.get("mode")): as_int(m.get("cap")) for m in rows}
    names = {one_line(m.get("mode")): one_line(m.get("label")) for m in rows}
    return modes, caps, names


def volume_label(mode: str, names: Mapping[str, str] | None = None) -> str:
    return labels.VOLUME_LABELS.get(mode) or (names or {}).get(mode) or mode.replace("_", " ").capitalize()


def render_how_much(ws: Workspace) -> None:
    try:
        settings = data.settings(ws.id)
    except api.ApiError as exc:
        ui.error_box("your 'how much' setting", exc, key="pf_settings")
        return
    volume = pick(settings, "volume") if isinstance(pick(settings, "volume"), Mapping) else {}
    modes, caps, names = volume_modes(volume)
    saved_mode = one_line(volume.get("mode")) or "standard"
    saved_mode = saved_mode if saved_mode in modes else modes[0]
    saved_shelf = bool(volume.get("near_miss_shelf"))
    saved = (saved_mode, saved_shelf)
    # Start from the saved setting, and follow it when it changes (an undo, another tab) rather than keep a stale pick.
    if (st.session_state.get(VOLUME_SEEN_KEY) != saved or VOLUME_MODE_KEY not in st.session_state
            or st.session_state.get(VOLUME_MODE_KEY) not in modes):
        st.session_state[VOLUME_MODE_KEY] = saved_mode
        st.session_state[VOLUME_SHELF_KEY] = saved_shelf
        st.session_state[VOLUME_SEEN_KEY] = saved
    mode = st.radio("How many stories per briefing?", modes, key=VOLUME_MODE_KEY,
                    format_func=lambda m: volume_label(m, names),
                    captions=[labels.volume_help(m, caps.get(m)) for m in modes])
    shelf = st.toggle("Show near misses under each briefing", key=VOLUME_SHELF_KEY)
    chosen = (mode if mode in modes else saved_mode, bool(shelf))
    unchanged = chosen == saved
    if unchanged:
        st.markdown(f'<div class="preview-line">{esc(VOLUME_CURRENT)}</div>', unsafe_allow_html=True)
    else:
        try:
            preview = data.volume_preview(ws.id, chosen[0], chosen[1])
            text = one_line(pick(preview, "text")) or VOLUME_NO_PREVIEW
        except api.ApiError as exc:
            text = ui.plain_error(exc)[0]
        st.markdown(f'<div class="preview-line">{esc(text)}</div>', unsafe_allow_html=True)
    if unchanged:
        st.button("Use this setting", key="pf_volume_save", disabled=True, help="Choose a different setting first.")
    elif ui.write_button("Use this setting", ws=ws, key="pf_volume_save", type="primary"):
        new_mode, new_shelf = chosen
        result = ui.write(
            ws, lambda token: api.set_volume(ws, token, new_mode, near_miss_shelf=new_shelf),
            toast=lambda answer: join(f"Now: {volume_label(new_mode, names)}.", effective(answer, ws)),
            undo=lambda answer: ("Changed how much you see.",
                                 lambda token: api.set_volume(ws, token, saved_mode, near_miss_shelf=saved_shelf)))
        if result is not None:
            st.rerun()
    st.caption(VOLUME_CAPTION)


ui.register_dialog("pref_edit", "Edit preference", edit_dialog, width="medium")
ui.register_dialog("pref_end", "End date", end_date_dialog, width="small")
ui.register_dialog("pref_reactivate", "Bring it back", reactivate_dialog, width="small")
