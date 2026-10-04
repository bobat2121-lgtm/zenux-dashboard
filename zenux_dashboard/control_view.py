"""Control room: the builder's tab, spanning every configured workspace (shown only while the builder is unlocked).

Builder vocabulary is allowed here (source keys, lanes, routines by role); sentences stay plain. Order:

1. Today's diagnostics (every workspace). Hub /diagnostics plus each module's /health (detailed with the module's
   run_token). One severity per workspace: the hub computes it (severity.level: red, amber, green, with plain reasons,
   awaiting_signoff among them while the workspace is staging); the dashboard adds only what the hub cannot see, an
   unreachable hub or an unreachable configured module, which is red whatever the hub says. Tiles, the module table,
   the routines table, silent sources, biggest disagreements with the Grader, recent hub errors and dead letters, and a
   footer with the hub's build, the last delivery check and the last clean-up. An older hub without severity gets a
   conservative local estimate (a dead configured module is never green).
   Each workspace card is drawn by its own fragment that refreshes every 60 s: its top (status, reasons, tiles), one
   row per module, then the routines and the footer. A module that is not ok has a clickable status light ("Degraded",
   "Down"...) that opens "Sources not working": each failing source of that module with what is wrong in plain words
   (the HTTP answer, the failure streak, the last error the module reported), when it last worked, and the
   acknowledged and quiet ones. Phase A of docs/PLAN-SOURCE-REPAIR.md: a source with one missed check after working
   is "retrying" (it colours nothing), and a source the module slowed down after repeated HTTP 429s is "slowed"; an ok
   module with either gets a small note ("1 retrying · 1 slowed") that opens the same window. Phase B: a failing or
   retrying source with an open repair says so in the window, in one line ("A fix is proposed ..."; the cached GET
   /repairs, matched by module and source key). Under the card, outside the fragment (nothing with an input field
   reruns on a timer):
   - failing sources with Acknowledge (a note; POST /admin/sources/ack) and acknowledged sources with Remove
     acknowledgement (POST /admin/sources/unack), both through ui.write with a toast and undo;
   - the stage line and its switch (POST /admin/stage, after a confirmation, with undo);
   - "Open a module" pills: the technical module view right below (GET /modules/<id>/inspect, GET /modules, and the
     module snapshot from GET /snapshot: counts by lane and the latest 20 events).
2. Backfill: workspace, module, optional sources (from the module's /health), days 1-30, an optional "send again even
   if already sent", Run. It POSTs the module Worker's /backfill (bearer run_token, behind the builder unlock) and
   polls GET /backfill for progress.
3. Coverage requests to review (radar_view.render_review): the Source finder's technical proposals, approve or reject.
4. Source repairs to review (repairs_view.render_review): the Radar scout's proposed fixes for broken sources, each
   with before and after and the probe's evidence, approve or reject; then the approved ones with their apply command
   (and Withdraw), the applied, recovered, rejected and withdrawn ones.
5. Configuration (collapsed): what is set, never a value, and where the builder PIN comes from.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

import streamlit as st

from . import api, data, labels, links, owner, radar_view, repairs_view, ui
from .config import Config, Module, Workspace
from .fmt import (as_int, as_list, clip, count_of, dicts, empty_state, esc, every_text, fmt_day, fmt_short, label_of,
                  link, one_line, parse_time, pick, pill, plural, relative_time, safe_url, section_label, table, zone,
                  zone_label, MIN_TIME, UTC)

HEALTH_REFRESH_SECONDS = 60
BACKFILL_POLL_SECONDS = 10
SNAPSHOT_LIMIT = 20
ACTIVE_JOB = ("queued", "running")
WINDOWS = {
    "24h": ("24h", "last_24h", "events_24h", "1d", "day"),
    "7d": ("7d", "last_7d", "events_7d", "week"),
}
BAD_MODULE = ("down", "failed")

# Workspace severity: the hub's severity.level, shown as a pill and the card's top border.
LEVELS = ("red", "amber", "green")
LEVEL_TEXT = {"red": "needs action", "amber": "needs attention", "green": "healthy"}
LEVEL_CSS = {"red": "bad", "amber": "warn", "green": "ok"}
ROLES = (("grader", "Grader"), ("refiner", "Rule refiner"), ("scout", "Radar scout"))
TOKEN_NAMES = {"REVIEW_TOKEN": "review", "READ_TOKEN": "read", "OWNER_TOKEN": "owner", "HUB_TOKEN": "hub",
               "ANY": "unknown"}
PROBLEM_TEXT = {"failing": "failing", "structural_empty": "empty", "quota_streak": "quota used up"}
DB_WARN_PCT = 70
DB_LIMIT_BYTES = 10_000_000_000
CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
CATALOG_MISSING = "catalog_missing"
STAGES = ("staging", "live")
BUILDER_PIN_TEXT = {"builder_pin": "set (builder_pin)", "owner_pin": "set (owner PIN fallback)",
                    "workspace": "set (owner PIN fallback)"}
NOT_BUILDER = "The Control room is for the builder. Unlock it under Sign in to edit."
SOURCE_STATE_CSS = {"ok": "ok", "failing": "bad", "quiet": "warn", "off": "idle", "new": "idle", "retired": "idle"}
DIALOG_FAILING = "failing_sources"
QUIET_LIGHT = ("ok", "unknown", "retired")  # module statuses without a clickable light
MODULE_COLUMNS = ("Module", "Status", "Last run", "Events 24h", "Events 7d", "Failing", "Silent", "Backfill")
MODULE_WIDTHS = (1.6, 2.6, 1.5, 0.9, 0.9, 0.8, 0.8, 1.1)
HEALTH_WORDS = {"backoff": "retrying less often", "quarantined": "set aside after repeated failures",
                "degraded": "some checks failing"}
ACK_HINT = ("A problem you already know about can be acknowledged under the card (failing sources): it then stops "
            "colouring the status until the source recovers or fails in a new way.")


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
    acknowledged = row.get("acknowledged")
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
        "error": one_line(pick(row, "last_error", "error")),  # the module's own health has it; the hub's has not
        "pace": dict(row["pace"]) if isinstance(row.get("pace"), Mapping) else None,
        # schema v7: which problem it is (failing, structural_empty, quota_streak), its streaks, and the owner's
        # acknowledgement while the problem is unchanged ({acked_at, note, ...} or null)
        "kind": one_line(row.get("kind")),
        "empty_streak": as_int(row.get("empty_streak")) or 0,
        "quota_streak": as_int(row.get("quota_streak")) or 0,
        "acknowledged": dict(acknowledged) if isinstance(acknowledged, Mapping) else (
            {} if acknowledged is True else None),
    }


def _slowed_row(module_id: str, row: Mapping) -> dict:
    """A source the module slowed down after repeated HTTP 429s: a /diagnostics or module /health `slowed` row, or a
    source row carrying `pace`."""
    pace = row.get("pace") if isinstance(row.get("pace"), Mapping) else row
    return {
        "module": one_line(pick(row, "module_id", "module")) or module_id,
        "key": one_line(pick(row, "source_key", "key")),
        "factor": as_int(pace.get("factor")) or 1,
        "base_minutes": as_int(pace.get("base_minutes")),
        "effective_minutes": as_int(pace.get("effective_minutes")),
        "http": as_int(pick(pace, "http_status")),
        "since": pace.get("since"),
    }


def slowed_text(row: Mapping, tz: str) -> str:
    """'Checked every 2 h instead of every 1 h since Oct 4: the site asked us to slow down (HTTP 429).'"""
    since = f" since {fmt_short(row.get('since'), tz)}" if row.get("since") else ""
    return (f"Checked {every_text(row.get('effective_minutes'))} instead of {every_text(row.get('base_minutes'))}{since}: "
            f"the site asked us to slow down (HTTP {row.get('http') or 429}). It returns to normal after a week "
            "without that.")


def _ack_row(row: Mapping) -> dict:
    """An entry of severity.acknowledged: {module, source_key, kind, fingerprint, acked_at, note}."""
    return {
        "module": one_line(pick(row, "module", "module_id")),
        "key": one_line(pick(row, "source_key", "key")),
        "kind": one_line(row.get("kind")),
        "acked_at": row.get("acked_at"),
        "note": one_line(row.get("note")),
    }


def problem_text(row: Mapping) -> str:
    """'failing', 'empty 4 runs in a row' or 'quota used up 3 runs in a row' for a failing-source row."""
    kind = one_line(row.get("kind"))
    text = PROBLEM_TEXT.get(kind, label_of(kind))
    streak = as_int(row.get({"structural_empty": "empty_streak", "quota_streak": "quota_streak"}.get(kind, ""))) or 0
    return f"{text} {streak} runs in a row" if streak else text


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


def _merge_slowed(rows: list[dict]) -> list[dict]:
    """Slowed rows unique by (module, key), the hub's first; a factor of 1 is not slowed."""
    out: dict[tuple, dict] = {}
    for row in rows:
        if row["key"] and row["factor"] > 1:
            out.setdefault((row["module"], row["key"]), row)
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


def _stale_reason(hub_entry: Mapping) -> str:
    minutes = as_int(hub_entry.get("minutes_since_run"))
    every = as_int(hub_entry.get("interval_minutes"))
    if minutes is None:
        return "no recent run"
    if minutes < 120:
        gap = f"{minutes} min"
    elif minutes < 48 * 60:
        gap = f"{minutes // 60} h"
    else:
        gap = f"{minutes // 1440} days"
    return f"no run for {gap}" + (f" (it runs every {every} min)" if every else "")


def module_status(hub_entry: dict | None, health: dict | None, health_error: str | None, failing: int,
                  configured: bool = True, acknowledged: int = 0, partial_flagged: bool = False,
                  retrying: int = 0, red_flagged: bool = False) -> tuple[str, str]:
    """(status, reason) of one module row. The hub's view wins over the module's liveness answer; a configured module
    never shows ok when the hub reports it stale, failed or without runs, and is never shown as retired.
    `partial_flagged`: the hub lists a module_partial reason for this module (its partial run has a cause other than
    the failing sources), so acknowledged sources never turn it ok. `retrying`: sources with one missed check after
    working; like acknowledged ones they never make a partial run degraded, and a failed run whose only misses are
    retrying (the hub raises no red reason for it, `red_flagged` False: often the only source due in that tick) is ok."""
    entry = hub_entry if isinstance(hub_entry, Mapping) else {}
    if health_error:
        return "down", health_error
    if isinstance(health, Mapping) and health.get("ok") is False:
        return "failed", one_line(health.get("error")) or "the module reports a failed run"
    hub_status = one_line(entry.get("status")).lower()
    if hub_status == "failed":
        if retrying and not failing and not red_flagged:
            return "ok", plural(retrying, "source") + " retrying"
        return "failed", "last run failed"
    if hub_status == "no_runs":
        return "no_runs", "no run has reached the hub yet"
    if entry.get("retired") and not configured:
        return "retired", "no run for a long time"
    if entry.get("stale") or entry.get("retired"):
        return "stale", _stale_reason(entry)
    if failing:
        return "degraded", plural(failing, "failing source")
    unfinished = as_int(entry.get("unfinished_runs_24h")) or 0
    if unfinished or (isinstance(health, Mapping) and isinstance(health.get("unfinished"), Mapping)):
        return "degraded", "a run did not finish" if unfinished <= 1 else f"{unfinished} runs did not finish"
    if hub_status == "partial":
        if (acknowledged or retrying) and not partial_flagged:  # only known or retrying sources missed this run
            return "ok", " · ".join(p for p in (plural(retrying, "source") + " retrying" if retrying else "",
                                               plural(acknowledged, "acknowledged source") if acknowledged else "") if p)
        causes = entry.get("partial_causes") if isinstance(entry.get("partial_causes"), Mapping) else {}
        other = [one_line(c) for c in (causes.get("other") or []) if one_line(c)]
        return "degraded", ("partial run: " + ", ".join(other[:3])) if other else "some sources failed"
    if not entry and not health:
        return "unknown", "no data yet"
    return "ok", ""


def module_pill(m: Mapping) -> str:
    """A module row's status pill: stale and never-run configured modules are coloured, never neutral."""
    status = m["status"]
    css = None
    if m.get("configured") or m.get("hub_configured"):
        css = {"stale": "bad", "no_runs": "bad" if m.get("red") else "warn"}.get(status)
    return pill(status, css=css)


def _reason(level: str, message: str, code: str = "", module: str | None = None) -> dict:
    return {"level": level, "code": code, "message": message, "module": module}


def _worst(levels: list[str]) -> str:
    return next((level for level in LEVELS if level in levels), "green")


def hub_severity(diag: Any) -> tuple[str | None, list[dict], list[dict]]:
    """(level, reasons, acknowledged) from /diagnostics severity, or (None, [], []) from a hub that has none."""
    sev = pick(diag, "severity")
    if not isinstance(sev, Mapping):
        return None, [], []
    reasons = []
    for r in dicts(sev.get("reasons")):
        level = one_line(r.get("level")).lower()
        message = one_line(r.get("message")) or label_of(r.get("code")) or "an unnamed problem"
        reasons.append(_reason(level if level in ("red", "amber") else "amber", message, one_line(r.get("code")),
                               one_line(r.get("module")) or None))
    level = one_line(sev.get("level")).lower()
    if level not in LEVELS:
        level = _worst([r["level"] for r in reasons])
    return level, reasons, [a for a in (_ack_row(row) for row in dicts(sev.get("acknowledged"))) if a["key"]]


def local_reasons(diag: Any, modules: list[dict]) -> list[dict]:
    """For a hub without severity (schema 6 or older): a conservative estimate from the module rows, so a dead or
    failed configured module is red and never green; anything degraded is amber."""
    reasons = []
    for m in modules:
        if not m["configured"] or m["error"]:
            continue  # unreachable modules are reported by the dashboard itself
        if m["status"] == "failed":
            reasons.append(_reason("red", f"{m['id']}: {m['reason'] or 'last run failed'}", "module_failed", m["id"]))
        elif m["status"] == "stale":
            reasons.append(_reason("red", f"{m['id']} has not run recently ({m['reason']})", "module_stale", m["id"]))
        elif m["status"] == "no_runs":
            reasons.append(_reason("amber", f"{m['id']} has not reported a run yet", "module_no_runs", m["id"]))
        elif m["status"] == "degraded":
            reasons.append(_reason("amber", f"{m['id']}: {m['reason']}", "module_partial", m["id"]))
    if not reasons and one_line(pick(diag, "status")).lower() in ("degraded", "failed"):
        reasons.append(_reason("amber", "The hub reports a problem it does not describe (update the hub for details)"))
    return reasons


def module_error_reason(m: Mapping) -> dict:
    if one_line(m.get("error_kind")) == "unauthorized":
        return _reason("red", f"{m['id']} refused the dashboard's run token, so its health cannot be read",
                       "module_unreachable", m["id"])
    return _reason("red", f"{m['id']} did not answer its health check ({m['error']})", "module_unreachable", m["id"])


def module_unhealthy_reason(m: Mapping) -> dict:
    problem = one_line((m.get("health") or {}).get("error"))
    return _reason("red", f"{m['id']} reports a problem ({problem})" if problem else f"{m['id']} reports that its last run failed",
                   "module_unhealthy", m["id"])


def summarize(ws: Workspace, report: Mapping) -> dict:
    """One workspace's health, merged from hub /diagnostics and each module's /health. Pure; no Streamlit."""
    hub = report.get("hub") or {}
    diag = hub.get("data") if isinstance(hub.get("data"), Mapping) else {}
    hub_error = hub.get("error")
    entries = hub_modules(diag)
    failing: list[dict] = [_source_row("", r) for r in dicts(pick(diag, "failing", default=[]))]
    silent: list[dict] = [_source_row("", r) for r in dicts(pick(diag, "silent", default=[]))]
    retrying: list[dict] = [_source_row("", r) for r in dicts(pick(diag, "retrying", default=[]))]
    slowed: list[dict] = [_slowed_row("", r) for r in dicts(pick(diag, "slowed", default=[]))]
    module_ids = [m.id for m in ws.modules] + [mid for mid in entries if ws.module(mid) is None]
    modules = []
    for mid in module_ids:
        entry = entries.get(mid) or {}
        result = (report.get("modules") or {}).get(mid) or {}
        health = result.get("data") if isinstance(result.get("data"), Mapping) else None
        configured = ws.module(mid) is not None
        error = result.get("error") if configured else None
        failing += [_source_row(mid, r) for r in dicts(entry.get("failing"))]
        silent += [_source_row(mid, r) for r in dicts(entry.get("silent"))]
        failing += [_source_row(mid, r) for r in dicts((health or {}).get("failing"))]
        silent += [_source_row(mid, r) for r in dicts((health or {}).get("silent"))]
        retrying += [_source_row(mid, r) for r in dicts(entry.get("retrying")) + dicts((health or {}).get("retrying"))]
        slowed += [_slowed_row(mid, r) for r in dicts(entry.get("slowed")) + dicts((health or {}).get("slowed"))]
        last_run = pick(entry, "last_run") if isinstance(pick(entry, "last_run"), Mapping) else {}
        health_run = (health or {}).get("last_run") if isinstance((health or {}).get("last_run"), Mapping) else {}
        modules.append({
            "id": mid,
            "configured": configured,
            "hub_configured": entry.get("configured") is True,
            "version": one_line(pick(entry, "version")) or one_line((health or {}).get("version")),
            "last_run_at": pick(last_run, "ended_at", "started_at") or pick(health_run, "ended_at", "started_at")
            or pick(entry, "last_run_at"),
            "last_run_status": one_line(pick(last_run, "status")) or one_line(pick(health_run, "status")),
            "running": isinstance((health or {}).get("running"), Mapping),
            "events_24h": lane_counts(entry, "24h"),
            "events_7d": lane_counts(entry, "7d"),
            "dead_letters": count_of(pick(entry, "dead_letters")),
            "backfill": (health or {}).get("backfill") if isinstance((health or {}).get("backfill"), Mapping) else None,
            "hub_entry": entry,
            "health": health,
            "error": error,
            "error_kind": result.get("kind") if error else None,
        })
    hub_level, hub_reasons, acknowledged = hub_severity(diag)
    failing = _merge(failing)
    acknowledged = _merge(acknowledged + [
        {"module": r["module"], "key": r["key"], "kind": r["kind"], "acked_at": r["acknowledged"].get("acked_at"),
         "note": one_line(r["acknowledged"].get("note"))}
        for r in failing if r["acknowledged"] is not None])
    acked = {(a["module"], a["key"]) for a in acknowledged}
    failing = [r for r in failing if (r["module"], r["key"]) not in acked]
    silent = _merge(silent)
    failing_keys = {(r["module"], r["key"]) for r in failing}
    retrying = [r for r in _merge(retrying) if (r["module"], r["key"]) not in failing_keys]  # failing wins
    slowed = _merge_slowed(slowed)
    red_modules = {r["module"] for r in hub_reasons if r["level"] == "red" and r["module"]}
    partial_modules = {r["module"] for r in hub_reasons if r["code"] == "module_partial" and r["module"]}
    for module in modules:
        n_fail = sum(1 for r in failing if r["module"] == module["id"])
        module["failing"] = n_fail
        module["acknowledged"] = sum(1 for a in acknowledged if a["module"] == module["id"])
        module["silent"] = sum(1 for r in silent if r["module"] == module["id"])
        module["retrying"] = sum(1 for r in retrying if r["module"] == module["id"])
        module["slowed"] = sum(1 for r in slowed if r["module"] == module["id"])
        module["red"] = module["id"] in red_modules
        module["status"], module["reason"] = module_status(
            module["hub_entry"] or None, module["health"], module["error"], n_fail,
            configured=module["configured"] or module["hub_configured"], acknowledged=module["acknowledged"],
            partial_flagged=module["id"] in partial_modules, retrying=module["retrying"],
            red_flagged=module["red"])
    # The dashboard adds only what the hub cannot see: an unreachable configured module, or one whose own health
    # check says it is not ok (its state database is down, its last run failed) before the hub has noticed.
    own = [module_error_reason(m) for m in modules if m["configured"] and m["error"]]
    own += [module_unhealthy_reason(m) for m in modules if m["configured"] and not m["error"] and m["id"] not in red_modules
            and isinstance(m["health"], Mapping) and m["health"].get("ok") is False]
    if hub_level is None:
        hub_reasons = local_reasons(diag, modules) if not hub_error else []
        hub_level = _worst([r["level"] for r in hub_reasons])
    reasons = sorted(own + hub_reasons, key=lambda r: r["level"] != "red")  # stable: red first, order kept
    level = "red" if hub_error else _worst([hub_level] + [r["level"] for r in own])
    dead = pick(diag, "dead_letters", "counts.dead_letters")
    dead_recent = dicts(pick(dead, "recent", "items")) if isinstance(dead, Mapping) else dicts(dead)
    by_reason = pick(dead, "by_reason") if isinstance(pick(dead, "by_reason"), Mapping) else {}
    last_edition = pick(diag, "last_edition", "review.last_edition")
    last_edition = last_edition if isinstance(last_edition, Mapping) else {}
    block = lambda path: pick(diag, path) if isinstance(pick(diag, path), Mapping) else None  # noqa: E731
    return {
        "workspace": ws.id,
        "level": level,
        "reasons": reasons,
        "hub_error": hub_error,
        "hub_error_kind": hub.get("kind"),
        "hub_error_code": hub.get("code"),
        "hub_status": one_line(pick(diag, "status")),
        "generated_at": pick(diag, "generated_at") or report.get("fetched_at"),
        "fetched_at": report.get("fetched_at"),
        "last_edition_at": pick(last_edition, "published_at", "created_at"),
        "last_edition_id": pick(last_edition, "id", "edition_id"),
        "last_edition_items": count_of(pick(last_edition, "items", "item_count")),
        "backlog": as_int(pick(diag, "review.backlog", "backlog", "review_backlog", "review.pending")),
        "fresh_backlog": block("review.fresh_backlog"),
        "aged_out": block("review.aged_out"),
        "auto_stale": as_int(pick(diag, "review.auto_decided_total")),
        "lease": lease_of(diag),
        "last_review": block("review.last_run"),
        "dead_by_reason": by_reason,
        "dead_letters": count_of(dead) if dead is not None else sum(m["dead_letters"] for m in modules),
        "dead_last_24h": as_int(pick(dead, "last_24h")) if isinstance(dead, Mapping) else None,
        "delivery_failed": as_int(pick(dead, "delivery_failed")) or as_int(by_reason.get("delivery_failed")) or 0,
        # Refused for a configuration mismatch (workspace, contract version): kept until replayed, red like a lost one.
        "config_rejected": as_int(pick(dead, "config_rejected"))
        or sum(as_int(by_reason.get(k)) or 0 for k in CONFIG_REJECT_REASONS),
        "dead_recent": dead_recent,
        "failing": failing,
        "acknowledged": acknowledged,
        "silent": silent,
        "retrying": retrying,
        "slowed": slowed,
        "modules": modules,
        "grading": block("grading"),
        "routines": block("routines"),
        "build": block("build"),
        "canary": block("canary"),
        "storage": block("storage"),
        "maintenance": block("maintenance"),
        "errors": block("errors"),
        "can_ack": isinstance(pick(diag, "severity"), Mapping),  # acknowledgements need a schema 7 hub
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


def stage_of(settings: Any) -> tuple[str, Any]:
    """(stage, since) from GET /settings: 'live', 'staging', or '' when the hub has no stage setting."""
    stage = one_line(pick(settings, "stage.stage")).lower()
    return (stage if stage in STAGES else ""), pick(settings, "stage.since")


def builder_pin_line(conf: Config) -> str:
    """Where the builder PIN comes from, never its value."""
    return "Builder PIN: " + BUILDER_PIN_TEXT.get(conf.builder_pin_source, "not set")


def open_access_line(conf: Config) -> str:
    if conf.open_access:
        return ("Open access: on. No PIN is asked; anyone with the link can edit. Add open_access = false to the "
                "secrets to require the PINs again.")
    return "Open access: off. Editing needs the PIN."


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
    if job.get("ignore_seen") is True:
        parts.append("<span>sending again what was already sent</span>")
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
    ignore_seen = st.checkbox(
        "Send again even if already sent (after lost deliveries)", value=False, key=f"bf_ignore_{ws.id}_{module.id}",
        help="Normally a backfill skips stories the module already sent. Tick this after records were lost on the way "
             "to the hub (Dead letters shows 'delivery failed'): every story in the window is sent again, and the hub "
             "keeps one copy of each.")
    if health_error:
        st.caption(f"Could not list sources from {module.id}/health: {health_error}")
    if not module.can_backfill:
        st.caption(f"Backfill is disabled for {module.id}: url or run_token is not configured.")
    locked = not owner.can_edit(ws)
    if st.button("Run backfill", type="primary", key="bf_run", disabled=not module.can_backfill or locked,
                 help=labels.LOCKED_HELP if locked else None):
        try:
            job, created = api.start_backfill(module, int(days), [str(s) for s in sources], ignore_seen=bool(ignore_seen))
        except api.ApiError as exc:
            st.error(f"Backfill not started: {exc}")
        else:
            scope = f"{len(sources)} source(s)" if sources else "every source"
            if created:
                message = (f"Backfill {clip(job.get('id') or '', 40)} queued for {ws.id}/{module.id}: "
                           f"{plural(int(days), 'day')}, {scope}"
                           + (", sending again what was already sent" if ignore_seen else "") + ". "
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


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _block(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def stories_tile(s: dict) -> str:
    """Stories waiting: the fresh (7-day) backlog, coloured only when its trend is growing (no fixed threshold)."""
    backlog, fresh = s["backlog"], s.get("fresh_backlog")
    auto = f' · {s["auto_stale"]} auto-rejected as stale' if s.get("auto_stale") else ""
    if fresh is None:  # a hub without the fresh count (schema 6 or older): the whole backlog, uncoloured
        return tile("Stories waiting", "—" if backlog is None else backlog, "in all, waiting for the Grader" + auto)
    now = as_int(fresh.get("now"))
    trend = one_line(fresh.get("trend")).lower() or "unknown"
    parts = ["fresh, 7 days"] + ([f"{backlog} in all"] if backlog is not None else []) + [f"trend {trend}"]
    return tile("Stories waiting", "—" if now is None else now, " · ".join(parts) + auto,
                "warn" if trend == "growing" else "")


def aged_out_tile(aged: Mapping | None) -> str:
    """Stories the stale rule closed unread in the last 24 hours; amber when any had arrived while still fresh."""
    if aged is None:
        return ""
    waited = as_int(aged.get("waited_last_24h")) or 0
    return tile("Aged out unread (24 h)", as_int(aged.get("last_24h")) or 0, f"{waited} arrived fresh",
                "warn" if waited > 0 else "")


def agreement_tile(grading: Mapping | None) -> str:
    """How often the owner's grades land in the Grader's band. Information, never a colour."""
    if grading is None:
        return ""
    agreement = _block(grading.get("agreement"))
    month, week = _block(agreement.get("last_30d")), _block(agreement.get("last_7d"))
    n, pct = as_int(month.get("n")) or 0, as_int(month.get("same_band_pct"))
    if not n or pct is None:
        return tile("Grader agreement (30 days)", "no grades yet")
    within = as_int(month.get("within_one_pct"))
    week_pct = as_int(week.get("same_band_pct"))
    detail = (f"n={n} · {'—' if within is None else within}% within one band · 7 days: "
              + (f"{week_pct}%" if week_pct is not None else "no grades"))
    return tile("Grader agreement (30 days)", f"{pct}% same band", detail)


def storage_tile(storage: Mapping | None) -> str:
    """The hub database against the 10 GB D1 limit; amber at 70%."""
    if storage is None:
        return ""
    used = _num(storage.get("db_bytes"))
    limit = _num(storage.get("limit_bytes")) or DB_LIMIT_BYTES
    if used is None:
        return tile("Database size", "unknown", "the database did not report its size")
    pct = _num(storage.get("used_pct"))
    pct = used / limit * 100 if pct is None else pct
    return tile("Database size", f"{used / 1e9:.1f} GB of {limit / 1e9:g} GB",
                f"{used / 1e6:,.0f} MB · {pct:.1f}% used", "warn" if pct >= DB_WARN_PCT else "")


CONFIG_REJECT_REASONS = ("workspace_mismatch", "contract_version")


def dead_letters_tile(s: dict) -> str:
    """Red for records the hub never stored although the module counts them sent (a lost delivery, a configuration
    reject); amber for other recent dead letters."""
    by_reason = dict(s.get("dead_by_reason") or {})
    delivery = s.get("delivery_failed") or 0
    if delivery:
        by_reason["delivery_failed"] = delivery
    kept = ("delivery_failed",) + CONFIG_REJECT_REASONS
    reasons = sorted(by_reason.items(), key=lambda kv: (kv[0] not in kept, -(as_int(kv[1]) or 0)))[:2]
    detail = ", ".join(f"{label_of(k)} {as_int(v) or 0}" for k, v in reasons)
    css = "bad" if delivery or s.get("config_rejected") else "warn" if (s.get("dead_last_24h") or 0) > 0 else ""
    return tile("Dead letters", s["dead_letters"], detail, css)


def reasons_html(reasons: list[dict]) -> str:
    """The workspace's reasons as plain lines, red first (the order summarize gives)."""
    if not reasons:
        return ""
    return ('<div class="health-reasons">' + "".join(
        f'<div class="health-reason {LEVEL_CSS.get(r["level"], "warn")}">{esc(r["message"])}</div>' for r in reasons)
        + "</div>")


def clock_label(value: Any) -> str:
    """'16:30' -> '4:30 PM'; anything else as given."""
    match = CLOCK_RE.match(one_line(value))
    if not match:
        return one_line(value)
    hour = int(match.group(1))
    return f"{hour % 12 or 12}:{match.group(2)} {'AM' if hour < 12 else 'PM'}"


def schedule_text(times: Any, tz_name: str) -> str:
    labels_ = [clock_label(t) for t in as_list(times) if one_line(t)]
    if not labels_:
        return "—"
    return " · ".join(labels_) + " " + zone_label(tz_name, datetime.now(zone(tz_name)))


def prompt_pill(current: Any) -> str:
    if current is True:
        return pill("current")
    if current is False:
        return pill("out_of_date", "out of date")
    return pill("unknown")


def routine_row(name: str, r: Mapping, schedule_zone: str, tz: str, flagged: bool = False) -> list[str]:
    """`flagged`: the hub lists this role's <role>_missed reason, so a never-seen routine is coloured, not neutral."""
    due_state = one_line(r.get("last_due_state")).lower()
    if due_state:
        last = pill(due_state) + (f' <span class="tile-d">{esc(fmt_short(r.get("last_due_at"), tz))}</span>'
                                  if r.get("last_due_at") else "")
    else:
        state = one_line(r.get("state")).lower() or "unknown"
        last = pill(state, css="bad" if flagged and state == "never_seen" else None)
    missed = as_int(r.get("missed_7d")) or 0
    if missed:
        last += f' <span class="tile-d">{esc(missed)} missed in 7 days</span>'
    next_due = r.get("next_due_at")
    return [
        esc(name),
        esc(schedule_text(r.get("schedule"), schedule_zone)),
        esc(relative_time(r.get("last_seen_at"))),
        last,
        esc(f"{fmt_short(next_due, tz)} ({relative_time(next_due)})") if next_due else "—",
        prompt_pill(r.get("prompt_current")),
        f'<span class="mono">{esc(one_line(r.get("cli_version")) or "—")}</span>',
    ]


def refused_tokens_line(failures: Any) -> str:
    """'Refused tokens today: review 2, read 0' when any token class was refused in the last 24 hours."""
    counts = [(TOKEN_NAMES.get(str(cls), label_of(cls).lower()), as_int(v.get("last_24h")) or 0)
              for cls, v in _block(failures).items() if isinstance(v, Mapping)]
    if not any(n for _, n in counts):
        return ""
    counts.sort(key=lambda c: (-c[1], c[0]))
    return ('<div class="refine-note">Refused tokens today: '
            + esc(", ".join(f"{name} {n}" for name, n in counts)) + "</div>")


def routines_html(routines: Mapping | None, tz: str, reason_codes: Any = ()) -> str:
    """The three routines: schedule, last seen, the last scheduled run's state, next due, prompt and CLI version.
    `reason_codes`: the workspace's severity codes; a role with a <role>_missed reason gets a red pill."""
    if routines is None:
        return ""
    schedule_zone = one_line(routines.get("timezone")) or tz
    codes = set(reason_codes or ())
    rows = [routine_row(name, _block(routines.get(role)), schedule_zone, tz, flagged=f"{role}_missed" in codes)
            for role, name in ROLES]
    return ('<div class="health-subhead">Routines</div>'
            + table(["Routine", "Schedule", "Last seen", "Last scheduled run", "Next due", "Prompt", "CLI version"], rows)
            + refused_tokens_line(routines.get("auth_failures")))


def build_text(build: Mapping) -> str:
    sha = one_line(build.get("git_sha")) or "unknown"
    schema, db = as_int(build.get("schema_version")), as_int(build.get("db_schema_version"))
    parts = [f"Hub build {sha}"]
    if schema is not None:
        parts.append(f"schema {schema}" + (f" (database {db})" if db is not None and db != schema else ""))
    if one_line(build.get("rubric_version")):
        parts.append(f"rubric {one_line(build.get('rubric_version'))[:12]}")
    if one_line(build.get("cli_version")):
        parts.append(f"CLI {one_line(build.get('cli_version'))}")
    if build.get("built_at"):
        parts.append(f"deployed {relative_time(build.get('built_at'))}")
    return " · ".join(parts)


def canary_text(canary: Mapping) -> str:
    """The last test record a module sent through the queue (deploy smoke test): how long it took, how long ago."""
    last = _block(canary.get("last"))
    if not last:
        return "Delivery check: no test record has come through yet"
    module = one_line(last.get("module_id")) or "a module"
    via = "the queue" if one_line(last.get("via")) == "queue" else "direct ingest"
    latency = _num(last.get("latency_ms"))
    took = f" in {latency / 1000:.1f} s" if latency is not None else ""
    return f"Delivery check: a test record from {module} came through {via}{took}, {relative_time(last.get('received_at'))}"


def footer_html(s: dict) -> str:
    parts = []
    if s.get("build"):
        parts.append(build_text(s["build"]))
    if s.get("canary") is not None:
        parts.append(canary_text(s["canary"]))
    if s.get("maintenance") is not None:
        last_at = s["maintenance"].get("last_at")
        parts.append(f"cleaned up {relative_time(last_at)}" if last_at else "not cleaned up yet")
    return ('<div class="health-foot">' + "".join(f"<span>{esc(p)}</span>" for p in parts) + "</div>") if parts else ""


def hub_line_html(s: dict) -> str:
    if not s["hub_error"]:
        return ""
    if s.get("hub_error_code") == "schema_outdated":
        what = "Hub waiting for its database upgrade"
    else:
        what = {"unreachable": "Hub unreachable", "unauthorized": "Hub refused the read token"}.get(
            s.get("hub_error_kind"), "Hub error")
    return f'<div class="rejected-rationale"><strong>{esc(what)}</strong> · {esc(s["hub_error"])}</div>'


def failure_reason(row: Mapping) -> str:
    """Why a source is failing, in plain words, from its problem kind, HTTP answer, status and the module's error."""
    kind = one_line(row.get("kind"))
    http = as_int(row.get("http"))
    status = one_line(row.get("status")).lower()
    if kind == "structural_empty":
        n = as_int(row.get("empty_streak")) or 0
        text = ("The page loads, but ZENUX found no stories on it"
                + (f" {n} runs in a row" if n else "") + ". The site's layout may have changed.")
    elif kind == "quota_streak":
        n = as_int(row.get("quota_streak")) or 0
        text = "The daily allowance for this source's service was used up" + (f" {n} runs in a row" if n else "") + "."
    elif http in (401, 403):
        text = f"The site refused ZENUX's request (HTTP {http}). It may block automated readers."
    elif http == 404:
        text = "The page wasn't found (HTTP 404). It may have moved."
    elif http == 429:
        text = "The site asked ZENUX to slow down (HTTP 429, too many requests)."
    elif http is not None and 500 <= http < 600:
        text = f"The site's server had an error (HTTP {http})."
    elif "timeout" in status or "timed out" in one_line(row.get("error")).lower():
        text = "The site didn't answer in time."
    elif http is not None:
        text = f"The last check failed (HTTP {http})."
    else:
        text = "The last check failed."
    error = one_line(row.get("error"))
    return f"{text} Last error: {clip(error, 200)}" if error else text


def light_css(m: Mapping) -> str:
    """The colour of a module's status light: the module pill's (warn for degraded, bad for down, failed, stale)."""
    match = re.search(r'status-pill (\w+)', module_pill(m))
    return match.group(1) if match else "idle"


def light_label(m: Mapping) -> str:
    """'Degraded · 1 failing source': the status in words and its reason, the text of the clickable light."""
    status = label_of(m["status"]) or "unknown"
    reason = clip(one_line(m.get("reason")), 60)
    return (status[:1].upper() + status[1:]) + (f" · {reason}" if reason else "")


def notes_label(m: Mapping) -> str:
    """'1 retrying · 1 slowed' for a module with sources in either state, else ''."""
    parts = [f"{m.get('retrying')} retrying" if m.get("retrying") else "",
             f"{m.get('slowed')} slowed" if m.get("slowed") else ""]
    return " · ".join(p for p in parts if p)


def open_failing(workspace_id: str, module_id: str) -> None:
    ui.open_dialog(DIALOG_FAILING, workspace_id=workspace_id, module_id=module_id)


def module_cells(m: Mapping) -> list[str]:
    """The HTML of a module row's cells but the status (the status is a light, or a pill when it is ok)."""
    backfill = m["backfill"]
    bf = "—"
    if backfill:
        done, total = job_counts(backfill)
        bf = f'{pill(backfill.get("status") or "unknown")} {esc(done)}/{esc(total)}'
    last = (f'{esc(relative_time(m["last_run_at"]))} {pill(m["last_run_status"]) if m["last_run_status"] else ""}'
            if m["last_run_at"] else "never")
    if m.get("running"):
        last += ' <span class="tile-d">running now</span>'
    name = f'<span class="mono">{esc(m["id"])}</span>' + ("" if m["configured"] else ' <span class="tile-d">(hub only)</span>')
    return [name, last, esc(_total(m["events_24h"])), esc(_total(m["events_7d"])), esc(m["failing"]), esc(m["silent"]),
            bf]


def render_module_rows(ws: Workspace, s: dict) -> None:
    """One row per module; a module that is not ok has a clickable status light that opens Sources not working."""
    if not s["modules"]:
        st.markdown('<div class="refine-note">No modules configured or reported.</div>', unsafe_allow_html=True)
        return
    with st.container(key=f"zx_modrows_{ws.id}"):
        head = st.columns(MODULE_WIDTHS, vertical_alignment="center")
        for col, title in zip(head, MODULE_COLUMNS):
            col.markdown(f'<div class="mod-th">{esc(title)}</div>', unsafe_allow_html=True)
        for m in s["modules"]:
            cells = module_cells(m)
            cols = st.columns(MODULE_WIDTHS, vertical_alignment="center")
            cols[0].markdown(f'<div class="mod-td">{cells[0]}</div>', unsafe_allow_html=True)
            with cols[1]:
                note = notes_label(m)
                if m["status"] in QUIET_LIGHT and note:
                    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
                        st.markdown(f'<div class="mod-td">{module_pill(m)}</div>', unsafe_allow_html=True)
                        if st.button(note, key=f"cr_notes_{ws.id}_{m['id']}", type="tertiary",
                                     help="See which sources are retrying or slowed down, and why"):
                            open_failing(ws.id, m["id"])
                            st.rerun(scope="app")
                elif m["status"] in QUIET_LIGHT:
                    st.markdown(f'<div class="mod-td">{module_pill(m)}'
                                + (f' <span class="tile-d">{esc(clip(m["reason"], 60))}</span>' if m["reason"] else "")
                                + '</div>', unsafe_allow_html=True)
                elif st.button(light_label(m), key=f"cr_light_{light_css(m)}_{ws.id}_{m['id']}",
                               help="See which sources are not working, and why"):
                    open_failing(ws.id, m["id"])
                    st.rerun(scope="app")  # the shell draws the dialog at the end of a full run
            for col, cell in zip(cols[2:], cells[1:]):
                col.markdown(f'<div class="mod-td">{cell}</div>', unsafe_allow_html=True)


def source_names(workspace_id: str, module_id: str) -> dict[str, str]:
    """{source key: plain name} from the module's catalog (empty when it cannot be read)."""
    try:
        insp = data.inspect(workspace_id, module_id)
    except api.ApiError:
        return {}
    return {one_line(src.get("key")): one_line(src.get("label")) for src in dicts(pick(insp, "sources", default=[]))
            if one_line(src.get("key")) and one_line(src.get("label"))}


def failing_source_html(row: Mapping, name: str, tz: str, repair: str = "") -> str:
    """One failing source: its name and key, then what is wrong, since when, the streak, its health and, when a fix is
    under way, the line about its open repair (repairs_view.window_line)."""
    health = one_line(row.get("health"))
    facts = [("What's wrong", failure_reason(row)),
             ("Last worked", fmt_short(row.get("last_ok_at"), tz) if row.get("last_ok_at") else "not yet")]
    if as_int(row.get("failures")):
        facts.append(("Failed checks in a row", str(as_int(row.get("failures")))))
    if health:
        facts.append(("Health", label_of(health) + (f" ({HEALTH_WORDS[health]})" if health in HEALTH_WORDS else "")))
    facts.append(("Repair", repair))  # left out while empty
    title = (f'<span class="failing-name">{esc(name)}</span> ' if name else "") + \
        f'<span class="mono">{esc(row.get("key"))}</span>'
    rows = "".join(f'<div class="why-row"><span class="why-label">{esc(k)}</span><span>{esc(v)}</span></div>'
                   for k, v in facts if v)
    return f'<div class="failing-source"><div class="failing-title">{title}</div><div class="why-block">{rows}</div></div>'


def failing_dialog(workspace_id: str, module_id: str) -> None:
    """Sources not working in one module: the module's status and reason, each failing source and why (with its open
    repair, if any), then the retrying, slowed, acknowledged and quiet ones (the same cached health read the card
    used, and the cached GET /repairs)."""
    ws = data.config().workspace(workspace_id)
    if ws is None:
        st.info("This workspace is no longer configured.")
        return
    s = summarize(ws, data.workspace_health(ws.id))
    m = next((x for x in s["modules"] if x["id"] == module_id), None)
    if m is None:
        st.info(f"{module_id} is no longer listed in this workspace.")
        return
    st.markdown(f'<div class="health-head">{module_pill(m)}'
                + (f'<span class="health-sub">{esc(m["reason"])}</span>' if m["reason"] else "") + "</div>",
                unsafe_allow_html=True)
    names = source_names(ws.id, module_id)
    fixes = repairs_view.open_fixes(ws.id)

    def with_repair(r: Mapping) -> str:
        return failing_source_html(r, names.get(r["key"], ""), ws.timezone,
                                   repairs_view.window_line(fixes.get((r["module"], r["key"]))))

    failing = [r for r in s["failing"] if r["module"] == module_id]
    if failing:
        st.markdown("".join(with_repair(r) for r in failing), unsafe_allow_html=True)
    elif m["status"] in QUIET_LIGHT and (m.get("retrying") or m.get("slowed")):
        st.markdown("No source is failing.")
    elif m["status"] == "down":
        st.markdown(f"ZENUX could not reach {module_id} itself: {m['reason'] or 'no answer'}. Its sources are not "
                    "being checked until it answers again.")
    elif m["status"] == "stale":
        st.markdown(f"{module_id} has stopped reporting runs ({m['reason']}). No single source is to blame: the module "
                    "itself is not running.")
    else:
        st.markdown(f"No single source is failing. {m['reason'][:1].upper() + m['reason'][1:] if m['reason'] else ''}")
    retrying = [r for r in s["retrying"] if r["module"] == module_id]
    if retrying:
        st.markdown('<div class="refine-label">Retrying after one missed check (it colours nothing)</div>',
                    unsafe_allow_html=True)
        st.markdown("".join(with_repair(r) for r in retrying), unsafe_allow_html=True)
    slowed = [r for r in s["slowed"] if r["module"] == module_id]
    if slowed:
        st.markdown('<div class="refine-label">Slowed down automatically</div>', unsafe_allow_html=True)
        st.markdown("".join(
            f'<div class="failing-source"><div class="failing-title">'
            + (f'<span class="failing-name">{esc(names.get(r["key"], ""))}</span> ' if names.get(r["key"]) else "")
            + f'<span class="mono">{esc(r["key"])}</span></div><div class="why-block"><div class="why-row">'
            f'<span>{esc(slowed_text(r, ws.timezone))}</span></div></div></div>' for r in slowed), unsafe_allow_html=True)
    acked = [a for a in s["acknowledged"] if a["module"] == module_id]
    if acked:
        st.markdown('<div class="refine-label">Known problems you acknowledged</div>', unsafe_allow_html=True)
        st.markdown(acknowledged_table(acked, ws.timezone), unsafe_allow_html=True)
    silent = [r for r in s["silent"] if r["module"] == module_id]
    if silent:
        st.markdown('<div class="refine-label">Quiet lately (working, but no new stories)</div>', unsafe_allow_html=True)
        st.markdown(silent_table(silent, ws.timezone), unsafe_allow_html=True)
    if failing:
        st.caption(ACK_HINT)
    if st.button("Close", key="dlg_cancel"):
        ui.close_dialog()
        st.rerun()


def failing_title(module_id: str = "", **_: Any) -> str:
    return f"Source health · {module_id}" if module_id else "Source health"


def health_card_html(ws: Workspace, s: dict) -> str:
    level = s["level"]
    css = LEVEL_CSS[level]
    head = (
        '<div class="health-head">'
        f'<span class="health-title">{esc(ws.label)}</span>{pill(level, LEVEL_TEXT[level])}'
        f'<span class="health-sub">{esc(ws.id)} · checked {esc(relative_time(s["fetched_at"]))}</span>'
        "</div>"
    )
    hub_line = hub_line_html(s)
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
    n_acked = len(s.get("acknowledged") or [])
    tiles = "".join([
        tile("Last edition", relative_time(s["last_edition_at"]) if s["last_edition_at"] else "none yet",
             (f'#{s["last_edition_id"]} · {plural(s["last_edition_items"], "item")}' if s["last_edition_at"] else "")),
        stories_tile(s),
        aged_out_tile(s.get("aged_out")),
        tile("Grader lease", lease_text, lease_detail),
        agreement_tile(s.get("grading")),
        dead_letters_tile(s),
        tile("Failing sources", len(s["failing"]), f"{n_acked} acknowledged" if n_acked else "",
             "warn" if s["failing"] else ""),
        tile("Silent sources", len(s["silent"]), "", "warn" if s["silent"] else ""),
        storage_tile(s.get("storage")),
    ])
    return (f'<div class="health-card {css}">{head}{reasons_html(s["reasons"])}{hub_line}'
            f'<div class="tile-grid">{tiles}</div></div>')


def health_tail_html(ws: Workspace, s: dict) -> str:
    """The card's end, under the module rows: the routines table and the footer."""
    routines = routines_html(s.get("routines"), ws.timezone, [r["code"] for r in s["reasons"]])
    return f'<div class="health-tail">{routines}{footer_html(s)}</div>'



def failing_table(rows: list[dict], tz: str) -> str:
    return table(["Module", "Source", "Health", "Last status", "HTTP", "Failures", "Last OK", "Problem"], [[
        esc(r["module"]), f'<span class="mono">{esc(r["key"])}</span>', pill(r["health"] or "unknown"),
        esc(label_of(r["status"]) or "—"), esc(r["http"] if r["http"] is not None else "—"), esc(r["failures"]),
        esc(fmt_short(r["last_ok_at"], tz)), esc(problem_text(r) or "—"),
    ] for r in rows])


def acknowledged_table(rows: list[dict], tz: str) -> str:
    return table(["Module", "Source", "Problem", "Acknowledged", "Note"], [[
        esc(r["module"]), f'<span class="mono">{esc(r["key"])}</span>', esc(problem_text(r) or "—"),
        esc(fmt_short(r.get("acked_at"), tz)), esc(clip(r.get("note") or "—", 200)),
    ] for r in rows])


def disagreements_table(rows: list[dict], tz: str) -> str:
    """The largest gaps between the owner's grade and the Grader's score (last 30 days)."""
    def grader(r: Mapping) -> str:
        score = as_int(r.get("grader_score"))
        band = label_of(r.get("grader_band"))
        return f"{score} ({band})" if score is not None and band else str(score) if score is not None else band or "—"

    return table(["Story", "Your verdict", "Grader score", "Graded"], [[
        esc(clip(one_line(r.get("title")) or f"event #{one_line(r.get('event_id')) or '?'}", 140)),
        esc(label_of(r.get("owner_verdict")) or "—"), esc(grader(r)), esc(fmt_short(r.get("graded_at"), tz)),
    ] for r in rows])


def errors_table(rows: list[dict], tz: str) -> str:
    return table(["When", "Kind", "Route", "What happened"], [[
        esc(fmt_short(r.get("at"), tz)), esc(label_of(r.get("kind")) or "—"),
        f'<span class="mono">{esc(clip(r.get("route") or "—", 60))}</span>', esc(clip(r.get("message"), 300)),
    ] for r in rows[:20]])


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


def _source_ident(ws: Workspace, row: Mapping) -> str:
    return f"{ws.id}_{row['module']}_{row['key']}"


def _ack_call(ws: Workspace, module_id: str, source_key: str, note: str):
    def call(token: str) -> Any:
        try:
            return api.ack_source(ws, module_id, source_key, note, token)
        finally:
            data.clear_health()  # also after a 409: the problem changed since the panel was read
    return call


def _unack_call(ws: Workspace, module_id: str, source_key: str):
    def call(token: str) -> Any:
        try:
            return api.unack_source(ws, module_id, source_key, token)
        finally:
            data.clear_health()
    return call


def acknowledge(ws: Workspace, module_id: str, source_key: str, note: str) -> None:
    """POST /admin/sources/ack through ui.write (toast, undo = unack), then a full rerun with a fresh health read."""
    name = f"{module_id}/{source_key}"
    result = ui.write(ws, _ack_call(ws, module_id, source_key, note), toast=f"Acknowledged {name}.",
                      undo=lambda res: (f"Acknowledged {name}.", _unack_call(ws, module_id, source_key)))
    if result is not None:
        st.rerun()


def unacknowledge(ws: Workspace, module_id: str, source_key: str, note: str = "") -> None:
    """POST /admin/sources/unack through ui.write (toast, undo = ack with the same note)."""
    name = f"{module_id}/{source_key}"

    def removed(res: Any) -> bool:
        return not (isinstance(res, Mapping) and res.get("removed") is False)

    result = ui.write(
        ws, _unack_call(ws, module_id, source_key),
        toast=lambda res: "Acknowledgement removed." if removed(res) else f"{name} had no acknowledgement to remove.",
        undo=lambda res: (f"Removed the acknowledgement for {name}.", _ack_call(ws, module_id, source_key, note))
        if removed(res) else None)
    if result is not None:
        st.rerun()


def render_ack_controls(ws: Workspace, rows: list[dict]) -> None:
    st.caption("Acknowledge a problem you already know about: the source stops coloring the workspace until it "
               "recovers or fails in a new way.")
    for row in rows:
        ident = _source_ident(ws, row)
        label_col, note_col, button_col = st.columns([3, 4, 2], vertical_alignment="center")
        label_col.markdown(f'<span class="mono">{esc(row["module"])}/{esc(row["key"])}</span>', unsafe_allow_html=True)
        note = note_col.text_input("Note (optional)", key=f"ack_note_{ident}", label_visibility="collapsed",
                                   placeholder="Why it can wait (optional)", max_chars=api.ACK_NOTE_MAX)
        with button_col:
            if ui.write_button("Acknowledge", ws=ws, key=f"ack_{ident}"):
                acknowledge(ws, row["module"], row["key"], note or "")


def render_unack_controls(ws: Workspace, rows: list[dict]) -> None:
    for row in rows:
        label_col, button_col = st.columns([7, 2], vertical_alignment="center")
        label_col.markdown(f'<span class="mono">{esc(row["module"])}/{esc(row["key"])}</span>', unsafe_allow_html=True)
        with button_col:
            if ui.write_button("Remove acknowledgement", ws=ws, key=f"unack_{_source_ident(ws, row)}"):
                unacknowledge(ws, row["module"], row["key"], row.get("note") or "")


def render_card_display(ws: Workspace, s: dict) -> None:
    """The health card (its top, the module rows with their status lights, the routines and footer) and its
    display-only lists (the part the 60-second fragment redraws)."""
    with st.container(key=f"zx_hcard_{LEVEL_CSS[s['level']]}_{ws.id}"):
        st.markdown(health_card_html(ws, s), unsafe_allow_html=True)
        render_module_rows(ws, s)
        st.markdown(health_tail_html(ws, s), unsafe_allow_html=True)
    if s["silent"]:
        with st.expander(f"{ws.id} · silent sources · {len(s['silent'])}"):
            st.markdown(silent_table(s["silent"], ws.timezone), unsafe_allow_html=True)
    if s["retrying"]:
        with st.expander(f"{ws.id} · retrying after one missed check · {len(s['retrying'])}"):
            st.markdown(failing_table(s["retrying"], ws.timezone), unsafe_allow_html=True)
    if s["slowed"]:
        with st.expander(f"{ws.id} · slowed down automatically · {len(s['slowed'])}"):
            st.markdown(table(["Module", "Source", "Checked now", "Normally", "Since"], [[
                esc(r["module"]), f'<span class="mono">{esc(r["key"])}</span>', esc(every_text(r["effective_minutes"])),
                esc(every_text(r["base_minutes"])), esc(fmt_short(r["since"], ws.timezone)),
            ] for r in s["slowed"]]), unsafe_allow_html=True)
    biggest = dicts(pick(s.get("grading"), "agreement.biggest", default=[]))
    if biggest:
        with st.expander(f"{ws.id} · biggest disagreements · {len(biggest)}"):
            st.markdown(disagreements_table(biggest, ws.timezone), unsafe_allow_html=True)
    hub_errors = dicts(pick(s.get("errors"), "recent", default=[]))
    if hub_errors:
        with st.expander(f"{ws.id} · recent hub errors · {len(hub_errors)}"):
            st.markdown(errors_table(hub_errors, ws.timezone), unsafe_allow_html=True)
    if s["dead_recent"]:
        with st.expander(f"{ws.id} · recent dead letters · {len(s['dead_recent'])}"):
            st.markdown(dead_table(s["dead_recent"], ws.timezone), unsafe_allow_html=True)


@st.fragment(run_every=HEALTH_REFRESH_SECONDS)
def health_card_live(workspace_id: str) -> None:
    """One workspace's card, redrawn every 60 s. No input field lives in here (the status lights only open a
    window)."""
    ws = data.config().workspace(workspace_id)
    if ws is not None:
        render_card_display(ws, summarize(ws, data.workspace_health(ws.id)))


def render_stage(ws: Workspace) -> None:
    """'Stage: live since Sat Oct 4' or 'staging', and the switch (POST /admin/stage) behind a confirmation."""
    try:
        stage, since = stage_of(data.settings(ws.id))
    except api.ApiError as exc:
        st.caption(f"Stage unknown: GET /settings failed ({exc}).")
        return
    if not stage:
        st.caption("Stage unknown: this hub has no stage setting.")
        return
    target = "staging" if stage == "live" else "live"
    text_col, button_col = st.columns([5, 2], vertical_alignment="center")
    if stage == "live":
        text = "Stage: live" + (f" since {fmt_day(since, ws.timezone)}" if since else "")
    else:
        text = "Stage: staging (collecting; no briefings until sign-off or Go live)"
    text_col.markdown(f'<div class="refine-note">{esc(text)}</div>', unsafe_allow_html=True)
    with button_col:
        if ui.write_button("Switch to staging" if stage == "live" else "Go live", ws=ws, key=f"cr_stage_{ws.id}"):
            ui.ask_confirm(
                f"Switch {ws.label} to {target}?",
                ("The workspace keeps collecting but publishes no briefings until the analyst signs off or you go "
                 "live again." if target == "staging" else
                 "Briefings start at the next scheduled ZENUX editor run. Going live here records a sign-off by the "
                 "builder."),
                "Switch to staging" if target == "staging" else "Go live",
                lambda: set_stage(ws, target, stage))


def _stage_call(ws: Workspace, stage: str):
    def call(token: str) -> Any:
        try:
            return api.set_stage(ws, token, stage)
        finally:
            data.clear_health()  # awaiting_signoff comes and goes with the stage
    return call


def set_stage(ws: Workspace, target: str, previous: str) -> None:
    """POST /admin/stage {stage}: toast 'Stage is now <stage>.', undo = the previous stage. Runs inside the confirm."""
    ui.write(ws, _stage_call(ws, target), toast=f"Stage is now {target}.",
             undo=lambda res: (f"Stage is now {target}.", _stage_call(ws, previous)) if previous in STAGES else None)


def _mirror_module(key: str) -> None:
    links.set_focus(module=st.session_state.get(key) or None)


def render_module_pills(ws: Workspace, s: dict, mirror: bool) -> None:
    """'Open a module': the technical module view of the chosen module right below. The current workspace's choice
    is mirrored as `module` in the page's link."""
    options = [m["id"] for m in s["modules"]]
    if not options:
        return
    key = f"cr_module_{ws.id}"
    if mirror and key not in st.session_state and links.focus("module") in options:
        st.session_state[key] = links.focus("module")
    choice = st.pills("Open a module", options, key=key, selection_mode="single",
                      on_change=_mirror_module if mirror else None, args=(key,) if mirror else None)
    if choice:
        render_module_view(ws, choice)


def render_workspace_controls(ws: Workspace, mirror: bool) -> None:
    """Under one workspace card, outside its fragment: acknowledgements, the stage, the module view."""
    s = summarize(ws, data.workspace_health(ws.id))  # the same cached read the card used
    if s["failing"]:
        with st.expander(f"{ws.id} · failing sources · {len(s['failing'])}"):
            st.markdown(failing_table(s["failing"], ws.timezone), unsafe_allow_html=True)
            if s["can_ack"]:
                render_ack_controls(ws, s["failing"])
    if s["acknowledged"]:
        with st.expander(f"{ws.id} · acknowledged sources · {len(s['acknowledged'])}"):
            st.markdown(acknowledged_table(s["acknowledged"], ws.timezone), unsafe_allow_html=True)
            render_unack_controls(ws, s["acknowledged"])
    if not s["hub_error"]:
        render_stage(ws)
    render_module_pills(ws, s, mirror)


def render_health(conf: Config, current: Workspace | None) -> None:
    head_col, button_col = st.columns([5, 1], vertical_alignment="center")
    head_col.markdown(section_label("Today's diagnostics · every workspace",
                                    f"refreshes every {HEALTH_REFRESH_SECONDS} s"), unsafe_allow_html=True)
    if button_col.button("Refresh now", key="health_refresh"):
        data.clear_health()
        data.clear_reads()
    for ws in conf.workspaces:
        with st.container(key=f"cr_ws_{ws.id}"):
            health_card_live(ws.id)
            render_workspace_controls(ws, mirror=current is not None and ws.id == current.id)


# ---------------------------------------------------------------------------------------------- module view


def _yes(value: Any) -> str:
    return "yes" if value is True else "no" if value is False else "—"


def _rate(value: Any) -> str:
    rate = _num(value)
    return "—" if rate is None else f"{rate * 100:.1f}%"


def module_line(insp: Mapping, card: Mapping | None, tz: str) -> str:
    """'Catalog 0.1.0-3f2a9c1b7d4e · pushed Oct 4 · 12:00 PM · git abc123def456 · 188 sources (160 on) · 142
    entities' (the counts from GET /modules, else counted in the inspector)."""
    mod = _block(insp.get("module"))
    catalog = _block((card or {}).get("catalog"))
    counts = _block((card or {}).get("counts"))
    version = one_line(pick(mod, "catalog_version")) or one_line(catalog.get("version")) or "—"
    parts = [f"Catalog {version}", f"pushed {fmt_short(pick(mod, 'pushed_at') or catalog.get('pushed_at'), tz)}"]
    if one_line(catalog.get("git_sha")):
        parts.append(f"git {one_line(catalog.get('git_sha'))}")
    sources = dicts(insp.get("sources"))
    enabled = sum(1 for src in sources if src.get("enabled") is not False)
    on = as_int(counts.get("sources_enabled"))
    parts.append(f"{as_int(counts.get('sources')) or len(sources)} sources ({enabled if on is None else on} on)")
    parts.append(plural(as_int(counts.get("entities")) or len(dicts(insp.get("entities"))), "entity", "entities"))
    return " · ".join(parts)


def lanes_table(insp: Mapping) -> str:
    rows = [[f'<span class="mono">{esc(one_line(lane.get("id")))}</span>', esc(one_line(lane.get("label"))),
             esc(one_line(lane.get("column"))), esc(as_int(lane.get("source_count")) or 0),
             esc(as_int(lane.get("items_7d")) or 0)] for lane in dicts(insp.get("lanes"))]
    return table(["Lane", "Label", "Column", "Sources", "Items 7 days"], rows) if rows else ""


def sources_table_html(insp: Mapping, tz: str) -> str:
    rows = []
    for src in dicts(insp.get("sources")):
        stats, health = _block(src.get("stats")), _block(src.get("health"))
        state = one_line(health.get("state")) or "—"
        status = one_line(health.get("last_status"))
        url = safe_url(src.get("url"))
        rows.append([
            f'<span class="mono">{esc(one_line(src.get("key")))}</span>' + (f' {link(url, "link", "")}' if url else ""),
            esc(one_line(src.get("label"))), esc(one_line(src.get("origin"))),
            esc(one_line(src.get("entity_id")) or "—"), esc(one_line(src.get("lane")) or "—"),
            esc(one_line(src.get("connector"))), esc(one_line(src.get("kind"))), esc(one_line(src.get("trust"))),
            esc(_yes(src.get("enabled"))) + (f' <span class="tile-d">{esc(clip(src.get("off_reason"), 120))}</span>'
                                             if one_line(src.get("off_reason")) else ""),
            pill(state, css=SOURCE_STATE_CSS.get(state)) + (f' <span class="tile-d">{esc(status)}</span>' if status else ""),
            esc(fmt_short(health.get("last_ok_at"), tz)),
            esc(f"{as_int(src.get('cadence_minutes'))} min" if as_int(src.get("cadence_minutes")) else "—"),
            esc(f"{as_int(stats.get('items_7d')) or 0} / {as_int(stats.get('items_30d')) or 0}"),
            esc(as_int(stats.get("briefing_30d")) or 0), esc(_rate(stats.get("hit_rate"))),
            esc("muted" if isinstance(src.get("muted"), Mapping) else "—"),
        ])
    return table(["Key", "Label", "Origin", "Entity", "Lane", "Connector", "Kind", "Trust", "Enabled", "Health",
                  "Last OK", "Cadence", "Items 7/30 d", "Briefing 30 d", "Hit rate", "Muted"], rows) if rows else ""


def entities_table_html(insp: Mapping) -> str:
    rows = []
    for ent in dicts(insp.get("entities")):
        stats, coverage = _block(ent.get("stats")), _block(ent.get("coverage"))
        flags = [flag for flag, _, _ in labels.COVERAGE_ICONS if coverage.get(flag) is True]
        keys = [one_line(k) for k in as_list(ent.get("source_keys")) if one_line(k)]
        rows.append([
            f'<span class="mono">{esc(one_line(ent.get("id")))}</span>', esc(one_line(ent.get("name"))),
            esc(one_line(ent.get("role"))), esc(one_line(ent.get("category"))), esc(one_line(ent.get("ownership")) or "—"),
            esc(", ".join(one_line(t) for t in as_list(ent.get("tickers")) if one_line(t)) or "—"),
            esc(", ".join(flags) or "—"),
            f'<span class="mono">{esc(", ".join(keys) or "—")}</span>',
            esc(f"{as_int(stats.get('items_7d')) or 0} / {as_int(stats.get('items_30d')) or 0} · "
                f"briefing {as_int(stats.get('briefing_30d')) or 0}"),
            esc("muted" if isinstance(ent.get("muted"), Mapping) else "—"),
            esc("starred" if isinstance(ent.get("starred"), Mapping) else "—"),
        ])
    return table(["Id", "Name", "Role", "Category", "Ownership", "Tickers", "Coverage", "Source keys",
                  "Items 7/30 d", "Muted", "Starred"], rows) if rows else ""


def orphans_table(insp: Mapping) -> str:
    rows = [[f'<span class="mono">{esc(one_line(o.get("source_key")))}</span>', esc(as_int(o.get("events")) or 0),
             esc(_yes(o.get("retired")))] for o in dicts(insp.get("orphans"))]
    return table(["Source key", "Events", "Retired"], rows) if rows else ""


def _module_card(ws: Workspace, module_id: str) -> Mapping | None:
    try:
        body = data.modules(ws.id)
    except api.ApiError:
        return None
    return next((m for m in dicts(pick(body, "modules", default=[])) if one_line(m.get("id")) == module_id), None)


def render_module_view(ws: Workspace, module_id: str) -> None:
    """The technical module view: catalog, lanes, sources, entities and orphans (GET /modules/<id>/inspect), then the
    module snapshot. A module without a catalog shows the hub's sentence and the snapshot only."""
    with st.container(border=True, key=f"cr_view_{ws.id}_{module_id}"):
        st.markdown(section_label(f"{ws.id}/{module_id}", "technical module view"), unsafe_allow_html=True)
        try:
            insp = data.inspect(ws.id, module_id)
        except api.ApiError as exc:
            insp = None
            if exc.code == CATALOG_MISSING:
                st.info(getattr(exc, "detail", None) or f"Coverage details for {module_id} appear after the next deploy.")
            else:
                st.markdown(empty_state(f"Could not load the inspector for {module_id}.", str(exc)), unsafe_allow_html=True)
        if isinstance(insp, Mapping):
            st.markdown(f'<div class="refine-note">{esc(module_line(insp, _module_card(ws, module_id), ws.timezone))}'
                        "</div>", unsafe_allow_html=True)
            lanes = lanes_table(insp)
            if lanes:
                st.markdown(lanes, unsafe_allow_html=True)
            sources, entities = dicts(insp.get("sources")), dicts(insp.get("entities"))
            with st.expander(f"{module_id} · sources · {len(sources)}"):
                st.markdown(sources_table_html(insp, ws.timezone) or empty_state("No sources in the catalog."),
                            unsafe_allow_html=True)
            with st.expander(f"{module_id} · entities · {len(entities)}"):
                st.markdown(entities_table_html(insp) or empty_state("No entities in the catalog."),
                            unsafe_allow_html=True)
            orphans = dicts(insp.get("orphans"))
            if orphans:
                st.markdown(f'<div class="health-subhead">Orphans · {len(orphans)} source keys with events but not '
                            "in the catalog</div>" + orphans_table(insp), unsafe_allow_html=True)
        render_snapshot(ws, module_id)


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


def render_snapshot(ws: Workspace, module_id: str) -> None:
    st.markdown(section_label("Module snapshot", f"counts by lane and the latest {SNAPSHOT_LIMIT} events"),
                unsafe_allow_html=True)
    try:
        body = data.snapshot(ws.id, module_id, SNAPSHOT_LIMIT)
    except api.ApiError as exc:
        st.markdown(empty_state(f"Could not load the snapshot for {ws.id}/{module_id}.", str(exc)), unsafe_allow_html=True)
        return
    c24, c7 = lane_counts(body, "24h"), lane_counts(body, "7d")
    if not c24 and not c7:
        try:
            entry = hub_modules((data.workspace_health(ws.id).get("hub") or {}).get("data")).get(module_id) or {}
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
    yes = lambda ok: pill("ok", "set") if ok else pill("missing")  # noqa: E731
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
        st.caption(builder_pin_line(conf))
        st.caption(open_access_line(conf))
        for problem in conf.problems:
            st.caption(problem)
        st.caption("Values come from st.secrets and are never shown here.")


def render(conf: Config, ws: Workspace) -> None:
    """The Control room: today's diagnostics, backfill, coverage requests and source repairs to review, configuration
    (builder only)."""
    if not owner.is_builder(conf):
        st.info(NOT_BUILDER)
        return
    render_health(conf, ws)
    render_backfill(conf, ws)
    radar_view.render_review(conf)
    repairs_view.render_review(conf)
    render_config(conf)


ui.register_dialog(DIALOG_FAILING, failing_title, failing_dialog, width="large")
