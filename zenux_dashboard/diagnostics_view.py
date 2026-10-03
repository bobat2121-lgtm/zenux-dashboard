"""Diagnostics: the owner's control room, spanning every configured workspace.

1. Backfill (top): workspace, module, optional sources (from the module's /health), days 1-30, Run. It POSTs the
   module Worker's /backfill (bearer run_token, behind the owner PIN) and polls GET /backfill for progress.
2. Live health (every workspace, refreshed every 60 s): hub /diagnostics plus each module's /health: status
   pills, last runs, failing and silent sources, dead letters, review backlog, lease and the last edition.
3. Per-module snapshot (hub /snapshot): event counts by lane for 24 hours and 7 days, and the latest 20 events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

import streamlit as st

from . import api, data, owner
from .config import Config, Module, Workspace
from .fmt import (as_int, as_list, clip, count_of, dicts, empty_state, esc, fmt_short, fmt_time, label_of, link,
                  one_line, parse_time, pick, pill, plural, relative_time, safe_url, section_label, table, MIN_TIME, UTC)

HEALTH_REFRESH_SECONDS = 60
BACKFILL_POLL_SECONDS = 10
SNAPSHOT_LIMIT = 20
ACTIVE_JOB = ("queued", "running")
WINDOWS = {
    "24h": ("24h", "last_24h", "events_24h", "1d", "day"),
    "7d": ("7d", "last_7d", "events_7d", "week"),
}
BAD_MODULE = ("down", "failed")


# ---------------------------------------------------------------------------------------------- shapes


def _lane_map(value: Any) -> dict[str, int] | None:
    if isinstance(value, Mapping):
        out = {str(k): as_int(v) for k, v in value.items() if str(k) != "total" and as_int(v) is not None}
        return {k: v for k, v in out.items() if v is not None}
    if isinstance(value, list):
        out: dict[str, int] = {}
        for row in dicts(value):
            lane = one_line(pick(row, "lane", "name", "key"))
            n = as_int(pick(row, "count", "n", "events", "total"))
            if lane and n is not None:
                out[lane] = out.get(lane, 0) + n
        return out
    n = as_int(value)
    return {"all lanes": n} if n is not None else None


def lane_counts(entry: Any, window: str) -> dict[str, int]:
    """Events by lane for '24h' or '7d', from any of the shapes a hub may use."""
    if not isinstance(entry, Mapping):
        return {}
    keys = WINDOWS[window]
    for container in (entry.get("events"), entry.get("counts"), entry.get("by_lane"), entry.get("lanes"), entry):
        if isinstance(container, Mapping):
            for key in keys:
                if key in container:
                    parsed = _lane_map(container[key])
                    if parsed is not None:
                        return parsed
    for container in (entry.get("lanes"), entry.get("by_lane"), entry.get("events")):
        rows = dicts(container)
        if rows:
            out: dict[str, int] = {}
            for row in rows:
                lane = one_line(pick(row, "lane", "name"))
                n = as_int(pick(row, *keys))
                if lane and n is not None:
                    out[lane] = out.get(lane, 0) + n
            if out:
                return out
    return {}


def hub_modules(diag: Any) -> dict[str, dict]:
    modules = pick(diag, "modules", default=[])
    if isinstance(modules, Mapping):
        return {str(k): dict(v, module_id=str(k)) for k, v in modules.items() if isinstance(v, Mapping)}
    out = {}
    for entry in dicts(modules):
        mid = one_line(pick(entry, "module_id", "id", "module"))
        if mid:
            out[mid] = entry
    return out


def _source_row(module_id: str, row: Mapping) -> dict:
    return {
        "module": one_line(pick(row, "module_id", "module")) or module_id,
        "key": one_line(pick(row, "source_key", "key")),
        "health": one_line(pick(row, "health")),
        "status": one_line(pick(row, "last_status", "status")),
        "http": as_int(pick(row, "last_http_status", "http_status")),
        "failures": as_int(pick(row, "consecutive_failures")) or 0,
        "last_ok_at": pick(row, "last_ok_at"),
        "last_new_at": pick(row, "last_new_at"),
        "warnings": [one_line(w) for w in as_list(row.get("warnings")) if one_line(w)],
    }


def _merge(rows: list[dict]) -> list[dict]:
    """De-duplicate by (module, key); the hub's row (listed first) wins, gaps are filled from the module's."""
    out: dict[tuple, dict] = {}
    for row in rows:
        if not row["key"]:
            continue
        key = (row["module"], row["key"])
        if key in out:
            for k, v in row.items():
                if out[key].get(k) in (None, "", [], 0) and v not in (None, "", []):
                    out[key][k] = v
        else:
            out[key] = dict(row)
    return sorted(out.values(), key=lambda r: (r["module"], r["key"]))


def lease_of(diag: Any, now: datetime | None = None) -> dict | None:
    lease = pick(diag, "review.lease", "lease")
    if not isinstance(lease, Mapping):
        return None
    expires = pick(lease, "lease_expires_at", "expires_at")
    held = lease.get("held")
    if held is None:
        expiry = parse_time(expires)
        held = bool(lease.get("run_id")) and expiry != MIN_TIME and expiry > (now or datetime.now(UTC))
    state = one_line(lease.get("state")).lower() or ("active" if held else "idle")
    return {"held": bool(held), "state": state, "run_id": lease.get("run_id"), "expires_at": expires}


def module_status(hub_entry: dict | None, health: dict | None, health_error: str | None, failing: int) -> tuple[str, str]:
    if health_error:
        return "down", health_error
    if isinstance(health, Mapping) and health.get("ok") is False:
        return "failed", one_line(health.get("error")) or "the module reports a failed run"
    hub_status = one_line(pick(hub_entry, "status")).lower()
    if hub_status == "no_runs" and not failing:
        return "no_runs", "no run has reached the hub yet"
    if hub_status == "failed":
        return "failed", "last run failed"
    if isinstance(hub_entry, Mapping) and hub_entry.get("retired"):
        return "unknown", "retired: no run for a long time"
    if isinstance(hub_entry, Mapping) and hub_entry.get("stale"):
        return "stale", "no recent run"
    if hub_status == "partial":
        return "degraded", "some sources failed"
    if failing:
        return "degraded", plural(failing, "failing source")
    if not hub_entry and not health:
        return "unknown", "no data yet"
    return "ok", ""


def summarize(ws: Workspace, report: Mapping) -> dict:
    """One workspace's health, merged from hub /diagnostics and each module's /health. Pure; no Streamlit."""
    hub = report.get("hub") or {}
    diag = hub.get("data") if isinstance(hub.get("data"), Mapping) else {}
    hub_error = hub.get("error")
    entries = hub_modules(diag)
    failing: list[dict] = [_source_row("", r) for r in dicts(pick(diag, "failing", default=[]))]
    silent: list[dict] = [_source_row("", r) for r in dicts(pick(diag, "silent", default=[]))]
    module_ids = [m.id for m in ws.modules] + [mid for mid in entries if ws.module(mid) is None]
    modules = []
    for mid in module_ids:
        entry = entries.get(mid) or {}
        result = (report.get("modules") or {}).get(mid) or {}
        health = result.get("data") if isinstance(result.get("data"), Mapping) else None
        error = result.get("error") if ws.module(mid) is not None else None
        failing += [_source_row(mid, r) for r in dicts(entry.get("failing"))]
        silent += [_source_row(mid, r) for r in dicts(entry.get("silent"))]
        failing += [_source_row(mid, r) for r in dicts((health or {}).get("failing"))]
        silent += [_source_row(mid, r) for r in dicts((health or {}).get("silent"))]
        last_run = pick(entry, "last_run") if isinstance(pick(entry, "last_run"), Mapping) else {}
        health_run = (health or {}).get("last_run") if isinstance((health or {}).get("last_run"), Mapping) else {}
        modules.append({
            "id": mid,
            "configured": ws.module(mid) is not None,
            "version": one_line(pick(entry, "version")) or one_line((health or {}).get("version")),
            "last_run_at": pick(last_run, "ended_at", "started_at") or pick(health_run, "ended_at", "started_at")
            or pick(entry, "last_run_at"),
            "last_run_status": one_line(pick(last_run, "status")) or one_line(pick(health_run, "status")),
            "events_24h": lane_counts(entry, "24h"),
            "events_7d": lane_counts(entry, "7d"),
            "dead_letters": count_of(pick(entry, "dead_letters")),
            "backfill": (health or {}).get("backfill") if isinstance((health or {}).get("backfill"), Mapping) else None,
            "hub_entry": entry,
            "health": health,
            "error": error,
        })
    failing = _merge(failing)
    silent = _merge(silent)
    for module in modules:
        n_fail = sum(1 for r in failing if r["module"] == module["id"])
        module["failing"] = n_fail
        module["silent"] = sum(1 for r in silent if r["module"] == module["id"])
        module["status"], module["reason"] = module_status(module["hub_entry"] or None, module["health"],
                                                            module["error"], n_fail)
    dead = pick(diag, "dead_letters", "counts.dead_letters")
    dead_recent = dicts(pick(dead, "recent", "items")) if isinstance(dead, Mapping) else dicts(dead)
    last_edition = pick(diag, "last_edition", "review.last_edition")
    last_edition = last_edition if isinstance(last_edition, Mapping) else {}
    if hub_error:
        status = "down"
    elif one_line(pick(diag, "status")).lower() in ("degraded", "failed") or any(
            m["status"] not in ("ok", "unknown", "no_runs") for m in modules if m["configured"]):
        status = "degraded"
    else:
        status = "ok"
    return {
        "workspace": ws.id,
        "status": status,
        "hub_error": hub_error,
        "hub_error_kind": hub.get("kind"),
        "hub_status": one_line(pick(diag, "status")),
        "generated_at": pick(diag, "generated_at") or report.get("fetched_at"),
        "fetched_at": report.get("fetched_at"),
        "last_edition_at": pick(last_edition, "published_at", "created_at"),
        "last_edition_id": pick(last_edition, "id", "edition_id"),
        "last_edition_items": count_of(pick(last_edition, "items", "item_count")),
        "backlog": as_int(pick(diag, "review.backlog", "backlog", "review_backlog", "review.pending")),
        "lease": lease_of(diag),
        "last_review": pick(diag, "review.last_run") if isinstance(pick(diag, "review.last_run"), Mapping) else None,
        "dead_by_reason": pick(dead, "by_reason") if isinstance(pick(dead, "by_reason"), Mapping) else {},
        "dead_letters": count_of(dead) if dead is not None else sum(m["dead_letters"] for m in modules),
        "dead_recent": dead_recent,
        "failing": failing,
        "silent": silent,
        "modules": modules,
    }


def source_keys(health: Any) -> list[str]:
    keys: set[str] = set()
    raw = pick(health, "sources", "source_keys")
    if isinstance(raw, Mapping):
        raw = pick(raw, "keys", "list", default=[])
    for source in as_list(raw) + dicts(pick(health, "failing")) + dicts(pick(health, "silent")):
        key = source if isinstance(source, str) else pick(source, "key", "source_key") if isinstance(source, Mapping) else None
        key = one_line(key)
        if key and api.SOURCE_KEY_RE.match(key):
            keys.add(key)
    return sorted(keys)


def hub_source_keys(body: Any) -> list[str]:
    """Current (not retired) source keys from the hub's GET /sources rows."""
    rows = dicts(pick(body, "sources", default=[])) if isinstance(body, Mapping) else dicts(body)
    keys = {one_line(pick(r, "source_key", "key")) for r in rows if not r.get("retired")}
    return sorted(k for k in keys if k and api.SOURCE_KEY_RE.match(k))


def job_counts(job: Mapping) -> tuple[int, int]:
    done = count_of(job.get("done"))
    remaining = count_of(job.get("remaining"))
    total = done + remaining or count_of(job.get("sources")) or (as_int(job.get("total")) or 0)
    return done, max(total, done)


def job_fraction(job: Mapping) -> float:
    if one_line(job.get("status")).lower() == "done":
        return 1.0
    done, total = job_counts(job)
    return 0.0 if total <= 0 else max(0.0, min(1.0, done / total))


# ---------------------------------------------------------------------------------------------- backfill


def _flag(ws: Workspace, module: Module) -> str:
    """Session key: True while this module's job is queued or running, so the progress fragment polls."""
    return f"bf_live_{ws.id}_{module.id}"


def _started(ws: Workspace, module: Module) -> str:
    """Session key: (job, message) from this session's last successful POST /backfill."""
    return f"bf_started_{ws.id}_{module.id}"


def job_html(job: Mapping, tz: str) -> str:
    done, total = job_counts(job)
    status = one_line(job.get("status")).lower() or "unknown"
    parts = [
        pill(status),
        f'<span>job {esc(clip(job.get("id") or "—", 40))}</span>',
        f'<span>{esc(plural(as_int(job.get("days")) or 0, "day"))}</span>',
        f'<span>{esc(done)} of {esc(total)} sources done</span>',
    ]
    if job.get("requested_at"):
        parts.append(f'<span>requested {esc(relative_time(job.get("requested_at")))}</span>')
    if job.get("finished_at"):
        parts.append(f'<span>finished {esc(fmt_short(job.get("finished_at"), tz))}</span>')
    totals = job.get("totals") if isinstance(job.get("totals"), Mapping) else {}
    if totals:
        parts.append(f'<span>{esc(as_int(totals.get("new")) or 0)} new · {esc(as_int(totals.get("emitted")) or 0)} emitted'
                     + (f' · {esc(as_int(totals.get("failed")))} failed' if as_int(totals.get("failed")) else "") + "</span>")
    return f'<div class="backfill-line">{"".join(parts)}</div>'


def backfill_progress(workspace_id: str, module_id: str) -> None:
    """GET /backfill and draw the job. Polled by a fragment while a job is queued or running."""
    conf = data.config()
    ws = conf.workspace(workspace_id)
    module = ws.module(module_id) if ws else None
    if ws is None or module is None:
        return
    flag, started_key = _flag(ws, module), _started(ws, module)
    try:
        job = api.backfill_status(module)
    except api.ApiError as exc:
        st.markdown(empty_state(f"Could not read backfill progress for {module.id}.", str(exc)), unsafe_allow_html=True)
        return
    started = st.session_state.get(started_key)
    if not job and isinstance(started, tuple):
        job = started[0]  # just queued here; the module has not reported it yet
    if isinstance(started, tuple):
        st.success(started[1])
    was_live = bool(st.session_state.get(flag))
    if not job:
        st.caption(f"No backfill has run for {module.id} yet.")
        st.session_state[flag] = False
        if was_live:
            st.rerun()  # nothing to poll any more
        return
    st.markdown(f'<div class="backfill-box">{job_html(job, ws.timezone)}</div>', unsafe_allow_html=True)
    done, total = job_counts(job)
    st.progress(job_fraction(job), text=f"{done} of {total} sources")
    if one_line(job.get("last_error")):
        st.caption(f"Last chunk error: {clip(job.get('last_error'), 200)}")
    remaining = [one_line(k) for k in as_list(job.get("remaining")) if one_line(k)]
    if remaining:
        st.caption("Remaining: " + ", ".join(remaining[:12]) + (f" and {len(remaining) - 12} more" if len(remaining) > 12 else ""))
    active = one_line(job.get("status")).lower() in ACTIVE_JOB
    st.session_state[flag] = active
    if active and not was_live:
        st.rerun()  # switch to the polling fragment
    if was_live and not active:
        st.session_state.pop(started_key, None)
        data.clear_health()
        st.rerun()  # the job ended: stop polling and refresh the health panel


backfill_progress_live = st.fragment(run_every=BACKFILL_POLL_SECONDS)(backfill_progress)


def render_backfill(conf: Config, current: Workspace | None) -> None:
    st.markdown(section_label("Backfill", "pulls recent weeks wherever each source allows"), unsafe_allow_html=True)
    candidates = [w for w in conf.workspaces if w.modules]
    if not candidates:
        st.markdown(empty_state("No modules are configured. Add [[workspaces.modules]] entries to the secrets."),
                    unsafe_allow_html=True)
        return
    ids = [w.id for w in candidates]
    if st.session_state.get("bf_ws") not in ids:
        st.session_state["bf_ws"] = current.id if current is not None and current.id in ids else ids[0]
    ws_col, module_col, days_col = st.columns([1, 1, 1])
    ws_id = ws_col.selectbox("Workspace", ids, key="bf_ws", format_func=lambda i: (conf.workspace(i) or current).label)
    ws = conf.workspace(ws_id)
    module_id = module_col.selectbox("Module", [m.id for m in ws.modules], key=f"bf_module_{ws.id}")
    module = ws.module(module_id)
    days = days_col.number_input("Days", min_value=1, max_value=30, value=14, step=1, key="bf_days",
                                 help="1 to 30 days back from now. Sources that cannot reach that far return what they hold.")
    try:
        health = data.module_health(ws.id, module.id)
        health_error = None
    except api.ApiError as exc:
        health, health_error = None, str(exc)
    try:
        reported = hub_source_keys(data.hub_sources(ws.id, module.id))
    except api.ApiError:
        reported = []
    options = sorted(set(source_keys(health)) | set(reported))
    sources = st.multiselect(
        "Sources (optional: every source when empty)", options, key=f"bf_sources_{ws.id}_{module.id}",
        accept_new_options=True, placeholder="all sources" if options else "type a source key",
        help="Sources the hub has seen from this module, plus any the module reports failing or silent; you can type "
             "another key. Quarantined sources still run during a backfill, and are reported.",
    )
    if health_error:
        st.caption(f"Could not list sources from {module.id}/health: {health_error}")
    if not module.can_backfill:
        st.caption(f"Backfill is disabled for {module.id}: url or run_token is not configured.")
    if st.button("Run backfill", type="primary", key="bf_run", disabled=not module.can_backfill):
        token = owner.require_owner(ws)
        if token:
            try:
                job, created = api.start_backfill(module, int(days), [str(s) for s in sources])
            except api.ApiError as exc:
                st.error(f"Backfill not started: {exc}")
            else:
                scope = f"{len(sources)} source(s)" if sources else "every source"
                if created:
                    message = (f"Backfill {clip(job.get('id') or '', 40)} queued for {ws.id}/{module.id}: "
                               f"{plural(int(days), 'day')}, {scope}. "
                               "The module works through it on its next scheduled runs.")
                else:
                    done, total = job_counts(job)
                    message = (f"A backfill is already in progress for {ws.id}/{module.id} "
                               f"(job {clip(job.get('id') or '', 40)}, {done} of {total} sources done). "
                               "It was left unchanged; run a new one when it finishes.")
                st.session_state[_started(ws, module)] = (job or {"status": "queued", "days": int(days)}, message)
                st.session_state[_flag(ws, module)] = True
                data.clear_health()
    if module.can_backfill:
        if st.session_state.get(_flag(ws, module)):
            backfill_progress_live(ws.id, module.id)
        else:
            backfill_progress(ws.id, module.id)


# ---------------------------------------------------------------------------------------------- health


def _total(counts: dict[str, int]) -> str:
    return str(sum(counts.values())) if counts else "—"


def tile(label: str, value: Any, detail: str = "", css: str = "") -> str:
    return (f'<div class="tile {css}"><div class="tile-n">{esc(value)}</div><div class="tile-l">{esc(label)}</div>'
            + (f'<div class="tile-d">{esc(detail)}</div>' if detail else "") + "</div>")


def health_card_html(ws: Workspace, s: dict) -> str:
    status = s["status"]
    css = {"down": "bad", "degraded": "warn"}.get(status, "ok")
    head = (
        '<div class="health-head">'
        f'<span class="health-title">{esc(ws.label)}</span>{pill(status)}'
        f'<span class="health-sub">{esc(ws.id)} · checked {esc(relative_time(s["fetched_at"]))}</span>'
        "</div>"
    )
    if s["hub_error"]:
        what = {"unreachable": "Hub unreachable", "unauthorized": "Hub refused the read token"}.get(
            s.get("hub_error_kind"), "Hub error")
        hub_line = f'<div class="rejected-rationale"><strong>{esc(what)}</strong> · {esc(s["hub_error"])}</div>'
    else:
        hub_line = ""
    lease = s["lease"]
    if lease is None:
        lease_text = "—"
    elif lease["held"]:
        lease_text = "held"
    else:
        lease_text = "expired" if lease["state"] == "expired" else "free"
    lease_detail = (f'run {clip(lease["run_id"], 24)} · until {fmt_short(lease["expires_at"], ws.timezone)}'
                    if lease and lease["held"] else "")
    last_review = s.get("last_review")
    if last_review:
        when = pick(last_review, "finished_at", "leased_at")
        lease_detail = " · ".join(p for p in (
            lease_detail, f'last run {label_of(last_review.get("status")) or "—"} {relative_time(when)}') if p)
    reasons = sorted((s.get("dead_by_reason") or {}).items(), key=lambda kv: -(as_int(kv[1]) or 0))[:2]
    dead_detail = ", ".join(f"{label_of(k)} {as_int(v) or 0}" for k, v in reasons)
    tiles = "".join([
        tile("Last edition", relative_time(s["last_edition_at"]) if s["last_edition_at"] else "none yet",
             (f'#{s["last_edition_id"]} · {plural(s["last_edition_items"], "item")}' if s["last_edition_at"] else "")),
        tile("Review backlog", "—" if s["backlog"] is None else s["backlog"], "events waiting for the Grader",
             "warn" if (s["backlog"] or 0) > 150 else ""),
        tile("Grader lease", lease_text, lease_detail),
        tile("Dead letters", s["dead_letters"], dead_detail, "bad" if s["dead_letters"] else ""),
        tile("Failing sources", len(s["failing"]), "", "bad" if s["failing"] else ""),
        tile("Silent sources", len(s["silent"]), "", "warn" if s["silent"] else ""),
    ])
    rows = []
    for m in s["modules"]:
        backfill = m["backfill"]
        bf = "—"
        if backfill:
            done, total = job_counts(backfill)
            bf = f'{pill(backfill.get("status") or "unknown")} {esc(done)}/{esc(total)}'
        last = (f'{esc(relative_time(m["last_run_at"]))} {pill(m["last_run_status"]) if m["last_run_status"] else ""}'
                if m["last_run_at"] else "never")
        rows.append([
            f'<span class="mono">{esc(m["id"])}</span>' + ("" if m["configured"] else ' <span class="tile-d">(hub only)</span>'),
            pill(m["status"]) + (f' <span class="tile-d">{esc(clip(m["reason"], 60))}</span>' if m["reason"] else ""),
            last,
            esc(_total(m["events_24h"])),
            esc(_total(m["events_7d"])),
            esc(m["failing"]),
            esc(m["silent"]),
            bf,
        ])
    modules_table = (table(["Module", "Status", "Last run", "Events 24h", "Events 7d", "Failing", "Silent", "Backfill"], rows)
                     if rows else '<div class="refine-note">No modules configured or reported.</div>')
    return f'<div class="health-card {css}">{head}{hub_line}<div class="tile-grid">{tiles}</div>{modules_table}</div>'


def failing_table(rows: list[dict], tz: str) -> str:
    return table(["Module", "Source", "Health", "Last status", "HTTP", "Failures", "Last OK"], [[
        esc(r["module"]), f'<span class="mono">{esc(r["key"])}</span>', pill(r["health"] or "unknown"),
        esc(label_of(r["status"]) or "—"), esc(r["http"] if r["http"] is not None else "—"), esc(r["failures"]),
        esc(fmt_short(r["last_ok_at"], tz)),
    ] for r in rows])


def silent_table(rows: list[dict], tz: str) -> str:
    return table(["Module", "Source", "Warnings", "Last new item"], [[
        esc(r["module"]), f'<span class="mono">{esc(r["key"])}</span>', esc(", ".join(r["warnings"]) or "—"),
        esc(fmt_short(r["last_new_at"], tz)),
    ] for r in rows])


def dead_table(rows: list[dict], tz: str) -> str:
    return table(["#", "Received", "Reason", "Record"], [[
        esc(pick(r, "id", default="—")), esc(fmt_short(pick(r, "received_at"), tz)), esc(label_of(pick(r, "reason"))),
        f'<span class="mono">{esc(clip(pick(r, "key", "record_key", default=""), 80))}</span>',
    ] for r in rows[:20]])


def render_workspace_health(ws: Workspace) -> None:
    report = data.workspace_health(ws.id)
    s = summarize(ws, report)
    st.markdown(health_card_html(ws, s), unsafe_allow_html=True)
    if s["failing"]:
        with st.expander(f"{ws.id} · failing sources · {len(s['failing'])}"):
            st.markdown(failing_table(s["failing"], ws.timezone), unsafe_allow_html=True)
    if s["silent"]:
        with st.expander(f"{ws.id} · silent sources · {len(s['silent'])}"):
            st.markdown(silent_table(s["silent"], ws.timezone), unsafe_allow_html=True)
    if s["dead_recent"]:
        with st.expander(f"{ws.id} · recent dead letters · {len(s['dead_recent'])}"):
            st.markdown(dead_table(s["dead_recent"], ws.timezone), unsafe_allow_html=True)


@st.fragment(run_every=HEALTH_REFRESH_SECONDS)
def render_health_panel() -> None:
    conf = data.config()
    head_col, button_col = st.columns([5, 1], vertical_alignment="center")
    head_col.markdown(section_label("Live health · every workspace", f"refreshes every {HEALTH_REFRESH_SECONDS} s"),
                      unsafe_allow_html=True)
    if button_col.button("Refresh now", key="health_refresh"):
        data.clear_health()
    for ws in conf.workspaces:
        render_workspace_health(ws)


# ---------------------------------------------------------------------------------------------- snapshot


def snapshot_events(body: Any) -> list[dict]:
    if isinstance(body, list):
        return dicts(body)
    return dicts(pick(body, "events", "items", "latest", default=[]))


def event_row_html(event: dict, tz: str) -> str:
    title = one_line(pick(event, "title", "headline")) or "(untitled event)"
    url = safe_url(pick(event, "url"))
    title_html = link(url, title, "") if url else esc(title)
    meta = " · ".join(p for p in (
        one_line(pick(event, "lane", "source.lane")), one_line(pick(event, "source_key", "source.key")),
        one_line(pick(event, "kind")), one_line(pick(event, "trust", "source.trust")),
    ) if p)
    entities = ", ".join(one_line(pick(e, "name", "entity_id")) for e in dicts(event.get("entities"))[:4])
    when = pick(event, "published_at", "received_at", "observed_at", "hub.received_at")
    return (
        '<div class="event-row"><div>'
        f'<div class="event-title">{title_html}</div>'
        f'<div class="event-meta">{esc(meta)}{(" · " + esc(entities)) if entities else ""}</div>'
        f'</div><div class="event-time">{esc(fmt_short(when, tz))}<br>{esc(relative_time(when))}</div></div>'
    )


def counts_table(c24: dict[str, int], c7: dict[str, int]) -> str:
    lanes = sorted(set(c24) | set(c7), key=lambda lane: (-(c7.get(lane, 0)), lane))
    rows = [[esc(label_of(lane)), f'{esc(c24.get(lane, 0))}', f'{esc(c7.get(lane, 0))}'] for lane in lanes]
    rows.append(["<b>All lanes</b>", f"<b>{sum(c24.values())}</b>", f"<b>{sum(c7.values())}</b>"])
    return table(["Lane", "Last 24 hours", "Last 7 days"], rows)


def render_snapshot(conf: Config, current: Workspace | None) -> None:
    st.markdown(section_label("Module snapshot", f"counts by lane and the latest {SNAPSHOT_LIMIT} events"),
                unsafe_allow_html=True)
    targets = [f"{w.id}/{m.id}" for w in conf.workspaces for m in w.modules]
    if not targets:
        st.markdown(empty_state("No modules are configured."), unsafe_allow_html=True)
        return
    if st.session_state.get("snap_target") not in targets:
        preferred = [t for t in targets if current is not None and t.startswith(current.id + "/")]
        st.session_state["snap_target"] = (preferred or targets)[0]
    target = st.selectbox("Module", targets, key="snap_target")
    ws_id, module_id = target.split("/", 1)
    ws = conf.workspace(ws_id)
    try:
        body = data.snapshot(ws_id, module_id, SNAPSHOT_LIMIT)
    except api.ApiError as exc:
        st.markdown(empty_state(f"Could not load the snapshot for {target}.", str(exc)), unsafe_allow_html=True)
        return
    c24, c7 = lane_counts(body, "24h"), lane_counts(body, "7d")
    if not c24 and not c7:
        try:
            entry = hub_modules((data.workspace_health(ws_id).get("hub") or {}).get("data")).get(module_id) or {}
        except api.ApiError:
            entry = {}
        c24, c7 = lane_counts(entry, "24h"), lane_counts(entry, "7d")
    if c24 or c7:
        st.markdown(counts_table(c24, c7), unsafe_allow_html=True)
    else:
        st.caption("No lane counts reported for this module.")
    events = snapshot_events(body)[:SNAPSHOT_LIMIT]
    if not events:
        st.markdown(empty_state(f"No events from {module_id} yet."), unsafe_allow_html=True)
        return
    st.markdown(f'<div class="event-list">{"".join(event_row_html(e, ws.timezone) for e in events)}</div>',
                unsafe_allow_html=True)


# ---------------------------------------------------------------------------------------------- config notes


def config_rows(conf: Config) -> list[list[str]]:
    yes = lambda ok: pill("ok", "set") if ok else pill("failed", "missing")  # noqa: E731
    rows = []
    for ws in conf.workspaces:
        rows.append([f'<b>{esc(ws.id)}</b>', "hub", yes(bool(ws.hub_url)), yes(bool(ws.read_token)),
                     yes(ws.can_write)])
        for m in ws.modules:
            rows.append([esc(f"{ws.id}/{m.id}"), "module", yes(bool(m.url)), yes(bool(m.run_token)), "—"])
    return rows


def render_config(conf: Config) -> None:
    with st.expander(f"Configuration · {plural(len(conf.workspaces), 'workspace')}"
                     + (f" · {plural(len(conf.problems), 'note')}" if conf.problems else "")):
        st.markdown(table(["Workspace / module", "Kind", "URL", "Read or run token", "Owner token and PIN"],
                          config_rows(conf)), unsafe_allow_html=True)
        for problem in conf.problems:
            st.caption(problem)
        st.caption("Values come from st.secrets and are never shown here.")


def render(conf: Config, current: Workspace | None) -> None:
    render_backfill(conf, current)
    render_health_panel()
    render_snapshot(conf, current)
    render_config(conf)
