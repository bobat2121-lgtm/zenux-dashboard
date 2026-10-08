"""Stories left out of a briefing, on the Briefing (docs/SPEC-SIMPLIFY.md 2.2): the shared left-out row and the two
lists built from it.

- The shared row (render_row): the title (linked), the dateline (date · plain source name · coverage-area tag), one
  reason chip, the story icons (thumb up, thumb down, star, and the up arrow where "Should have been in" applies;
  docs/SPEC-ICON-ACTIONS.md, through actions.action_bar), "Show it" when a later briefing published the story (for a
  repeat: the briefing that ran the story it repeats), and the lazy "Why was it left out?", which holds the score and
  the bar in force for that briefing (the row itself has no score chip). The briefing's shelves (watchlist, near
  misses) use it too; a watchlist row keeps "Not about <company>" (WF5 AW-10).
- "Left out of this briefing · N" (render_edition_section): collapsed; it reads GET /rejected?edition_id=N only once
  opened, then lists three groups by the hub's `group` (Near misses, Below your bar, Same story as one in your
  briefings), each best score first, 10 rows and "Show N more", and one caption: "Kept out before the editor read
  them: N muted, N old news." (with a way to the mutes in Tuning). Drawn only for a briefing that carries `left_out`
  (schema 11): an older hub would ignore `edition_id` and answer the last 3 days instead.
- The search's "Left out · N" group (render_search_group): GET /rejected?q=&days=90, 20 rows and "Show more".

Rows are read tolerantly (the GET /rejected rows of docs/SPEC-PHASE05.md 2 and docs/SPEC-SIMPLIFY.md 1.3, and the
shelf rows of GET /editions). Nothing here shows an event id, a source key, a coverage-area id or a reason code:
sources go by the hub's plain name (`source_label`, never the key), areas by labels.area_name, reasons by
labels.reason_label, the editor's reasoning by `rationale_plain`.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

import streamlit as st

from . import actions, api, data, labels, links, ui
from .config import Workspace
from .fmt import (as_int, as_list, chip, dicts, domain_of, esc, fmt_date, link, md_label, module_color, one_line,
                  parse_time, pick, tag_style)

GROUPS: tuple[tuple[str, str], ...] = (("near_miss", "Near misses"), ("below_bar", "Below your bar"),
                                       ("same_story", "Same story as one in your briefings"))
GROUP_NAMES = dict(GROUPS)
SAME_DECISIONS = ("duplicate", "already_covered")
SECTION_LABEL = "Left out of this briefing"
GROUP_PAGE = 10          # rows a group shows before "Show N more"
EDITION_PAGES = 4        # GET /rejected pages (500 each) read for one briefing: a run decides at most a few hundred
SEARCH_PAGE = 20         # the search's left-out rows per "Show more"
SEARCH_DAYS = api.SEARCH_DAYS
SEARCH_GROUP = "Left out"
SEARCH_NONE = "Nothing left out of your briefings of the last 90 days matches your search."
SEARCH_FAILED = "Couldn't search what was left out: {reason}"
AUTO_CAPTION = "Kept out before the editor read them: {muted} muted, {old} old news."
SEE_MUTES = "See your mutes"
LATER = "Later in your briefing"
AUTO_OLD = "It was already old when it arrived, so the ZENITH editor never saw it."
CALIBRATED_RE = re.compile(r"calibrated:\s*owner grade #(\d+)", re.IGNORECASE)
RULE_NOTE_RE = re.compile(r"\s*\(rule\s+[^)]*\)", re.IGNORECASE)
SHOWN_KEY = "lo_shown"   # {(edition id, group): rows shown} and {("search", query): rows shown}


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


def area_of(row: Mapping) -> str:
    return one_line(pick(row, "module", "module_id"))


def is_auto(row: Mapping) -> bool:
    """Decided by the hub's own rule (old news, a mute), not by the ZENITH editor."""
    return row.get("auto") is True


def is_mute_row(row: Mapping) -> bool:
    return one_line(row.get("rule")).startswith("mute:")


def score_of(row: Mapping) -> int | None:
    return as_int(row.get("score"))


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
    """An open "Should have been in" request on the row's story (not cancelled), else None."""
    return actions.requested_of(row.get("requested"))


def canonical_of(row: Mapping) -> dict | None:
    """The story a repeated row repeats (`canonical`: {event_id, title, url, story_id, briefing}, and `label` for one the
    old tracker ran), or None."""
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


def is_same_story(row: Mapping) -> bool:
    return decision_of(row) in SAME_DECISIONS


def calibrated_ids(rationale: Any) -> list[int]:
    return [int(m.group(1)) for m in CALIBRATED_RE.finditer(one_line(rationale))]


def auto_rationale(row: Mapping) -> str:
    """The hub's sentence on an automatic decision in plain words (`rationale_plain`; the rule's name is dropped
    from an older text too)."""
    return RULE_NOTE_RE.sub("", one_line(row.get("rationale_plain")) or one_line(row.get("rationale"))).strip()


def unique_rows(rows: Iterable[Mapping]) -> list[dict]:
    """The rows that can be drawn: one per story; a row without an event id is dropped (no action could target it,
    and widget keys are built from the id), and a repeated id keeps its first row."""
    seen: set[int] = set()
    out = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        eid = event_id_of(row)
        if eid is None or eid in seen:
            continue
        seen.add(eid)
        out.append(dict(row))
    return out


def by_score(rows: Iterable[Mapping]) -> list[dict]:
    """Best score first (unknown scores last), then the newest story, then the newest id."""
    return sorted((dict(r) for r in rows),
                  key=lambda r: (score_of(r) is None, -(score_of(r) or 0),
                                 -parse_time(pick(r, "published_at", "decided_at")).timestamp(),
                                 -(event_id_of(r) or 0)))


def group_of(row: Mapping) -> str:
    """The hub's `group` (near_miss, below_bar, same_story); for a row without one, the same rule worked out here: a
    repeat is the same story, a rejection within 10 of its bar a near miss, any other rejection below the bar."""
    group = one_line(row.get("group"))
    if group in GROUP_NAMES:
        return group
    if is_same_story(row):
        return "same_story"
    score, bar = score_of(row), as_int(row.get("bar"))
    if row.get("near_miss") is True or (score is not None and bar is not None and score >= bar - 10):
        return "near_miss"
    return "below_bar"


def grouped(rows: Iterable[Mapping]) -> dict[str, list[dict]]:
    """{group: its rows, best score first} for every group, in GROUPS order (empty groups included)."""
    out: dict[str, list[dict]] = {g: [] for g, _ in GROUPS}
    for row in unique_rows(rows):
        out[group_of(row)].append(row)
    return {g: by_score(rs) for g, rs in out.items()}


# ---------------------------------------------------------------------------------------------- html


def area_tag(module_id: str) -> str:
    return (f'<span class="module-tag" style="{tag_style(module_color(module_id))}">'
            f'{esc(labels.area_name(module_id).upper())}</span>')


def dateline_html(row: Mapping, tz: str) -> str:
    """'Oct 3 · Data Center Dynamics · AI INFRASTRUCTURE': the story's date, its plain source name (a news-search
    story names its outlet, WF5 AW-1) and its coverage area as a tag."""
    date = fmt_date(pick(row, "published_at", "decided_at"), tz)
    label = source_label(row)
    source = actions.with_outlet(label, actions.outlet_of(row.get("publisher"), row.get("publisher_domain"), label)[0])
    parts = [p for p in (date if date not in ("", "—") else "", source) if p]
    area = area_of(row)
    text = esc(" · ".join(parts))
    tag = (" · " if text else "") + area_tag(area) if area else ""
    return f'<div class="feed-dateline">{text}{tag}</div>' if text or tag else ""


def same_html(row: Mapping) -> str:
    """'Same story as: <headline> · in your Sat Oct 3 · morning briefing', from the hub's `canonical`; '' when the hub
    names no story. A story the old tracker ran (hub schema v14) has no briefing; its `label` says where it ran:
    'Same story as: <headline> · From the old tracker · Sep 20, 2026 · 9am digest'."""
    canonical = canonical_of(row) or {}
    title = one_line(canonical.get("title"))
    if not title:
        return ""
    briefing = briefing_of(canonical.get("briefing"))
    name = one_line(briefing.get("briefing_label")) if briefing else ""
    label = one_line(canonical.get("label"))
    where = (f" · in your {name}" if name else " · in your briefing") if briefing else (f" · {label}" if label else "")
    return f'<div class="rejected-rationale">Same story as: <strong>{esc(title)}</strong>{esc(where)}</div>'


def reason_chip(row: Mapping) -> str:
    """The row's one chip: "Later in your briefing" for a story a later briefing published after all, else the plain
    reason; none for a repeat whose "Same story as" line already names the story it repeats."""
    if later_of(row):
        return chip(LATER, "chip-state chip-corrected")
    if is_same_story(row) and one_line(pick(canonical_of(row) or {}, "title")):
        return ""
    return f'<span class="rejected-chip">{esc(reason_text(row))}</span>'


def tags_html(row: Mapping) -> str:
    """The left of the row's line of chip and icons."""
    return f'<div class="rejected-signals">{reason_chip(row)}</div>'


def row_html(row: Mapping, tz: str) -> str:
    """One left-out story: its title (linked) and dateline, and for a repeat the story it repeats. Its chip shares the
    line under it with the icons (render_row); the editor's reasoning, the score and the bar stay inside Why."""
    title = one_line(row.get("title")) or "Untitled story"
    extra = same_html(row) if is_same_story(row) else ""
    return (
        '<article class="filtered-row">'
        f'<div class="rejected-title">{link(row.get("url"), title, "filtered-link")}</div>'
        f'{dateline_html(row, tz)}{extra}'
        '</article>'
    )


# ---------------------------------------------------------------------------------------------- why


def why_of(row: Mapping) -> dict:
    """The row as a `why` mapping for actions.why_expander (the shape of an item's `why`, SPEC-PHASE02 5.11): the
    reason, the score and the bar in force for that briefing, the preferences it cites with their words
    (`rules_detail`; bare ids from an older hub are looked up when the expander opens), the editor's reasoning in plain
    words, the source's name and group. An automatic decision has no editor's reasoning: its sentence goes in the
    extra lines instead."""
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
        "bar": as_int(row.get("bar")),
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
    """Why lines only a left-out row has: the mute that hid the story, or the old-news sentence."""
    out: list[tuple[str, str]] = []
    muted = muted_of(row)
    if muted and one_line(muted.get("label")):
        label = one_line(muted.get("label"))
        out.append(("Muted by you", label if muted.get("active") is not False else f"{label} (unmuted since)"))
    elif is_auto(row) and not is_mute_row(row):
        out.append(("Filtered automatically", auto_rationale(row) or AUTO_OLD))
    return out


# ---------------------------------------------------------------------------------------------- the shared row


def unique_key(base: str, used: set[str] | None) -> str:
    """A widget key not used yet on this page (the same story can sit on a shelf, in a briefing's left-out list and in
    the search's)."""
    if used is None:
        return base
    key, n = base, 1
    while key in used:
        n += 1
        key = f"{base}_{n}"
    used.add(key)
    return key


def render_row(ws: Workspace, row: Mapping, key: str, *, not_about: bool = False) -> None:
    """One left-out story (its own container, zx_row_<key>): the row HTML, then one line of its chip, Show it (a story
    a later briefing published, or the briefing that ran the story a repeat repeats), "Not about <company>" (a
    watchlist shelf's look-alike names) and the story icons, then "Why was it left out?". `key` is unique on the page
    (unique_key); every widget of the row is keyed from it."""
    eid = event_id_of(row)
    later = later_of(row)
    same = is_same_story(row)
    found = later or (briefing_of(pick(canonical_of(row) or {}, "briefing")) if same else None)
    promote = decision_of(row) == "rejected" and not is_auto(row) and not later
    target = actions.target_from_row(ws, dict(row))
    stars = [(one_line(s.get("entity_id")), one_line(pick(s, "name", "label"))) for s in dicts(row.get("stars"))]
    stars = [(e, n) for e, n in stars if e and n] if not_about and eid is not None else []

    def extra() -> None:
        if found:
            focus = {"edition": as_int(found["edition_id"])}
            if as_int(found.get("item_id")) is not None:
                focus["item"] = as_int(found["item_id"])
            # in a callback: it runs before the tab bar is drawn, so the view can change in this same rerun
            st.button("Show it", key=f"lo_show_{key}", type="tertiary", icon=":material/arrow_forward:",
                      on_click=links.go, args=("briefing",), kwargs=focus)
        for n, (entity_id, name) in enumerate(stars):
            ui.write_button(f"Not about {name}", ws=ws, key=f"lo_not_about_{key}_{n}", type="tertiary",
                            on_click=actions.report_not_about, args=(ws, entity_id, name, eid), kwargs={"rerun": False})

    with st.container(key=f"zx_row_{key}"):
        st.markdown(row_html(row, ws.timezone), unsafe_allow_html=True)
        actions.action_bar(ws, target, key=key, promote=promote, tags=tags_html(row),
                           extra=extra if (found or stars) else None)
        actions.why_expander(ws, target, why_of(row), key=key, extra=extra_of(row) or None)


# ---------------------------------------------------------------------------------------------- paging state


def shown(slot: tuple, page: int) -> int:
    """How many rows `slot` shows (it starts at one page; "Show more" adds pages)."""
    saved = st.session_state.get(SHOWN_KEY)
    value = saved.get(slot) if isinstance(saved, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= page else page


def _show_more(slot: tuple, count: int) -> None:
    saved = st.session_state.get(SHOWN_KEY)
    saved = dict(saved) if isinstance(saved, dict) else {}
    saved[slot] = count
    st.session_state[SHOWN_KEY] = saved


def more_button(label: str, key: str, slot: tuple, count: int) -> None:
    st.button(label, key=key, type="tertiary", icon=":material/expand_more:", on_click=_show_more, args=(slot, count))


# ---------------------------------------------------------------------------------------------- left out of a briefing


def left_out_of(edition: Mapping) -> dict | None:
    """The briefing's `left_out` counts (schema 11), or None from an older hub."""
    value = edition.get("left_out") if isinstance(edition, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else None


def automatic_counts(left_out: Mapping | None) -> tuple[int, int]:
    """(muted, old news) the hub kept out before the editor read them in that briefing's window."""
    auto = left_out.get("kept_out_automatically") if isinstance(left_out, Mapping) else None
    auto = auto if isinstance(auto, Mapping) else {}
    return max(as_int(auto.get("muted")) or 0, 0), max(as_int(auto.get("old_news")) or 0, 0)


def section_label(left_out: Mapping) -> str:
    """'Left out of this briefing · 214' (the hub's total), or without a count when it gives none."""
    total = as_int(left_out.get("total"))
    return f"{SECTION_LABEL} · {total}" if total is not None and total >= 0 else SECTION_LABEL


def has_section(left_out: Mapping | None) -> bool:
    """The section is drawn when the briefing left something out or kept something out automatically."""
    if left_out is None:
        return False
    total = as_int(left_out.get("total"))
    return (total is None or total > 0) or any(n > 0 for n in automatic_counts(left_out))


def automatic_text(left_out: Mapping | None) -> str:
    """'Kept out before the editor read them: 4 muted, 12 old news.', or '' when both are 0."""
    muted, old = automatic_counts(left_out)
    return AUTO_CAPTION.format(muted=muted, old=old) if muted or old else ""


def group_title(group: str, count: int) -> str:
    return f"{GROUP_NAMES.get(group, group)} · {count}"


def read_edition(ws: Workspace, edition_id: int) -> list[dict]:
    """Every story that briefing's run left out: GET /rejected?edition_id=N, page by page (up to EDITION_PAGES)."""
    rows: list[dict] = []
    offset = 0
    for _ in range(EDITION_PAGES):
        body = data.rejected(ws.id, days=None, edition_id=edition_id, offset=offset)
        page = rows_of(body)
        rows.extend(page)
        more = isinstance(body, Mapping) and body.get("has_more") is True
        next_offset = as_int(pick(body, "next_offset")) if isinstance(body, Mapping) else None
        if not more or not page or next_offset is None:
            break
        offset = next_offset
    return unique_rows(rows)


def render_group(ws: Workspace, edition_id: int, group: str, rows: list[dict], used: set[str]) -> None:
    """One group: its title with its count, the first rows (GROUP_PAGE, then more on demand) and "Show N more"."""
    if not rows:
        return
    st.markdown(f'<div class="zx-group-title">{esc(group_title(group, len(rows)))}</div>', unsafe_allow_html=True)
    slot = (edition_id, group)
    limit = shown(slot, GROUP_PAGE)
    for row in rows[:limit]:
        render_row(ws, row, unique_key(f"l{edition_id}{group[0]}_{event_id_of(row)}", used))
    remaining = len(rows) - limit
    if remaining > 0:
        more_button(f"Show {min(GROUP_PAGE, remaining)} more", f"lo_more_{edition_id}_{group}", slot,
                    limit + GROUP_PAGE)


def _see_mutes() -> None:
    links.go("tuning", rules="muted")


def render_automatic(left_out: Mapping | None, key: str) -> None:
    """The one caption on what the hub kept out before the editor read them, with a way to the mutes in Tuning."""
    text = automatic_text(left_out)
    if not text:
        return
    with st.container(horizontal=True, key=f"zx_leftout_auto_{key}", gap="small", vertical_alignment="center"):
        st.markdown(f'<div class="zx-leftout-auto">{esc(text)}</div>', unsafe_allow_html=True)
        if automatic_counts(left_out)[0] > 0:
            st.button(SEE_MUTES, key=f"lo_mutes_{key}", type="tertiary", icon=":material/arrow_forward:",
                      on_click=_see_mutes)


def render_edition_section(ws: Workspace, edition: Mapping, used: set[str]) -> None:
    """"Left out of this briefing · N" under the shelves: collapsed, and lazy (its read happens only once opened)."""
    left_out = left_out_of(edition)
    edition_id = as_int(pick(edition, "id", "edition_id"))
    if edition_id is None or not has_section(left_out):
        return
    with st.container(key=f"zx_leftout_{edition_id}"):
        box = st.expander(section_label(left_out), key=f"zx_leftout_open_{edition_id}", on_change="rerun")
        with box:
            if not box.open:
                return
            try:
                rows = read_edition(ws, edition_id)
            except api.ApiError as exc:
                ui.error_box("what this briefing left out", exc, key=f"leftout_{edition_id}")
                return
            groups = grouped(rows)
            if not any(groups.values()) and not automatic_text(left_out):
                st.caption("Nothing was left out of this briefing.")
            for group, _ in GROUPS:
                render_group(ws, edition_id, group, groups[group], used)
            render_automatic(left_out, str(edition_id))


# ---------------------------------------------------------------------------------------------- the search's group


def render_search_group(ws: Workspace, query: str, used: set[str]) -> None:
    """The search's second group, "Left out · N": what the hub finds among the stories left out of the briefings of
    the last 90 days (GET /rejected?q=&days=90), SEARCH_PAGE rows at a time with "Show more"."""
    slot = ("search", one_line(query).casefold())
    limit = shown(slot, SEARCH_PAGE)
    try:
        body = data.rejected(ws.id, days=SEARCH_DAYS, filter="all", q=query, limit=limit)
    except api.ApiError as exc:
        st.caption(md_label(SEARCH_FAILED.format(reason=ui.plain_error(exc)[0])))
        return
    rows = unique_rows(rows_of(body))
    total = as_int(pick(body, "total")) if isinstance(body, Mapping) else None
    total = max(total if total is not None else len(rows), len(rows))
    with st.container(key="zx_leftout_search"):
        st.markdown(f'<div class="zx-group-title">{esc(SEARCH_GROUP)} · {total}</div>', unsafe_allow_html=True)
        if not rows:
            st.markdown(f'<div class="zx-group-empty">{esc(SEARCH_NONE)}</div>', unsafe_allow_html=True)
            return
        for row in rows[:limit]:
            render_row(ws, row, unique_key(f"q_{event_id_of(row)}", used))
        if total > min(limit, len(rows)):
            more_button("Show more", "lo_search_more", slot, limit + SEARCH_PAGE)
