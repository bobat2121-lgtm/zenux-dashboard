"""What ZENITH looks for: the analyst's one-pager in plain sections, "Suggest a change", and the sign-off
(docs/SPEC-PHASE03-UI.md section 7.4). Drawn by coverage_view at the top of Coverage, above the coverage-area picker
(docs/SPEC-SIMPLIFY.md 2.4): one expander titled with its sign-off state ("What ZENITH looks for · signed off by you on
Oct 3" / "· not signed off yet"), open while the workspace is staging, under the staging banner.

    GET  /brief           (READ_TOKEN)  sections -> parts -> lines {id, text}, in the approved vocabulary (Top story,
                                        In the briefing, Near miss, Your coverage ...; the hub maps the rubric's words
                                        and keeps them in `original`, docs/SPEC-PHASE05.md 3.1), the sign-off and the
                                        stage
    POST /brief/suggest   (OWNER_TOKEN) {line_id, text}: a draft for the wording assistant; it comes back under Needs
                                        your OK in Tuning (404 unknown_line when the line left the page)
    POST /signoff         (OWNER_TOKEN) {rubric_version, catalog_versions, note?}: the versions of the brief as drawn
                                        (409 changed_since_viewed: re-read and ask again; 409 catalog_missing)

The sign-off sends exactly the versions the analyst was looking at (the cached read that drew the page), so a change
made meanwhile is refused by the hub rather than signed off unseen. Neither write has an undo route (gap 8).

Right after the "Your coverage" section, company_map_view draws "Your companies' big names" from the same read (its
`companies` block, docs/SPEC-COMPANY-MAP.md 6.1), with its own Suggest a change per company.

`write_or_handle` is ui.write for a write whose particular refusals (a 409 that needs its own plain message) the caller
answers itself; tuning_view uses it for approvals.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

import streamlit as st

from . import api, company_map_view, data, labels, ui
from .config import Workspace, load_config
from .fmt import clip, dicts, empty_state, esc, fmt_clock, fmt_date, fmt_day, md_label, one_line, pick

NOTICE_KEY = "br_notice"
SUGGEST_MIN = 10
SUGGEST_MAX = 2000
NOTE_MAX = 500
LINE_CLIP = 120

STAGING_BANNER = ("ZENITH is collecting but not publishing yet. Read What ZENITH looks for and your coverage below, "
                  "then sign off to start your briefings.")
LABEL = "What ZENITH looks for"
CONFIRM = "Sign off on what ZENITH looks for and your coverage? This records the versions you are looking at."
CONFIRM_STAGING = "Your briefings start at the next scheduled time."
CHANGED = "Coverage or this page changed while you were reading. It has been reloaded; look again and sign off."
UNKNOWN_LINE = "This page changed; reload and try again."
SUGGEST_SENT = "Sent to the wording assistant. It comes back in Tuning, under Needs your OK, for you to approve."
SUGGEST_SHORT = f"Write at least {SUGGEST_MIN} characters so the wording assistant knows what to change."
NOT_SIGNED = "Not signed off yet. Read below and press Sign off when it matches what you want."
EMPTY_BRIEF = "What ZENITH looks for isn't ready yet. The builder is setting it up."


class Handled(Exception):
    """An ApiError the caller answers itself. Not an ApiError, so ui.write lets it pass instead of drawing it."""

    def __init__(self, exc: api.ApiError):
        super().__init__(str(exc))
        self.exc = exc


def write_or_handle(ws: Workspace, call: Callable[[str], Any], *, toast: str | Callable[[Any], str],
                    codes: Iterable[str], undo: Callable[[Any], Any] | None = None, in_callback: bool = False
                    ) -> tuple[Any | None, api.ApiError | None]:
    """ui.write, except that a refusal whose hub code is in `codes` comes back to the caller instead of being drawn
    as an error. in_callback: as ui.write's (a button callback says the lock or an error in a toast). -> (result or
    None, the refusal or None)."""
    wanted = set(codes)
    caught: list[api.ApiError] = []

    def guarded(token: str) -> Any:
        try:
            return call(token)
        except api.ApiError as exc:
            if exc.code in wanted:
                caught.append(exc)
                raise Handled(exc) from None
            raise

    try:
        result = ui.write(ws, guarded, toast=toast, undo=undo, in_callback=in_callback)
    except Handled:
        result = None
    return (None, caught[0]) if caught else (result, None)


# ---------------------------------------------------------------------------------------------- pure helpers


def signoff_status(brief: Any, tz: str) -> str:
    """The last sign-off in plain words."""
    last = pick(brief, "signoff.last")
    if not isinstance(last, Mapping):
        return NOT_SIGNED
    by = one_line(last.get("by")).lower()
    at = last.get("signed_at")
    if by == "owner":
        return f"Approved by you on {fmt_day(at, tz)} {fmt_clock(at, tz)}."
    if by == "migration":
        # WF5 AW-11: no builder history; say what to do.
        return "Briefings are running, but you haven't approved this page yet. Read below and press Sign off again."
    if by == "admin":
        return f"Signed off by the builder on {fmt_date(at, tz)}."
    return f"Signed off on {fmt_date(at, tz)}." if at else NOT_SIGNED


def is_staging(brief: Any) -> bool:
    return one_line(pick(brief, "stage")).lower() == "staging"


def section_lines(part: Mapping) -> list[dict]:
    """A part's lines that can be suggested on: {id, text}, both present."""
    return [{"id": one_line(line.get("id")), "text": one_line(line.get("text"))}
            for line in dicts(part.get("lines")) if one_line(line.get("id")) and one_line(line.get("text"))]


def part_title(part: Mapping) -> str:
    return one_line(pick(part, "title", "kind")).replace("_", " ")


def part_html(part: Mapping, heading: str = "") -> str:
    """One part as a headed list; the part's title is left out when it only repeats the section heading."""
    title = part_title(part)
    if title and title.casefold() == one_line(heading).casefold():
        title = ""
    lines = [one_line(line.get("text")) for line in dicts(part.get("lines")) if one_line(line.get("text"))]
    return ('<div class="brief-part">' + (f'<div class="refine-label">{esc(title)}</div>' if title else "")
            + '<ul class="brief-lines">' + "".join(f'<li class="brief-line">{esc(line)}</li>' for line in lines)
            + "</ul></div>")


def expander_label(brief: Any, tz: str) -> str:
    """The expander's title with the sign-off state: 'What ZENITH looks for · signed off by you on Oct 3', '· signed
    off by the builder on Oct 3', or '· not signed off yet' (also while briefings run on a sign-off recorded when the
    workspace was set up, which the analyst has not given yet)."""
    last = pick(brief, "signoff.last")
    if isinstance(last, Mapping):
        by = one_line(last.get("by")).lower()
        day = fmt_date(last.get("signed_at"), tz)
        known = day not in ("", "—")
        if by == "owner" and known:
            return f"{LABEL} · signed off by you on {day}"
        if by == "admin" and known:
            return f"{LABEL} · signed off by the builder on {day}"
        if by not in ("owner", "admin", "migration") and known:
            return f"{LABEL} · signed off on {day}"
    return f"{LABEL} · not signed off yet"


def catalog_missing_text(exc: api.ApiError) -> str:
    """The sign-off refusal for coverage details not set up yet, in the dashboard's words (the hub's sentence names
    module ids and "the next deploy"): "Coverage details for AI infrastructure aren't ready yet. The builder is
    setting them up; sign off once they appear." """
    body = getattr(exc, "data", None)
    modules = body.get("modules") if isinstance(body, Mapping) and isinstance(body.get("modules"), list) else []
    names = [labels.area_name(m) for m in (one_line(m) for m in modules) if m]
    area = " and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " and " + names[-1]
    return (f"Coverage details{' for ' + area if area else ''} aren't ready yet. The builder is setting them up; sign "
            "off once they appear.")


def signed_off_toast(answer: Any, staging: bool, tz: str) -> str:
    if not staging:
        return "Signed off."
    at = pick(answer, "effective.next_briefing_at")
    clock = fmt_clock(at, tz) if at else ""
    when = f"Briefings start at {clock}." if clock and clock != "—" else "Briefings start at the next scheduled time."
    return f"Signed off. {when}"


def workspace_of(workspace_id: Any) -> Workspace | None:
    return load_config().workspace(one_line(workspace_id))


def close_and_rerun() -> None:
    ui.close_dialog()
    st.rerun()


# ---------------------------------------------------------------------------------------------- the section


def render_brief(ws: Workspace) -> None:
    """The staging banner (while ZENITH collects but does not publish yet) and the expander: the sign-off line with
    Sign off, then the page's sections, each part with Suggest a change. Open while staging."""
    notice = st.session_state.pop(NOTICE_KEY, None)
    if notice:
        st.warning(notice)
    try:
        brief = data.brief(ws.id)
    except api.ApiError as exc:
        ui.error_box("what ZENITH looks for", exc, key="brief")
        return
    brief = brief if isinstance(brief, Mapping) else {}
    staging = is_staging(brief)
    if staging:
        st.info(STAGING_BANNER)
    with st.container(key="zx_brief"):
        with st.expander(expander_label(brief, ws.timezone), expanded=staging or bool(notice)):
            render_body(ws, brief, staging)


def render_body(ws: Workspace, brief: Mapping, staging: bool) -> None:
    with st.container(horizontal=True, key="zx_brief_signoff", vertical_alignment="center", gap="small"):
        st.markdown(f'<div class="pref-meta">{esc(signoff_status(brief, ws.timezone))}</div>', unsafe_allow_html=True)
        if ui.write_button("Sign off" if staging else "Sign off again", ws=ws, key="br_signoff",
                           type="primary" if staging else "secondary"):
            ui.open_dialog("signoff", workspace_id=ws.id, rubric_version=brief.get("rubric_version"),
                           catalog_versions=dict(brief.get("catalog_versions") or {}), staging=staging)
    title = one_line(brief.get("title"))
    if title:
        st.markdown(f'<div class="brief-title">{esc(title)}</div>', unsafe_allow_html=True)
    sections = dicts(brief.get("sections"))
    if not sections:
        st.markdown(empty_state(EMPTY_BRIEF), unsafe_allow_html=True)
    names_drawn = False
    for index, section in enumerate(sections):
        section_id = one_line(section.get("id")) or f"s{index}"
        heading = one_line(section.get("heading"))
        if heading:
            st.markdown(f'<div class="rules-section">{esc(heading)}</div>', unsafe_allow_html=True)
        for n, part in enumerate(dicts(section.get("parts"))):
            st.markdown(part_html(part, heading), unsafe_allow_html=True)
            lines = section_lines(part)
            if lines and ui.write_button("Suggest a change", ws=ws, key=f"br_suggest_{section_id}_{n}",
                                         type="tertiary"):
                ui.open_dialog("brief_suggest", workspace_id=ws.id, section=heading, part=part_title(part),
                               lines=lines)
        if not names_drawn and company_map_view.follows(section):
            company_map_view.render(ws, brief)  # "Your companies' big names" (docs/SPEC-COMPANY-MAP.md 6.1)
            names_drawn = True
    if not names_drawn:
        company_map_view.render(ws, brief)
    ui.locked_hint(ws)


# ---------------------------------------------------------------------------------------------- dialogs


def suggest_dialog(workspace_id: str, section: str = "", part: str = "", lines: list | None = None) -> None:
    """Suggest a change to one line; the wording assistant words it and it comes back under Needs your OK."""
    ws = workspace_of(workspace_id)
    if ws is None:
        st.error("This workspace is no longer configured. Close this and reload the page.")
        return
    rows = [line for line in (lines or []) if isinstance(line, Mapping) and one_line(line.get("id"))]
    texts = {one_line(line.get("id")): one_line(line.get("text")) for line in rows}
    where = " › ".join(p for p in (one_line(section), one_line(part)) if p)
    if where:
        st.caption(md_label(where))
    line_id = st.selectbox("Which line?", list(texts), key="dlg_choice",
                           format_func=lambda i: clip(texts.get(i, ""), LINE_CLIP))
    text = st.text_area("How should it read?", key="dlg_text", height=110, max_chars=SUGGEST_MAX)
    with st.container(horizontal=True):
        send = ui.write_button("Send", ws=ws, key="dlg_save", type="primary")
        cancel = st.button("Cancel", key="dlg_cancel")
    if cancel:
        close_and_rerun()
    if not send:
        return
    clean = (text or "").strip()
    if len(one_line(clean)) < SUGGEST_MIN or not line_id:
        st.info(SUGGEST_SHORT)
        return
    result, handled = write_or_handle(ws, lambda token: api.suggest_brief_change(ws, token, line_id, clean),
                                      toast=SUGGEST_SENT, codes=("unknown_line",))
    if handled is not None:
        data.clear_reads()
        st.session_state[NOTICE_KEY] = UNKNOWN_LINE
        close_and_rerun()
    if result is not None:
        close_and_rerun()


def signoff_dialog(workspace_id: str, rubric_version: Any = None, catalog_versions: Mapping | None = None,
                   staging: bool = False) -> None:
    """Sign off on the versions that were drawn; a change meanwhile is refused and the page re-read."""
    ws = workspace_of(workspace_id)
    if ws is None:
        st.error("This workspace is no longer configured. Close this and reload the page.")
        return
    st.markdown(esc(CONFIRM + (" " + CONFIRM_STAGING if staging else "")))
    note = st.text_input("Note (optional)", key="dlg_text", max_chars=NOTE_MAX)
    with st.container(horizontal=True):
        save = ui.write_button("Sign off", ws=ws, key="dlg_save", type="primary")
        cancel = st.button("Cancel", key="dlg_cancel")
    if cancel:
        close_and_rerun()
    if not save:
        return
    versions = dict(catalog_versions or {})
    result, handled = write_or_handle(
        ws, lambda token: api.sign_off(ws, token, rubric_version=rubric_version, catalog_versions=versions,
                                       note=one_line(note) or None),
        toast=lambda answer: signed_off_toast(answer, staging, ws.timezone),
        codes=("changed_since_viewed", "catalog_missing"))
    if handled is not None:
        if handled.code == "changed_since_viewed":
            data.clear_reads()
            st.session_state[NOTICE_KEY] = CHANGED
            close_and_rerun()
        st.error(md_label("Not saved. " + catalog_missing_text(handled)))
        return
    if result is not None:
        close_and_rerun()


ui.register_dialog("brief_suggest", "Suggest a change", suggest_dialog, width="medium")
ui.register_dialog("signoff", "Sign off", signoff_dialog, width="small")
