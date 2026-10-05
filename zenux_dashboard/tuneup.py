"""The weekly tune-up on the Briefing (docs/SPEC-SIMPLIFY.md 2.2 and 1.5): one banner line while GET /tuneup says it is
due, "Start" to open an inline panel, "Skip this week" (POST /tuneup/dismiss).

The panel lists the stories the hub picked (up to its `target`, 5: the ones whose scores sat closest to their
briefing's bar this week), one compact row each: the title (linked), the dateline (date · source · coverage area),
what the editor did ("In your briefing at 74" / "Left out at 66, bar 70"), and a one-click rating: Top story, In the
briefing, Near miss or Not relevant (POST /feedback, item_id for a published story, else event_id; no dialog, score or
note here). The rows the panel opened with stay put while they are rated (a rated row says so), and once every row is
rated the panel says "Thanks. The editor uses your ratings from the next briefing." and can be closed.

The panel's state is per workspace and per tune-up week, in session state (PANEL_KEY), so a rerun or a fresh GET
/tuneup (every write clears the read caches) never moves the rows under the analyst's pointer. An older hub (no GET
/tuneup) or a failed read shows nothing: the tune-up is an offer, never an alert.
"""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from . import api, data, labels, owner, ui
from .config import Workspace
from .fmt import as_int, dicts, esc, fmt_date, link, module_color, one_line, pick, plural, tag_style

PANEL_KEY = "tu_panel"  # {workspace id: {"week", "open", "items", "rated": {row key: verdict}}}
DEFAULT_TARGET = 5
CHOICES = labels.RATING_CHOICES  # lead, digest, watch, reject
BANNER = "Weekly tune-up: rate {count} so the editor learns your bar (about 2 minutes)."
DONE = "Thanks. The editor uses your ratings from the next briefing."
SKIPPED = "Skipped this week's tune-up. It comes back next week."
RATED = "Rated: {rating}."
PANEL_HEAD = "Rate each story the way you would have wanted it."


def panels() -> dict:
    value = st.session_state.get(PANEL_KEY)
    return dict(value) if isinstance(value, dict) else {}


def panel_of(ws: Workspace) -> dict:
    value = panels().get(ws.id)
    return dict(value) if isinstance(value, dict) else {}


def save_panel(ws: Workspace, panel: dict) -> None:
    store = panels()
    store[ws.id] = panel
    st.session_state[PANEL_KEY] = store


# ---------------------------------------------------------------------------------------------- shapes (pure)


def items_of(body: Any) -> list[dict]:
    """The tune-up's stories that can be rated: each needs an event id (or a briefing item)."""
    out = []
    for item in dicts(pick(body, "items", default=[])):
        if as_int(item.get("event_id")) is not None or as_int(item.get("item_id")) is not None:
            out.append(dict(item))
    return out


def target_of(body: Any) -> int:
    target = as_int(pick(body, "target"))
    return target if target is not None and target > 0 else DEFAULT_TARGET


def is_due(body: Any) -> bool:
    """The hub's `due` (not skipped this week, fewer than 5 ratings this week, and stories left), and at least one
    story to rate."""
    return isinstance(body, Mapping) and body.get("due") is True and bool(items_of(body))


def row_key(item: Mapping) -> str:
    """'i1201' for a published story (rated by its briefing item), else 'e7201' (rated by the story)."""
    item_id = as_int(item.get("item_id"))
    return f"i{item_id}" if item_id is not None else f"e{as_int(item.get('event_id'))}"


def banner_text(count: int) -> str:
    """'Weekly tune-up: rate 5 stories so the editor learns your bar (about 2 minutes).'"""
    return BANNER.format(count=plural(count, "story", "stories"))


def editor_line(item: Mapping) -> str:
    """What the editor did: 'In your briefing at 74' or 'Left out at 66, bar 70' (with the hub's plain reason)."""
    score, bar = as_int(item.get("score")), as_int(item.get("bar"))
    if one_line(item.get("decision")) == "selected":
        return "In your briefing" + (f" at {score}" if score is not None else "")
    text = "Left out" + (f" at {score}" if score is not None else "") + (f", bar {bar}" if bar is not None else "")
    reason = one_line(item.get("reason_text"))
    return f"{text} · {reason}" if reason and not ui.looks_technical(reason) else text


def area_html(item: Mapping) -> str:
    module = one_line(item.get("module"))
    name = labels.area_name(module, item.get("area_label")) if module else one_line(item.get("area_label"))
    if not name:
        return ""
    return f'<span class="module-tag" style="{tag_style(module_color(module or name))}">{esc(name.upper())}</span>'


def row_html(item: Mapping, tz: str) -> str:
    """One compact row: the title (linked), then the dateline and what the editor did."""
    title = one_line(item.get("title")) or "A story"
    date = fmt_date(item.get("published_at"), tz)
    source = one_line(item.get("source_label"))
    parts = [p for p in (date if date not in ("", "—") else "", source) if p]
    area = area_html(item)
    dateline = esc(" · ".join(parts)) + ((" · " if parts else "") + area if area else "")
    return ('<div class="tu-row">'
            f'<div class="tu-title">{link(item.get("url"), title, "filtered-link")}</div>'
            + (f'<div class="feed-dateline">{dateline}</div>' if dateline else "")
            + f'<div class="tu-editor">{esc(editor_line(item))}</div></div>')


# ---------------------------------------------------------------------------------------------- writes (callbacks)


def _start(ws: Workspace, week: Any, items: list[dict]) -> None:
    save_panel(ws, {"week": week, "open": True, "items": [dict(i) for i in items], "rated": {}})


def _close(ws: Workspace) -> None:
    panel = panel_of(ws)
    panel["open"] = False
    save_panel(ws, panel)


def _rate(ws: Workspace, item: dict, verdict: str) -> None:
    """One click: POST /feedback {verdict, scope: item, item_id | event_id}; no undo route (the story's star withdraws
    a rating)."""
    item_id = as_int(item.get("item_id"))
    event_id = None if item_id is not None else as_int(item.get("event_id"))
    rating = labels.VERDICT_LABELS.get(verdict, "your rating")
    result = ui.write(ws, lambda token: api.add_feedback(ws, token, verdict=verdict, item_id=item_id,
                                                         event_id=event_id, scope="item"),
                      toast=RATED.format(rating=rating), in_callback=True)
    if result is not None:
        panel = panel_of(ws)
        rated = dict(panel.get("rated") or {})
        rated[row_key(item)] = verdict
        panel["rated"] = rated
        save_panel(ws, panel)


def _skip(ws: Workspace, week: Any) -> None:
    """Skip this week: POST /tuneup/dismiss; the banner is gone until next week (no undo route)."""
    result = ui.write(ws, lambda token: api.dismiss_tuneup(ws, token), toast=SKIPPED, in_callback=True)
    if result is not None:
        save_panel(ws, {"week": pick(result, "week") or week, "open": False, "items": [], "rated": {},
                        "skipped": True})


# ---------------------------------------------------------------------------------------------- page


def read(ws: Workspace) -> Mapping | None:
    """GET /tuneup, or None when it cannot be read (an older hub answers 404): no banner then."""
    try:
        body = data.tuneup(ws.id)
    except api.ApiError:
        return None
    return body if isinstance(body, Mapping) else None


def render(ws: Workspace) -> None:
    """The banner while the tune-up is due, and the panel while it is open (also after the last rating turned `due`
    off, so the thanks can be read)."""
    body = read(ws)
    week = pick(body, "week") if body is not None else None
    panel = panel_of(ws)
    if panel and body is not None and week is not None and panel.get("week") != week:
        panel = {}  # a new week: a new tune-up
        save_panel(ws, panel)
    is_open = panel.get("open") is True
    if not is_open and not is_due(body):
        return
    items = items_of(body)[:target_of(body)] if body is not None else []
    with st.container(key="zx_tuneup"):
        if not is_open:
            banner(ws, week, items)
            return
        panel_view(ws, panel, week)


def banner(ws: Workspace, week: Any, items: list[dict]) -> None:
    with st.container(horizontal=True, key="zx_tuneup_banner", gap="small", vertical_alignment="center"):
        st.markdown(f'<div class="zx-banner-text">{esc(banner_text(len(items)))}</div>', unsafe_allow_html=True)
        st.button("Start", key="tu_start", type="primary", on_click=_start, args=(ws, week, items))
        ui.write_button("Skip this week", ws=ws, key="tu_skip", type="tertiary", on_click=_skip, args=(ws, week))


def panel_view(ws: Workspace, panel: Mapping, week: Any) -> None:
    items = dicts(panel.get("items"))
    rated = panel.get("rated") if isinstance(panel.get("rated"), dict) else {}
    done = bool(items) and all(row_key(i) in rated for i in items)
    with st.container(horizontal=True, key="zx_tuneup_head", gap="small", vertical_alignment="center"):
        head = DONE if done else f"Weekly tune-up · {len(rated)} of {plural(len(items), 'story', 'stories')} rated"
        st.markdown(f'<div class="zx-banner-text">{esc(head)}</div>', unsafe_allow_html=True)
        st.button("Close" if done else "Hide", key="tu_close", type="tertiary", on_click=_close, args=(ws,))
        if not done:
            ui.write_button("Skip this week", ws=ws, key="tu_skip", type="tertiary", on_click=_skip, args=(ws, week))
    if done:
        return
    st.caption(PANEL_HEAD)
    if not owner.can_edit(ws):
        ui.locked_hint(ws)
    for item in items:
        key = row_key(item)
        with st.container(key=f"zx_tu_{key}"):
            st.markdown(row_html(item, ws.timezone), unsafe_allow_html=True)
            verdict = rated.get(key)
            if verdict:
                st.markdown(f'<div class="tu-done">{esc(RATED.format(rating=labels.VERDICT_LABELS.get(verdict, "")))}'
                            '</div>', unsafe_allow_html=True)
                continue
            with st.container(horizontal=True, key=f"zx_tu_choices_{key}", gap="small"):
                for choice in CHOICES:
                    ui.write_button(labels.VERDICT_LABELS[choice], ws=ws, key=f"tu_{choice}_{key}", type="secondary",
                                    on_click=_rate, args=(ws, dict(item), choice))
