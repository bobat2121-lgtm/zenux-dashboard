"""Hub bodies for the Tuning tests and What ZENITH looks for (docs/SPEC-PHASE02.md 5.6-5.13, the shapes
hub/src/preferences.js and hub/src/tuning.js return; the page is docs/SPEC-SIMPLIFY.md 2.3). Fresh copies per call;
markup in a few texts checks the escaping.

`route_reads(http)` routes every read the page makes to these bodies (on top of helpers.hub_defaults), so the tests do
not depend on the shared fixtures' contents.
"""

from __future__ import annotations

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


def preferences(*, suggestions: list[dict] | None = None, over: bool = False) -> dict:
    rows = preference_rows()
    return {
        "generated_at": iso(0),
        "preferences": rows,
        "suggestions": suggestions if suggestions is not None else [
            grades_draft(), wording_draft(), merge_draft(), brief_draft(), radar_draft()],
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
