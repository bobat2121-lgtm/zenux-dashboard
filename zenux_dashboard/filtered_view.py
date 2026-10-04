"""Filtered out: stories that did not make a briefing (GET /rejected), one view at a time.

Views (docs/SPEC-PHASE03-UI.md section 6; the hub's views of docs/SPEC-PHASE05.md section 2), picked with the "Show"
control (each choice carries the view's true count from the answer's `views`) and mirrored as `view` in the page link:

- near "Near misses" (default): filter=near_miss, the editor's rejections scored within 10 of the bar in force for
  that run (the watch band, cut for space, below the "how much" setting), best score first.
- all "All": filter=all with the hub's own decisions (old news, mutes), newest first.
- same "Same story": filter=same_story, duplicates and already-reported stories, each with the story it repeats
  (`canonical`) and, when a briefing ran that story, a "Show it" link into Briefing.
- muted "Muted": filter=muted, what the analyst's mutes kept out, under the list of mutes (Unmute with the bring-back
  preview and choice, and Bring back on a removed mute).
- old "Old news": filter=old_news, the hub's old-news rule and the editor's old-news rejections.

Sort (on the count line, right above the list): Newest first (by the story's own date, the one on each row), Highest
score first or Lowest score first. Changing the view resets it to the view's own order (Near misses: highest first; the
rest: newest first). Every order covers the whole window: the hub pages by when the editor decided, so the view's pages
are all read first (up to MAX_PAGES) and sorted here; stories without a score come last in a score order.

The hub does the work: one row per story, the true `total`, the search box sent as `q` (every word must match the
title, the editor's reasoning, the source's name, the publisher or a company, over the whole window), the coverage-area
filter as `module`, and pages of up to 500 (`offset`). Rows show 50 at a time; "Show 50 more" reads the next page when
the loaded ones are all shown. A row a later briefing published after all (`published_later`) says so, with Show it.
Every per-row action (More or Less like this, Should have been in, mute, star, rate, Why) comes from `actions`, the
card-actions module the Briefing uses; writes need Sign in to edit. Nothing on this page shows an event id, a source
key, a coverage-area id or a reason code: sources go by the hub's plain name (`source_label`, never the key), areas by
`labels.area_name`, reasons by `labels.reason_label`, the editor's reasoning by `rationale_plain`.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping

import streamlit as st

from . import actions, api, data, labels, links, ui
from .config import MODULE_ID_RE, Workspace
from .fmt import (as_int, as_list, chip, dicts, domain_of, empty_state, esc, fmt_date, link, module_color, one_line,
                  parse_time, pick, plural, tag_style)

VIEWS: tuple[tuple[str, str], ...] = (("near", "Near misses"), ("all", "All"), ("same", "Same story"),
                                      ("muted", "Muted"), ("old", "Old news"))
VIEW_LABELS = dict(VIEWS)
DEFAULT_VIEW = "near"
# view -> (the hub's filter, include_auto, the answer's `views` key that counts it)
VIEW_READS: dict[str, tuple[str, bool, str]] = {
    "near": ("near_miss", False, "near_miss"),
    "all": ("all", True, "all_with_auto"),
    "same": ("same_story", False, "same_story"),
    "muted": ("muted", False, "muted"),
    "old": ("old_news", False, "old_news"),
}
DAYS = (1, 3, 7, 14, 30)
DEFAULT_DAYS = 3
PAGE = 50
ROW_CAP = api.REJECTED_LIMIT   # one GET /rejected page
MAX_PAGES = 20                 # at most this many pages are read for one view (10,000 stories)
ALL_AREAS = ""                 # the "All areas" choice of the coverage-area filter

SORTS: tuple[tuple[str, str], ...] = (("newest", "Newest first"), ("high", "Highest score first"),
                                      ("low", "Lowest score first"))
SORT_LABELS = dict(SORTS)
VIEW_SORT = {"near": "high"}           # a view's own order; every other view: newest first
BY_SCORE = ("high", "low")

VIEW_KEY = "fo_view"
SORT_KEY = "fo_sort"
SEARCH_KEY = "fo_search"
DAYS_KEY = "fo_days"
AREA_KEY = "fo_area"
MORE_KEY = "fo_more"
LIMIT_KEY = "fo_limit"           # (signature of the list shown, rows shown): Show 50 more appends to it
SAVED_KEY = "fo_saved"           # {widget key: value}: days, area and search, kept while another tab is shown
REMOVED_KEY = "fo_removed_mutes"  # the lazy "Removed mutes" expander

INTRO = {
    "near": "Stories that scored just under your bar at the time, best first, including stories cut for space or "
            "below your \"how much\" setting.",
    "all": "Everything left out of your briefings, newest first.",
    "same": "Stories left out because your briefing already had the same story.",
    "muted": "Stories your mutes kept out. " + labels.STILL_COLLECTED,
    "old": "Stories left out because they were already old: too old when they arrived, or old news reposted.",
}
EMPTY = {
    "near": "No near misses in the {last}.",
    "all": "Nothing was left out in the {last}.",
    "same": "No repeated stories in the {last}.",
    "muted": "Your mutes hid nothing in the {last}.",
    "old": "No old news was filtered out in the {last}.",
}
NO_MATCH = "No filtered-out story matches your search. Try another word, or choose more days."
MUTE_GROUPS: tuple[tuple[str, str], ...] = (("source", "Sources"), ("entity", "Companies"), ("story", "Stories"))
REQUESTED = "You asked for this · re-checked at the next briefing"
LATER = "Later in your briefing"
PROMOTE_NOTE = "Should have been in"   # the hub's prefix on the rating a "Should have been in" stores
AUTO_OLD = "It was already old when it arrived, so the ZENUX editor never saw it."
CALIBRATED_RE = re.compile(r"calibrated:\s*owner grade #(\d+)", re.IGNORECASE)
RULE_NOTE_RE = re.compile(r"\s*\(rule\s+[^)]*\)", re.IGNORECASE)


# ---------------------------------------------------------------------------------------------- row fields


def rows_of(body: Any) -> list[dict]:
    """The rows of a GET /rejected answer (a bare list is accepted too)."""
    if isinstance(body, list):
        return dicts(body)
    return dicts(pick(body, "items", "rejected", "decisions", "rows", default=[]))


def event_id_of(row: Mapping) -> int | None:
    return as_int(row.get("event_id"))


def decision_of(row: Mapping) -> str:
    return one_line(row.get("decision")) or "rejected"


def reason_code_of(row: Mapping) -> str:
    return one_line(row.get("reason_code"))


def area_of(row: Mapping) -> str:
    return one_line(pick(row, "module", "module_id"))


def is_auto(row: Mapping) -> bool:
    """Decided by the hub's own rule (old news, a mute), not by the ZENUX editor."""
    return row.get("auto") is True


def is_mute_row(row: Mapping) -> bool:
    return one_line(row.get("rule")).startswith("mute:")


def score_of(row: Mapping) -> int | None:
    return as_int(row.get("score"))


def decided_ts(row: Mapping) -> float:
    return parse_time(pick(row, "decided_at", "published_at")).timestamp()


def reason_text(row: Mapping) -> str:
    return labels.reason_label(row.get("reason_code"), row.get("reason"))


def source_label(row: Mapping) -> str:
    """The source's plain name: the hub's `source_label` (never the key), guarded against a label that is only the
    key; then the link's domain; '' when neither is known."""
    label = one_line(row.get("source_label"))
    key = one_line(row.get("source_key"))
    if label and label != key:
        return label
    return domain_of(row.get("url"))


def subjects_of(row: Mapping) -> list[dict]:
    return [s for s in dicts(row.get("subjects")) if one_line(s.get("name"))]


def muted_of(row: Mapping) -> dict | None:
    muted = row.get("muted")
    return dict(muted) if isinstance(muted, Mapping) else None


def requested_of(row: Mapping) -> dict | None:
    """An open "Should have been in" request on the row's story, else None."""
    req = row.get("requested")
    if isinstance(req, Mapping) and one_line(req.get("reason")) == "promote":
        return dict(req)
    return None


def canonical_of(row: Mapping) -> dict | None:
    """The story a repeated row repeats (`canonical`: {event_id, title, url, story_id, briefing}), or None."""
    canonical = row.get("canonical")
    return dict(canonical) if isinstance(canonical, Mapping) else None


def briefing_of(value: Any) -> dict | None:
    """A {edition_id, item_id, headline, published_at, briefing_label} that can be opened, else None."""
    if isinstance(value, Mapping) and as_int(value.get("edition_id")) is not None:
        return dict(value)
    return None


def later_of(row: Mapping) -> dict | None:
    """The later briefing that published this very story after all (`published_later`), else None."""
    return briefing_of(row.get("published_later"))


def newest_rating(row: Mapping) -> str | None:
    """The verdict of the analyst's newest plain rating of this story (a "Should have been in" note is not a rating
    here: the requested chip shows it)."""
    best: tuple[float, int, str] | None = None
    for n, fb in enumerate(dicts(row.get("feedback"))):
        verdict = one_line(fb.get("verdict"))
        if verdict not in labels.RATING_CHOICES or one_line(fb.get("note")).startswith(PROMOTE_NOTE):
            continue
        key = (parse_time(fb.get("created_at")).timestamp(), n, verdict)
        if best is None or key[:2] >= best[:2]:
            best = key
    return best[2] if best else None


def calibrated_ids(rationale: Any) -> list[int]:
    return [int(m.group(1)) for m in CALIBRATED_RE.finditer(one_line(rationale))]


def auto_rationale(row: Mapping) -> str:
    """The hub's sentence on an automatic decision in plain words (`rationale_plain`; the rule's name is dropped
    from an older text too): "Published Aug 1, 2026, 63 days before Oct 3, 2026; older than the 21-day freshness
    line." """
    return RULE_NOTE_RE.sub("", one_line(row.get("rationale_plain")) or one_line(row.get("rationale"))).strip()


def last_days(days: int) -> str:
    return "last day" if days == 1 else f"last {days} days"


def days_label(days: int) -> str:
    return "Last day" if days == 1 else f"Last {days} days"


# ---------------------------------------------------------------------------------------------- views


def unique_rows(rows: Iterable[Mapping]) -> list[dict]:
    """The rows that can be drawn: the hub sends one row per story; a row without an event id is dropped (no action
    could target it, and widget keys are built from the id), and a repeated id (two pages that overlap while the
    window moves) keeps its first row."""
    seen: set[int] = set()
    out = []
    for row in rows:
        eid = event_id_of(row)
        if eid is None or eid in seen:
            continue
        seen.add(eid)
        out.append(dict(row))
    return out


def default_sort(view: str) -> str:
    return VIEW_SORT.get(view, "newest")


def story_ts(row: Mapping) -> float:
    """The story's own date, the one its row shows (published, else when it was decided)."""
    return parse_time(pick(row, "published_at", "decided_at")).timestamp()


def view_rows(view: str, rows: Iterable[Mapping], sort: str | None = None) -> list[dict]:
    """The view's rows in the chosen order (the view's own when none): highest or lowest score first (unknown scores
    last, then the newest), or newest first by the story's own date (not the hub's order, which is when the editor
    decided)."""
    rows = unique_rows(rows)
    sort = sort if sort in SORT_LABELS else default_sort(view)
    if sort == "high":
        return sorted(rows, key=lambda r: (score_of(r) is None, -(score_of(r) or 0), -decided_ts(r),
                                           -(event_id_of(r) or 0)))
    if sort == "low":
        return sorted(rows, key=lambda r: (score_of(r) is None, score_of(r) or 0, -decided_ts(r),
                                           -(event_id_of(r) or 0)))
    return sorted(rows, key=lambda r: (-story_ts(r), -(event_id_of(r) or 0)))


def area_options(ws: Workspace, rows: Iterable[Mapping], current: str) -> list[str]:
    """The coverage areas to filter by (configured, present in the rows, or chosen), by plain name."""
    found = {m.id for m in ws.modules} | {area_of(r) for r in rows if area_of(r)}
    if current:
        found.add(current)
    return sorted(found, key=lambda m: (labels.area_name(m).casefold(), m))


def count_line(*, shown: int, total: int, days: int, loaded: int, query: str = "", near: bool = False,
               sort: str = "high") -> str:
    """The count line (6.1), from the hub's true total: what is shown out of every story of the view (with the search
    and the coverage area), and, for a score order over a view not all loaded (`near`), that the order covers the
    loaded ones."""
    if query:
        text = f"{plural(total, 'story matches', 'stories match')} “{query}”"
        if shown < total:
            text += f" · showing {shown}"
    else:
        text = f"Showing {shown} of {plural(total, 'story', 'stories')}"
    text += f" · {last_days(days)}"
    if near and loaded < total:
        first = {"low": "lowest", "newest": "newest"}.get(sort, "best")
        text += f" · {first} first among the newest {loaded}"
    return text


def view_label(view: str, counts: Mapping[str, Any]) -> str:
    """'Near misses · 12': the view's true count over the window (before the search and the area)."""
    n = as_int(counts.get(VIEW_READS[view][2])) if view in VIEW_READS else None
    name = VIEW_LABELS.get(view, str(view))
    return f"{name} · {n}" if n is not None else name


# ---------------------------------------------------------------------------------------------- html


def area_tag(module_id: str) -> str:
    return (f'<span class="module-tag" style="{tag_style(module_color(module_id))}">'
            f'{esc(labels.area_name(module_id).upper())}</span>')


def dateline_html(row: Mapping, tz: str) -> str:
    date = fmt_date(pick(row, "published_at", "decided_at"), tz)
    label = source_label(row)
    # WF5 AW-1: a news-search story names its outlet ("Yahoo Finance via News search: ...").
    source = actions.with_outlet(label, actions.outlet_of(row.get("publisher"), row.get("publisher_domain"), label)[0])
    parts = [p for p in (date if date not in ("", "—") else "", source) if p]
    area = area_of(row)
    text = esc(" · ".join(parts))
    tag = (" · " if text else "") + area_tag(area) if area else ""
    return f'<div class="feed-dateline">{text}{tag}</div>' if text or tag else ""


def score_chip(row: Mapping) -> str:
    """'Score 74 of 100 · bar 80': the score and the bar in force for that run (the words of the Why row)."""
    score = score_of(row)
    if score is None:
        return ""
    bar = as_int(row.get("bar"))
    text = f"Score {score} of 100" + (f" · bar {bar}" if bar is not None else "")
    return f'<span class="rejected-chip score">{esc(text)}</span>'


def chips_html(row: Mapping, view: str, later: bool = False) -> str:
    """The plain reason, then the state chips. In the Muted view the "Muted" chip stands in for the reason when the
    reason is the mute itself ("Muted by you" twice says nothing more); in the Same story view the "Same story as:
    <headline>" line stands in for a "Same story as another" reason when the hub names the story. A scored story's
    chip reads "Score 74 of 100 · bar 80" in every view. `later`: a later briefing published it."""
    out = []
    reason = reason_text(row)
    named = bool(one_line(pick(canonical_of(row) or {}, "title")))
    doubled = (view == "muted" and reason_code_of(row) == "muted") or (
        view == "same" and named and reason == labels.REASON_LABELS["duplicate"])
    if not doubled:
        out.append(f'<span class="rejected-chip">{esc(reason)}</span>')
    # the score and the bar in force, in every view, so a score order shows what it sorts by (a story the hub decided
    # itself, old news or muted, has none)
    out.append(score_chip(row))
    if view == "muted":
        out.append(chip("Muted", "chip-state chip-muted"))
    if later:
        out.append(chip(LATER, "chip-state chip-corrected"))
    elif requested_of(row):
        out.append(chip(REQUESTED, "chip-state chip-requested"))
    rating = newest_rating(row)
    if rating:
        out.append(chip(f"You rated it: {labels.VERDICT_LABELS.get(rating, rating)}", "grade"))
    if any(s.get("starred") is True for s in subjects_of(row)):
        out.append(chip("On your watchlist", "chip-state chip-starred"))
    return f'<div class="rejected-signals">{"".join(out)}</div>'


def same_html(row: Mapping) -> str:
    """'Same story as: <headline> · in your Sat Oct 3 · morning briefing', from the hub's `canonical`; '' when the hub
    names no story."""
    canonical = canonical_of(row) or {}
    title = one_line(canonical.get("title"))
    if not title:
        return ""
    briefing = briefing_of(canonical.get("briefing"))
    name = one_line(briefing.get("briefing_label")) if briefing else ""
    where = f" · in your {name}" if name else (" · in your briefing" if briefing else "")
    return f'<div class="rejected-rationale">Same story as: <strong>{esc(title)}</strong>{esc(where)}</div>'


def row_html(row: Mapping, view: str, tz: str, later: bool = False) -> str:
    """One filtered-out story: title (linked), dateline, the plain reason and state chips; for Same story the story
    it repeats. The editor's reasoning stays inside Why."""
    title = one_line(row.get("title")) or "Untitled story"
    title_html = link(row.get("url"), title, "filtered-link")
    extra = same_html(row) if view == "same" else ""
    return (
        '<article class="filtered-row">'
        f'<div class="rejected-title">{title_html}</div>'
        f'{dateline_html(row, tz)}{chips_html(row, view, later)}{extra}'
        '</article>'
    )


# ---------------------------------------------------------------------------------------------- why


def why_of(row: Mapping) -> dict:
    """The row as a `why` mapping for actions.why_expander (the shape of an item's `why`, SPEC-PHASE02 5.11): the
    preferences it cites with their words (`rules_detail`; bare ids from an older hub are looked up when the expander
    opens), the editor's reasoning in plain words, the source's name and group. An automatic decision has no editor's
    reasoning: its sentence goes in the extra lines instead."""
    detail = [dict(r) for r in dicts(row.get("rules_detail")) if one_line(r.get("id"))]
    rules = detail or [one_line(rid) for rid in as_list(row.get("rules")) if one_line(rid)]
    requested = requested_of(row)
    promoted = ({"note": one_line(requested.get("note")), "requested_at": requested.get("requested_at")}
                if requested and one_line(requested.get("note")) else None)
    subjects = subjects_of(row)
    auto = is_auto(row)
    return {
        "reason_code": row.get("reason_code"),
        "reason": row.get("reason"),
        "score": score_of(row),
        "rationale": None if auto else row.get("rationale"),
        "rationale_plain": None if auto else row.get("rationale_plain"),
        "rules": rules,
        "calibrated_by": [] if auto else calibrated_ids(row.get("rationale")),
        "stars": [{"entity_id": s.get("entity_id"), "name": s.get("name")} for s in subjects if s.get("starred")],
        "subjects": subjects,
        "promoted": promoted,
        "source": {"module": area_of(row) or None, "label": source_label(row) or None,
                   "lane_label": one_line(row.get("lane_label")) or None},
    }


def extra_of(row: Mapping) -> list[tuple[str, str]]:
    """Why lines only this page has: the mute that hid the story, or the old-news sentence."""
    out: list[tuple[str, str]] = []
    muted = muted_of(row)
    if muted and one_line(muted.get("label")):
        label = one_line(muted.get("label"))
        out.append(("Muted by you", label if muted.get("active") is not False else f"{label} (unmuted since)"))
    elif is_auto(row) and not is_mute_row(row):
        out.append(("Filtered automatically", auto_rationale(row) or AUTO_OLD))
    return out


# ---------------------------------------------------------------------------------------------- state


def _view_changed() -> None:
    view = st.session_state.get(VIEW_KEY) or DEFAULT_VIEW
    links.set_focus(view=view)
    st.session_state[SORT_KEY] = default_sort(view)  # a new view starts in its own order


def current_view() -> str:
    """The view: a link (or another tab's "Show what they hid") wins over the remembered choice; the control's own
    changes reach the link state through its on_change callback, so the two never disagree after a click."""
    linked = links.focus("view")
    if linked in VIEW_LABELS and linked != st.session_state.get(VIEW_KEY):
        st.session_state[VIEW_KEY] = linked
    view = remembered(VIEW_KEY, lambda v: v in VIEW_LABELS, DEFAULT_VIEW)
    links.set_focus(view=view)
    return view


def remembered(key: str, ok: Callable[[Any], bool], default: Any) -> Any:
    """A choice of this page: the widget's value, else the one remembered from an earlier run (Streamlit drops a
    widget's state while another tab is shown), else the default. Written back before the widget is drawn."""
    saved = st.session_state.get(SAVED_KEY)
    saved = dict(saved) if isinstance(saved, dict) else {}
    value = st.session_state.get(key)
    if not ok(value):
        value = saved.get(key) if ok(saved.get(key)) else default
    st.session_state[key] = value
    saved[key] = value
    st.session_state[SAVED_KEY] = saved
    return value


def current_sort(view: str) -> str:
    return remembered(SORT_KEY, lambda v: v in SORT_LABELS, default_sort(view))


def current_days() -> int:
    return remembered(DAYS_KEY, lambda v: v in DAYS and not isinstance(v, bool), DEFAULT_DAYS)


def current_query() -> str:
    return one_line(remembered(SEARCH_KEY, lambda v: isinstance(v, str), ""))


def current_area() -> str:
    return remembered(AREA_KEY, lambda v: v == ALL_AREAS or (isinstance(v, str) and bool(MODULE_ID_RE.match(v))),
                      ALL_AREAS)


def read(ws: Workspace, view: str, days: int, *, query: str = "", area: str = "", pages: int = 1) -> dict:
    """The view's read (6.2): the first `pages` pages of GET /rejected for the view, the search and the area, joined:
    {items, total, views, has_more} (total, views and has_more from the hub; has_more after the last page read)."""
    filter_, include_auto, _ = VIEW_READS.get(view, VIEW_READS[DEFAULT_VIEW])
    items: list[dict] = []
    first: Mapping = {}
    more = False
    offset = 0
    for n in range(max(1, min(pages, MAX_PAGES))):
        body = data.rejected(ws.id, days=days, filter=filter_, include_auto=include_auto, q=query, module=area,
                             offset=offset)
        if n == 0:
            first = body if isinstance(body, Mapping) else {}
        page = rows_of(body)
        items.extend(page)
        more = isinstance(body, Mapping) and body.get("has_more") is True
        next_offset = as_int(pick(body, "next_offset")) if isinstance(body, Mapping) else None
        if not more or not page or next_offset is None:
            break
        offset = next_offset
    total = as_int(first.get("total"))
    views = first.get("views") if isinstance(first.get("views"), Mapping) else {}
    return {"items": items, "total": total if total is not None else len(items), "views": dict(views),
            "has_more": more}


def _show_more(signature: tuple, shown: int) -> None:
    st.session_state[LIMIT_KEY] = (signature, shown + PAGE)


def shown_limit(signature: tuple) -> int:
    saved = st.session_state.get(LIMIT_KEY)
    if isinstance(saved, tuple) and len(saved) == 2 and saved[0] == signature and isinstance(saved[1], int):
        return max(PAGE, saved[1])
    return PAGE


# ---------------------------------------------------------------------------------------------- render


def header(options: list[str], days: int, area: str, counts: Mapping[str, Any]) -> None:
    """One row: the Show control (with each view's count), the search box, the Filters popover (days, coverage area)
    and Refresh."""
    show_col, search_col, filter_col, refresh_col = st.columns([4.1, 2.6, 1.2, 1], gap="small",
                                                               vertical_alignment="center")
    with show_col:
        st.segmented_control("Show", [v for v, _ in VIEWS], format_func=lambda v: view_label(v, counts),
                             key=VIEW_KEY, required=True, on_change=_view_changed, label_visibility="collapsed",
                             wrap=True)  # on a phone the five choices wrap instead of hiding off the edge
    with search_col:
        st.text_input("Search filtered-out stories", key=SEARCH_KEY, placeholder="Headline, company or source",
                      label_visibility="collapsed", icon=":material/search:")
    with filter_col:
        active = int(days != DEFAULT_DAYS) + int(area != ALL_AREAS)
        with ui.filters(active, key="fo_filters"):
            st.selectbox("Days", list(DAYS), key=DAYS_KEY, format_func=days_label)
            st.selectbox("Coverage area", [ALL_AREAS] + options, key=AREA_KEY,
                         format_func=lambda m: "All areas" if m == ALL_AREAS else labels.area_name(m))
    with refresh_col:
        ui.refresh_button("filtered")


def mute_html(mute: Mapping, tz: str, removed: bool = False) -> str:
    label = one_line(mute.get("label")) or labels.MUTE_KIND_LABELS.get(one_line(mute.get("kind")), "Mute")
    if removed:
        when = fmt_date(mute.get("removed_at"), tz)
        meta = [f"removed {when}" if when not in ("", "—") else "removed"]
    else:
        when = fmt_date(mute.get("created_at"), tz)
        hid_7d = as_int(mute.get("hidden_7d")) or 0
        hid_total = as_int(mute.get("hidden_total")) or 0
        meta = ([f"since {when}"] if when not in ("", "—") else []) + [f"hid {hid_7d} this week ({hid_total} in all)"]
    note = one_line(mute.get("note"))
    note_html = f'<div class="rejected-rationale">{esc(note)}</div>' if note else ""
    return (f'<div class="filtered-mute"><div class="rejected-title">{esc(label)}</div>'
            f'<div class="feed-dateline">{esc(" · ".join(meta))}</div>{note_html}</div>')


def render_mute(ws: Workspace, mute: dict) -> None:
    mute_id = as_int(mute.get("id"))
    text_col, button_col = st.columns([5, 1.4], vertical_alignment="center")
    with text_col:
        st.markdown(mute_html(mute, ws.timezone), unsafe_allow_html=True)
    with button_col:
        if mute_id is not None and ui.write_button("Unmute", ws=ws, key=f"fo_unmute_{mute_id}"):
            actions.open_unmute(ws, mute)


def render_removed_mute(ws: Workspace, mute: dict) -> None:
    mute_id = as_int(mute.get("id"))
    text_col, button_col = st.columns([5, 2], vertical_alignment="center")
    with text_col:
        st.markdown(mute_html(mute, ws.timezone, removed=True), unsafe_allow_html=True)
    with button_col:
        if mute.get("brought_back") is True:
            st.caption("Brought back")
        elif mute_id is not None and ui.write_button("Bring back the last 7 days", ws=ws,
                                                     key=f"fo_bring_back_{mute_id}"):
            actions.bring_back(ws, mute)


def render_mutes(ws: Workspace) -> None:
    """Your mutes (6.3): active ones by kind with Unmute, then the removed ones (lazy) with Bring back."""
    try:
        body = data.mutes(ws.id, include_removed=True)
    except api.ApiError as exc:
        ui.error_box("your mutes", exc, key="filtered_mutes")
        return
    mutes = [m for m in dicts(pick(body, "mutes", default=[])) if as_int(m.get("id")) is not None]
    on = [m.get("active") is True or m.get("active") == 1 for m in mutes]
    active = sorted((m for m, a in zip(mutes, on) if a), key=lambda m: parse_time(m.get("created_at")), reverse=True)
    removed = sorted((m for m, a in zip(mutes, on) if not a), key=lambda m: parse_time(m.get("removed_at")),
                     reverse=True)
    ui.section("Your mutes", plural(len(active), "active mute") if active else "")
    # the intro right above already says "Still collected, kept out of your briefing."
    st.caption("You can unmute any time and bring back what a mute hid in the last 7 days.")
    total = as_int(pick(body, "total"))
    if pick(body, "has_more") is True:
        st.caption(f"The newest {len(mutes)} of {plural(total or len(mutes), 'mute')} are listed.")
    if not active:
        st.markdown(empty_state("Nothing muted. Use Mute on any story, or Mute on a source or company in Coverage."),
                    unsafe_allow_html=True)
    known = {kind for kind, _ in MUTE_GROUPS}

    def kind_of(mute: Mapping) -> str:
        kind = one_line(mute.get("kind"))
        return kind if kind in known else ""

    for kind, heading in MUTE_GROUPS + (("", "Other"),):
        group = [m for m in active if kind_of(m) == kind]
        if not group:
            continue
        st.markdown(f'<div class="rules-section">{esc(heading)} · {len(group)}</div>', unsafe_allow_html=True)
        for mute in group:
            render_mute(ws, mute)
    if removed:
        box = st.expander(f"Removed mutes · {len(removed)}", key=REMOVED_KEY, on_change="rerun")
        if box.open:
            with box:
                for mute in removed:
                    render_removed_mute(ws, mute)


def render_row(ws: Workspace, row: dict, view: str) -> None:
    """One row card (6.4): its HTML, Show it for a repeated story whose briefing is known (or for one a later
    briefing published), the action bar and the Why expander."""
    eid = event_id_of(row)
    key = f"r{eid}"
    later = later_of(row)
    with st.container(key=f"zx_row_{eid}"):
        st.markdown(row_html(row, view, ws.timezone, later=bool(later)), unsafe_allow_html=True)
        found = briefing_of(pick(canonical_of(row) or {}, "briefing")) if view == "same" else later
        if found:
            focus = {"edition": as_int(found["edition_id"])}
            if as_int(found.get("item_id")) is not None:
                focus["item"] = as_int(found["item_id"])
            # in a callback: it runs before the tab bar is drawn, so the tab can change in this same rerun
            st.button("Show it", key=f"fo_show_{eid}", type="tertiary", icon=":material/arrow_forward:",
                      on_click=links.go, args=("briefing",), kwargs=focus)
        target = actions.target_from_row(ws, row)
        promote = view != "same" and decision_of(row) == "rejected" and not later
        actions.action_bar(ws, target, key=key, promote=promote)
        actions.why_expander(ws, target, why_of(row), key=key, extra=extra_of(row) or None)


def render(ws: Workspace) -> None:
    view = current_view()
    sort = current_sort(view)
    days = current_days()
    query = current_query()
    area = current_area()
    signature = (ws.id, view, days, area, query.casefold(), sort)
    limit = shown_limit(signature)
    # Every order covers the whole window, so every page of the view is read first (up to MAX_PAGES): the hub pages by
    # decision time, which is neither the story's date nor its score.
    pages = MAX_PAGES
    try:
        body, error = read(ws, view, days, query=query, area=area, pages=pages), None
    except api.ApiError as exc:
        body, error = {"items": [], "total": 0, "views": {}, "has_more": False}, exc
    rows = view_rows(view, body["items"], sort)
    header(area_options(ws, rows, area), days, area, body["views"])
    st.caption(INTRO[view])
    if view == "muted":
        render_mutes(ws)
        if error is None:
            ui.section("What they hid")
    if error is not None:
        ui.error_box("filtered-out stories", error, key="filtered")
        return
    total = max(body["total"], len(rows))
    page = rows[:limit]
    counts = count_line(shown=len(page), total=total, days=days, loaded=len(rows), query=query,
                        near=body["has_more"], sort=sort)
    count_col, sort_col = st.columns([5, 1.7], vertical_alignment="center")
    count_col.markdown(f'<div class="rejected-summary">{esc(counts)}</div>', unsafe_allow_html=True)
    with sort_col:
        st.selectbox("Sort", [k for k, _ in SORTS], key=SORT_KEY, format_func=SORT_LABELS.get,
                     label_visibility="collapsed")
    if not page:
        message = EMPTY[view].format(last=last_days(days))
        if query:
            message = NO_MATCH
        elif area:
            message = f"{message.rstrip('.')} in {labels.area_name(area)}."
        st.markdown(empty_state(message), unsafe_allow_html=True)
        return
    for row in page:
        render_row(ws, row, view)
    remaining = total - len(page)
    if remaining > 0 and (len(rows) > len(page) or body["has_more"]):
        st.button(f"Show {min(PAGE, remaining)} more", key=MORE_KEY, on_click=_show_more, args=(signature, limit))
