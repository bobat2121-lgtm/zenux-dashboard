"""Hub and module response bodies, shaped as hub/src/brain.js and the module SDK return them. Fresh copies per call.

A few deliberately hostile values (a javascript: link, markup in titles, blank lines in text) check the escaping.
The schema v8 bodies (docs/SPEC-PHASE02.md section 5) are at the end: editions_v8, rejected_v8, modules, inspect,
mutes, mute_preview, stars, star_preview, preferences, settings, volume_preview, brief, radar_v8, effective and the
write answers. helpers.hub_defaults routes every read to them. View builders keep extra bodies in their own
fixtures_<area>.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def iso(hours_ago: float = 0.0) -> str:
    moment = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _items(edition_id: int, n: int) -> list[dict]:
    base = 100 * edition_id
    return [
        {
            "id": base + 1, "edition_id": edition_id, "rank": 1, "event_id": 9001 + 10 * n, "event_ids": [],
            "score": 93, "tier": 3, "module": "ai-infra", "story_id": "s-100",
            "headline": "Neocloud signs 200 MW <lease> with hyperscaler",
            "text": "The company signed a 15-year lease for 200 MW of critical IT capacity.\n\nEnergization is planned for 2027.",
            "metrics": [{"label": "Critical IT", "value": "200 MW", "source_url": "https://example.com/neocloud-lease"},
                        {"label": "Term", "value": "15 years"}],
            "sources": [{"url": "https://example.com/neocloud-lease", "title": "Company newsroom"},
                        {"url": "https://www.sec.gov/Archives/edgar/data/1/0001.htm"}],
            "event": {"title": "Neocloud signs lease", "url": "https://example.com/neocloud-lease", "module": "ai-infra",
                      "source_key": "neocloud-ir", "lane": "companies", "trust": "primary", "published_at": iso(30)},
            "feedback": [],
        },
        {
            "id": base + 2, "edition_id": edition_id, "rank": 2, "event_id": 9002 + 10 * n, "event_ids": [9003 + 10 * n],
            "score": 78, "tier": 3, "module": "defense-unmanned", "story_id": "s-101",
            "headline": "Army awards $48M counter-UAS order",
            "text": "The Army awarded a $48 million firm-fixed-price order for counter-UAS interceptors.",
            "metrics": [{"label": "Obligated", "value": "$48M"}],
            "sources": [{"url": "javascript:alert(1)", "title": "bad link"},
                        {"url": "https://www.war.gov/News/Contracts/", "title": "war.gov"}],
            "event": None,
            "feedback": [{"id": 4, "item_id": base + 2, "event_id": 9002 + 10 * n, "verdict": "digest", "score": 80,
                          "note": None, "scope": "item", "created_at": iso(1)}] if n == 0 else [],
        },
    ]


def editions(count: int = 2, start_id: int = 12) -> dict:
    out = []
    for n in range(count):
        eid = start_id - n
        out.append({
            "id": eid, "run_id": f"rv-2026100{n}T113000Z-0000abcd", "published_at": iso(2 + 12 * n),
            "item_count": 2, "candidate_count": 41, "backlog": 0, "rubric_version": "sha256:abc",
            "note": "Two items cleared the bar." if n == 0 else f"Edition {eid} note",
            "items": _items(eid, n),
        })
    return {"editions": out, "next_before": None, "has_more": False}


def empty_edition() -> dict:
    return {"editions": [{"id": 5, "run_id": "rv-20261003T113000Z-0000beef", "published_at": iso(1), "item_count": 0,
                          "candidate_count": 12, "backlog": 0, "note": None, "items": []}],
            "next_before": None, "has_more": False}


def rejected() -> dict:
    rows = [
        {"event_id": 7001, "decision": "rejected", "score": 31, "tier": 3, "reason_code": "below_materiality",
         "rationale": "Routine monthly update; no material change.", "canonical_event_id": None, "story_id": None,
         "decided_at": iso(5), "run_id": "rv-1", "edition_id": 12, "title": "Miner monthly production update",
         "url": "https://example.com/miner-update", "module": "ai-infra", "source_key": "miner-ir", "lane": "companies",
         "trust": "primary", "kind": "press_release", "published_at": iso(7),
         "feedback": [{"id": 2, "item_id": None, "event_id": 7001, "verdict": "watch", "score": 55, "note": None,
                       "scope": "item", "created_at": iso(4)}]},
        {"event_id": 7002, "decision": "duplicate", "score": 78, "tier": None, "reason_code": "duplicate",
         "rationale": "Same award as #9002.", "canonical_event_id": 9002, "story_id": "s-101", "decided_at": iso(6),
         "run_id": "rv-1", "edition_id": 12, "title": "Same award via trade press", "url": "https://example.com/dup",
         "module": "defense-unmanned", "source_key": "defense-news", "lane": "trade_press", "trust": "press",
         "kind": "article", "published_at": iso(8), "feedback": []},
        {"event_id": 7003, "decision": "rejected", "score": 22, "tier": None, "reason_code": "out_of_scope",
         "rationale": None, "canonical_event_id": None, "story_id": None, "decided_at": iso(30), "run_id": "rv-0",
         "edition_id": 11, "title": "Drone unveiled at trade show", "url": "https://example.com/show",
         "module": "defense-unmanned", "source_key": "uas-vision", "lane": "trade_press", "trust": "press",
         "kind": "article", "published_at": iso(31), "feedback": []},
    ]
    return {"days": 3, "since": iso(72), "counts": {"rejected": 2, "duplicate": 1, "already_covered": 0},
            "total": 3, "items": rows}


def rules() -> dict:
    return {
        "precedents": [
            {"id": "R-0001", "precedent_id": "R-0001", "kind": "rule", "status": "active", "origin": "owner+refiner",
             "text": "Competitive resizing ranks above people on the importance ladder.", "draft_id": 20,
             "created_at": iso(48), "activated_at": iso(48), "retired_at": None, "updated_at": iso(48)},
            {"id": "I-0001", "precedent_id": "I-0001", "kind": "item", "status": "active", "origin": "feedback:3+refiner",
             "text": "A miner's routine monthly update ranks only on a material change.", "draft_id": 21,
             "created_at": iso(30), "activated_at": iso(30), "retired_at": None, "updated_at": iso(30)},
            {"id": "R-0002", "precedent_id": "R-0002", "kind": "rule", "status": "retired", "origin": "owner",
             "text": "Old retired rule about space programs.", "draft_id": 5, "created_at": iso(200),
             "activated_at": iso(200), "retired_at": iso(100), "updated_at": iso(100)},
        ],
        "drafts": [
            {"id": 32, "kind": "item", "text": "Grid interconnection approvals for 100 MW+ sites lead.", "origin": "feedback",
             "feedback_id": 7, "status": "queued", "proposal": None, "proposed_at": None, "precedent_id": None,
             "decision_note": None, "decided_at": None, "created_at": iso(3), "updated_at": iso(3),
             "context": {"item_id": 1201, "edition_id": 12, "event_id": 9001, "headline": "Neocloud signs 200 MW lease",
                         "url": "https://example.com/neocloud-lease", "verdict": "lead", "score": 92, "scope": "case"}},
            {"id": 31, "kind": "rule", "text": "counter drone orders under 1M are watch", "origin": "owner",
             "feedback_id": None, "context": None, "status": "proposed",
             "proposal": {"text": "Counter-UAS orders under $1M score in the watch band unless the buyer is new.",
                          "rationale": "Generalised from three grades.", "kind": "rule"},
             "proposed_at": iso(20), "precedent_id": None, "decision_note": None, "decided_at": None,
             "created_at": iso(26), "updated_at": iso(20)},
            {"id": 20, "kind": "rule", "text": "resizing over people", "origin": "owner", "feedback_id": None,
             "context": None, "status": "approved", "proposal": {"text": "Competitive resizing ranks above people."},
             "proposed_at": iso(50), "precedent_id": "R-0001", "decision_note": "good", "decided_at": iso(48),
             "created_at": iso(60), "updated_at": iso(48)},
        ],
        "counts": {"active": 2, "retired": 1, "draft": 0, "queued": 1, "proposed": 1, "approved": 1, "rejected": 0},
    }


def radar() -> dict:
    return {
        "requests": [
            {"id": 42, "kind": "missed_story", "text": "We missed the Shield AI Hivemind award",
             "url": "https://example.com/missed", "module": "defense-unmanned", "status": "queued", "proposal": None,
             "proposed_at": None, "decision_note": None, "decided_at": None, "created_at": iso(2), "updated_at": iso(2)},
            {"id": 41, "kind": "track_source", "text": "Follow the Texas PUC large-load docket", "url": None,
             "module": "ai-infra", "status": "proposed", "created_at": iso(26), "updated_at": iso(20),
             "proposed_at": iso(20), "decision_note": None, "decided_at": None,
             "proposal": {
                 "summary": "Add the PUCT docket filings feed to ai-infra.",
                 "sources": [{"key": "puct-large-load", "connector": "html-list", "module": "ai-infra",
                              "lane": "power_policy", "trust": "official", "cadence_minutes": 360,
                              "config": {"url": "https://interchange.puc.texas.gov/"}}],
                 "registry_changes": [{"op": "add_alias", "entity_id": "oncor", "name": "Oncor Electric Delivery"}],
                 "notes": "Verified one fetch: 200, 40 filings listed.",
             }},
            {"id": 40, "kind": "new_coverage", "text": "Cover sodium-ion storage for DCs", "url": None, "module": None,
             "status": "approved_pending_apply", "proposal": {"summary": "Add two trade feeds."}, "proposed_at": iso(95),
             "decision_note": "Start with the trade feeds", "decided_at": iso(90), "created_at": iso(100),
             "updated_at": iso(90)},
        ],
    }


def _lanes(day: dict, week: dict) -> dict:
    return {"last_24h": day, "last_7d": week, "total_24h": sum(day.values()), "total_7d": sum(week.values())}


def diagnostics(workspace: str = "pilot", *, failing: bool = True, legacy: bool = False,
                awaiting_signoff: bool = False) -> dict:
    """GET /diagnostics of a schema 7+ hub (docs/SPEC-PHASE01.md 4.6), with last_edition and routines (the Grader's
    next_due_at 1.5 hours ahead); legacy=True: a schema 5/6 hub without severity, routines, grading, storage, build,
    canary, maintenance, errors and the fresh backlog; awaiting_signoff=True: a staging workspace (v8)."""
    sam = {"module_id": "defense-unmanned", "source_key": "sam-opps", "health": "backoff", "last_status": "error",
           "last_http_status": 429, "consecutive_failures": 3, "last_ok_at": iso(30), "last_run_at": iso(0.35)}
    body = {
        "service": "zenux-hub", "workspace": workspace, "generated_at": iso(0),
        "status": "degraded" if failing else "ok",
        "counts": {"events": 1824, "dead_letters": 2},
        "modules": [
            {"module_id": "ai-infra", "version": "0.1.0", "status": "ok", "stale": False, "retired": False,
             "last_run": {"run_id": "run-a1", "started_at": iso(0.3), "ended_at": iso(0.25), "status": "ok",
                          "received_at": iso(0.25), "sources": 40},
             "sources": {"total": 40, "failing": 0, "silent": 0, "retired": 0},
             "events": _lanes({"companies": 12, "trade_press": 30}, {"companies": 80, "trade_press": 190}),
             "failing": [], "silent": [],
             "dead_letters": {"total": 0, "last_24h": 0, "by_reason": {}, "last_at": None}, "retired_sources": []},
            {"module_id": "defense-unmanned", "version": "0.1.0", "status": "partial", "stale": False, "retired": False,
             "last_run": {"run_id": "run-d1", "started_at": iso(0.4), "ended_at": iso(0.35), "status": "partial",
                          "received_at": iso(0.35), "sources": 37},
             "sources": {"total": 37, "failing": 1 if failing else 0, "silent": 1, "retired": 0},
             "events": _lanes({"procurement": 9}, {"procurement": 61, "budgets": 4}),
             "failing": [sam] if failing else [],
             "silent": [{"module_id": "defense-unmanned", "source_key": "dod-budget", "health": "healthy",
                         "warnings": ["silent_for_96h"], "last_new_at": iso(100), "last_run_at": iso(0.35)}],
             "dead_letters": {"total": 2, "last_24h": 1, "by_reason": {"invalid": 2}, "last_at": iso(10)},
             "retired_sources": []},
        ],
        "dead_letters": {"total": 2, "last_24h": 1, "by_reason": {"invalid": 2}, "unattributed": 0,
                         "recent": [{"id": 3, "received_at": iso(10), "reason": "invalid", "key": "defense-unmanned:x:1"}]},
        "review": {
            "cursor": {"last_event_id": 1700, "last_run_id": "rv-1", "last_edition_id": 12, "updated_at": iso(2)},
            "latest_event_id": 1757, "backlog": 57, "backlog_oldest_event_id": 1701,
            "auto_decided_total": 807, "auto_decided_last": iso(0.5),
            "lease": {"state": "active", "held": True, "run_id": "rv-13", "agent": "grader", "leased_at": iso(0.2),
                      "lease_expires_at": iso(-0.5), "candidates": 57, "decided": 10},
            "last_run": {"run_id": "rv-1", "status": "published", "leased_at": iso(2.2), "finished_at": iso(2)},
        },
        "last_edition": {"id": 12, "run_id": "rv-1", "published_at": iso(2), "item_count": 2, "candidate_count": 41,
                         "backlog": 0},
    }
    if legacy:
        return body
    for module, minutes in zip(body["modules"], (15, 21)):
        module.update(configured=True, interval_minutes=10, stale_after_minutes=30, minutes_since_run=minutes,
                      unfinished_runs_24h=0)
    sam.update(kind="failing", empty_streak=0, quota_streak=0, fingerprint="failing:error:429", acknowledged=None)
    body["dead_letters"]["delivery_failed"] = 0
    body["severity"] = {
        "level": "amber" if failing else "green",
        "reasons": [{"level": "amber", "code": "source_failing",
                     "message": "defense-unmanned/sam-opps is failing (HTTP 429, 3 runs)", "module": "defense-unmanned",
                     "source_key": "sam-opps", "since": iso(30), "count": None}] if failing else [],
        "acknowledged": [],
    }
    if awaiting_signoff:
        body["severity"]["level"] = "amber"
        body["severity"]["reasons"].append({
            "level": "amber", "code": "awaiting_signoff", "module": None, "source_key": None, "since": iso(48),
            "count": None, "message": "This workspace is collecting. Briefings start after the analyst signs off."})
    body["review"].update({
        "candidate_limit": 800, "page_size": 100, "lease_minutes": 120,
        "fresh_backlog": {"now": 21, "trend": "steady", "recent_runs": [
            {"run_id": "rv-1", "leased_at": iso(2.2), "fresh_backlog": 24}]},
        "aged_out": {"last_24h": 31, "waited_last_24h": 0,
                     "by_day": [{"day": iso(24)[:10], "total": 31, "waited": 0}]},
    })
    body["grading"] = {
        "agreement": {
            "last_7d": {"n": 9, "same_band": 6, "same_band_pct": 67, "within_one": 9, "within_one_pct": 100,
                        "owner_higher": 2, "owner_lower": 1},
            "last_30d": {"n": 22, "same_band": 15, "same_band_pct": 68, "within_one": 21, "within_one_pct": 95,
                         "owner_higher": 4, "owner_lower": 3},
            "biggest": [{"feedback_id": 41, "event_id": 1234, "title": "Army awards counter-UAS <production> order",
                         "graded_at": iso(30), "owner_verdict": "lead", "owner_band": "lead", "grader_score": 55,
                         "grader_band": "watch", "gap": 2}],
        },
        "calibration_examples": 7, "grades_14d": 12,
        "suggestions": {"proposed": 1, "approved_30d": 0, "rejected_30d": 0},
    }
    body["routines"] = {
        "timezone": "America/New_York", "schedule_source": "deploy",
        "grader": {"schedule": ["07:30", "12:30", "16:30"], "state": "ok", "last_seen_at": iso(2),
                   "last_route": "/review/lease", "last_status": 200, "agent": "Zenith · pilot · Grader · lease ab12cd34",
                   "cli_version": "0.2.0", "prompt_hash": "0123456789ab", "prompt_hash_expected": "0123456789ab",
                   "prompt_current": True, "last_due_at": iso(2.5), "last_due_state": "done",
                   "next_due_at": iso(-1.5), "missed_7d": 1},
        "refiner": {"schedule": ["12:00"], "state": "ok", "last_seen_at": iso(5), "last_route": "/review/rules/queue",
                    "last_status": 200, "agent": None, "cli_version": "0.1.0", "prompt_hash": "aaaaaaaaaaaa",
                    "prompt_hash_expected": "bbbbbbbbbbbb", "prompt_current": False, "last_due_at": None,
                    "last_due_state": None, "next_due_at": iso(-19), "missed_7d": 0},
        "scout": {"schedule": ["13:00"], "state": "never_seen", "last_seen_at": None, "last_route": None,
                  "last_status": None, "agent": None, "cli_version": None, "prompt_hash": None,
                  "prompt_hash_expected": "cccccccccccc", "prompt_current": None, "last_due_at": None,
                  "last_due_state": None, "next_due_at": iso(-20), "missed_7d": 0},
        "unknown": {"last_seen_at": iso(2), "last_route": "/review/rubric", "last_status": 200},
        "auth_failures": {"REVIEW_TOKEN": {"total": 4, "last_24h": 2, "last_at": iso(1), "last_route": "/review/lease"},
                          "READ_TOKEN": {"total": 1, "last_24h": 0, "last_at": iso(50), "last_route": "/diagnostics"}},
    }
    canary = {"canary_id": "cn-20261004T001500Z-1a2b3c4d", "module_id": "ai-infra", "sent_at": iso(3),
              "received_at": iso(3), "via": "queue", "latency_ms": 3100}
    body["canary"] = {"last": canary, "recent": [canary]}
    body["storage"] = {"db_bytes": 41_000_000, "limit_bytes": 10_000_000_000, "used_pct": 0.4}
    body["maintenance"] = {"last_at": iso(5), "last": {"at": iso(5), "dry_run": False, "deleted": {"module_runs": 120}}}
    body["errors"] = {"last_hour": 0, "last_24h": 0, "recent": []}
    body["build"] = {"git_sha": "abc123def456", "built_at": iso(26), "schema_version": 7, "db_schema_version": 7,
                     "contract_versions": [2], "rubric_version": "64154d4b0a1b2c3d", "cli_version": "0.2.0",
                     "migrate_mode": "explicit", "workspace": workspace}
    return body


def suggestion_draft(draft_id: int = 19) -> dict:
    """A rule draft the Rule refiner built from the owner's grades (POST /review/rules/suggestions, 4.3)."""
    grades = [{"feedback_id": 50 + n, "event_id": 1300 + n, "title": f"Conference webcast notice {n} <live>",
               "verdict": "reject", "grader_decision": "selected", "grader_score": 74 - n} for n in range(6)]
    grades[5].update(grader_score=None, grader_decision="rejected")
    return {"id": draft_id, "kind": "rule", "text": "Suggested from 6 of your grades", "origin": "grades",
            "feedback_id": None, "status": "proposed",
            "proposal": {"text": "When a news-search article only announces a conference talk or webcast, rank it "
                                 "reject (under 40).", "rationale": "Six of your grades downgraded conference notices.",
                         "kind": "rule", "conflicts": [], "examples": [1300, 1301]},
            "proposed_at": iso(4), "precedent_id": None, "decision_note": None, "decided_at": None,
            "created_at": iso(4), "updated_at": iso(4),
            "context": {"feedback_ids": [50, 51, 52, 53, 54, 55], "examples": [1300, 1301], "grades": grades}}


def module_liveness(module: str, *, ok: bool = True) -> dict:
    """A module's public GET /health without a bearer (schema 7 modules): liveness only."""
    return {"ok": ok, "service": "zenux-module", "module": module, "workspace": "pilot", "version": "0.1.0+abc123d"}


def module_health(module: str, *, backfill: dict | None = None, ok: bool = True) -> dict:
    body = {
        "module": module, "version": "0.1.0", "workspace": "pilot", "ok": ok,
        "last_run": {"run_id": f"run-{module}", "status": "ok" if ok else "failed", "started_at": iso(0.3),
                     "ended_at": iso(0.25), "totals": {"sources": 40, "emitted": 12}},
        "failing": [],
        "silent": [],
        "sources": [{"key": f"{module}-rss"}, {"key": f"{module}-sitemap"}, "edgar-8k"],
    }
    if backfill is not None:
        body["backfill"] = backfill
    return body


def job(status: str = "queued", done: int = 0, remaining: int = 3, job_id: str = "bf-1", days: int = 14) -> dict:
    keys = ["ai-infra-rss", "ai-infra-sitemap", "edgar-8k", "dcd-news", "bisnow-dc"]
    total = done + remaining
    return {"id": job_id, "days": days, "sources": keys[:total], "requested_at": iso(0.1), "status": status,
            "done": keys[:done], "remaining": keys[done:total],
            **({"finished_at": iso(0)} if status == "done" else {})}


def snapshot(module: str = "ai-infra") -> dict:
    return {
        "workspace": "pilot", "generated_at": iso(0), "module": module,
        "counts": _lanes({"companies": 12, "trade_press": 30}, {"companies": 80, "trade_press": 190}),
        "events": [
            {"id": 500 + n, "module": module, "source_key": "dcd-news", "lane": "trade_press", "trust": "press",
             "kind": "article", "title": f"Event {n} <b>title</b>", "url": f"https://example.com/e{n}",
             "published_at": iso(n), "event_date": None, "thread_key": None,
             "entities": [{"id": "iren", "name": "IREN", "role": "subject"}], "excerpt": "", "facts": {},
             "received_at": iso(n)}
            for n in range(25)
        ],
        "retired_sources": [],
    }


# ================================================================================================ schema v8 bodies
# Shaped exactly as docs/SPEC-PHASE02.md section 5 (and hub/src as built). Visible copy avoids engine words, so the
# jargon guard (labels.find_jargon) passes on a page drawn from them; markup in titles and a javascript: link stay.

TZ = "America/New_York"


def effective(hours_ahead: float = 2.0) -> dict:
    """The `effective` object of every tuning write (5.1)."""
    return {"applies_from": "next_briefing", "next_briefing_at": iso(-hours_ahead), "timezone": TZ}


def _source_info(module: str, key: str, label: str | None, lane: str, lane_label: str | None, column: str | None,
                 trust: str) -> dict:
    return {"module": module, "source_key": key, "label": label if label is not None else key, "lane": lane,
            "lane_label": lane_label, "column": column, "trust": trust}


def _subject(entity_id: str, name: str, *, muted: bool = False, starred: bool = False) -> dict:
    return {"entity_id": entity_id, "name": name, "muted": muted, "starred": starred}


def _items_v8(edition_id: int, n: int) -> list[dict]:
    base = 100 * edition_id
    lead = {
        "id": base + 1, "edition_id": edition_id, "rank": 1, "event_id": 9001 + 10 * n, "event_ids": [],
        "score": 93, "tier": 3, "module": "ai-infra", "modules": ["ai-infra"], "story_id": f"s-{100 + 2 * n}",
        "headline": "Neocloud signs 200 MW <deal> with a hyperscaler",
        "text": "The company signed a 15-year agreement for 200 MW of critical IT capacity.\n\nPower-on is planned for 2027.",
        "metrics": [{"label": "Critical IT", "value": "200 MW", "source_url": "https://example.com/neocloud-deal"},
                    {"label": "Term", "value": "15 years"}],
        "sources": [{"url": "https://example.com/neocloud-deal", "title": "Neocloud newsroom"},
                    {"url": "https://www.sec.gov/Archives/edgar/data/1/0001.htm"}],
        "event": {"title": "Neocloud signs a capacity deal", "url": "https://example.com/neocloud-deal",
                  "module": "ai-infra", "source_key": "neocloud-ir", "lane": "companies", "trust": "primary",
                  "published_at": iso(30 + 12 * n)},
        "feedback": [],
        "why": {
            "reason_code": "material", "reason": "Material news", "score": 93, "band": "lead",
            "rationale": "Signed 15-year 200 MW agreement with a named hyperscaler; calibrated: owner grade #41.",
            "rationale_plain": "Signed 15-year 200 MW agreement with a named hyperscaler; calibrated by your feedback.",
            "rules": [{"id": "R-0012", "status": "active",
                       "text": "Show me more like this: capacity deals of 100 MW or more. Example: event #9001 "
                               "\"Neocloud signs a capacity deal\" from Neocloud newsroom.",
                       "plain_text": "Show me more like this: capacity deals of 100 MW or more. Example: "
                                     "\"Neocloud signs a capacity deal\" from Neocloud newsroom."}],
            "calibrated_by": [41],
            "stars": [{"entity_id": "coreweave", "name": "CoreWeave"}],
            "subjects": [_subject("neocloud", "Neocloud"), _subject("coreweave", "CoreWeave", starred=True)],
            # WF5 (gap 15): every company the story is about, the buyer too
            "companies": [{**_subject("neocloud", "Neocloud"), "role": "subject"},
                          {**_subject("coreweave", "CoreWeave", starred=True), "role": "subject"},
                          {**_subject("hyperscale-co", "Hyperscale Co"), "role": "buyer"}],
            "promoted": None,
            "source": _source_info("ai-infra", "neocloud-ir", "Neocloud newsroom", "companies",
                                   "Company news and filings", "companies", "primary"),
        },
        "correction": None,
    }
    second = {
        "id": base + 2, "edition_id": edition_id, "rank": 2, "event_id": 9002 + 10 * n, "event_ids": [9003 + 10 * n],
        "score": 78, "tier": 1, "module": "defense-unmanned", "modules": ["defense-unmanned", "ai-infra"],
        "story_id": f"s-{101 + 2 * n}",
        "headline": "Army awards $48M counter-drone order",
        "text": "The Army awarded a $48 million firm-fixed-price order for counter-drone interceptors.",
        "metrics": [{"label": "Obligated", "value": "$48M"}],
        "sources": [{"url": "javascript:alert(1)", "title": "bad link"},
                    {"url": "https://www.war.gov/News/Contracts/", "title": "war.gov"}],
        "event": None,
        "feedback": [{"id": 4, "item_id": base + 2, "event_id": 9002 + 10 * n, "verdict": "digest", "score": 80,
                      "note": None, "scope": "item", "created_at": iso(1)}] if n == 0 else [],
        "why": {
            "reason_code": "new_information", "reason": "New information on an ongoing story", "score": 78,
            "band": "digest", "rationale": "Follows the award reported as #9002 with the order value.",
            # the hub's plain words leave a bare "#9002" (clean_rationale is the last guard)
            "rationale_plain": "Follows the award reported as #9002 with the order value.",
            "rules": [], "calibrated_by": [], "stars": [],
            "subjects": [_subject("anduril", "Anduril")],
            "promoted": {"note": "Army orders matter to me", "requested_at": iso(20)} if n == 0 else None,
            # no catalog yet: the hub names the source by its link's host, never the key (gap 7)
            "source": _source_info("defense-unmanned", "war-contracts", "war.gov", "procurement", None, None,
                                   "official"),
        },
        "correction": ({"correction_id": 7, "state": "flagged", "note": "The award was $48M, not $84M",
                        "flagged_at": iso(1), "resolved_at": None, "resolved_edition_id": None, "headline": None,
                        "text": None, "metrics": None} if n == 0 else
                       {"correction_id": 5, "state": "corrected", "note": "Wrong buyer", "flagged_at": iso(20),
                        "resolved_at": iso(2), "resolved_edition_id": edition_id + 1,
                        "headline": "Navy awards $48M counter-drone order",
                        "text": "The Navy, not the Army, awarded the order.",
                        "metrics": [{"label": "Obligated", "value": "$48M"}]}),
    }
    return [lead, second]


def _shelf_row(event_id: int, title: str, score: int, reason_code: str, reason: str, *,
               stars: list[dict] | None = None) -> dict:
    return {"event_id": event_id, "title": title, "url": f"https://example.com/story-{event_id}",
            "published_at": iso(8), "module": "ai-infra", "source_key": "dcd-news",
            "source_label": "Data Center Dynamics", "decision": "rejected", "score": score,
            "reason_code": reason_code, "reason": reason, "rationale": "Close to the bar, no new capacity figure.",
            "stars": stars or [], "canonical_event_id": None}


def briefing_name(published_at: str) -> dict:
    """The hub's plain briefing name (hub/src/plain.js briefingName) in New York time: {briefing_label, slot,
    local_date}."""
    local = datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(ZoneInfo(TZ))
    slot = "morning" if local.hour < 11 else "midday" if local.hour < 16 else "afternoon" if local.hour < 21 \
        else "evening"
    day = f"{local:%a} {local:%b} {local.day}"
    return {"briefing_label": f"{day} · {slot} briefing", "slot": slot, "local_date": day}


def editions_v8(count: int = 2, start_id: int = 12) -> dict:
    """GET /editions (5.11): the newest briefing has both shelves and resolved corrections; older ones predate v8
    shelves (null). Every edition carries its plain name (WF5)."""
    out = []
    for n in range(count):
        eid = start_id - n
        latest = n == 0
        published = iso(2 + 12 * n)
        out.append({
            "id": eid, "run_id": f"rv-2026100{n}T113000Z-0000abcd", "published_at": published,
            **briefing_name(published),
            "item_count": 2, "candidate_count": 41, "backlog": 0, "rubric_version": "sha256:abc",
            "note": "Two stories cleared the bar." if latest else f"Briefing {eid} note",
            "summary": "A 200 MW capacity deal leads; the Army orders counter-drone interceptors." if latest else None,
            "items": _items_v8(eid, n),
            "selection": {"volume": "standard" if latest else "top", "min_score": 70 if latest else 80,
                          "item_limit": 12 if latest else 8, "near_miss_shelf": latest},
            "shelves": {
                "watchlist": [_shelf_row(1300, "CoreWeave adds a <second> campus", 62, "watch", "Near miss",
                                         stars=[{"entity_id": "coreweave", "name": "CoreWeave"}])],
                "near_misses": [_shelf_row(1301, "Nebius expands its Finland site", 66, "edition_limit",
                                           "Cut for space"),
                                _shelf_row(1302, "Miner converts a site to AI hosting", 61, "watch", "Near miss")],
            } if latest else None,
            "corrections": [
                {"correction_id": 5, "item_id": 100 * (eid - 1) + 2, "original_edition_id": eid - 1,
                 "original_headline": "Army awards $48M counter-drone order", "outcome": "corrected",
                 "headline": "Navy awards $48M counter-drone order",
                 "text": "The Navy, not the Army, awarded the order.",
                 "sources": [{"url": "https://www.war.gov/News/Contracts/", "title": "war.gov"}],
                 "metrics": [{"label": "Obligated", "value": "$48M"}], "note": "Wrong buyer", "flagged_at": iso(20),
                 "resolved_at": iso(2)},
                {"correction_id": 6, "item_id": 100 * (eid - 1) + 1, "original_edition_id": eid - 1,
                 "original_headline": "Neocloud signs 200 MW <deal> with a hyperscaler", "outcome": "upheld",
                 "headline": None, "text": "The release states 200 MW in its second paragraph; the story stands.",
                 "sources": [], "metrics": None, "note": "Was it 20 MW?", "flagged_at": iso(20),
                 "resolved_at": iso(2)},
            ] if latest else [],
        })
    return {"editions": out, "next_before": None, "has_more": False}


def _rejected_row(event_id: int, *, decision: str = "rejected", score: int | None = 66, reason_code: str = "watch",
                  reason: str | None = "Near miss", title: str = "Story", module: str = "ai-infra",
                  source_key: str = "dcd-news", source_label: str = "Data Center Dynamics", hours: float = 5,
                  rationale: str | None = "Close to the bar.", auto: bool = False, rule: str | None = None,
                  muted: dict | None = None, requested: dict | None = None, rules: list | None = None,
                  subjects: list | None = None, canonical: int | None = None, kind: str = "article") -> dict:
    row = {
        "event_id": event_id, "decision": decision, "score": score, "tier": None, "reason_code": reason_code,
        "reason": reason, "rationale": rationale, "canonical_event_id": canonical, "story_id": None,
        "decided_at": iso(hours), "run_id": None if auto else "rv-1", "edition_id": None if auto else 12,
        "auto": auto, "title": title, "url": f"https://example.com/e{event_id}", "module": module,
        "source_key": source_key, "lane": "trade_press", "trust": "press", "kind": kind,
        "published_at": iso(hours + 2), "rules": rules or [], "source_label": source_label,
        "subjects": subjects or [], "muted": muted, "requested": requested, "feedback": [],
        # WF5 (docs/SPEC-PHASE05.md 2): the plain extras of every row
        "rationale_plain": rationale, "lane_label": "Trade press",
        "area": "AI infrastructure" if module == "ai-infra" else "Defense unmanned",
        "bar": None if auto else 70, "near_miss": not auto and decision == "rejected" and (score or 0) >= 60,
        "rules_detail": [{"id": rid, "text": None, "plain_text": None, "status": None} for rid in rules or []],
        "canonical": None, "published_later": None,
    }
    if auto:
        row["rule"] = rule
    return row


REJECTED_VIEWS = {"near_miss": 3, "same_story": 2, "muted": 1, "old_news": 1, "auto": 2, "all": 6,
                  "all_with_auto": 8}


def rejected_page(rows: list[dict], filter: str, *, include_auto: bool = False, views: dict | None = None,
                  days: int = 3, total: int | None = None, offset: int = 0, limit: int = 500) -> dict:
    """A GET /rejected answer (WF5 shape): the rows of one view and page, true totals, every view's count."""
    page = rows[offset:offset + limit]
    true_total = len(rows) if total is None else total
    counts: dict = {"rejected": 0, "duplicate": 0, "already_covered": 0}
    for r in rows:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    with_auto = filter in ("muted", "auto", "old_news") or (filter == "all" and include_auto)
    if with_auto:
        counts["auto"] = sum(1 for r in rows if r["auto"])
    more = offset + len(page) < true_total
    return {"days": days, "since": iso(24 * days), "include_auto": with_auto, "filter": filter, "q": None,
            "module": None, "counts": counts, "views": dict(views or REJECTED_VIEWS), "total": true_total,
            "limit": limit, "offset": offset, "returned": len(page), "has_more": more,
            "next_offset": offset + len(page) if more else None, "items": page}


def rejected_v8(filter: str = "all", include_auto: bool = True) -> dict:
    """GET /rejected?filter= (WF5): near misses (near miss, cut for space, below the bar), a plain reject, a repeat,
    an already-reported story, a muted row and an old-news row (the last two only with include_auto or their
    filter)."""
    view = filter
    if filter == "all" and not include_auto:
        filter = "graded"
    near = [
        _rejected_row(7101, score=66, title="Nebius expands its <Finland> site",
                      subjects=[_subject("nebius", "Nebius")], rules=["R-0012"]),
        _rejected_row(7102, score=74, reason_code="edition_limit", reason="Cut for space",
                      title="Miner converts a site to AI hosting", requested={"reason": "promote", "note": "Matters"}),
        _rejected_row(7103, score=72, reason_code="below_bar", reason="Below your \"how much\" setting",
                      title="Army tests a new drone swarm", module="defense-unmanned", source_key="sam-awards",
                      source_label="SAM.gov awards"),
    ]
    graded = [
        _rejected_row(7104, score=31, reason_code="below_materiality", reason="Not significant enough",
                      title="Monthly production update", hours=30),
        _rejected_row(7105, decision="duplicate", score=78, reason_code="duplicate", reason="Same story as another",
                      title="Same award via trade press", canonical=9002, rationale="Same award as #9002."),
        _rejected_row(7106, decision="already_covered", score=None, reason_code="no_new_facts",
                      reason="Already reported", title="Recap of the 200 MW deal", canonical=9001),
    ]
    muted = [_rejected_row(7107, score=None, reason_code="muted", reason="Muted by you", auto=True,
                           title="AI data center themes roundup", source_key="gn-themes",
                           source_label="News search: AI data center themes",
                           rule="mute:source:ai-infra/gn-themes",
                           rationale="Hidden because you muted News search: AI data center themes on 2026-10-01.",
                           muted={"mute_id": 4, "kind": "source", "label": "News search: AI data center themes",
                                  "active": True})]
    old = [_rejected_row(7108, score=None, reason_code="stale", reason="Old news", auto=True, title="An old recap",
                         rule="stale_backlog", hours=40,
                         rationale="Published 2026-09-01, 33 days before 2026-10-04; older than the 21-day freshness "
                                   "line (rule stale_backlog).")]
    old[0]["rationale_plain"] = ("Published Sep 1, 2026, 33 days before Oct 4, 2026; older than the 21-day freshness "
                                 "line.")
    graded[1]["canonical"] = {"event_id": 9002, "title": "Army awards $48M counter-drone order",
                              "url": "https://example.com/army", "story_id": "s-101",
                              "briefing": {"edition_id": 12, "item_id": 1202,
                                           "headline": "Army awards $48M counter-drone order",
                                           "published_at": iso(2), **briefing_name(iso(2))}}
    rows = {"near_miss": near, "same_story": graded[1:], "muted": muted, "old_news": old, "auto": muted + old,
            "all": near + graded + muted + old}.get(filter, near + graded)
    return rejected_page(rows, view, include_auto=include_auto)


def modules() -> dict:
    """GET /modules (5.4)."""
    def mod(mid: str, title: str, counts: tuple, mutes: int, stars: int) -> dict:
        sources, enabled, entities, items, briefing = counts
        return {"id": mid, "title": title, "configured": True,
                "catalog": {"version": f"0.1.0-{mid[:4]}9c1b7d4e", "pushed_at": iso(26), "git_sha": "abc123def456"},
                "counts": {"sources": sources, "sources_enabled": enabled, "sources_off": sources - enabled,
                           "entities": entities, "items_7d": items, "briefing_30d": briefing},
                "health": {"status": "ok", "stale": False, "minutes_since_run": 4}, "mutes": mutes, "stars": stars}
    return {"modules": [
        mod("ai-infra", "AI infrastructure: data centers, colocation, AI cloud, bitcoin miners",
            (6, 5, 4, 1840, 61), 1, 1),
        mod("defense-unmanned", "Defense unmanned: drones, counter-drone and autonomy", (3, 3, 2, 420, 18), 0, 0),
    ]}


_HEALTH_LABELS = {"ok": "Working", "failing": "Not responding", "quiet": "Quiet lately", "off": "Turned off",
                  "new": "Not run yet", "retired": "Removed"}


def _cov_source(key: str, label: str, lane: str, lane_label: str, column: str, *, origin: str = "module",
                entity_id: str | None = None, state: str = "ok", enabled: bool = True, off_reason: str | None = None,
                items_7d: int = 12, briefing_30d: int = 1, muted: dict | None = None, kind: str = "News feed") -> dict:
    return {"key": key, "label": label, "origin": origin, "entity_id": entity_id, "lane": lane,
            "lane_label": lane_label, "column": column, "connector": "rss", "kind": kind, "trust": "press",
            "enabled": enabled, "off_reason": off_reason, "url": f"https://example.com/{key}", "cadence_minutes": 60,
            "stats": {"items_7d": items_7d, "items_30d": items_7d * 4, "briefing_30d": briefing_30d,
                      "briefing_7d": briefing_30d // 2,
                      "hit_rate": round(briefing_30d / (items_7d * 4), 3) if items_7d else None,
                      "last_item_at": iso(3)},
            "health": {"state": state, "label": _HEALTH_LABELS[state],
                       "last_ok_at": iso(30 if state == "failing" else 1),
                       "last_status": "error" if state == "failing" else "ok", "acknowledged": False},
            "muted": muted}


def _cov_entity(eid: str, name: str, category: str, category_label: str, *, ownership: str | None = "public",
                role: str = "core", tickers: tuple = (), coverage: dict | None = None, source_keys: tuple = (),
                muted: dict | None = None, starred: dict | None = None, items_7d: int = 3,
                briefing_30d: int = 1) -> dict:
    flags = {"own_feed": False, "sec_filings": False, "federal_contracts": False, "news_search": False,
             "name_only": False}
    flags.update(coverage or {"name_only": True})
    return {"id": eid, "name": name, "role": role, "category": category, "category_label": category_label,
            "importance": "major", "ownership": ownership, "tickers": list(tickers), "coverage": flags,
            "source_keys": list(source_keys),
            "stats": {"items_7d": items_7d, "items_30d": items_7d * 3, "briefing_30d": briefing_30d,
                      "briefing_7d": briefing_30d // 2, "last_item_at": iso(5)},
            "muted": muted, "starred": starred}


def inspect(module: str = "ai-infra") -> dict:
    """GET /modules/<id>/inspect (5.5)."""
    if module == "defense-unmanned":
        title = "Defense unmanned: drones, counter-drone and autonomy"
        description = "Drones and counter-drone buying."
        sources = [_cov_source("sam-awards", "SAM.gov awards", "procurement", "Federal contracts and notices",
                               "government", kind="Contract notices", state="failing"),
                   _cov_source("defense-news", "Defense trade press", "trade_press", "Trade press", "industry"),
                   _cov_source("army-programs", "Army programs", "programs", "Programs and agencies", "government")]
        entities = [_cov_entity("anduril", "Anduril", "primes", "Drone makers", ownership="private",
                                coverage={"news_search": True, "federal_contracts": True}),
                    _cov_entity("replicator", "Replicator initiative", "programs", "Programs", role="program",
                                ownership="government")]
        lanes = [{"id": "procurement", "label": "Federal contracts and notices", "column": "government",
                  "about": "Contract awards and notices that name a drone maker.", "source_count": 1, "items_7d": 40},
                 {"id": "trade_press", "label": "Trade press", "column": "industry", "about": "Defense trade news.",
                  "source_count": 1, "items_7d": 80}]
        categories = [{"id": "primes", "label": "Drone makers", "entity_count": 1}]
    else:
        title = "AI infrastructure: data centers, colocation, AI cloud, bitcoin miners"
        description = "Data center capacity, AI cloud and the miners turning into AI hosts."
        sources = [
            _cov_source("dcd-news", "Data Center Dynamics", "trade_press", "Trade press", "industry", items_7d=120,
                        briefing_30d=6),
            _cov_source("gn-themes", "News search: AI data center themes", "search", "News search", "industry",
                        items_7d=300, briefing_30d=0,
                        muted={"mute_id": 4, "created_at": iso(72), "note": None, "kind": "source",
                               "module": "ai-infra", "ref": "gn-themes",
                               "label": "News search: AI data center themes"}),
            _cov_source("puct-filings", "Texas utility commission filings", "power_grid", "Power and grid",
                        "government", kind="Filings", state="off", enabled=False,
                        off_reason="The site blocks automated access."),
            _cov_source("ent-coreweave-1", "CoreWeave newsroom", "companies", "Company news and filings",
                        "companies", origin="entity", entity_id="coreweave"),
            _cov_source("ent-coreweave-2", "CoreWeave investor relations", "companies", "Company news and filings",
                        "companies", origin="entity", entity_id="coreweave", state="quiet"),
            _cov_source("edgar-dc-cloud", "SEC filings: data center and AI cloud companies", "companies",
                        "Company news and filings", "companies", kind="Filings"),
        ]
        entities = [
            _cov_entity("coreweave", "CoreWeave", "ai_cloud", "AI cloud", tickers=("NASDAQ:CRWV",),
                        coverage={"own_feed": True, "sec_filings": True},
                        source_keys=("ent-coreweave-1", "ent-coreweave-2"),
                        starred={"star_id": 2, "created_at": iso(48), "note": None}, items_7d=9, briefing_30d=2),
            _cov_entity("nebius", "Nebius", "ai_cloud", "AI cloud", tickers=("NASDAQ:NBIS",),
                        coverage={"sec_filings": True, "news_search": True}),
            _cov_entity("lambda", "Lambda", "ai_cloud", "AI cloud", ownership="private"),
            _cov_entity("example-co", "Example Co <b>", "miners", "Bitcoin miners", ownership="subsidiary",
                        muted={"mute_id": 5, "created_at": iso(30), "note": "noise", "kind": "entity", "module": None,
                               "ref": "example-co", "label": "Example Co <b>"}),
        ]
        lanes = [{"id": "trade_press", "label": "Trade press", "column": "industry", "about": "Industry news sites.",
                  "source_count": 1, "items_7d": 120},
                 {"id": "search", "label": "News search", "column": "industry",
                  "about": "Searches by name and theme.", "source_count": 1, "items_7d": 300},
                 {"id": "power_grid", "label": "Power and grid", "column": "government",
                  "about": "Grid operators and utility commissions.", "source_count": 1, "items_7d": 0},
                 {"id": "companies", "label": "Company news and filings", "column": "companies",
                  "about": "Company newsrooms and filings.", "source_count": 3, "items_7d": 40}]
        categories = [{"id": "ai_cloud", "label": "AI cloud", "entity_count": 3},
                      {"id": "miners", "label": "Bitcoin miners", "entity_count": 1}]
    return {
        "module": {"id": module, "title": title, "description": description,
                   "catalog_version": f"0.1.0-{module[:4]}9c1b7d4e", "pushed_at": iso(26)},
        "generated_at": iso(0), "lanes": lanes, "categories": categories, "sources": sources, "entities": entities,
        "orphans": [{"source_key": "old-key", "events": 41, "retired": True}],
        "totals": {"items_7d": sum(s["stats"]["items_7d"] for s in sources), "items_30d": 7020, "briefing_30d": 61,
                   "briefing_7d": 14},
    }


def _mute(mute_id: int, kind: str, ref: str, label: str, *, module: str | None = None, active: bool = True,
          brought_back: bool = False, hidden_7d: int = 30, hidden_total: int = 30, note: str | None = None) -> dict:
    rule = f"mute:{kind}:{module + '/' if kind == 'source' and module else ''}{ref}"
    return {"id": mute_id, "kind": kind, "module": module if kind == "source" else None, "ref": ref, "label": label,
            "note": note, "active": active, "created_at": iso(72), "removed_at": None if active else iso(10),
            "brought_back": brought_back, "rule": rule, "hidden_total": hidden_total, "hidden_7d": hidden_7d}


def mutes(include_removed: bool = False) -> dict:
    """GET /mutes (all=1 with include_removed) (5.6)."""
    rows = [_mute(4, "source", "gn-themes", "News search: AI data center themes", module="ai-infra"),
            _mute(5, "entity", "example-co", "Example Co <b>", hidden_7d=3, hidden_total=8, note="noise"),
            _mute(8, "story", "s-077", "Old merger saga", hidden_7d=1, hidden_total=2)]
    if include_removed:
        rows += [_mute(3, "source", "uas-vision", "UAS Vision", module="defense-unmanned", active=False,
                       hidden_7d=0, hidden_total=12),
                 _mute(2, "entity", "old-co", "Old Co", active=False, brought_back=True, hidden_7d=0,
                       hidden_total=4)]
    return {"mutes": rows, "active_count": 3, "total": len(rows), "limit": 500, "has_more": False}


def bring_back_preview(mute_id: int = 4, n: int = 12, days: int = 7) -> dict:
    """GET /mutes/bring-back-preview (WF5, gap 13)."""
    text = (f"{n} {'story' if n == 1 else 'stories'} it hid in the last {days} days would go back to the editor for "
            "the next briefing." if n else f"Nothing it hid in the last {days} days would come back.")
    return {"mute_id": mute_id, "kind": "source", "label": "News search: AI data center themes", "active": True,
            "days": days, "would_bring_back": n,
            "examples": [{"event_id": 7600 + k, "title": f"Hidden story {k}", "published_at": iso(10 + k),
                          "hidden_at": iso(9 + k)} for k in range(min(n, 2))],
            "text": text}


def mute_preview(kind: str = "source", ref: str = "dcd-news", module: str | None = "ai-infra",
                 label: str = "Data Center Dynamics", *, already_muted: bool = False) -> dict:
    """GET /mutes/preview (5.6)."""
    return {"kind": kind, "module": module if kind == "source" else None, "ref": ref, "label": label,
            "window_days": 7, "would_hide": 42, "in_briefing": 0, "official_records": 3,
            "already_muted": already_muted,
            "examples": [{"event_id": 1234 + n, "title": f"Example story {n} <i>", "published_at": iso(10 + n),
                          "kind": "article", "source_label": label, "in_briefing": n == 0} for n in range(5)],
            "text": "Would have hidden 42 stories in the last 7 days; none were in your briefing; 3 were official "
                    "records."}


def _star(star_id: int, entity_id: str, label: str, *, matches: int = 9, in_briefing: int = 2) -> dict:
    return {"id": star_id, "entity_id": entity_id, "label": label, "note": None, "active": True,
            "created_at": iso(48), "removed_at": None, "matches_7d": matches, "in_briefing_7d": in_briefing}


def stars() -> dict:
    """GET /stars (5.7)."""
    return {"stars": [_star(2, "coreweave", "CoreWeave")]}


def star_preview(entity_id: str = "nebius", label: str = "Nebius") -> dict:
    """GET /stars/preview (5.7)."""
    return {"entity_id": entity_id, "label": label, "window_days": 7, "matches": 9, "in_briefing": 2,
            "not_in_briefing": 7,
            "examples": [{"event_id": 1400 + n, "title": f"{label} story {n}", "published_at": iso(5 + n),
                          "decision": "selected" if n < 2 else "rejected", "score": 80 - 5 * n,
                          "reason_code": "material" if n < 2 else "watch",
                          "reason": "Material news" if n < 2 else "Near miss", "in_briefing": n < 2}
                         for n in range(3)],
            "text": f"9 stories about {label} in the last 7 days; 2 were in your briefing."}


def _stats(**over) -> dict:
    stats = {"hits_7d": 0, "hits_30d": 0, "promoted_30d": 0, "suppressed_30d": 0, "raised_under_bar_30d": 0,
             "lowered_in_briefing_30d": 0, "last_hit_at": None, "top_suppressed_sources": [],
             "top_suppressed_companies": [], "dormant": False, "looks_like_mute": None}
    stats.update(over)
    return stats


_DIRECTIONS = {"more": "Show me more like this", "less": "Show me less like this", "exact": "Exactly as I write it"}
_SCOPES = {"this_story": "Just this story", "similar": "Stories like this", "standing": "Standing preference"}


def preference(pid: str, text: str, *, direction: str | None = "less", scope: str | None = "similar",
               status: str = "active", stats: dict | None = None, wording: dict | None = None,
               expires_at: str | None = None, example: dict | None = None, origin: str = "preference",
               retired_reason: str | None = None) -> dict:
    """One preference as GET /preferences shows it (5.9)."""
    return {
        "id": pid, "kind": "rule" if scope in (None, "standing") else "item", "scope": scope,
        "scope_label": _SCOPES.get(scope or ""), "direction": direction,
        "direction_label": _DIRECTIONS.get(direction or ""), "text": text, "note": None, "status": status,
        "origin": origin, "event_id": example["event_id"] if example else None, "story_id": None,
        "created_at": iso(240), "activated_at": iso(240), "paused_at": iso(5) if status == "paused" else None,
        "expires_at": expires_at, "retired_at": iso(10) if status == "retired" else None,
        "retired_reason": retired_reason, "supersedes": None, "superseded_by": None, "example": example,
        "wording": wording, "stats": stats or _stats(),
    }


def suggestion(draft_id: int, origin: str, text: str, *, target: str | None = None, replaces: list | None = None,
               added: int = 3, removed: int = 9) -> dict:
    """A proposed draft as GET /preferences.suggestions carries it (draftView with preview_summary)."""
    proposal = {"text": text, "rationale": "Several of your ratings point the same way.", "kind": "rule",
                "conflicts": [], "preview": [{"event_id": 7101, "from": "out", "to": "in"},
                                             {"event_id": 7104, "from": "out", "to": "in"},
                                             {"event_id": 9001, "from": "in", "to": "out"}],
                "preview_summary": {"window_days": 14, "added": added, "removed": removed}}
    if replaces:
        proposal["replaces"] = replaces
    context = None
    if origin == "grades":
        context = {"feedback_ids": [50, 51], "grades": [
            {"feedback_id": 50, "event_id": 1300, "title": "Conference webcast notice", "verdict": "reject",
             "grader_decision": "selected", "grader_score": 74}]}
    elif origin == "brief":
        context = {"brief_line": {"section": "s-ai-infrastructure", "subsection": "rank_high",
                                  "line_id": "L-1a2b3c4d5e", "text": "Signed capacity with a hyperscaler."}}
    titles = {7101: ("Nebius expands its Finland site", "Data Center Dynamics"),
              7104: ("Monthly production update", "Miner Co. investor relations"),
              9001: ("Neocloud signs a capacity deal", "Neocloud newsroom")}
    body = {"id": draft_id, "kind": "rule", "text": text, "origin": origin, "feedback_id": None, "context": context,
            "status": "proposed", "proposal": proposal, "proposed_at": iso(4), "precedent_id": None,
            "decision_note": None, "decided_at": None, "created_at": iso(5), "updated_at": iso(4),
            "target_precedent_id": target, "preview_summary": proposal["preview_summary"],
            # WF5 (docs/SPEC-PHASE05.md 3.2): the plain words and the preview's stories
            "plain_text": text, "status_text": "waiting for your OK",
            "proposal_plain": {"text": text, "rationale": proposal["rationale"]},
            "preview_items": [{"event_id": p["event_id"], "title": titles[p["event_id"]][0], "from": p["from"],
                               "to": p["to"], "source_label": titles[p["event_id"]][1]} for p in proposal["preview"]],
            "preview_more": 0}
    if replaces:
        body["replaces_detail"] = [{"id": rid, "text": None, "plain_text": None, "status": "active",
                                    "status_text": "on", "ended": False} for rid in replaces]
        body["outdated"] = False
    return body


def preferences() -> dict:
    """GET /preferences (5.9): each direction, a legacy one, a paused, a dormant and an ended one; one looks like a
    mute and has a wording waiting; three suggestions (from ratings, a wording, a merge)."""
    prefs = [
        preference("R-0014", "Show me less like this: stock-move articles with no new facts. Example: event #7104 "
                             "\"Monthly production update\" from Data Center Dynamics.",
                   stats=_stats(hits_7d=4, hits_30d=11, suppressed_30d=11, last_hit_at=iso(3),
                                top_suppressed_sources=[{"module": "ai-infra", "source_key": "gn-themes",
                                                         "label": "News search: AI data center themes", "n": 10}],
                                looks_like_mute={"kind": "source", "module": "ai-infra", "ref": "gn-themes",
                                                 "label": "News search: AI data center themes", "share": 0.91,
                                                 "n": 11}),
                   example={"event_id": 7104, "title": "Monthly production update",
                            "source_label": "Data Center Dynamics"},
                   wording={"draft_id": 41, "status": "proposed",
                            "proposal": {"text": "Leave out stock-move articles that report no new facts.",
                                         "rationale": "Clearer."},
                            "proposed_at": iso(4), "preview_summary": {"window_days": 14, "added": 0, "removed": 9}}),
        preference("R-0012", "Show me more like this: capacity deals of 100 MW or more.", direction="more",
                   scope="standing", stats=_stats(hits_7d=2, hits_30d=5, promoted_30d=3, raised_under_bar_30d=2,
                                                  last_hit_at=iso(2)),
                   expires_at=iso(-24 * 30)),
        preference("R-0010", "Counter-drone orders under $1M rank as near misses unless the buyer is new.",
                   direction=None, scope=None, origin="owner+refiner",
                   stats=_stats(promoted_30d=1, suppressed_30d=4, hits_30d=5, last_hit_at=iso(50))),
        preference("R-0008", "Show me less like this: conference notices.", status="paused"),
        preference("I-0003", "Show me more like this: grid interconnection approvals.", direction="more",
                   stats=_stats(dormant=True)),
        preference("R-0005", "Show me less like this: space launches.", status="retired", retired_reason="owner"),
    ]
    merge = suggestion(43, "consolidation", "Leave out conference notices and stock-move articles.",
                       replaces=["R-0014", "R-0008"])
    by_id = {p["id"]: p for p in prefs}
    for detail in merge["replaces_detail"]:
        pref = by_id[detail["id"]]
        detail.update(text=pref["text"], plain_text=pref["text"].replace("Example: event #7104 ", "Example: "),
                      status=pref["status"], status_text={"active": "on", "paused": "paused"}.get(pref["status"]))
    return {
        "preferences": prefs,
        "suggestions": [suggestion(19, "grades", "Rank conference and webcast notices as not relevant."),
                        suggestion(41, "preference", "Leave out stock-move articles that report no new facts.",
                                   target="R-0014", added=0, removed=9),
                        merge],
        "soft_cap": {"active": 4, "cap": 40, "over": False, "warning": None},
        "with_assistant": {"total": 0, "by_origin": {}},
        "summary_7d": {"hits": 23, "promoted": 4, "suppressed": 15, "raised": 3, "lowered": 1,
                       "top": [{"id": "R-0014", "text": "Show me less like this: stock-move articles with no new "
                                                        "facts.", "hits_7d": 4}]},
        "counts": {"active": 4, "paused": 1, "retired": 1},
    }


def settings(mode: str = "standard", stage: str = "live") -> dict:
    """GET /settings (5.12)."""
    modes = [{"mode": "top", "label": "Only the big ones", "bar": 80, "cap": 8},
             {"mode": "standard", "label": "Standard", "bar": 70, "cap": 12},
             {"mode": "broad", "label": "Everything notable", "bar": 60, "cap": 20}]
    current = next(m for m in modes if m["mode"] == mode)
    return {"volume": {**current, "near_miss_shelf": False, "updated_at": None, "modes": modes},
            "stage": {"stage": stage, "since": iso(200)}}


def volume_preview(mode: str = "top") -> dict:
    """GET /settings/volume/preview (5.12)."""
    bar, cap, would = {"top": (80, 8, 5.8), "standard": (70, 12, 9.1), "broad": (60, 20, 14.2)}.get(
        mode, (70, 12, 9.1))
    return {"mode": mode, "bar": bar, "cap": cap, "window_days": 7, "editions": 21, "now_avg": 9.1,
            "would_avg": would, "per_edition": [{"edition_id": 12, "published_at": iso(2), "now": 9,
                                                 "would": round(would)}],
            "text": f"Would show about {round(would)} per briefing instead of about 9."}


def _company_entry(eid: str, name: str, *, big: bool = True, kind_label: str = "Product", basis_text: str | None = None,
                   call_only: bool = False, unnamed: bool = False, tags_stories: bool = True,
                   aliases: tuple[str, ...] = ()) -> dict:
    return {"id": eid, "name": name, "aliases": list(aliases), "big": big, "kind_label": kind_label, "note": None,
            "basis": "share" if basis_text else None, "basis_text": basis_text, "disclosed_label": "Filing",
            "call_only": call_only, "unnamed": unnamed, "since_label": None, "tags_stories": tags_stories}


def brief_companies() -> dict:
    """GET /brief `companies` (docs/SPEC-COMPANY-MAP.md 4.2): two covered companies whose real names trip the jargon
    guard ("Sentinel Hub", "Rekor Scout"), so every Coverage test's assert_plain checks that names are skipped (6.4);
    an unnamed, call-only big customer and a suggestion being checked."""
    e = _company_entry
    rows = [
        ("REKR", "Rekor Systems", "Roadway data and license-plate recognition.", {
            "products": [e("p-rekor-scout", "Rekor Scout", aliases=("OpenALPR by Rekor",)),
                         e("p-rekor-command", "Rekor Command", big=False)],
            "units": [],
            "customers": [e("c-customer-a", "Customer A", kind_label="Customer", basis_text="40% of Q2 2026 revenue",
                            call_only=True, unnamed=True, tags_stories=False)],
            "read_through": [e("r-flock", "Flock Safety", kind_label="Competitor")]},
         [{"id": "CS-1a2b3c4d", "column": "read_through", "action": "add", "name": "Motorola Solutions",
           "status": "queued", "status_label": "Being checked", "big": None}]),
        ("PL", "Planet Labs", "Earth-imaging satellites and data.", {
            "products": [e("p-pelican", "Pelican")],
            "units": [e("u-sentinel-hub", "Sentinel Hub", kind_label="Unit", aliases=("Sinergise",))],
            "customers": [e("c-nga", "NGA", kind_label="Government buyer", basis_text="About 20% of 2025 revenue")],
            "read_through": [e("r-blacksky", "BlackSky", kind_label="Competitor")]}, []),
    ]
    return {"items": [{"ticker": ticker, "name": name, "summary": summary, "columns": columns,
                       "counts": {c: len(v) for c, v in columns.items()}, "pending": pending}
                      for ticker, name, summary, columns, pending in rows],
            "pending_total": 1}


def brief(stage: str = "live") -> dict:
    """GET /brief (5.13), with the company map's `companies` (docs/SPEC-COMPANY-MAP.md 4.2)."""
    return {
        "workspace": "pilot", "stage": stage, "generated_at": iso(0),
        # WF5 (docs/SPEC-PHASE05.md 3.1): the one-pager in the approved vocabulary, the rubric's words in original*
        "title": "What ZENITH looks for: AI infrastructure and defense unmanned",
        "original_title": "Pilot rubric v0: AI infrastructure and defense unmanned",
        "rubric_version": "64154d4b0a1b2c3d", "precedents_version": "p-1",
        "catalog_versions": {"ai-infra": "0.1.0-ai-i9c1b7d4e", "defense-unmanned": "0.1.0-defe9c1b7d4e"},
        "sections": [
            {"id": "s-scores", "module": None, "heading": "Scores",
             "parts": [{"kind": "scores", "title": "Scores", "lines": [
                 {"id": "L-0a1b2c3d4e", "text": "90+: Top story", "original": "90+: Lead item"},
                 {"id": "L-0b1c2d3e4f", "text": "40-69: Near miss; listed under each briefing in Left out",
                  "original": "40-69: Watch; shows on the Rejected tab"}]}]},
            {"id": "s-ai-infrastructure", "module": "ai-infra",
             "heading": "AI infrastructure: data centers, colocation, AI cloud, bitcoin miners",
             "parts": [{"kind": "rank_high", "title": "What ranks high", "lines": [
                 {"id": "L-1a2b3c4d5e", "text": "Signed capacity: an agreement with a hyperscaler or AI lab."},
                 {"id": "L-2b3c4d5e6f", "text": "Power: a utility approves a large new load."}]},
                 {"kind": "ignored", "title": "What is ignored", "lines": [
                     {"id": "L-3c4d5e6f70", "text": "Stock moves with no new facts."}]}]},
            {"id": "s-defense-unmanned", "module": "defense-unmanned", "heading": "Defense unmanned",
             "parts": [{"kind": "who", "title": "Who is covered", "lines": [
                 {"id": "L-4d5e6f7081", "text": "Drone makers and the agencies that buy from them."}]}]},
        ],
        "preferences": [{"id": "R-0014", "text": "Leave out stock-move articles.",
                         "direction_label": "Show me less like this", "scope_label": "Stories like this",
                         "status": "active", "expires_at": None}],
        "mutes": mutes()["mutes"], "stars": stars()["stars"], "volume": settings()["volume"],
        "coverage": [{"module": "ai-infra", "title": "AI infrastructure: data centers",
                      "catalog_version": "0.1.0-ai-i9c1b7d4e", "entities": 4, "sources": 6,
                      "covered": [{"category_label": "AI cloud", "names": ["CoreWeave", "Nebius", "Lambda"]}]}],
        "signoff": ({"last": {"id": 1, "signed_at": iso(200), "by": "migration", "note": None,
                              "rubric_version": None, "catalog_versions": {}}, "count": 1} if stage == "live"
                    else {"last": None, "count": 0}),
        "companies": brief_companies(),
    }


def radar_v8() -> dict:
    """GET /radar (R): one request per stage, with timelines, the proposed sources' states and `first_items` (the hub
    sends a count of stories from those sources since they were set up, null before)."""
    proposal = {"summary": "Add the utility commission's docket feed to AI infrastructure.",
                "sources": [{"key": "puct-large-load", "label": "Texas large-load docket", "connector": "html-list",
                             "module": "ai-infra", "lane": "power_grid", "trust": "official",
                             "cadence_minutes": 360, "config": {"url": "https://interchange.puc.texas.gov/"}}],
                "notes": "Checked one fetch."}

    def req(rid: int, kind: str, status: str, stage: str, steps: list[tuple[str, float]], *,
            state: str | None = None, first_items: int | None = None, **extra) -> dict:
        body = {"id": rid, "kind": kind, "text": f"Please follow the Texas large-load docket (ask {rid})",
                "url": None, "module": "ai-infra", "status": status, "proposal": None, "proposed_at": None,
                "decision_note": None, "decided_at": None, "created_at": iso(steps[0][1]), "updated_at": iso(1),
                "applied_at": None, "live_at": None, "rule_draft_id": None, "stage": stage,
                "timeline": [{"stage": s, "at": iso(h)} for s, h in steps]}
        if state is not None:
            body.update(proposal=proposal, sources=[{"module": "ai-infra", "key": "puct-large-load",
                                                     "label": "Texas large-load docket", "state": state}],
                        first_items=first_items,
                        first_stories=[{"event_id": 8800 + k, "title": f"Docket filing {k}",
                                        "url": f"https://example.com/docket-{k}", "published_at": iso(20 + k)}
                                       for k in range(min(first_items or 0, 3))] if first_items is not None else None,
                        proposal_plain={"summary": proposal["summary"], "notes": proposal["notes"], "cause": None})
        body.update(status_text={"queued": "waiting for the source finder", "proposed": "waiting for your OK",
                                 "approved_pending_apply": "approved, waiting for setup", "applied": "set up",
                                 "live": "live", "rejected": "turned down"}.get(status), area="AI infrastructure")
        body.update(extra)
        return body

    return {"requests": [
        req(46, "missed_story", "queued", "asked", [("asked", 2)], url="https://example.com/missed",
            text="We missed the counter-drone award reported on Oct 2"),
        req(45, "track_source", "proposed", "proposal", [("asked", 26), ("proposal", 20)], state="waiting",
            proposed_at=iso(20)),
        req(44, "new_coverage", "approved_pending_apply", "approved",
            [("asked", 100), ("proposal", 95), ("approved", 90)], state="waiting", proposed_at=iso(95),
            decided_at=iso(90), decision_note="Start with the docket"),
        req(43, "track_source", "applied", "applied",
            [("asked", 200), ("proposal", 190), ("approved", 180), ("applied", 30)], state="in_catalog",
            first_items=0, proposed_at=iso(190), decided_at=iso(180), applied_at=iso(30)),
        req(42, "track_source", "live", "live",
            [("asked", 300), ("proposal", 290), ("approved", 280), ("applied", 100), ("live", 90)], state="live",
            first_items=4, proposed_at=iso(290), decided_at=iso(280), applied_at=iso(100), live_at=iso(90)),
        req(41, "new_coverage", "rejected", "rejected", [("asked", 400), ("rejected", 390)], decided_at=iso(390),
            decision_note="Already covered by the trade press."),
    ], "total": 6, "limit": 200, "has_more": False}


def repairs_v9() -> dict:
    """GET /repairs (schema 9, docs/SPEC-REPAIR-PHASE-B.md 1.2): no source repair yet. fixtures_repairs.py holds one of
    every action and status."""
    return {"repairs": [], "counts": {"proposed": 0, "approved": 0, "applied": 0, "recovered": 0, "rejected": 0,
                                      "withdrawn": 0}}


def company_suggestions_v13(status: str | None = None) -> dict:
    """GET /companies/suggestions?status= (schema 13, docs/SPEC-COMPANY-MAP.md 5.2): no suggested company name yet.
    fixtures_tuning.py holds suggestions of every kind."""
    return {"suggestions": [], "counts": {s: 0 for s in ("queued", "proposed", "approved", "applied", "live",
                                                         "rejected", "withdrawn")}}


# ------------------------------------------------------------------------------------------------ WF5 reads


def status(level: str = "amber", *, stage: str = "live", reasons: list | None = None, last_hours: float | None = 2.0,
           next_hours: float | None = 1.5, late: bool = False, working: bool = False) -> dict:
    """GET /status (docs/SPEC-PHASE05.md 5): by default amber with a source not responding (as diagnostics())."""
    if reasons is None:
        reasons = [{"level": "amber", "code": "sources_not_responding", "count": 1, "modules": ["defense-unmanned"],
                    "text": "1 source is not responding. Coverage shows which."}] if level == "amber" else []
    if late:
        reasons = [{"level": "red", "code": "briefing_late", "due_at": "2026-10-04T16:30:00Z",
                    "text": "The 12:30 PM ET briefing is late."}] + reasons
    top = reasons[0] if reasons else {"code": "on_schedule", "text": "Healthy. Briefings are on schedule."}
    last = None
    if last_hours is not None:
        published = iso(last_hours)
        last = {"edition_id": 12, "published_at": published, "item_count": 2,
                "briefing_label": briefing_name(published)["briefing_label"]}
    next_at = iso(-next_hours) if next_hours is not None and stage != "staging" else None
    return {"workspace": "pilot", "generated_at": iso(0), "level": level, "code": top["code"], "reason": top["text"],
            "reasons": reasons, "stage": stage, "timezone": TZ, "last_briefing": last,
            "latest_edition_id": last["edition_id"] if last else None, "next_briefing_at": next_at,
            "next_briefing_text": None, "last_due_at": iso(2.5), "late": late,
            "late_text": "The 12:30 PM ET briefing is late." if late else None, "editor_working": working}


def latest(edition_id: int | None = 12) -> dict:
    """GET /editions/latest (WF5, gaps 18 and 22)."""
    published = iso(2)
    return {"latest_edition_id": edition_id, "published_at": published if edition_id else None,
            "item_count": 2 if edition_id else None,
            "briefing_label": briefing_name(published)["briefing_label"] if edition_id else None,
            "editions": 2 if edition_id else 0}


def edition_single(edition_id: int = 12) -> dict:
    """GET /editions/<id> (WF5, gap 1): {edition} as GET /editions lists it."""
    pages = editions_v8(count=3, start_id=12)["editions"]
    found = next((e for e in pages if e["id"] == edition_id), None)
    if found is None:
        found = editions_v8(count=1, start_id=edition_id)["editions"][0]
    return {"edition": found}


def search_hits(query: str, hits: list[dict] | None = None, *, total: int | None = None,
                legacy: list[dict] | None = None, legacy_total: int | None = None) -> dict:
    """GET /editions/search (WF5, gap 4), with schema 14's `legacy`: the old tracker's matches (none by default)."""
    hits = list(hits or [])
    true_total = len(hits) if total is None else total
    old = list(legacy or [])
    old_total = len(old) if legacy_total is None else legacy_total
    return {"q": query, "days": 90, "limit": 50, "offset": 0, "total": true_total, "returned": len(hits),
            "has_more": true_total > len(hits), "next_offset": len(hits) if true_total > len(hits) else None,
            "hits": hits,
            "legacy": {"total": old_total, "returned": len(old), "has_more": old_total > len(old),
                       "next_offset": len(old) if old_total > len(old) else None, "hits": old}}


def search_hit(edition_id: int, item_id: int, headline: str, hours: float = 300) -> dict:
    published = iso(hours)
    return {"edition_id": edition_id, "item_id": item_id, "rank": 1, "headline": headline, "event_id": 5000 + item_id,
            "story_id": f"s-{item_id}", "title": headline, "url": f"https://example.com/hit-{item_id}",
            "published_at": published, "briefing_label": briefing_name(published)["briefing_label"]}


def legacy_hit(post: int, headline: str, summary: str | None = None, *, date: str = "2026-09-20", slot: str = "9am ET",
               url: str | None = "https://news.example.com/old", corrected: bool = False, correction: str | None = None,
               tickers: list[str] | None = None, companies: list[str] | None = None) -> dict:
    """One story of the old tracker in GET /editions/search `legacy.hits` (hub/src/legacy.js hitView), with the hub's
    plain label ("From the old tracker · Sep 20, 2026 · 9am digest")."""
    day = datetime.strptime(date, "%Y-%m-%d")
    when = "catch-up digest" if "backfill" in slot else f"{slot.split()[0].lower()} digest"
    return {"kind": "old_tracker", "ref": f"post:{post}:item:1", "date": date, "slot": slot,
            "label": f"From the old tracker · {day:%b} {day.day}, {day.year} · {when}", "headline": headline,
            "summary": summary, "url": url, "corrected": corrected, "correction": correction,
            "tickers": list(tickers or []), "companies": list(companies or []), "entity_ids": [], "reruns": []}


def tuneup(*, due: bool = False, items: list[dict] | None = None, week: str = "2026-W40", rated: int = 0,
           dismissed: bool = False) -> dict:
    """GET /tuneup (schema 11, docs/SPEC-SIMPLIFY.md 1.5): by default not due (nothing to rate)."""
    return {"due": due, "week": week, "dismissed": dismissed, "rated_7d": rated, "target": 5,
            "items": list(items or [])}


def tuneup_item(event_id: int, *, item_id: int | None = None, title: str = "A story to rate", decision: str = "rejected",
                score: int | None = 66, bar: int | None = 70, module: str = "ai-infra",
                reason_text: str | None = "Near miss", hours: float = 30) -> dict:
    """One story of GET /tuneup (docs/SPEC-SIMPLIFY.md 1.5)."""
    return {"event_id": event_id, "item_id": item_id, "title": title, "url": f"https://example.com/tune-{event_id}",
            "source_label": "Data Center Dynamics", "module": module,
            "area_label": "AI infrastructure" if module == "ai-infra" else "Defense unmanned",
            "published_at": iso(hours), "decision": decision, "score": score, "bar": bar, "reason_text": reason_text}


def tuneup_due(n: int = 5) -> dict:
    """A due tune-up: two stories that made a briefing (lowest scores first) and three left out just under the bar."""
    items = [tuneup_item(9101, item_id=1201, title="Neocloud adds a small site", decision="selected", score=74,
                         reason_text=None),
             tuneup_item(9102, item_id=1202, title="Army orders spare parts", decision="selected", score=76,
                         module="defense-unmanned", reason_text=None),
             tuneup_item(9103, title="Miner signs a hosting letter", score=66),
             tuneup_item(9104, title="Grid study for a new campus", score=65, reason_text="Cut for space"),
             tuneup_item(9105, title="Drone maker raises capital", score=64, module="defense-unmanned")]
    return tuneup(due=True, items=items[:n])


# ------------------------------------------------------------------------------------------------ write answers


def preference_created(pid: str = "R-0015", direction: str = "more", scope: str = "similar") -> dict:
    """POST /preferences -> 201 (5.8)."""
    return {"preference": preference(pid, "Show me more like this: stories like this example.", direction=direction,
                                     scope=scope),
            "wording_draft_id": 44, "warnings": [], "effective": effective()}


def mute_added(mute_id: int = 9, kind: str = "source", ref: str = "dcd-news", label: str = "Data Center Dynamics",
               *, module: str | None = "ai-infra", created: bool = True, applied_now: int = 30) -> dict:
    """POST /mutes add -> 201 (200 with created false) (5.6)."""
    return {"created": created, "mute": _mute(mute_id, kind, ref, label, module=module), "applied_now": applied_now,
            "preview": mute_preview(kind, ref, module, label), "effective": effective()}


def mute_removed(mute_id: int = 4, brought_back: int = 12) -> dict:
    """POST /mutes remove or bring_back -> 200 (5.6)."""
    return {"mute": _mute(mute_id, "source", "gn-themes", "News search: AI data center themes", module="ai-infra",
                          active=False, brought_back=brought_back > 0),
            "brought_back": brought_back, "requeued": max(0, brought_back - 3), "effective": effective()}


def star_added(entity_id: str = "nebius", label: str = "Nebius", *, created: bool = True) -> dict:
    """POST /stars add -> 201 (5.7)."""
    return {"created": created, "star": _star(3, entity_id, label), "preview": star_preview(entity_id, label),
            "effective": effective()}


def star_removed(entity_id: str = "coreweave", label: str = "CoreWeave") -> dict:
    """POST /stars remove -> 200 (5.7)."""
    return {"star": {**_star(2, entity_id, label), "active": False, "removed_at": iso(0)}, "removed": True,
            "effective": effective()}


def promoted(event_id: int = 7101) -> dict:
    """POST /promote -> 201 (A)."""
    return {"requeue": {"event_id": event_id, "reason": "promote", "note": "It matters", "requested_at": iso(0)},
            "feedback_id": 88, "effective": effective()}


def feedback_stored(correction_id: int | None = None) -> dict:
    """POST /feedback -> 201 {id, feedback, draft_id, correction_id, effective}."""
    verdict = "factual_error" if correction_id else "digest"
    return {"id": 77, "feedback": {"id": 77, "item_id": 1201, "event_id": 9001, "verdict": verdict, "score": None,
                                   "note": None, "scope": "item", "created_at": iso(0)},
            "draft_id": None, "correction_id": correction_id, "effective": effective()}


def rule_action_answer(action: str, pid: str = "R-0014") -> dict:
    """POST /rules/<id>/<action> -> {preference, changed, warnings, effective} (P2); retire and approve add
    `restored`."""
    status = {"pause": "paused", "retire": "retired"}.get(action, "active")
    body = {"preference": preference(pid, "Show me less like this: stock-move articles.", status=status),
            "changed": True, "warnings": [], "effective": effective()}
    if action == "approve":
        body["preference"] = preference("R-0016", "Leave out stock-move articles that report no new facts.")
    if action in ("retire", "approve"):
        body["restored"] = None
    return body


def volume_set(mode: str = "top") -> dict:
    """POST /settings/volume -> {volume, effective} (V)."""
    return {"volume": settings(mode)["volume"], "effective": effective()}


def brief_suggested() -> dict:
    """POST /brief/suggest -> 201 {draft, effective}; it takes effect after approval."""
    draft = suggestion(45, "brief", "Signed capacity of 50 MW or more with any AI cloud.")
    draft.update(status="queued", proposal=None, proposed_at=None, preview_summary=None)
    return {"draft": draft, "effective": {"applies_from": "after_approval", "next_briefing_at": None, "timezone": TZ}}


def signed_off() -> dict:
    """POST /signoff -> 201 {signoff, stage}."""
    return {"signoff": {"id": 2, "signed_at": iso(0), "by": "owner", "note": None,
                        "rubric_version": "64154d4b0a1b2c3d", "precedents_version": "p-1",
                        "catalog_versions": brief()["catalog_versions"]},
            "stage": "live", "effective": effective()}
