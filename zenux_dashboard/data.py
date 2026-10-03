"""Cached hub and module reads.

Cache keys hold only workspace and module ids plus query values: the tokens are looked up inside the cached
function from st.secrets, so they never pass through Streamlit's cache machinery. A read that fails raises
ApiError and is not cached; the health panel instead records failures as data, because it is a status board.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import streamlit as st

from . import api
from .config import Config, Workspace, load_config
from .fmt import utc_now_iso

READ_TTL = 60
HEALTH_TTL = 30  # below the panel's 60 s refresh, so every refresh sees fresh data


def _ws(workspace_id: str) -> Workspace:
    ws = load_config().workspace(workspace_id)
    if ws is None:
        raise api.ApiError("not_configured", f"workspace '{workspace_id}' is not configured")
    return ws


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def editions(workspace_id: str, before: str | None = None, limit: int = 10) -> Any:
    return api.hub_get(_ws(workspace_id), "/editions", {"limit": limit, "before": before})


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def rejected(workspace_id: str, days: int = 3) -> Any:
    return api.hub_get(_ws(workspace_id), "/rejected", {"days": days})


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def rules(workspace_id: str) -> Any:
    return api.hub_get(_ws(workspace_id), "/rules")


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def radar(workspace_id: str) -> Any:
    return api.hub_get(_ws(workspace_id), "/radar")


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
        return {"data": None, "error": str(exc), "kind": exc.kind}
    except Exception as exc:  # never let one call take the panel down
        return {"data": None, "error": f"failed ({type(exc).__name__})", "kind": "error"}


def gather_health(ws: Workspace) -> dict:
    """Hub /diagnostics plus every module's /health, fetched in parallel. Failures are recorded, not raised."""
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


def clear_reads() -> None:
    """After an owner write: the next run reads fresh lists."""
    for fn in (editions, rejected, rules, radar):
        fn.clear()


def clear_health() -> None:
    for fn in (workspace_health, module_health, snapshot):
        fn.clear()


def config() -> Config:
    return load_config()
