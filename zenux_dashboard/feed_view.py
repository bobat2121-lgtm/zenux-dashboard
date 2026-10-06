"""Briefing: the analyst's published briefings, newest first (GET /editions?limit=5&before=), with card actions.

Page, top to bottom (docs/SPEC-SIMPLIFY.md 2.2): the plain status line and the new-briefing check (status); at most two
one-line banners, only when they apply ("N suggestions need your OK" with Review, which opens Tuning; the weekly
tune-up of `tuneup`); one search box over the briefings and what was left out of them; a deep-linked briefing that is
not among the loaded pages (GET /editions/<id>, api.edition); the briefings; and Load earlier briefings. Nothing on this
page reruns on a timer (the new-briefing check is the shell's own small fragment with no inputs).

The search ("Search your briefings and what was left out (last 90 days)") shows two groups: "In your briefings · N"
(matching stories of the briefings loaded below show as full cards, and GET /editions/search lists the matches of
earlier briefings of the last 90 days under them, each with Show it) and "Left out · N" (left_out.render_search_group:
GET /rejected?q=&days=90, with the shared left-out row).

A briefing (edition) card: the kicker (LATEST on the newest, the hub's briefing name "Sat Oct 4 · morning briefing",
age, clock time, story count, and the "how much" setting when it is not Standard), the editor's one-sentence
summary as the title (older briefings have none: a deterministic sentence built from the stories), the tuning receipt
under it ("Your tuning here: 2 stories brought in and 1 kept out by your rules; the editor used 3 of your ratings.",
from the briefing's `tuning`, only when a count is above zero), the hero tiles and coverage-area split on the newest,
the corrections answered in this briefing, one card per story, the "On your watchlist" and "Near misses" shelves (the
shared left-out row, left_out.render_row), "Left out of this briefing · N" (left_out.render_edition_section: lazy,
three groups and the automatic caption), the editor's notes collapsed (shown as written, inside the expander only),
and under them "Why am I seeing this?": one collapsed section with every story's reasons, each headed by the story's
number ("01") and headline (lazy: drawn only while open).

A story card: rank, dateline (date · plain source name, never a source key), the headline with its facts, metrics and
source links (a corrected story shows the corrected text and metrics), then one row under the headline
(actions.action_bar, docs/SPEC-ICON-ACTIONS.md): on the left its tags (coverage areas, TOP STORY at 90+, the plain tier
in grey words, and its states: flagged by you, corrected, checked, on your watchlist), on the right the story icons.
What the analyst said about the story (a preference, a rating) shows as a glowing icon, not as a chip. Fields are read
tolerantly, so an older or newer hub shape still renders (a briefing without `left_out` or `tuning` simply has no
receipt and no left-out section); anything unknown is left out, not guessed.

"Conferences coming up" (docs/SPEC-MIGRATION-BUILD.md section 7): the first briefing of Friday's first scheduled time
leads with an item of kind `conference_list`. It is a plain card, not a story: its title, the hub's summary, the next
six months grouped by month (lines with a flag first: NEW, DATES SET, NOW PRESENTING: TICKER, MOVED), then one line
for later months and one for dates not posted yet. It has no number, no score, no tags and no story icons, and it is
left out of the story counts, the hero tiles, the coverage-area split and "Why am I seeing this?".
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import streamlit as st

from . import actions, api, data, labels, left_out, links, owner, status, tuneup, tuning_view, ui
from .config import Workspace
from .fmt import (MIN_TIME, as_int, as_list, chip, clip, dicts, empty_state, esc, esc_lines, fmt_clock, fmt_date,
                  fmt_day, join_and, link, md_label, module_color, module_name, one_line, parse_time, pick, plural,
                  relative_time, safe_url, tag_style)

PAGE_SIZE = 5
MAX_PAGES = 20
NOTES_LABEL = "Editor's notes"
WHY_LABEL = "Why am I seeing this?"
FULL_ITEMS = "_all_items"  # set by search(): the edition's full item list, while `items` holds only the hits
SEARCH_KEY = "br_search"
SEARCH_LABEL = "Search your briefings and what was left out"
SEARCH_PLACEHOLDER = "Search your briefings and what was left out (last 90 days)"
IN_BRIEFINGS = "In your briefings"
MORE_KEY = "br_more"
BACK_KEY = "br_back_latest"
SIGNOFF_KEY = "br_signoff"
EMPTY_BRIEFING = "Nothing new cleared your bar in this briefing."
NO_HITS = "No matching stories in the loaded briefings. Try another word, or load earlier briefings."
NO_HITS_ANYWHERE = "No matching stories in your briefings of the last 90 days."
EARLIER = "Earlier briefings"
EARLIER_MORE = "Showing the newest {n} matches from earlier briefings. Add a word to narrow the search."
SEARCH_FAILED = "Couldn't search earlier briefings: {reason}"
LINKED = "Showing the briefing you linked."
LINKED_GONE = "The briefing you linked isn't available any more."
STAGING_EMPTY = ("ZENITH is collecting. Briefings start after you sign off on What ZENITH looks for, at the top of "
                 "Coverage.")
SHELF_TITLES = {"watchlist": "On your watchlist · not in this briefing", "near": "Near misses · just under your bar"}
SHELF_FIELDS = {"watchlist": "watchlist", "near": "near_misses"}
BRIEFING_LOCKED = "Sign in to edit (top right) to use More like this, Less like this and Rate this story."
SHELF_SHOWN = 5  # watchlist and near-miss shelf rows shown before "Show all" (WF5 SA-2)
OK_REVIEW = "Review"
RECEIPT_LEAD = "Your tuning here: "
# The briefing's `tuning` (docs/SPEC-SIMPLIFY.md 1.4): what the analyst's rules did in that run, in this order.
RECEIPT_EFFECTS = (("brought_in", "brought in"), ("kept_out", "kept out"), ("raised", "raised"), ("lowered", "lowered"))
CONFERENCE_KIND = "conference_list"  # the hub's Friday "Conferences coming up" item
CONFERENCE_TITLE = "Conferences coming up"
CONFERENCE_LINK = "Event page ↗"
# The flags a conference line can carry, in the order the hub shows them; "NOW PRESENTING" takes its tickers.
NEW_FLAG, DATES_FLAG, PRESENTING_FLAG, MOVED_FLAG = "NEW", "DATES SET", "NOW PRESENTING", "MOVED"


def _map(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


# ---------------------------------------------------------------------------------------------- shapes


def editions_of(body: Any) -> list[dict]:
    if isinstance(body, list):
        return dicts(body)
    return dicts(pick(body, "editions", "items", "data", default=[]))


def next_cursor(body: Any, page: list[dict]) -> int | None:
    """The `before` edition id of the next (older) page, or None when there is none."""
    cursor = as_int(pick(body, "next_before", "next", "before"))
    if cursor is not None:
        return cursor
    if pick(body, "has_more") is False or len(page) < PAGE_SIZE:
        return None
    return as_int(pick(page[-1], "id", "edition_id")) if page else None


def items_of(edition: Mapping) -> list[dict]:
    return sorted(dicts(edition.get("items")), key=lambda it: (as_int(it.get("rank")) is None, as_int(it.get("rank")) or 0))


def all_items(edition: Mapping) -> list[dict]:
    """Every item of the edition, also when a search narrowed `items` to the hits."""
    full = edition.get(FULL_ITEMS)
    return items_of({"items": full}) if isinstance(full, list) else items_of(edition)


def is_conference_list(item: Mapping) -> bool:
    """The Friday "Conferences coming up" item, not a story."""
    return one_line(item.get("kind")).lower() == CONFERENCE_KIND


def story_items(items: list[dict]) -> list[dict]:
    """The stories among a briefing's items (the conference list is not one)."""
    return [item for item in items if not is_conference_list(item)]


def edition_id(edition: Mapping) -> Any:
    return pick(edition, "id", "edition_id")


def edition_time(edition: Mapping) -> Any:
    return pick(edition, "published_at", "created_at", "posted_at")


def known_time(value: Any) -> bool:
    return parse_time(value) != MIN_TIME


def score_of(item: Mapping) -> int | None:
    """The story's score: the item's, else its why.score."""
    score = as_int(item.get("score"))
    return score if score is not None else as_int(pick(item, "why.score"))


def metric_html(metric: Any) -> str:
    if isinstance(metric, Mapping):
        label = one_line(pick(metric, "label", "name", "metric"))
        value = one_line(pick(metric, "value", "amount", "text"))
        unit = one_line(metric.get("unit"))
        value = f"{value} {unit}".strip() if unit and unit not in value else value
        if not value and not label:
            return ""
        return f'<span class="feed-metric">{esc(label)}{" " if label else ""}<b>{esc(value)}</b></span>'
    text = one_line(metric)
    return f'<span class="feed-metric"><b>{esc(text)}</b></span>' if text else ""


def item_modules(item: Mapping) -> list[str]:
    """Every coverage area the item draws on: `modules` when the hub gives it, else [module]. Unique, in order."""
    out: list[str] = []
    for raw in as_list(item.get("modules")):
        mid = one_line(pick(raw, "id", "module_id", "module") if isinstance(raw, Mapping) else raw)
        if mid and mid not in out:
            out.append(mid)
    if not out:
        mid = one_line(pick(item, "module", "module_id"))
        out = [mid] if mid else []
    return out


def item_module(item: Mapping) -> str:
    """The item's own coverage area (its canonical event's), else the first of its areas."""
    return one_line(pick(item, "module", "module_id")) or next(iter(item_modules(item)), "")


def module_counts(items: list[dict]) -> list[tuple[str, int]]:
    """[(area id, stories)] counted by each item's own area, ordered by display name."""
    counts: dict[str, int] = {}
    for item in items:
        mid = item_module(item)
        if mid:
            counts[mid] = counts.get(mid, 0) + 1
    return sorted(counts.items(), key=lambda kv: (module_name(kv[0]).casefold(), kv[0]))


def fallback_summary(items: list[dict]) -> str:
    """A deterministic one-sentence title for a briefing without the editor's summary (older briefings)."""
    if not items:
        return "An empty briefing: nothing new cleared your bar."
    counts = module_counts(items)
    if len(counts) > 1:
        where = " across " + join_and([f"{module_name(m)} ({n})" for m, n in counts])
    elif counts:
        where = " in " + module_name(counts[0][0])
    else:
        where = ""
    lead = clip(pick(items[0], "headline", "title", default=""), 160).rstrip(" .;:,")
    sentence = plural(len(items), "story", "stories") + where
    if lead:
        sentence += f": {lead}" if len(items) == 1 else f", led by {lead}"
    return sentence if sentence.endswith(("?", "!", "…")) else sentence + "."


def summary_of(edition: Mapping, items: list[dict]) -> str:
    """The briefing's title: the editor's one-sentence summary, else the fallback sentence."""
    return one_line(edition.get("summary")) or fallback_summary(items)


def note_of(edition: Mapping) -> str:
    """The briefing's editor's note (evidence and grading warnings), or ''."""
    note = edition.get("note")
    return str(note).strip() if one_line(note) else ""


def on_watchlist(item: Mapping) -> bool:
    """A starred subject company, or a starred company the story is about."""
    why = _map(item.get("why"))
    return any(s.get("starred") for s in actions.subjects_of(why.get("subjects"))) or bool(dicts(why.get("stars")))


def receipt_text(edition: Mapping) -> str:
    """The tuning receipt from the briefing's `tuning` (schema 11), only when a count is above zero: "Your tuning here:
    2 stories brought in and 1 kept out by your rules; the editor used 3 of your ratings." A run whose rules changed no
    decision but were cited says "the editor applied 2 of your rules". '' for an older hub or a briefing your tuning
    did not touch."""
    tuning = _map(edition.get("tuning"))

    def n(key: str) -> int:
        return max(as_int(tuning.get(key)) or 0, 0)

    effects = [(n(key), words) for key, words in RECEIPT_EFFECTS if n(key) > 0]
    parts = []
    if effects:
        first, rest = effects[0], effects[1:]
        phrases = [f"{plural(first[0], 'story', 'stories')} {first[1]}"] + [f"{count} {words}" for count, words in rest]
        parts.append(f"{join_and(phrases)} by your rules")
    elif n("rules_used"):
        parts.append(f"the editor applied {n('rules_used')} of your rules")
    if n("ratings_used"):
        parts.append(f"the editor used {n('ratings_used')} of your ratings")
    return RECEIPT_LEAD + "; ".join(parts) + "." if parts else ""


# ---------------------------------------------------------------------------------------------- html


def module_tag(module_id: str) -> str:
    """A coverage area as a coloured pill: violet for ai-infra, teal for defense-unmanned, a stable palette colour
    otherwise; its plain area name, never the id."""
    return (f'<span class="module-tag" style="{tag_style(module_color(module_id))}">'
            f'{esc(labels.area_name(module_id).upper())}</span>')


def module_tags_html(item: Mapping) -> str:
    return "".join(module_tag(m) for m in item_modules(item))


def dateline_html(item: Mapping, edition: Mapping, tz: str) -> str:
    """"Oct 3 · Data Center Dynamics": the story's date (else the briefing's) and its plain source name."""
    when = next((v for v in (pick(item, "event.published_at"), edition_time(edition)) if known_time(v)), None)
    parts = [fmt_date(when, tz) if when is not None else "", actions.item_source_line(item)]
    text = " · ".join(p for p in parts if p)
    return f'<div class="feed-dateline">{esc(text)}</div>' if text else ""


def state_chips(item: Mapping) -> str:
    """The story's states: its correction and the watchlist. A rating has no chip: the glowing star says it."""
    out = []
    correction = _map(item.get("correction"))
    state = one_line(correction.get("state"))
    if state == "flagged":
        out.append(chip("Flagged by you · being re-checked", "chip-state chip-flagged"))
    elif state == "corrected":
        out.append(chip("Corrected", "chip-state chip-corrected"))
    elif state == "upheld":
        out.append(chip("Checked: stands", "chip-state chip-upheld"))
    if on_watchlist(item):
        out.append(chip("On your watchlist", "chip-state chip-starred"))
    return "".join(out)


def item_tags_html(item: Mapping) -> str:
    """The tags on the left of the story's row under its headline: coverage areas (coloured pills), TOP STORY at 90+, the
    tier in plain grey words (no pill), its states, and a note when no source link was captured."""
    score = score_of(item)
    top = '<span class="badge-top">TOP STORY</span>' if score is not None and score >= labels.TOP_STORY_MIN else ""
    tier = labels.tier_label(item.get("tier"))
    tier_html = f'<span class="feed-tier">{esc(tier)}</span>' if tier else ""
    nolink = "" if actions.item_sources(item) else '<span class="feed-nolink">No source link captured</span>'
    return f'<div class="feed-tags">{module_tags_html(item)}{top}{tier_html}{state_chips(item)}{nolink}</div>'


def item_html(item: Mapping, edition: Mapping, tz: str, focus: bool = False) -> str:
    """The story card above its row (item_tags_html and the icons): number, dateline, and the headline that opens the
    text, metrics and source links."""
    rank = as_int(item.get("rank"))
    marker = str(rank).zfill(2) if rank is not None else "–"
    correction = _map(item.get("correction"))
    corrected = one_line(correction.get("state")) == "corrected"
    headline = one_line(pick(item, "headline", "title"))
    text = pick(item, "text", "body", "summary", "factual_text", default="")
    metrics_raw = as_list(item.get("metrics"))
    if corrected:  # the corrected text and metrics replace the published ones (none: no published metric stands)
        headline = one_line(correction.get("headline")) or headline
        text = correction.get("text") if one_line(correction.get("text")) else text
        if correction.get("metrics") is not None:
            metrics_raw = as_list(correction.get("metrics"))
    metrics = "".join(metric_html(m) for m in metrics_raw[:5])
    metrics_html = f'<div class="feed-metrics">{metrics}</div>' if metrics else ""
    sources = actions.item_sources(item)
    source_links = "".join(link(url, f"{label} ↗") for url, label in sources)
    summary = (f'<div class="feed-item-headline">{esc(headline)}</div>' if headline
               else '<span class="feed-summary-label">Read the story</span>')
    return (
        f'<article class="feed-item{" zx-focus" if focus else ""}">'
        f'<div class="rank-marker">{esc(marker)}</div>'
        '<div class="feed-copy">'
        f'{dateline_html(item, edition, tz)}'
        '<details class="feed-details">'
        f'<summary class="feed-toggle">{summary}</summary>'
        f'<div class="feed-text">{esc_lines(text)}</div>'
        f'{metrics_html}'
        f'<div class="feed-sources">{source_links}</div>'
        '</details>'
        '</div></article>'
    )


def conference_body(item: Mapping) -> Mapping:
    """The conference list's structured body: the item's `conferences` (the hub's lead item view), else its `body`
    (the stored column), an object or the JSON text of one; {} when there is none."""
    body = item.get("conferences") if item.get("conferences") is not None else item.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            body = None
    return body if isinstance(body, Mapping) else {}


def conference_flags(flags: Any) -> str:
    """A line's flags in the hub's order, the presenting tickers merged: "NEW, NOW PRESENTING: RCAT, ONDS". Anything
    else is left out."""
    given = [one_line(f) for f in as_list(flags) if isinstance(f, str)]
    tickers: list[str] = []
    for flag in given:
        if flag.startswith(f"{PRESENTING_FLAG}: "):
            for ticker in flag[len(PRESENTING_FLAG) + 2:].split(","):
                if one_line(ticker) and one_line(ticker) not in tickers:
                    tickers.append(one_line(ticker))
    out = [f for f in (NEW_FLAG, DATES_FLAG) if f in given]
    if tickers:
        out.append(f"{PRESENTING_FLAG}: {', '.join(tickers)}")
    if MOVED_FLAG in given:
        out.append(MOVED_FLAG)
    return ", ".join(out)


def conference_line_html(line: Mapping) -> str:
    """One conference: its flags as a label, the hub's line without its flag prefix, and its event page."""
    flags = conference_flags(line.get("flags"))
    text = one_line(line.get("text"))
    if flags and text.startswith(f"{flags} - "):
        text = text[len(flags) + 3:]
    flag_html = f'<span class="conf-flag">{esc(flags)}</span>' if flags else ""
    page = link(line.get("url"), CONFERENCE_LINK, "conf-link") if safe_url(line.get("url")) else ""
    return (f'<li class="conf-line{" conf-flagged" if flags else ""}">{flag_html}'
            f'<span class="conf-text">{esc(text)}</span>{page}</li>')


def conference_html(item: Mapping) -> str:
    """The "Conferences coming up" card: title, summary, the months with their lines (flagged lines first), then the
    later months and the dates not posted yet. Without a body (an older hub), the item's text, line by line."""
    body = conference_body(item)
    title = one_line(pick(item, "headline", "title")) or CONFERENCE_TITLE
    parts = [f'<div class="conf-title" role="heading" aria-level="3">{esc(title)}</div>']
    months = dicts(body.get("months"))
    if body and (months or one_line(pick(body, "later.text", "undated.text"))):
        summary = one_line(body.get("summary"))
        if summary:
            parts.append(f'<div class="conf-summary">{esc(summary)}</div>')
        for month in months:
            lines = dicts(month.get("lines"))
            if not lines:
                continue
            flagged = [line for line in lines if conference_flags(line.get("flags"))]
            ordered = flagged + [line for line in lines if not conference_flags(line.get("flags"))]
            label = one_line(pick(month, "label", "month"))
            parts.append('<section class="conf-month">'
                         + (f'<div class="conf-month-label">{esc(label)}</div>' if label else "")
                         + '<ul class="conf-lines">' + "".join(conference_line_html(line) for line in ordered) + "</ul>"
                         + "</section>")
        for key in ("later", "undated"):
            text = one_line(pick(body, f"{key}.text"))
            if text:
                parts.append(f'<div class="conf-more">{esc(text)}</div>')
    else:
        text = item.get("text") if isinstance(item.get("text"), str) else ""
        if one_line(text):
            parts.append(f'<div class="conf-text-block">{esc_lines(text)}</div>')
    return f'<article class="conf-card">{"".join(parts)}</article>'


def stats_html(edition: Mapping, items: list[dict]) -> str:
    """The hero's right side: 2x2 tiles, then the coverage-area split bar and its legend."""
    scores = [score_of(i) for i in items]
    screened = as_int(pick(edition, "candidate_count", "reviewed", "candidates", "stats.candidates", "stats.reviewed"))
    # "Also notable" is every other scored story in the briefing, not a fixed 70-89: under Everything notable the bar
    # is 60, and a story you sent back may sit under the bar. The tiles add up (WF5 AW-8).
    tiles = [
        ("STORIES", len(items), ""),
        ("SCREENED", screened if screened is not None else "—", ""),
        ("TOP STORIES", sum(1 for s in scores if s is not None and s >= labels.TOP_STORY_MIN), " stat-high"),
        ("ALSO NOTABLE", sum(1 for s in scores if s is not None and s < labels.TOP_STORY_MIN), " stat-medium"),
    ]
    tiles_html = "".join(
        f'<div class="stat{css}"><div class="stat-n">{esc(n)}</div><div class="stat-l">{esc(name)}</div></div>'
        for name, n, css in tiles
    )
    counts = module_counts(items)
    bar = "".join(f'<span style="flex-grow:{n};background:{module_color(m)}"></span>' for m, n in counts)
    legend = "".join(f'<span><i style="background:{module_color(m)}"></i>{esc(labels.area_name(m).upper())} {n}</span>'
                     for m, n in counts)
    split = (f'<div class="theme-bar" aria-hidden="true">{bar}</div><div class="theme-legend">{legend}</div>'
             if counts else "")
    return f'<div class="edition-stats"><div class="stat-grid">{tiles_html}</div>{split}</div>'


def head_html(edition: Mapping, tz: str, latest: bool = False, matched: int | None = None) -> str:
    """The briefing header: the kicker (LATEST, the briefing's name, age, time, stories, the "how much" setting when
    it is not Standard), then the summary as the title. The newest briefing is the hero: its stats sit on the right.
    The editor's note never appears here. The conference list is not a story: it is left out of the counts."""
    items = story_items(all_items(edition))
    when = edition_time(edition)
    meta = [relative_time(when), fmt_clock(when, tz)] if known_time(when) else []
    meta.append(plural(len(items), "story", "stories"))
    if matched is not None:
        meta.append(f"{matched} matching")
    volume = one_line(pick(edition, "selection.volume"))
    volume_chip = chip(labels.VOLUME_LABELS.get(volume, ""), "tier") if volume and volume != "standard" else ""
    name = one_line(edition.get("briefing_label")) or labels.edition_label(when, tz)
    kicker = (
        '<div class="edition-kicker">'
        + ('<span class="latest-badge">LATEST</span>' if latest else "")
        + f'<span class="edition-label">{esc(name)}</span>'
        + "".join(f'<span aria-hidden="true">·</span><span>{esc(part)}</span>' for part in meta)
        + volume_chip
        + '</div>'
    )
    title = f'<div class="edition-title" role="heading" aria-level="2">{esc(summary_of(edition, items))}</div>'
    receipt = receipt_text(edition)
    receipt_html = f'<div class="edition-receipt">{esc(receipt)}</div>' if receipt else ""
    main = f'<div class="edition-main">{kicker}{title}{receipt_html}</div>'
    if latest:
        return f'<header class="edition-head has-stats">{main}{stats_html(edition, items)}</header>'
    return f'<header class="edition-head">{main}</header>'


def edition_html(edition: Mapping, tz: str, latest: bool = False, matched: int | None = None) -> str:
    """The briefing's header block (the story cards are drawn one by one under it)."""
    css = "feed-edition" + (" latest-edition" if latest else "")
    return f'<section class="{css}">{head_html(edition, tz, latest=latest, matched=matched)}</section>'


def corrections_html(edition: Mapping, tz: str) -> str:
    """Corrections answered in this briefing: a corrected story's new text, or why a flagged story stands."""
    notes = []
    for c in dicts(edition.get("corrections")):
        outcome = one_line(pick(c, "outcome", "state"))
        original = one_line(c.get("original_headline"))
        named = f"“{original}”" if original else "an earlier story"
        if outcome == "corrected":
            head = f"Correction to {named}"
            metrics = "".join(metric_html(m) for m in as_list(c.get("metrics"))[:5])
            links_html = "".join(link(url, f"{label} ↗") for url, label in actions.item_sources({"sources": c.get("sources")}))
            body = ((f'<div class="feed-item-headline">{esc(one_line(c.get("headline")))}</div>'
                     if one_line(c.get("headline")) else "")
                    + (f'<div class="feed-text">{esc_lines(c.get("text"))}</div>' if one_line(c.get("text")) else "")
                    + (f'<div class="feed-metrics">{metrics}</div>' if metrics else "")
                    + (f'<div class="feed-sources">{links_html}</div>' if links_html else ""))
        elif outcome == "upheld":
            head = f"Checked: {named} stands."
            body = f'<div class="feed-text">{esc_lines(c.get("text"))}</div>' if one_line(c.get("text")) else ""
        else:
            continue
        notes.append(f'<div class="correction-note"><div class="edition-label">{esc(head)}</div>{body}</div>')
    return "".join(notes)


def shelf_rows(edition: Mapping, kind: str) -> list[dict]:
    """A shelf's rows: `watchlist` or `near` (near_misses is null when the shelf was off; shelves null before v8)."""
    return dicts(_map(edition.get("shelves")).get(SHELF_FIELDS[kind]))


def shelf_order(rows: list[dict]) -> list[dict]:
    """Shelf rows best first: score (highest first, unscored last), then the newest."""
    return sorted(rows, key=lambda r: (-(as_int(r.get("score")) if as_int(r.get("score")) is not None else -1),
                                       -parse_time(r.get("published_at")).timestamp()))


def shelf_row(row: Mapping, edition: Mapping) -> dict:
    """A shelf row as the shared left-out row takes it: the bar in force for the briefing (`selection.min_score`) when
    the row does not carry its own, so "Why was it left out?" can say it."""
    out = dict(row)
    if as_int(out.get("bar")) is None:
        bar = as_int(pick(edition, "selection.min_score"))
        if bar is not None:
            out["bar"] = bar
    return out


# ---------------------------------------------------------------------------------------------- search


def item_haystack(item: Mapping) -> str:
    """What the search box covers for one story: headline, text, companies, sources and coverage areas. The conference
    list: its title, text, summary and lines (never its field names)."""
    if is_conference_list(item):
        body = conference_body(item)
        lines = [line.get("text") for month in dicts(body.get("months")) for line in dicts(month.get("lines"))]
        parts = [item.get("headline"), item.get("text"), body.get("summary"), *lines, pick(body, "later.text"),
                 pick(body, "undated.text")]
        return " ".join(one_line(p) for p in parts if isinstance(p, str)).casefold()
    why = _map(item.get("why"))
    correction = _map(item.get("correction"))
    modules = item_modules(item)
    sources = actions.item_sources(item)
    parts = [
        item.get("headline"), item.get("text"), item.get("body"), correction.get("headline"), correction.get("text"),
        " ".join(modules), " ".join(labels.area_name(m) for m in modules), labels.tier_label(item.get("tier")),
        actions.item_source_line(item), pick(why, "source.lane_label"),
        " ".join(label for _, label in sources), " ".join(url for url, _ in sources),
        " ".join(s["name"] for s in actions.subjects_of(why.get("subjects"))),
        " ".join(one_line(s.get("name")) for s in dicts(why.get("stars"))),
    ]
    return " ".join(one_line(p) for p in parts).casefold()


def search(editions: list[dict], query: str) -> list[dict]:
    """The briefings with at least one story matching every word of the query, narrowed to those stories."""
    terms = one_line(query).casefold().split()
    if not terms:
        return editions
    out = []
    for edition in editions:
        hits = [item for item in items_of(edition) if all(term in item_haystack(item) for term in terms)]
        if hits:
            out.append({**edition, "items": hits, FULL_ITEMS: as_list(edition.get("items"))})
    return out


# ---------------------------------------------------------------------------------------------- reads


def pages_key(ws: Workspace) -> str:
    return f"br_pages_{ws.id}"


def page_count(ws: Workspace) -> int:
    return max(1, min(MAX_PAGES, as_int(st.session_state.get(pages_key(ws))) or 1))


def load(ws: Workspace) -> tuple[list[dict], bool]:
    """Every loaded page (newest first, unique by id); True when an earlier page exists."""
    out: list[dict] = []
    before: int | None = None
    more = False
    for _ in range(page_count(ws)):
        body = data.editions(ws.id, before, PAGE_SIZE)
        page = editions_of(body)
        out.extend(page)
        before = next_cursor(body, page)
        more = before is not None
        if not more:
            break
    seen: set = set()
    unique = []
    for edition in sorted(out, key=lambda e: parse_time(edition_time(e)), reverse=True):
        eid = edition_id(edition)
        if eid is not None and eid in seen:
            continue
        seen.add(eid)
        unique.append(edition)
    return unique, more


def unique_key(base: str, used: set[str]) -> str:
    """A widget key not used yet on this page (malformed data may repeat ids)."""
    key, n = base, 1
    while key in used:
        n += 1
        key = f"{base}_{n}"
    used.add(key)
    return key


# ---------------------------------------------------------------------------------------------- page


def render_notes(edition: Mapping) -> None:
    """The briefing's editor's note, collapsed at the bottom of the briefing (nothing when there is none)."""
    note = note_of(edition)
    if note:
        with st.expander(NOTES_LABEL):
            st.markdown(f'<div class="grading-notes">{esc_lines(note)}</div>', unsafe_allow_html=True)


def item_number(item: Mapping, n: int) -> str:
    """The story's number as its card shows it ("01"): its rank, else its place in the briefing."""
    rank = as_int(item.get("rank"))
    return str(rank if rank is not None else n + 1).zfill(2)


def why_head_html(number: str, title: str) -> str:
    return (f'<div class="why-item-head"><span class="why-num">{esc(number)}</span>'
            f'<span class="why-title">{esc(title)}</span></div>')


def render_why(ws: Workspace, edition: Mapping, items: list[dict], index: Any) -> None:
    """"Why am I seeing this?" for every story of the briefing, in one collapsed section under the editor's notes.
    Lazy: the reasons are built only while it is open."""
    if not items:
        return
    box = st.expander(WHY_LABEL, key=f"zx_whyall_{index}", on_change="rerun")
    with box:
        if not box.open:
            return
        for n, item in enumerate(items):
            target = actions.target_from_item(ws, edition, item)
            with st.container(key=f"zx_why_{index}_{n}"):
                st.markdown(why_head_html(item_number(item, n), target.title), unsafe_allow_html=True)
                why = item.get("why")
                actions.why_body(ws, target, why if isinstance(why, Mapping) else {}, f"w{index}_{n}", [])


def render_item(ws: Workspace, edition: Mapping, item: dict, index: Any, n: int, focus_item: int | None,
                used: set[str]) -> None:
    """One story card: the card HTML, then its row of tags and icons (its Why is listed under the editor's notes)."""
    eid = as_int(edition_id(edition))
    item_id = as_int(item.get("id"))
    rank = as_int(item.get("rank"))
    if item_id is not None:
        base = f"i{item_id}"
    elif eid is not None and rank is not None:
        base = f"e{eid}r{rank}"
    else:
        base = f"x{index}n{n}"
    key = unique_key(base, used)
    container = f"zx_item_{eid}_{item_id}" if key == f"i{item_id}" and eid is not None else f"zx_item_{key}"
    focus = focus_item is not None and item_id == focus_item
    target = actions.target_from_item(ws, edition, item)
    with st.container(key=container):
        st.markdown(item_html(item, edition, ws.timezone, focus=focus), unsafe_allow_html=True)
        actions.action_bar(ws, target, key=key, tags=item_tags_html(item))


def render_shelf(ws: Workspace, edition: Mapping, index: Any, kind: str, used: set[str]) -> None:
    """A lighter sub-section under the stories, one shared left-out row per story (left_out.render_row: its reason, the
    story icons with the up arrow, Why was it left out?); a watchlist row keeps "Not about <company>" for a look-alike
    name (WF5 AW-10). The first SHELF_SHOWN rows, then the rest on demand."""
    rows = [shelf_row(r, edition) for r in shelf_order(shelf_rows(edition, kind))
            if left_out.event_id_of(r) is not None]
    if not rows:
        return

    def draw(row: Mapping) -> None:
        key = left_out.unique_key(f"{kind[0]}{index}_{left_out.event_id_of(row)}", used)
        left_out.render_row(ws, row, key, not_about=kind == "watchlist")

    with st.container(key=f"zx_shelf_{index}_{kind}"):
        title = SHELF_TITLES[kind] + (f" · {len(rows)}" if len(rows) > SHELF_SHOWN else "")
        st.markdown(f'<div class="shelf"><div class="shelf-title">{esc(title)}</div></div>', unsafe_allow_html=True)
        for row in rows[:SHELF_SHOWN]:
            draw(row)
        if len(rows) > SHELF_SHOWN:
            # A starred company with a long backlog would otherwise bury a short briefing (WF5 SA-2); lazy like Why.
            box = st.expander(f"Show all {len(rows)}", key=f"zx_shelf_more_{index}_{kind}", on_change="rerun")
            with box:
                if box.open:
                    for row in rows[SHELF_SHOWN:]:
                        draw(row)


def render_conferences(item: Mapping, index: Any, n: int) -> None:
    """The "Conferences coming up" card: plain text, no story icons."""
    with st.container(key=f"zx_conf_{index}_{n}"):
        st.markdown(conference_html(item), unsafe_allow_html=True)


def render_edition(ws: Workspace, edition: Mapping, index: Any, *, latest: bool, searching: bool,
                   focus_item: int | None, used: set[str]) -> None:
    """One briefing card: its header (with the tuning receipt), corrections, the conference list on a Friday morning,
    stories, shelves, what it left out, the editor's notes and every story's Why. A search narrows it to its matching
    stories."""
    items = items_of(edition)
    stories = story_items(items)
    with st.container(key=f"zx_edition_{index}"):
        st.markdown(edition_html(edition, ws.timezone, latest=latest, matched=len(items) if searching else None),
                    unsafe_allow_html=True)
        if not searching:
            corrections = corrections_html(edition, ws.timezone)
            if corrections:
                st.markdown(corrections, unsafe_allow_html=True)
        for n, item in enumerate(items):
            if is_conference_list(item):
                render_conferences(item, index, n)
        if not stories and not searching:
            st.markdown(f'<div class="edition-empty">{esc(EMPTY_BRIEFING)}</div>', unsafe_allow_html=True)
        for n, item in enumerate(stories):
            render_item(ws, edition, item, index, n, focus_item, used)
        if not searching:
            render_shelf(ws, edition, index, "watchlist", used)
            render_shelf(ws, edition, index, "near", used)
            left_out.render_edition_section(ws, edition, used)
        render_notes(edition)
        render_why(ws, edition, stories, index)


def render_search() -> str:
    """The one search box (always visible); returns the query."""
    return one_line(st.text_input(SEARCH_LABEL, key=SEARCH_KEY, placeholder=SEARCH_PLACEHOLDER,
                                  label_visibility="collapsed", icon=":material/search:"))


def search_caption(editions: list[dict], more: bool, tz: str) -> str:
    """What the first group covers: 'Matches in the 2 briefings loaded below (back to Fri Oct 2) show in full; matches
    in earlier briefings are listed after them.'"""
    if not editions:
        return ""
    oldest = edition_time(editions[-1])
    back = f" (back to {fmt_day(oldest, tz)})" if known_time(oldest) else ""
    earlier = "; matches in earlier briefings are listed after them" if more else ""
    return f"Matches in the {plural(len(editions), 'briefing')} loaded below{back} show in full{earlier}."


def group_title_html(title: str, count: int) -> str:
    return f'<div class="zx-group-title">{esc(title)} · {count}</div>'


def earlier_hits(ws: Workspace, query: str, shown_ids: set) -> tuple[list[dict], bool, api.ApiError | None]:
    """(hits of GET /editions/search outside the briefings drawn here, more beyond this page, the read's error)."""
    try:
        body = data.search_editions(ws.id, query)
    except api.ApiError as exc:
        return [], False, exc
    hits = [h for h in dicts(pick(body, "hits", default=[]))
            if as_int(h.get("edition_id")) is not None and as_int(h.get("edition_id")) not in shown_ids]
    return hits, pick(body, "has_more") is True, None


def _open_hit(edition: int, item: int | None) -> None:
    """Show it (a button callback): clear the search, then open the briefing with the story in focus."""
    st.session_state[SEARCH_KEY] = ""
    links.go("briefing", edition=edition, item=item)


def hit_html(hit: Mapping, tz: str) -> str:
    when = hit.get("published_at")
    name = one_line(hit.get("briefing_label")) or labels.edition_label(when, tz)
    title = one_line(pick(hit, "headline", "title")) or "A story"
    return ('<div class="shelf-row">'
            f'<div class="feed-dateline">{esc(name)}</div>'
            f'<div>{link(hit.get("url"), title) if hit.get("url") else esc(title)}</div>'
            '</div>')


def render_earlier(ws: Workspace, hits: list[dict], more: bool, error: api.ApiError | None, used: set[str]) -> None:
    """The matches of earlier briefings (not loaded here), newest briefing first, each with Show it."""
    if error is not None:
        st.caption(md_label(SEARCH_FAILED.format(reason=ui.plain_error(error)[0])))
        return
    if not hits:
        return
    with st.container(key="zx_earlier_hits"):
        st.markdown(f'<div class="shelf"><div class="shelf-title">{esc(EARLIER)} · {len(hits)}</div></div>',
                    unsafe_allow_html=True)
        for hit in hits:
            edition, item = as_int(hit.get("edition_id")), as_int(hit.get("item_id"))
            st.markdown(hit_html(hit, ws.timezone), unsafe_allow_html=True)
            st.button("Show it", key=unique_key(f"br_hit_{edition}_{item}", used), type="tertiary",
                      icon=":material/arrow_forward:", on_click=_open_hit, args=(edition, item))
        if more:
            st.caption(EARLIER_MORE.format(n=len(hits)))


def back_to_latest(message: str) -> None:
    with st.container(horizontal=True, key="zx_linked", vertical_alignment="center", gap="small"):
        st.markdown(f'<div class="rejected-summary">{esc(message)}</div>', unsafe_allow_html=True)
        if st.button("Back to the latest", key=BACK_KEY):
            links.clear_focus("edition", "item")
            st.rerun()


def render_linked(ws: Workspace, loaded: list[dict], query: str, focus_item: int | None, used: set[str]) -> bool:
    """A deep-linked briefing that is not among the loaded pages, drawn first. True when one was drawn."""
    eid = as_int(links.focus("edition"))
    if eid is None or eid <= 0 or any(as_int(edition_id(e)) == eid for e in loaded):
        return False
    try:
        edition = data.edition(ws.id, eid)
    except api.ApiError as exc:
        ui.error_box("the briefing you linked", exc, key="briefing_link")
        back_to_latest(LINKED_GONE)
        return False
    if not isinstance(edition, Mapping):
        back_to_latest(LINKED_GONE)
        return False
    back_to_latest(LINKED)
    shown = search([dict(edition)], query)
    if shown:
        render_edition(ws, shown[0], "linked", latest=False, searching=bool(query), focus_item=focus_item, used=used)
    return True


def render_empty(ws: Workspace) -> None:
    """No briefings yet: say when the next one is due, or that sign-off starts them (staging)."""
    try:
        summary = status.summary(ws)
    except Exception:  # the status line already said what it could; the empty state still renders
        summary = {}
    if _map(summary).get("level") == "staging":
        st.markdown(empty_state(STAGING_EMPTY), unsafe_allow_html=True)
        if st.button("Review and sign off", key=SIGNOFF_KEY, type="primary"):
            links.go("coverage")
        return
    when = _map(summary).get("next_at")
    clock = f" (next: {fmt_clock(when, ws.timezone)})" if known_time(when) else ""
    st.markdown(empty_state(f"No briefings yet. The ZENITH editor publishes one at each scheduled time{clock}."),
                unsafe_allow_html=True)


def ok_count(ws: Workspace) -> int:
    """How many suggestions need the analyst's OK: the list Tuning shows (GET /preferences suggestions and the legacy
    proposed drafts of GET /rules); 0 when it cannot be read (the banner is an offer, never an alert)."""
    try:
        prefs = data.preferences(ws.id)
    except api.ApiError:
        return 0
    try:
        rules = data.rules(ws.id)
    except api.ApiError:
        rules = None
    return len(tuning_view.needs_ok(prefs, rules))


def ok_text(n: int) -> str:
    """'1 suggestion needs your OK' / '3 suggestions need your OK'."""
    return f"{plural(n, 'suggestion')} {'needs' if n == 1 else 'need'} your OK"


def render_banners(ws: Workspace) -> None:
    """At most two one-line banners, only when they apply: suggestions that need the analyst's OK (Review opens
    Tuning, where Needs your OK comes first) and the weekly tune-up (tuneup)."""
    n = ok_count(ws)
    if n > 0:
        with st.container(horizontal=True, key="zx_ok_banner", gap="small", vertical_alignment="center"):
            st.markdown(f'<div class="zx-banner-text">{esc(ok_text(n))}</div>', unsafe_allow_html=True)
            st.button(OK_REVIEW, key="br_ok_review", icon=":material/arrow_forward:", on_click=links.go,
                      args=("tuning",))
    tuneup.render(ws)


def render(ws: Workspace) -> None:
    status.status_line(ws)
    render_banners(ws)
    actions.ctrl_click_support()  # Ctrl/Cmd+click on a thumb or the star opens its dialog
    try:
        editions, more = load(ws)
    except api.ApiError as exc:
        ui.error_box("your briefings", exc, key="briefing")
        return
    status.new_briefing_watch(ws, as_int(edition_id(editions[0])) if editions else None)
    query = render_search()
    if editions and not owner.can_edit(ws):
        # The story buttons are drawn disabled while locked; a phone has no hover for their tooltip (WF5 AW-4).
        st.markdown(f'<div class="zx-locked">{esc(BRIEFING_LOCKED)}</div>', unsafe_allow_html=True)
    focus_item = as_int(links.focus("item"))
    used: set[str] = set()
    linked = render_linked(ws, editions, query, focus_item, used)
    if not editions:
        if not linked:
            render_empty(ws)
        return
    shown = search(editions, query)
    earlier: list[dict] = []
    earlier_more, earlier_error = False, None
    if query and more:  # every briefing is loaded otherwise
        drawn = {as_int(edition_id(e)) for e in editions} | ({as_int(links.focus("edition"))} if linked else set())
        earlier, earlier_more, earlier_error = earlier_hits(ws, query, drawn)
    if query:
        hits = sum(len(items_of(e)) for e in shown) + len(earlier)
        st.markdown(group_title_html(IN_BRIEFINGS, hits), unsafe_allow_html=True)
        st.caption(search_caption(editions, more, ws.timezone))
        if not hits:
            empty = NO_HITS if earlier_error is not None else NO_HITS_ANYWHERE
            st.markdown(f'<div class="zx-group-empty">{esc(empty)}</div>', unsafe_allow_html=True)
    newest = edition_id(editions[0])
    for index, edition in enumerate(shown):
        latest = not query and index == 0 and edition_id(edition) == newest
        render_edition(ws, edition, index, latest=latest, searching=bool(query), focus_item=focus_item, used=used)
    if query:
        render_earlier(ws, earlier, earlier_more, earlier_error, used)
        left_out.render_search_group(ws, query, used)
    if more and st.button("Load earlier briefings", key=MORE_KEY):
        st.session_state[pages_key(ws)] = page_count(ws) + 1
        st.rerun()
