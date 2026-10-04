"""Source repairs (GET /repairs): the builder's review in the Control room, right after the coverage requests
(docs/SPEC-REPAIR-PHASE-B.md section 3; Phase B of docs/PLAN-SOURCE-REPAIR.md).

The Radar scout's repair step proposes one fix for a broken source, proven by a probe on the module Worker itself:
replace the source, turn it off with named alternates, check it less often, or add a source next to it, with one plain
diagnosis sentence. The hub keeps it as a repair (1.4): the catalog's entry for the source when proposed
(`proposal.current`, the "before"), the new source definition (`proposal.source`), the alternates with their catalog
labels, the probe's trimmed answer (`evidence`), a status (proposed, approved, rejected, applied, recovered, withdrawn)
and its time stamps.

render_review(conf), every workspace:
- each proposed repair as a card styled like the coverage-request review: the action, the module, the source's label
  and key, the class's plain label, the diagnosis, before and after side by side (replace and add: the catalog's entry
  against the new source definition as compact JSON; turn_off: on against off, with the off reason and the alternates
  by label; slow_down: the cadence now and after, in words), the probe's evidence (its status, the HTTP answer, the
  items found, up to 5 titles as links, when it ran), a note, then Approve and Reject (POST
  /repairs/<id>/{approve|reject} {note?} through ui.write with a toast; no route reverses either, so there is no undo,
  and Reject asks first);
- below, collapsed, with their counts: approved (the command `node tools/zenux.js repair apply <ws> <id>`, then the
  deploy, and Withdraw: POST /repairs/<id>/withdraw after a confirmation), applied (waiting for the source to report
  ok; Withdraw too, for a fix that did not work: the change stays in the module, and the source is free for another
  proposal), recovered, and rejected or withdrawn, most recent first.
The writes need the owner token, like every Control room write (open access makes everyone the builder during the
beta). A failed read is one plain line, never a crash. The source-health window (control_view.failing_dialog) reads
the same cached list (open_fixes, window_line); Coverage says "ZENUX is fixing 2 sources." from GET /modules
`repairs_open` (coverage_view.fixing_text).
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import streamlit as st

from . import api, data, labels, ui
from .config import Config, Workspace
from .fmt import (as_int, as_list, clip, dicts, esc, every_text, fmt_short, label_of, link, md_label, one_line,
                  parse_time, pick, pill, plural, safe_url, section_label, table, unique_by_id)

ACTION_WORDS = {"replace": "Replace the source", "turn_off": "Turn it off", "slow_down": "Check it less often",
                "add": "Add a source"}
STATUSES = ("proposed", "approved", "applied", "recovered", "rejected", "withdrawn")
OPEN = ("proposed", "approved", "applied")  # the hub keeps at most one open repair per source
STAMPS = {"proposed": "created_at", "approved": "decided_at", "applied": "applied_at", "recovered": "recovered_at",
          "rejected": "decided_at", "withdrawn": "updated_at"}  # when a repair reached its status
STATUS_CSS = {"recovered": "ok", "withdrawn": "idle"}  # pills the shared map lacks
PROBE_OK = ("ok", "empty", "not_modified")  # a probe answer that counts as a working check
ITEMS_SHOWN = 5
APPLY_COMMAND = "node tools/zenux.js repair apply {ws} {id}"
DEPLOY_COMMAND = "node deploy/workspace.mjs {ws}"
WINDOW_LINES = {  # the source-health window's line for a failing or retrying source with an open repair
    "proposed": "A fix is proposed (repair #{id}): review it under Source repairs to review.",
    "approved": "A fix is approved (repair #{id}); waiting for the builder to apply it.",
    "applied": "A fix is applied (repair #{id}); waiting for the source to report ok.",
}
REJECT_TEXT = "Nothing changes in the module. The Radar scout may propose another fix while the source keeps failing."
WITHDRAW_TEXT = "It will not be applied, and nothing changes in the module."
WITHDRAW_APPLIED_TEXT = ("For a fix that did not work. The change stays in the module (undo it there by hand if "
                         "needed); withdrawing only closes this repair, so the Radar scout can propose another fix "
                         "while the source keeps failing.")
APPLY_HINT = ("Run in PowerShell from the repository: it writes the change into the module, keeps the old definition in "
              "the source's notes and runs the module's tests (the files go back when they fail). Deploy once it "
              "succeeds.")


# ---------------------------------------------------------------------------------------------- shapes (pure)


def repairs_of(body: Any) -> list[dict]:
    """GET /repairs rows with a usable id (the first of each), newest first."""
    rows = dicts(body) if isinstance(body, list) else dicts(pick(body, "repairs", default=[]))
    rows = [r for r in unique_by_id(rows) if as_int(r.get("id")) is not None]
    return sorted(rows, key=lambda r: as_int(r.get("id")) or 0, reverse=True)


def status_of(row: Mapping) -> str:
    return one_line(row.get("status")).lower()


def action_of(row: Mapping) -> str:
    return one_line(row.get("action")).lower()


def action_text(action: Any) -> str:
    """The action in plain words: 'Replace the source', 'Turn it off', 'Check it less often' or 'Add a source'."""
    code = one_line(action).lower()
    words = label_of(code)
    return ACTION_WORDS.get(code) or (words[:1].upper() + words[1:] if words else "A change")


def proposal_of(row: Mapping) -> dict:
    proposal = row.get("proposal")
    return dict(proposal) if isinstance(proposal, Mapping) else {}


def current_of(row: Mapping) -> dict | None:
    """proposal.current: the catalog's entry for the source when the repair was proposed (the "before"), or None."""
    current = proposal_of(row).get("current")
    return dict(current) if isinstance(current, Mapping) else None


def compact_json(value: Any) -> str:
    """A source definition on one line, its empty (null) fields left out: '{"key": "x", "connector": "rss", ...}'."""
    if isinstance(value, Mapping):
        value = {k: v for k, v in value.items() if v is not None}
    try:
        return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    except (TypeError, ValueError):
        return one_line(value)


def alternates_of(row: Mapping) -> list[tuple[str, str]]:
    """(label, key) of each alternate a turn_off names: the hub's `alternates` with their catalog labels, then any key
    of the proposal the hub did not resolve (its label '')."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for alt in dicts(row.get("alternates")) + [{"key": k} for k in as_list(proposal_of(row).get("alternates"))]:
        key = one_line(alt.get("key"))
        if key and key not in seen:
            seen.add(key)
            out.append((one_line(alt.get("label")), key))
    return out


def cadence_change(row: Mapping) -> tuple[str, str]:
    """('Checked every 2 h', 'Checked every 6 h'): a slow_down's cadence now (the catalog's) and after, in words."""
    now = as_int(pick(current_of(row) or {}, "cadence_minutes"))
    new = as_int(proposal_of(row).get("cadence_minutes"))
    return (f"Checked {every_text(now)}" if now and now > 0 else "Checked at the module's default pace",
            f"Checked {every_text(new)}" if new and new > 0 else "No new pace given")


def evidence_facts(evidence: Any, tz: str) -> list[str]:
    """['HTTP 200', '7 items found', 'probed Oct 4 · 8:55 AM']: what the probe answered (its status is a pill)."""
    if not isinstance(evidence, Mapping):
        return []
    facts = []
    http = as_int(evidence.get("http_status"))
    if http is not None:
        facts.append(f"HTTP {http}")
    total = as_int(evidence.get("items_total"))
    if total is not None:
        facts.append(f"{plural(total, 'item')} found" if total > 0 else "no items found")
    if evidence.get("probed_at"):
        facts.append(f"probed {fmt_short(evidence.get('probed_at'), tz)}")
    return facts


def evidence_notes(evidence: Any) -> str:
    """The probe's notes, joined ('preview, disabled_in_manifest'); '' when it has none."""
    notes = evidence.get("notes") if isinstance(evidence, Mapping) else None
    if isinstance(notes, (list, tuple)):
        return ", ".join(one_line(n) for n in notes if one_line(n))
    return one_line(notes)


def window_line(row: Mapping | None) -> str:
    """The source-health window's line for a source whose repair is open; '' for any other status."""
    template = WINDOW_LINES.get(status_of(row or {}))
    return template.format(id=as_int((row or {}).get("id"))) if template else ""


def open_by_source(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """{(module id, source key): its open repair (proposed, approved or applied)}; with rows newest first, the newest
    when a hub lists two."""
    out: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (one_line(row.get("module_id")), one_line(row.get("source_key")))
        if status_of(row) in OPEN and all(key):
            out.setdefault(key, row)
    return out


def open_fixes(workspace_id: str) -> dict[tuple[str, str], dict]:
    """open_by_source of one workspace, from the cached GET /repairs; {} when it cannot be read (an older hub)."""
    try:
        return open_by_source(repairs_of(data.repairs(workspace_id)))
    except api.ApiError:
        return {}


def counts_of(body: Any, rows: list[dict]) -> dict[str, int]:
    """Repairs by status: the hub's `counts` (over every repair, not only the 100 it lists), else counted from rows."""
    out = {status: sum(1 for r in rows if status_of(r) == status) for status in STATUSES}
    counts = pick(body, "counts")
    if isinstance(counts, Mapping):
        for status in STATUSES:
            n = as_int(counts.get(status))
            if n is not None and n >= 0:
                out[status] = n
    return out


def recent_first(rows: list[dict]) -> list[dict]:
    """Most recent first: by when each repair reached its status (STAMPS), then by id."""
    def when(row: Mapping) -> Any:
        return parse_time(pick(row, STAMPS.get(status_of(row), "updated_at"), "updated_at", "created_at"))

    return sorted(rows, key=lambda r: (when(r), as_int(r.get("id")) or 0), reverse=True)


def count_text(listed: int, total: int) -> str:
    """'3', or '3 of 140' when the hub counts more than it lists."""
    return f"{listed} of {total}" if total > listed else str(listed)


def summary_line(ws: Workspace, counts: Mapping[str, int]) -> str:
    """'Pilot: 4 to review · 1 approved, waiting to be applied · 1 applied, waiting for the source to report ok ·
    1 recovered · 2 rejected or withdrawn'."""
    return (f"{ws.label}: {counts['proposed']} to review · {counts['approved']} approved, waiting to be applied · "
            f"{counts['applied']} applied, waiting for the source to report ok · {counts['recovered']} recovered · "
            f"{counts['rejected'] + counts['withdrawn']} rejected or withdrawn")


def read_error_line(ws: Workspace, exc: api.ApiError) -> str:
    """One plain line for a GET /repairs that failed; an older hub (404) does not list repairs yet."""
    if exc.kind == "not_found":
        return f"{ws.label}: this hub does not list source repairs yet; deploy the hub (schema 9) to add them."
    return f"Could not load source repairs from {ws.label} ({exc})."


# ---------------------------------------------------------------------------------------------- html (pure)


def mono(text: Any) -> str:
    return f'<span class="mono">{esc(text)}</span>'


def repair_head(ws: Workspace, row: Mapping) -> str:
    """The action chip, the status pill, then '<ws> #<id> · <module> · <when it reached its status>'."""
    action, status = action_of(row), status_of(row)
    module = one_line(row.get("module_id"))
    when = pick(row, STAMPS.get(status, "updated_at"), "updated_at", "created_at")
    chip = (f'<span class="loop-kind{" loop-kind-" + action if action in ACTION_WORDS else ""}">'
            f'{esc(action_text(action))}</span>')
    return ('<div class="loop-card-head">' + chip + pill(status or "unknown", css=STATUS_CSS.get(status))
            + f'<span class="rule-meta" style="margin-top:0">{esc(ws.id)} #{esc(as_int(row.get("id")))}'
            + (f" · {esc(module)}" if module else "") + f" · {esc(fmt_short(when, ws.timezone))}</span></div>")


def source_html(row: Mapping) -> str:
    """The source's plain name and its key (mono)."""
    label, key = one_line(row.get("source_label")), one_line(row.get("source_key"))
    return ('<div class="failing-title">' + (f'<span class="failing-name">{esc(label)}</span>' if label else "")
            + (mono(key) if key else "") + "</div>")


def why_html(row: Mapping) -> str:
    """The class's plain label, then the diagnosis sentence."""
    why = one_line(row.get("class_label")) or label_of(row.get("class"))
    diagnosis = one_line(row.get("diagnosis"))
    return ((f'<div class="refine-note">{esc(why)}</div>' if why else "")
            + (f'<div class="rule-text">{esc(diagnosis)}</div>' if diagnosis
               else '<div class="refine-note">No diagnosis given.</div>'))


def change_cells(row: Mapping) -> tuple[str, str] | None:
    """(before, after) as HTML cells for the repair's action (see the module docstring); None for an unknown action."""
    action = action_of(row)
    proposal = proposal_of(row)
    current = current_of(row)
    if action in ("replace", "add"):
        source = proposal.get("source")
        before = mono(compact_json(current)) if current else esc("Not in the catalog.")
        after = mono(compact_json(source)) if isinstance(source, Mapping) else esc("No source definition was sent.")
        if action == "add":
            return esc("Stays as it is:") + "<br>" + before, esc("Added next to it:") + "<br>" + after
        return before, after
    if action == "turn_off":
        url = one_line(pick(current or {}, "url"))
        alternates = ", ".join((f"{esc(label)} " if label else "") + mono(key) for label, key in alternates_of(row))
        return (esc("On") + (f"<br>{mono(url)}" if url else ""),
                esc("Off: " + (one_line(proposal.get("off_reason")) or "no reason given."))
                + "<br>" + esc("Alternates: ") + (alternates or esc("none named.")))
    if action == "slow_down":
        now, new = cadence_change(row)
        return esc(now), esc(new)
    return None


def change_html(row: Mapping) -> str:
    """Before and after, side by side, in one table row ('' for an unknown action)."""
    cells = change_cells(row)
    return table(["Before", "After"], [list(cells)]) if cells else ""


def evidence_html(evidence: Any, tz: str) -> str:
    """The probe's answer: its status and facts, up to 5 items (each title a link, with its date), its notes."""
    if not isinstance(evidence, Mapping):
        return '<div class="refine-note">No probe evidence.</div>'
    status = one_line(evidence.get("status")).lower() or "unknown"
    facts = evidence_facts(evidence, tz)
    out = ['<div class="refine-note">' + pill(status, css="ok" if status in PROBE_OK else None)
           + (f" {esc(' · '.join(facts))}" if facts else "") + "</div>"]
    rows = []
    for item in dicts(evidence.get("items"))[:ITEMS_SHOWN]:
        title = clip(item.get("title"), 160) or "Untitled item"
        url = safe_url(item.get("url"))
        rows.append([link(url, title, "") if url else esc(title), esc(fmt_short(item.get("published_at"), tz))])
    if rows:
        out.append(table(["Found by the probe", "Published"], rows))
    notes = evidence_notes(evidence)
    if notes:
        out.append(f'<div class="refine-note">Notes: {esc(notes)}</div>')
    return "".join(out)


def card_html(ws: Workspace, row: Mapping) -> str:
    """One proposed repair, for review: the head, the source, why it broke, before and after, the probe's evidence."""
    return ('<div class="radar-body">' + repair_head(ws, row) + source_html(row)
            + '<div class="refine-label">Why it broke</div>' + why_html(row)
            + '<div class="refine-label">Before and after</div>'
            + (change_html(row) or '<div class="refine-note">No change described.</div>')
            + '<div class="refine-label">Probe from the module</div>' + evidence_html(row.get("evidence"), ws.timezone)
            + "</div>")


def listed_html(ws: Workspace, row: Mapping, extra: str = "") -> str:
    """A repair in a list under the cards: the head, the source, why it broke, `extra`, the builder's note."""
    note = one_line(row.get("note"))
    return ('<div class="radar-body">' + repair_head(ws, row) + source_html(row) + why_html(row) + extra
            + (f'<div class="refine-note">Note: {esc(clip(note, 300))}</div>' if note else "") + "</div>")


def applied_html(row: Mapping, tz: str) -> str:
    return (f'<div class="refine-note">Applied {esc(fmt_short(row.get("applied_at"), tz))}; it counts as recovered '
            "once the source reports ok after that.</div>")


def recovered_html(row: Mapping, tz: str) -> str:
    return (f'<div class="refine-note">Recovered {esc(fmt_short(row.get("recovered_at"), tz))}: the source reported '
            "ok after the fix.</div>")


# ---------------------------------------------------------------------------------------------- writes


def _call(ws: Workspace, rid: int, action: str, note: str = ""):
    """The write for ui.write. A refusal because the repair moved on (409) or is gone (404) clears the cached list, so
    the next run shows where it stands."""
    def call(token: str) -> Any:
        try:
            return api.repair_action(ws, token, rid, action, note=note or None)
        except api.ApiError as exc:
            if exc.status in (404, 409):
                data.repairs.clear()
            raise
    return call


def approve_repair(ws: Workspace, rid: int, note: str = "") -> None:
    """POST /repairs/<id>/approve {note?} through ui.write: a toast and no undo (Withdraw, under approved, takes it
    back until it is applied); then a full rerun."""
    if ui.write(ws, _call(ws, rid, "approve", note),
                toast=f"Approved source repair #{rid} for {ws.label}. Apply it with the command under approved, then "
                      "deploy.") is not None:
        st.rerun()


def reject_repair(ws: Workspace, rid: int, note: str = "") -> None:
    """POST /repairs/<id>/reject {note?} through ui.write; runs inside the confirmation (which closes and reruns)."""
    ui.write(ws, _call(ws, rid, "reject", note), toast=f"Rejected source repair #{rid} for {ws.label}.")


def withdraw_repair(ws: Workspace, rid: int, applied: bool = False) -> None:
    """POST /repairs/<id>/withdraw through ui.write; runs inside the confirmation."""
    after = ("The change stays in the module; the Radar scout may propose another fix." if applied
             else "It will not be applied.")
    ui.write(ws, _call(ws, rid, "withdraw"), toast=f"Withdrew source repair #{rid} for {ws.label}. {after}")


# ---------------------------------------------------------------------------------------------- page


def render_card(ws: Workspace, row: Mapping) -> None:
    """A proposed repair: the card, a note, Approve and Reject (Reject asks first)."""
    rid = as_int(row.get("id"))
    with st.container(border=True, key=f"zx_card_repair_{ws.id}_{rid}"):
        st.markdown(card_html(ws, row), unsafe_allow_html=True)
        note = st.text_input("Note (optional)", key=f"cr_repair_note_{ws.id}_{rid}", max_chars=api.LONG_TEXT_MAX,
                             placeholder="why, or what to check when it is applied")
        approve, reject = st.columns(2)
        with approve:
            if ui.write_button("Approve", ws=ws, key=f"cr_repair_approve_{ws.id}_{rid}", type="primary"):
                approve_repair(ws, rid, one_line(note))
        with reject:
            if ui.write_button("Reject", ws=ws, key=f"cr_repair_reject_{ws.id}_{rid}"):
                text = one_line(note)
                ui.ask_confirm(f"Reject source repair #{rid}?", REJECT_TEXT, "Reject",
                               lambda: reject_repair(ws, rid, text), detail=f"Your note: {text}" if text else None)


def render_approved(ws: Workspace, row: Mapping) -> None:
    """An approved repair: the command that applies it, then the deploy, and Withdraw (asks first)."""
    rid = as_int(row.get("id"))
    st.markdown(listed_html(ws, row), unsafe_allow_html=True)
    st.code(APPLY_COMMAND.format(ws=ws.id, id=rid), language="powershell")
    st.markdown(f'<div class="refine-note">then deploy: {mono(DEPLOY_COMMAND.format(ws=ws.id))}</div>',
                unsafe_allow_html=True)
    if ui.write_button("Withdraw", ws=ws, key=f"cr_repair_withdraw_{ws.id}_{rid}", type="tertiary"):
        ui.ask_confirm(f"Withdraw source repair #{rid}?", WITHDRAW_TEXT, "Withdraw", lambda: withdraw_repair(ws, rid),
                       detail=labels.NO_UNDO)


def render_applied(ws: Workspace, row: Mapping) -> None:
    """An applied repair: when it counts as recovered, and Withdraw for a fix that did not work (asks first)."""
    rid = as_int(row.get("id"))
    st.markdown(listed_html(ws, row, applied_html(row, ws.timezone)), unsafe_allow_html=True)
    if ui.write_button("Withdraw", ws=ws, key=f"cr_repair_withdraw_{ws.id}_{rid}", type="tertiary",
                       help="For a fix that did not work: frees the source for another proposal"):
        ui.ask_confirm(f"Withdraw source repair #{rid}?", WITHDRAW_APPLIED_TEXT, "Withdraw",
                       lambda: withdraw_repair(ws, rid, applied=True), detail=labels.NO_UNDO)


def render_workspace(ws: Workspace) -> None:
    """One workspace: a count line, a card per proposed repair, then the collapsed lists."""
    try:
        body = data.repairs(ws.id)
    except api.ApiError as exc:
        st.caption(md_label(read_error_line(ws, exc)))
        return
    rows = repairs_of(body)
    if not rows:
        st.caption(md_label(f"{ws.label}: no source repairs yet."))
        return
    counts = counts_of(body, rows)
    by_status = {status: [r for r in rows if status_of(r) == status] for status in STATUSES}
    st.caption(md_label(summary_line(ws, counts)))
    for row in by_status["proposed"]:
        render_card(ws, row)
    if counts["proposed"] > len(by_status["proposed"]):  # nothing silent: the hub lists its newest 100 repairs
        st.caption(f"{len(by_status['proposed'])} of the {counts['proposed']} proposed repairs are shown here: the hub "
                   "lists its newest 100 repairs.")
    approved = recent_first(by_status["approved"])
    if approved:
        with st.expander(f"{ws.id} · repairs approved, waiting to be applied · "
                         f"{count_text(len(approved), counts['approved'])}"):
            st.caption(APPLY_HINT)
            for row in approved:
                render_approved(ws, row)
    applied = recent_first(by_status["applied"])
    if applied:
        with st.expander(f"{ws.id} · repairs applied, waiting for the source to report ok · "
                         f"{count_text(len(applied), counts['applied'])}"):
            for row in applied:
                render_applied(ws, row)
    recovered = recent_first(by_status["recovered"])
    if recovered:
        with st.expander(f"{ws.id} · repairs recovered · {count_text(len(recovered), counts['recovered'])}"):
            st.markdown("".join(listed_html(ws, r, recovered_html(r, ws.timezone)) for r in recovered),
                        unsafe_allow_html=True)
    closed = recent_first(by_status["rejected"] + by_status["withdrawn"])
    if closed:
        with st.expander(f"{ws.id} · repairs rejected or withdrawn · "
                         f"{count_text(len(closed), counts['rejected'] + counts['withdrawn'])}"):
            st.markdown("".join(listed_html(ws, r) for r in closed), unsafe_allow_html=True)


def render_review(conf: Config) -> None:
    """Source repairs to review, every workspace (Control room, after the coverage requests)."""
    st.markdown(section_label("Source repairs to review", "every workspace"), unsafe_allow_html=True)
    if not conf.workspaces:
        st.caption("No workspace is configured.")
        return
    for ws in conf.workspaces:
        with st.container(key=f"cr_repairs_{ws.id}"):
            render_workspace(ws)
