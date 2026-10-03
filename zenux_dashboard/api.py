"""HTTP client for the Zenux hub and module Workers.

Plain functions over `requests` (no Streamlit calls), so they also run in worker threads. Tokens travel only in
the Authorization header, never in a URL, and no error message carries a token, a header or a response body
beyond the hub's short error code.

Hub routes (docs/SPEC-DAY2.md, "Dashboard API"):
    reads  (bearer READ_TOKEN):  GET /editions, /rejected, /rules, /radar, /diagnostics, /snapshot
    writes (bearer OWNER_TOKEN): POST /feedback, /rules/drafts, /rules/:id/{approve|reject|retire},
                                 /radar/requests, /radar/:id/{approve|reject}
Module routes (packages/module-sdk/src/worker.js):
    GET /health (public), GET /backfill (404 no_backfill_job) and POST /backfill (202 new job, 200 job in flight),
    both bearer RUN_TOKEN
"""

from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import quote

import requests

from . import USER_AGENT
from .config import Module, Workspace

TIMEOUT = (5, 15)  # connect, read (seconds)
SOURCE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MAX_MESSAGE = 160


class ApiError(Exception):
    """kind: not_configured | unreachable | unauthorized | not_found | http | bad_response."""

    def __init__(self, kind: str, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.code = code

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
    if status in (401, 403):
        raise ApiError("unauthorized", f"HTTP {status}: token refused", status, code)
    if status == 404:
        raise ApiError("not_found", f"HTTP 404{': ' + code if code else ''}", status, code)
    if status >= 400 or status < 200:
        detail = code or ""
        message = _clip(data.get("message")) if isinstance(data, dict) and data.get("message") else ""
        if message and message != detail:
            detail = f"{detail} ({message})" if detail else message
        raise ApiError("http", f"HTTP {status}{': ' + detail if detail else ''}", status, code)
    if data is None:
        raise ApiError("bad_response", f"HTTP {status}: response is not JSON", status)
    return (status, data) if with_status else data


def segment(value: Any) -> str:
    """One URL path segment from an id taken from hub data (no slashes, dots or query characters survive)."""
    return quote(str(value), safe="")


# ---------------------------------------------------------------------------------------------- hub


def hub_get(ws: Workspace, path: str, params: dict | None = None) -> Any:
    if not ws.hub_url:
        raise ApiError("not_configured", f"hub_url is not configured for workspace '{ws.id}'")
    if not ws.read_token:
        raise ApiError("not_configured", f"read_token is not configured for workspace '{ws.id}'")
    clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    return request_json("GET", ws.hub_url + path, token=ws.read_token, params=clean)


def hub_post(ws: Workspace, path: str, body: Any, owner_token: str) -> Any:
    """An owner write. The caller resolves owner_token through the PIN gate (owner.py)."""
    if not ws.hub_url:
        raise ApiError("not_configured", f"hub_url is not configured for workspace '{ws.id}'")
    if not owner_token:
        raise ApiError("not_configured", "owner writes are locked")
    return request_json("POST", ws.hub_url + path, token=owner_token, body=body)


# ---------------------------------------------------------------------------------------------- modules


def module_health(module: Module) -> dict:
    """GET /health (public). A 503 with a JSON body is the module reporting its own trouble, not an error."""
    if not module.url:
        raise ApiError("not_configured", f"url is not configured for module '{module.id}'")
    data = request_json("GET", module.url + "/health", accept_status=(503,))
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


def start_backfill(module: Module, days: int, sources: list[str] | None = None) -> tuple[dict, bool]:
    """POST /backfill {days, sources?} → (job, created). Validates before sending anything.

    The module answers 202 with a new job, or 200 with the job already in flight (it is left unchanged)."""
    if not module.can_backfill:
        raise ApiError("not_configured", f"url or run_token is not configured for module '{module.id}'")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise ApiError("invalid", "days must be a whole number from 1 to 30")
    body: dict[str, Any] = {"days": days}
    keys = [str(k).strip() for k in sources or [] if str(k).strip()]
    bad = [k for k in keys if not SOURCE_KEY_RE.match(k)]
    if bad:
        raise ApiError("invalid", f"invalid source key: {_clip(bad[0], 64)}")
    if keys:
        body["sources"] = sorted(set(keys))
    status, data = request_json("POST", module.url + "/backfill", token=module.run_token, body=body, with_status=True)
    return _job_of(data) or {}, status != 200
