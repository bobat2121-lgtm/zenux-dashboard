"""Cached hub and module reads.

Cache keys hold only workspace and module ids plus query values: the tokens are looked up inside the cached
function from st.secrets, so they never pass through Streamlit's cache machinery. A read that fails raises
ApiError and is not cached; the health panel instead records failures as data, because it is a status board.

TTLs (docs/SPEC-PHASE03-UI.md 1.4): reads 60 s, the coverage-area list 120 s, the coverage inspector and the brief
300 s, health 30 s. Every successful write calls clear_reads(), which clears every hub read below except the health
group (clear_health()).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import streamlit as st

from . import api
from .config import Config, Workspace, load_config
from .fmt import as_int, utc_now_iso

READ_TTL = 60
MODULES_TTL = 120
SLOW_TTL = 300
HEALTH_TTL = 30  # below the panel's 60 s refresh, so every refresh sees fresh data


def _ws(workspace_id: str) -> Workspace:
    ws = load_config().workspace(workspace_id)
    if ws is None:
        raise api.ApiError("not_configured", f"workspace '{workspace_id}' is not configured")
    return ws


# ---------------------------------------------------------------------------------------------- briefings


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def editions(workspace_id: str, before: int | None = None, limit: int = 5) -> dict:
    """GET /editions: one page of briefings, newest first."""
    return api.editions(_ws(workspace_id), before=before, limit=limit)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def edition(workspace_id: str, edition_id: int) -> dict | None:
    """GET /editions/<id>: one briefing (a deep link), or None when it does not exist."""
    return api.edition(_ws(workspace_id), edition_id)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def latest_edition_id(workspace_id: str) -> int | None:
    """The newest briefing's id (the new-briefing check, GET /editions/latest), or None when there is none yet."""
    return as_int(api.latest_edition(_ws(workspace_id)).get("latest_edition_id"))


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def search_editions(workspace_id: str, query: str, days: int = api.SEARCH_DAYS, limit: int = api.SEARCH_LIMIT) -> dict:
    """GET /editions/search: briefing stories of the last `days` days matching every word of the query."""
    return api.search_editions(_ws(workspace_id), query, days=days, limit=limit)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def status(workspace_id: str) -> dict:
    """GET /status: the analyst's status line."""
    return api.status(_ws(workspace_id))


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def rejected(workspace_id: str, days: int | None = 3, filter: str = "all", include_auto: bool = False, q: str = "",
             module: str = "", offset: int = 0, edition_id: int | None = None, limit: int | None = None) -> dict:
    """GET /rejected: stories left out of the briefings (filter all | near_miss | same_story | muted | old_news | auto),
    searched (q) and narrowed to one coverage area (module) by the hub; one page of up to `limit` (500 at most) from
    `offset`. With edition_id: what that briefing left out (Briefing's "Left out of this briefing")."""
    return api.rejected(_ws(workspace_id), days=days, filter=filter, include_auto=include_auto, q=q or None,
                        module=module or None, offset=offset, edition_id=edition_id, limit=limit)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def tuneup(workspace_id: str) -> dict:
    """GET /tuneup: the weekly tune-up (Briefing's banner and its panel)."""
    return api.tuneup(_ws(workspace_id))


# ---------------------------------------------------------------------------------------------- coverage


@st.cache_data(ttl=MODULES_TTL, show_spinner=False)
def modules(workspace_id: str) -> dict:
    """GET /modules: the coverage areas."""
    return api.modules(_ws(workspace_id))


@st.cache_data(ttl=SLOW_TTL, show_spinner=False)
def inspect(workspace_id: str, module_id: str) -> dict:
    """GET /modules/<id>/inspect: a coverage area's sources and companies."""
    return api.inspect_module(_ws(workspace_id), module_id)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def radar(workspace_id: str) -> dict:
    """GET /radar: coverage requests."""
    return api.radar(_ws(workspace_id))


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def repairs(workspace_id: str) -> dict:
    """GET /repairs: source repairs (the Control room's review and its source-health window)."""
    return api.repairs(_ws(workspace_id))


# ---------------------------------------------------------------------------------------------- tuning


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def mutes(workspace_id: str, include_removed: bool = False) -> dict:
    return api.mutes(_ws(workspace_id), include_removed=include_removed)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def mute_preview(workspace_id: str, kind: str, ref: str, module: str | None = None, event_id: int | None = None) -> dict:
    return api.mute_preview(_ws(workspace_id), kind, ref, module, event_id)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def bring_back_preview(workspace_id: str, mute_id: int, days: int = 7) -> dict:
    """GET /mutes/bring-back-preview: what unmuting would bring back."""
    return api.bring_back_preview(_ws(workspace_id), mute_id, days)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def stars(workspace_id: str) -> dict:
    return api.stars(_ws(workspace_id))


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def star_preview(workspace_id: str, entity_id: str) -> dict:
    return api.star_preview(_ws(workspace_id), entity_id)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def preferences(workspace_id: str) -> dict:
    return api.preferences(_ws(workspace_id))


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def rules(workspace_id: str) -> dict:
    return api.rules(_ws(workspace_id))


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def settings(workspace_id: str) -> dict:
    return api.settings(_ws(workspace_id))


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def volume_preview(workspace_id: str, mode: str, near_miss_shelf: bool | None = None) -> dict:
    return api.volume_preview(_ws(workspace_id), mode, near_miss_shelf)


@st.cache_data(ttl=SLOW_TTL, show_spinner=False)
def brief(workspace_id: str) -> dict:
    """GET /brief: what ZENITH looks for (sign-off sends the versions of exactly this cached read)."""
    return api.brief(_ws(workspace_id))


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def diagnostics(workspace_id: str) -> dict:
    """GET /diagnostics: the source finder's next run for the coverage-request toast (the status line reads /status;
    the Control room keeps workspace_health)."""
    return api.diagnostics(_ws(workspace_id))


# ---------------------------------------------------------------------------------------------- health (Control room)


@st.cache_data(ttl=HEALTH_TTL, show_spinner=False)
def snapshot(workspace_id: str, module_id: str, limit: int = 20) -> Any:
    return api.hub_get(_ws(workspace_id), "/snapshot", {"module": module_id, "limit": limit})


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def hub_sources(workspace_id: str, module_id: str) -> Any:
    """GET /sources?module=: the hub's source_health rows for one module (every source that has reported)."""
    return api.hub_get(_ws(workspace_id), "/sources", {"module": module_id})


@st.cache_data(ttl=HEALTH_TTL, show_spinner=False)
def module_health(workspace_id: str, module_id: str) -> dict:
    module = _ws(workspace_id).module(module_id)
    if module is None:
        raise api.ApiError("not_configured", f"module '{module_id}' is not configured")
    return api.module_health(module)


def _attempt(fn, *args) -> dict:
    try:
        return {"data": fn(*args), "error": None}
    except api.ApiError as exc:
        return {"data": None, "error": str(exc), "kind": exc.kind, "code": exc.code}
    except Exception as exc:  # never let one call take the panel down
        return {"data": None, "error": f"failed ({type(exc).__name__})", "kind": "error"}


def gather_health(ws: Workspace) -> dict:
    """Hub /diagnostics plus every module's /health (detailed with the module's run_token, else liveness only),
    fetched in parallel. Failures are recorded, not raised."""
    calls: dict[str, tuple] = {"hub": (api.hub_get, ws, "/diagnostics")}
    for module in ws.modules:
        calls[f"module:{module.id}"] = (api.module_health, module)
    with ThreadPoolExecutor(max_workers=min(8, len(calls))) as pool:
        futures = {name: pool.submit(_attempt, *call) for name, call in calls.items()}
        results = {name: future.result() for name, future in futures.items()}
    return {
        "workspace": ws.id,
        "fetched_at": utc_now_iso(),
        "hub": results["hub"],
        "modules": {m.id: results[f"module:{m.id}"] for m in ws.modules},
    }


@st.cache_data(ttl=HEALTH_TTL, show_spinner=False)
def workspace_health(workspace_id: str) -> dict:
    return gather_health(_ws(workspace_id))


READS = (editions, edition, latest_edition_id, search_editions, status, rejected, tuneup, modules, inspect, radar,
         repairs, mutes, mute_preview, bring_back_preview, stars, star_preview, preferences, rules, settings,
         volume_preview, brief, diagnostics, hub_sources)


def clear_reads() -> None:
    """After a write (or Refresh, or Try again): the next run reads every hub list fresh (module health excepted)."""
    for fn in READS:
        fn.clear()


def clear_health() -> None:
    for fn in (workspace_health, module_health, snapshot):
        fn.clear()


def config() -> Config:
    return load_config()
