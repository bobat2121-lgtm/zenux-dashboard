"""Briefing bodies (GET /editions of a schema 8 hub, docs/SPEC-PHASE02.md 5.11) and the write answers the card actions
read. Fresh copies per call. Times are fixed, so briefing names are stable: the latest briefing was published Sat Oct 3
2026 at 7:41 AM ET (a morning briefing), the older one Fri Oct 2 at 4:32 PM ET (an afternoon briefing).

The story texts avoid words the plain-language guard flags (labels.JARGON_PATTERNS), so a fully rendered page can be
checked; a few hostile values (markup in a headline, a javascript: link, an event id in a rationale) check escaping
and cleaning.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

LATEST_ID = 12
OLDER_ID = 11
LATEST_AT = "2026-10-03T11:41:00Z"   # Sat Oct 3, 7:41 AM ET
OLDER_AT = "2026-10-02T20:32:00Z"    # Fri Oct 2, 4:32 PM ET
LATEST_LABEL = "Sat Oct 3 · morning briefing"
OLDER_LABEL = "Fri Oct 2 · afternoon briefing"
PREF_TEXT = ('Show me more like this: capacity deals with named hyperscalers. Example: event #1234 "CoreWeave adds '
             'capacity" from CoreWeave newsroom.')
RATIONALE = "Signed capacity with a named hyperscaler; calibrated: owner grade #41. Larger than the deal in #9002."


def iso(hours_from_now: float = 0.0) -> str:
    moment = datetime.now(timezone.utc) + timedelta(hours=hours_from_now)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def effective(hours_ahead: float = 2.0) -> dict:
    return {"applies_from": "next_briefing", "next_briefing_at": iso(hours_ahead), "timezone": "America/New_York"}


def _why_coreweave() -> dict:
    return {
        "reason_code": "material", "reason": "Material news", "score": 93, "band": "lead",
        "rationale": RATIONALE,
        "rules": [{"id": "R-0012", "text": PREF_TEXT, "status": "active"},
                  {"id": "I-0003", "text": None, "status": None}],
        "calibrated_by": [41],
        "stars": [],
        "subjects": [{"entity_id": "coreweave", "name": "CoreWeave", "muted": False, "starred": False},
                     {"entity_id": "microsoft", "name": "Microsoft", "muted": False, "starred": True}],
        "promoted": {"note": "Big capacity deals always belong", "requested_at": "2026-10-03T22:00:00Z"},
        "source": {"module": "ai-infra", "source_key": "ent-coreweave-1", "label": "CoreWeave newsroom",
                   "lane": "companies", "lane_label": "Company news and filings", "column": "companies",
                   "trust": "primary"},
    }


def _why_army() -> dict:
    return {
        "reason_code": "primary_source", "reason": "Official confirmation", "score": 78, "band": "digest",
        "rationale": "A contract notice confirms the award.", "rules": [], "calibrated_by": [], "stars": [],
        "subjects": [{"entity_id": "anduril", "name": "Anduril", "muted": True, "starred": False}],
        "promoted": None,
        # no catalog yet: the label is the source key, so the card falls back to the first source's name
        "source": {"module": "defense-unmanned", "source_key": "wargov-contracts", "label": "wargov-contracts",
                   "lane": "procurement", "lane_label": None, "column": None, "trust": "official"},
    }


def items(edition_id: int) -> list[dict]:
    base = 100 * edition_id
    return [
        {
            "id": base + 1, "edition_id": edition_id, "rank": 1, "event_id": 9001, "event_ids": [],
            "score": 93, "tier": 1, "module": "ai-infra", "modules": ["ai-infra"], "story_id": "s-100",
            "headline": "CoreWeave signs 200 MW <capacity> deal with Microsoft",
            "text": "The company signed a 15-year agreement for 200 MW of critical IT capacity.\n\nEnergization is "
                    "planned for 2027.",
            "metrics": [{"label": "Critical IT", "value": "200 MW", "source_url": "https://example.com/coreweave"},
                        {"label": "Term", "value": "15 years"}],
            "sources": [{"url": "https://example.com/coreweave", "title": "CoreWeave newsroom"},
                        {"url": "https://www.sec.gov/Archives/edgar/data/1/0001.htm"}],
            "event": {"title": "CoreWeave signs capacity deal", "url": "https://example.com/coreweave",
                      "module": "ai-infra", "source_key": "ent-coreweave-1", "lane": "companies", "trust": "primary",
                      "published_at": "2026-10-02T13:00:00Z"},
            "feedback": [{"id": 3, "item_id": base + 1, "event_id": 9001, "verdict": "watch", "score": None,
                          "note": None, "scope": "item", "created_at": "2026-10-03T12:00:00Z"},
                         {"id": 4, "item_id": base + 1, "event_id": 9001, "verdict": "lead", "score": None,
                          "note": None, "scope": "item", "created_at": "2026-10-03T13:00:00Z"},
                         {"id": 5, "item_id": None, "event_id": 9001, "verdict": "digest", "score": None,
                          "note": "Should have been in: big deals belong", "scope": "item",
                          "created_at": "2026-10-03T14:00:00Z"}],
            "why": _why_coreweave(),
            "correction": None,
        },
        {
            "id": base + 2, "edition_id": edition_id, "rank": 2, "event_id": 9002, "event_ids": [9003],
            "score": 78, "tier": "industry", "module": "defense-unmanned",
            "modules": ["defense-unmanned", "ai-infra"], "story_id": None,
            "headline": "Army awards $48M counter-UAS order to Anduril",
            "text": "The Army awarded a $48 million firm-fixed-price order for counter-UAS interceptors.",
            "metrics": [{"label": "Obligated", "value": "$48M"}],
            "sources": [{"url": "javascript:alert(1)", "title": "bad link"},
                        {"url": "https://www.war.gov/News/Contracts/", "title": "war.gov"}],
            "event": {"title": "Army awards order", "url": "https://www.war.gov/News/Contracts/",
                      "module": "defense-unmanned", "source_key": "wargov-contracts", "lane": "procurement",
                      "trust": "official", "published_at": None},
            "feedback": [],
            "why": _why_army(),
            "correction": None,
        },
    ]


def edition(edition_id: int = LATEST_ID, published_at: str = LATEST_AT, **extra) -> dict:
    body = {
        "id": edition_id, "run_id": f"rv-{edition_id}", "published_at": published_at,
        "item_count": 2, "candidate_count": 41, "backlog": 0, "rubric_version": "sha256:abc",
        "note": "Two stories cleared the bar." if edition_id == LATEST_ID else f"Briefing {edition_id} note",
        "summary": None,
        "items": items(edition_id),
        "selection": {"volume": "standard", "min_score": 70, "item_limit": 12, "near_miss_shelf": False},
        "shelves": {"watchlist": [], "near_misses": None},
        "corrections": [],
    }
    body.update(extra)
    return body


def editions(count: int = 2) -> dict:
    out = [edition(LATEST_ID, LATEST_AT)]
    if count > 1:
        out.append(edition(OLDER_ID, OLDER_AT))
    return {"editions": out[:count], "next_before": None, "has_more": False}


CONFERENCE_SUMMARY = ("Conferences for your coverage from Fri Oct 9, 2026 to Thu Apr 8, 2027. Changes this week: 1 new, "
                      "1 with a covered company now presenting.")
CONFERENCE_LATER = "Later (Apr 2027 to Sep 2027): Space Symposium (42nd) (Apr); MOVED - DSEI 2027 (Sep)."
CONFERENCE_UNDATED = "Dates not posted yet: Needham Growth Conference (29th) (expected Jan 2027)."


def _conference_line(cid: str, text: str, flags: list[str], url: str, presenting: list[str] | None = None) -> dict:
    return {"conference_id": cid, "text": text, "flags": flags, "dates_text": text.split(":", 1)[0], "start": None,
            "end": None, "name": cid, "city": None, "url": url, "tickers": [], "presenting": presenting or []}


def conference_item(edition_id: int = LATEST_ID, *, body_as_text: bool = False) -> dict:
    """The hub's Friday "Conferences coming up" item as GET /editions serves it (hub/src/brain.js leadView: kind
    conference_list, rank 0, score null, story_actions false, the list in `conferences`, built by hub/src/conferences.js
    conferenceList). body_as_text: an older shape, the stored `body` column as JSON text. Its October lines come
    unsorted (a flagged line second) to check that flags lead; one name carries markup and one link is a javascript:
    URL."""
    body = {
        "from": "2026-10-09", "until": "2027-04-08", "months_ahead": 6, "summary": CONFERENCE_SUMMARY,
        "changes": {"new": 1, "dates_set": 0, "now_presenting": 1, "moved": 0},
        "months": [
            {"month": "2026-10", "label": "October 2026", "lines": [
                _conference_line("thinkequity-conference-2026", "Oct 15: ThinkEquity Conference, New York, NY. For RCAT. "
                                 "Small-cap investor day.", [], "https://www.think-equity.com/thinkequity-conference"),
                _conference_line("ausa-meeting-exposition-2026", "NOW PRESENTING: DPRO - Oct 12-14: AUSA Annual Meeting "
                                 "& Exposition 2026, Washington, DC. Presenting: DPRO. Also for RCAT, ONDS.",
                                 ["NOW PRESENTING: DPRO"], "https://meetings.ausa.org/annual/2026/", ["DPRO"]),
            ]},
            {"month": "2026-11", "label": "November 2026", "lines": []},
            {"month": "2026-12", "label": "December 2026", "lines": [
                _conference_line("humanoids-summit-2026", "NEW - Dec 1-2: Humanoids <Summit> Silicon Valley 2026, San Mateo, "
                                 "CA. For MBAI, SYM. Sheriffs and public-safety drones, too.", ["NEW", "SOMETHING_ELSE"],
                                 "javascript:alert(1)"),
            ]},
        ],
        "later": {"text": CONFERENCE_LATER, "conferences": []},
        "undated": {"text": CONFERENCE_UNDATED, "conferences": []},
    }
    text = "\n\n".join([CONFERENCE_SUMMARY, "October 2026\n- line", CONFERENCE_LATER, CONFERENCE_UNDATED])
    item = {
        "id": 100 * edition_id + 9, "edition_id": edition_id, "rank": 0, "kind": "conference_list", "event_id": None,
        "event_ids": [], "score": None, "tier": None, "headline": "Conferences coming up", "text": text, "metrics": [],
        "sources": [], "story_id": None, "module": None, "modules": [], "feedback": [], "why": None, "correction": None,
        "story_actions": False,
    }
    if body_as_text:
        item["body"] = json.dumps(body)
    else:
        item["conferences"] = body
    return item


def with_conferences(**kwargs) -> dict:
    """The latest briefing led by the conference list."""
    body = editions()
    body["editions"][0]["items"].insert(0, conference_item(**kwargs))
    return body


def shelf_row(event_id: int, title: str, score: int, *, stars: list[dict] | None = None,
              reason_code: str = "watch", reason: str = "Near miss") -> dict:
    return {"event_id": event_id, "title": title, "url": f"https://example.com/story-{event_id}",
            "published_at": "2026-10-03T15:00:00Z", "module": "ai-infra", "source_key": "dcd-news",
            "source_label": "Data Center Dynamics", "decision": "rejected", "score": score,
            "reason_code": reason_code, "reason": reason, "rationale": "Close, but no signed capacity.",
            "stars": stars or [], "canonical_event_id": None}


def with_shelves() -> dict:
    body = editions(1)
    body["editions"][0]["shelves"] = {
        "watchlist": [shelf_row(1300, "CoreWeave opens a <new> site in Texas", 62,
                                stars=[{"entity_id": "coreweave", "name": "CoreWeave"}])],
        "near_misses": [shelf_row(1301, "Nebius raises capital for new capacity", 66),
                        shelf_row(1302, "Applied Digital updates guidance", 61, reason_code="below_bar",
                                  reason="Below your \"how much\" setting")],
    }
    body["editions"][0]["selection"].update(near_miss_shelf=True)
    return body


def with_corrections() -> dict:
    """Item 1 flagged, item 2 corrected (new text and metrics), plus an edition-level corrected and upheld note."""
    body = editions(1)
    ed = body["editions"][0]
    ed["items"][0]["correction"] = {"correction_id": 7, "state": "flagged", "note": "The term is 12 years",
                                    "flagged_at": "2026-10-04T12:30:00Z", "resolved_at": None,
                                    "resolved_edition_id": None, "headline": None, "text": None, "metrics": None}
    ed["items"][1]["correction"] = {"correction_id": 8, "state": "corrected", "note": "It was $12M",
                                    "flagged_at": "2026-10-03T12:30:00Z", "resolved_at": "2026-10-04T11:40:00Z",
                                    "resolved_edition_id": LATEST_ID,
                                    "headline": "Army awards $12M counter-UAS order to Anduril",
                                    "text": "The Army awarded a $12 million order for interceptors.",
                                    "metrics": [{"label": "Obligated", "value": "$12M"}]}
    ed["corrections"] = [
        {"correction_id": 8, "item_id": 1102, "original_edition_id": OLDER_ID,
         "original_headline": "Army awards $48M counter-UAS order to Anduril", "outcome": "corrected",
         "headline": "Army awards $12M counter-UAS order to Anduril",
         "text": "The award was $12 million, not $48 million.",
         "sources": [{"url": "https://www.war.gov/News/Contracts/", "title": "war.gov"}],
         "metrics": [{"label": "Obligated", "value": "$12M"}], "note": "It was $12M",
         "flagged_at": "2026-10-03T12:30:00Z", "resolved_at": "2026-10-04T11:40:00Z"},
        {"correction_id": 9, "item_id": 1101, "original_edition_id": OLDER_ID,
         "original_headline": "Nebius signs 300 MW deal", "outcome": "upheld", "headline": None,
         "text": "The release states 300 MW in its second paragraph; the story is correct.", "sources": [],
         "metrics": None, "note": "Was it 30 MW?", "flagged_at": "2026-10-03T12:00:00Z",
         "resolved_at": "2026-10-04T11:40:00Z"},
    ]
    return body


def upheld_item() -> dict:
    body = editions(1)
    body["editions"][0]["items"][0]["correction"] = {
        "correction_id": 9, "state": "upheld", "note": "Was it 30 MW?", "flagged_at": "2026-10-03T12:00:00Z",
        "resolved_at": "2026-10-04T11:40:00Z", "resolved_edition_id": LATEST_ID, "headline": None,
        "text": "The release states 200 MW.", "metrics": None}
    return body


def page(start_id: int, count: int, *, more: bool) -> dict:
    """One full page of `count` briefings, newest first, 12 hours apart, starting at start_id."""
    base = datetime(2026, 10, 3, 11, 41, tzinfo=timezone.utc)
    out = []
    for n in range(count):
        eid = start_id - n
        published = (base - timedelta(hours=12 * (LATEST_ID + 8 - eid))).isoformat().replace("+00:00", "Z")
        ed = edition(eid, published)
        ed["note"] = f"Briefing {eid} note"
        out.append(ed)
    return {"editions": out, "next_before": start_id - count + 1 if more else None, "has_more": more}


def preferences() -> dict:
    """GET /preferences, only what the Why expander looks up (I-0003's words)."""
    return {"preferences": [
        {"id": "I-0003", "kind": "item", "scope": "similar", "direction": "less", "status": "paused",
         "text": "Show me less like this: stock-move articles with no new facts.", "stats": {}},
    ], "suggestions": [], "soft_cap": {"active": 1, "cap": 40, "over": False}, "summary_7d": {},
        "counts": {"active": 0, "paused": 1, "retired": 0}}


def preference_created(pid: str = "R-0013", hours_ahead: float = 2.0) -> dict:
    return {"preference": {"id": pid, "kind": "item", "scope": "similar", "direction": "more", "status": "active",
                           "text": "Show me more like this: production orders for small drones."},
            "wording_draft_id": 41, "warnings": [], "effective": effective(hours_ahead)}


def retired(pid: str = "R-0013") -> dict:
    return {"preference": {"id": pid, "status": "retired", "retired_reason": "undone"}, "changed": True,
            "restored": None, "warnings": [], "effective": effective()}


def feedback_stored(correction_id: int | None = None, hours_ahead: float = 2.0) -> dict:
    return {"id": 80, "feedback": {"id": 80}, "draft_id": None, "correction_id": correction_id,
            "effective": effective(hours_ahead)}


def promoted() -> dict:
    return {"created": True, "requeue": {"event_id": 1301, "reason": "promote"}, "feedback_id": 81,
            "effective": effective()}


def mute_preview(kind: str = "source", label: str = "CoreWeave newsroom", *, already: bool = False) -> dict:
    return {"kind": kind, "module": "ai-infra" if kind == "source" else None, "ref": "ent-coreweave-1",
            "label": label, "window_days": 7, "would_hide": 42, "in_briefing": 1, "official_records": 3,
            "already_muted": already,
            "examples": [{"event_id": 1234, "title": "CoreWeave adds a <site>", "published_at": "2026-10-02T15:00:00Z",
                          "kind": "article", "source_label": "CoreWeave newsroom", "in_briefing": True},
                         {"event_id": 1235, "title": "CoreWeave hires", "published_at": "2026-10-01T15:00:00Z",
                          "kind": "press_release", "source_label": "CoreWeave newsroom", "in_briefing": False}],
            "text": "Would have hidden 42 stories in the last 7 days; 1 was in your briefing; 3 were official records."}


def mute_added(mute_id: int = 4, *, created: bool = True, applied_now: int = 30, kind: str = "source") -> dict:
    return {"created": created,
            "mute": {"id": mute_id, "kind": kind, "module": "ai-infra" if kind == "source" else None,
                     "ref": "ent-coreweave-1", "label": "CoreWeave newsroom", "note": None, "active": True,
                     "created_at": iso(), "removed_at": None, "brought_back": False,
                     "rule": "mute:source:ai-infra/ent-coreweave-1", "hidden_total": applied_now,
                     "hidden_7d": applied_now},
            "applied_now": applied_now, "preview": mute_preview(), "warnings": [], "effective": effective()}


def mutes() -> dict:
    return {"mutes": [{"id": 6, "kind": "entity", "module": None, "ref": "anduril", "label": "Anduril", "note": None,
                       "active": True, "created_at": "2026-10-01T12:00:00Z", "removed_at": None,
                       "brought_back": False, "rule": "mute:entity:anduril", "hidden_total": 9, "hidden_7d": 4}],
            "active_count": 1}


def mute_removed(mute_id: int = 6, brought_back: int = 4) -> dict:
    return {"mute": dict(mutes()["mutes"][0], id=mute_id, active=False, removed_at=iso()),
            "brought_back": brought_back, "requeued": brought_back, "effective": effective()}


def star_preview() -> dict:
    return {"entity_id": "coreweave", "label": "CoreWeave", "window_days": 7, "matches": 9, "in_briefing": 2,
            "not_in_briefing": 7, "examples": [],
            "text": "9 stories about CoreWeave in the last 7 days; 2 were in your briefing."}


def star_added(created: bool = True) -> dict:
    return {"created": created,
            "star": {"id": 2, "entity_id": "coreweave", "label": "CoreWeave", "note": None, "active": True,
                     "created_at": iso(), "removed_at": None, "matches_7d": 9, "in_briefing_7d": 2},
            "preview": star_preview(), "effective": effective()}


def star_removed() -> dict:
    return {"star": {"id": 3, "entity_id": "microsoft", "label": "Microsoft", "active": False}, "removed": True,
            "effective": effective()}
