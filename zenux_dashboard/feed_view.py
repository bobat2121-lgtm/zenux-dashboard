"""Feed: published Zenux editions, newest first (GET /editions?limit=10&before=).

An edition carries the Grader's one-sentence summary, which is the edition's title. Older editions have none, so the
dashboard builds a deterministic sentence from the items. The edition's grading note (evidence and grading warnings)
appears only in a collapsed "Grading notes" expander at the bottom of the edition. An item carries rank, event_id,
score, tier, headline, factual text (at most 150 words), metrics (at most 5), sources (at most 4), story_id, module
and modules (every module the story draws on). The score feeds the edition's stats only; item cards show module tags.
Fields are read tolerantly, so an older or newer hub shape still renders; anything unknown is left out, not guessed.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from . import api, data, grading
from .config import Workspace
from .fmt import (as_int, as_list, chip, clip, dicts, domain_of, empty_state, esc, esc_lines, fmt_short, fmt_time,
                  join_and, label_of, link, module_name, one_line, parse_time, pick, plural, relative_time, safe_url,
                  section_label)

PAGE_SIZE = 10
MAX_PAGES = 20
NOTES_LABEL = "Grading notes"
FULL_ITEMS = "_all_items"  # set by search(): the edition's full item list, while `items` holds only the hits
TIER_LABEL = {"1": "Tier 1 · covered", "2": "Tier 2 · read-through", "3": "Tier 3 · catalyst",
              "covered": "Tier 1 · covered", "read_through": "Tier 2 · read-through", "industry": "Tier 3 · catalyst",
              "catalyst": "Tier 3 · catalyst"}


# ---------------------------------------------------------------------------------------------- shapes


def editions_of(body: Any) -> list[dict]:
    if isinstance(body, list):
        return dicts(body)
    return dicts(pick(body, "editions", "items", "data", default=[]))


def next_cursor(body: Any, page: list[dict]) -> str | None:
    cursor = pick(body, "next_before", "next", "before")
    if cursor not in (None, ""):
        return str(cursor)
    has_more = pick(body, "has_more")
    if has_more is False or len(page) < PAGE_SIZE:
        return None
    last = page[-1] if page else {}
    value = pick(last, "id", "edition_id", "published_at")
    return None if value is None else str(value)


def items_of(edition: dict) -> list[dict]:
    return sorted(dicts(edition.get("items")), key=lambda it: (as_int(it.get("rank")) is None, as_int(it.get("rank")) or 0))


def all_items(edition: dict) -> list[dict]:
    """Every item of the edition, also when a search narrowed `items` to the hits."""
    full = edition.get(FULL_ITEMS)
    return items_of({"items": full}) if isinstance(full, list) else items_of(edition)


def edition_id(edition: dict) -> Any:
    return pick(edition, "id", "edition_id")


def edition_time(edition: dict) -> Any:
    return pick(edition, "published_at", "created_at", "posted_at")


def tier_label(tier: Any) -> str:
    text = one_line(tier).lower().replace("tier", "").strip().replace(" ", "_")
    return TIER_LABEL.get(text, label_of(tier) if one_line(tier) else "")


def sources_of(item: dict) -> list[tuple[str, str]]:
    """[(url, label)] for http(s) sources only, at most 4."""
    out: list[tuple[str, str]] = []
    raw = as_list(item.get("sources"))
    if not raw and item.get("url"):
        raw = [item.get("url")]
    for source in raw:
        if isinstance(source, dict):
            url = safe_url(pick(source, "url", "href"))
            label = one_line(pick(source, "name", "publisher", "title", "domain")) or domain_of(url)
        else:
            url = safe_url(source)
            label = domain_of(url)
        if url:
            out.append((url, label or "source"))
    return out[:4]


def metric_html(metric: Any) -> str:
    if isinstance(metric, dict):
        label = one_line(pick(metric, "label", "name", "metric"))
        value = one_line(pick(metric, "value", "amount", "text"))
        unit = one_line(metric.get("unit"))
        value = f"{value} {unit}".strip() if unit and unit not in value else value
        if not value and not label:
            return ""
        return f'<span class="feed-metric">{esc(label)}{" " if label else ""}<b>{esc(value)}</b></span>'
    text = one_line(metric)
    return f'<span class="feed-metric"><b>{esc(text)}</b></span>' if text else ""


def item_modules(item: dict) -> list[str]:
    """Every module the item draws on: `modules` when the hub gives it, else [module]. Unique, in order."""
    out: list[str] = []
    for raw in as_list(item.get("modules")):
        mid = one_line(pick(raw, "id", "module_id", "module") if isinstance(raw, dict) else raw)
        if mid and mid not in out:
            out.append(mid)
    if not out:
        mid = one_line(pick(item, "module", "module_id"))
        out = [mid] if mid else []
    return out


def item_module(item: dict) -> str:
    """The item's own module (its canonical event's), else the first of its modules."""
    return one_line(pick(item, "module", "module_id")) or next(iter(item_modules(item)), "")


def module_counts(items: list[dict]) -> list[tuple[str, int]]:
    """[(module id, items)] counted by each item's own module, ordered by display name."""
    counts: dict[str, int] = {}
    for item in items:
        mid = item_module(item)
        if mid:
            counts[mid] = counts.get(mid, 0) + 1
    return sorted(counts.items(), key=lambda kv: (module_name(kv[0]).casefold(), kv[0]))


def fallback_summary(items: list[dict]) -> str:
    """A deterministic one-sentence title for an edition without a Grader summary (older editions)."""
    if not items:
        return "An empty edition: nothing cleared the bar in this window."
    counts = module_counts(items)
    if len(counts) > 1:
        where = " across " + join_and([f"{module_name(m)} ({n})" for m, n in counts])
    elif counts:
        where = " in " + module_name(counts[0][0])
    else:
        where = ""
    lead = clip(pick(items[0], "headline", "title", default=""), 160).rstrip(" .;:,")
    sentence = plural(len(items), "item") + where
    if lead:
        sentence += f": {lead}" if len(items) == 1 else f", led by {lead}"
    return sentence if sentence.endswith(("?", "!", "…")) else sentence + "."


def summary_of(edition: dict, items: list[dict]) -> str:
    """The edition's title: the Grader's one-sentence summary, else the fallback sentence."""
    return one_line(edition.get("summary")) or fallback_summary(items)


def note_of(edition: dict) -> str:
    """The edition's grading note (evidence and grading warnings), or ''."""
    note = edition.get("note")
    return str(note).strip() if one_line(note) else ""


# ---------------------------------------------------------------------------------------------- html


def module_tags_html(item: dict) -> str:
    return "".join(f'<span class="module-tag">{esc(module_name(m).upper())}</span>' for m in item_modules(item))


def item_html(item: dict) -> str:
    rank = as_int(item.get("rank"))
    marker = str(rank).zfill(2) if rank is not None else "–"
    sources = sources_of(item)
    source_line = f'<div class="feed-source">{esc(sources[0][1])}</div>' if sources else ""
    headline = one_line(pick(item, "headline", "title"))
    text = pick(item, "text", "body", "summary", "factual_text", default="")
    metrics = "".join(metric_html(m) for m in as_list(item.get("metrics"))[:5])
    metrics_html = f'<div class="feed-metrics">{metrics}</div>' if metrics else ""
    source_links = "".join(link(url, f"{label} ↗") for url, label in sources)
    tier = tier_label(item.get("tier"))
    tags = (module_tags_html(item) + chip(tier, "tier") + grading.feedback_chips(item.get("feedback"))
            + ("" if source_links else '<span class="feed-nolink">No source link captured</span>'))
    summary = (f'<div class="feed-item-headline">{esc(headline)}</div>' if headline
               else '<span class="feed-summary-label">Read the item</span>')
    return (
        '<article class="feed-item">'
        f'<div class="rank-marker">{esc(marker)}</div>'
        '<div class="feed-copy">'
        f'{source_line}'
        '<details class="feed-details">'
        f'<summary class="feed-toggle">{summary}</summary>'
        f'<div class="feed-text">{esc_lines(text)}</div>'
        f'{metrics_html}'
        f'<div class="feed-sources">{source_links}</div>'
        '</details>'
        f'<div class="feed-tags">{tags}</div>'
        '</div></article>'
    )


def stats_html(edition: dict, items: list[dict]) -> str:
    scores = [as_int(i.get("score")) for i in items]
    reviewed = as_int(pick(edition, "reviewed", "candidates", "candidate_count", "stats.candidates", "stats.reviewed"))
    tiles = [
        ("ITEMS", len(items), ""),
        ("REVIEWED", reviewed if reviewed is not None else "—", ""),
        ("LEAD 90+", sum(1 for s in scores if s is not None and s >= 90), ""),
        ("DIGEST 70–89", sum(1 for s in scores if s is not None and 70 <= s < 90), ""),
    ] + [(module_name(m).upper(), n, " stat-module") for m, n in module_counts(items)]
    tiles_html = "".join(
        f'<div class="stat{css}"><div class="stat-n">{esc(n)}</div><div class="stat-l">{esc(name)}</div></div>'
        for name, n, css in tiles
    )
    return f'<div class="stat-grid">{tiles_html}</div>'


def band_html(edition: dict, tz: str, latest: bool = False, matched: int | None = None) -> str:
    """The edition's green feature band: the summary as its title, the meta line, then the stats tiles."""
    items = all_items(edition)
    when = edition_time(edition)
    eid = edition_id(edition)
    label = one_line(pick(edition, "label", "slot", "trigger_label")) or (f"Edition #{eid}" if eid is not None else "Edition")
    meta = [relative_time(when), fmt_time(when, tz), plural(len(items), "item")]
    if matched is not None:
        meta.append(f"{matched} matching")
    meta_html = f'<span class="edition-label">{esc(label)}</span>' + "".join(
        f'<span aria-hidden="true">·</span><span>{esc(part)}</span>' for part in meta)
    return (
        '<header class="edition-band">'
        + ('<span class="latest-badge">LATEST</span>' if latest else "")
        + f'<div class="edition-title" role="heading" aria-level="2">{esc(summary_of(edition, items))}</div>'
        + f'<div class="edition-meta">{meta_html}</div>'
        + stats_html(edition, items)
        + '</header>'
    )


def edition_html(edition: dict, tz: str, latest: bool = False, grading_on: bool = False) -> str:
    items = items_of(edition)
    searched = isinstance(edition.get(FULL_ITEMS), list)
    head = band_html(edition, tz, latest=latest, matched=len(items) if searched else None)
    body = "".join(item_html(item) for item in items) or (
        '<div class="edition-empty">Nothing material in this window: the Grader published an empty edition.</div>')
    css = "feed-edition" + (" latest-edition" if latest else "") + (" owner-edition" if grading_on else "")
    return f'<section class="{css}">{head}<div class="edition-items">{body}</div></section>'


# ---------------------------------------------------------------------------------------------- search


def search(editions: list[dict], query: str) -> list[dict]:
    terms = query.casefold().split()
    if not terms:
        return editions
    out = []
    for edition in editions:
        hits = []
        for item in items_of(edition):
            modules = item_modules(item)
            hay = " ".join(one_line(v) for v in (
                item.get("headline"), item.get("text"), item.get("body"), item.get("module"), item.get("tier"),
                " ".join(modules), " ".join(module_name(m) for m in modules),
                " ".join(label for _, label in sources_of(item)), " ".join(url for url, _ in sources_of(item)),
            )).casefold()
            if all(term in hay for term in terms):
                hits.append(item)
        if hits:
            out.append({**edition, "items": hits, FULL_ITEMS: as_list(edition.get("items"))})
    return out


# ---------------------------------------------------------------------------------------------- page


def load(ws: Workspace) -> tuple[list[dict], bool]:
    """Every loaded page, in order; True when an earlier page exists."""
    pages = max(1, min(MAX_PAGES, int(st.session_state.get(f"feed_pages_{ws.id}", 1))))
    out: list[dict] = []
    before: str | None = None
    more = False
    for _ in range(pages):
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


def grade_options(edition: dict) -> list[dict]:
    """Gradable items: by edition item id when the hub gives one, else by edition id and rank."""
    options = []
    eid = edition_id(edition)
    for item in items_of(edition):
        rank = as_int(item.get("rank"))
        item_id = as_int(item.get("id"))
        if item_id is None and (eid is None or rank is None):
            continue
        options.append({
            "key": f"item-{item_id}" if item_id is not None else f"rank-{eid}-{rank}",
            "label": f"{rank if rank is not None else '–'}. {clip(pick(item, 'headline', 'title', 'text', default=''), 90)}",
            "item_id": item_id, "edition_id": eid, "item_rank": rank, "event_id": as_int(item.get("event_id")),
        })
    return options


def render_notes(edition: dict) -> None:
    """The edition's grading note, collapsed at the bottom of the edition (nothing when there is none)."""
    note = note_of(edition)
    if note:
        with st.expander(NOTES_LABEL):
            st.markdown(f'<div class="grading-notes">{esc_lines(note)}</div>', unsafe_allow_html=True)


def render_edition(ws: Workspace, edition: dict, index: int, latest: bool, grading_on: bool) -> None:
    """One edition card: the band and items, its grading notes, and (for the owner) its grade form."""
    eid = edition_id(edition)
    options = grade_options(edition) if grading_on and eid is not None else []
    with st.container(key=f"zx_edition_{index}"):
        if not options:
            st.markdown(edition_html(edition, ws.timezone, latest=latest), unsafe_allow_html=True)
            render_notes(edition)
            return
        with st.form(f"grade_edition_{ws.id}_{eid}", border=False):
            st.markdown(edition_html(edition, ws.timezone, latest=latest, grading_on=True), unsafe_allow_html=True)
            render_notes(edition)
            grading.grade_form(ws, f"ed_{ws.id}_{eid}", options,
                               f"Grade an item · {fmt_short(edition_time(edition), ws.timezone)}")


def render(ws: Workspace) -> None:
    try:
        editions, more = load(ws)
    except api.ApiError as exc:
        st.markdown(empty_state(f"Could not load editions from the {ws.label} hub.", str(exc)), unsafe_allow_html=True)
        return
    if not editions:
        st.markdown(empty_state(
            "No editions yet. The Zenux Grader publishes one at each scheduled run once the hub has candidates."),
            unsafe_allow_html=True)
        return
    query = one_line(st.session_state.get("feed_search", ""))
    shown = search(editions, query)
    if query:
        hits = sum(len(items_of(e)) for e in shown)
        st.markdown(section_label(plural(hits, "search result")), unsafe_allow_html=True)
        if not shown:
            st.markdown(empty_state("No matching stories. Try another company, topic or source."), unsafe_allow_html=True)
    grading_on = bool(st.session_state.get("grading_enabled"))
    for index, edition in enumerate(shown):
        render_edition(ws, edition, index, latest=not query and index == 0, grading_on=grading_on)
    if more and not query:
        if st.button("Load earlier editions", key=f"feed_more_{ws.id}"):
            st.session_state[f"feed_pages_{ws.id}"] = int(st.session_state.get(f"feed_pages_{ws.id}", 1)) + 1
            st.rerun()
