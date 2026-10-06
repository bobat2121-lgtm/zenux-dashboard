"""Hub bodies for the Tuning tests and What ZENITH looks for (docs/SPEC-PHASE02.md 5.6-5.13, the shapes
hub/src/preferences.js and hub/src/tuning.js return; the page is docs/SPEC-SIMPLIFY.md 2.3). Fresh copies per call;
markup in a few texts checks the escaping.

`route_reads(http)` routes every read the page makes to these bodies (on top of helpers.hub_defaults), so the tests do
not depend on the shared fixtures' contents.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

HUB = "https://zenux-pilot-hub.test.invalid"
TZ = "America/New_York"
NOW = datetime.now(timezone.utc).replace(microsecond=0)  # frozen at import: every call returns the same times


def iso(hours_ago: float = 0.0) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def effective(hours_ahead: float = 2.0, applies_from: str = "next_briefing") -> dict:
    return {"applies_from": applies_from, "next_briefing_at": iso(-hours_ahead), "timezone": TZ}


def future(days: float) -> str:
    return iso(-24 * days)


def _stats(**values: Any) -> dict:
    stats = {"hits_7d": 0, "hits_30d": 0, "promoted_30d": 0, "suppressed_30d": 0, "raised_under_bar_30d": 0,
             "lowered_in_briefing_30d": 0, "last_hit_at": None, "top_suppressed_sources": [],
             "top_suppressed_companies": [], "dormant": False, "looks_like_mute": None}
    stats.update(values)
    return stats


def _pref(pid: str, **values: Any) -> dict:
    row = {"id": pid, "kind": "rule" if pid.startswith("R-") else "item", "scope": "standing",
           "scope_label": "Standing preference", "direction": "less", "direction_label": "Show me less like this",
           "text": "", "note": None, "status": "active", "origin": "preference", "event_id": None, "story_id": None,
           "created_at": iso(100), "activated_at": iso(100), "paused_at": None, "expires_at": None, "retired_at": None,
           "retired_reason": None, "supersedes": None, "superseded_by": None, "example": None, "wording": None,
           "stats": _stats()}
    row.update(values)
    return row


LESS_TEXT = ('Show me less like this: stock-move articles with no new facts. Example: event #1234 "Shares jump 8% '
             'on AI hopes" from Yahoo Finance.')
MORE_TEXT = ('Show me more like this: production orders for small drones. Example: event #2201 "Army orders 500 '
             'small drones" from Breaking Defense.')
CRYPTO_TEXT = "Show me less like this: crypto price recaps."
LEGACY_TEXT = "Competitive resizing ranks above people on the importance ladder."
MUTE_LABEL = "News search: AI data center themes"


def preference_rows() -> list[dict]:
    return [
        _pref("R-0012", text=LESS_TEXT, event_id=1234, created_at=iso(90), activated_at=iso(90),
              example={"event_id": 1234, "title": "Shares jump 8% on AI <hopes>", "source_label": "Yahoo Finance"},
              wording={"draft_id": 41, "status": "proposed",
                       "proposal": {"text": "Rank stock-price move articles without new company facts as not relevant.",
                                    "rationale": "Clearer wording."},
                       "proposed_at": iso(2), "preview_summary": {"window_days": 14, "added": 0, "removed": 9}},
              stats=_stats(hits_7d=4, hits_30d=12, suppressed_30d=11, lowered_in_briefing_30d=1, last_hit_at=iso(5),
                           top_suppressed_sources=[{"module": "ai-infra", "source_key": "gn-themes",
                                                    "label": MUTE_LABEL, "n": 10}],
                           top_suppressed_companies=[{"entity_id": "example-co", "name": "Example Co", "n": 3}],
                           looks_like_mute={"kind": "source", "module": "ai-infra", "ref": "gn-themes",
                                            "label": MUTE_LABEL, "share": 0.91, "n": 10})),
        _pref("R-0010", text=CRYPTO_TEXT, created_at=iso(80), activated_at=iso(80),
              stats=_stats(hits_30d=2, suppressed_30d=2, last_hit_at=iso(30))),
        _pref("I-0007", text=MORE_TEXT, scope="similar", scope_label="Stories like this", direction="more",
              direction_label="Show me more like this", status="paused", paused_at=iso(30), expires_at=future(20),
              event_id=2201, created_at=iso(70), activated_at=iso(70),
              example={"event_id": 2201, "title": "Army orders 500 small drones", "source_label": "Breaking Defense"},
              stats=_stats(hits_30d=5, promoted_30d=2, raised_under_bar_30d=3, last_hit_at=iso(48))),
        _pref("R-0001", text=LEGACY_TEXT, scope=None, scope_label=None, direction=None, direction_label=None,
              origin="owner+refiner", created_at=iso(24 * 60), activated_at=iso(24 * 60),
              stats=_stats(dormant=True)),
        _pref("R-0005", text="Show me less like this: conference webcast notices.", status="retired",
              retired_at=iso(10), retired_reason="owner", created_at=iso(200)),
        _pref("I-0003", text="Show me more like this: Army counter-drone production awards.", kind="item",
              scope="similar", direction="more", status="retired", retired_at=iso(20), retired_reason="expired",
              expires_at=iso(20), created_at=iso(300)),
        _pref("R-0009", text="Show me less like this: share price moves.", status="retired", retired_at=iso(95),
              retired_reason="superseded", superseded_by="R-0012", created_at=iso(400)),
    ]


def grades_draft() -> dict:
    """A suggestion from the analyst's ratings (origin grades), with a preview and a conflict."""
    grades = [{"feedback_id": 50 + n, "event_id": 1300 + n, "title": f"Conference webcast notice {n} <live>",
               "verdict": "reject", "grader_decision": "selected", "grader_score": 74 - n} for n in range(6)]
    grades[4].update(grader_score=None, grader_decision="rejected")
    return {"id": 19, "kind": "rule", "text": "Suggested from 6 of your grades", "origin": "grades", "feedback_id": None,
            "context": {"feedback_ids": [50, 51, 52, 53, 54, 55], "grades": grades}, "status": "proposed",
            "proposal": {"text": "A news-search article that only announces a conference talk ranks not relevant.",
                         "rationale": "Six of your ratings downgraded conference notices, e.g. #1300.",
                         "kind": "rule", "conflicts": ["R-0001", "R-0404"],
                         "preview": [{"event_id": 7001, "from": "out", "to": "in"},
                                     {"event_id": 5555, "from": "out", "to": "in"},
                                     {"event_id": 9002, "from": "in", "to": "out"}],
                         "preview_summary": {"window_days": 14, "added": 2, "removed": 1}},
            "proposed_at": iso(4), "precedent_id": None, "decision_note": None, "decided_at": None,
            "created_at": iso(4), "updated_at": iso(4), "target_precedent_id": None,
            "preview_summary": {"window_days": 14, "added": 2, "removed": 1},
            # WF5 (docs/SPEC-PHASE05.md 3.2): plain words and the preview's stories (one no longer stored)
            "plain_text": "Suggested from 6 of your grades", "status_text": "waiting for your OK",
            "proposal_plain": {"text": "A news-search article that only announces a conference talk ranks not "
                                       "relevant.",
                               "rationale": "Six of your ratings downgraded conference notices, e.g. #1300."},
            "preview_items": [{"event_id": 7001, "title": "Miner monthly production update", "from": "out",
                               "to": "in", "source_label": "Miner Co. investor relations"},
                              {"event_id": 5555, "title": None, "from": "out", "to": "in", "source_label": None},
                              {"event_id": 9002, "title": "Army awards $48M counter-drone order", "from": "in",
                               "to": "out", "source_label": "war.gov"}],
            "preview_more": 0}


def wording_draft() -> dict:
    """The wording assistant's clearer wording for R-0012 (origin preference)."""
    return {"id": 41, "kind": "rule", "text": "stock-move articles with no new facts", "origin": "preference",
            "feedback_id": None, "context": {"precedent_id": "R-0012", "direction": "less", "scope": "standing"},
            "status": "proposed",
            "proposal": {"text": "Rank stock-price move articles without new company facts as not relevant.",
                         "rationale": "Clearer wording of your preference; see #1234 for the example.",
                         "preview_summary": {"window_days": 14, "added": 0, "removed": 9}},
            "proposed_at": iso(2), "precedent_id": None, "decision_note": None, "decided_at": None,
            "created_at": iso(50), "updated_at": iso(2), "target_precedent_id": "R-0012",
            "preview_summary": {"window_days": 14, "added": 0, "removed": 9},
            "proposal_plain": {"text": "Rank stock-price move articles without new company facts as not relevant.",
                               "rationale": "Clearer wording of your preference; see #1234 for the example."},
            "preview_items": [], "preview_more": 0}


def merge_draft() -> dict:
    """A monthly merge of two preferences (origin consolidation)."""
    return {"id": 44, "kind": "rule", "text": "Keep market-move and price-recap articles out.", "origin": "consolidation",
            "feedback_id": None, "context": {"replaces": ["R-0012", "R-0010"]}, "status": "proposed",
            "proposal": {"text": "Keep market-move and price-recap articles out unless they carry new company facts.",
                         "rationale": "Two preferences say nearly the same thing.", "kind": "rule",
                         "replaces": ["R-0012", "R-0010"], "preview": [],
                         "preview_summary": {"window_days": 14, "added": 0, "removed": 0}},
            "proposed_at": iso(6), "precedent_id": None, "decision_note": None, "decided_at": None,
            "created_at": iso(6), "updated_at": iso(6), "target_precedent_id": None,
            "preview_summary": {"window_days": 14, "added": 0, "removed": 0},
            "proposal_plain": {"text": "Keep market-move and price-recap articles out unless they carry new company "
                                       "facts.", "rationale": "Two preferences say nearly the same thing."},
            "preview_items": [], "preview_more": 0,
            # WF5 (gap 28): the preferences it replaces in their words, and whether one has ended
            "replaces_detail": [{"id": pid, "text": text, "plain_text": text, "status": "active", "status_text": "on",
                                 "ended": False} for pid, text in (("R-0012", LESS_TEXT), ("R-0010", CRYPTO_TEXT))],
            "outdated": False}


def brief_draft() -> dict:
    """The analyst's suggested change to a line of What ZENITH looks for, worded (origin brief); no preview."""
    return {"id": 45, "kind": "rule", "text": "Also rank power purchase agreements over 100 MW.", "origin": "brief",
            "feedback_id": None,
            "context": {"brief_line": {"section": "AI infrastructure", "subsection": "What ranks high",
                                       "line_id": "L-1a2b3c4d5e", "text": "Signed capacity: a contract with a hyperscaler."}},
            "status": "proposed",
            "proposal": {"text": "Signed capacity, including power purchase agreements of 100 MW or more, ranks high.",
                         "rationale": "Worded from your suggestion."},
            "proposed_at": iso(1), "precedent_id": None, "decision_note": None, "decided_at": None,
            "created_at": iso(30), "updated_at": iso(1), "target_precedent_id": None, "preview_summary": None}


def radar_draft() -> dict:
    return {"id": 46, "kind": "rule", "text": "Large-load approvals matter.", "origin": "radar", "feedback_id": None,
            "context": {"radar_id": 41, "title": "Texas large-load docket"}, "status": "proposed",
            "proposal": {"text": "Rank Texas large-load interconnection approvals as material news.",
                         "preview_summary": {"window_days": 14, "added": 1, "removed": 0}},
            "proposed_at": iso(8), "precedent_id": None, "decision_note": None, "decided_at": None,
            "created_at": iso(9), "updated_at": iso(8), "target_precedent_id": None,
            "preview_summary": {"window_days": 14, "added": 1, "removed": 0}}


def legacy_draft() -> dict:
    """An owner draft from before v8, worded by the wording assistant (only in GET /rules)."""
    return {"id": 31, "kind": "rule", "text": "counter drone orders under 1M are watch", "origin": "owner",
            "feedback_id": None, "context": None, "status": "proposed",
            "proposal": {"text": "Counter-UAS orders under $1M score in the watch band unless the buyer is new.",
                         "rationale": "Generalised from three ratings.", "kind": "rule"},
            "proposed_at": iso(20), "precedent_id": None, "decision_note": None, "decided_at": None,
            "created_at": iso(26), "updated_at": iso(20)}


def preferences(*, suggestions: list[dict] | None = None, over: bool = False,
                companies: list[dict] | None = None) -> dict:
    """GET /preferences: five suggestions and (schema 13) two suggested company names waiting for the analyst's OK
    (`companies` replaces them)."""
    rows = preference_rows()
    return {
        "generated_at": iso(0),
        "preferences": rows,
        "suggestions": suggestions if suggestions is not None else [
            grades_draft(), wording_draft(), merge_draft(), brief_draft(), radar_draft()],
        "company_suggestions": companies if companies is not None else [company_add(), company_remove()],
        "soft_cap": {"active": 41 if over else 3, "cap": 40, "over": over,
                     "warning": "You have 41 active preferences. Older ones may conflict; the wording assistant "
                                "suggests merges once a month." if over else None},
        # WF5 (gap 29): drafts still with the wording assistant, by origin (the brief suggestion of GET /rules)
        "with_assistant": {"total": 2, "by_origin": {"brief": 1, "preference": 1}},
        "summary_7d": {"hits": 23, "promoted": 4, "suppressed": 15, "raised": 3, "lowered": 0,
                       "top": [{"id": "R-0012", "text": LESS_TEXT, "hits_7d": 4}]},
        "counts": {"active": 3, "paused": 1, "retired": 3},
    }


def rules() -> dict:
    """GET /rules: the drafts list repeats suggestion 19 (deduplicated), adds the legacy draft 31, one brief
    suggestion still waiting for the wording assistant and a decided draft."""
    waiting = {"id": 50, "kind": "rule", "text": "Rank grid connection queue reforms high.", "origin": "brief",
               "feedback_id": None, "context": None, "status": "queued", "proposal": None, "proposed_at": None,
               "created_at": iso(1), "updated_at": iso(1)}
    decided = {"id": 20, "kind": "rule", "text": "resizing over people", "origin": "owner", "status": "approved",
               "proposal": {"text": "Competitive resizing ranks above people."}, "proposed_at": iso(50),
               "precedent_id": "R-0001", "created_at": iso(60), "updated_at": iso(48)}
    return {"precedents": [{"id": p["id"], "kind": p["kind"], "text": p["text"], "status": p["status"]}
                           for p in preference_rows()],
            "drafts": [grades_draft(), legacy_draft(), waiting, decided],
            "counts": {"active": 3, "paused": 1, "retired": 3, "queued": 1, "proposed": 2, "approved": 1}}


def mute(mute_id: int, kind: str, ref: str, label: str, *, module: str | None = None, active: bool = True,
         note: str | None = None, hidden_7d: int = 0, hidden_total: int = 0, brought_back: bool = False,
         created_hours: float = 50, removed_hours: float | None = None) -> dict:
    rule = f"mute:{kind}:{module + '/' if module else ''}{ref}"
    return {"id": mute_id, "kind": kind, "module": module, "ref": ref, "label": label, "note": note, "active": active,
            "created_at": iso(created_hours), "removed_at": iso(removed_hours) if removed_hours is not None else None,
            "brought_back": brought_back, "rule": rule, "hidden_total": hidden_total, "hidden_7d": hidden_7d}


def mutes() -> dict:
    rows = [
        mute(4, "source", "gn-themes", MUTE_LABEL, module="ai-infra", hidden_7d=12, hidden_total=30),
        mute(5, "entity", "example-co", "Example Co", note="Not part of the <thesis>", hidden_7d=1, hidden_total=3),
        mute(6, "story", "s-77", "Miner reports monthly hashrate", hidden_7d=2, hidden_total=2),
        mute(2, "source", "old-feed", "Old trade feed", module="ai-infra", active=False, removed_hours=30,
             created_hours=300),
        mute(1, "entity", "acme", "Acme Corp", active=False, removed_hours=60, brought_back=True, created_hours=400),
    ]
    return {"mutes": rows, "active_count": 3}


def stars() -> dict:
    return {"stars": [
        {"id": 2, "entity_id": "coreweave", "label": "CoreWeave", "note": None, "active": True, "created_at": iso(20),
         "removed_at": None, "matches_7d": 9, "in_briefing_7d": 2},
        {"id": 3, "entity_id": "nebius", "label": "Nebius", "note": "Watch the Finland build", "active": True,
         "created_at": iso(40), "removed_at": None, "matches_7d": 1, "in_briefing_7d": 0},
        {"id": 1, "entity_id": "iren", "label": "IREN", "note": None, "active": False, "created_at": iso(400),
         "removed_at": iso(300), "matches_7d": 0, "in_briefing_7d": 0},
    ]}


MODES = [{"mode": "top", "label": "Only the big ones", "bar": 80, "cap": 8},
         {"mode": "standard", "label": "Standard", "bar": 70, "cap": 12},
         {"mode": "broad", "label": "Everything notable", "bar": 60, "cap": 20}]


def volume(mode: str = "standard", shelf: bool = False) -> dict:
    caps = {m["mode"]: m for m in MODES}
    return {"mode": mode, "label": caps[mode]["label"], "bar": caps[mode]["bar"], "cap": caps[mode]["cap"],
            "near_miss_shelf": shelf, "updated_at": None, "modes": [dict(m) for m in MODES]}


def settings(mode: str = "standard", shelf: bool = False, stage: str = "live") -> dict:
    return {"volume": volume(mode, shelf), "stage": {"stage": stage, "since": iso(500)}}


PREVIEW_TEXT = {"top": "Would show about 6 per briefing instead of about 9.",
                "broad": "Would show about 14 per briefing instead of about 9.",
                "standard": "Would show about 9 per briefing, about the same as now."}


def volume_preview(call) -> dict:
    mode = (call.params or {}).get("mode", "standard")
    return {"mode": mode, "bar": 80, "cap": 8, "window_days": 7, "editions": 21, "now_avg": 9.1, "would_avg": 5.8,
            "per_edition": [], "text": PREVIEW_TEXT.get(mode, "No briefings in the last 7 days to compare.")}


def company_entry(eid: str, name: str, *, big: bool = False, kind_label: str = "Product", note: str | None = None,
                  basis: str | None = None, basis_text: str | None = None, disclosed_label: str = "Press release",
                  call_only: bool = False, unnamed: bool = False, since_label: str | None = None,
                  tags_stories: bool = True, aliases: tuple[str, ...] = ()) -> dict:
    """One name of a company's sheet as GET /brief sends it (docs/SPEC-COMPANY-MAP.md 4.2 ITEM, plus its aliases for
    Find a name)."""
    return {"id": eid, "name": name, "aliases": list(aliases), "big": big, "kind_label": kind_label, "note": note,
            "basis": basis, "basis_text": basis_text, "disclosed_label": disclosed_label, "call_only": call_only,
            "unnamed": unnamed, "since_label": since_label, "tags_stories": tags_stories}


def _company(ticker: str, name: str, summary: str, columns: dict, pending: list | None = None) -> dict:
    return {"ticker": ticker, "name": name, "summary": summary, "columns": columns,
            "counts": {column: len(rows) for column, rows in columns.items()}, "pending": pending or []}


def brief_companies() -> dict:
    """GET /brief `companies` (docs/SPEC-COMPANY-MAP.md 4.2), out of ticker order: Red Cat (big and not big names, call-only
    customers, a pending suggestion being checked, a name that tags no story), Planet Labs ("Sentinel Hub" trips the
    jargon guard; a suggestion with no status_label) and Rekor Systems ("Rekor Scout" trips it; an unnamed big customer,
    no units, an approved suggestion and a live one, which no longer shows)."""
    e = company_entry
    rcat = _company("RCAT", "Red Cat Holdings", "Small military reconnaissance drones (Black Widow) and uncrewed boats.", {
        "products": [
            e("p-black-widow", "Black Widow", big=True, note="The Army's short-range reconnaissance drone.",
              aliases=("Black Widow sUAS", "Teal Black Widow")),
            e("p-hellcat", "Hellcat", big=True, note="A first-person-view strike drone.", since_label="Since May 2025",
              aliases=("Hellcat sUAS",)),
            e("p-fang", "FANG", note="A line of small strike drones.", tags_stories=False)],
        "units": [
            e("u-teal-drones", "Teal Drones", big=True, kind_label="Bought Aug 2021",
              disclosed_label="Filing", note="Makes Black Widow and Hellcat in Salt Lake City.",
              aliases=("Teal Drones, Inc.", "Teal 2")),
            e("u-blue-ops", "Blue Ops", kind_label="Bought Jan 2025", note="Uncrewed boats.")],
        "customers": [
            e("c-army-srr", "U.S. Army SRR program", big=True, kind_label="Program", basis="share",
              basis_text="73% of 2025 revenue", disclosed_label="Filing"),
            e("c-jgsdf", "Japan Ground Self-Defense Force", big=True, kind_label="Government buyer", basis="assumed",
              basis_text="#2 customer in H1 2026, named on the call", disclosed_label="Earnings call",
              since_label="First named Apr 2026"),
            e("c-nspa", "NATO NSPA", big=True, kind_label="Sales channel", basis="assumed",
              basis_text="Named among the top customers on the Q2 2026 call", disclosed_label="Earnings call"),
            e("c-spetstechnoexport", "Spetstechnoexport (Ukraine)", big=True, kind_label="Government buyer",
              basis="forecast", basis_text="Expected: Ukraine asked for 100,000+ drones",
              disclosed_label="Earnings call", call_only=True, aliases=("Spetstechnoexport",)),
            e("c-air-force", "U.S. Air Force", kind_label="Government buyer", disclosed_label="News",
              since_label="First named Apr 2025",
              note="Testing Black Widow to replace the Teal 2 (2025-04-02).")],
        "read_through": [
            e("r-aerovironment", "AeroVironment", big=True, kind_label="Competitor", disclosed_label="News",
              note="The main U.S. small-drone maker."),
            e("r-skydio", "Skydio", big=True, kind_label="Competitor", disclosed_label="News"),
            e("r-parrot", "Parrot", kind_label="Competitor", disclosed_label="News")],
    }, [{"id": "CS-1a2b3c4d", "column": "customers", "action": "add", "name": "Drone Dominance program",
         "status": "queued", "status_label": "Being checked", "big": True}])
    pl = _company("PL", "Planet Labs", "Earth-imaging satellites and data.", {
        "products": [e("p-pelican", "Pelican", big=True, note="The next high-resolution satellites."),
                     e("p-skysat", "SkySat", big=True),
                     e("p-insights", "Planet Insights Platform", kind_label="Brand")],
        "units": [e("u-sentinel-hub", "Sentinel Hub", big=True, kind_label="Bought Aug 2023",
                    disclosed_label="Filing",
                    note="Sentinel Hub keeps its own brand: a satellite data platform from Slovenia.",
                    aliases=("Sinergise", "Sinergise (Sentinel Hub)"))],
        "customers": [e("c-nga", "NGA", big=True, kind_label="Government buyer", basis="share",
                        basis_text="About 20% of 2025 revenue", disclosed_label="Filing"),
                      e("c-german-government", "German government", big=True, kind_label="Government buyer",
                        basis="forecast", basis_text="Expected: a satellite deal of about €240M")],
        "read_through": [e("r-blacksky", "BlackSky", big=True, kind_label="Competitor", disclosed_label="News"),
                         e("r-iceye", "ICEYE", kind_label="Competitor", disclosed_label="News")],
    }, [{"id": "CS-2b3c4d5e", "column": "products", "action": "change", "name": "Planet Insights Platform",
         "status": "proposed", "status_label": None, "big": None}])
    rekr = _company("REKR", "Rekor Systems", "Roadway data and license-plate recognition.", {
        "products": [e("p-rekor-scout", "Rekor Scout", big=True, note="License-plate recognition software.",
                       aliases=("OpenALPR by Rekor",)),
                     e("p-rekor-discover", "Rekor Discover", big=True),
                     e("p-rekor-command", "Rekor Command")],
        "units": [],
        "customers": [e("c-customer-a", "Customer A", big=True, kind_label="Customer", basis="share",
                        basis_text="40% of Q2 2026 revenue", disclosed_label="Filing", call_only=True, unnamed=True,
                        tags_stories=False),
                      e("c-txdot", "Texas Department of Transportation", kind_label="Government buyer")],
        "read_through": [e("r-flock", "Flock Safety", big=True, kind_label="Competitor", disclosed_label="News"),
                         e("r-soundthinking", "SoundThinking", big=True, kind_label="Competitor",
                           disclosed_label="News")],
    }, [{"id": "CS-3c4d5e6f", "column": "read_through", "action": "remove", "name": "SoundThinking",
         "status": "approved", "status_label": "Approved: the ZENITH editor stops counting it from the next briefing",
         "big": None},
        {"id": "CS-4d5e6f70", "column": "products", "action": "add", "name": "Rekor Edge",
         "status": "live", "status_label": None, "big": None}])
    return {"items": [rcat, pl, rekr], "pending_total": 3}


def brief(stage: str = "live", signed_by: str | None = "owner") -> dict:
    signoff = None
    if signed_by:
        signoff = {"id": 1, "signed_at": iso(30), "by": signed_by, "note": None, "rubric_version": "64154d4b0a1b2c3d",
                   "precedents_version": "pv-1", "catalog_versions": {}}
    return {
        "workspace": "pilot", "stage": stage, "generated_at": iso(0),
        # WF5 (docs/SPEC-PHASE05.md 3.1): the approved vocabulary; the rubric's own words only in original*
        "title": "What ZENITH looks for: AI infrastructure and defense unmanned",
        "original_title": "Pilot rubric v0: AI infrastructure and defense unmanned",
        "rubric_version": "64154d4b0a1b2c3d", "precedents_version": "pv-1",
        "catalog_versions": {"ai-infra": "0.1.0-3f2a9c1b7d4e", "defense-unmanned": "0.1.0-77aa00bb11cc"},
        "sections": [
            {"id": "s-scores", "heading": "How stories are scored", "module": None,
             "parts": [{"kind": "scores", "title": "Scores", "lines": [
                 {"id": "L-0a1b2c3d4e", "text": "90+: Top story", "original": "90+: Lead item"},
                 {"id": "L-0b1c2d3e4f", "text": "40-69: Near miss; listed under each briefing in Left out",
                  "original": "40-69: Watch; shows on the Rejected tab"},
                 {"id": "L-0c1d2e3f40", "text": "Your coverage, Read-through, Industry and policy",
                  "original": "Tier 1, Tier 2, Tier 3"}]}]},
            {"id": "s-ai-infrastructure", "heading": "AI infrastructure: data centers, colocation, AI cloud, bitcoin miners",
             "module": "ai-infra",
             "parts": [
                 {"kind": "rank_high", "title": "What ranks high", "lines": [
                     {"id": "L-1a2b3c4d5e", "text": "Signed capacity: a contract with a hyperscaler or AI lab. Capture MW, "
                                                   "dollar value, term and counterparty."},
                     {"id": "L-2b3c4d5e6f", "text": "Power: interconnection approvals for 100 MW or more."}]},
                 {"kind": "ignored", "title": "What is ignored", "lines": [
                     {"id": "L-3c4d5e6f70", "text": "Stock-price moves without new facts <b>at all</b>."}]}]},
            # "Your companies' big names" is drawn right after this section (docs/SPEC-COMPANY-MAP.md 6.1)
            {"id": "s-your-coverage", "heading": "Your coverage: the covered companies", "module": "coverage",
             "parts": [{"kind": "who", "title": "Who is covered", "lines": [
                 {"id": "L-5e6f708192", "text": "Red Cat, Planet Labs and Rekor Systems, with their units, brands and "
                                               "products."}]}]},
            {"id": "s-defense-unmanned", "heading": "Defense unmanned: drones and counter-drone systems",
             "module": "defense-unmanned",
             "parts": [{"kind": "who", "title": "Who is covered", "lines": [
                 {"id": "L-4d5e6f7081", "text": "Prime contractors and venture-backed drone makers."}]}]},
        ],
        "preferences": [{"id": p["id"], "kind": p["kind"], "text": p["text"], "direction": p["direction"],
                         "scope": p["scope"], "direction_label": p["direction_label"], "scope_label": p["scope_label"],
                         "status": p["status"], "expires_at": p["expires_at"]}
                        for p in preference_rows() if p["status"] in ("active", "paused")],
        "mutes": [m for m in mutes()["mutes"] if m["active"]],
        "stars": [s for s in stars()["stars"] if s["active"]],
        "volume": volume(),
        "coverage": [
            {"module": "ai-infra", "title": "AI infrastructure: data centers, colocation, AI cloud, bitcoin miners",
             "catalog_version": "0.1.0-3f2a9c1b7d4e", "entities": 142, "sources": 188,
             "covered": [{"category_label": "AI cloud", "names": ["CoreWeave", "Nebius"]},
                         {"category_label": "Bitcoin miners", "names": ["IREN", "Cipher <Mining>"]}]},
            {"module": "defense-unmanned", "title": "Defense unmanned: drones and counter-drone systems",
             "catalog_version": "0.1.0-77aa00bb11cc", "entities": 90, "sources": 120,
             "covered": [{"category_label": "Drone makers", "names": ["Anduril", "Shield AI"]}]},
        ],
        "signoff": {"last": signoff, "count": 1 if signoff else 0},
        "companies": brief_companies(),
    }


# ---------------------------------------------------------------------------------------------- write answers


def preference_view(pid: str, **values: Any) -> dict:
    base = next((p for p in preference_rows() if p["id"] == pid), None) or _pref(pid)
    return {**base, **values}


def approved(new_id: str = "R-0014", superseded: str | None = None, retired: list[str] | None = None) -> dict:
    return {"draft": {"id": 19, "status": "approved", "precedent_id": new_id},
            "precedent": {"id": new_id, "precedent_id": new_id, "status": "active"},
            "preference": preference_view(new_id, text="The approved wording.", supersedes=superseded),
            "superseded": superseded, "retired": retired or [], "warnings": [], "effective": effective()}


def rejected_draft(draft_id: int) -> dict:
    return {"draft": {"id": draft_id, "status": "rejected"}}


def lifecycle(pid: str, status: str = "active", **values: Any) -> dict:
    return {"preference": preference_view(pid, status=status, **values), "changed": True, "warnings": [],
            "effective": effective()}


def edited(new_id: str = "R-0015", old_id: str = "R-0012") -> dict:
    return {**lifecycle(new_id, supersedes=old_id), "replaces": old_id}


def retired(pid: str, restored: str | None = None) -> dict:
    return {"precedent": {"id": pid, "status": "retired"}, "changed": True, "previous_status": "active",
            "restored": restored, "preference": preference_view(pid, status="retired"), "warnings": [],
            "effective": effective()}


def created(new_id: str = "R-0016", warnings: list[str] | None = None) -> dict:
    return {"preference": preference_view(new_id, text="Fewer crypto recaps."), "wording_draft_id": 52,
            "warnings": warnings or [], "effective": effective()}


def volume_set(mode: str = "top", shelf: bool = False) -> dict:
    return {"volume": volume(mode, shelf), "effective": effective()}


def signed_off() -> dict:
    return {"signoff": {"id": 2, "signed_at": iso(0), "by": "owner", "note": None}, "stage": "live",
            "effective": effective(3)}


def suggested() -> dict:
    return {"draft": {"id": 53, "status": "queued", "origin": "brief"},
            "effective": effective(applies_from="after_approval")}


def company_suggested(**values: Any) -> dict:
    """POST /companies/suggestions -> 201 {suggestion, effective} (docs/SPEC-COMPANY-MAP.md 5.2): queued for the source
    finder."""
    suggestion = {"id": "CS-5e6f7081", "ticker": "RCAT", "column": "customers", "action": "add",
                  "name": "Spetstechnoexport", "status": "queued", "created_at": iso(0), "updated_at": iso(0)}
    suggestion.update(values)
    return {"suggestion": suggestion, "effective": effective(applies_from="after_approval")}


DRONE_URL = "https://example.com/red-cat-drone-dominance"
REKOR_URL = "https://example.com/rekor-2025-annual-report"


def company_row(sid: str, ticker: str, company: str | None, column: str, action: str, name: str | None, *,
                status: str = "proposed", hours: float = 5, verdict: Any = None, **values: Any) -> dict:
    """One suggested company name as GET /preferences `company_suggestions` and GET /companies/suggestions send it
    (docs/SPEC-COMPANY-MAP.md 5.1: what the analyst typed, the source finder's verdict), with the company's name."""
    row = {"id": sid, "ticker": ticker, "company_name": company, "column": column, "action": action, "target_id": None,
           "name": name, "aliases": [], "note": None, "kind": None, "big": None, "basis": None, "basis_text": None,
           "link": None, "analyst_note": None, "status": status, "verdict": verdict, "created_at": iso(hours + 20),
           "updated_at": iso(hours), "proposed_at": iso(hours), "decided_at": None, "applied_at": None,
           "live_at": None}
    row.update(values)
    return row


def company_add(**values: Any) -> dict:
    """The analyst's "Drone Dominance" for Red Cat's customers: confirmed by the source finder, who cleaned up the
    name, added another name and made it a big customer by forecast."""
    verdict = {"result": "confirmed",
               "evidence": [{"url": DRONE_URL, "title": "Red Cat selected for the Army's <Drone Dominance> program",
                             "date": "2026-09-30",
                             "quote": "Red Cat expects Drone Dominance orders to begin in the first half of 2026."},
                            {"url": "javascript:alert(1)", "title": "Red Cat Q2 2026 earnings call", "date": "2026-08",
                             "quote": None}],
               "proposal": {"name": "Army Drone Dominance program", "aliases": ["Drone Dominance"], "kind": "program",
                            "note": "U.S. Army plan to buy small drones in large numbers from 2026.", "big": True,
                            "basis": "forecast", "basis_text": "Expected: the Army plans to buy about 1 million drones",
                            "entity_id": "drone-dominance"},
               "summary": "Red Cat's September release names the program; management expects orders in 2026."}
    return {**company_row("CS-6f708192", "RCAT", "Red Cat Holdings", "customers", "add", "Drone Dominance", hours=5,
                          note="Army plan to buy drones at scale", big=True, basis_text="Management expects big orders",
                          link="https://example.com/drone-dominance-news", analyst_note="Heard it on the Q2 call.",
                          verdict=verdict), **values}


def company_remove(**values: Any) -> dict:
    """The analyst's "Rekor Scout is gone" for Rekor Systems' products ("Scout" trips the jargon guard): the source
    finder could not confirm it and says so in a sentence that names it."""
    verdict = {"result": "not_confirmed",
               "evidence": [{"url": REKOR_URL, "title": "Rekor Systems 2025 annual report", "date": "2026-03-14",
                             "quote": "Rekor Scout remains our license-plate recognition product."}],
               "proposal": None,
               "summary": "The 2025 annual report still lists Rekor Scout as a product; nothing says it was folded "
                          "into another one."}
    return {**company_row("CS-7081920a", "REKR", "Rekor Systems", "products", "remove", "Rekor Scout", hours=12,
                          target_id="p-rekor-scout", note="Folded into Rekor Discover in 2025", verdict=verdict),
            **values}


def company_fix(**values: Any) -> dict:
    """A rename of Planet Labs' "Planet Insights Platform", its verdict as JSON text and no company name (the ticker
    stands in): the source finder was not sure."""
    verdict = json.dumps({"result": "unclear", "evidence": [], "summary": None,
                          "proposal": {"name": "Planet Insights", "note": "Planet's data platform, renamed in 2025."}})
    return {**company_row("CS-2b3c4d5e", "PL", None, "products", "change", "Planet Insights", hours=7,
                          target_id="p-insights", target_name="Planet Insights Platform", verdict=verdict), **values}


def company_approved(**values: Any) -> dict:
    """company_add, approved by the analyst (the source finder's version): waiting for the builder."""
    return company_add(**{"status": "approved", "decided_at": iso(2), "use": "proposal", **values})


def company_applied(**values: Any) -> dict:
    """A big customer of Planet Labs approved as the analyst typed it and applied: waiting for a deploy."""
    verdict = {"result": "confirmed", "evidence": [{"url": "https://example.com/planet-bundeswehr", "title":
                                                    "Planet signs a satellite deal with Germany", "date": "2026-07-02"}],
               "proposal": {"name": "German Armed Forces", "big": True, "basis": "forecast",
                            "basis_text": "Expected: a satellite deal of about €240M"},
               "summary": "Planet's July release names the deal."}
    row = company_row("CS-8192a3b4", "PL", "Planet Labs", "customers", "add", "Bundeswehr", status="applied",
                      hours=40, big=True, basis_text="Expected: a satellite deal of about €240M", verdict=verdict,
                      decided_at=iso(30), applied_at=iso(20), use="as_typed")
    row.update(values)
    return row


def company_list(rows: list[dict], status: str | None = None) -> dict:
    """GET /companies/suggestions?status=: the rows of that status (all without one) and the counts by status."""
    counts = {s: sum(1 for r in rows if r["status"] == s)
              for s in ("queued", "proposed", "approved", "applied", "live", "rejected", "withdrawn")}
    return {"suggestions": [r for r in rows if status is None or r["status"] == status], "counts": counts}


def company_decided(sid: str, status: str) -> dict:
    """POST /companies/suggestions/<id>/(approve|reject) -> {suggestion, effective}."""
    return {"suggestion": {"id": sid, "status": status, "decided_at": iso(0)},
            "effective": effective(applies_from="next_briefing")}


def refusal(http_status: int, code: str, message: str, **extra: Any):
    """A hub refusal {error, message, ...extra} with that HTTP status."""
    from helpers import FakeResponse

    return FakeResponse(http_status, {"error": code, "message": message, **extra})


def route_reads(http, base: str = HUB) -> None:
    """Every read Tuning (and What ZENITH looks for) makes, routed to the bodies above."""
    http.on("GET", base + "/preferences", preferences())
    http.on("GET", base + "/rules", rules())
    http.on("GET", base + "/mutes", mutes())
    http.on("GET", base + "/stars", stars())
    http.on("GET", base + "/settings", settings())
    http.on("GET", base + "/settings/volume/preview", volume_preview)
    http.on("GET", base + "/brief", brief())


def rule_url(rule_id: Any, action: str, base: str = HUB) -> str:
    return f"{base}/rules/{quote(str(rule_id), safe='')}/{action}"
