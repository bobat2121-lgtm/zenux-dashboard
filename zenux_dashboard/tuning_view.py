"""Tuning: everything the analyst tunes, on one page with no sub-tabs (docs/SPEC-SIMPLIFY.md 2.3), in this order:

1. The title, the 7-day summary line ("This week your preferences changed 23 decisions: ...") and Refresh.
2. "Needs your OK · N", only when something waits: suggested wordings, suggestions from the analyst's ratings,
   merges and brief or coverage suggestions (GET /preferences `suggestions`, plus legacy proposed drafts from GET
   /rules). Each card: its head chip, the suggestion, one impact line ("Would have brought 3 stories in and kept 1 out
   over the last 14 days."), its two buttons (Approve / Not now, Use this wording / Keep mine, Merge them / Keep them
   separate), and a "Details" expander with the rest: the ratings behind it, which stories, the wording assistant's
   reasoning, the wording box and the conflict checkboxes (on by default). Approve: POST /rules/<draft>/approve
   {proposed_at, text?, retire?, as_new?}; the other: POST /rules/<draft>/reject {} with Undo (reopen). The 409 answers
   (proposal_changed, merge_outdated, target_retired) are said on the card in plain words (brief_view.write_or_handle).
   Suggested company names the source finder has checked (GET /preferences `company_suggestions`,
   docs/SPEC-COMPANY-MAP.md 6.3) are cards of the same list: "Suggested name for <Company>", what it changes, the note,
   a big customer's reason and the source finder's result (company_names_view; a name the hub left out comes from the
   cached GET /brief), then Approve and Reject: POST /companies/suggestions/<id>/{approve|reject}, never /rules. No
   route reverses either, so they have no Undo, and Reject asks first; a 409 suggestion_closed re-reads the list and
   says so at the top.
3. "How much": one row with the three choices, the near-miss switch, the preview line and "Use this setting" (enabled
   only when changed): GET /settings, GET /settings/volume/preview, POST /settings/volume, with Undo.
4. "Your rules · N": one list of the preferences (GET /preferences, active and paused), mutes (GET /mutes?all=1,
   active) and the watchlist (GET /stars), with filter pills (All · More · Less · Muted · Watchlist, with counts) and
   "+ Add a rule" (a dialog: more, less or exactly as I write it, own words, only for a while; POST /preferences
   {direction, scope: standing, text, expires_at?}). Each row: what kind, its words or label, one impact line, an
   optional hint (paused; a clearer wording is waiting; mostly kept out one source; not used in 30 days) and one ⋯
   menu: a preference has Edit, End date and Remove (Resume when paused, "Mute <source> instead" when it looks like a
   mute), a mute Unmute (the card actions' dialog), the watchlist Remove from watchlist. There is no Pause. A `pref=`
   link highlights its row (and opens Ended once for an ended one).
5. "Ended · N" (collapsed): ended preferences (Bring back) and removed mutes (Bring back the last 7 days), 100 at most.

Every write goes through ui.write: the owner token from the PIN, a toast that says when the change takes effect (from
the answer's `effective`), and an undo where the hub has an inverse route. An approval names the proposal shown
(`proposed_at`). Each part reads only what it needs, so one failing route never blanks the others.

The analyst never sees an id, a source key or a module id here: the hub sends plain words beside every stored text
(`plain_text`, `proposal_plain`, `replaces_detail`, `soft_cap.warning`, `with_assistant`; docs/SPEC-PHASE05.md 3.2);
labels.preference_text keeps the analyst's own words of a preference, labels.clean_rationale stays the last guard on
reasoning, and the end reason, scope and direction go through their plain labels.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

import streamlit as st

from . import actions, api, brief_view, company_names_view, data, labels, links, ui
from .config import Workspace, load_config
from .fmt import (MIN_TIME, UTC, as_int, as_list, chip, clip, dicts, empty_state, esc, fmt_date, md_label, one_line,
                  parse_time, pick, plural, relative_time, unique_by_id, zone)

NOTICE_KEY = "pf_notice"          # a plain warning for the top of the page, after a 409 re-read
AS_NEW_KEY = "pf_as_new"          # {draft id: the hub's sentence}: suggestions whose preference has ended
RULES_KEY = "tn_rules"            # the filter pills of Your rules
PREF_SEEN_KEY = "tn_pref_seen"    # the last `pref` link applied (a new one resets the filter to All)
ENDED_KEY = "tn_ended"            # the lazy "Ended" expander
ENDED_FOCUS_KEY = "tn_ended_focus"
VOLUME_MODE_KEY = "tn_volume_mode"
VOLUME_SHELF_KEY = "tn_volume_shelf"
VOLUME_SEEN_KEY = "tn_volume_seen"

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
RULE_FILTERS: tuple[tuple[str, str], ...] = (("all", "All"), ("more", "More"), ("less", "Less"), ("muted", "Muted"),
                                             ("watchlist", "Watchlist"))
RULE_FILTER_NAMES = dict(RULE_FILTERS)

# ---------------------------------------------------------------------------------------------- copy

TITLE = "Tuning"
SUMMARY_NONE = "Your preferences haven't changed anything this week."
EMPTY_RULES = "No rules yet. Use the thumbs on any story in your briefing, or + Add a rule."
EMPTY_FILTER = {
    "more": "No “more like this” preferences.",
    "less": "No “less like this” preferences.",
    "muted": "Nothing muted. Mute a source or company in Coverage.",
    "watchlist": "No companies on your watchlist. Star one in Coverage.",
}
FILTER_NOTES = {"muted": labels.STILL_COLLECTED + " Mute or unmute sources and companies in Coverage too.",
                "watchlist": labels.STAR_PROMISE}
PROPOSAL_CHANGED = ("The wording assistant changed this suggestion after the page loaded, so nothing was approved. "
                    "Look at it again below.")
MERGE_OUTDATED = ("One of these preferences changed meanwhile, so nothing was merged. The list has been reloaded.")
MERGE_STALE = ("One of these preferences has changed since this merge was suggested, so it can't be merged. Keep them "
               "separate; the wording assistant suggests a fresh merge next month.")
TARGET_RETIRED = "The preference this wording was for has ended. Approve it as a new preference instead."
REMOVE_TITLE = "Remove this preference?"
REMOVE_MESSAGE = "The editor stops using it from the next briefing. You can bring it back from Ended."
TOO_SHORT = f"Write at least {TEXT_MIN} characters so the editor knows what you mean."
EMPTY_WORDING = "The wording is empty. Write it, or reload the page to see the suggestion again."
NOTHING_CHANGED = "Nothing changed."
WORDING_LABEL = "Wording (edit before approving if you like)"
VOLUME_CAPTION = ("This changes how many stories make the briefing, never how stories are scored or what is "
                  "collected.")
VOLUME_CURRENT = "This is your current setting."
VOLUME_NO_PREVIEW = "No briefings in the last 7 days to compare."
SHELF_LABEL = "Near misses under each briefing"
ADD_PLACEHOLDER = "e.g. Less coverage of bitcoin price moves unless a miner announces AI hosting"
ADD_LABEL = "Add a rule"
MENU_LABEL = "Options"  # each rule's ⋯ menu (the icon shows; the word is for screen readers)

SUGGESTION_HEADS = {
    "grades": "Suggested from your ratings",
    "preference": "Suggested wording for your preference",
    "brief": "Your suggested change to What ZENITH looks for",
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
KIND_LABELS = {"more": "More like this", "less": "Less like this", "exact": "Exactly as I write it"}
MUTE_KIND_CHIPS = {"source": "Muted source", "entity": "Muted company", "story": "Muted story",
                   "outlet": "Muted outlet"}


# ---------------------------------------------------------------------------------------------- pure helpers


def attempt(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, api.ApiError | None]:
    """(body, None) or (None, the ApiError): one failing read never stops the other parts."""
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
    """GET /preferences suggestions, the legacy proposed drafts of GET /rules that are not among them and the
    suggested company names (`company_suggestions`; company_names_view.is_suggestion tells them apart), newest first
    (by when the proposal arrived, then by id). The Briefing's banner counts the same list."""
    suggestions = [d for d in unique_by_id(dicts(pick(prefs_body, "suggestions", default=[])))
                   if status_of(d, "proposed") == "proposed" and not company_names_view.is_suggestion(d)]
    seen = {one_line(d.get("id")) for d in suggestions}
    legacy = [d for d in drafts_of(rules_body)
              if status_of(d, "queued") == "proposed" and one_line(d.get("id")) not in seen]
    cards = suggestions + legacy + company_names_view.proposed(prefs_body)
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


def kind_label(pref: Mapping) -> str:
    """'More like this', 'Less like this' or 'Exactly as I write it' (a legacy preference reads as the last)."""
    return KIND_LABELS.get(one_line(pref.get("direction")).lower(), KIND_LABELS["exact"])


def rule_meta(pref: Mapping, tz: str) -> str:
    """'Stories like this · until Nov 3': the scope and, when it has one, the end date."""
    parts = [labels.scope_label(pref.get("scope"))]
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


def looks_like_mute(pref: Mapping) -> dict | None:
    """The hub's "this preference behaves like a mute" ({kind, module, ref, label, share}), or None."""
    stats = pref.get("stats") if isinstance(pref.get("stats"), Mapping) else {}
    mute = stats.get("looks_like_mute")
    if isinstance(mute, Mapping) and one_line(mute.get("ref")) and one_line(mute.get("kind")):
        return dict(mute)
    return None


def looks_like_mute_text(mute: Mapping) -> str:
    share = pick(mute, "share")
    try:
        pct = round(float(share) * 100)
    except (TypeError, ValueError):
        pct = None
    label = one_line(pick(mute, "label", "ref"))
    lead = f"{pct}% of what it kept out" if pct is not None else "Most of what it kept out"
    return f"{lead} came from {label}. Mute it instead?"


def wording_waiting(pref: Mapping, waiting: set[str] | None = None) -> bool:
    """A clearer wording of this preference waits for the analyst's OK (`wording`, proposed); with `waiting` (the ids
    of the Needs your OK cards) only when its card is there to approve."""
    wording = pref.get("wording")
    if not (isinstance(wording, Mapping) and status_of(wording, "queued") == "proposed"):
        return False
    return waiting is None or one_line(wording.get("draft_id")) in waiting


def preference_hint(pref: Mapping, tz: str, waiting: set[str] | None = None) -> str:
    """The row's one hint, the most useful first: paused; a clearer wording is waiting (`waiting`: the ids of the
    Needs your OK cards); it kept out mostly one source; not used in 30 days. '' when none applies."""
    stats = pref.get("stats") if isinstance(pref.get("stats"), Mapping) else {}
    if status_of(pref) == "paused":
        since = fmt_date(pref.get("paused_at"), tz) if pref.get("paused_at") else ""
        when = f" since {since}" if since and since != "—" else ""
        return f"Paused{when}. The editor ignores it until you resume it."
    if wording_waiting(pref, waiting):
        return "A clearer wording is waiting under Needs your OK."
    mute = looks_like_mute(pref)
    if mute:
        return looks_like_mute_text(mute)
    if stats.get("dormant"):
        return "Not used in 30 days. Still useful?"
    return ""


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


def impact_line(draft: Mapping) -> str:
    """'Would have brought 3 stories in and kept 1 out over the last 14 days.', or 'No preview yet.'"""
    counts = preview_counts(draft)
    if counts is None:
        return "No preview yet."
    added, removed, days = counts
    span = f"over the last {days} days"
    if added and removed:
        return f"Would have brought {plural(added, 'story', 'stories')} in and kept {removed} out {span}."
    if added:
        return f"Would have brought {plural(added, 'story', 'stories')} in {span}."
    if removed:
        return f"Would have kept {plural(removed, 'story', 'stories')} out {span}."
    return f"Would not have changed your briefings {span}."


def preview_item_line(item: Mapping) -> str:
    """'<title> · <source>' for one story of a proposal's preview (gap 2: the hub sends titles and plain source
    names)."""
    title = one_line(item.get("title")) or "A story no longer available"
    source = one_line(item.get("source_label"))
    return " · ".join(p for p in (title, source) if p)


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


def mute_impact(mute: Mapping) -> str:
    """'Hid 12 stories this week (30 in all)'."""
    week = max(as_int(mute.get("hidden_7d")) or 0, 0)
    total = max(as_int(mute.get("hidden_total")) or 0, 0)
    return f"Hid {plural(week, 'story', 'stories')} this week ({total} in all)"


def mute_meta(mute: Mapping, tz: str) -> str:
    """'since Oct 2 · <note>'."""
    parts = []
    since = fmt_date(mute.get("created_at"), tz) if mute.get("created_at") else ""
    if since and since != "—":
        parts.append(f"since {since}")
    note = one_line(mute.get("note"))
    if note:
        parts.append(note)
    return " · ".join(parts)


def star_impact(star: Mapping) -> str:
    """'9 stories this week, 2 in your briefing'."""
    return (f"{plural(as_int(star.get('matches_7d')) or 0, 'story', 'stories')} this week, "
            f"{as_int(star.get('in_briefing_7d')) or 0} in your briefing")


def rules_of(prefs_body: Any, mutes_body: Any, stars_body: Any) -> list[dict]:
    """Your rules as one list: [{kind: pref | mute | star, filter, id, row}], preferences first (the hub's order,
    newest first), then mutes (newest first), then the watchlist. `filter` is the pill that shows the row besides All:
    more, less, muted or watchlist ("" for a preference exactly as written, shown under All only)."""
    out: list[dict] = []
    for pref in live_preferences(prefs_body):
        direction = one_line(pref.get("direction")).lower()
        out.append({"kind": "pref", "filter": direction if direction in ("more", "less") else "",
                    "id": one_line(pref.get("id")), "row": pref})
    mutes = sorted(active_mutes(mutes_body), key=lambda m: parse_time(m.get("created_at")), reverse=True)
    for mute in mutes:
        if as_int(mute.get("id")) is not None:
            out.append({"kind": "mute", "filter": "muted", "id": str(as_int(mute.get("id"))), "row": mute})
    for star in active_stars(stars_body):
        if one_line(star.get("entity_id")):
            out.append({"kind": "star", "filter": "watchlist", "id": one_line(pick(star, "id", "entity_id")),
                        "row": star})
    return out


def filter_counts(rules: list[dict]) -> dict[str, int]:
    counts = {code: 0 for code, _ in RULE_FILTERS}
    counts["all"] = len(rules)
    for rule in rules:
        if rule["filter"] in counts:
            counts[rule["filter"]] += 1
    return counts


def filter_label(code: str, counts: Mapping[str, int | None]) -> str:
    """'Muted · 3' (a count that could not be read is left out)."""
    n = counts.get(code)
    name = RULE_FILTER_NAMES.get(code, code)
    return f"{name} · {n}" if n is not None else name


def filtered_rules(rules: list[dict], code: str, focus: str = "") -> list[dict]:
    """The rows the pill shows, the linked preference (`pref=`) first."""
    shown = [r for r in rules if code == "all" or r["filter"] == code]
    if focus:
        shown.sort(key=lambda r: not (r["kind"] == "pref" and r["id"] == focus))
    return shown


def rule_html(rule: Mapping, tz: str, focused: bool = False, waiting: set[str] | None = None) -> str:
    """One row of Your rules: the kind chip (and the scope and end date of a preference, or since when a mute is on),
    the words or label (a preference's example on its own line), one impact line and the hint (`waiting`: the ids of
    the Needs your OK cards)."""
    row = rule["row"]
    kind = rule["kind"]
    if kind == "pref":
        head, meta = kind_label(row), rule_meta(row, tz)
        words = labels.preference_text(row) or "Your preference"
        example = example_line(row)
        impact = stats_line(row)
        hint = preference_hint(row, tz, waiting)
    elif kind == "mute":
        head = MUTE_KIND_CHIPS.get(one_line(row.get("kind")), "Muted")
        meta = mute_meta(row, tz)
        words = one_line(pick(row, "label")) or labels.MUTE_KIND_LABELS.get(one_line(row.get("kind")), "A mute")
        example, impact, hint = "", mute_impact(row), ""
    else:
        head, meta = "Watchlist", one_line(row.get("note"))
        words = one_line(pick(row, "label", "name")) or "A company"
        example, impact, hint = "", star_impact(row), ""
    css = "tn-rule" + (" zx-focus" if focused else "")
    return (f'<div class="{css}">'
            f'<div class="loop-card-head">{chip(head, "suggested")}'
            + (f'<span class="pref-meta">{esc(meta)}</span>' if meta else "") + "</div>"
            f'<div class="pref-text">{esc(words)}</div>'
            + (f'<div class="pref-meta">{esc(example)}</div>' if example else "")
            + f'<div class="pref-stats">{esc(impact)}</div>'
            + (f'<div class="tn-hint">{esc(hint)}</div>' if hint else "")
            + "</div>")


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


def ended_rows(prefs_body: Any, mutes_body: Any) -> list[tuple[str, dict]]:
    """[("pref" | "mute", row)]: ended preferences and removed mutes, most recently ended first."""
    rows = [("pref", p) for p in ended_preferences(prefs_body)] + [("mute", m) for m in removed_mutes(mutes_body)]
    return sorted(rows, key=lambda kr: parse_time(pick(kr[1], "retired_at", "removed_at", "created_at")),
                  reverse=True)


# ---------------------------------------------------------------------------------------------- the page


def render(ws: Workspace) -> None:
    prefs, prefs_error = attempt(data.preferences, ws.id)
    rules, _ = attempt(data.rules, ws.id)
    mutes, mutes_error = attempt(data.mutes, ws.id, include_removed=True)
    stars, stars_error = attempt(data.stars, ws.id)
    header(ws, prefs)
    ui.locked_hint(ws)
    if prefs_error is None:
        render_ok(ws, prefs, rules)
    render_how_much(ws)
    waiting = {one_line(d.get("id")) for d in needs_ok(prefs, rules)} if prefs_error is None else set()
    render_rules(ws, prefs, prefs_error, mutes, mutes_error, stars, stars_error, waiting)
    render_ended(ws, prefs, mutes)


def header(ws: Workspace, prefs: Any) -> None:
    """'Tuning', 'This week your preferences changed ...' and Refresh; a notice after a refused approval, and how many
    of the analyst's suggestions are still with the wording assistant."""
    with st.container(horizontal=True, key="zx_tuning_head", vertical_alignment="center", gap="small"):
        summary = (f'<div class="pref-text">{esc(summary_sentence(pick(prefs, "summary_7d")))}</div>'
                   if prefs is not None else "")
        st.markdown(f'<div class="tn-head"><div class="tn-title">{esc(TITLE)}</div>{summary}</div>',
                    unsafe_allow_html=True)
        ui.refresh_button("tuning")
    notice = st.session_state.pop(NOTICE_KEY, None)
    if notice:
        st.warning(notice)
    n = waiting_count(prefs) if prefs is not None else 0
    if n:
        st.caption(f"{plural(n, 'suggestion')} you sent {'is' if n == 1 else 'are'} with the wording assistant. "
                   f"{'It comes' if n == 1 else 'They come'} back under Needs your OK once worded.")


def section(title: str) -> None:
    st.markdown(f'<div class="rules-section">{esc(title)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------------------------- Needs your OK


def render_ok(ws: Workspace, prefs: Any, rules: Any) -> None:
    """"Needs your OK · N", only when something waits."""
    cards = needs_ok(prefs, rules)
    if not cards:
        return
    section(f"Needs your OK · {len(cards)}")
    by_id = preferences_by_id(prefs)
    companies = {one_line(d.get("id")): d for d in company_names_view.named(
        [d for d in cards if company_names_view.is_suggestion(d)], lambda: data.brief(ws.id))}
    lines = (brief_lines(ws) if any(origin_of(d) == "brief" for d in cards if one_line(d.get("id")) not in companies)
             else {})
    for draft in cards:
        if one_line(draft.get("id")) in companies:
            company_card(ws, companies[one_line(draft.get("id"))])
        else:
            suggestion_card(ws, draft, by_id, lines)


def brief_lines(ws: Workspace) -> dict[str, str]:
    """{line id: the line as What ZENITH looks for shows it} from GET /brief (cached), so a suggested change names its
    line in the approved words (the draft's context keeps the original words for the wording assistant)."""
    brief, _ = attempt(data.brief, ws.id)
    out: dict[str, str] = {}
    for part_section in dicts(pick(brief, "sections", default=[])):
        for part in dicts(part_section.get("parts")):
            for line in dicts(part.get("lines")):
                if one_line(line.get("id")) and one_line(line.get("text")):
                    out[one_line(line.get("id"))] = one_line(line.get("text"))
    return out


def suggestion_html(draft: Mapping, by_id: Mapping[str, dict], tz: str, lines: Mapping[str, str] | None = None) -> str:
    """The card's head chip, the suggestion (with what it changes, by origin) and its impact line, escaped. The
    ratings behind it and the stories it moves are in Details."""
    origin = origin_of(draft)
    proposed = shown_text(draft)
    when = fmt_date(pick(draft, "proposed_at", "updated_at", "created_at"), tz)
    head = ('<div class="loop-card-head">' + chip(suggestion_head(draft), "suggested")
            + (f'<span class="pref-meta">{esc(when)}</span>' if when and when != "—" else "") + "</div>")
    if origin in ("grades", "radar"):
        body = f'<div class="pref-text">{esc(proposed)}</div>'
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
    else:
        words = one_line(pick(draft, "owner_text", "plain_text", "text"))
        body = ((f'<div class="refine-owner">Your words: {esc(words)}</div>' if words else "")
                + f'<div class="pref-text">Suggested: {esc(proposed)}</div>')
    return (f'<div class="pref-card">{head}{body}'
            f'<div class="preview-line">{esc(impact_line(draft))}</div></div>')


def details_html(draft: Mapping) -> str:
    """The Details expander's read-only part: the ratings behind it, then which stories it would bring in and drop
    out (`preview_items`, at most 50; `preview_more` counts the rest)."""
    html = ""
    lines, more = grade_lines(draft) if origin_of(draft) == "grades" else ([], 0)
    if lines:
        html += ('<div class="refine-label">Your ratings behind it</div><div class="grade-lines">'
                 + "".join(f'<div class="grade-line">{esc(line)}</div>' for line in lines) + "</div>"
                 + (f'<div class="refine-note">and {more} more</div>' if more else ""))
    items = dicts(draft.get("preview_items"))
    for heading, to in (("Would come in", "in"), ("Would drop out", "out")):
        group = [e for e in items if one_line(e.get("to")).lower() == to]
        if not group:
            continue
        html += (f'<div class="refine-label">{esc(heading)} · {len(group)}</div><div class="grade-lines">'
                 + "".join(f'<div class="grade-line">{esc(preview_item_line(e))}</div>' for e in group) + "</div>")
    extra = as_int(draft.get("preview_more")) or 0
    if extra > 0:
        html += f'<div class="refine-note">and {plural(extra, "more story", "more stories")}</div>'
    return html


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
    """One card: the head chip, the suggestion and its impact line, the two buttons, then Details (drawn every run,
    collapsed, so the wording box and the conflict choices count whether or not it was opened)."""
    did = one_line(draft.get("id"))
    approve_label, reject_label = button_labels(draft)
    store = st.session_state.get(AS_NEW_KEY)
    as_new = store.get(did) if isinstance(store, dict) else None
    stale = merge_is_stale(draft, by_id)
    with st.container(border=True, key=f"zx_card_sg_{did}"):
        st.markdown(suggestion_html(draft, by_id, ws.timezone, lines), unsafe_allow_html=True)
        if stale:
            st.caption(MERGE_STALE)
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
        with st.expander("Details", key=f"sg_details_{did}"):
            html = details_html(draft)
            if html:
                st.markdown(html, unsafe_allow_html=True)
            rationale = shown_rationale(draft, by_id)
            if rationale:
                st.caption(md_label(rationale))
            edited = st.text_area(WORDING_LABEL, value=shown_text(draft), key=f"sg_text_{did}", height=100,
                                  max_chars=EDIT_TEXT_MAX, disabled=stale)
            retire = conflict_choices(draft, did, by_id)
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


def company_card(ws: Workspace, row: Mapping) -> None:
    """A suggested company name: the card (company_names_view.card_html), Approve and Reject (which asks first: no
    route reverses it), then Details when the source finder left more to read."""
    sid = one_line(row.get("id"))
    with st.container(border=True, key=f"zx_card_cs_{sid}"):
        st.markdown(company_names_view.card_html(row, ws.timezone), unsafe_allow_html=True)
        with st.container(horizontal=True, key=f"zx_actions_cs_{sid}"):
            approve = ui.write_button(company_names_view.APPROVE_LABEL, ws=ws, key=f"cs_approve_{sid}",
                                      type="primary")
            reject = ui.write_button(company_names_view.REJECT_LABEL, ws=ws, key=f"cs_reject_{sid}", type="tertiary")
        details = company_names_view.details_html(row, ws.timezone)
        if details:
            with st.expander("Details", key=f"cs_details_{sid}"):
                st.markdown(details, unsafe_allow_html=True)
        if approve:
            if decide_company(ws, row, "approve"):
                st.rerun()
        if reject:
            ui.ask_confirm(company_names_view.REJECT_TITLE, company_names_view.REJECT_MESSAGE,
                           company_names_view.REJECT_LABEL, lambda: decide_company(ws, row, "reject"),
                           detail=labels.NO_UNDO)


def decide_company(ws: Workspace, row: Mapping, action: str) -> bool:
    """POST /companies/suggestions/<id>/approve {use} (the version the card shows) or /reject {} (run inside the
    confirmation, which closes and reruns): a toast and no undo (no route reverses either). A 409 suggestion_closed
    re-reads the list and says so at the top. -> True when something changed (the caller reruns)."""
    sid = one_line(row.get("id"))
    use = company_names_view.use_of(row) if action == "approve" else None
    result, handled = brief_view.write_or_handle(
        ws, lambda token: api.company_suggestion_action(ws, token, sid, action, use=use),
        toast=company_names_view.approved_toast(row) if action == "approve" else company_names_view.REJECTED,
        codes=company_names_view.CLOSED_CODES)
    if handled is not None:
        data.clear_reads()
        st.session_state[NOTICE_KEY] = company_names_view.CLOSED
    return handled is not None or result is not None


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
    """One row: the three choices, the near-miss switch, the preview line and Use this setting."""
    section("How much")
    try:
        settings = data.settings(ws.id)
    except api.ApiError as exc:
        ui.error_box("your 'how much' setting", exc, key="tn_settings")
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
    with st.container(horizontal=True, key="zx_how_much", vertical_alignment="center", gap="small"):
        mode = st.segmented_control("How many stories per briefing?", modes, key=VOLUME_MODE_KEY, required=True,
                                    format_func=lambda m: volume_label(m, names), label_visibility="collapsed",
                                    wrap=True)  # on a phone the choices wrap instead of hiding off the edge
        shelf = st.toggle(SHELF_LABEL, key=VOLUME_SHELF_KEY)
        chosen = (mode if mode in modes else saved_mode, bool(shelf))
        unchanged = chosen == saved
        if unchanged:
            text = join(labels.volume_help(chosen[0], caps.get(chosen[0])), VOLUME_CURRENT)
        else:
            try:
                preview = data.volume_preview(ws.id, chosen[0], chosen[1])
                text = one_line(pick(preview, "text")) or VOLUME_NO_PREVIEW
            except api.ApiError as exc:
                text = ui.plain_error(exc)[0]
        st.markdown(f'<div class="preview-line tn-preview">{esc(text)}</div>', unsafe_allow_html=True)
        if unchanged:
            save = False
            st.button("Use this setting", key="tn_volume_save", disabled=True, help="Choose a different setting first.")
        else:
            save = ui.write_button("Use this setting", ws=ws, key="tn_volume_save", type="primary")
    st.caption(VOLUME_CAPTION)
    if save:
        new_mode, new_shelf = chosen
        result = ui.write(
            ws, lambda token: api.set_volume(ws, token, new_mode, near_miss_shelf=new_shelf),
            toast=lambda answer: join(f"Now: {volume_label(new_mode, names)}.", effective(answer, ws)),
            undo=lambda answer: ("Changed how much you see.",
                                 lambda token: api.set_volume(ws, token, saved_mode, near_miss_shelf=saved_shelf)))
        if result is not None:
            st.rerun()


# ---------------------------------------------------------------------------------------------- Your rules


def _filter_changed() -> None:
    value = st.session_state.get(RULES_KEY)
    links.set_focus(rules=value if value in RULE_FILTER_NAMES and value != "all" else None)


def current_filter(focus_pref: str) -> None:
    """Set the pill before it is drawn: a `rules` link (Briefing's "See your mutes", an old `section=muted` link)
    selects its filter; a new `pref` link shows All, so its row is in view; otherwise the analyst's choice stays (All
    at first). The analyst's own choice is mirrored into the link by the pills' callback, so the two never disagree."""
    want = links.focus("rules")
    want = want if want in RULE_FILTER_NAMES else None
    if focus_pref and st.session_state.get(PREF_SEEN_KEY) != focus_pref:
        st.session_state[PREF_SEEN_KEY] = focus_pref
        want = want or "all"
    if want and st.session_state.get(RULES_KEY) != want:
        st.session_state[RULES_KEY] = want
    elif st.session_state.get(RULES_KEY) not in RULE_FILTER_NAMES:
        st.session_state[RULES_KEY] = "all"


def open_add(ws: Workspace) -> None:
    ui.open_dialog("add_rule", workspace_id=ws.id)


def render_rules(ws: Workspace, prefs: Any, prefs_error: api.ApiError | None, mutes: Any,
                 mutes_error: api.ApiError | None, stars: Any, stars_error: api.ApiError | None,
                 waiting: set[str] | None = None) -> None:
    """"Your rules · N": the pills, + Add a rule, and one row per rule with its ⋯ menu (`waiting`: the ids of the
    Needs your OK cards, for the "a clearer wording is waiting" hint)."""
    rules = rules_of(prefs, mutes, stars)
    counts: dict[str, int | None] = dict(filter_counts(rules))
    if prefs_error is not None:
        counts.update(all=None, more=None, less=None)
    if mutes_error is not None:
        counts.update(all=None, muted=None)
    if stars_error is not None:
        counts.update(all=None, watchlist=None)
    total = counts.get("all")
    section(f"Your rules · {total}" if total is not None else "Your rules")
    focus = one_line(links.focus("pref"))
    current_filter(focus)
    with st.container(horizontal=True, key="zx_rules_bar", vertical_alignment="center", gap="small"):
        code = st.pills("Show", [c for c, _ in RULE_FILTERS], key=RULES_KEY, selection_mode="single", required=True,
                        format_func=lambda c: filter_label(c, counts), on_change=_filter_changed,
                        label_visibility="collapsed", wrap=True)
        ui.write_button(f"+ {ADD_LABEL}", ws=ws, key="tn_add", type="secondary", on_click=open_add, args=(ws,))
    code = code if code in RULE_FILTER_NAMES else "all"
    if code in FILTER_NOTES:
        st.caption(FILTER_NOTES[code])
    if code in ("muted", "watchlist"):
        st.button("Open Coverage", key="tn_open_coverage", type="tertiary", icon=":material/arrow_forward:",
                  on_click=links.go, args=("coverage",))
    warning = soft_cap_text(pick(prefs, "soft_cap")) if prefs is not None else ""
    if warning and code in ("all", "more", "less"):
        st.info(md_label(warning))
    for exc, what, key, codes in ((prefs_error, "your preferences", "preferences", ("all", "more", "less")),
                                  (mutes_error, "your mutes", "tn_mutes", ("all", "muted")),
                                  (stars_error, "your watchlist", "tn_stars", ("all", "watchlist"))):
        if exc is not None and code in codes:
            ui.error_box(what, exc, key=key)
    shown = filtered_rules(rules, code, focus)
    if not shown and not any(e is not None for e in (prefs_error, mutes_error, stars_error)):
        st.markdown(empty_state(EMPTY_FILTER.get(code, EMPTY_RULES)), unsafe_allow_html=True)
    for rule in shown:
        rule_row(ws, rule, focused=bool(focus) and rule["kind"] == "pref" and rule["id"] == focus, waiting=waiting)


def rule_row(ws: Workspace, rule: Mapping, *, focused: bool = False, waiting: set[str] | None = None) -> None:
    """One rule: its words on the left, its ⋯ menu on the right."""
    ident = f"{rule['kind']}_{rule['id']}"
    with st.container(horizontal=True, key=f"zx_rule_{ident}", vertical_alignment="top", gap="small"):
        st.markdown(rule_html(rule, ws.timezone, focused, waiting), unsafe_allow_html=True)
        # the ⋯ menu: its words stay the label for screen readers (feed.css shows only the icon)
        menu = st.popover(MENU_LABEL, key=f"tn_menu_{ident}", on_change="rerun", type="tertiary",
                          icon=":material/more_horiz:", help="What you can do with this rule")
        with menu:
            if menu.open:
                rule_menu(ws, rule, f"tn_menu_{ident}")


def rule_menu(ws: Workspace, rule: Mapping, pop: str) -> None:
    """The ⋯ menu's items (drawn only while it is open); each closes the menu and opens its dialog or writes, in its
    button's callback (ui.menu_item)."""
    row = rule["row"]
    ident = f"{rule['kind']}_{rule['id']}"
    if rule["kind"] == "pref":
        if status_of(row) == "paused":
            ui.menu_item("Resume", ws=ws, key=f"tn_resume_{ident}", popover_key=pop, action=resume, args=(ws, row))
        ui.menu_item("Edit", ws=ws, key=f"tn_edit_{ident}", popover_key=pop, action=ui.open_dialog,
                     args=("pref_edit",), kwargs={"workspace_id": ws.id, "pref": dict(row)})
        ui.menu_item("End date", ws=ws, key=f"tn_end_{ident}", popover_key=pop, action=ui.open_dialog,
                     args=("pref_end",), kwargs={"workspace_id": ws.id, "pref": dict(row)})
        ui.menu_item("Remove", ws=ws, key=f"tn_remove_{ident}", popover_key=pop, action=confirm_remove,
                     args=(ws, row))
        mute = looks_like_mute(row)
        if mute:
            label = one_line(pick(mute, "label", "ref"))
            ui.menu_item(f"Mute {label} instead", ws=ws, key=f"tn_mute_instead_{ident}", popover_key=pop,
                         action=actions.open_mute, args=(ws,),
                         kwargs={"kind": one_line(mute.get("kind")), "ref": one_line(mute.get("ref")), "label": label,
                                 "module": one_line(mute.get("module")) or None})
    elif rule["kind"] == "mute":
        ui.menu_item("Unmute", ws=ws, key=f"tn_unmute_{ident}", popover_key=pop, action=actions.open_unmute,
                     args=(ws, dict(row)))
        st.caption(labels.STILL_COLLECTED)
    else:
        entity_id = one_line(row.get("entity_id"))
        name = one_line(pick(row, "label", "name", "entity_id"))
        ui.menu_item("Remove from watchlist", ws=ws, key=f"tn_unstar_{ident}", popover_key=pop, action=actions.unstar,
                     args=(ws, entity_id, name), kwargs={"rerun": False})


def resume(ws: Workspace, pref: Mapping) -> None:
    """Resume a paused preference (a menu item's callback); Undo pauses it again."""
    pid = one_line(pref.get("id"))
    ui.write(ws, lambda token: api.rule_action(ws, token, pid, "resume", {}),
             toast=lambda answer: join("Resumed.", effective(answer, ws)),
             undo=lambda answer: ("Resumed a preference.", lambda token: api.rule_action(ws, token, pid, "pause", {})),
             in_callback=True)


def confirm_remove(ws: Workspace, pref: Mapping) -> None:
    pid = one_line(pref.get("id"))

    def remove() -> None:
        ui.write(ws, lambda token: api.rule_action(ws, token, pid, "retire", {}), toast="Removed.",
                 undo=lambda answer: ("Removed a preference.",
                                      lambda token: api.rule_action(ws, token, pid, "reactivate", {})))

    ui.ask_confirm(REMOVE_TITLE, REMOVE_MESSAGE, "Remove", remove, danger=True, detail=remove_detail(pref))


# ---------------------------------------------------------------------------------------------- Ended


def render_ended(ws: Workspace, prefs: Any, mutes: Any) -> None:
    """"Ended · N", collapsed and lazy: ended preferences (Bring back) and removed mutes (Bring back the last 7 days),
    the most recently ended first, 100 at most. A link to an ended preference opens it once."""
    rows = ended_rows(prefs, mutes)
    if not rows:
        return
    focus = one_line(links.focus("pref"))
    ids = [one_line(r.get("id")) for kind, r in rows if kind == "pref"]
    if focus and focus in ids and st.session_state.get(ENDED_FOCUS_KEY) != focus:
        st.session_state[ENDED_KEY] = True  # a link to an ended preference opens the list once
        st.session_state[ENDED_FOCUS_KEY] = focus
    box = st.expander(f"Ended · {len(rows)}", key=ENDED_KEY, on_change="rerun")
    if not box.open:
        return
    if focus in ids:
        rows = sorted(rows, key=lambda kr: not (kr[0] == "pref" and one_line(kr[1].get("id")) == focus))
    with box:
        for kind, row in rows[:ENDED_MAX]:
            if kind == "pref":
                ended_preference(ws, row, focused=one_line(row.get("id")) == focus)
            else:
                ended_mute(ws, row)
        if len(rows) > ENDED_MAX:
            st.caption(f"and {len(rows) - ENDED_MAX} more ended earlier")


def ended_preference(ws: Workspace, pref: Mapping, *, focused: bool = False) -> None:
    pid = one_line(pref.get("id"))
    when = fmt_date(pref.get("retired_at"), ws.timezone) if pref.get("retired_at") else ""
    meta = " · ".join(p for p in (kind_label(pref), ended_reason(pref), when if when != "—" else "") if p)
    with st.container(horizontal=True, key=f"zx_ended_pref_{pid}", vertical_alignment="center", gap="small"):
        st.markdown(f'<div class="pref-card{" zx-focus" if focused else ""}">'
                    f'<div class="pref-text">{esc(labels.preference_text(pref))}</div>'
                    f'<div class="pref-meta">{esc(meta)}</div></div>', unsafe_allow_html=True)
        if ui.write_button("Bring back", ws=ws, key=f"pf_bring_back_{pid}", type="tertiary"):
            bring_back_preference(ws, pref)


def ended_mute(ws: Workspace, mute: Mapping) -> None:
    mid = one_line(mute.get("id"))
    when = fmt_date(mute.get("removed_at"), ws.timezone) if mute.get("removed_at") else ""
    meta = " · ".join(p for p in (MUTE_KIND_CHIPS.get(one_line(mute.get("kind")), "Muted"),
                                  f"removed {when}" if when and when != "—" else "") if p)
    with st.container(horizontal=True, key=f"zx_ended_mute_{mid}", vertical_alignment="center", gap="small"):
        st.markdown(f'<div class="pref-card"><div class="pref-text">{esc(one_line(pick(mute, "label", "ref")))}</div>'
                    f'<div class="pref-meta">{esc(meta)}</div></div>', unsafe_allow_html=True)
        if mute.get("brought_back"):
            st.caption("Brought back")
        elif ui.write_button("Bring back the last 7 days", ws=ws, key=f"pf_bring_back_m{mid}", type="tertiary"):
            actions.bring_back(ws, mute)


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


def add_rule_dialog(workspace_id: str) -> None:
    """+ Add a rule: more, less or exactly as I write it, in the analyst's own words, optionally only for a while; a
    standing preference, active at once (Undo ends it)."""
    ws = workspace_of(workspace_id)
    if ws is None:
        ws_missing()
        return
    earliest, default, latest = day_bounds(ws.timezone)
    direction = st.radio("What do you want?", DIRECTIONS, key="dlg_direction", format_func=labels.direction_label)
    text = st.text_area("In your own words", key="dlg_text", height=90, max_chars=ADD_TEXT_MAX,
                        placeholder=ADD_PLACEHOLDER)
    until = None
    if st.checkbox("Only for a while", key="dlg_until_on"):
        until = st.date_input("Until", value=default, min_value=earliest, max_value=latest, key="dlg_until")
    save, cancel = dialog_buttons(ws, "Add")
    st.caption(actions.ACTIVE_AT_ONCE)
    if cancel:
        close_and_rerun()
    if not save:
        return
    clean = (text or "").strip()
    if len(one_line(clean)) < TEXT_MIN:
        st.info(TOO_SHORT)
        return
    expires = expires_iso(until, ws.timezone) if isinstance(until, date) else None
    chosen = direction if direction in DIRECTIONS else "more"
    result = ui.write(
        ws, lambda token: api.add_preference(ws, token, direction=chosen, scope="standing", text=clean,
                                             expires_at=expires),
        toast=lambda answer: join(f"Added: {labels.direction_label(chosen)}.", effective(answer, ws)),
        undo=lambda answer: _undo_new(ws, answer, "Added a preference."))
    if result is not None:
        close_and_rerun()


def _undo_new(ws: Workspace, answer: Any, text: str) -> tuple[str, Callable[[str], Any]] | None:
    """Undo a new preference: retire it as undone."""
    new_id = one_line(pick(answer, "preference.id", "precedent.id"))
    if not new_id:
        return None
    return text, lambda token: api.rule_action(ws, token, new_id, "retire", {"reason": "undone"})


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


ui.register_dialog("add_rule", ADD_LABEL, add_rule_dialog, width="medium")
ui.register_dialog("pref_edit", "Edit preference", edit_dialog, width="medium")
ui.register_dialog("pref_end", "End date", end_date_dialog, width="small")
ui.register_dialog("pref_reactivate", "Bring it back", reactivate_dialog, width="small")
