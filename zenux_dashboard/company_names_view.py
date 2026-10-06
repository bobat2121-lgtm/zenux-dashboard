"""Suggested company names after the source finder's check (docs/SPEC-COMPANY-MAP.md 6.3): what their card under
Tuning's Needs your OK says (tuning_view draws the card and its buttons), and the Control room's "Company names to build
in" list, right after the source repairs.

    GET  /preferences                       (READ_TOKEN)   `company_suggestions`: the proposed ones, newest first, each
                                                           {id, ticker, company_name?, column, action, target_id?,
                                                           target_name?, name, aliases, note, kind, big, basis,
                                                           basis_text, link, analyst_note, status, verdict, proposed_at,
                                                           use?, decision_note?, ...}; verdict {result: confirmed |
                                                           not_confirmed | unclear, evidence: [{url, title, date,
                                                           quote}], proposal: {name, aliases, kind, note, big, basis,
                                                           basis_text, entity_id}, summary}, maybe as JSON text; big may
                                                           be 1 or 0 (an INTEGER column)
    POST /companies/suggestions/<id>/approve {use}  (OWNER_TOKEN)  use: "proposal" when the card shows the source
                                                           finder's version, else "as_typed" (the analyst's words)
    POST /companies/suggestions/<id>/reject  {}     (OWNER_TOKEN)  409 suggestion_closed when it was decided or
                                                           withdrawn meanwhile; no route reverses either, so no Undo
    GET  /companies/suggestions?status=approved | applied  (READ_TOKEN)  the Control room's list, every workspace
    GET  /brief `companies`                 (READ_TOKEN)   cached; read only when a suggestion lacks the company's name
                                                           or the name of the entry it removes or fixes (named)

The card: "Suggested name for <Company>", what it changes ("Add Army Drone Dominance program to Customers & programs"),
the analyst's own words when the source finder cleaned them up, the note, a big customer's reason and the source
finder's result ("Confirmed: <title>, <date>" with the link, or "Could not confirm"); Details holds what the source
finder found, its sources and what the analyst sent. The values shown are the ones the approval writes: the source
finder's proposal over what was typed (tools/lib/company-apply.mjs effectiveValues). A hub that leaves out the
company's name or the name of the entry a removal or fix is about gets them from the names on file (GET /brief), so a
card never says a bare ticker or "a name" when the dashboard knows better. Names are data (6.4): every name is drawn
with labels.name_html, also inside a sentence (company_map_view.marked); the words around them stay guarded. The source
finder's own sentences (its summary, and its note or reason when the card shows them) appear on Tuning only when they
pass the jargon guard (ui.looks_technical); the Control room shows them as written.

The Control room lists, per workspace, the approved suggestions with `node tools/zenux.js company apply <ws> <id>`
each, then the deploy, then the applied ones waiting for that deploy (the hub marks them live once the deployed bundle
carries them). A failed read is one plain line, never a crash.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Callable, Mapping

import streamlit as st

from . import api, company_map_view, data, labels, ui
from .config import Config, Workspace
from .fmt import (MIN_TIME, as_list, clip, dicts, domain_of, esc, fmt_date, fmt_short, link, md_label, one_line,
                  parse_time, pick, pill, plural, safe_url, section_label, unique_by_id, zone)

COLUMNS = company_map_view.ALL_COLUMNS          # {column: its heading}; customers as "Customers & programs"
CHANGE_WORDS = company_map_view.PENDING_WORDS   # {action: (verb, joint)}: "Add ... to", "Remove ... from", "Fix ... in"
ACTION_KINDS = company_map_view.ACTIONS         # {action: "Add a name" | "Remove a name" | "Fix a name"}
WAITING = ("proposed",)
TO_BUILD = ("approved", "applied")
STAMPS = {"proposed": "proposed_at", "approved": "decided_at", "applied": "applied_at"}

# ---------------------------------------------------------------------------------------------- copy

HEAD = "Suggested name for "
CONFIRMED = "Confirmed"
CONFIRMED_BARE = "Confirmed by the source finder."
NOT_CONFIRMED = "Could not confirm."
NOT_CONFIRMED_MORE = "Could not confirm. What the source finder found is under Details."
NOT_CHECKED = "The source finder has not checked it yet."
APPROVE_LABEL, REJECT_LABEL = "Approve", "Reject"
APPROVED = ("Approved. The ZENITH editor uses it from the next briefing. The builder adds it to story tagging with "
            "the next update.")
# A removal takes the name away, and a fix changes what is on file: their own words after the approval.
APPROVED_REMOVAL = ("Approved. The ZENITH editor stops counting it from the next briefing. The builder takes it out of "
                    "story tagging with the next update.")
APPROVED_FIX = ("Approved. The ZENITH editor uses the fix from the next briefing. The builder brings story tagging in "
                "line with the next update.")
NO_LONGER_BIG = "No longer a big customer"
REJECTED = "Rejected. The names on file stay as they are."
REJECT_TITLE = "Reject this suggested name?"
REJECT_MESSAGE = ("The names on file stay as they are, and the source finder's check is set aside. To bring it back, "
                  "suggest it again from Coverage.")
CLOSED = "This suggestion was decided or withdrawn meanwhile, so nothing changed. The list has been reloaded."
CLOSED_CODES = ("suggestion_closed",)

SECTION = "Company names to build in"
APPLY_COMMAND = "node tools/zenux.js company apply {ws} {id}"
DEPLOY_COMMAND = "node deploy/workspace.mjs {ws}"
APPLY_HINT = ("Run in PowerShell from the repository, one at a time: it writes the name into the company's sheet, "
              "rebuilds the registries and the bundle, runs their tests (the files go back when they fail) and marks "
              "it applied. Deploy once they succeed.")
DEPLOY_AFTER_APPLY = "Then deploy (this also makes the applied ones live):"
DEPLOY_ONLY = "Deploy to make them live:"
APPLIED_HEAD = "Applied, waiting for a deploy"
AS_TYPED = "Approved as the analyst typed it (not the source finder's version)."

_DAY_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")


# ---------------------------------------------------------------------------------------------- shapes (pure)


def jsonish(value: Any) -> Any:
    """A JSON column the hub may send as text (verdict, aliases): parsed, or the value itself."""
    if isinstance(value, str) and value.strip()[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def is_suggestion(row: Any) -> bool:
    """A company suggestion (its id is CS- and 8 hex digits), not a preference suggestion."""
    return isinstance(row, Mapping) and bool(api.SUGGESTION_ID_RE.match(one_line(row.get("id"))))


def status_of(row: Mapping, default: str = "") -> str:
    return one_line(row.get("status")).lower() or default


def suggestions_of(body: Any, key: str = "suggestions") -> list[dict]:
    """The company suggestions of a hub answer (`key`; or the answer itself when it is a list), first of each id."""
    rows = dicts(body) if isinstance(body, list) else dicts(pick(body, key, default=[]))
    return [r for r in unique_by_id(rows) if is_suggestion(r)]


def proposed(prefs_body: Any) -> list[dict]:
    """GET /preferences `company_suggestions` that wait for the analyst's OK (proposed; a row without a status counts
    as proposed, since only those are sent)."""
    return [r for r in suggestions_of(prefs_body, "company_suggestions") if status_of(r, "proposed") in WAITING]


def verdict_of(row: Mapping) -> dict:
    verdict = jsonish(row.get("verdict"))
    return dict(verdict) if isinstance(verdict, Mapping) else {}


def proposal_of(row: Mapping) -> dict:
    proposal = verdict_of(row).get("proposal")
    return dict(proposal) if isinstance(proposal, Mapping) else {}


def result_of(row: Mapping) -> str:
    """confirmed, not_confirmed, unclear or '' (not checked)."""
    return one_line(verdict_of(row).get("result")).lower()


def use_of(row: Mapping) -> str:
    """Which version an approval writes: the source finder's proposal when there is one (and the owner did not choose
    the analyst's words), else the analyst's words as typed."""
    return "proposal" if proposal_of(row) and one_line(row.get("use")).lower() != "as_typed" else "as_typed"


def names_list(value: Any) -> list[str]:
    return [one_line(n) for n in as_list(jsonish(value)) if one_line(n)]


def shown(row: Mapping) -> dict:
    """What the suggestion writes, as the card shows it: {name, aliases, note, big, basis_text, typed}: the source
    finder's proposal over what the analyst typed (use_of; big True or False, a stored 1 or 0 counting as such, or
    None), and `typed`, the analyst's own name when the proposal renames it ('' otherwise, and for a removal, whose
    name was picked from the names on file)."""
    layers = [proposal_of(row), row] if use_of(row) == "proposal" else [row]

    def first(key: str) -> str:
        return next((one_line(layer.get(key)) for layer in layers if one_line(layer.get(key))), "")

    big = next((company_map_view.flag(layer.get("big")) for layer in layers
                if company_map_view.flag(layer.get("big")) is not None), None)
    typed = one_line(row.get("name")) if action_of(row) != "remove" else ""
    name = first("name") or target_name(row)
    aliases = next((names_list(layer.get("aliases")) for layer in layers if names_list(layer.get("aliases"))), [])
    return {"name": name, "aliases": [a for a in aliases if a.casefold() != name.casefold()], "note": first("note"),
            "big": big, "basis_text": first("basis_text") if big else "",
            "typed": typed if typed and typed.casefold() != name.casefold() else ""}


def company_name(row: Mapping) -> str:
    """The company's name as the hub (or named) sent it; '' when it sent none."""
    for key in ("company_name", "company.name", "company"):
        value = pick(row, key)
        if isinstance(value, str) and one_line(value):
            return one_line(value)
    return ""


def company_of(row: Mapping) -> str:
    """The company's name, else its ticker."""
    return company_name(row) or one_line(row.get("ticker")).upper() or "a company"


def column_of(row: Mapping) -> str:
    column = one_line(row.get("column"))
    return column if column in COLUMNS else ""


def action_of(row: Mapping) -> str:
    return one_line(row.get("action")).lower()


def target_name(row: Mapping) -> str:
    """The name on file a removal or a fix is about: the hub's target_name, else (a removal) the name sent with it."""
    return one_line(pick(row, "target_name")) or (one_line(row.get("name")) if action_of(row) == "remove" else "")


def on_file(brief: Any) -> dict[str, dict]:
    """The names on file of GET /brief `companies`: {TICKER: {"name": the company's name, "entries": {(column, entry
    id): its name}}}; empty for an older hub."""
    out: dict[str, dict] = {}
    for company in company_map_view.companies_of(brief) or []:
        out[one_line(company.get("ticker")).upper()] = {
            "name": one_line(company.get("name")),
            "entries": {(column, one_line(e.get("id"))): one_line(e.get("name")) for column in COLUMNS
                        for e in company_map_view.entries(company, column) if one_line(e.get("id"))}}
    return out


def lacks_names(row: Mapping) -> bool:
    """True when the hub sent no company name, or no name of the entry a removal or a fix is about."""
    return not company_name(row) or (action_of(row) in ("remove", "change") and bool(one_line(row.get("target_id")))
                                     and not target_name(row))


def with_names(row: Mapping, files: Mapping[str, Mapping]) -> dict:
    """The row with company_name and target_name taken from the names on file (on_file) where the hub left them out."""
    out = dict(row)
    known = files.get(one_line(row.get("ticker")).upper()) or {}
    if not company_name(row) and one_line(known.get("name")):
        out["company_name"] = one_line(known.get("name"))
    if action_of(row) in ("remove", "change") and not target_name(row):
        entries = known.get("entries") if isinstance(known.get("entries"), Mapping) else {}
        found = one_line(entries.get((column_of(row), one_line(row.get("target_id")))))
        if found:
            out["target_name"] = found
    return out


def named(rows: list[dict], read_brief: Callable[[], Any]) -> list[dict]:
    """The rows, those that lack a name filled from the names on file; read_brief (the cached GET /brief) runs only
    when one lacks a name, and a failed read leaves the rows as they are."""
    if not any(lacks_names(r) for r in rows):
        return list(rows)
    try:
        files = on_file(read_brief())
    except api.ApiError:
        return list(rows)
    return [with_names(r, files) if lacks_names(r) else r for r in rows]


def pattern(row: Mapping) -> re.Pattern | None:
    """The suggestion's names (as shown, as typed, the other names, the entry it changes, the company) for marking them
    inside a sentence (company_map_view.marked)."""
    values = shown(row)
    return company_map_view.pattern_of(
        [values["name"], values["typed"], one_line(row.get("name")), one_line(pick(row, "target_name")),
         company_of(row)] + values["aliases"] + names_list(row.get("aliases")))


def source_date(value: Any, tz: str) -> str:
    """'Sep 30, 2026' (a day as written, never moved by a time zone), 'Sep 2026', or a time's local day; '' unknown."""
    raw = one_line(value)
    m = _DAY_RE.match(raw)
    if m:
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
        except ValueError:
            return ""
        return f"{day:%b} {day.day}, {day.year}" if m.group(3) else f"{day:%b} {day.year}"
    at = parse_time(raw)
    if at == MIN_TIME:
        return ""
    local = at.astimezone(zone(tz))
    return f"{local:%b} {local.day}, {local.year}"


def evidence_of(row: Mapping) -> list[dict]:
    """The sources the source finder read that can be shown: a title or a plain http(s) link."""
    return [e for e in dicts(verdict_of(row).get("evidence")) if one_line(e.get("title")) or safe_url(e.get("url"))]


def source_html(item: Mapping, tz: str) -> str:
    """'<title as a link>, Sep 30, 2026' (the link's site when it has no title)."""
    url = safe_url(item.get("url"))
    title = clip(item.get("title"), 160) or domain_of(url) or "a source"
    when = source_date(item.get("date"), tz)
    return (link(url, title) if url else esc(title)) + (f", {esc(when)}" if when else "")


def summary_of(row: Mapping) -> str:
    return one_line(verdict_of(row).get("summary"))


def by_finder(row: Mapping, key: str) -> bool:
    """True when what the card shows for `key` (note, basis_text) is the source finder's wording, not the analyst's
    (shown takes the proposal's first)."""
    return use_of(row) == "proposal" and bool(one_line(proposal_of(row).get(key)))


def plain_html(text: Any, names: re.Pattern | None = None) -> str:
    """A sentence the source finder wrote, escaped with its names drawn as names, or '' when it is not in plain words
    (engine words, ids, JSON; ui.looks_technical): Tuning leaves such a line out rather than show the engine's words."""
    html = company_map_view.marked(text, names)
    return "" if ui.looks_technical(html) else html


# ---------------------------------------------------------------------------------------------- html (pure)


def change_html(row: Mapping) -> str:
    """'Add <name> to Customers & programs' ('Remove ... from', 'Fix ... in'); a removal names the entry on file, and a
    fix that renames says both names: 'Fix <old> in Products & brands: call it <new>'."""
    values, action = shown(row), action_of(row)
    verb, joint = CHANGE_WORDS.get(action, ("Change", "in"))
    column = COLUMNS.get(column_of(row), "")
    target = target_name(row)
    renames = bool(action == "change" and target and values["name"]
                   and target.casefold() != values["name"].casefold())
    first = target if target and (renames or action == "remove") else values["name"]
    out = f"{esc(verb)} " + (labels.name_html(first) if first else esc("a name"))
    out += f" {esc(joint)} {esc(column)}" if column else ""
    return out + (f": call it {labels.name_html(values['name'])}" if renames else "")


def result_html(row: Mapping, tz: str, details: bool = True) -> str:
    """The source finder's result in plain words: 'Confirmed: <title>, <date>' with the link, or 'Could not confirm.'
    (pointing to Details when they hold what it found; details=False where there are none, as in the Control room)."""
    result = result_of(row)
    if result == "confirmed":
        found = evidence_of(row)
        return f"{esc(CONFIRMED)}: {source_html(found[0], tz)}" if found else esc(CONFIRMED_BARE)
    if result:
        more = details and bool(plain_html(summary_of(row)) or evidence_of(row))
        return esc(NOT_CONFIRMED_MORE if more else NOT_CONFIRMED)
    return esc(NOT_CHECKED)


def approved_toast(row: Mapping) -> str:
    """What the approval of this suggestion does, in its own words: an add is used, a fix is used, a removal stops
    counting."""
    return {"remove": APPROVED_REMOVAL, "change": APPROVED_FIX}.get(action_of(row), APPROVED)


def big_line(row: Mapping, names: re.Pattern | None = None, plain: bool = False) -> str:
    """'Big customer: 73% of 2025 revenue' for a big customer, 'No longer a big customer' for a fix that takes that
    away ('' otherwise). plain (Tuning): the source finder's reason only when it is in plain words, else 'Big customer'
    alone."""
    values = shown(row)
    if column_of(row) != "customers" or action_of(row) == "remove":
        return ""
    if values["big"] is False and action_of(row) == "change":
        return esc(NO_LONGER_BIG)
    if values["big"] is not True:
        return ""
    reason = values["basis_text"]
    html = (plain_html(reason, names) if plain and by_finder(row, "basis_text")
            else company_map_view.marked(reason, names)) if reason else ""
    return "Big customer" + (f": {html}" if html else "")


def card_html(row: Mapping, tz: str) -> str:
    """The card: its head, what it changes, the analyst's own name when the source finder renamed it, the note, a big
    customer's reason and the source finder's result. Escaped; names drawn as names; the source finder's note and
    reason only in plain words."""
    values, names = shown(row), pattern(row)
    when = fmt_date(pick(row, "proposed_at", "updated_at", "created_at"), tz)
    head = ('<div class="loop-card-head">'
            f'<span class="zx-chip suggested">{esc(HEAD)}{labels.name_html(company_of(row))}</span>'
            + (f'<span class="pref-meta">{esc(when)}</span>' if when and when != "—" else "") + "</div>")
    big = big_line(row, names, plain=True)
    note = ((plain_html if by_finder(row, "note") else company_map_view.marked)(values["note"], names)
            if values["note"] else "")
    return (f'<div class="pref-card">{head}<div class="pref-text">{change_html(row)}</div>'
            + (f'<div class="refine-owner">You wrote: {labels.name_html(values["typed"])}</div>'
               if values["typed"] else "")
            + (f'<div class="pref-stats">{note}</div>' if note else "")
            + (f'<div class="pref-stats">{big}</div>' if big else "")
            + f'<div class="preview-line">{result_html(row, tz)}</div></div>')


def sent_lines(row: Mapping, names: re.Pattern | None = None) -> list[str]:
    """What the analyst sent, as HTML lines: the name, what it is, the big customer's reason, the link, the note."""
    lines = []
    if one_line(row.get("name")):
        lines.append("Name: " + labels.name_html(row.get("name")))
    if one_line(row.get("note")):
        label = "Why it no longer counts: " if action_of(row) == "remove" else "What it is: "
        lines.append(label + company_map_view.marked(row.get("note"), names))
    if company_map_view.is_yes(row.get("big")) and one_line(row.get("basis_text")):
        lines.append("Big customer: " + company_map_view.marked(row.get("basis_text"), names))
    elif (action_of(row) == "change" and column_of(row) == "customers"
          and company_map_view.flag(row.get("big")) is False):
        lines.append("Big customer: no")
    url = safe_url(row.get("link"))
    if url:
        lines.append("Where you saw it: " + link(url, domain_of(url) or url))
    if one_line(row.get("analyst_note")):
        lines.append("Your note: " + company_map_view.marked(row.get("analyst_note"), names))
    return lines


def details_html(row: Mapping, tz: str) -> str:
    """Details: what the source finder found (its summary, when in plain words), its sources (each a link with its
    date and the quote: the source's own words, like a story's title), the other names, and what the analyst sent; ''
    when there is nothing more to show."""
    names, values, html = pattern(row), shown(row), ""
    summary = plain_html(summary_of(row), names)
    if summary:
        html += ('<div class="refine-label">What the source finder found</div>'
                 f'<div class="refine-owner">{summary}</div>')
    found = evidence_of(row)
    if found:
        items = []
        for item in found:
            quote = clip(item.get("quote"), 200)
            items.append(f'<div class="grade-line">{source_html(item, tz)}</div>'
                         + (f'<div class="grade-line">“{company_map_view.marked(quote, names)}”</div>' if quote else ""))
        html += (f'<div class="refine-label">{esc(plural(len(found), "source"))}</div>'
                 f'<div class="grade-lines">{"".join(items)}</div>')
    if values["aliases"]:
        html += ('<div class="refine-label">Also known as</div>'
                 f'<div class="grade-line">{", ".join(labels.name_html(a) for a in values["aliases"])}</div>')
    sent = sent_lines(row, names)
    if sent:
        html += ('<div class="refine-label">What you sent</div><div class="grade-lines">'
                 + "".join(f'<div class="grade-line">{line}</div>' for line in sent) + "</div>")
    return html


# ---------------------------------------------------------------------------------------------- the Control room


def read_error_line(ws: Workspace, exc: api.ApiError) -> str:
    """One plain line for a GET /companies/suggestions that failed; an older hub (404) does not list them yet."""
    if exc.kind == "not_found":
        return f"{ws.label}: this hub does not list company names yet; deploy the hub (schema 13) to add them."
    return f"Could not load company names from {ws.label} ({exc})."


def to_build(workspace_id: str) -> dict[str, list[dict]]:
    """{approved: [...], applied: [...]} from the cached GET /companies/suggestions?status=, most recent first; each
    list keeps only its status, in case a hub answers more, and a row that lacks a name gets it from the names on file
    (named). Raises ApiError."""
    out: dict[str, list[dict]] = {}
    for status in TO_BUILD:
        rows = [r for r in suggestions_of(data.company_suggestions(workspace_id, status)) if status_of(r) == status]
        out[status] = named(sorted(rows, key=lambda r: parse_time(pick(r, STAMPS[status], "updated_at", "created_at")),
                                   reverse=True), lambda: data.brief(workspace_id))
    return out


def summary_line(ws: Workspace, lists: Mapping[str, list]) -> str:
    """'Pilot: 2 approved, waiting to be built in · 1 applied, waiting for a deploy'."""
    return (f"{ws.label}: {len(lists['approved'])} approved, waiting to be built in · {len(lists['applied'])} applied, "
            "waiting for a deploy")


def item_html(ws: Workspace, row: Mapping) -> str:
    """One suggestion in the list: what kind, its status and '<ws> <id> · <ticker> · <when>', what it changes and in
    which company, the note, a big customer's reason, the source finder's result and what it found (as written: this
    is the builder's room), and how it was approved."""
    status, names = status_of(row), pattern(row)
    when = pick(row, STAMPS.get(status, "updated_at"), "updated_at", "created_at")
    sid, ticker = one_line(row.get("id")), one_line(row.get("ticker")).upper()
    values, big = shown(row), big_line(row, names)
    note, summary = one_line(row.get("decision_note")), summary_of(row)
    return ('<div class="radar-body"><div class="loop-card-head">'
            f'<span class="loop-kind">{esc(ACTION_KINDS.get(action_of(row), "A change"))}</span>'
            + pill(status or "unknown")
            + f'<span class="rule-meta" style="margin-top:0">{esc(ws.id)} {esc(sid)}'
            + (f" · {esc(ticker)}" if ticker else "") + f" · {esc(fmt_short(when, ws.timezone))}</span></div>"
            + f'<div class="rule-text">{change_html(row)} of {labels.name_html(company_of(row))}</div>'
            + (f'<div class="refine-note">{company_map_view.marked(values["note"], names)}</div>'
               if values["note"] else "")
            + (f'<div class="refine-note">{big}</div>' if big else "")
            + f'<div class="refine-note">Source finder: {result_html(row, ws.timezone, details=False)}</div>'
            + (f'<div class="refine-note">What it found: {company_map_view.marked(clip(summary, 300), names)}</div>'
               if summary else "")
            + (f'<div class="refine-note">{esc(AS_TYPED)}</div>' if one_line(row.get("use")).lower() == "as_typed"
               else "")
            + (f'<div class="refine-note">Note: {esc(clip(note, 300))}</div>' if note else "")
            + "</div>")


def render_workspace(ws: Workspace, lists: Mapping[str, list[dict]]) -> None:
    """One workspace: a count line; each approved suggestion with its apply command; the deploy; the applied ones."""
    approved, applied = lists["approved"], lists["applied"]
    if not approved and not applied:
        st.caption(md_label(f"{ws.label}: no company names to build in."))
        return
    st.caption(md_label(summary_line(ws, lists)))
    deploy = DEPLOY_COMMAND.format(ws=ws.id)
    if approved:
        st.caption(APPLY_HINT)
        for row in approved:
            st.markdown(item_html(ws, row), unsafe_allow_html=True)
            st.code(APPLY_COMMAND.format(ws=ws.id, id=one_line(row.get("id"))), language="powershell")
        st.caption(DEPLOY_AFTER_APPLY)
        st.code(deploy, language="powershell")
    if applied:
        st.markdown(f'<div class="refine-label">{esc(APPLIED_HEAD)} · {len(applied)}</div>'
                    + "".join(item_html(ws, row) for row in applied), unsafe_allow_html=True)
        if not approved:
            st.caption(DEPLOY_ONLY)
            st.code(deploy, language="powershell")


def render_review(conf: Config) -> None:
    """Company names to build in · N, every workspace (Control room, after the source repairs)."""
    read: list[tuple[Workspace, dict | None, api.ApiError | None]] = []
    for ws in conf.workspaces:
        try:
            read.append((ws, to_build(ws.id), None))
        except api.ApiError as exc:
            read.append((ws, None, exc))
    total = sum(len(lists["approved"]) + len(lists["applied"]) for _, lists, _ in read if lists)
    st.markdown(section_label(f"{SECTION} · {total}", "every workspace"), unsafe_allow_html=True)
    if not conf.workspaces:
        st.caption("No workspace is configured.")
        return
    for ws, lists, exc in read:
        with st.container(key=f"cr_cnames_{ws.id}"):
            if exc is not None:
                st.caption(md_label(read_error_line(ws, exc)))
            else:
                render_workspace(ws, lists or {"approved": [], "applied": []})
