"""Your companies' big names: the names ZENITH ties to each covered company, and "Suggest a change"
(docs/SPEC-COMPANY-MAP.md 6.1, 6.2 and 6.4). Drawn by brief_view inside What ZENITH looks for, right after the "Your
coverage" section (at the end when the page has none).

    GET  /brief                 (READ_TOKEN)  `companies`: {items: [{ticker, name, summary, columns: {products, units,
                                              customers, read_through}, counts, pending}], pending_total}; each column a
                                              list of {id, name, aliases?, big, kind_label, note, basis, basis_text,
                                              disclosed_label, call_only, unnamed, since_label, tags_stories}, big ones
                                              first; pending: {id, column, action, name, status, status_label, big,
                                              target_id?, target_name?}; big may come as 1 or 0 (the hub stores it so)
    POST /companies/suggestions (OWNER_TOKEN) {ticker, column, action, name?, target_id?, note?, big?, basis_text?,
                                              link?}: the source finder checks it, then it comes back in Tuning under
                                              Needs your OK (409 suggestion_exists; 404 unknown_company, unknown_entry).
                                              A removal sends the name on file with its target_id, so the hub, the card
                                              and the line under the company can say which name goes

One row per company, in ticker order: its name with Suggest a change, then a four-column grid (Products & brands, Units
& acquisitions, Big customers & programs, Read-through) holding only the big names as chips. A big customer's chip
shows its reason on hover; ☎ marks a customer named only on calls or in filings, and a legend says so. "Show all N" is a
lazy expander (key and on_change="rerun"; drawn only while open) listing every name with what it is, a note, how it is
known, since when ("Since ...", "First named ..."; a company bought says its month in what it is), and "Not used to tag
stories" for a name that never tags a story. The sheets' dates inside a sentence are drawn in plain words ("Jun 15,
2026"). Suggestions not built in yet show under their company ("Being checked", "Needs your OK", "Approved: the ZENITH
editor uses it from the next briefing"; a removal "... stops counting it ..."), named by the name sent, else the name on
file of the entry they remove or fix, and a fix that only takes "big" away says so; a live, rejected or withdrawn one
never shows. "Find a name"
searches every name and alias, big or not, keeps the companies that have it and highlights it. Under 900 px each
company's grid is one column (feed.css).

Names are data and real ones trip the jargon guard ("Sentinel Hub", "Rekor Scout"), so every name is drawn with
labels.name_html, which the guard skips, also where a summary, note or reason names one (marked); the words around the
names stay guarded (6.4). An older hub sends no `companies`, and then nothing is drawn.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

import streamlit as st

from . import api, data, labels, ui
from .config import Workspace, load_config
from .fmt import as_int, as_list, dicts, empty_state, esc, one_line

HEADING = "Your companies' big names"
LEDE = ("The names ZENITH ties to each company. Big customers are 5% or more of revenue, or ones the company treats or "
        "expects to be that big.")
# The grid's four columns; Show all and Suggest a change list every customer, big or not.
COLUMNS = {"products": "Products & brands", "units": "Units & acquisitions", "customers": "Big customers & programs",
           "read_through": "Read-through"}
ALL_COLUMNS = {**COLUMNS, "customers": "Customers & programs"}
CALL_MARK = "☎"
CALL_ONLY = "Named only on calls or in filings"
NONE_ON_FILE = "None on file"
ONLY_IN_ALL = "Listed under Show all"
NOT_TAGGING = "Not used to tag stories"
UNNAMED = "Not named by the company"
FIND_KEY = "cm_find"
FIND_LABEL = "Find a name"
FIND_HINT = "Find a name: a product, unit, customer or company"
NO_MATCH = "No company has a name like that. Try part of the name."
EMPTY = "No company names on file yet. The builder is setting them up."
# The hub's status_label, used when it is missing or not plain; an approved removal has words of its own.
STATUS_LABELS = {"queued": "Being checked", "proposed": "Needs your OK",
                 "approved": "Approved: the ZENITH editor uses it from the next briefing",
                 "applied": "Approved: the ZENITH editor uses it from the next briefing"}
REMOVAL_APPROVED = "Approved: the ZENITH editor stops counting it from the next briefing"
PENDING_WORDS = {"add": ("Add", "to"), "remove": ("Remove", "from"), "change": ("Fix", "in")}

DIALOG = "company_suggest"
SUGGEST_LABEL = "Suggest a change"
SUGGEST_SENT = "Sent. The source finder checks it on its next run; then it shows in Tuning under Needs your OK."
ACTIONS = {"add": "Add a name", "remove": "Remove a name", "change": "Fix a name"}
BIG_LABEL = "Big customer (5% or more of revenue, or expected to be)"
REASON_HINT = "For example: 12% of 2025 revenue, or expected to order 10,000 drones"
NOTHING_THERE = "Nothing is on file in this column yet. Choose another column, or add a name."
FIX_EMPTY = "Write the right name, or what is wrong with it."
EXISTS = "You already suggested this. It is waiting for the source finder, or for your OK in Tuning."
GONE_ENTRY = "That name is no longer on file. Close this, reload the page and try again."
_KEY_RE = re.compile(r"[^A-Za-z0-9]+")
# The sheets' dates inside a sentence: a day (2026-06-15) or a month (2026-06; never a year range such as 2026-2028, nor
# 2027-28, whose "28" is no month).
_ISO_DAY_RE = re.compile(r"(?<![\w-])(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?![\w-])")
_ISO_MONTH_RE = re.compile(r"(?<![\w-])(\d{4})-(0[1-9]|1[0-2])(?![\w-])")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# ---------------------------------------------------------------------------------------------- shapes (pure)


def follows(section: Mapping) -> bool:
    """True for the one-pager's "Your coverage" section, which this one follows."""
    return (one_line(section.get("module")).lower() == "coverage"
            or one_line(section.get("heading")).casefold().startswith("your coverage"))


def flag(value: Any) -> bool | None:
    """A yes/no field as the hub may send it: JSON true or false, or 1 or 0 as its database stores them (`big` is an
    INTEGER column); None for anything else."""
    if isinstance(value, bool):
        return value
    return bool(value) if type(value) is int and value in (0, 1) else None


def is_yes(value: Any) -> bool:
    return flag(value) is True


def companies_of(brief: Any) -> list[dict] | None:
    """The companies with a ticker, in ticker order, the first of each ticker only (its widget keys must be unique);
    None when the hub sends no `companies` (an older hub)."""
    block = brief.get("companies") if isinstance(brief, Mapping) else None
    if not isinstance(block, Mapping):
        return None
    rows, seen = [], set()
    for company in dicts(block.get("items")):
        ticker = one_line(company.get("ticker"))
        if ticker and key_of(ticker.upper()) not in seen:
            seen.add(key_of(ticker.upper()))
            rows.append(company)
    return sorted(rows, key=lambda c: one_line(c.get("ticker")).upper())


def entries(company: Mapping, column: str) -> list[dict]:
    """A column's names, big ones first, each group in the sheet's order."""
    columns = company.get("columns") if isinstance(company.get("columns"), Mapping) else {}
    rows = [e for e in dicts(columns.get(column)) if one_line(e.get("name"))]
    return [e for e in rows if is_yes(e.get("big"))] + [e for e in rows if not is_yes(e.get("big"))]


def total(company: Mapping) -> int:
    """How many names the company has on file (the hub's counts; never fewer than the names sent)."""
    counts = company.get("counts") if isinstance(company.get("counts"), Mapping) else {}
    counted = sum(as_int(counts.get(c)) or 0 for c in COLUMNS)
    return max(counted, sum(len(entries(company, c)) for c in COLUMNS))


def entry_key(entry: Mapping) -> str:
    return one_line(entry.get("id")) or one_line(entry.get("name"))


def names_of(entry: Mapping) -> list[str]:
    """The entry's name and its aliases."""
    return [n for n in [one_line(entry.get("name"))] + [one_line(a) for a in as_list(entry.get("aliases"))] if n]


def hits_of(company: Mapping, query: str) -> set[str]:
    """The entries (entry_key) whose name or an alias holds the query, big or not; none for an empty query."""
    if not query:
        return set()
    return {entry_key(e) for c in COLUMNS for e in entries(company, c)
            if any(query in n.casefold() for n in names_of(e))}


def company_matches(company: Mapping, query: str) -> bool:
    """Find a name: the company's own name or ticker, or any of its names or aliases, holds the query."""
    if not query:
        return True
    own = f"{one_line(company.get('ticker'))} {one_line(company.get('name'))}".casefold()
    return query in own or bool(hits_of(company, query))


def status_text(pending: Mapping) -> str:
    """For a suggestion not built in yet (queued, proposed, approved, applied): the hub's plain status_label, else the
    dashboard's words (an approved removal stops counting rather than being used); '' for any other status (live,
    rejected, withdrawn), whatever label it carries."""
    status = one_line(pending.get("status")).lower()
    if status not in STATUS_LABELS:
        return ""
    label = one_line(pending.get("status_label"))
    if label and not ui.looks_technical(label):
        return label
    removal = one_line(pending.get("action")).lower() == "remove" and status in ("approved", "applied")
    return REMOVAL_APPROVED if removal else STATUS_LABELS[status]


def target_name(company: Mapping, pending: Mapping) -> str:
    """The name on file a removal or a fix is about: the hub's target_name, else the name of the company's entry with
    its target_id; '' for an add or when neither is known."""
    if one_line(pending.get("action")).lower() not in ("remove", "change"):
        return ""
    target = one_line(pending.get("target_id"))
    return one_line(pending.get("target_name")) or next(
        (one_line(e.get("name")) for e in entries(company, one_line(pending.get("column")))
         if target and one_line(e.get("id")) == target), "")


def name_pattern(company: Mapping) -> re.Pattern | None:
    """Every name of the company's sheet (its own, each entry's and their other names, 3 characters or more) as one
    whole-word pattern over escaped text, longest first; None when there are none."""
    return pattern_of({one_line(company.get("name"))}
                      | {n for c in COLUMNS for e in entries(company, c) for n in names_of(e)})


def pattern_of(found: Iterable[Any]) -> re.Pattern | None:
    """These names (3 characters or more) as one whole-word pattern over escaped text, longest first; None when there
    are none."""
    names = sorted({one_line(n) for n in found if len(one_line(n)) >= 3}, key=len, reverse=True)
    if not names:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(esc(n)) for n in names) + r")(?!\w)")


def plain_dates(text: Any) -> str:
    """The sheet's dates in a sentence as the rest of the dashboard writes them: 2026-06-15 is "Jun 15, 2026" and
    2026-06 is "Jun 2026"; year ranges (2026-2028, 2027-28) stay as they are. The sheets keep their dates as data."""
    out = _ISO_DAY_RE.sub(lambda m: f"{_MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(1)}", one_line(text))
    return _ISO_MONTH_RE.sub(lambda m: f"{_MONTHS[int(m.group(2)) - 1]} {m.group(1)}", out)


def marked(text: Any, pattern: re.Pattern | None) -> str:
    """A sentence from the sheet (a summary, a note, a reason), its dates in plain words (plain_dates), escaped, with
    the sheet's names in it drawn as names: the sentence stays under the jargon guard, the names in it do not
    ("Sentinel Hub keeps its own brand")."""
    out = esc(plain_dates(text))
    return pattern.sub(lambda m: f'<span class="{labels.NAME_CLASS}">{m.group(0)}</span>', out) if pattern else out


def has_call_only(companies: list[dict]) -> bool:
    return any(is_yes(e.get("call_only")) for c in companies for col in COLUMNS for e in entries(c, col))


def key_of(ticker: str) -> str:
    return _KEY_RE.sub("_", ticker) or "x"


def choices_of(company: Mapping) -> dict[str, list[list]]:
    """Every column's names as [id, name, big] for the dialog (names without an id cannot be removed or fixed)."""
    return {c: [[one_line(e.get("id")), one_line(e.get("name")), is_yes(e.get("big"))]
                for e in entries(company, c) if one_line(e.get("id"))] for c in COLUMNS}


# ---------------------------------------------------------------------------------------------- html (pure)


def call_html(entry: Mapping) -> str:
    return (f'<span class="cm-call" title="{esc(CALL_ONLY)}">{CALL_MARK}</span>'
            if is_yes(entry.get("call_only")) else "")


def reason_of(entry: Mapping) -> str:
    """A big entry's reason (basis_text: big customers only)."""
    return one_line(entry.get("basis_text")) if is_yes(entry.get("big")) else ""


def chip_html(entry: Mapping, hit: bool = False) -> str:
    """One name as a chip: a big customer's reason on hover, ☎ when it is named only on calls or in filings."""
    reason = plain_dates(reason_of(entry))
    css = "cm-chip" + (" cm-hit" if hit else "") + (" cm-reason" if reason else "")
    title = f' title="{esc(reason)}"' if reason else ""
    return f'<span class="{css}"{title}>{labels.name_html(entry.get("name"))}{call_html(entry)}</span>'


def cell_html(company: Mapping, column: str, hits: set[str]) -> str:
    """One column of a company's row: its big names, plus the names Find a name found."""
    rows = entries(company, column)
    shown = [e for e in rows if is_yes(e.get("big")) or entry_key(e) in hits]
    body = "".join(chip_html(e, entry_key(e) in hits) for e in shown) or (
        f'<span class="cm-none">{esc(ONLY_IN_ALL if rows else NONE_ON_FILE)}</span>')
    return f'<div class="cm-cell"><div class="cm-col">{esc(COLUMNS[column])}</div><div class="cm-chips">{body}</div></div>'


def pending_html(company: Mapping) -> str:
    """The company's suggestions not built in yet: "Being checked  Add <name> to Big customers & programs". A removal
    or a fix names the entry on file (target_name), a fix that renames says both names ("Fix <old> in Products &
    brands: call it <new>"), and one whose name is not known says "a name" rather than going missing."""
    lines = []
    for row in dicts(company.get("pending")):
        state = status_text(row)
        if not state:
            continue
        action, column_id = one_line(row.get("action")).lower(), one_line(row.get("column"))
        name, target = one_line(row.get("name")), target_name(company, row)
        first = target or name
        renames = bool(action == "change" and target and name and name.casefold() != target.casefold())
        verb, joint = PENDING_WORDS.get(action, ("Change", "in"))
        column = ALL_COLUMNS.get(column_id, "")
        big = ""
        if column_id == "customers" and is_yes(row.get("big")):
            big = " as a big customer"
        elif column_id == "customers" and action == "change" and flag(row.get("big")) is False:
            big = " as no longer a big customer"  # a fix that only takes "big" away still says what it changes
        lines.append(f'<div class="cm-pending"><span class="cm-pending-state">{esc(state)}</span>'
                     f'<span>{esc(verb)} ' + (labels.name_html(first) if first else esc("a name"))
                     + (f" {esc(joint)} {esc(column)}" if column else "")
                     + (f": call it {labels.name_html(name)}" if renames else "") + f"{esc(big)}</span></div>")
    return f'<div class="cm-pendings">{"".join(lines)}</div>' if lines else ""


def row_html(company: Mapping, hits: set[str]) -> str:
    return (f'<div class="cm-grid">{"".join(cell_html(company, c, hits) for c in COLUMNS)}</div>'
            + pending_html(company))


def head_html(company: Mapping) -> str:
    ticker, summary = one_line(company.get("ticker")).upper(), one_line(company.get("summary"))
    return (f'<div class="cm-head"><div class="cm-title"><span class="cm-ticker">{esc(ticker)}</span>'
            f'{labels.name_html(company.get("name") or ticker)}</div>'
            + (f'<div class="cm-summary">{marked(summary, name_pattern(company))}</div>' if summary else "") + "</div>")


def entry_html(entry: Mapping, pattern: re.Pattern | None = None) -> str:
    """One name in Show all: the name (☎), a big customer's reason, other names, the note, then what it is, how it is
    known, since when and whether it tags stories. pattern (name_pattern): the sheet's names in the reason and the
    note are drawn as names."""
    reason = reason_of(entry)
    aliases = [a for a in names_of(entry)[1:] if a.casefold() != one_line(entry.get("name")).casefold()]
    meta = [one_line(entry.get(k)) for k in ("kind_label", "disclosed_label", "since_label")]
    meta += [UNNAMED] if is_yes(entry.get("unnamed")) else []
    meta += [CALL_ONLY] if is_yes(entry.get("call_only")) else []
    meta += [NOT_TAGGING] if flag(entry.get("tags_stories")) is False else []
    note = one_line(entry.get("note"))
    return (f'<div class="cm-entry{" cm-big" if is_yes(entry.get("big")) else ""}">'
            f'<div class="cm-entry-name">{labels.name_html(entry.get("name"))}{call_html(entry)}</div>'
            + (f'<div class="cm-entry-reason">Big customer: {marked(reason, pattern)}</div>' if reason else "")
            + (f'<div class="cm-entry-aka">Also: {", ".join(labels.name_html(a) for a in aliases)}</div>'
               if aliases else "")
            + (f'<div class="cm-entry-note">{marked(note, pattern)}</div>' if note else "")
            + (f'<div class="cm-entry-meta">{esc(" · ".join(m for m in meta if m))}</div>' if any(meta) else "")
            + "</div>")


def all_html(company: Mapping) -> str:
    """Show all: every name, column by column."""
    cols, pattern = [], name_pattern(company)
    for column, title in ALL_COLUMNS.items():
        rows = entries(company, column)
        body = "".join(entry_html(e, pattern) for e in rows) or f'<div class="cm-none">{esc(NONE_ON_FILE)}</div>'
        cols.append(f'<div class="cm-all-col"><div class="cm-col">{esc(title)} · {len(rows)}</div>{body}</div>')
    return f'<div class="cm-all">{"".join(cols)}</div>'


# ---------------------------------------------------------------------------------------------- the section


def render(ws: Workspace, brief: Mapping) -> None:
    """The heading and its line, Find a name, the ☎ legend, then one row per company."""
    companies = companies_of(brief)
    if companies is None:
        return
    st.markdown(f'<div class="rules-section">{esc(HEADING)}</div><div class="cm-lede">{esc(LEDE)}</div>',
                unsafe_allow_html=True)
    if not companies:
        st.markdown(empty_state(EMPTY), unsafe_allow_html=True)
        return
    query = st.text_input(FIND_LABEL, key=FIND_KEY, placeholder=FIND_HINT, label_visibility="collapsed",
                          icon=":material/search:")
    if has_call_only(companies):
        st.markdown(f'<div class="cm-legend"><span class="cm-call">{CALL_MARK}</span> {esc(CALL_ONLY)}</div>',
                    unsafe_allow_html=True)
    term = one_line(query).casefold()
    shown = [c for c in companies if company_matches(c, term)]
    if not shown:
        st.markdown(empty_state(NO_MATCH), unsafe_allow_html=True)
    for company in shown:
        render_company(ws, company, hits_of(company, term))


def render_company(ws: Workspace, company: Mapping, hits: set[str]) -> None:
    ticker = one_line(company.get("ticker")).upper()
    slug = key_of(ticker)
    with st.container(key=f"zx_cmrow_{slug}"):
        with st.container(horizontal=True, key=f"zx_cmhead_{slug}", vertical_alignment="center", gap="small"):
            st.markdown(head_html(company), unsafe_allow_html=True)
            if ui.write_button(SUGGEST_LABEL, ws=ws, key=f"cm_suggest_{slug}", type="tertiary"):
                ui.open_dialog(DIALOG, workspace_id=ws.id, ticker=ticker, company=one_line(company.get("name")),
                               choices=choices_of(company))
        st.markdown(row_html(company, hits), unsafe_allow_html=True)
        box = st.expander(f"Show all {total(company)}", key=f"cm_all_{slug}", on_change="rerun")
        with box:
            if box.open:
                st.markdown(all_html(company), unsafe_allow_html=True)


# ---------------------------------------------------------------------------------------------- the dialog


def suggest_dialog(workspace_id: str, ticker: str = "", company: str = "", choices: Mapping | None = None) -> None:
    """Add a name to a column, or remove or fix one on file (a removal sends its name on file too); for customers,
    whether it is big and why; a link."""
    from . import brief_view  # brief_view draws this section, so it is imported here, not at the top

    ws = load_config().workspace(one_line(workspace_id))
    if ws is None:
        st.error("This workspace is no longer configured. Close this and reload the page.")
        return
    on_file = choices if isinstance(choices, Mapping) else {}
    st.markdown(f'<div class="cm-dlg-head">{labels.name_html(company or ticker)}'
                f'<span class="cm-ticker">{esc(ticker)}</span></div>', unsafe_allow_html=True)
    action = st.radio("What do you want to do?", list(ACTIONS), key="dlg_action", horizontal=True,
                      format_func=lambda a: ACTIONS[a]) or "add"
    column = st.selectbox("Which column?", list(ALL_COLUMNS), key="dlg_column",
                          format_func=lambda c: ALL_COLUMNS[c]) or "products"
    rows = [r for r in as_list(on_file.get(column)) if isinstance(r, (list, tuple)) and len(r) >= 2 and one_line(r[0])]
    names = {one_line(r[0]): one_line(r[1]) for r in rows}
    bigs = {one_line(r[0]): len(r) > 2 and r[2] is True for r in rows}
    target, name = None, ""
    if action == "add":
        name = st.text_input("The name", key="dlg_name", max_chars=api.COMPANY_NAME_MAX)
    elif not names:
        st.info(NOTHING_THERE)
    else:
        target = st.selectbox("Which name?", list(names), key="dlg_target", format_func=lambda i: names.get(i, ""))
        if action == "remove":
            name = names.get(target or "", "")  # the name on file, so every place can say which name goes
        else:
            name = st.text_input("The right name (leave it empty to keep the name)", key="dlg_name",
                                 max_chars=api.COMPANY_NAME_MAX)
    note = st.text_input("Why it no longer counts (one line)" if action == "remove" else "What it is (one line)",
                         key="dlg_note", max_chars=api.COMPANY_NOTE_MAX)
    big, reason = None, ""
    if column == "customers" and action != "remove" and (action == "add" or target):
        was_big = bigs.get(target or "", False)
        big = st.checkbox(BIG_LABEL, value=was_big, key=f"dlg_big_{target or 'new'}")
        if big:
            reason = st.text_input("Why it is that big", key="dlg_reason", max_chars=api.COMPANY_REASON_MAX,
                                   placeholder=REASON_HINT)
        if action == "change" and big == was_big and not (big and one_line(reason)):
            big = None  # unchanged: a fix says only what changes
    link = st.text_input("Where you saw it (optional)", key="dlg_link", placeholder="https://")
    with st.container(horizontal=True):
        send = ui.write_button("Send", ws=ws, key="dlg_save", type="primary")
        cancel = st.button("Cancel", key="dlg_cancel")
    if cancel:
        ui.close_dialog()
        st.rerun()
    if not send:
        return
    if action != "add" and not target:
        st.info(NOTHING_THERE)
        return
    if action == "change" and not one_line(name) and not one_line(note) and big is None:
        st.info(FIX_EMPTY)
        return
    result, handled = brief_view.write_or_handle(
        ws, lambda token: api.suggest_company_change(ws, token, ticker=ticker, column=column, action=action,
                                                     name=name, target_id=target, note=note, big=big,
                                                     basis_text=reason, link=link),
        toast=SUGGEST_SENT, codes=("suggestion_exists", "unknown_entry"))
    if handled is not None:
        if handled.code == "unknown_entry":
            data.clear_reads()
        st.info(EXISTS if handled.code == "suggestion_exists" else GONE_ENTRY)
        return
    if result is not None:
        ui.close_dialog()
        st.rerun()


ui.register_dialog(DIALOG, "Suggest a change", suggest_dialog, width="medium")
