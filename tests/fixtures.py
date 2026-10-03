"""Hub and module response bodies, shaped as hub/src/brain.js and the module SDK return them. Fresh copies per call.

A few deliberately hostile values (a javascript: link, markup in titles, blank lines in text) check the escaping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


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


def diagnostics(workspace: str = "pilot", *, failing: bool = True) -> dict:
    sam = {"module_id": "defense-unmanned", "source_key": "sam-opps", "health": "backoff", "last_status": "error",
           "last_http_status": 429, "consecutive_failures": 3, "last_ok_at": iso(30), "last_run_at": iso(0.35)}
    return {
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
            "lease": {"state": "active", "held": True, "run_id": "rv-13", "agent": "grader", "leased_at": iso(0.2),
                      "lease_expires_at": iso(-0.5), "candidates": 57, "decided": 10},
            "last_run": {"run_id": "rv-1", "status": "published", "leased_at": iso(2.2), "finished_at": iso(2)},
        },
        "last_edition": {"id": 12, "run_id": "rv-1", "published_at": iso(2), "item_count": 2, "candidate_count": 41,
                         "backlog": 0},
    }


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
