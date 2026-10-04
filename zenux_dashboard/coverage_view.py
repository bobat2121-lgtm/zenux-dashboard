"""Coverage: who and what ZENUX collects in each coverage area, in the analyst's words (GET /modules, GET
/modules/<id>/inspect).

Pick a coverage area (a module: `cv_area`, mirrored as `module` in the page's link), then:

- a header: the area's title and plain description, and its counts (companies, sources on and off, stories this
  week, how many made the briefings this week and in 30 days, mutes and stars);
- a search box (always visible: names, tickers, categories and source names in all four columns) and a Filters
  popover with "Show": All, On your watchlist, Muted, Name only (gaps), Not responding;
- four columns: Public companies, Private and state-owned (entities by ownership, grouped by category), Industry
  sources and Government and public record (the area's own sources by lane column, grouped by lane; programs and
  agencies join Government). A company's own feeds appear in its details, not as rows. Each group is a lazy expander
  whose rows are drawn only while it is open (search and Show open every matching group).
- a company row: name and tickers, coverage chips (own feed, SEC filings, federal contracts, news search, name only),
  stories this week (and how many made the briefings) and in briefings (30 days), Muted / On your watchlist, and
  Star / Starred and Details; a source row: name, kind, health in plain words, stats, Muted, and Mute / Unmute and
  Details.
- Details open the `company` or `source` dialog (registered here). Mute, unmute and star go through the card-action
  dialogs of `actions` (preview first, a toast, undo); Unmute takes the inspector's full mute reference (kind, ref,
  label). A dialog cannot open another one, so these dialogs close themselves before opening the next. "Request
  coverage" opens the `request` dialog of `radar_view`, prefilled.

Every mute surface says it: muted sources and companies are still collected, kept out of the briefing. Below the
columns, `radar_view.render_requests(ws, module_id)` draws the coverage requests. While the workspace is staging, a
banner asks the analyst to review this page and What ZENUX looks for, then sign off.
"""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from . import actions, api, data, labels, links, radar_view, ui
from .config import Workspace, load_config
from .fmt import (as_int, as_list, chip, dicts, domain_of, empty_state, esc, fmt_date, label_of, link, md_label,
                  one_line, pick, plural, safe_url)

AREA_KEY = "cv_area"
SEARCH_KEY = "cv_search"
SHOW_KEY = "cv_show"
SHOW_CHOICES = {"all": "All", "starred": "On your watchlist", "muted": "Muted", "name_only": "Name only (gaps)",
                "failing": "Not responding"}
PUBLIC = "public"
PROGRAM_ROLE = "program"
PROGRAM_GROUP = "Programs and agencies"
GOVERNMENT = "government"
OTHER_COMPANIES = "Other companies"
OTHER_SOURCES = "Other sources"
CATALOG_MISSING = "catalog_missing"
UNKNOWN_MODULE = "unknown_module"
STAR_MUTED_HELP = "{name} is muted. Unmute it first."
MUTE_STARRED_HELP = "{name} is on your watchlist. Remove the star first."
ASK_JUMP = "Ask for a source, a company or a topic ↓"


# ---------------------------------------------------------------------------------------------- shapes (pure)


def modules_of(body: Any) -> list[dict]:
    """GET /modules rows with a usable id, first occurrence only."""
    out, seen = [], set()
    for m in dicts(pick(body, "modules", default=[])):
        mid = one_line(m.get("id"))
        if mid and mid not in seen:
            seen.add(mid)
            out.append(m)
    return out


def entity_column(entity: Mapping) -> str:
    """public | private | government: programs and agencies are public record, every other company by ownership
    (private, subsidiary, government-owned or missing: Private and state-owned)."""
    if one_line(entity.get("role")).lower() == PROGRAM_ROLE:
        return GOVERNMENT
    return "public" if one_line(entity.get("ownership")).lower() == PUBLIC else "private"


def source_column(source: Mapping) -> str | None:
    """industry | government for the area's own sources; None for a company's own feeds (shown in its details)."""
    if one_line(source.get("origin")).lower() == "entity":
        return None
    return GOVERNMENT if one_line(source.get("column")).lower() == GOVERNMENT else "industry"


def entity_group(entity: Mapping) -> str:
    if one_line(entity.get("role")).lower() == PROGRAM_ROLE:
        return PROGRAM_GROUP
    label = one_line(entity.get("category_label")) or label_of(entity.get("category"))
    return (label[:1].upper() + label[1:]) if label else OTHER_COMPANIES


def source_group(source: Mapping) -> str:
    label = one_line(source.get("lane_label")) or label_of(source.get("lane"))
    return (label[:1].upper() + label[1:]) if label else OTHER_SOURCES


def coverage_flags(entity: Mapping) -> list[tuple[str, str, str]]:
    """(flag, chip label, help) for each true coverage flag, in COVERAGE_ICONS order."""
    coverage = entity.get("coverage") if isinstance(entity.get("coverage"), Mapping) else {}
    return [icon for icon in labels.COVERAGE_ICONS if coverage.get(icon[0]) is True]


def tickers_of(entity: Mapping) -> str:
    return ", ".join(one_line(t) for t in as_list(entity.get("tickers")) if one_line(t))


def state_of(source: Mapping) -> str:
    return one_line(pick(source, "health.state")).lower()


def is_muted(row: Mapping) -> bool:
    return isinstance(row.get("muted"), Mapping)


def is_starred(row: Mapping) -> bool:
    return isinstance(row.get("starred"), Mapping)


def entity_text(entity: Mapping) -> str:
    return " ".join([one_line(entity.get("name")), tickers_of(entity), entity_group(entity),
                     " ".join(one_line(a) for a in as_list(entity.get("aliases")))]).casefold()


def source_text(source: Mapping) -> str:
    return " ".join([one_line(source.get("label")), one_line(source.get("kind")), source_group(source)]).casefold()


def terms_of(query: Any) -> list[str]:
    return [t for t in one_line(query).casefold().split(" ") if t]


def shown(row: Mapping, is_entity: bool, terms: list[str], show: str) -> bool:
    """Search (every term in the row's name, tickers, category, kind or lane) and the Show filter."""
    text = entity_text(row) if is_entity else source_text(row)
    if any(term not in text for term in terms):
        return False
    if show == "starred":
        return is_entity and is_starred(row)
    if show == "muted":
        return is_muted(row)
    if show == "name_only":
        return is_entity and bool(pick(row, "coverage.name_only"))
    if show == "failing":
        return not is_entity and state_of(row) == "failing"
    return True


def build_columns(insp: Mapping, terms: list[str] | None = None, show: str = "all") -> dict[str, list[tuple[str, list]]]:
    """{column: [(group label, [(index, row, is_entity)])]}: groups by size (largest first), then label. `index` is the
    row's position in the inspector's entities or sources list (stable within a read: widget keys use it)."""
    terms = terms or []
    buckets: dict[str, dict[str, list]] = {code: {} for code, _ in labels.COLUMNS}
    for n, entity in enumerate(dicts(insp.get("entities"))):
        if shown(entity, True, terms, show):
            buckets[entity_column(entity)].setdefault(entity_group(entity), []).append((n, entity, True))
    for n, source in enumerate(dicts(insp.get("sources"))):
        column = source_column(source)
        if column and shown(source, False, terms, show):
            buckets[column].setdefault(source_group(source), []).append((n, source, False))
    return {code: sorted(groups.items(), key=lambda g: (-len(g[1]), g[0].casefold())) for code, groups in buckets.items()}


def counts_line(insp: Mapping, card: Mapping | None) -> str:
    """'142 companies · 160 sources on (28 off) · 1840 stories this week (12 in your briefings) · 61 in your briefings
    (30 days)'."""
    counts = card.get("counts") if isinstance((card or {}).get("counts"), Mapping) else {}
    entities, sources = dicts(insp.get("entities")), dicts(insp.get("sources"))
    n_entities = as_int(counts.get("entities"))
    n_on = as_int(counts.get("sources_enabled"))
    n_off = as_int(counts.get("sources_off"))
    if n_on is None:
        n_on = sum(1 for s in sources if s.get("enabled") is not False)
    if n_off is None:
        n_off = sum(1 for s in sources if s.get("enabled") is False)
    totals = insp.get("totals") if isinstance(insp.get("totals"), Mapping) else {}
    return " · ".join(p for p in [
        plural(len(entities) if n_entities is None else n_entities, "company", "companies"),
        f"{plural(n_on, 'source')} on ({n_off} off)",
        f"{as_int(totals.get('items_7d')) or 0} stories this week{week_briefings(totals, ' in your briefings')}",
        month_briefings(totals),
    ] if p)


def month_briefings(stats: Mapping) -> str:
    """'61 in your briefings in 30 days', or '' when it would only repeat this week's figure (WF5 AW-12)."""
    month = as_int(stats.get("briefing_30d")) or 0
    week = as_int(stats.get("briefing_7d"))
    return "" if week is not None and week == month else f"{month} in your briefings in 30 days"


def week_briefings(stats: Mapping, words: str = " in briefings") -> str:
    """' (2 in briefings)': how many of this week's stories made a briefing (`briefing_7d`, gap 12); '' when the hub
    does not say."""
    n = as_int(stats.get("briefing_7d")) if isinstance(stats, Mapping) else None
    return f" ({n}{words})" if n is not None else ""


def tuning_line(insp: Mapping, card: Mapping | None) -> str:
    """'2 muted · 1 on your watchlist' when the area has any, else ''."""
    mutes, stars = as_int((card or {}).get("mutes")), as_int((card or {}).get("stars"))
    if mutes is None:
        mutes = sum(1 for r in dicts(insp.get("entities")) + dicts(insp.get("sources")) if is_muted(r))
    if stars is None:
        stars = sum(1 for r in dicts(insp.get("entities")) if is_starred(r))
    return f"{mutes} muted · {stars} on your watchlist" if mutes or stars else ""


def stats_text(row: Mapping) -> str:
    stats = row.get("stats") if isinstance(row.get("stats"), Mapping) else {}
    return (f"{as_int(stats.get('items_7d')) or 0} this week{week_briefings(stats)} · "
            f"{as_int(stats.get('briefing_30d')) or 0} in briefings (30 days)")


def health_text(source: Mapping, tz: str) -> str:
    """'Working', 'Not responding since Oct 1', 'Turned off: <why>' ..."""
    state = state_of(source)
    text = labels.SOURCE_STATE_LABELS.get(state) or one_line(pick(source, "health.label")) or "Not run yet"
    if state == "failing" and pick(source, "health.last_ok_at"):
        text += f" since {fmt_date(pick(source, 'health.last_ok_at'), tz)}"
    if state == "off" and one_line(source.get("off_reason")):
        text += f": {one_line(source.get('off_reason'))}"
    return text


def chips_html(entity: Mapping) -> str:
    return "".join(f'<span class="cov-chip cov-chip-{esc(flag)}" title="{esc(help_)}">{esc(label)}</span>'
                   for flag, label, help_ in coverage_flags(entity))


def state_chips(row: Mapping) -> str:
    return ((chip("Muted", "chip-state chip-muted") if is_muted(row) else "")
            + (chip("On your watchlist", "chip-state chip-starred") if is_starred(row) else ""))


def entity_row_html(entity: Mapping) -> str:
    tickers = tickers_of(entity)
    return (f'<div class="cov-row"><div class="cov-name">{esc(one_line(entity.get("name")) or "Unnamed company")}'
            + (f' <span class="cov-tickers">{esc(tickers)}</span>' if tickers else "") + "</div>"
            + (f'<div class="cov-chips">{chips_html(entity)}</div>' if coverage_flags(entity) else "")
            + f'<div class="cov-stats">{esc(stats_text(entity))}</div>'
            + (f"<div>{state_chips(entity)}</div>" if state_chips(entity) else "") + "</div>")


def source_row_html(source: Mapping, tz: str) -> str:
    kind = one_line(source.get("kind"))
    return (f'<div class="cov-row"><div class="cov-name">{esc(one_line(source.get("label")) or "Unnamed source")}</div>'
            f'<div class="cov-stats">{esc(" · ".join(p for p in (kind, health_text(source, tz)) if p))}</div>'
            f'<div class="cov-stats">{esc(stats_text(source))}</div>'
            + (f"<div>{state_chips(source)}</div>" if state_chips(source) else "") + "</div>")


def catalog_missing_sentence(name: str) -> str:
    """A coverage area whose details are not set up yet (the hub's sentence names the module id and "the next
    deploy")."""
    return f"Coverage details for {name} aren't ready yet. The builder is setting them up."


# ---------------------------------------------------------------------------------------------- lookups


def _inspect(workspace_id: str, module_id: str) -> Mapping | None:
    try:
        insp = data.inspect(workspace_id, module_id)
    except api.ApiError:
        return None
    return insp if isinstance(insp, Mapping) else None


def find_entity(insp: Mapping, entity_id: str) -> dict | None:
    return next((e for e in dicts(insp.get("entities")) if one_line(e.get("id")) == entity_id), None)


def find_source(insp: Mapping, key: str) -> dict | None:
    return next((s for s in dicts(insp.get("sources")) if one_line(s.get("key")) == key), None)


def mute_row(ref: Mapping, fallback: Mapping) -> dict:
    """The mute behind an inspector's `muted` reference ({mute_id, created_at, note, kind, module, ref, label}; gap
    32) as the unmute dialog takes it; the row's own kind, ref and name fill what the reference leaves out."""
    out = {**fallback, "id": as_int(pick(ref, "mute_id", "id")), "active": True}
    for field in ("kind", "module", "ref", "label", "note", "created_at"):
        if one_line(ref.get(field)):
            out[field] = ref.get(field)
    return out


def source_mute_fallback(module_id: str, source: Mapping) -> dict:
    return {"kind": "source", "module": module_id, "ref": one_line(source.get("key")),
            "label": one_line(source.get("label")) or one_line(source.get("key"))}


def entity_mute_fallback(entity: Mapping) -> dict:
    return {"kind": "entity", "module": None, "ref": one_line(entity.get("id")),
            "label": one_line(entity.get("name")) or one_line(entity.get("id"))}


# ---------------------------------------------------------------------------------------------- rows


def mute_source(ws: Workspace, module_id: str, source: Mapping) -> None:
    """Open the mute dialog (preview first) or the unmute dialog of `actions` for one of the area's sources."""
    label = one_line(source.get("label")) or one_line(source.get("key"))
    if is_muted(source):
        actions.open_unmute(ws, mute_row(source["muted"], source_mute_fallback(module_id, source)))
    else:
        actions.open_mute(ws, kind="source", ref=one_line(source.get("key")), label=label, module=module_id)


def render_entity_row(ws: Workspace, module_id: str, n: int, entity: Mapping) -> None:
    st.markdown(entity_row_html(entity), unsafe_allow_html=True)
    eid, name = one_line(entity.get("id")), one_line(entity.get("name")) or one_line(entity.get("id"))
    with st.container(horizontal=True, key=f"zx_actions_cv_e_{n}"):
        if is_starred(entity):
            if ui.write_button("Starred", ws=ws, key=f"cv_star_{n}", type="tertiary", icon=":material/star:",
                               help=f"Remove {name} from your watchlist"):
                actions.unstar(ws, eid, name)
        elif is_muted(entity):
            st.button("Star", key=f"cv_star_{n}", type="tertiary", icon=":material/star_border:", disabled=True,
                      help=STAR_MUTED_HELP.format(name=name))
        elif ui.write_button("Star", ws=ws, key=f"cv_star_{n}", type="tertiary", icon=":material/star_border:"):
            actions.open_star(ws, eid, name)
        if st.button("Details", key=f"cv_details_e_{n}", type="tertiary"):
            ui.open_dialog("company", workspace_id=ws.id, module_id=module_id, entity_id=eid)


def render_source_row(ws: Workspace, module_id: str, n: int, source: Mapping) -> None:
    st.markdown(source_row_html(source, ws.timezone), unsafe_allow_html=True)
    with st.container(horizontal=True, key=f"zx_actions_cv_s_{n}"):
        if ui.write_button("Unmute" if is_muted(source) else "Mute", ws=ws, key=f"cv_mute_s_{n}", type="tertiary"):
            mute_source(ws, module_id, source)
        if st.button("Details", key=f"cv_details_s_{n}", type="tertiary"):
            ui.open_dialog("source", workspace_id=ws.id, module_id=module_id,
                           source_key=one_line(source.get("key")))


def render_columns(ws: Workspace, module_id: str, insp: Mapping, terms: list[str], show: str) -> int:
    """The four columns; returns how many rows match."""
    active = bool(terms) or show != "all"
    columns = build_columns(insp, terms, show)
    total = sum(len(rows) for groups in columns.values() for _, rows in groups)
    for (code, title), col in zip(labels.COLUMNS, st.columns(4)):
        groups = columns[code]
        with col:
            st.markdown(f'<div class="cov-col"><span>{esc(title)}</span>'
                        f'<span> · {sum(len(rows) for _, rows in groups)}</span></div>', unsafe_allow_html=True)
            if not groups:
                st.caption("No matches." if active else "None in this coverage area.")
            for index, (label, rows) in enumerate(groups):
                group = st.expander(md_label(f"{label} · {len(rows)}"), expanded=active, key=f"cv_g_{code}_{index}",
                                    on_change="rerun")
                if not group.open:
                    continue  # lazy: rows are drawn only while the group is open
                with group:
                    for n, row, is_entity in rows:
                        (render_entity_row if is_entity else render_source_row)(ws, module_id, n, row)
    return total


# ---------------------------------------------------------------------------------------------- page


def _mirror_area() -> None:
    links.set_focus(module=st.session_state.get(AREA_KEY) or None)


def pick_area(modules: list[dict]) -> str:
    """The coverage-area control (a segmented control). A `module` link, or a module chosen in the Control room,
    selects it; the analyst's own choice is mirrored into the link by the control's callback (the default first
    area is not, so merely opening Coverage never pins a module for the other tabs)."""
    ids = [one_line(m.get("id")) for m in modules]
    titles = {one_line(m.get("id")): m.get("title") for m in modules}
    focus = links.focus("module")
    if focus in ids and st.session_state.get(AREA_KEY) != focus:
        st.session_state[AREA_KEY] = focus
    elif st.session_state.get(AREA_KEY) not in ids:
        st.session_state[AREA_KEY] = ids[0]
    return st.segmented_control("Coverage area", ids, key=AREA_KEY, required=True, on_change=_mirror_area,
                                format_func=lambda m: labels.area_name(m, titles.get(m))) or ids[0]


def render_staging(ws: Workspace) -> None:
    try:
        stage = one_line(pick(data.settings(ws.id), "stage.stage")).lower()
    except api.ApiError:
        return  # a failing settings read never blocks the page
    if stage != "staging":
        return
    text_col, button_col = st.columns([5, 1], vertical_alignment="center")
    text_col.info("Review who and what ZENUX covers here and in My preferences › What ZENUX looks for, then sign off.")
    if button_col.button("Go to sign-off", key="cv_signoff", type="primary"):
        links.go("preferences", section="looks_for")


def render_head(insp: Mapping, card: Mapping | None, name: str) -> None:
    mod = insp.get("module") if isinstance(insp.get("module"), Mapping) else {}
    title = one_line(mod.get("title")) or one_line((card or {}).get("title")) or name
    description = one_line(mod.get("description"))  # plain: the hub drops the manifest's file references (gap 33)
    tuning = tuning_line(insp, card)
    st.markdown(
        f'<div class="cov-head"><div class="cov-title">{esc(title)}</div>'
        + (f'<div class="cov-desc">{esc(description)}</div>' if description else "")
        + f'<div class="cov-stats">{esc(counts_line(insp, card))}</div>'
        + (f'<div class="cov-stats">{esc(tuning)}</div>' if tuning else "") + "</div>",
        unsafe_allow_html=True)


def render_area(ws: Workspace, module_id: str, card: Mapping | None) -> None:
    name = labels.area_name(module_id, (card or {}).get("title"))
    try:
        insp = data.inspect(ws.id, module_id)
    except api.ApiError as exc:
        if exc.code == CATALOG_MISSING:
            st.info(md_label(catalog_missing_sentence(name)))
        elif exc.code == UNKNOWN_MODULE:
            st.info(md_label(f"{name} isn't set up in this workspace yet."))
        else:
            ui.error_box(f"the details of {name}", exc, key="coverage_area")
        return
    render_head(insp, card, name)
    search_col, filter_col = st.columns([5, 1], vertical_alignment="bottom")
    query = search_col.text_input("Search companies and sources", key=SEARCH_KEY, label_visibility="collapsed",
                                  placeholder="Search companies and sources: name, ticker, category or source name")
    show = st.session_state.get(SHOW_KEY) if st.session_state.get(SHOW_KEY) in SHOW_CHOICES else "all"
    with filter_col, ui.filters(0 if show == "all" else 1, key="cv_filters"):
        show = st.radio("Show", list(SHOW_CHOICES), key=SHOW_KEY, format_func=SHOW_CHOICES.get) or "all"
    terms = terms_of(query)
    if terms or show != "all":
        matches = sum(len(rows) for groups in build_columns(insp, terms, show).values() for _, rows in groups)
        st.caption(f"{plural(matches, 'match', 'matches')}"
                   + ("" if matches else ". Try another word, or ask for coverage below."))
    else:
        st.caption("Open a group to see who is in it. Star a company to put it on your watchlist; mute a source or "
                   "company you don't want. Muted: " + labels.STILL_COLLECTED)
    render_columns(ws, module_id, insp, terms, show)


def render(ws: Workspace) -> None:
    """Coverage: pick a coverage area, its header, search and filters, the four columns, then coverage requests."""
    render_staging(ws)
    # The request form sits under every company and source group; a jump to it at the top (WF5 AW-13).
    st.markdown(f'<div class="zx-jump"><a href="#{radar_view.REQUESTS_ANCHOR}">{esc(ASK_JUMP)}</a></div>',
                unsafe_allow_html=True)
    area = None
    try:
        modules = modules_of(data.modules(ws.id))
    except api.ApiError as exc:
        ui.error_box("coverage areas", exc, key="coverage")
        modules = []
    else:
        if not modules:
            st.markdown(empty_state("No coverage areas yet. They appear after the builder's first setup."),
                        unsafe_allow_html=True)
    if modules:
        pick_col, refresh_col = st.columns([6, 1], vertical_alignment="bottom")
        with pick_col:
            area = pick_area(modules)
        with refresh_col:
            ui.refresh_button("coverage")
        render_area(ws, area, next((m for m in modules if one_line(m.get("id")) == area), None))
    radar_view.render_requests(ws, area)


# ---------------------------------------------------------------------------------------------- dialogs


def _dialog_ws(workspace_id: str) -> Workspace | None:
    ws = load_config().workspace(workspace_id)
    if ws is None:
        ui.close_dialog()
    return ws


def _then(open_next) -> None:
    """Close this dialog, open the next one (mute, unmute, star, request), rerun: one dialog at a time."""
    ui.close_dialog()
    open_next()
    st.rerun()


def _close_button() -> None:
    if st.button("Close", key="dlg_cancel"):
        ui.close_dialog()
        st.rerun()


def _company_dialog(workspace_id: str, module_id: str, entity_id: str) -> None:
    """A company's coverage: flags with their meaning, its own feeds (with mute switches), stats, Mute company,
    Star or Remove from watchlist, and Request coverage (primary when ZENUX only catches it by name)."""
    ws = _dialog_ws(workspace_id)
    if ws is None:
        return
    insp = _inspect(ws.id, module_id)
    entity = find_entity(insp, entity_id) if insp else None
    if entity is None:
        st.info("This company is no longer listed in this coverage area.")
        _close_button()
        return
    name = one_line(entity.get("name")) or entity_id
    category = entity_group(entity)
    tickers = tickers_of(entity)
    st.markdown(f'<div class="cov-head"><div class="cov-title">{esc(name)}</div>'
                f'<div class="cov-stats">{esc(" · ".join(p for p in (category, tickers) if p))}</div>'
                + (f"<div>{state_chips(entity)}</div>" if state_chips(entity) else "") + "</div>",
                unsafe_allow_html=True)
    lines = [(label, help_) for flag, label, help_ in coverage_flags(entity) if flag != "name_only"]
    if pick(entity, "coverage.name_only"):
        lines.append(("Name only", f"ZENUX only catches {name} when another source names it."))
    st.markdown('<div class="why-block">' + ("".join(
        f'<div class="why-row"><span class="why-label">{esc(label)}</span> {esc(text)}</div>' for label, text in lines)
        or '<div class="why-row">No coverage details yet.</div>') + "</div>", unsafe_allow_html=True)
    stats = entity.get("stats") if isinstance(entity.get("stats"), Mapping) else {}
    st.caption(f"{plural(as_int(stats.get('items_7d')) or 0, 'story', 'stories')} this week"
               f"{week_briefings(stats, ' in your briefings')} · "
               f"{as_int(stats.get('items_30d')) or 0} in 30 days · "
               f"{as_int(stats.get('briefing_30d')) or 0} in your briefings (30 days)"
               + (f" · last {fmt_date(stats.get('last_item_at'), ws.timezone)}" if stats.get("last_item_at") else ""))
    feeds = [s for s in (find_source(insp, one_line(k)) for k in as_list(entity.get("source_keys"))) if s]
    if feeds:
        st.markdown('<div class="refine-label">Its own feeds</div>', unsafe_allow_html=True)
        for i, feed in enumerate(feeds):
            text_col, button_col = st.columns([4, 1], vertical_alignment="center")
            text_col.markdown(f'<div class="cov-row"><div class="cov-name">{esc(one_line(feed.get("label")))}</div>'
                              f'<div class="cov-stats">{esc(health_text(feed, ws.timezone))} · {esc(stats_text(feed))}'
                              f'</div>{state_chips(feed)}</div>', unsafe_allow_html=True)
            with button_col:
                if ui.write_button("Unmute" if is_muted(feed) else "Mute", ws=ws, key=f"dlg_mute_s_{i}",
                                   type="tertiary"):
                    _then(lambda feed=feed: mute_source(ws, module_id, feed))
    st.caption(labels.STILL_COLLECTED + " You can unmute any time and bring back the last 7 days.")
    starred, muted = is_starred(entity), is_muted(entity)
    name_only = bool(pick(entity, "coverage.name_only"))
    with st.container(horizontal=True, key="zx_actions_dlg_company"):
        if muted:
            if ui.write_button("Unmute company", ws=ws, key="dlg_mute"):
                _then(lambda: actions.open_unmute(ws, mute_row(entity["muted"], entity_mute_fallback(entity))))
        elif starred:
            st.button("Mute company", key="dlg_mute", disabled=True, help=MUTE_STARRED_HELP.format(name=name))
        elif ui.write_button("Mute company", ws=ws, key="dlg_mute"):
            _then(lambda: actions.open_mute(ws, kind="entity", ref=entity_id, label=name))
        if starred:
            if ui.write_button("Remove from watchlist", ws=ws, key="dlg_star"):
                actions.unstar(ws, entity_id, name)  # a direct write with undo; this dialog redraws with the change
        elif muted:
            st.button("Star", key="dlg_star", disabled=True, help=STAR_MUTED_HELP.format(name=name))
        elif ui.write_button("Star", ws=ws, key="dlg_star"):
            _then(lambda: actions.open_star(ws, entity_id, name))
        if ui.write_button("Request coverage", ws=ws, key="dlg_request", type="primary" if name_only else "secondary",
                           help=f"Ask the source finder to collect {name}'s own news."):
            _then(lambda: ui.open_dialog("request", workspace_id=ws.id, module_id=module_id, company=name))
        if st.button("Close", key="dlg_cancel"):
            ui.close_dialog()
            st.rerun()
    ui.locked_hint(ws)


def _source_dialog(workspace_id: str, module_id: str, source_key: str) -> None:
    """One source in plain words: what it is, what it covers, its health, a link, stats, and the mute switch."""
    ws = _dialog_ws(workspace_id)
    if ws is None:
        return
    insp = _inspect(ws.id, module_id)
    source = find_source(insp, source_key) if insp else None
    if source is None:
        st.info("This source is no longer listed in this coverage area.")
        _close_button()
        return
    label = one_line(source.get("label")) or "This source"
    lane = next((row for row in dicts(insp.get("lanes")) if one_line(row.get("id")) == one_line(source.get("lane"))),
                {})
    covers = " · ".join(p for p in (source_group(source), one_line(lane.get("about"))) if p)
    url = safe_url(source.get("url"))
    rows = [("What it is", one_line(source.get("kind"))), ("What it covers", covers),
            ("Health", health_text(source, ws.timezone)), ("Stories", stats_text(source))]
    st.markdown(
        f'<div class="cov-head"><div class="cov-title">{esc(label)}</div>'
        + (f"<div>{state_chips(source)}</div>" if state_chips(source) else "") + "</div>"
        + '<div class="why-block">'
        + "".join(f'<div class="why-row"><span class="why-label">{esc(k)}</span> {esc(v)}</div>' for k, v in rows if v)
        + (f'<div class="why-row"><span class="why-label">Where</span> {link(url, domain_of(url) or url)}</div>'
           if url else "") + "</div>",
        unsafe_allow_html=True)
    st.caption(labels.STILL_COLLECTED + " You can unmute any time and bring back the last 7 days.")
    with st.container(horizontal=True, key="zx_actions_dlg_source"):
        if ui.write_button("Unmute" if is_muted(source) else "Mute", ws=ws, key="dlg_mute"):
            _then(lambda: mute_source(ws, module_id, source))
        if st.button("Close", key="dlg_cancel"):
            ui.close_dialog()
            st.rerun()
    ui.locked_hint(ws)


ui.register_dialog("company", "Company details", _company_dialog, width="large")
ui.register_dialog("source", "Source details", _source_dialog)
