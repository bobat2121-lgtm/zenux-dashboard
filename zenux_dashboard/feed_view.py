"""Feed: published Zenux editions, newest first (GET /editions?limit=10&before=).

An edition item carries rank, event_id, score, tier, headline, factual text (at most 150 words), metrics (at
most 5), sources (at most 4) and story_id. Fields are read tolerantly, so an older or newer hub shape still
renders; anything unknown is left out rather than guessed.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from . import api, data, grading
from .config import Workspace
from .fmt import (as_int, as_list, chip, clip, dicts, domain_of, empty_state, esc, esc_lines, fmt_short, fmt_time,
                  label_of, link, one_line, palette_for, parse_time, pick, plural, relative_time, safe_url, section_label)

PAGE_SIZE = 10
MAX_PAGES = 20
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


def edition_id(edition: dict) -> Any:
    return pick(edition, "id", "edition_id")


def edition_time(edition: dict) -> Any:
    return pick(edition, "published_at", "created_at", "posted_at")


def score_level(score: Any) -> str | None:
    n = as_int(score)
    if n is None:
        return None
    return "high" if n >= 90 else "medium" if n >= 70 else "low"


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


def item_group(item: dict) -> str:
    return one_line(pick(item, "module", "module_id", "lane")) or tier_label(item.get("tier")) or ""


# ---------------------------------------------------------------------------------------------- html


def item_html(item: dict, colors: dict[str, str]) -> str:
    rank = as_int(item.get("rank"))
    marker = str(rank).zfill(2) if rank is not None else "–"
    sources = sources_of(item)
    meta = []
    if sources:
        meta.append(f'<span class="feed-worker">{esc(sources[0][1])}</span>')
    group = item_group(item)
    if group:
        meta.append(f'<span class="feed-theme"><i style="background:{colors.get(group, "#b692f6")}"></i>{esc(label_of(group))}</span>')
    tier = tier_label(item.get("tier"))
    if tier and tier != label_of(group):
        meta.append(chip(tier))
    headline = one_line(pick(item, "headline", "title"))
    text = pick(item, "text", "body", "summary", "factual_text", default="")
    metrics = "".join(metric_html(m) for m in as_list(item.get("metrics"))[:5])
    metrics_html = f'<div class="feed-metrics">{metrics}</div>' if metrics else ""
    source_links = "".join(link(url, f"{label} ↗") for url, label in sources)
    level = score_level(item.get("score"))
    badge = (f'<span class="value-badge level-{level}">score {esc(as_int(item.get("score")))}</span>' if level else "")
    badge += grading.feedback_chips(item.get("feedback"))
    summary = (f'<div class="feed-item-headline">{esc(headline)}</div>' if headline
               else '<span class="feed-summary-label">Read the item</span>')
    return (
        f'<article class="feed-item{" has-value" if level else ""}">'
        f'<div class="rank-marker">{esc(marker)}</div>'
        '<div class="feed-copy">'
        f'<div class="feed-meta">{"".join(meta)}</div>'
        '<details class="feed-details">'
        f'<summary class="feed-toggle">{summary}</summary>'
        f'<div class="feed-text">{esc_lines(text)}</div>'
        f'{metrics_html}'
        f'<div class="feed-sources">{source_links}</div>'
        '</details>'
        f'<div class="feed-meta">{badge}{"" if source_links else "<span>No source link captured</span>"}</div>'
        '</div></article>'
    )


def stats_html(edition: dict, items: list[dict], colors: dict[str, str]) -> str:
    scores = [as_int(i.get("score")) for i in items]
    reviewed = as_int(pick(edition, "reviewed", "candidates", "candidate_count", "stats.candidates", "stats.reviewed"))
    tiles = [
        ("ITEMS", len(items), ""),
        ("REVIEWED", reviewed if reviewed is not None else "—", ""),
        ("LEAD 90+", sum(1 for s in scores if s is not None and s >= 90), " stat-high"),
        ("DIGEST 70–89", sum(1 for s in scores if s is not None and 70 <= s < 90), " stat-medium"),
    ]
    tiles_html = "".join(
        f'<div class="stat{css}"><div class="stat-n">{esc(n)}</div><div class="stat-l">{esc(name)}</div></div>'
        for name, n, css in tiles
    )
    groups: dict[str, int] = {}
    for item in items:
        group = item_group(item)
        if group:
            groups[group] = groups.get(group, 0) + 1
    bar = "".join(f'<span style="flex-grow:{n};background:{colors[g]}"></span>' for g, n in groups.items())
    legend = "".join(f'<span><i style="background:{colors[g]}"></i>{esc(label_of(g).upper())} {n}</span>' for g, n in groups.items())
    themes = f'<div class="theme-bar">{bar}</div><div class="theme-legend">{legend}</div>' if groups else ""
    return f'<div class="edition-stats"><div class="stat-grid">{tiles_html}</div>{themes}</div>'


def edition_html(edition: dict, tz: str, latest: bool = False, grading_on: bool = False) -> str:
    items = items_of(edition)
    colors = palette_for(item_group(i) for i in items if item_group(i))
    when = edition_time(edition)
    eid = edition_id(edition)
    label = one_line(pick(edition, "label", "slot", "trigger_label")) or (f"Edition #{eid}" if eid is not None else "Edition")
    kicker = (
        '<div class="edition-kicker">'
        + ('<span class="latest-badge">LATEST</span>' if latest else "")
        + f'<span class="edition-label">{esc(label)}</span>'
        f'<span>·</span><span>{esc(relative_time(when))}</span>'
        f'<span>·</span><span>{esc(fmt_time(when, tz))}</span>'
        f'<span>·</span><span>{esc(plural(len(items), "item"))}</span>'
        '</div>'
    )
    headline = one_line(pick(edition, "headline", "title"))
    note = one_line(edition.get("note"))
    main = (kicker + (f'<div class="edition-headline">{esc(headline)}</div>' if headline else "")
            + (f'<div class="edition-note">{esc(note)}</div>' if note else ""))
    head = (f'<div class="edition-head has-stats"><div class="edition-main">{main}</div>{stats_html(edition, items, colors)}</div>'
            if latest else f'<div class="edition-head">{main}</div>')
    body = "".join(item_html(item, colors) for item in items) or (
        '<div class="edition-empty">Nothing material in this window: the Grader published an empty edition.</div>')
    css = "feed-edition" + (" latest-edition" if latest else "") + (" owner-edition" if grading_on else "")
    return f'<section class="{css}">{head}{body}</section>'


# ---------------------------------------------------------------------------------------------- search


def search(editions: list[dict], query: str) -> list[dict]:
    terms = query.casefold().split()
    if not terms:
        return editions
    out = []
    for edition in editions:
        hits = []
        for item in items_of(edition):
            hay = " ".join(one_line(v) for v in (
                item.get("headline"), item.get("text"), item.get("body"), item.get("module"), item.get("tier"),
                " ".join(label for _, label in sources_of(item)), " ".join(url for url, _ in sources_of(item)),
            )).casefold()
            if all(term in hay for term in terms):
                hits.append(item)
        if hits:
            out.append({**edition, "items": hits})
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
    if grading_on:
        for index, edition in enumerate(shown):
            latest = not query and index == 0
            eid = edition_id(edition)
            options = grade_options(edition)
            if eid is None or not options:
                st.markdown(edition_html(edition, ws.timezone, latest=latest), unsafe_allow_html=True)
                continue
            with st.form(f"grade_edition_{ws.id}_{eid}", border=False):
                st.markdown(edition_html(edition, ws.timezone, latest=latest, grading_on=True), unsafe_allow_html=True)
                grading.grade_form(ws, f"ed_{ws.id}_{eid}", options,
                                   f"Grade an item · {fmt_short(edition_time(edition), ws.timezone)}")
    else:
        html = "".join(edition_html(e, ws.timezone, latest=not query and i == 0) for i, e in enumerate(shown))
        if html:
            st.markdown(f'<main class="edition-stack" aria-label="Published editions">{html}</main>', unsafe_allow_html=True)
    if more and not query:
        if st.button("Load earlier editions", key=f"feed_more_{ws.id}"):
            st.session_state[f"feed_pages_{ws.id}"] = int(st.session_state.get(f"feed_pages_{ws.id}", 1)) + 1
            st.rerun()
