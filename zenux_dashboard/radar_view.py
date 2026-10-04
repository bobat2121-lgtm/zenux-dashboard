"""Coverage requests (GET /radar): the analyst's asks inside Coverage, and the builder's review inside the Control room.

The analyst asks in their own words (POST /radar/requests {kind, text, url?, module?}): a source, a company or topic,
or a story ZENUX missed. The Source finder routine (the Radar scout) answers at its next run with a proposal; the
builder approves or rejects it in the Control room (POST /radar/:id/{approve|reject}) and sets it up with
`node tools/zenux.js radar apply <ws> <id>`; the hub then marks it applied (in the coverage catalog) and live (its new
sources report). Every request carries a plain `stage` (asked, proposal, approved, applied, live, rejected) and a
`timeline` [{stage, at}]; GET /radar adds the proposed `sources` [{module, key, label, state}], `first_items` (a count
of events collected from them since they were set up), `first_stories` (the newest three), and `proposal_plain`
(the source finder's summary with area names, and its diagnosis in plain words).

Analyst part, render_requests(ws, module_id): the composer ("Ask for a source or topic" / "Report a missed story"),
toast with the Source finder's next run and undo (withdraw), and the request list: kind, when it was asked, the
coverage area, the analyst's words, a five-step timeline, the plain proposal summary and diagnosis, source states and
first stories, and Withdraw (confirmed) while asked or proposed. No source keys, connectors, module ids or JSON here.
Dialog `request` ("Request coverage" from Coverage's company details): the same fields, kind new_coverage, prefilled.

Builder part, render_review(conf), every workspace: the technical proposal (field table, proposed sources with module,
key, label, connector, lane, trust and URL, registry changes, notes, diagnosis, rule draft, the full JSON), Approve
(bound to the proposal's proposed_at: a newer proposal is refused with 409 proposal_changed and the list is read again)
and Reject (confirmed) with a note; approved requests list the setup command; applied and live ones their sources.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

import streamlit as st

from . import api, data, fmt, labels, links, owner, ui
from .config import Workspace, load_config
from .fmt import (as_int, as_list, clip, dicts, empty_state, esc, esc_lines, fmt_date, fmt_day, fmt_short, label_of,
                  link, one_line, pick, pill, plural, safe_url, section_label, table, unique_by_id)

MIN_TEXT = 10
WITHDRAWN = "withdrawn by owner"
REQUESTS_ANCHOR = "zx-coverage-requests"  # the id Coverage's "Ask for a source" link jumps to
PROPOSAL_CHANGED = "proposal_changed"
SOURCE_OR_TOPIC = "source_or_topic"
MISSED_STORY = "missed_story"
ASK_CHOICES = {SOURCE_OR_TOPIC: "Ask for a source or topic", MISSED_STORY: "Report a missed story"}
WHAT_CHOICES = ("track_source", "new_coverage")
PLACEHOLDERS = {SOURCE_OR_TOPIC: "e.g. the Texas PUC large-load docket",
                MISSED_STORY: "e.g. Army order for 500 interceptors, reported by Breaking Defense on Oct 2"}
NOT_SURE = ""
# Stored statuses -> plain stages, for a hub that sends no `stage` (older than schema 8).
STATUS_STAGE = {"queued": "asked", "pending": "asked", "new": "asked", "scouting": "asked", "proposed": "proposal",
                "ready": "proposal", "approved": "approved", "approved_pending_apply": "approved",
                "applied": "applied", "live": "live", "rejected": "rejected"}
STAMP_FIELDS = (("asked", "created_at"), ("proposal", "proposed_at"), ("approved", "decided_at"),
                ("applied", "applied_at"), ("live", "live_at"))
WITHDRAWABLE = ("asked", "proposal")
FIRST_ITEMS_SHOWN = 3
STAGE_NOTES = {
    "asked": "The source finder looks into it at its next run.",
    "proposal": "A proposal is ready. The builder reviews it and sets it up.",
    "approved": "Approved. The builder is setting it up.",
    "applied": "Set up. It shows as live once the new source reports.",
    "live": "Live: ZENUX collects from it now.",
}
APPLY_COMMAND = "node tools/zenux.js radar apply {ws} {id}"
STATE_CSS = {"live": "ok", "in_catalog": "warn", "waiting": "idle", "applied": "ok"}  # pills the shared map lacks
CHANGED_KEY = "rv_changed"     # {"<ws>:<id>": message} shown at the top of that card on the next run
RESET_KEY = "rq_reset"         # clear the composer's text fields on the next run (after a successful send)
AREA_FOR_KEY = "rq_area_for"   # the coverage area the composer's area select was last preset to
TEXT_MESSAGE = "Write a few words (10 characters or more) so the source finder knows what to look for."
LINK_MISSING = "Paste the story's link so the source finder can see what was missed."
LINK_BAD = "The link must start with https:// or http://."
PROPOSAL_FIELDS = (
    ("action", "Action"), ("module", "Module"), ("source_key", "Source key"), ("key", "Source key"),
    ("label", "Label"), ("connector", "Connector"), ("url", "URL"), ("lane", "Lane"), ("trust", "Trust"),
    ("cadence_minutes", "Cadence"), ("entity_id", "Entity"), ("found", "Found"), ("collected", "Collected"),
    ("event_id", "Event"), ("why_missed", "Why missed"),
)


# ---------------------------------------------------------------------------------------------- shapes (pure)


def requests_of(body: Any) -> list[dict]:
    if isinstance(body, list):
        return dicts(body)
    return dicts(pick(body, "requests", "radar", "items", default=[]))


def status_of(row: Mapping) -> str:
    return one_line(pick(row, "status", "state")).lower() or "queued"


def kind_of(row: Mapping) -> str:
    return one_line(pick(row, "kind", "type")).lower() or "track_source"


def proposal_of(row: Mapping) -> dict:
    proposal = row.get("proposal")
    return proposal if isinstance(proposal, dict) else ({"summary": proposal} if one_line(proposal) else {})


def stage_of(row: Mapping) -> str:
    """The plain stage: the hub's `stage`, else derived from the stored status."""
    stage = one_line(row.get("stage")).lower()
    return stage if stage in STATUS_STAGE.values() else STATUS_STAGE.get(status_of(row), "asked")


def timeline_of(row: Mapping) -> dict[str, Any]:
    """{stage: at} from the hub's `timeline`, else from the request's own time stamps."""
    out: dict[str, Any] = {}
    for step in dicts(row.get("timeline")):
        stage = one_line(step.get("stage")).lower()
        if stage and step.get("at") and stage not in out:
            out[stage] = step.get("at")
    if out:
        return out
    for stage, field in STAMP_FIELDS:
        if row.get(field):
            out["rejected" if stage == "approved" and status_of(row) == "rejected" else stage] = row.get(field)
    return out


def ordered(rows: list[dict], focus: Any = None) -> list[dict]:
    """Newest first; a deep-linked request first of all."""
    rows = sorted(rows, key=lambda r: as_int(r.get("id")) or 0, reverse=True)
    return sorted(rows, key=lambda r: as_int(r.get("id")) != as_int(focus)) if as_int(focus) is not None else rows


def area_names(ws: Workspace) -> dict[str, str]:
    """{module id: plain coverage-area name} from GET /modules, else the configured modules."""
    names = {m.id: labels.area_name(m.id, m.title or None) for m in ws.modules}
    try:
        body = data.modules(ws.id)
    except api.ApiError:
        return names
    for m in dicts(pick(body, "modules", default=[])):
        mid = one_line(m.get("id"))
        if mid:
            names[mid] = labels.area_name(mid, m.get("title"))
    return names


def plain_text(text: Any, names: Mapping[str, str]) -> str:
    """Hub or Source finder text with each coverage-area id replaced by its plain name."""
    out = one_line(text)
    for mid, name in sorted(names.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"(?<![\w-]){re.escape(mid)}(?![\w-])", name, out)
    return out


def timeline_html(row: Mapping, tz: str) -> str:
    """Five steps (Asked, Proposal ready, Approved, Set up, Live): done when the timeline has the step (its date under
    the label), current for the request's stage. A rejected request shows Asked and Not added."""
    stage = stage_of(row)
    dates = timeline_of(row)
    steps = [("asked", "Asked"), ("rejected", labels.RADAR_REJECTED)] if stage == "rejected" else list(labels.RADAR_STAGES)
    parts = []
    for key, label in steps:
        css = "timeline-step current" if key == stage else "timeline-step done" if key in dates else "timeline-step"
        when = f'<br><span>{esc(fmt_date(dates[key], tz))}</span>' if key in dates else ""
        parts.append(f'<div class="{css}">{esc(label)}{when}</div>')
    return f'<div class="timeline">{"".join(parts)}</div>'


def first_items_lines(value: Any, tz: str) -> list[str]:
    """'First stories: <title> (<date>)' lines from a list, or one count line from the hub's number."""
    items = dicts(value)
    if items:
        return [f"{clip(pick(i, 'title', 'headline') or 'A story', 140)} "
                f"({fmt_date(pick(i, 'published_at', 'received_at'), tz)})" for i in items[:FIRST_ITEMS_SHOWN]]
    n = as_int(value)
    if n is None:
        return []
    return [f"{plural(n, 'story', 'stories')} collected from it so far." if n else "No stories from it yet."]


def diagnosis_label(cause: str) -> str:
    return labels.DIAGNOSIS_LABELS.get(cause) or labels.DIAGNOSIS_LABELS["unknown"]


def decision_text(row: Mapping) -> str:
    """Why a request was not added: the analyst withdrew it, or the builder's note."""
    note = one_line(row.get("decision_note"))
    return "You withdrew this request." if note.lower() == WITHDRAWN else note


def request_html(row: Mapping, names: Mapping[str, str], tz: str, focused: bool = False) -> str:
    """One request card for the analyst, in plain words (no keys, connectors, module ids or JSON)."""
    stage = stage_of(row)
    proposal = proposal_of(row)
    module = one_line(row.get("module"))
    area = (names.get(module) or labels.area_name(module)) if module else ""
    head = " · ".join(p for p in (labels.RADAR_KIND_LABELS.get(kind_of(row), "A request"),
                                  f"asked {fmt_day(row.get('created_at'), tz)}", area) if p)
    url = safe_url(row.get("url"))
    out = [f'<div class="rq-card{" zx-focus" if focused else ""}"><div class="refine-label">{esc(head)}</div>',
           f'<div class="refine-owner">You asked: {esc_lines(row.get("text"))}</div>']
    if url:
        out.append(f'<div class="refine-note">{link(url, fmt.domain_of(url) or url)}</div>')
    out.append(timeline_html(row, tz))
    plain = row.get("proposal_plain") if isinstance(row.get("proposal_plain"), Mapping) else {}
    # the source finder's summary in plain words (`proposal_plain`, area names for module ids; gap 31)
    summary = plain_text(one_line(plain.get("summary")) or pick(proposal, "summary", "rationale"), names)
    if summary and stage != "asked":
        out.append(f'<div class="rule-text">{esc(summary)}</div>')
    cause = one_line(pick(proposal, "diagnosis.cause")).lower()
    cause_text = one_line(plain.get("cause")) or (diagnosis_label(cause) if cause else "")
    if cause_text:
        out.append(f'<div class="refine-note">{esc(cause_text)}</div>')
    sources = [s for s in dicts(row.get("sources")) if one_line(s.get("label")) or one_line(s.get("state"))]
    for src in sources:
        state = labels.RADAR_SOURCE_STATES.get(one_line(src.get("state")).lower(), "")
        out.append(f'<div class="refine-note">{esc(one_line(src.get("label")) or "A new source")}'
                   + (f": {esc(state)}" if state else "") + "</div>")
    # the newest stories from the new sources (`first_stories`, gap 20), else the hub's count
    stories = row.get("first_stories") if dicts(row.get("first_stories")) else row.get("first_items")
    first = first_items_lines(stories, tz) if stage in ("applied", "live") else []
    if first and dicts(stories):
        out.append(f'<div class="refine-note">First stories: {esc(" · ".join(first))}</div>')
    elif first:  # the hub sends a count
        out.append(f'<div class="refine-note">{esc(first[0])}</div>')
    if stage == "rejected":
        why = decision_text(row)
        out.append(f'<div class="refine-note">{esc(labels.RADAR_REJECTED)}' + (f" · {esc(why)}" if why else "") + "</div>")
    elif STAGE_NOTES.get(stage):
        out.append(f'<div class="refine-note">{esc(STAGE_NOTES[stage])}</div>')
    return "".join(out) + "</div>"


# ---------------------------------------------------------------------------------------------- analyst part


def scout_clock(ws: Workspace) -> str:
    """'1:00 PM ET': the Source finder's next run from /diagnostics routines (cached), '' when unknown."""
    try:
        diag = data.diagnostics(ws.id)
    except api.ApiError:
        return ""
    routines = pick(diag, "routines")
    tz = one_line(pick(routines, "timezone")) or ws.timezone
    when = pick(routines, "scout.next_due_at")
    if not when:
        times = [one_line(t) for t in as_list(pick(routines, "scout.schedule")) if one_line(t)]
        when = fmt.next_slot(times, tz) if times else None
    clock = fmt.fmt_clock(when, ws.timezone) if when else ""
    return "" if clock in ("", "—") else clock


def sent_toast(clock: str) -> str:
    return ("Sent to the source finder. It answers after its next run"
            + (f" (about {clock})." if clock else "."))


def validate(kind: str, text: str, url: str) -> str | None:
    """The plain refusal for a request that cannot be sent, else None."""
    if len(text) < MIN_TEXT:
        return TEXT_MESSAGE
    if kind == MISSED_STORY and not url:
        return LINK_MISSING
    if url and not safe_url(url):
        return LINK_BAD
    return None


def send_request(ws: Workspace, kind: str, text: str, url: str, module: str | None) -> Any:
    """POST /radar/requests through ui.write: toast with the Source finder's next run, undo = withdraw."""
    clock = scout_clock(ws)  # read before the write clears the caches

    def undo(result: Any) -> tuple | None:
        rid = as_int(pick(result, "id", "request.id"))
        if rid is None:
            return None
        return ("Sent a coverage request.",
                lambda token: api.radar_action(ws, token, rid, "reject", note=WITHDRAWN), "Request withdrawn.")

    return ui.write(ws, lambda token: api.add_radar_request(ws, token, kind=kind, text=text, url=url or None,
                                                            module=module or None),
                    toast=sent_toast(clock), undo=undo)


def render_composer(ws: Workspace, module_id: str | None, names: Mapping[str, str]) -> None:
    if st.session_state.pop(RESET_KEY, False):
        st.session_state["rq_text"] = ""
        st.session_state["rq_url"] = ""
    areas = [NOT_SURE] + list(names)
    if "rq_area" not in st.session_state or st.session_state.get(AREA_FOR_KEY) != module_id:
        st.session_state["rq_area"] = module_id if module_id in names else NOT_SURE
        st.session_state[AREA_FOR_KEY] = module_id
    ask = st.segmented_control("What do you want?", list(ASK_CHOICES), key="rq_kind", default=SOURCE_OR_TOPIC,
                               required=True, format_func=lambda k: ASK_CHOICES.get(k, k)) or SOURCE_OR_TOPIC
    with st.form("rq_form", border=True):
        if ask == SOURCE_OR_TOPIC:
            kind = st.radio("It is", list(WHAT_CHOICES), key="rq_what", horizontal=True,
                            format_func=lambda k: labels.RADAR_KIND_LABELS.get(k, k))
        else:
            kind = MISSED_STORY
        text = st.text_area("In your own words", key="rq_text", height=90, max_chars=2000, placeholder=PLACEHOLDERS[ask])
        url = st.text_input("Link", key="rq_url",
                            placeholder="https://… (required)" if ask == MISSED_STORY else "https://… (optional)")
        area = st.selectbox("Coverage area", areas, key="rq_area",
                            format_func=lambda m: "Not sure" if m == NOT_SURE else names.get(m, labels.area_name(m)))
        sent = st.form_submit_button("Send", key="rq_send", type="primary", disabled=not owner.can_edit(ws),
                                     help=labels.LOCKED_HELP if not owner.can_edit(ws) else None)
    ui.locked_hint(ws)
    if sent:
        # "www.utilitydive.com" as people copy it gets https:// in front (WF5 AW-13).
        text, url = one_line(text), api.with_scheme((url or "").strip())
        problem = validate(kind, text, url)
        if problem:
            st.info(problem)
        elif send_request(ws, kind, text, url, area or None) is not None:
            st.session_state[RESET_KEY] = True
            st.rerun()


def withdraw(ws: Workspace, rid: int) -> None:
    """POST /radar/<id>/reject {note: 'withdrawn by owner'}; runs inside the confirmation. No undo."""
    ui.write(ws, lambda token: api.radar_action(ws, token, rid, "reject", note=WITHDRAWN), toast="Withdrawn.")


def render_request(ws: Workspace, row: Mapping, names: Mapping[str, str], focused: bool) -> None:
    rid = as_int(row.get("id"))
    with st.container(border=True, key=f"zx_card_rq_{rid}"):
        st.markdown(request_html(row, names, ws.timezone, focused), unsafe_allow_html=True)
        if stage_of(row) in WITHDRAWABLE:
            if ui.write_button("Withdraw", ws=ws, key=f"rq_withdraw_{rid}", type="tertiary"):
                ui.ask_confirm("Withdraw this request?", "The source finder stops working on it.", "Withdraw",
                               lambda: withdraw(ws, rid), detail=labels.NO_UNDO)


def render_requests(ws: Workspace, module_id: str | None) -> None:
    """Coverage requests, under Coverage's four columns: the composer, then every request, newest first."""
    st.markdown(f'<div id="{REQUESTS_ANCHOR}"></div>', unsafe_allow_html=True)  # Coverage's jump link lands here
    ui.section("Coverage requests")
    st.caption("Ask for a source, a company or a topic, or report a story ZENUX missed. The source finder looks into "
               "it at its next run, and the builder sets up what it finds.")
    names = area_names(ws)
    render_composer(ws, module_id, names)
    try:
        body = data.radar(ws.id)
    except api.ApiError as exc:
        ui.error_box("your coverage requests", exc, key="requests")
        return
    rows = [r for r in unique_by_id(requests_of(body)) if as_int(r.get("id")) is not None]
    if not rows:
        st.markdown(empty_state("No coverage requests yet. Ask above; the source finder answers after its next run."),
                    unsafe_allow_html=True)
        return
    focus = links.focus("request")
    for row in ordered(rows, focus):
        render_request(ws, row, names, focused=as_int(focus) is not None and as_int(row.get("id")) == as_int(focus))
    if pick(body, "has_more") is True:
        total = as_int(pick(body, "total")) or len(rows)
        st.caption(f"The newest {len(rows)} of {plural(total, 'coverage request')} are listed.")


def _request_dialog(workspace_id: str, module_id: str | None = None, company: str = "") -> None:
    """'Request coverage' from Coverage: kind new_coverage, the coverage area preset, the text prefilled with the
    company's name (`company`: a dialog argument may not be called `name`, which is ui.open_dialog's own)."""
    ws = load_config().workspace(workspace_id)
    if ws is None:
        ui.close_dialog()
        return
    names = area_names(ws)
    st.caption("The source finder looks into it at its next run, and the builder sets up what it finds.")
    text = st.text_area("In your own words", key="dlg_text", height=90, max_chars=2000,
                        value=f"Please collect {company}'s own news: its newsroom, filings or contracts." if company else "")
    url = st.text_input("Link (optional)", key="dlg_url", placeholder="https://…")
    areas = [NOT_SURE] + list(names)
    area = st.selectbox("Coverage area", areas, key="dlg_choice", index=areas.index(module_id) if module_id in areas else 0,
                        format_func=lambda m: "Not sure" if m == NOT_SURE else names.get(m, labels.area_name(m)))
    ui.locked_hint(ws)
    save, cancel = st.columns(2)
    with save:
        if ui.write_button("Send", ws=ws, key="dlg_save", type="primary"):
            text, url = one_line(text), (url or "").strip()
            problem = validate("new_coverage", text, url)
            if problem:
                st.info(problem)
            elif send_request(ws, "new_coverage", text, url, area or None) is not None:
                ui.close_dialog()
                st.rerun()
    with cancel:
        if st.button("Cancel", key="dlg_cancel"):
            ui.close_dialog()
            st.rerun()


ui.register_dialog("request", "Request coverage", _request_dialog)


# ---------------------------------------------------------------------------------------------- builder part


def proposal_rows(proposal: dict) -> list[list[str]]:
    rows = []
    shown: set[str] = set()
    source = proposal.get("source") if isinstance(proposal.get("source"), dict) else {}
    merged = {**source, **{k: v for k, v in proposal.items() if not isinstance(v, (dict, list))}}
    for key, label in PROPOSAL_FIELDS:
        value = merged.get(key)
        if value is None or one_line(value) == "" or label in shown:
            continue
        shown.add(label)
        cell = link(value, one_line(value)) if key == "url" and safe_url(value) else esc(one_line(value))
        rows.append([esc(label), cell])
    config = source.get("config") if isinstance(source.get("config"), dict) else None
    if config and config.get("url") and "URL" not in shown:
        rows.append(["URL", link(config["url"], one_line(config["url"]))])
    return rows


def sources_table(proposal: dict) -> str:
    """The Source finder's proposed module source configs, one row each."""
    rows = []
    for src in dicts(proposal.get("sources"))[:50]:
        config = src.get("config") if isinstance(src.get("config"), dict) else {}
        url = pick(src, "url") or pick(config, "url", "feed_url", "base_url", "site")
        rows.append([
            esc(one_line(src.get("module"))), f'<span class="mono">{esc(one_line(src.get("key")))}</span>',
            esc(one_line(src.get("label"))), esc(one_line(src.get("connector"))), esc(one_line(src.get("lane"))),
            esc(one_line(src.get("trust"))), link(url, clip(url, 60)) if safe_url(url) else esc(clip(url, 60)),
        ])
    return table(["Module", "Source key", "Label", "Connector", "Lane", "Trust", "URL"], rows) if rows else ""


def registry_html(proposal: dict) -> str:
    changes = dicts(proposal.get("registry_changes"))
    if not changes:
        return ""
    names = [one_line(pick(c, "name", "entity_id", "id")) for c in changes[:8]]
    names = [n for n in names if n]
    more = f" and {len(changes) - len(names)} more" if len(changes) > len(names) else ""
    listed = f": {esc(', '.join(names))}{esc(more)}" if names else ""
    return f'<div class="refine-note">{esc(plural(len(changes), "registry change"))}{listed}</div>'


def diagnosis_html(proposal: dict, row: Mapping) -> str:
    diag = proposal.get("diagnosis") if isinstance(proposal.get("diagnosis"), Mapping) else {}
    parts = []
    if diag:
        cause = one_line(diag.get("cause")).lower()
        parts.append(f"Diagnosis: {cause or 'unknown'} ({diagnosis_label(cause)})")
        if as_int(diag.get("event_id")) is not None:
            parts.append(f"event #{as_int(diag.get('event_id'))}")
        if one_line(diag.get("suggested_rule")):
            parts.append(f"suggested rule: {clip(diag.get('suggested_rule'), 300)}")
    draft = as_int(row.get("rule_draft_id"))
    if draft is not None:
        parts.append(f"rule draft #{draft} (in the analyst's Needs your OK once worded)")
    return f'<div class="refine-note">{esc(" · ".join(parts))}</div>' if parts else ""


def kind_chip(kind: str) -> str:
    return (f'<span class="loop-kind loop-kind-{esc(kind)}">'
            f'{esc(labels.RADAR_KIND_LABELS.get(kind, label_of(kind)))}</span>')


def review_head(ws: Workspace, row: Mapping, when_field: str = "created_at") -> str:
    rid = row.get("id")
    status = status_of(row)
    return ('<div class="loop-card-head">' + kind_chip(kind_of(row)) + pill(status, css=STATE_CSS.get(status))
            + f'<span class="rule-meta" style="margin-top:0">{esc(ws.id)} #{esc(rid)}'
            + (f' · {esc(row.get("module"))}' if one_line(row.get("module")) else "")
            + f' · {esc(fmt_short(pick(row, when_field, "updated_at", "created_at"), ws.timezone))}</span></div>')


def decide(ws: Workspace, rid: int, action: str, *, note: str = "", proposed_at: Any = api.NOT_SHOWN,
           rerun: bool = True) -> bool:
    """POST /radar/<id>/<approve|reject> with the builder's token. A 409 proposal_changed (the Source finder has a
    newer proposal than the one shown) re-reads the list and says so on that card."""
    token = owner.token(ws)
    if not token:
        st.warning(labels.LOCKED_HELP)
        return False
    try:
        api.radar_action(ws, token, rid, action, note=note or None, proposed_at=proposed_at)
    except api.ApiError as exc:
        if exc.code == PROPOSAL_CHANGED:
            data.clear_reads()
            st.session_state.setdefault(CHANGED_KEY, {})[f"{ws.id}:{rid}"] = (
                f"The source finder has a newer proposal for request #{rid} than the one shown, so nothing was "
                "approved. Review it again below.")
            if rerun:
                st.rerun()
            return False
        ui.show_write_error(exc)  # in place; inside the confirmation it keeps the dialog open
        return False
    data.clear_reads()
    ui.notify(f"Approved request #{rid} for {ws.label}. Set it up with the command under Approved, waiting for setup."
              if action == "approve" else f"Rejected request #{rid} for {ws.label}.")
    if rerun:
        st.rerun()
    return True


def render_review_card(ws: Workspace, row: Mapping) -> None:
    rid = as_int(row.get("id"))
    proposal = proposal_of(row)
    summary = one_line(pick(proposal, "summary", "rationale", "why", "text"))
    with st.container(border=True, key=f"zx_card_rv_{ws.id}_{rid}"):
        changed = (st.session_state.get(CHANGED_KEY) or {}).pop(f"{ws.id}:{rid}", None)
        if changed:
            st.warning(changed)
        details = proposal_rows(proposal)
        st.markdown(
            '<div class="radar-body">' + review_head(ws, row, "proposed_at")
            + f'<div class="refine-label">Asked</div><div class="refine-owner">{esc_lines(row.get("text"))}</div>'
            + (f'<div class="refine-note">{link(row.get("url"), one_line(row.get("url")))}</div>' if row.get("url") else "")
            + '<div class="refine-label">Source finder proposal</div>'
            + (f'<div class="rule-text">{esc(summary)}</div>' if summary
               else '<div class="refine-note">No summary given.</div>')
            + (table(["Field", "Value"], details) if details else "")
            + sources_table(proposal)
            + registry_html(proposal)
            + diagnosis_html(proposal, row)
            + (f'<div class="refine-note">{esc_lines(proposal.get("notes"))}</div>' if one_line(proposal.get("notes")) else "")
            + "</div>",
            unsafe_allow_html=True,
        )
        evidence = as_list(pick(proposal, "evidence", "samples"))
        if proposal:
            with st.expander("Full proposal" + (f" · {len(evidence)} evidence item(s)" if evidence else "")):
                st.json(proposal, expanded=False)
        note = st.text_input("Note (optional)", key=f"rv_note_{ws.id}_{rid}",
                             placeholder="why, or what to change before it is applied")
        approve, reject = st.columns(2)
        with approve:
            if ui.write_button("Approve", ws=ws, key=f"rv_approve_{ws.id}_{rid}", type="primary"):
                # the proposal shown; the hub binds the approval to it
                decide(ws, rid, "approve", note=one_line(note),
                       proposed_at=row.get("proposed_at") if "proposed_at" in row else api.NOT_SHOWN)
        with reject:
            if ui.write_button("Reject", ws=ws, key=f"rv_reject_{ws.id}_{rid}"):
                text = one_line(note)
                ui.ask_confirm(f"Reject request #{rid}?", "The analyst sees it as Not added, with your note.", "Reject",
                               lambda: decide(ws, rid, "reject", note=text, rerun=False),
                               detail=f"Your note: {text}" if text else None)


def sources_state_lines(row: Mapping, tz: str) -> str:
    lines = []
    for src in dicts(row.get("sources")):
        state = one_line(src.get("state"))
        lines.append(f'{esc(one_line(src.get("module")))}/<span class="mono">{esc(one_line(src.get("key")))}</span> '
                     f'{esc(one_line(src.get("label")))}: {pill(state or "unknown", css=STATE_CSS.get(state))}')
    first = first_items_lines(row.get("first_items"), tz)
    return ("".join(f'<div class="refine-note">{line}</div>' for line in lines)
            + (f'<div class="refine-note">First items: {esc(" · ".join(first))}</div>' if first else ""))


def render_review_workspace(ws: Workspace) -> None:
    try:
        body = data.radar(ws.id)
    except api.ApiError as exc:
        st.markdown(empty_state(f"Could not load coverage requests from {ws.label}.", str(exc)), unsafe_allow_html=True)
        return
    rows = ordered([r for r in unique_by_id(requests_of(body)) if as_int(r.get("id")) is not None])
    by_stage: dict[str, list[dict]] = {}
    for row in rows:
        by_stage.setdefault(stage_of(row), []).append(row)
    review, asked, approved = by_stage.get("proposal", []), by_stage.get("asked", []), by_stage.get("approved", [])
    done, rejected = by_stage.get("applied", []) + by_stage.get("live", []), by_stage.get("rejected", [])
    st.caption(f"{ws.label}: {len(review)} to review · {len(asked)} with the Radar scout · {len(approved)} approved, "
               f"waiting for setup · {len(done)} applied or live · {len(rejected)} rejected")
    for row in review:
        render_review_card(ws, row)
    if approved:
        with st.expander(f"{ws.id} · approved, waiting for setup · {len(approved)}", expanded=True):
            st.caption("Run in PowerShell from the repository, then deploy the module it names:")
            for row in approved:
                summary = one_line(pick(proposal_of(row), "summary")) or one_line(row.get("text"))
                st.markdown(f'<div class="radar-body">{review_head(ws, row, "decided_at")}'
                            f'<div class="rule-text">{esc(summary)}</div></div>', unsafe_allow_html=True)
                st.code(APPLY_COMMAND.format(ws=ws.id, id=as_int(row.get("id"))), language="powershell")
    if asked:
        with st.expander(f"{ws.id} · with the Radar scout · {len(asked)}"):
            st.markdown("".join(f'<div class="radar-body">{review_head(ws, r)}'
                                f'<div class="refine-owner">{esc_lines(r.get("text"))}</div></div>' for r in asked),
                        unsafe_allow_html=True)
    if done:
        with st.expander(f"{ws.id} · applied and live · {len(done)}"):
            st.markdown("".join(f'<div class="radar-body">{review_head(ws, r, "applied_at")}'
                                f'<div class="refine-owner">{esc_lines(r.get("text"))}</div>'
                                f'{sources_state_lines(r, ws.timezone)}{diagnosis_html(proposal_of(r), r)}</div>'
                                for r in done), unsafe_allow_html=True)
    if rejected:
        with st.expander(f"{ws.id} · rejected · {len(rejected)}"):
            st.markdown("".join(f'<div class="radar-body">{review_head(ws, r, "decided_at")}'
                                f'<div class="refine-owner">{esc_lines(r.get("text"))}</div>'
                                + (f'<div class="refine-note">Note: {esc(clip(r.get("decision_note"), 300))}</div>'
                                   if one_line(r.get("decision_note")) else "") + "</div>" for r in rejected[:50]),
                        unsafe_allow_html=True)


def render_review(conf) -> None:
    """Coverage requests to review, every workspace (Control room)."""
    st.markdown(section_label("Coverage requests to review", "every workspace"), unsafe_allow_html=True)
    if not conf.workspaces:
        st.markdown(empty_state("No workspace is configured."), unsafe_allow_html=True)
        return
    for ws in conf.workspaces:
        with st.container(key=f"rv_ws_{ws.id}"):
            render_review_workspace(ws)
