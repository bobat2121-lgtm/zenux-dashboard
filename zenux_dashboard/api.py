"""HTTP client for the Zenith hub and module Workers.

Plain functions over `requests` (no Streamlit calls), so they also run in worker threads. Tokens travel only in
the Authorization header, never in a URL, and no error carries a token, a header or a URL query: `str(exc)` is a
short technical line for the builder, and `detail` is the hub's own plain sentence (`{error, message, ...}`).

Hub routes (docs/SPEC-PHASE02.md section 5 for the shapes, docs/SPEC-PHASE05.md for the WF5 ones;
docs/SPEC-PHASE03-UI.md 3.3 for these wrappers; docs/SPEC-REPAIR-PHASE-B.md 1.2 and 1.4 for the source repairs):
    reads  (bearer READ_TOKEN):  GET /editions, /editions/<id>, /editions/latest, /editions/search, /status,
                                 /rejected (also ?edition_id=), /modules, /modules/<id>/inspect, /mutes, /mutes/preview,
                                 /mutes/bring-back-preview, /stars, /stars/preview, /preferences, /rules, /settings,
                                 /settings/volume/preview, /brief, /radar, /repairs, /tuneup, /diagnostics, /snapshot,
                                 /sources, /companies/suggestions (docs/SPEC-COMPANY-MAP.md 5.2)
    writes (bearer OWNER_TOKEN): POST /preferences, /rules/<id>/<action> (reopen undoes turning a suggestion down),
                                 /feedback, /feedback/withdraw, /mutes, /stars, /promote, /promote/withdraw
                                 (docs/SPEC-ICON-ACTIONS.md), /settings/volume, /brief/suggest, /signoff,
                                 /tuneup/dismiss, /admin/stage, /admin/routines/allow-once, /radar/requests,
                                 /radar/<id>/{approve|reject}, /repairs/<id>/{approve|reject|withdraw},
                                 /admin/sources/{ack|unack}, /companies/suggestions and
                                 /companies/suggestions/<id>/{approve|reject|withdraw} (docs/SPEC-COMPANY-MAP.md 5.2)
The schema 11 routes (docs/SPEC-SIMPLIFY.md section 1: /rejected?edition_id=, /tuneup, /tuneup/dismiss,
/admin/routines/allow-once) answer 404 on an older hub; the callers treat that as "not there yet".

A hub refusal is {error, message, ...details}: `message` is one plain sentence (docs/SPEC-PHASE05.md section 1), so
`detail` can be shown as written once ui.looks_technical passes it; `data` keeps the details (`fields` on a validation
error, the ids on a not-found or conflict refusal).
Module routes (packages/module-sdk/src/worker.js), bearer RUN_TOKEN:
    GET /health (the detailed body with the token; liveness only {ok, service, module, workspace, version} without),
    GET /backfill (404 no_backfill_job) and POST /backfill {days, sources?, ignore_seen?} (202 new job, 200 job in
    flight)

Every write wrapper validates its arguments before sending anything and raises ApiError("invalid", <plain sentence>)
on a bad one, so a refused write never reaches the hub.
"""

from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import quote

import requests

from . import USER_AGENT
from .config import MODULE_ID_RE, Module, Workspace
from .fmt import safe_url

TIMEOUT = (5, 15)  # connect, read (seconds)
SOURCE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
RULE_ID_RE = re.compile(r"^(?:\d{1,9}|[RI]-\d{4,9})$")
MAX_MESSAGE = 160
DETAIL_MAX = 300
ERROR_ITEM_MAX = 200
ERRORS_MAX = 20
ACK_NOTE_MAX = 500
TEXT_MAX = 500  # preference text and notes (hub PREFERENCE_LIMITS)
TEXT_MIN = 10
LONG_TEXT_MAX = 2000

RULE_ACTIONS = ("approve", "reject", "retire", "pause", "resume", "edit", "end-date", "reactivate", "reopen")
DIRECTIONS = ("more", "less", "exact")
SCOPES = ("this_story", "similar", "standing")
VERDICTS = ("lead", "digest", "watch", "reject", "factual_error")
FEEDBACK_SCOPES = ("item", "case", "rule")
MUTE_KINDS = ("source", "entity", "story", "outlet")  # outlet (WF5): one outlet behind a news-search source
VOLUME_MODES = ("top", "standard", "broad")
STAGES = ("staging", "live")
RADAR_KINDS = ("track_source", "missed_story", "new_coverage")
REPAIR_ACTIONS = ("approve", "reject", "withdraw")  # POST /repairs/<id>/<action>; no route reverses one
ROUTINE_ROLES = ("grader", "refiner", "scout")  # POST /admin/routines/allow-once {role}
# POST /companies/suggestions (docs/SPEC-COMPANY-MAP.md 5.2): the columns of a company sheet, what a suggestion does,
# and the sheet's lengths (a name 60, a note 140, a big customer's reason 80)
COMPANY_COLUMNS = ("products", "units", "customers", "read_through")
COMPANY_CHANGES = ("add", "remove", "change")
COMPANY_ACTIONS = ("approve", "reject", "withdraw")  # POST /companies/suggestions/<id>/<action>; none is reversed
COMPANY_USES = ("proposal", "as_typed")  # an approval writes the source finder's version, or the analyst's words
COMPANY_STATUSES = ("queued", "proposed", "approved", "applied", "live", "rejected", "withdrawn")
SUGGESTION_ID_RE = re.compile(r"^CS-[0-9a-f]{8}$", re.IGNORECASE)
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,9}$")
COMPANY_NAME_MAX = 60
COMPANY_NOTE_MAX = 140
COMPANY_REASON_MAX = 80
REJECTED_FILTERS = ("all", "near_miss", "same_story", "muted", "old_news", "auto")
REJECTED_LIMIT = 500        # the hub's page size cap for GET /rejected (BRAIN_LIMITS.rejectedMax)
SEARCH_DAYS = 90            # GET /editions/search looks this far back by default
SEARCH_LIMIT = 50

NOT_SHOWN = object()  # sentinel: "no proposed_at key at all" (an approval of a draft with no proposal sends null)


class ApiError(Exception):
    """kind: not_configured | unreachable | unauthorized | not_found | http | bad_response | invalid.

    detail: the hub's `message` (one plain sentence, clipped to 300 characters) or None; errors: the hub's `errors`
    list (strings, each clipped to 200), [] when absent; data: the decoded error body (e.g. {"current": {...}} for
    changed_since_viewed, {"mute_id": 4} for mute_active). For kind "invalid" (local validation) detail is the plain
    sentence that was raised."""

    def __init__(self, kind: str, message: str, status: int | None = None, code: str | None = None, *,
                 detail: str | None = None, errors: list[str] | None = None, data: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.code = code
        self.detail = detail if detail is not None else (message if kind == "invalid" else None)
        self.errors = list(errors or [])
        self.data = dict(data or {})

    def __str__(self) -> str:  # the message only; never a header, token or body
        return self.args[0] if self.args else self.kind


def _clip(text: Any, limit: int = MAX_MESSAGE) -> str:
    out = " ".join(str(text or "").split())
    return out if len(out) <= limit else out[: limit - 1] + "…"


def _headers(token: str | None, has_body: bool) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if has_body:
        headers["Content-Type"] = "application/json"
    return headers


def _error_fields(data: Any) -> dict[str, Any]:
    """The plain sentence, the errors list and the body of a hub refusal {error, message, errors?, ...}."""
    if not isinstance(data, dict):
        return {"detail": None, "errors": [], "data": {}}
    message = data.get("message")
    detail = _clip(message, DETAIL_MAX) if isinstance(message, str) and message.strip() else None
    raw = data.get("errors")
    errors = [_clip(e, ERROR_ITEM_MAX) for e in raw[:ERRORS_MAX] if isinstance(e, str) and e.strip()] \
        if isinstance(raw, list) else []
    return {"detail": detail, "errors": errors, "data": data}


def request_json(method: str, url: str, *, token: str | None = None, params: dict | None = None,
                 body: Any = None, accept_status: Iterable[int] = (), timeout=TIMEOUT, with_status: bool = False) -> Any:
    """One JSON call. Raises ApiError; returns the decoded body (also for a status listed in accept_status), or
    (status, body) with with_status."""
    try:
        if method == "GET":
            response = requests.get(url, params=params or None, headers=_headers(token, False), timeout=timeout)
        else:
            response = requests.post(url, params=params or None, json=body if body is not None else {},
                                     headers=_headers(token, True), timeout=timeout)
    except requests.Timeout:
        raise ApiError("unreachable", "timed out") from None
    except requests.RequestException as exc:
        raise ApiError("unreachable", f"unreachable ({type(exc).__name__})") from None
    status = int(getattr(response, "status_code", 0) or 0)
    try:
        data = response.json()
    except ValueError:
        data = None
    code = _clip(data.get("error"), 60) if isinstance(data, dict) and data.get("error") else None
    if status in accept_status and data is not None:
        return (status, data) if with_status else data
    fields = _error_fields(data)
    if status in (401, 403):
        raise ApiError("unauthorized", f"HTTP {status}: token refused", status, code, **fields)
    if status == 404:
        raise ApiError("not_found", f"HTTP 404{': ' + code if code else ''}", status, code, **fields)
    if status >= 400 or status < 200:
        detail = code or ""
        message = _clip(data.get("message")) if isinstance(data, dict) and data.get("message") else ""
        if message and message != detail:
            detail = f"{detail} ({message})" if detail else message
        raise ApiError("http", f"HTTP {status}{': ' + detail if detail else ''}", status, code, **fields)
    if data is None:
        raise ApiError("bad_response", f"HTTP {status}: response is not JSON", status)
    return (status, data) if with_status else data


def segment(value: Any) -> str:
    """One URL path segment from an id taken from hub data (no slashes, dots or query characters survive)."""
    return quote(str(value), safe="")


def invalid(sentence: str) -> ApiError:
    """A local validation refusal: nothing was sent."""
    return ApiError("invalid", sentence)


# ---------------------------------------------------------------------------------------------- hub transport


def hub_get(ws: Workspace, path: str, params: dict | None = None) -> Any:
    if not ws.hub_url:
        raise ApiError("not_configured", f"hub_url is not configured for workspace '{ws.id}'")
    if not ws.read_token:
        raise ApiError("not_configured", f"read_token is not configured for workspace '{ws.id}'")
    clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    return request_json("GET", ws.hub_url + path, token=ws.read_token, params=clean)


def hub_post(ws: Workspace, path: str, body: Any, owner_token: str) -> Any:
    """An owner write. The caller resolves owner_token through the PIN gate (owner.token)."""
    if not ws.hub_url:
        raise ApiError("not_configured", f"hub_url is not configured for workspace '{ws.id}'")
    if not owner_token:
        raise ApiError("not_configured", "owner writes are locked")
    return request_json("POST", ws.hub_url + path, token=owner_token, body=body)


def _dict(data: Any, what: str) -> dict:
    if not isinstance(data, dict):
        raise ApiError("bad_response", f"{what} is not a JSON object")
    return data


# ---------------------------------------------------------------------------------------------- hub reads


def editions(ws: Workspace, *, before: int | None = None, limit: int = 5) -> dict:
    """GET /editions?limit=&before=: {editions, next_before, has_more}, newest first."""
    return _dict(hub_get(ws, "/editions", {"limit": limit, "before": before}), "editions")


def edition(ws: Workspace, edition_id: int) -> dict | None:
    """GET /editions/<id>: one briefing (the shape GET /editions lists), or None when there is no such briefing
    (404 unknown_edition)."""
    if isinstance(edition_id, bool) or not isinstance(edition_id, int) or edition_id < 1:
        raise invalid("That briefing link is not valid.")
    try:
        body = _dict(hub_get(ws, f"/editions/{edition_id}"), "edition")
    except ApiError as exc:
        if exc.kind == "not_found" and exc.code == "unknown_edition":
            return None
        raise
    row = body.get("edition")
    return row if isinstance(row, dict) else None


def latest_edition(ws: Workspace) -> dict:
    """GET /editions/latest: {latest_edition_id, published_at, item_count, briefing_label, editions} (no items)."""
    return _dict(hub_get(ws, "/editions/latest"), "latest edition")


def search_editions(ws: Workspace, query: str, *, days: int = SEARCH_DAYS, limit: int = SEARCH_LIMIT,
                    offset: int = 0) -> dict:
    """GET /editions/search?q=&days=&limit=&offset=: briefing stories matching every word, newest briefing first:
    {q, days, total, returned, has_more, next_offset, hits: [{edition_id, item_id, rank, headline, ...}]}. Schema 14
    adds `legacy`, the old tracker's matching stories over its whole archive, newest first, with the same limit and
    offset: {total, returned, has_more, next_offset, hits: [{kind: "old_tracker", ref, date, slot, label, headline,
    summary, url, corrected, correction, ...}]}."""
    words = _text(query)
    if not words:
        raise invalid("Type a word to search your briefings for.")
    return _dict(hub_get(ws, "/editions/search", {"q": words, "days": days, "limit": limit,
                                                  "offset": offset or None}), "briefing search")


def status(ws: Workspace) -> dict:
    """GET /status: the analyst's status line in one light read (level, reason, stage, last and next briefing)."""
    return _dict(hub_get(ws, "/status"), "status")


def rejected(ws: Workspace, *, days: int | None = 3, filter: str = "all", include_auto: bool = False,
             q: str | None = None, module: str | None = None, limit: int | None = None, offset: int = 0,
             edition_id: int | None = None) -> dict:
    """GET /rejected?days=&filter=&include_auto=1&q=&module=&limit=&offset=&edition_id=: stories left out of the
    briefings (filter: all | near_miss | same_story | muted | old_news | auto), one row per story, with the true
    `total`, every view's count (`views`) and `has_more` / `next_offset`. With `edition_id` (schema 11,
    docs/SPEC-SIMPLIFY.md 1.3): the stories that briefing's run decided and left out, whatever `days` says, each with
    its `group` (near_miss, below_bar, same_story); 404 unknown_edition. `days` goes up to 90 with a search (`q`)."""
    if filter not in REJECTED_FILTERS:
        raise invalid("Choose which stories that were left out to show.")
    if module and not MODULE_ID_RE.match(module):
        raise invalid("That coverage area is not known.")
    eid = None
    if edition_id is not None:
        eid = _id(edition_id)
        if eid is None:
            raise invalid("That briefing is not known.")
    params = {"days": days, "filter": filter, "include_auto": 1 if include_auto else None, "q": _text(q) or None,
              "module": module or None, "limit": limit, "offset": offset or None, "edition_id": eid}
    return _dict(hub_get(ws, "/rejected", params), "rejected")


def tuneup(ws: Workspace) -> dict:
    """GET /tuneup (schema 11, docs/SPEC-SIMPLIFY.md 1.5): the weekly tune-up, {due, week, dismissed, rated_7d, target,
    items: [{event_id, item_id, title, url, source_label, module, area_label, published_at, decision, score, bar,
    reason_text}]}: up to 5 stories of the last 7 days' briefings whose scores sit closest to their bar. An older hub
    answers 404."""
    return _dict(hub_get(ws, "/tuneup"), "tune-up")


def modules(ws: Workspace) -> dict:
    """GET /modules: the coverage areas with catalog version, counts, health, mutes and stars."""
    return _dict(hub_get(ws, "/modules"), "modules")


def inspect_module(ws: Workspace, module_id: str) -> dict:
    """GET /modules/<id>/inspect: lanes, categories, sources and companies with stats (404 catalog_missing)."""
    if not MODULE_ID_RE.match(str(module_id or "")):
        raise invalid("That coverage area is not known.")
    return _dict(hub_get(ws, f"/modules/{segment(module_id)}/inspect"), "inspect")


def mutes(ws: Workspace, *, include_removed: bool = False) -> dict:
    """GET /mutes (all=1 also lists removed mutes): {mutes, active_count, total, limit, has_more}."""
    return _dict(hub_get(ws, "/mutes", {"all": 1 if include_removed else None}), "mutes")


def mute_preview(ws: Workspace, kind: str, ref: str, module: str | None = None, event_id: int | None = None) -> dict:
    """GET /mutes/preview?kind=&module=&ref=&event_id=: what a mute would have hidden in the last 7 days; event_id (the
    story the mute is made from) leads the examples and, for a company, says whether that story would be hidden."""
    return _dict(hub_get(ws, "/mutes/preview", {"kind": kind, "module": module, "ref": ref, "event_id": _id(event_id)}),
                 "mute preview")


def bring_back_preview(ws: Workspace, mute_id: int, days: int = 7) -> dict:
    """GET /mutes/bring-back-preview?mute_id=&days=: how many stories unmuting (or Bring back) would return, with
    examples and a plain `text`; `would_bring_back` equals what the unmute then reports as brought_back."""
    mid = _id(mute_id)
    if mid is None:
        raise invalid("That mute is not known.")
    return _dict(hub_get(ws, "/mutes/bring-back-preview", {"mute_id": mid, "days": days}), "bring-back preview")


def stars(ws: Workspace) -> dict:
    """GET /stars: {stars}, each with matches_7d and in_briefing_7d."""
    return _dict(hub_get(ws, "/stars"), "stars")


def star_preview(ws: Workspace, entity_id: str) -> dict:
    """GET /stars/preview?entity=: the company's stories of the last 7 days."""
    return _dict(hub_get(ws, "/stars/preview", {"entity": entity_id}), "star preview")


def preferences(ws: Workspace) -> dict:
    """GET /preferences: preferences with stats, suggestions, soft_cap, summary_7d, counts, and (schema 13) the
    suggested company names waiting for the analyst's OK (`company_suggestions`, status proposed, newest first)."""
    return _dict(hub_get(ws, "/preferences"), "preferences")


def rules(ws: Workspace) -> dict:
    """GET /rules: {precedents, drafts, counts}."""
    return _dict(hub_get(ws, "/rules"), "rules")


def settings(ws: Workspace) -> dict:
    """GET /settings: {volume, stage}."""
    return _dict(hub_get(ws, "/settings"), "settings")


def volume_preview(ws: Workspace, mode: str, near_miss_shelf: bool | None = None) -> dict:
    """GET /settings/volume/preview?mode=&near_miss_shelf=1|0."""
    shelf = None if near_miss_shelf is None else (1 if near_miss_shelf else 0)
    return _dict(hub_get(ws, "/settings/volume/preview", {"mode": mode, "near_miss_shelf": shelf}), "volume preview")


def brief(ws: Workspace) -> dict:
    """GET /brief: what ZENITH looks for, the analyst's tuning and the sign-off state."""
    return _dict(hub_get(ws, "/brief"), "brief")


def radar(ws: Workspace) -> dict:
    """GET /radar: {requests, total, limit, has_more}; each request with its stage, timeline, plain status and
    proposal, sources and first stories."""
    return _dict(hub_get(ws, "/radar"), "radar")


def repairs(ws: Workspace) -> dict:
    """GET /repairs: {repairs, counts}; the source repairs the Radar scout proposed, newest first (at most 100), each
    with the catalog's entry before the fix, the proposal, the alternates with their labels and the probe's evidence
    (docs/SPEC-REPAIR-PHASE-B.md 1.4), and `counts` by status over every repair. An older hub answers 404."""
    return _dict(hub_get(ws, "/repairs"), "repairs")


def company_suggestions(ws: Workspace, status: str | None = None) -> dict:
    """GET /companies/suggestions?status= (schema 13, docs/SPEC-COMPANY-MAP.md 5.2): {suggestions, counts}; the
    analyst's suggested changes to the company sheets with the source finder's check (`verdict`), one status when
    given. Tuning reads the proposed ones from GET /preferences `company_suggestions` instead. An older hub answers
    404."""
    if status is not None and status not in COMPANY_STATUSES:
        raise invalid("That kind of company name suggestion is not known.")
    return _dict(hub_get(ws, "/companies/suggestions", {"status": status}), "company suggestions")


def diagnostics(ws: Workspace) -> dict:
    """GET /diagnostics: severity, routines, last_edition and the rest (docs/SPEC-PHASE01.md 4.6). The Control room's
    read; the analyst's status line reads GET /status."""
    return _dict(hub_get(ws, "/diagnostics"), "diagnostics")


# ---------------------------------------------------------------------------------------------- hub writes


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()) if value is not None else ""


def _id(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _note(value: Any, limit: int = TEXT_MAX) -> str | None:
    note = _text(value)
    if len(note) > limit:
        raise invalid(f"Keep the note to {limit} characters or fewer.")
    return note or None


def _with(body: dict, **optional: Any) -> dict:
    """body plus every optional field that is not None."""
    body.update({k: v for k, v in optional.items() if v is not None})
    return body


def add_preference(ws: Workspace, token: str, *, direction: str, scope: str, text: str = "",
                   item_id: int | None = None, event_id: int | None = None, note: str | None = None,
                   expires_at: str | None = None, replace: bool = False) -> dict:
    """POST /preferences {direction, scope, text?, item_id | event_id, note?, expires_at?, replace?}: an active
    preference at once. Answers {preference, wording_draft_id, warnings, effective, replaced?}. 409 preference_exists
    when the story already has one (its sentence asks to replace it); replace=True ends that one in the same step."""
    if direction not in DIRECTIONS:
        raise invalid("Choose more like this, less like this or exactly as I write it.")
    if scope not in SCOPES:
        raise invalid("Choose what it applies to: just this story, stories like this, or a standing preference.")
    words = _text(text)
    if len(words) > TEXT_MAX:
        raise invalid(f"Keep it to {TEXT_MAX} characters or fewer.")
    target_item, target_event = _id(item_id), _id(event_id)
    has_target = target_item is not None or target_event is not None
    if not has_target and scope != "standing":
        raise invalid("Pick a story for this preference.")
    if (direction == "exact" or not has_target) and len(words) < TEXT_MIN:
        raise invalid(f"Write a sentence ({TEXT_MIN} characters or more) so the editor knows what you mean.")
    body: dict[str, Any] = {"direction": direction, "scope": scope}
    if words:
        body["text"] = words
    if target_item is not None:
        body["item_id"] = target_item
    elif target_event is not None:
        body["event_id"] = target_event
    if replace:
        body["replace"] = True
    return hub_post(ws, "/preferences", _with(body, note=_note(note), expires_at=expires_at or None), token)


def rule_action(ws: Workspace, token: str, rule_id: str | int, action: str, body: dict | None = None) -> dict:
    """POST /rules/<id>/<action> (approve, reject, retire, pause, resume, edit, end-date, reactivate)."""
    if action not in RULE_ACTIONS:
        raise invalid("That action is not available for a preference.")
    rid = str(rule_id).strip()
    if not RULE_ID_RE.match(rid):
        raise invalid("That preference is not known.")
    return hub_post(ws, f"/rules/{segment(rid)}/{action}", dict(body or {}), token)


def add_feedback(ws: Workspace, token: str, *, verdict: str, item_id: int | None = None, event_id: int | None = None,
                 note: str = "", scope: str = "item", score: int | None = None, edition_id: int | None = None,
                 item_rank: int | None = None) -> dict:
    """POST /feedback {verdict, scope, item_id | edition_id + item_rank | event_id, note?, score?}. Answers {id,
    feedback, draft_id, correction_id, effective}; a factual_error on a briefing item opens a correction."""
    if verdict not in VERDICTS:
        raise invalid("Choose a rating.")
    if scope not in FEEDBACK_SCOPES:
        raise invalid("That kind of rating is not known.")
    body: dict[str, Any] = {"verdict": verdict, "scope": scope}
    if _id(item_id) is not None:
        body["item_id"] = _id(item_id)
    elif _id(edition_id) is not None and _id(item_rank) is not None:
        body["edition_id"], body["item_rank"] = _id(edition_id), _id(item_rank)
    elif _id(event_id) is not None:
        body["event_id"] = _id(event_id)
    else:
        raise invalid("Pick a story to rate.")
    words = _note(note, LONG_TEXT_MAX)
    if verdict == "factual_error" and not words:
        raise invalid("Write a sentence so the editor knows what to check.")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise invalid("A score is a whole number from 0 to 100.")
        body["score"] = score
    return hub_post(ws, "/feedback", _with(body, note=words), token)


def withdraw_ratings(ws: Workspace, token: str, *, item_id: int | None = None, event_id: int | None = None) -> dict:
    """POST /feedback/withdraw {item_id} or {event_id} (exactly one; docs/SPEC-ICON-ACTIONS.md): withdraws every active
    rating of the story (for a briefing item, its ratings and its story's; for a story, its ratings and those of any
    briefing item of it). Nothing is deleted. Answers {withdrawn: [ids], effective}; nothing left to withdraw answers
    [] (the same call twice is harmless)."""
    item, event = _id(item_id), _id(event_id)
    if (item is None) == (event is None):
        raise invalid("Pick the story whose rating to withdraw.")
    return hub_post(ws, "/feedback/withdraw", {"item_id": item} if item is not None else {"event_id": event}, token)


def withdraw_promote(ws: Workspace, token: str, event_id: int) -> dict:
    """POST /promote/withdraw {event_id}: cancels the story's open "Should have been in" request and withdraws the note
    it stored. Answers {cancelled, already_reconsidered, withdrawn: [ids], effective}; already_reconsidered: the
    editor had looked at the story again, so only the note is withdrawn. The same call twice is harmless."""
    eid = _id(event_id)
    if eid is None:
        raise invalid("Pick the story whose request to withdraw.")
    return hub_post(ws, "/promote/withdraw", {"event_id": eid}, token)


def add_mute(ws: Workspace, token: str, *, kind: str, ref: str, module: str | None = None,
             note: str | None = None) -> dict:
    """POST /mutes {action: "add", kind, module?, ref, note?}. Answers {created, mute, applied_now, preview, effective}."""
    if kind not in MUTE_KINDS:
        raise invalid("Choose a source, an outlet, a company or a story to mute.")
    ref = _text(ref)
    if not ref:
        raise invalid("Choose what to mute.")
    if kind == "source" and not (module and MODULE_ID_RE.match(module)):
        raise invalid("This source can't be muted from here.")
    body: dict[str, Any] = {"action": "add", "kind": kind}
    if kind == "source":
        body["module"] = module
    body["ref"] = ref
    return hub_post(ws, "/mutes", _with(body, note=_note(note)), token)


def remove_mute(ws: Workspace, token: str, mute_id: int, *, bring_back_days: int = 0) -> dict:
    """POST /mutes {action: "remove", mute_id, bring_back_days} (0-7). Answers {mute, brought_back, requeued, effective}."""
    mid = _id(mute_id)
    if mid is None:
        raise invalid("That mute is not known.")
    if isinstance(bring_back_days, bool) or not isinstance(bring_back_days, int) or not 0 <= bring_back_days <= 7:
        raise invalid("Bring back from 0 to 7 days.")
    return hub_post(ws, "/mutes", {"action": "remove", "mute_id": mid, "bring_back_days": bring_back_days}, token)


def bring_back(ws: Workspace, token: str, mute_id: int, *, days: int = 7) -> dict:
    """POST /mutes {action: "bring_back", mute_id, days} (1-7) on a removed mute. 409 mute_active while it is on."""
    mid = _id(mute_id)
    if mid is None:
        raise invalid("That mute is not known.")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 7:
        raise invalid("Bring back from 1 to 7 days.")
    return hub_post(ws, "/mutes", {"action": "bring_back", "mute_id": mid, "days": days}, token)


def add_star(ws: Workspace, token: str, entity_id: str, *, note: str | None = None) -> dict:
    """POST /stars {action: "add", entity_id, note?}. Answers {created, star, preview, effective}."""
    eid = _text(entity_id)
    if not eid:
        raise invalid("Choose a company.")
    return hub_post(ws, "/stars", _with({"action": "add", "entity_id": eid}, note=_note(note)), token)


def remove_star(ws: Workspace, token: str, entity_id: str) -> dict:
    """POST /stars {action: "remove", entity_id}. Answers {star, removed, effective}."""
    eid = _text(entity_id)
    if not eid:
        raise invalid("Choose a company.")
    return hub_post(ws, "/stars", {"action": "remove", "entity_id": eid}, token)


def not_about(ws: Workspace, token: str, entity_id: str, event_id: int, *, undo: bool = False) -> dict:
    """POST /stars {action: "not_about" | "is_about", entity_id, event_id} (WF5): "this story is not about this company"
    (a look-alike name), or its undo. Answers {reported, entity_id, event_id, label, effective}."""
    eid, sid = _text(entity_id), _id(event_id)
    if not eid or sid is None:
        raise invalid("Choose the story and the company.")
    return hub_post(ws, "/stars", {"action": "is_about" if undo else "not_about", "entity_id": eid, "event_id": sid}, token)


def promote(ws: Workspace, token: str, event_id: int, note: str) -> dict:
    """POST /promote {event_id, note} ("Should have been in"; note 3-500). Answers {requeue, feedback_id, effective}."""
    eid = _id(event_id)
    if eid is None:
        raise invalid("Pick a story to send back.")
    words = _text(note)
    if len(words) < 3:
        raise invalid("Write a few words so the editor knows why it should have been in.")
    if len(words) > TEXT_MAX:
        raise invalid(f"Keep it to {TEXT_MAX} characters or fewer.")
    return hub_post(ws, "/promote", {"event_id": eid, "note": words}, token)


def dismiss_tuneup(ws: Workspace, token: str) -> dict:
    """POST /tuneup/dismiss {} (schema 11): skip this week's tune-up. Answers {dismissed: true, week}; idempotent."""
    return hub_post(ws, "/tuneup/dismiss", {}, token)


def allow_once(ws: Workspace, token: str, role: str) -> dict:
    """POST /admin/routines/allow-once {role} (schema 11, docs/SPEC-SIMPLIFY.md 1.2): the next due check of that
    routine (grader, refiner or scout) answers due, for 2 hours, so a run started by hand from claude.ai goes ahead.
    Answers {allowed: true, role, until}."""
    if role not in ROUTINE_ROLES:
        raise invalid("Choose a routine.")
    return hub_post(ws, "/admin/routines/allow-once", {"role": role}, token)


def set_volume(ws: Workspace, token: str, mode: str, *, near_miss_shelf: bool | None = None) -> dict:
    """POST /settings/volume {mode, near_miss_shelf?}. Answers {volume, effective}."""
    if mode not in VOLUME_MODES:
        raise invalid("Choose how many stories you want per briefing.")
    body: dict[str, Any] = {"mode": mode}
    if near_miss_shelf is not None:
        body["near_miss_shelf"] = bool(near_miss_shelf)
    return hub_post(ws, "/settings/volume", body, token)


def suggest_brief_change(ws: Workspace, token: str, line_id: str, text: str) -> dict:
    """POST /brief/suggest {line_id, text} (10-2000). Answers {draft, effective}."""
    lid = _text(line_id)
    if not lid:
        raise invalid("Choose the line to change.")
    words = _text(text)
    if len(words) < TEXT_MIN:
        raise invalid(f"Write how it should read ({TEXT_MIN} characters or more).")
    if len(words) > LONG_TEXT_MAX:
        raise invalid(f"Keep it to {LONG_TEXT_MAX} characters or fewer.")
    return hub_post(ws, "/brief/suggest", {"line_id": lid, "text": words}, token)


def suggest_company_change(ws: Workspace, token: str, *, ticker: str, column: str, action: str,
                           name: str | None = None, target_id: str | None = None, note: str | None = None,
                           big: bool | None = None, basis_text: str | None = None, link: str | None = None) -> dict:
    """POST /companies/suggestions {ticker, column, action, name?, target_id?, note?, big?, basis_text?, link?}: a
    name to add to a company's sheet, or one of its entries to remove or fix (target_id); the source finder checks it
    and it comes back under Needs your OK. big and basis_text are for customers only. Answers 201 {suggestion,
    effective}; 409 suggestion_exists, 404 unknown_company or unknown_entry."""
    tick = _text(ticker).upper()
    if not TICKER_RE.match(tick):
        raise invalid("Choose the company.")
    if column not in COMPANY_COLUMNS:
        raise invalid("Choose the column.")
    if action not in COMPANY_CHANGES:
        raise invalid("Choose whether to add, remove or fix a name.")
    words, target = _text(name), _text(target_id)
    if action == "add" and not words:
        raise invalid("Write the name to add.")
    if action != "add" and not target:
        raise invalid("Choose the name to remove or fix.")
    if len(words) > COMPANY_NAME_MAX:
        raise invalid(f"Keep the name to {COMPANY_NAME_MAX} characters or fewer.")
    reason = _text(basis_text)
    if big is not None and column != "customers":
        raise invalid("Only customers are marked as big.")
    if big and not reason:
        raise invalid("Say why it is a big customer, for example its share of revenue.")
    if len(reason) > COMPANY_REASON_MAX:
        raise invalid(f"Keep the reason to {COMPANY_REASON_MAX} characters or fewer.")
    url = with_scheme(_text(link))
    if url and not safe_url(url):
        raise invalid("The link must start with https:// or http://.")
    body: dict[str, Any] = {"ticker": tick, "column": column, "action": action}
    return hub_post(ws, "/companies/suggestions", _with(
        body, name=words or None, target_id=target if action != "add" else None,
        note=_note(note, COMPANY_NOTE_MAX), big=bool(big) if big is not None else None,
        basis_text=reason if big else None, link=url or None), token)


def company_suggestion_action(ws: Workspace, token: str, suggestion_id: str, action: str, *,
                              note: str | None = None, use: str | None = None) -> dict:
    """POST /companies/suggestions/<id>/<approve|reject|withdraw> {note?, use?}: use (approve only) says which version
    the builder writes, the source finder's proposal or the analyst's words as typed. Answers {suggestion, effective};
    409 suggestion_closed when it was decided or withdrawn meanwhile. No route reverses one."""
    if action not in COMPANY_ACTIONS:
        raise invalid("Choose approve, reject or withdraw.")
    sid = _text(suggestion_id)
    if not SUGGESTION_ID_RE.match(sid):
        raise invalid("That suggestion is not known.")
    if use is not None and (action != "approve" or use not in COMPANY_USES):
        raise invalid("Choose the source finder's version or your own words.")
    return hub_post(ws, f"/companies/suggestions/{segment(sid)}/{action}",
                    _with({}, note=_note(note), use=use), token)


def sign_off(ws: Workspace, token: str, *, rubric_version: str | None, catalog_versions: dict,
             note: str | None = None) -> dict:
    """POST /signoff {rubric_version, catalog_versions, note?}: the versions the analyst reviewed. 409
    changed_since_viewed (data.current) or catalog_missing."""
    if not isinstance(catalog_versions, dict):
        raise invalid("This page changed; reload it and sign off again.")
    body = {"rubric_version": rubric_version, "catalog_versions": dict(catalog_versions)}
    return hub_post(ws, "/signoff", _with(body, note=_note(note)), token)


def set_stage(ws: Workspace, token: str, stage: str, *, note: str | None = None) -> dict:
    """POST /admin/stage {stage, note?} (staging | live). Answers {stage, since, signoff, effective}."""
    if stage not in STAGES:
        raise invalid("Choose staging or live.")
    return hub_post(ws, "/admin/stage", _with({"stage": stage}, note=_note(note)), token)


_BARE_HOST_RE = re.compile(r"^(?!-)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::\d+)?(?:[/?#]\S*)?$")


def with_scheme(link: str) -> str:
    """A link as people usually copy it ("www.utilitydive.com/news") gets https:// in front (WF5 AW-13); anything
    else is returned as it is (and checked by safe_url)."""
    text = (link or "").strip()
    if text and "://" not in text and not text.startswith("//") and _BARE_HOST_RE.match(text):
        return "https://" + text
    return text


def add_radar_request(ws: Workspace, token: str, *, kind: str, text: str, url: str | None = None,
                      module: str | None = None) -> dict:
    """POST /radar/requests {kind, text, url?, module?}: a coverage request (kind track_source | missed_story |
    new_coverage). Answers the request."""
    if kind not in RADAR_KINDS:
        raise invalid("Choose what you are asking for.")
    words = _text(text)
    if len(words) < TEXT_MIN:
        raise invalid("Write a few words (10 characters or more) so the source finder knows what to look for.")
    if len(words) > LONG_TEXT_MAX:
        raise invalid(f"Keep it to {LONG_TEXT_MAX} characters or fewer.")
    link = with_scheme(_text(url))
    if kind == "missed_story" and not link:
        raise invalid("Paste the story's link so the source finder can see what was missed.")
    if link and not safe_url(link):
        raise invalid("The link must start with https:// or http://.")
    if module and not MODULE_ID_RE.match(module):
        raise invalid("That coverage area is not known.")
    body: dict[str, Any] = {"kind": kind, "text": words}
    return hub_post(ws, "/radar/requests", _with(body, url=link or None, module=module or None), token)


def radar_action(ws: Workspace, token: str, radar_id: int, action: str, *, note: str | None = None,
                 proposed_at: Any = NOT_SHOWN) -> dict:
    """POST /radar/<id>/<approve|reject> {note?, proposed_at?}; proposed_at is sent only when given (it binds an
    approval to the proposal shown: 409 proposal_changed otherwise)."""
    if action not in ("approve", "reject"):
        raise invalid("Choose approve or reject.")
    rid = _id(radar_id)
    if rid is None:
        raise invalid("That coverage request is not known.")
    body = _with({}, note=_note(note, LONG_TEXT_MAX))
    if proposed_at is not NOT_SHOWN:
        body["proposed_at"] = proposed_at
    return hub_post(ws, f"/radar/{rid}/{action}", body, token)


def repair_action(ws: Workspace, token: str, repair_id: int, action: str, note: str | None = None) -> dict:
    """POST /repairs/<id>/<approve|reject|withdraw> {note?}: a proposed repair becomes approved or rejected, a proposed
    or approved one withdrawn. Answers {repair}; a repair that has moved on is a 409 with the hub's plain sentence, an
    unknown one a 404."""
    if action not in REPAIR_ACTIONS:
        raise invalid("Choose approve, reject or withdraw.")
    rid = _id(repair_id)
    if rid is None:
        raise invalid("That source repair is not known.")
    return hub_post(ws, f"/repairs/{rid}/{action}", _with({}, note=_note(note, LONG_TEXT_MAX)), token)


def ack_source(ws: Workspace, module_id: str, source_key: str, note: str, owner_token: str) -> Any:
    """POST /admin/sources/ack: the owner knows about this source's problem; it stops coloring the workspace until
    the source recovers or fails in a new way. 404 unknown_source, 409 source_not_failing."""
    body: dict[str, Any] = {"module": module_id, "source_key": source_key}
    note = " ".join(str(note or "").split())
    if note:
        body["note"] = note[:ACK_NOTE_MAX]
    return hub_post(ws, "/admin/sources/ack", body, owner_token)


def unack_source(ws: Workspace, module_id: str, source_key: str, owner_token: str) -> Any:
    """POST /admin/sources/unack → {removed: true|false}."""
    return hub_post(ws, "/admin/sources/unack", {"module": module_id, "source_key": source_key}, owner_token)


# ---------------------------------------------------------------------------------------------- modules


def module_health(module: Module) -> dict:
    """GET /health. With the module's run_token the module answers its detailed body (last run, failing and silent
    sources, backfill, unfinished and running runs, build); without one, liveness only. A 503 with a JSON body is the
    module reporting its own trouble, not an error; a refused token is 'run token refused'."""
    if not module.url:
        raise ApiError("not_configured", f"url is not configured for module '{module.id}'")
    try:
        data = request_json("GET", module.url + "/health", token=module.run_token or None, accept_status=(503,))
    except ApiError as exc:
        if exc.kind == "unauthorized":
            raise ApiError("unauthorized", f"HTTP {exc.status}: run token refused", exc.status, exc.code) from None
        raise
    if not isinstance(data, dict):
        raise ApiError("bad_response", "health is not a JSON object")
    return data


def _job_of(data: Any) -> dict | None:
    if isinstance(data, dict) and "job" in data:
        data = data.get("job")
    return data if isinstance(data, dict) and data else None


def backfill_status(module: Module) -> dict | None:
    """GET /backfill: the current or last job, or None when the module has none yet."""
    if not module.can_backfill:
        raise ApiError("not_configured", f"url or run_token is not configured for module '{module.id}'")
    try:
        data = request_json("GET", module.url + "/backfill", token=module.run_token)
    except ApiError as exc:
        if exc.kind == "not_found":  # no_backfill_job: nothing has been requested yet
            return None
        raise
    return _job_of(data)


def start_backfill(module: Module, days: int, sources: list[str] | None = None,
                   ignore_seen: bool = False) -> tuple[dict, bool]:
    """POST /backfill {days, sources?, ignore_seen?} → (job, created). Validates before sending anything.

    ignore_seen (sent only when true) makes the module send every event again, even those it already sent: the
    recovery after lost deliveries. The hub drops what it already holds, so a resend is harmless.
    The module answers 202 with a new job, or 200 with the job already in flight (it is left unchanged)."""
    if not module.can_backfill:
        raise ApiError("not_configured", f"url or run_token is not configured for module '{module.id}'")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise ApiError("invalid", "days must be a whole number from 1 to 30")
    if not isinstance(ignore_seen, bool):
        raise ApiError("invalid", "ignore_seen must be true or false")
    body: dict[str, Any] = {"days": days}
    keys = [str(k).strip() for k in sources or [] if str(k).strip()]
    bad = [k for k in keys if not SOURCE_KEY_RE.match(k)]
    if bad:
        raise ApiError("invalid", f"invalid source key: {_clip(bad[0], 64)}")
    if keys:
        body["sources"] = sorted(set(keys))
    if ignore_seen:
        body["ignore_seen"] = True
    status, data = request_json("POST", module.url + "/backfill", token=module.run_token, body=body, with_status=True)
    return _job_of(data) or {}, status != 200
