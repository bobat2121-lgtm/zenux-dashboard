"""Hub bodies for what was left out of the briefings, shaped as docs/SPEC-PHASE05.md section 2 and
docs/SPEC-SIMPLIFY.md 1.3 (GET /rejected: one row per story, true totals, every view's count, paging, `q` and
`module`, and `edition_id` with each row's `group`; rows with reason, rules_detail, source_label, subjects, muted,
requested, rationale_plain, canonical and published_later), and the schema 11 fields of a briefing (`left_out`,
`tuning`; editions_v11). Fresh copies per call.

rejected_for(params) answers like the hub: with `edition_id`, that briefing's left-out rows (edition_rows); else it
picks the view by `filter`, then narrows by `module` and by `q` (every word in the title, the editor's reasoning, the
source's name or a company), and pages with `offset` and `limit` (500 a page at most).

A few deliberately hostile values (markup in a title, a javascript: link) check the escaping, and one row's
source_label is only its source key (an older hub), so the page must fall back to the link's domain.
"""

from __future__ import annotations

from fixtures import briefing_name, iso

AI = "ai-infra"
DEF = "defense-unmanned"
COREWEAVE = {"entity_id": "coreweave", "name": "CoreWeave", "muted": False, "starred": False}
ANDURIL = {"entity_id": "anduril", "name": "Anduril", "muted": False, "starred": True}
EXAMPLE_CO = {"entity_id": "example-co", "name": "Example Co", "muted": True, "starred": False}

STALE_RATIONALE = ("Published 2026-08-01, 63 days before 2026-10-03; older than the 21-day freshness line "
                   "(rule stale_backlog).")
STALE_PLAIN = "Published Aug 1, 2026, 63 days before Oct 3, 2026; older than the 21-day freshness line."
SOURCE_MUTE_LABEL = "News search: AI data center themes"
PAGE = 500


def row(event_id: int, *, decision: str = "rejected", score: int | None = 50, reason_code: str = "watch",
        reason: str | None = "Near miss", title: str = "A story", module: str = AI, source_key: str = "dcd",
        source_label: str | None = "Data Center Dynamics", url: str | None = None, hours: float = 5.0,
        rationale: str | None = "Credible but small.", **extra) -> dict:
    """One GET /rejected row (WF5). `hours`: how long ago it was decided; published two hours before that."""
    auto = extra.get("auto") is True
    body = {
        "event_id": event_id, "decision": decision, "score": score, "tier": None, "reason_code": reason_code,
        "rationale": rationale, "canonical_event_id": None, "story_id": None, "decided_at": iso(hours),
        "run_id": "rv-1", "edition_id": 12, "auto": False, "title": title,
        "url": url if url is not None else f"https://example.com/story-{event_id}", "module": module,
        "source_key": source_key, "lane": "trade_press", "trust": "press", "kind": "article",
        "published_at": iso(hours + 2), "rules": [], "source_label": source_label, "subjects": [], "muted": None,
        "requested": None, "feedback": [],
        "rationale_plain": rationale, "lane_label": "Trade press",
        "area": "AI infrastructure" if module == AI else "Defense unmanned",
        "bar": None if auto else 70, "near_miss": False, "rules_detail": [], "canonical": None,
        "published_later": None,
    }
    if reason is not None:
        body["reason"] = reason
    body.update(extra)
    return body


def near_rows() -> list[dict]:
    """GET /rejected?filter=near_miss, in the hub's order (newest decision first)."""
    return [
        row(7201, score=64, title="CoreWeave adds <b>Texas</b> capacity", story_id="s-200",
            subjects=[dict(COREWEAVE)], rules=["R-0012"], hours=5, near_miss=True,
            rationale="Credible expansion but no capacity figure; calibrated: owner grade #41. Like #9001 last week.",
            rationale_plain="Credible expansion but no capacity figure; calibrated by your feedback. Like #9001 last "
                            "week.",
            rules_detail=[{"id": "R-0012", "text": "Show me less like this: capacity announcements without a megawatt "
                                                   "figure",
                           "plain_text": "Show me less like this: capacity announcements without a megawatt figure",
                           "status": "active"}]),
        row(7202, score=75, reason_code="edition_limit", reason="Cut for space", title="Anduril wins drone order",
            module=DEF, source_key="breaking-defense", source_label="breaking-defense",
            url="https://www.breakingdefense.com/2026/10/anduril-order", subjects=[dict(ANDURIL)], hours=4,
            near_miss=True, bar=80),
        row(7204, score=None, reason_code="below_bar", reason="Below your \"how much\" setting",
            title="Small grid study", hours=3, near_miss=True),
        row(7205, score=61, title="Hyperscaler signs new campus", hours=6, near_miss=True,
            requested={"reason": "promote", "note": "Big customer", "requested_at": iso(4)},
            feedback=[{"id": 9, "item_id": None, "event_id": 7205, "verdict": "watch", "score": None, "note": None,
                       "scope": "item", "created_at": iso(30)},
                      {"id": 11, "item_id": None, "event_id": 7205, "verdict": "lead", "score": None, "note": None,
                       "scope": "item", "created_at": iso(3)},
                      {"id": 12, "item_id": None, "event_id": 7205, "verdict": "digest", "score": None,
                       "note": "Should have been in: Big customer", "scope": "item", "created_at": iso(1)}]),
    ]


def all_rows() -> list[dict]:
    """GET /rejected?filter=all&include_auto=1: editor decisions and the hub's automatic ones (old news, mutes)."""
    briefed = iso(2)
    return [
        row(7304, decision="rejected", score=None, reason_code="stale", reason="Old news",
            title="Old trade-press story", rationale=STALE_RATIONALE, rationale_plain=STALE_PLAIN, hours=1,
            auto=True, rule="stale_backlog", run_id=None, edition_id=None, bar=None),
        row(7305, decision="rejected", score=None, reason_code="muted", reason="Muted by you",
            title="Search result about AI data centers", source_key="gn-themes", source_label=SOURCE_MUTE_LABEL,
            rationale=f"Hidden because you muted {SOURCE_MUTE_LABEL} on 2026-10-02.",
            rationale_plain=f"Hidden because you muted {SOURCE_MUTE_LABEL} on Oct 2, 2026.", hours=2, auto=True,
            rule="mute:source:ai-infra/gn-themes", run_id=None, edition_id=None, bar=None,
            muted={"mute_id": 4, "kind": "source", "label": SOURCE_MUTE_LABEL, "active": True}),
        row(7301, score=31, reason_code="below_materiality", reason="Not significant enough",
            title="Miner monthly production update", source_key="miner-ir", source_label="Miner Co. investor relations",
            rationale="Routine monthly update; no material change.", hours=5,
            feedback=[{"id": 2, "item_id": None, "event_id": 7301, "verdict": "watch", "score": 55, "note": None,
                       "scope": "item", "created_at": iso(4)}]),
        row(7302, decision="duplicate", score=78, reason_code="duplicate", reason="Same story as another",
            title="Same deal via trade press", canonical_event_id=9001, story_id="s-100",
            rationale="Same deal as #9001.", rationale_plain="Same story as another.", hours=6,
            canonical={"event_id": 9001, "title": "Neocloud signs 200 MW capacity deal with hyperscaler",
                       "url": "https://example.com/neocloud-lease", "story_id": "s-100",
                       "briefing": {"edition_id": 12, "item_id": 1201,
                                    "headline": "Neocloud signs 200 MW capacity deal with hyperscaler",
                                    "published_at": briefed, **briefing_name(briefed)}}),
        row(7306, decision="already_covered", score=None, reason_code="already_covered", reason="Already reported",
            title="Award covered last week", module=DEF, source_key="defense-news", source_label="Defense News",
            canonical_event_id=8800, hours=8,
            canonical={"event_id": 8800, "title": "Army award reported last week", "url": None, "story_id": "s-88",
                       "briefing": None}),
        row(7307, score=40, reason_code="no_new_facts", reason="Already reported", title="Recap with no new facts",
            module=DEF, source_key="defense-news", source_label="Defense News", hours=9),
        row(7308, score=35, reason_code="insufficient_evidence", reason=None, title="Unconfirmed rumour of a deal",
            hours=10),
        row(7309, score=12, reason_code="brand_new_reason", reason=None, title="A story with a new kind of reason",
            hours=11),
        row(7310, score=20, reason_code="late_repost", reason="Old news, reposted",
            title="Two-year-old launch story shared again", hours=12),
        row(7303, score=22, reason_code="out_of_scope", reason="Outside your coverage",
            title="Drone <script>alert(1)</script> unveiled at trade show", module=DEF, source_key="uas-vision",
            source_label=None, url="javascript:alert(1)", hours=30),
    ]


def muted_rows() -> list[dict]:
    """GET /rejected?filter=muted: only mute:* automatic decisions."""
    return [
        row(7305, decision="rejected", score=None, reason_code="muted", reason="Muted by you",
            title="Search result about AI data centers", source_key="gn-themes", source_label=SOURCE_MUTE_LABEL,
            rationale=f"Hidden because you muted {SOURCE_MUTE_LABEL} on 2026-10-02.", hours=2, auto=True,
            rule="mute:source:ai-infra/gn-themes", run_id=None, edition_id=None,
            muted={"mute_id": 4, "kind": "source", "label": SOURCE_MUTE_LABEL, "active": True}),
        row(7401, decision="rejected", score=None, reason_code="muted", reason="Muted by you",
            title="Example Co newsroom post", source_key="ent-example-co-1", source_label="Example Co newsroom",
            rationale="Hidden because you muted Example Co on 2026-10-01.", hours=3, auto=True,
            rule="mute:entity:example-co", run_id=None, edition_id=None, subjects=[dict(EXAMPLE_CO)],
            muted={"mute_id": 5, "kind": "entity", "label": "Example Co", "active": True}),
        row(7402, decision="rejected", score=None, reason_code="muted", reason="Muted by you",
            title="Another update on the old story", hours=20, auto=True, rule="mute:story:s-300",
            run_id=None, edition_id=None, rationale="Hidden because you muted “Old story” on 2026-09-30.",
            muted={"mute_id": 6, "kind": "story", "label": "“Old story”", "active": False}),
    ]


def same_rows() -> list[dict]:
    """GET /rejected?filter=same_story: the editor's duplicate and already-reported decisions."""
    return [r for r in all_rows() if r["decision"] in ("duplicate", "already_covered")]


def old_rows() -> list[dict]:
    """GET /rejected?filter=old_news: the old-news rule and the editor's old-news rejections."""
    return [r for r in all_rows()
            if r.get("rule") == "stale_backlog" or (not r.get("auto") and r["reason_code"] in ("stale", "late_repost"))]


def auto_rows() -> list[dict]:
    """GET /rejected?filter=auto: every automatic decision (old news and mutes)."""
    out = [r for r in all_rows() if r.get("auto")]
    return out + [r for r in muted_rows() if r["event_id"] == 7401]


def views() -> dict:
    """Every view's true count over the window (the answer's `views`)."""
    every = all_rows()
    return {"all": sum(1 for r in every if not r.get("auto")), "all_with_auto": len(every),
            "near_miss": len(near_rows()), "same_story": len(same_rows()), "muted": len(muted_rows()),
            "old_news": len(old_rows()), "auto": len(auto_rows())}


def rejected_body(rows: list[dict], *, filter: str = "all", days: int = 3, include_auto: bool = False,
                  offset: int = 0, total: int | None = None, view_counts: dict | None = None) -> dict:
    page = rows[offset:offset + PAGE]
    true_total = len(rows) if total is None else total
    counts: dict[str, int] = {"rejected": 0, "duplicate": 0, "already_covered": 0}
    for r in rows:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    with_auto = filter in ("muted", "auto", "old_news") or (filter == "all" and include_auto)
    if with_auto:
        counts["auto"] = sum(1 for r in rows if r.get("auto"))
    more = offset + len(page) < true_total
    return {"days": days, "since": iso(24 * days), "include_auto": with_auto, "filter": filter, "q": None,
            "module": None, "counts": counts, "views": view_counts if view_counts is not None else views(),
            "total": true_total, "limit": PAGE, "offset": offset, "returned": len(page), "has_more": more,
            "next_offset": offset + len(page) if more else None, "items": page}


def matches(r: dict, query: str) -> bool:
    """The hub's search: every word in the title, the reasoning, the source's name or a company."""
    hay = " ".join(str(x or "") for x in (r.get("title"), r.get("rationale"), r.get("source_label"),
                                          " ".join(s.get("name", "") for s in r.get("subjects") or []))).casefold()
    return all(term in hay for term in query.casefold().split())


def rejected_for(params: dict) -> dict:
    """The GET /rejected answer for a request's query parameters, as the hub filters, searches and pages it."""
    f = str(params.get("filter") or "all")
    days = int(params.get("days") or 3)
    include_auto = str(params.get("include_auto", "")).lower() in ("1", "true")
    if params.get("edition_id") is not None:
        rows = edition_rows() if int(params["edition_id"]) == LEFT_OUT_EDITION else []
        rows = {"near_miss": [r for r in rows if r["group"] == "near_miss"],
                "same_story": [r for r in rows if r["group"] == "same_story"]}.get(f, rows)
    else:
        rows = {"near_miss": near_rows, "same_story": same_rows, "muted": muted_rows, "old_news": old_rows,
                "auto": auto_rows}.get(f)
        rows = rows() if rows else (all_rows() if include_auto else [r for r in all_rows() if not r.get("auto")])
    module = str(params.get("module") or "")
    if module:
        rows = [r for r in rows if r.get("module") == module]
    query = str(params.get("q") or "")
    if query:
        rows = [r for r in rows if matches(r, query)]
    limit = min(int(params.get("limit") or PAGE), PAGE)
    body = rejected_body(rows, filter=f, days=days, include_auto=include_auto, offset=int(params.get("offset") or 0))
    page = rows[int(params.get("offset") or 0):int(params.get("offset") or 0) + limit]
    more = int(params.get("offset") or 0) + len(page) < len(rows)
    body.update(items=page, returned=len(page), limit=limit, has_more=more,
                next_offset=int(params.get("offset") or 0) + len(page) if more else None)
    return body


# ---------------------------------------------------------------------------------------------- schema 11 (SIMPLIFY)

LEFT_OUT_EDITION = 12   # the latest briefing of fixtures_briefing
BELOW_BAR_ROWS = 13     # one more page than the 10 a group shows first


def edition_rows() -> list[dict]:
    """GET /rejected?edition_id=12: what briefing 12's run decided and left out, each with its `group`, in the hub's
    order (the run decided them all at once: best score first)."""
    near = [dict(r, group="near_miss") for r in near_rows()]
    below = [row(7500 + n, score=55 - n, reason_code="below_materiality", reason="Not significant enough",
                 title=f"Smaller story number {n}", hours=5, group="below_bar") for n in range(BELOW_BAR_ROWS - 1)]
    below.append(dict(next(r for r in all_rows() if r["event_id"] == 7301), group="below_bar"))
    same = [dict(r, group="same_story") for r in same_rows()]
    return near + below + same


def left_out(total: int | None = None, *, near: int = 4, below: int = BELOW_BAR_ROWS, same: int = 2, muted: int = 4,
             old: int = 12) -> dict:
    """A briefing's `left_out` (docs/SPEC-SIMPLIFY.md 1.4)."""
    return {"total": near + below + same if total is None else total, "near_miss": near, "below_bar": below,
            "same_story": same, "kept_out_automatically": {"muted": muted, "old_news": old}}


def tuning(**counts) -> dict:
    """A briefing's `tuning` (docs/SPEC-SIMPLIFY.md 1.4): by default 2 brought in and 1 kept out by 2 rules, 3 ratings."""
    body = {"brought_in": 2, "kept_out": 1, "raised": 0, "lowered": 0, "rules_used": 2, "ratings_used": 3}
    body.update(counts)
    return body


def editions_v11(**latest) -> dict:
    """GET /editions from a schema 11 hub: the latest briefing (12) with `left_out` and `tuning`; the older one (11)
    without them, as an older hub sends it (no receipt, no left-out section)."""
    import fixtures_briefing as fb

    body = fb.editions()
    body["editions"][0].update({"left_out": left_out(), "tuning": tuning(), **latest})
    return body


def many_rows(total: int = 620):
    """A near-miss view with `total` stories: a handler that pages them 500 at a time, as the hub does."""
    rows = [row(10_000 + i, score=60 + (i % 10), title=f"Near miss number {i}", hours=1 + i / 10) for i in range(total)]

    def answer(call) -> dict:
        offset = int((call.params or {}).get("offset") or 0)
        return rejected_body(rows, filter="near_miss", offset=offset,
                             view_counts={**views(), "near_miss": total})
    return answer


def mutes() -> dict:
    """GET /mutes?all=1: two active mutes, two removed (one already brought back)."""
    return {"mutes": [
        {"id": 4, "kind": "source", "module": AI, "ref": "gn-themes", "label": SOURCE_MUTE_LABEL, "note": "Too noisy",
         "active": True, "created_at": iso(48), "removed_at": None, "brought_back": False,
         "rule": "mute:source:ai-infra/gn-themes", "hidden_total": 30, "hidden_7d": 12},
        {"id": 5, "kind": "entity", "module": None, "ref": "example-co", "label": "Example Co", "note": None,
         "active": True, "created_at": iso(72), "removed_at": None, "brought_back": False,
         "rule": "mute:entity:example-co", "hidden_total": 3, "hidden_7d": 1},
        {"id": 6, "kind": "story", "module": None, "ref": "s-300", "label": "“Old story”", "note": None,
         "active": False, "created_at": iso(200), "removed_at": iso(10), "brought_back": False,
         "rule": "mute:story:s-300", "hidden_total": 4, "hidden_7d": 0},
        {"id": 3, "kind": "source", "module": DEF, "ref": "uas-vision", "label": "UAS Vision", "note": None,
         "active": False, "created_at": iso(300), "removed_at": iso(100), "brought_back": True,
         "rule": "mute:source:defense-unmanned/uas-vision", "hidden_total": 9, "hidden_7d": 0},
    ], "active_count": 2, "total": 4, "limit": 500, "has_more": False}


def preferences() -> dict:
    """GET /preferences with the preference row 7201 cites (R-0012)."""
    return {"preferences": [{
        "id": "R-0012", "kind": "rule", "scope": "standing", "scope_label": "Standing preference",
        "direction": "less", "direction_label": "Show me less like this",
        "text": "Show me less like this: capacity announcements without a megawatt figure", "note": None,
        "plain_text": "Show me less like this: capacity announcements without a megawatt figure", "status_text": "on",
        "status": "active", "origin": "preference", "event_id": None, "story_id": None, "created_at": iso(100),
        "activated_at": iso(100), "paused_at": None, "expires_at": None, "retired_at": None, "retired_reason": None,
        "supersedes": None, "superseded_by": None, "example": None, "wording": None,
        "stats": {"hits_7d": 2, "hits_30d": 5, "promoted_30d": 0, "suppressed_30d": 5, "raised_under_bar_30d": 0,
                  "lowered_in_briefing_30d": 0, "last_hit_at": iso(5), "top_suppressed_sources": [],
                  "top_suppressed_companies": [], "dormant": False, "looks_like_mute": None}}],
        "suggestions": [], "soft_cap": {"active": 1, "cap": 40, "over": False, "warning": None},
        "with_assistant": {"total": 0, "by_origin": {}},
        "summary_7d": {"hits": 2, "promoted": 0, "suppressed": 2, "raised": 0, "lowered": 0, "top": []},
        "counts": {"active": 1, "paused": 0, "retired": 0}}


def effective(hours_ahead: float = 2.0) -> dict:
    return {"applies_from": "next_briefing", "next_briefing_at": iso(-hours_ahead), "timezone": "America/New_York"}


def mute_preview(kind: str = "source", ref: str = "dcd", module: str | None = AI,
                 label: str = "Data Center Dynamics") -> dict:
    return {"kind": kind, "module": module, "ref": ref, "label": label, "window_days": 7, "would_hide": 42,
            "in_briefing": 0, "official_records": 3, "already_muted": False,
            "examples": [{"event_id": 7201, "title": "CoreWeave adds Texas capacity", "published_at": iso(7),
                          "kind": "article", "source_label": "Data Center Dynamics", "in_briefing": False}],
            "text": "Would have hidden 42 stories in the last 7 days; none were in your briefing; "
                    "3 were official records."}


def star_preview(entity_id: str = "coreweave", label: str = "CoreWeave") -> dict:
    return {"entity_id": entity_id, "label": label, "window_days": 7, "matches": 9, "in_briefing": 2,
            "not_in_briefing": 7, "examples": [],
            "text": f"9 stories about {label} in the last 7 days; 2 were in your briefing."}


def mute_view(mute_id: int, kind: str, ref: str, label: str, *, module: str | None = None, active: bool = True,
              brought_back: bool = False) -> dict:
    return {"id": mute_id, "kind": kind, "module": module, "ref": ref, "label": label, "note": None,
            "active": active, "created_at": iso(0), "removed_at": None if active else iso(0),
            "brought_back": brought_back, "rule": f"mute:{kind}:{(module + '/') if module else ''}{ref}",
            "hidden_total": 30, "hidden_7d": 30}


def mute_added(mute_id: int = 21, kind: str = "source", ref: str = "dcd", label: str = "Data Center Dynamics",
               module: str | None = AI) -> dict:
    return {"created": True, "mute": mute_view(mute_id, kind, ref, label, module=module), "applied_now": 4,
            "preview": mute_preview(kind, ref, module, label), "effective": effective()}


def mute_removed(mute_id: int = 4, brought_back: int = 12) -> dict:
    return {"mute": mute_view(mute_id, "source", "gn-themes", SOURCE_MUTE_LABEL, module=AI, active=False,
                              brought_back=brought_back > 0),
            "brought_back": brought_back, "requeued": brought_back, "effective": effective()}


def brought_back(mute_id: int = 6, n: int = 3) -> dict:
    return {"mute": mute_view(mute_id, "story", "s-300", "“Old story”", active=False, brought_back=True),
            "brought_back": n, "requeued": n, "effective": effective()}


def promoted(event_id: int = 7201) -> dict:
    return {"requeue": {"event_id": event_id, "reason": "promote", "note": "A big customer win",
                        "requested_at": iso(0)},
            "feedback_id": 90, "effective": effective()}


def preference_created(pid: str = "R-0031", direction: str = "less", scope: str = "similar") -> dict:
    return {"preference": {"id": pid, "kind": "rule", "scope": scope, "direction": direction, "status": "active",
                           "text": "Show me less like this: monthly production updates"},
            "wording_draft_id": 41, "warnings": [], "effective": effective()}


def star_added(entity_id: str = "coreweave", label: str = "CoreWeave") -> dict:
    return {"created": True, "star": {"id": 2, "entity_id": entity_id, "label": label, "note": None, "active": True,
                                      "created_at": iso(0), "removed_at": None, "matches_7d": 9, "in_briefing_7d": 2},
            "preview": star_preview(entity_id, label), "effective": effective()}


def feedback_stored() -> dict:
    return {"id": 77, "feedback": {"id": 77}, "draft_id": None, "correction_id": None}
