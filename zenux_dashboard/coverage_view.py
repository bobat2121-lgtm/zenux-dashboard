"""Coverage: what ZENITH looks for (with the sign-off), how ZENITH covers each coverage area, in four steps, and who and
what it watches (GET /brief, GET /modules, GET /modules/<id>/inspect, with GET /settings and GET /status for the
editor's bar and next run).

Built to be read cold by a new analyst (owner, 2026-10-04: "simple and efficient ... intuitively process how this
engine runs"). At the top, "What ZENITH looks for" (brief_view.render_brief, docs/SPEC-SIMPLIFY.md 2.4): one expander
titled with its sign-off state, open while the workspace is staging (then a banner says so), with Sign off and Suggest
a change. Then pick a coverage area (a module: `cv_area`, mirrored as `module` in the page's link), then:

- the area's title and one-sentence description;
- How it works: four steps with this area's live numbers. Watch (companies and sources, and the kinds of sources),
  Collect (stories this week), Score (the ZENITH editor scores every story 0 to 100; its next run), Brief (what made
  your briefings this week, and the bar and size of a briefing from "How much");
- one line on source health ("All 151 sources are working", or which are not responding, with Show them), and, while
  the area has open source repairs (GET /modules `repairs_open`), "ZENITH is fixing 2 sources.";
- What ZENITH watches: a search box, Companies or Sources, a filter (watchlist, muted, by name only; not responding,
  turned off, muted) and one sortable table. Clicking a row opens its details (the `company` or `source` dialog,
  registered here), where Star, Mute and Request coverage live; Mute, unmute and star go through the card-action
  dialogs of `actions` (preview first, a toast, undo). A dialog cannot open another one, so these dialogs close
  themselves before opening the next.

Every mute surface says it: muted sources and companies are still collected, kept out of the briefing. Below,
`radar_view.render_requests(ws, module_id)` draws the coverage requests. The Briefing's staging links (the status line,
the empty Briefing) open this page.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from . import actions, api, brief_view, data, labels, links, radar_view, status, ui
from .config import Workspace, load_config
from .fmt import (MIN_TIME, as_int, as_list, chip, dicts, domain_of, empty_state, esc, fmt_clock, fmt_date, join_and,
                  label_of, link, md_label, one_line, parse_time, pick, plural, safe_url)

AREA_KEY = "cv_area"
SEARCH_KEY = "cv_search"
LIST_KEY = "cv_list"
FILTER_KEYS = {"companies": "cv_filter_companies", "sources": "cv_filter_sources"}
TABLE_N_KEY = "cv_table_n"  # bumped after a row opens its details, so the table's selection starts fresh
LISTS = {"companies": "Companies", "sources": "Sources"}
FILTERS = {
    "companies": {"all": "All", "starred": "On your watchlist", "muted": "Muted", "name_only": "By name only"},
    "sources": {"all": "All", "failing": "Not responding", "off": "Turned off", "muted": "Muted"},
}
PROGRAM_ROLE = "program"
PROGRAM_GROUP = "Programs and agencies"
OTHER_COMPANIES = "Other companies"
OTHER_SOURCES = "Other sources"
CATALOG_MISSING = "catalog_missing"
UNKNOWN_MODULE = "unknown_module"
STAR_MUTED_HELP = "{name} is muted. Unmute it first."
MUTE_STARRED_HELP = "{name} is on your watchlist. Remove the star first."
ASK_JUMP = "Ask for a source, a company or a topic ↓"
TABLE_HINT = ("Click a row for its details: star a company, mute a source or company, or ask for more coverage. "
              "Muted: " + labels.STILL_COLLECTED)
COLLECT_TEXT = "Clearly off-topic items are dropped as they arrive. Everything else waits for the editor."
LEFT_OUT_TEXT = "The rest show under each briefing, in Left out of this briefing."
# The name column of each table stands out (owner, 2026-10-04): pinned at the left, bold, in the link green.
NAME_COLUMNS = {"companies": "Company", "sources": "Source"}
NAME_STYLE = {"color": "#6EF2B6", "font-weight": "700"}
FOLLOWS = {"own_feed": "Own news", "sec_filings": "SEC filings", "federal_contracts": "Contracts",
           "news_search": "News search"}


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


def is_off(source: Mapping) -> bool:
    return source.get("enabled") is False or state_of(source) == "off"


def listed(entity: Mapping) -> str:
    """'Public', 'Private' or 'Program or agency'."""
    if one_line(entity.get("role")).lower() == PROGRAM_ROLE:
        return "Program or agency"
    return "Public" if one_line(entity.get("ownership")).lower() == "public" else "Private"


def follows_text(entity: Mapping) -> str:
    """How ZENITH follows a company: 'Own news, SEC filings', or 'By name only' when nothing reads it directly."""
    flags = [flag for flag, _, _ in coverage_flags(entity)]
    parts = [FOLLOWS[f] for f in flags if f in FOLLOWS]
    return ", ".join(parts) if parts else ("By name only" if "name_only" in flags else "")


def you_text(row: Mapping) -> str:
    return "★ Watchlist" if is_starred(row) else "Muted" if is_muted(row) else ""


def entity_text(entity: Mapping) -> str:
    return " ".join([one_line(entity.get("name")), tickers_of(entity), entity_group(entity),
                     " ".join(one_line(a) for a in as_list(entity.get("aliases")))]).casefold()


def source_text(source: Mapping) -> str:
    return " ".join([one_line(source.get("label")), one_line(source.get("kind")), source_group(source)]).casefold()


def terms_of(query: Any) -> list[str]:
    return [t for t in one_line(query).casefold().split(" ") if t]


def matches(row: Mapping, kind: str, terms: list[str], filter_: str) -> bool:
    """Search (every term in the row's name, tickers, group or kind) and the list's filter."""
    text = entity_text(row) if kind == "companies" else source_text(row)
    if any(term not in text for term in terms):
        return False
    if filter_ == "starred":
        return is_starred(row)
    if filter_ == "muted":
        return is_muted(row)
    if filter_ == "name_only":
        return bool(pick(row, "coverage.name_only"))
    if filter_ == "failing":
        return state_of(row) == "failing"
    if filter_ == "off":
        return is_off(row)
    return True


def stats_of(row: Mapping) -> Mapping:
    return row.get("stats") if isinstance(row.get("stats"), Mapping) else {}


def company_rows(insp: Mapping, terms: list[str], filter_: str) -> tuple[list[str], list[dict]]:
    """(entity ids, table rows) of the companies that match, in the hub's order."""
    ids, rows = [], []
    for entity in dicts(insp.get("entities")):
        if not one_line(entity.get("id")) or not matches(entity, "companies", terms, filter_):
            continue
        stats = stats_of(entity)
        ids.append(one_line(entity.get("id")))
        rows.append({"Company": one_line(entity.get("name")) or "Unnamed company", "Group": entity_group(entity),
                     "Listed": listed(entity), "Ticker": tickers_of(entity), "How ZENITH follows it": follows_text(entity),
                     "This week": as_int(stats.get("items_7d")) or 0,
                     "In briefings, 30 days": as_int(stats.get("briefing_30d")) or 0, "You": you_text(entity)})
    return ids, rows


def source_rows(insp: Mapping, terms: list[str], filter_: str, tz: str) -> tuple[list[str], list[dict]]:
    """(source keys, table rows) of the sources that match: the area's own and the companies' own feeds."""
    ids, rows = [], []
    for source in dicts(insp.get("sources")):
        if not one_line(source.get("key")) or not matches(source, "sources", terms, filter_):
            continue
        stats = stats_of(source)
        ids.append(one_line(source.get("key")))
        rows.append({"Source": one_line(source.get("label")) or "Unnamed source", "What it is": one_line(source.get("kind")),
                     "Group": source_group(source), "Status": health_text(source, tz),
                     "This week": as_int(stats.get("items_7d")) or 0,
                     "In briefings, 30 days": as_int(stats.get("briefing_30d")) or 0,
                     "You": "Muted" if is_muted(source) else ""})
    return ids, rows


def counts_of(insp: Mapping, card: Mapping | None) -> dict[str, int]:
    """companies, sources on and off, stories this week and in briefings (this week, else 30 days)."""
    counts = card.get("counts") if isinstance((card or {}).get("counts"), Mapping) else {}
    entities, sources = dicts(insp.get("entities")), dicts(insp.get("sources"))
    totals = insp.get("totals") if isinstance(insp.get("totals"), Mapping) else {}
    on = as_int(counts.get("sources_enabled"))
    off = as_int(counts.get("sources_off"))
    return {
        "companies": as_int(counts.get("entities")) if as_int(counts.get("entities")) is not None else len(entities),
        "on": on if on is not None else sum(1 for s in sources if not is_off(s)),
        "off": off if off is not None else sum(1 for s in sources if is_off(s)),
        "week": as_int(totals.get("items_7d")) or 0,
        "briefing_7d": as_int(totals.get("briefing_7d")) if as_int(totals.get("briefing_7d")) is not None else -1,
        "briefing_30d": as_int(totals.get("briefing_30d")) or 0,
    }


def removed_week(insp: Mapping) -> str:
    """'Includes 9 from a removed source that ZENITH no longer collects.' when this week's total counts stories from
    sources no longer in the area's list (the hub's orphans: retired, or renamed in the module); '' otherwise. The
    number is the week's total minus what the listed sources account for."""
    orphans = dicts(insp.get("orphans"))
    if not orphans:
        return ""
    totals = insp.get("totals") if isinstance(insp.get("totals"), Mapping) else {}
    listed = sum(as_int((s.get("stats") if isinstance(s.get("stats"), Mapping) else {}).get("items_7d")) or 0
                 for s in dicts(insp.get("sources")))
    gone = (as_int(totals.get("items_7d")) or 0) - listed
    if gone <= 0:
        return ""
    if all(o.get("retired") is True for o in orphans):
        what = "a removed source" if len(orphans) == 1 else "removed sources"
        return f"Includes {number(gone)} from {what} that ZENITH no longer collects."
    return f"Includes {number(gone)} from sources no longer listed in this area."


def lane_words(insp: Mapping) -> str:
    """'Company news and filings, trade press and news search': the kinds of sources, by size, in plain words."""
    lanes = sorted(dicts(insp.get("lanes")), key=lambda lane: -(as_int(lane.get("source_count")) or 0))
    words = [one_line(lane.get("label")) for lane in lanes if one_line(lane.get("label"))]
    words = [w if n == 0 else w[:1].lower() + w[1:] for n, w in enumerate(words)]
    if len(words) > 2:  # the labels hold "and" themselves ("Power and grid"): a serial comma keeps them apart
        return ", ".join(words[:-1]) + ", and " + words[-1]
    return join_and(words)


def number(n: int) -> str:
    return f"{n:,}"


def flow_steps(insp: Mapping, card: Mapping | None, bar: int | None, cap: int | None, how_much: str,
               next_text: str) -> list[tuple[str, str, str]]:
    """The four steps (title, the big line, the explanation) with this area's numbers."""
    c = counts_of(insp, card)
    kinds = lane_words(insp)
    watch = (f"{kinds}, checked around the clock." if kinds else "Checked around the clock.")
    if c["briefing_7d"] >= 0:
        brief_big = f"{number(c['briefing_7d'])} in your briefings this week"
    else:
        brief_big = f"{number(c['briefing_30d'])} in your briefings in 30 days"
    if bar is not None:
        brief = (f"Stories scoring {bar} or more make your briefing"
                 + (f", up to {cap} at a time" if cap else "") + (f" (How much: {how_much})" if how_much else "")
                 + ". " + LEFT_OUT_TEXT)
    else:
        brief = "Stories that clear your bar make your briefing. " + LEFT_OUT_TEXT
    score = ("It reads every new story, drops repeats and old news, checks the facts and writes up the ones that "
             "matter." + (f" Next run: {next_text}." if next_text else ""))
    return [
        ("Watch", f"{plural(c['companies'], 'company', 'companies')} · "
                  f"{plural(c['on'] + c['off'], 'source')}" + (f" ({c['on']} on)" if c["off"] else ""), watch),
        ("Collect", f"{number(c['week'])} stories this week", " ".join(p for p in (COLLECT_TEXT, removed_week(insp)) if p)),
        ("Score", "The ZENITH editor scores each one 0 to 100", score),
        ("Brief", brief_big, brief),
    ]


def flow_html(steps: list[tuple[str, str, str]]) -> str:
    cells = []
    for n, (title, big, text) in enumerate(steps, start=1):
        if n > 1:
            cells.append('<div class="cov-arrow" aria-hidden="true">→</div>')
        cells.append(f'<div class="cov-step"><div class="cov-step-k"><span class="cov-step-n">{n}</span>'
                     f'{esc(title)}</div><div class="cov-step-big">{esc(big)}</div>'
                     f'<div class="cov-step-d">{esc(text)}</div></div>')
    return f'<div class="cov-flow" role="list" aria-label="How ZENITH works">{"".join(cells)}</div>'


def fixing_text(card: Mapping | None) -> str:
    """'ZENITH is fixing 1 source.' or 'ZENITH is fixing 3 sources.' while the area has open source repairs (GET /modules
    `repairs_open`: proposed, approved or applied, not yet recovered); '' otherwise and from an older hub."""
    n = as_int(card.get("repairs_open")) if isinstance(card, Mapping) else None
    return f"ZENITH is fixing {plural(n, 'source')}." if n is not None and n > 0 else ""


def health_line(insp: Mapping, card: Mapping | None) -> tuple[str, str, list[str]]:
    """(css, sentence, names of the failing sources) for the source-health line, with fixing_text after the sources
    not responding."""
    sources = dicts(insp.get("sources"))
    failing = [one_line(s.get("label")) or "A source" for s in sources if state_of(s) == "failing" and not is_off(s)]
    c = counts_of(insp, card)
    off = (f" {plural(c['off'], 'source is', 'sources are')} turned off on purpose: sites that block automated "
           "reading or no longer work." if c["off"] else "")
    fixing = fixing_text(card)
    fixing = f" {fixing}" if fixing else ""
    if failing:
        names = join_and(failing[:3]) + (f" and {len(failing) - 3} more" if len(failing) > 3 else "")
        verb = "isn't" if len(failing) == 1 else "aren't"
        return ("warn", f"{plural(len(failing), 'source')} {verb} responding right now: {names}. ZENITH keeps trying; "
                        f"everything else is collected as usual.{fixing}{off}", failing)
    return "ok", f"All {plural(c['on'], 'source')} on are working.{fixing}{off}", []


def stats_text(row: Mapping) -> str:
    stats = stats_of(row)
    return (f"{as_int(stats.get('items_7d')) or 0} this week{week_briefings(stats)} · "
            f"{as_int(stats.get('briefing_30d')) or 0} in briefings (30 days)")


def week_briefings(stats: Mapping, words: str = " in briefings") -> str:
    """' (2 in briefings)': how many of this week's stories made a briefing (`briefing_7d`, gap 12); '' when the hub
    does not say."""
    n = as_int(stats.get("briefing_7d")) if isinstance(stats, Mapping) else None
    return f" ({n}{words})" if n is not None else ""


def health_text(source: Mapping, tz: str) -> str:
    """'Working', 'Not responding since Oct 1', 'Turned off: <why>' ..."""
    state = state_of(source)
    text = labels.SOURCE_STATE_LABELS.get(state) or one_line(pick(source, "health.label")) or "Not run yet"
    if state == "failing" and pick(source, "health.last_ok_at"):
        text += f" since {fmt_date(pick(source, 'health.last_ok_at'), tz)}"
    if state == "off" and one_line(source.get("off_reason")):
        text += f": {one_line(source.get('off_reason'))}"
    return text


def state_chips(row: Mapping) -> str:
    return ((chip("Muted", "chip-state chip-muted") if is_muted(row) else "")
            + (chip("On your watchlist", "chip-state chip-starred") if is_starred(row) else ""))


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


def mute_source(ws: Workspace, module_id: str, source: Mapping) -> None:
    """Open the mute dialog (preview first) or the unmute dialog of `actions` for one of the area's sources."""
    label = one_line(source.get("label")) or one_line(source.get("key"))
    if is_muted(source):
        actions.open_unmute(ws, mute_row(source["muted"], source_mute_fallback(module_id, source)))
    else:
        actions.open_mute(ws, kind="source", ref=one_line(source.get("key")), label=label, module=module_id)


# ---------------------------------------------------------------------------------------------- the lists


def table_key(kind: str) -> str:
    return f"cv_table_{kind}_{as_int(st.session_state.get(TABLE_N_KEY)) or 0}"


def open_details(workspace_id: str, module_id: str, kind: str, ids: list[str], key: str) -> None:
    """A table row was clicked (the table's on_select callback): open its details, and start the next table with no
    selection (a new key), so the same row can be clicked again after the dialog closes."""
    state = st.session_state.get(key)
    selection = state.get("selection") if isinstance(state, Mapping) else getattr(state, "selection", None)
    rows = selection.get("rows") if isinstance(selection, Mapping) else getattr(selection, "rows", None)
    index = as_int(rows[0]) if rows else None
    if index is None or not 0 <= index < len(ids):
        return
    if kind == "companies":
        ui.open_dialog("company", workspace_id=workspace_id, module_id=module_id, entity_id=ids[index])
    else:
        ui.open_dialog("source", workspace_id=workspace_id, module_id=module_id, source_key=ids[index])
    st.session_state[TABLE_N_KEY] = (as_int(st.session_state.get(TABLE_N_KEY)) or 0) + 1


def show_failing() -> None:
    """Show them: the Sources list, filtered to the sources not responding."""
    st.session_state[LIST_KEY] = "sources"
    st.session_state[FILTER_KEYS["sources"]] = "failing"


def filter_label(kind: str, code: str, insp: Mapping) -> str:
    """'On your watchlist · 1': each filter with how many rows it keeps (before the search)."""
    if code == "all":
        return FILTERS[kind][code]
    rows = dicts(insp.get("entities" if kind == "companies" else "sources"))
    return f"{FILTERS[kind][code]} · {sum(1 for r in rows if matches(r, kind, [], code))}"


def styled_table(rows: list[dict], kind: str) -> Any:
    """The table's rows with the name column highlighted (a pandas Styler; st.dataframe draws its colour and weight)."""
    frame = pd.DataFrame(rows)
    name = NAME_COLUMNS[kind]
    return frame.style.set_properties(subset=[name], **NAME_STYLE) if name in frame.columns else frame


def render_lists(ws: Workspace, module_id: str, insp: Mapping) -> None:
    """What ZENITH watches: the search box, Companies or Sources, its filter, and one table whose rows open details."""
    ui.section("What ZENITH watches")
    entities, sources = dicts(insp.get("entities")), dicts(insp.get("sources"))
    if st.session_state.get(LIST_KEY) not in LISTS:
        st.session_state[LIST_KEY] = "companies"
    pick_col, search_col = st.columns([2, 3], vertical_alignment="center")
    with pick_col:
        counts = {"companies": len(entities), "sources": len(sources)}
        kind = st.segmented_control("Show", list(LISTS), key=LIST_KEY, required=True, label_visibility="collapsed",
                                    format_func=lambda k: f"{LISTS[k]} · {counts[k]}") or "companies"
    with search_col:
        query = st.text_input("Search companies and sources", key=SEARCH_KEY, label_visibility="collapsed",
                              placeholder="Search by name, ticker, group or kind of source",
                              icon=":material/search:")
    filter_key = FILTER_KEYS[kind]
    if st.session_state.get(filter_key) not in FILTERS[kind]:
        st.session_state[filter_key] = "all"
    filter_ = st.pills("Filter", list(FILTERS[kind]), key=filter_key, selection_mode="single", label_visibility="collapsed",
                       format_func=lambda code: filter_label(kind, code, insp)) or "all"
    terms = terms_of(query)
    if kind == "companies":
        ids, rows = company_rows(insp, terms, filter_)
        config = {"This week": st.column_config.NumberColumn(help="Stories that named it in the last 7 days"),
                  "In briefings, 30 days": st.column_config.NumberColumn(help="Of those, how many made your briefings")}
    else:
        ids, rows = source_rows(insp, terms, filter_, ws.timezone)
        config = {"Status": st.column_config.TextColumn(width="medium"),
                  "This week": st.column_config.NumberColumn(help="Stories it brought in the last 7 days"),
                  "In briefings, 30 days": st.column_config.NumberColumn(help="Of those, how many made your briefings")}
    if not rows:
        st.markdown(empty_state("Nothing matches. Try another word or filter, or ask for coverage below."),
                    unsafe_allow_html=True)
        return
    key = table_key(kind)
    config[NAME_COLUMNS[kind]] = st.column_config.TextColumn(pinned=True, width="medium")
    st.dataframe(styled_table(rows, kind), key=key, hide_index=True, width="stretch",
                 height=min(38 + 35 * len(rows), 460),
                 column_config=config, selection_mode="single-row",
                 on_select=partial(open_details, ws.id, module_id, kind, ids, key))
    noun = ("company", "companies") if kind == "companies" else ("source", "sources")
    st.caption(f"{plural(len(rows), *noun)} shown. {TABLE_HINT}")


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


def render_head(insp: Mapping, card: Mapping | None, name: str) -> None:
    mod = insp.get("module") if isinstance(insp.get("module"), Mapping) else {}
    title = one_line(mod.get("title")) or one_line((card or {}).get("title")) or name
    description = one_line(mod.get("description"))  # plain: the hub drops the manifest's file references (gap 33)
    st.markdown(f'<div class="cov-head"><div class="cov-title">{esc(title)}</div>'
                + (f'<div class="cov-desc">{esc(description)}</div>' if description else "") + "</div>",
                unsafe_allow_html=True)


def volume_of(ws: Workspace) -> tuple[int | None, int | None, str]:
    """(bar, briefing size, the How much label) from GET /settings; Nones when it cannot be read."""
    try:
        volume = pick(data.settings(ws.id), "volume")
    except api.ApiError:
        return None, None, ""
    volume = volume if isinstance(volume, Mapping) else {}
    return as_int(volume.get("bar")), as_int(volume.get("cap")), one_line(volume.get("label"))


def next_run_text(ws: Workspace) -> str:
    """'4:30 PM ET' (the editor's next scheduled run), or '' when it is not known."""
    try:
        when = status.summary(ws).get("next_at")
    except Exception:  # the status line already said what it could; this page still renders
        return ""
    return fmt_clock(when, ws.timezone) if when is not None and parse_time(when) != MIN_TIME else ""


def render_flow(ws: Workspace, insp: Mapping, card: Mapping | None) -> None:
    """How it works: the four steps with this area's numbers, then the source-health line."""
    ui.section("How ZENITH covers this area")
    bar, cap, how_much = volume_of(ws)
    st.markdown(flow_html(flow_steps(insp, card, bar, cap, how_much, next_run_text(ws))), unsafe_allow_html=True)
    css, sentence, failing = health_line(insp, card)
    with st.container(horizontal=True, key="zx_cov_health", vertical_alignment="center", gap="small"):
        st.markdown(f'<div class="cov-health {css}">{esc(sentence)}</div>', unsafe_allow_html=True)
        if failing:
            st.button("Show them", key="cv_show_failing", type="tertiary", icon=":material/arrow_downward:",
                      on_click=show_failing)


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
    render_flow(ws, insp, card)
    render_lists(ws, module_id, insp)


def render(ws: Workspace) -> None:
    """Coverage: what ZENITH looks for (and the sign-off), then pick a coverage area, how ZENITH covers it, what it
    watches, then coverage requests."""
    brief_view.render_brief(ws)
    # The request form sits at the bottom; a jump to it at the top (WF5 AW-13).
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
    Star or Remove from watchlist, and Request coverage (primary when ZENITH only catches it by name)."""
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
        lines.append(("Name only", f"ZENITH only catches {name} when another source names it."))
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
