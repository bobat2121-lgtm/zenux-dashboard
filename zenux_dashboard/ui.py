"""Shared page furniture: toasts, the undo bar, dialogs, plain errors and locked write buttons
(docs/SPEC-PHASE03-UI.md 1.3 and 3.6).

- **Toasts.** A write queues its toast with notify() and reruns; the shell shows the queue at the top of the next run
  (flush_toasts), so a toast survives st.rerun(). The text says what changed and when it takes effect
  (effective_text, built from the write answer's `effective`). A toast goes away by itself after TOAST_SECONDS
  (Streamlit pauses the countdown while the pointer rests on it, so it can be read; its X closes it at once).
- **Undo.** Toasts cannot hold buttons, so a write the hub can reverse also leaves one pending Undo (offer_undo); the
  shell draws it as a slim bar that floats at the bottom of the screen (undo_bar), so it is in view wherever the
  analyst acted. It lasts until the next write, Dismiss, or UNDO_SECONDS, and belongs to one workspace; a newer write
  that replaces a live Undo says so in a toast, unless that write reversed the very change the Undo would (its `ref`,
  dropped with forget_undo: a story icon clicked again).
- **Dialogs.** One at a time, through the shell: a button calls open_dialog(name, **args), which only stores
  {name, args}; at the end of every run the shell calls render_dialog(), which opens the registered dialog with
  on_dismiss=close_dialog (closing with X or Escape clears it). Save and Cancel call close_dialog() then st.rerun().
  Dialog widget keys start with `dlg_` and are cleared whenever a dialog opens or closes, so one dialog's text never
  shows up in the next.
- **Writes.** write() is the one way to send an owner write: it resolves the owner token (locked: a warning and
  nothing sent), shows a plain error in place on a refusal (the dialog stays open), and on success clears the read
  caches, queues the toast and offers the undo.
- **Errors.** plain_error() turns an ApiError into a plain headline and explanation (hub_sentence: the hub's own
  plain sentence when looks_technical passes it, else the dashboard's words for its code); error_box() draws a
  failed read with a "Try again" button; a failed write reads "Not saved. <headline> <explanation>"; the technical
  line is shown to the builder only, collapsed.
- **Markdown.** Text Streamlit renders as Markdown (toasts, dialog titles, button labels and tooltips, captions and
  errors) goes through fmt.md_label when it may hold hub text, so "$11.9B ... $5" is not typeset as math.
"""

from __future__ import annotations

import logging
import re
import string
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterator, Mapping

import streamlit as st

from . import data, labels, owner
from .api import ApiError
from .config import Workspace, load_config
from .fmt import UTC, MIN_TIME, clock_text, esc, fmt_day, md_label, one_line, parse_time, section_label, zone

LOG = logging.getLogger(__name__)

TOAST_KEY = "zx_toasts"
TOAST_SECONDS = 9  # how long a toast shows before it goes away by itself (the owner's call, 2026-10-05)
TOAST_SLOT_KEY = "zx_toast_slot"  # where the next toast goes (flush_toasts)
TOAST_SLOTS = 12  # toasts take turns over this many places, so a new one never lands where one still shows
TOAST_SPACER = "<style></style>"  # takes a place in Streamlit's event area and no room (flush_toasts)
UNDO_KEY = "zx_undo"
DIALOG_KEY = "zx_dialog"
WRITE_KEY = "zx_last_write"  # "ok" | "failed": what the last ui.write() in this run did (the confirm dialog reads it)
DIALOG_PREFIX = "dlg_"
CONFIRM = "confirm"
UNDO_SECONDS = 600
REPLACED_UNDO = ("Undo now reverses only your newest change. Your earlier change ({earlier}) stays; Tuning lists your "
                 "rules, mutes and watchlist if you want to change it back.")


@dataclass(frozen=True)
class Undo:
    workspace_id: str
    text: str  # what changed, e.g. "Muted Data Center Dynamics."
    run: Callable[[str], Any]  # the inverse call; receives the owner token
    done: str = "Undone."
    expires_at: float = 0.0  # _now() + UNDO_SECONDS, set by offer_undo
    ref: str = ""  # what it reverses ("pref:R-0013"), so a click that reverses it another way can drop it (forget_undo)


def _now() -> float:
    return time.monotonic()


# ---------------------------------------------------------------------------------------------- toasts


def notify(text: str, *, icon: str | None = None) -> None:
    """Queue a toast for the top of the next run (it survives st.rerun())."""
    if not text:
        return
    queue = list(st.session_state.get(TOAST_KEY) or [])
    queue.append((str(text), icon))
    st.session_state[TOAST_KEY] = queue


def flush_toasts() -> None:
    """Shell, top of every run: show and forget the queued toasts. Streamlit draws every toast in its event area and
    skips one drawn at the place of a toast still showing (its delta path; a run's first toast always takes the first
    place there), so a toast right after another (a story icon clicked twice) would be lost. Empty style blocks, which
    Streamlit also puts there and which take no room, move each batch on to the next of TOAST_SLOTS places."""
    queue = st.session_state.pop(TOAST_KEY, None) or []
    if not queue:
        return
    start = as_slot(st.session_state.get(TOAST_SLOT_KEY))
    for _ in range(start):
        st.html(TOAST_SPACER)
    for text, icon in queue:
        st.toast(md_label(text), icon=icon, duration=TOAST_SECONDS)
    st.session_state[TOAST_SLOT_KEY] = (start + len(queue)) % TOAST_SLOTS


def as_slot(value: Any) -> int:
    return value % TOAST_SLOTS if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


# ---------------------------------------------------------------------------------------------- undo


def offer_undo(ws: Workspace, text: str, run: Callable[[str], Any], done: str = "Undone.", ref: str = "") -> None:
    st.session_state[UNDO_KEY] = Undo(workspace_id=ws.id, text=text, run=run, done=done or "Undone.",
                                      expires_at=_now() + UNDO_SECONDS, ref=ref or "")


def clear_undo() -> None:
    st.session_state.pop(UNDO_KEY, None)


def forget_undo(ws: Workspace, refs: set[str]) -> None:
    """Drop the pending Undo, without a word, when it reverses one of `refs`: the change it would undo was just undone
    another way (a glowing story icon clicked again), so there is nothing left for it to do."""
    undo = pending_undo(ws)
    if undo is not None and undo.ref and undo.ref in refs:
        clear_undo()


def pending_undo(ws: Workspace) -> Undo | None:
    """The live undo of this workspace (an expired one is forgotten)."""
    undo = st.session_state.get(UNDO_KEY)
    if not isinstance(undo, Undo):
        return None
    if _now() >= undo.expires_at:
        clear_undo()
        return None
    return undo if undo.workspace_id == ws.id else None


def undo_bar(ws: Workspace) -> None:
    """Shell, top of the content band: "<what changed> · Undo · Dismiss"."""
    undo = pending_undo(ws)
    if undo is None:
        return
    with st.container(key="zx_undo", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f'<div class="zx-undo">{esc(undo.text)}</div>', unsafe_allow_html=True)
        do_undo = write_button("Undo", ws=ws, key="zx_undo_run", type="tertiary", icon=":material/undo:")
        dismiss = st.button("Dismiss", key="zx_undo_dismiss", type="tertiary")
    if dismiss:
        clear_undo()
        st.rerun()
    if do_undo:
        tok = owner.token(ws)
        if tok is None:
            st.warning(labels.LOCKED_HELP)
            return
        try:
            undo.run(tok)
        except ApiError as exc:
            show_write_error(exc)
            return
        data.clear_reads()
        clear_undo()
        notify(undo.done)
        st.rerun()


# ---------------------------------------------------------------------------------------------- effective


def effective_text(effective: Mapping | None, tz: str, *, now: datetime | None = None) -> str:
    """When a change takes effect, from a write answer's `effective` ({applies_from, next_briefing_at, timezone}),
    in the workspace's time zone: "Applies from the 12:30 PM briefing." (today), "Applies from tomorrow's 7:30 AM
    briefing.", "Applies from the Mon Oct 6 7:30 AM briefing.", "Applies from the next briefing." (unknown), or
    "Takes effect once you approve the wording in Tuning." (after_approval)."""
    eff = effective if isinstance(effective, Mapping) else {}
    if eff.get("applies_from") == "after_approval":
        return "Takes effect once you approve the wording in Tuning."
    at = parse_time(eff.get("next_briefing_at"))
    clock = parse_time(now or datetime.now(UTC))
    if at == MIN_TIME or at <= clock:
        return "Applies from the next briefing."
    tzinfo = zone(tz)
    days = (at.astimezone(tzinfo).date() - clock.astimezone(tzinfo).date()).days
    when = clock_text(at, tz)
    if days <= 0:
        return f"Applies from the {when} briefing."
    if days == 1:
        return f"Applies from tomorrow's {when} briefing."
    return f"Applies from the {fmt_day(at, tz)} {when} briefing."


# ---------------------------------------------------------------------------------------------- errors


# Every hub refusal's `message` is one plain sentence (docs/SPEC-PHASE05.md section 1), so it is shown as written once
# looks_technical passes it. HUB_PLAIN holds the dashboard's words for the codes whose sentence an older hub wrote
# with ids or field names: they stand in only when the hub's own sentence fails the guard (or is missing). A refusal
# because the record moved on meanwhile clears the read caches (STALE_CODES); a gone record adds REFRESH_AGAIN.
REFRESH_AGAIN = "Refresh and try again."
HUB_PLAIN = {
    "draft_closed": "This suggestion was already handled meanwhile. Refresh to see where it stands.",
    "radar_closed": "This request has moved on meanwhile (the builder may have approved it). Refresh to see where it "
                    "stands.",
    "superseded": "A newer wording replaced this preference. Change that one instead.",
    "unknown_source": "That source is no longer in your coverage.",
    "unknown_company": "That company is no longer in your coverage.",
    "unknown_story": "That story is no longer available.",
    "unknown_event": "That story is no longer available.",
    "unknown_item": "That story is no longer available.",
    "unknown_edition": "That briefing is no longer available.",
    "unknown_preference": "That preference is no longer available.",
    "unknown_precedent": "That preference is no longer available.",
    "unknown_draft": "That suggestion is no longer available.",
    "unknown_radar_request": "That request is no longer available.",
    "unknown_module": "That coverage area isn't set up in this workspace.",
    "catalog_missing": "Coverage details aren't ready yet. The builder is setting them up.",
}
STALE_CODES = frozenset({"draft_closed", "radar_closed", "superseded", "expired", "closed_by_change", "not_rejected"}
                        | {c for c in HUB_PLAIN if c.startswith("unknown_")})
GONE_CODES = frozenset(c for c in HUB_PLAIN if c.startswith("unknown_") and c != "unknown_module")
_ID_LIKE_RE = re.compile(r"\b[a-z]+(?:-[a-z0-9]+)*-\d+\b")  # a record id used as a name ("ent-coreweave-1")
_TECHNICAL_RE = re.compile(r"[{}]|\b\d{4}-\d{2}-\d{2}\b|\b(?:true|false|null)\b")


def _module_ids() -> set[str]:
    """The configured module ids that cannot be plain words ("ai-infra"; a one-word id such as "coverage" can)."""
    try:
        return {m.id.lower() for w in load_config().workspaces for m in w.modules if "-" in m.id or "_" in m.id}
    except Exception:  # pragma: no cover - secrets that cannot be read
        return set()


def looks_technical(text: Any) -> bool:
    """The last guard on a hub sentence: engine words (labels.find_jargon), a configured module id, a record id used as
    a name ("ent-coreweave-1"), JSON or an ISO date."""
    words = one_line(text)
    if labels.find_jargon(words) or _ID_LIKE_RE.search(words) or _TECHNICAL_RE.search(words):
        return True
    lower = words.lower()
    return any(re.search(rf"(?<![\w-]){re.escape(mid)}(?![\w-])", lower) for mid in _module_ids())


def _ended_on(value: Any) -> str:
    at = parse_time(value)
    return f" on {at:%b} {at.day}, {at.year}" if at != MIN_TIME else ""


def hub_sentence(exc: ApiError) -> str | None:
    """The plain sentence for a refusal, or None (the kind decides then, in plain_error): the hub's own message (or a
    local validation sentence) when it passes looks_technical, else the dashboard's words for its code (HUB_PLAIN,
    the expired sentence)."""
    code = one_line(exc.code)
    detail = one_line(exc.detail)
    if detail and not looks_technical(detail):
        return detail
    if code in HUB_PLAIN:
        return HUB_PLAIN[code]
    if code == "expired":
        return (f"This preference already ended{_ended_on(exc.data.get('expires_at'))}. Bring it back with a new end "
                "date, or none.")
    return None


def plain_error(exc: Exception) -> tuple[str, str | None]:
    """(headline, explanation) for a failed call, in plain words; the technical line stays in str(exc)."""
    if not isinstance(exc, ApiError):
        return ("Something went wrong on this page.",
                "Try again in a minute. If it keeps happening, tell the builder.")
    if exc.kind == "unreachable":
        if str(exc) == "timed out":
            return "ZENITH took too long to answer.", "This is usually brief. Try again in a minute."
        return "ZENITH can't be reached right now.", "This is usually brief. Try again in a minute."
    if exc.kind == "unauthorized":
        return "The dashboard's access was refused.", "Tell the builder: the workspace's keys may have changed."
    if exc.kind == "not_configured":
        return "This workspace isn't fully set up yet.", "Tell the builder."
    if exc.kind == "bad_response":
        return "ZENITH sent an answer the dashboard couldn't read.", "Tell the builder."
    sentence = hub_sentence(exc)
    if sentence:
        gone = one_line(exc.code) in GONE_CODES and REFRESH_AGAIN.casefold() not in sentence.casefold()
        return sentence, REFRESH_AGAIN if gone else None
    if exc.kind == "not_found":
        return "ZENITH couldn't find that. It may have changed meanwhile.", "Refresh and try again."
    if exc.kind == "http" and (exc.status or 0) >= 500:
        return "Something went wrong on the server.", "Try again in a minute."
    return "ZENITH refused that request.", "Tell the builder if it keeps happening."


def write_error_text(exc: Exception) -> str:
    """"Not saved. <plain headline> <its explanation>", e.g. "Not saved. ZENITH can't be reached right now. This is
    usually brief. Try again in a minute." """
    headline, explanation = plain_error(exc)
    return "Not saved. " + headline + (" " + explanation if explanation else "")


def _builder_details(exc: Exception) -> None:
    if not owner.is_builder():
        return
    line = str(exc) if isinstance(exc, ApiError) else f"{type(exc).__name__}: {exc}"
    with st.expander("Details for the builder", expanded=False):
        st.code(line or type(exc).__name__, language=None)


def _forget_stale(exc: Exception) -> None:
    """A refusal because the record moved on meanwhile clears the read caches, so the next run shows where it stands."""
    if isinstance(exc, ApiError) and one_line(exc.code) in STALE_CODES:
        data.clear_reads()


def show_write_error(exc: Exception) -> None:
    """In the current container (inside the dialog): write_error_text (a validation refusal's sentence already names
    the first problem) and, for the builder only, the technical line."""
    st.session_state[WRITE_KEY] = "failed"
    _forget_stale(exc)
    st.error(md_label(write_error_text(exc)))
    if isinstance(exc, ApiError) and exc.detail and hub_sentence(exc) is None and owner.is_builder():
        st.caption(md_label("ZENITH said: " + one_line(exc.detail)))  # the builder reads the engine's own sentence
    _builder_details(exc)


def toast_write_error(exc: Exception) -> None:
    """A write that ran in a button callback (a menu item): its error goes into a toast, which shows wherever the
    analyst is scrolled (anything drawn in a callback lands at the top of the page)."""
    st.session_state[WRITE_KEY] = "failed"
    _forget_stale(exc)
    notify(write_error_text(exc), icon=":material/error:")


def error_box(what: str, exc: Exception, *, key: str) -> None:
    """A failed read: "Couldn't load {what}." with a plain headline and explanation, a "Try again" button
    (zx_retry_{key}: clears the read caches, reruns) and, for the builder only, the technical line (collapsed)."""
    headline, explanation = plain_error(exc)
    body = esc(headline) + (" " + esc(explanation) if explanation else "")
    with st.container(key=f"zx_error_{key}"):
        st.markdown(f'<div class="zx-error"><div class="zx-error-title">Couldn&#x27;t load {esc(what)}.</div>'
                    f'<div class="zx-error-text">{body}</div></div>', unsafe_allow_html=True)
        retry = st.button("Try again", key=f"zx_retry_{key}", icon=":material/refresh:")
        _builder_details(exc)
    if retry:
        data.clear_reads()
        st.rerun()


# ---------------------------------------------------------------------------------------------- writes


def write(ws: Workspace, call: Callable[[str], Any], *, toast: str | Callable[[Any], str],
          undo: Callable[[Any], tuple | None] | None = None, in_callback: bool = False) -> Any | None:
    """The one way to send an owner write. Locked: st.warning(LOCKED_HELP), nothing sent, None. ApiError: a plain
    error in the current container (the dialog stays open), None. Success: the read caches are cleared, the toast is
    queued (toast, or toast(result)), undo(result) -> (text, run), (text, run, done) or (text, run, done, ref) is
    offered (else any older undo is cleared), each string in result["warnings"] is queued as one more toast, and the
    result is returned. The caller then closes its dialog and calls st.rerun(). in_callback (a write run in its
    button's callback: a menu item, a story icon): the lock or the error is said in a toast instead, since anything
    drawn in a callback lands at the top of the page."""
    tok = owner.token(ws)
    if tok is None:
        st.session_state[WRITE_KEY] = "failed"
        if in_callback:
            notify(labels.LOCKED_HELP, icon=":material/lock:")
        else:
            st.warning(labels.LOCKED_HELP)
        return None
    try:
        result = call(tok)
    except ApiError as exc:
        (toast_write_error if in_callback else show_write_error)(exc)
        return None
    st.session_state[WRITE_KEY] = "ok"
    data.clear_reads()
    try:
        text = toast(result) if callable(toast) else toast
    except Exception:  # a toast that cannot be built never hides a saved write
        LOG.exception("toast text failed")
        text = "Saved."
    earlier = pending_undo(ws)
    clear_undo()
    pair = None
    if undo is not None:
        try:
            pair = undo(result)
        except Exception:
            LOG.exception("undo offer failed")
            pair = None
    notify(text or "Saved.")
    if pair:
        offer_undo(ws, *tuple(pair)[:4])
    if earlier is not None:
        # Only the newest change has an Undo button; say so instead of silently dropping the earlier one.
        notify(REPLACED_UNDO.format(earlier=one_line(earlier.text).rstrip(".")))
    warnings = result.get("warnings") if isinstance(result, Mapping) else None
    for warning in warnings if isinstance(warnings, list) else []:
        if isinstance(warning, str) and warning.strip():
            notify(warning.strip())
    return result


def write_button(label: str, *, ws: Workspace, key: str, type: str = "secondary", help: str | None = None,
                 icon: str | None = None, width: str = "content", on_click: Callable[..., Any] | None = None,
                 args: tuple | None = None, kwargs: dict | None = None, locked_help: str | None = None) -> bool:
    """st.button for a write: drawn disabled with LOCKED_HELP (or `locked_help`: a story icon's tooltip keeps its words,
    since the icon shows none) while this session cannot edit ws. The label and help may hold hub text (a company or
    source name), so both are Markdown-escaped (fmt.md_label). on_click/args/kwargs pass through (a menu item runs its
    action in the callback; see menu_item)."""
    locked = not owner.can_edit(ws)
    tip = (locked_help or labels.LOCKED_HELP) if locked else help
    return st.button(md_label(label), key=key, type=type, help=md_label(tip) if tip else None, icon=icon, width=width,
                     disabled=locked, on_click=on_click, args=args, kwargs=kwargs)


def _run_menu_item(popover_key: str, action: Callable[..., Any], args: tuple, kwargs: dict) -> None:
    st.session_state[popover_key] = False  # a callback runs before the popover is drawn again, so it may close it
    action(*args, **kwargs)


def menu_item(label: str, *, ws: Workspace, key: str, popover_key: str, action: Callable[..., Any], args: tuple = (),
              kwargs: dict | None = None, help: str | None = None) -> None:
    """A write button inside a lazy popover (`on_change="rerun"`, key `popover_key`). Clicking it closes the popover
    and runs `action(*args, **kwargs)` in the button's callback, so the dialog it opens is not drawn under a popover
    that stays open. The action must be callback-safe: open a dialog (ui.open_dialog) or write through ui.write
    without st.rerun (the app reruns after every callback)."""
    write_button(label, ws=ws, key=key, type="tertiary", help=help, on_click=_run_menu_item,
                 args=(popover_key, action, tuple(args), dict(kwargs or {})))


def locked_hint(ws: Workspace) -> None:
    """A lock caption while this session cannot edit ws; nothing otherwise."""
    if not owner.can_edit(ws):
        st.caption(":material/lock: " + labels.LOCKED_HELP)


# ---------------------------------------------------------------------------------------------- dialogs

_DIALOGS: dict[str, tuple[Any, Callable[..., None], str]] = {}


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return ""


def register_dialog(name: str, title: str | Callable[..., str], body: Callable[..., None], *,
                    width: str = "medium") -> None:
    """Register a dialog at import time. title is a string, which may name the open_dialog() arguments as
    {placeholders} ("Mute {label}?"), or a callable that receives those arguments and returns the title."""
    _DIALOGS[name] = (title, body, width)


def _clear_dialog_widgets() -> None:
    for key in [k for k in st.session_state.keys() if isinstance(k, str) and k.startswith(DIALOG_PREFIX)]:
        try:
            del st.session_state[key]
        except Exception:  # pragma: no cover - a key Streamlit no longer holds
            pass


def open_dialog(name: str, /, **args: Any) -> None:
    """Ask the shell to open dialog `name` with args at the end of this run (no rerun needed when called before
    render_dialog; call st.rerun() when the dialog should replace the one that is open). `name` is positional only,
    so an argument may itself be called name."""
    _clear_dialog_widgets()
    st.session_state[DIALOG_KEY] = {"name": name, "args": dict(args)}


def close_dialog() -> None:
    st.session_state.pop(DIALOG_KEY, None)
    _clear_dialog_widgets()


def open_dialog_name() -> str | None:
    pending = st.session_state.get(DIALOG_KEY)
    return pending.get("name") if isinstance(pending, dict) else None


def _title(title: Any, args: Mapping[str, Any]) -> str:
    if callable(title):
        return str(title(**args))
    text = str(title)
    if "{" not in text:
        return text
    try:
        return string.Formatter().vformat(text, (), _Blank({k: "" if v is None else v for k, v in args.items()}))
    except (ValueError, IndexError, AttributeError):
        return text


def render_dialog() -> None:
    """Shell, end of every run: open the pending dialog, if any."""
    pending = st.session_state.get(DIALOG_KEY)
    if not isinstance(pending, dict):
        return
    entry = _DIALOGS.get(pending.get("name"))
    if entry is None:
        close_dialog()
        return
    title, body, width = entry
    args = pending.get("args") if isinstance(pending.get("args"), dict) else {}

    def run_body(**kwargs: Any) -> None:
        try:
            body(**kwargs)
        except Exception as exc:  # a broken dialog shows a plain error, never a traceback
            note_crash(exc)
            error_box("this window", exc, key="dialog")

    st.dialog(md_label(_title(title, args)), width=width, on_dismiss=close_dialog)(run_body)(**args)


def note_crash(exc: Exception) -> None:
    """Remember an unexpected exception the page turned into an error box (logged; the tests fail on it)."""
    LOG.error("page error: %s", "".join(traceback.format_exception(exc)))
    st.session_state["zx_page_crash"] = "".join(traceback.format_exception(exc))[-4000:]


def _confirm_body(title: str = "", message: str = "", confirm_label: str = "Confirm",
                  on_confirm: Callable[[], Any] | None = None, danger: bool = True, detail: str | None = None) -> None:
    st.markdown(f'<div class="zx-confirm{" danger" if danger else ""}">{esc(message)}</div>', unsafe_allow_html=True)
    if detail:
        st.caption(md_label(detail))
    with st.container(horizontal=True, gap="small"):
        confirm = st.button(confirm_label, key="dlg_save", type="primary")
        cancel = st.button("Cancel", key="dlg_cancel")
    if cancel:
        close_dialog()
        st.rerun()
    if confirm:
        st.session_state.pop(WRITE_KEY, None)
        if on_confirm is not None:
            on_confirm()
        if st.session_state.get(WRITE_KEY) == "failed":
            return  # the plain error is drawn in the dialog; it stays open
        close_dialog()
        st.rerun()


register_dialog(CONFIRM, lambda **args: str(args.get("title") or "Are you sure?"), _confirm_body, width="small")


def ask_confirm(title: str, message: str, confirm_label: str, on_confirm: Callable[[], Any], *, danger: bool = True,
                detail: str | None = None) -> None:
    """Open the built-in confirmation: the message, an optional detail caption, [confirm_label] (primary) and
    [Cancel]. Confirm runs on_confirm() (normally a ui.write), then closes and reruns; when that write failed, its
    plain error stays in the dialog."""
    open_dialog(CONFIRM, title=title, message=message, confirm_label=confirm_label, on_confirm=on_confirm,
                danger=danger, detail=detail)


# ---------------------------------------------------------------------------------------------- small pieces


def refresh_button(key: str) -> None:
    """A small "Refresh" (zx_refresh_{key}): clears the read caches and reruns."""
    if st.button("Refresh", key=f"zx_refresh_{key}", type="tertiary", icon=":material/refresh:"):
        data.clear_reads()
        st.rerun()


@contextmanager
def filters(active: int = 0, *, key: str) -> Iterator[None]:
    """The one "Filters" popover of a tab ("Filters · 2 on" when some are set)."""
    label = f"Filters · {active} on" if active else "Filters"
    with st.popover(label, key=key, icon=":material/tune:"):
        yield


def section(title: str, aside: str = "") -> None:
    st.markdown(section_label(title, aside), unsafe_allow_html=True)


def local_today(tz: str) -> date:
    """Today's date in the workspace's time zone (date inputs default from it)."""
    return datetime.now(UTC).astimezone(zone(tz)).date()


def local_midnight_iso(day: date, tz: str) -> str:
    """An end date as the hub takes it: local midnight of `day` in tz, as UTC ISO ("2026-11-03T05:00:00.000Z")."""
    at = datetime(day.year, day.month, day.day, tzinfo=zone(tz)).astimezone(UTC)
    return at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
