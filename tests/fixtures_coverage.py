"""Hub bodies for the Coverage tab, coverage requests and the Control room's module view (docs/SPEC-PHASE02.md 5.4-5.7,
radar closure R). Fresh copies per call. Hostile values (markup in names, a javascript: link) check the escaping."""

from __future__ import annotations

from fixtures import iso

AI_TITLE = "AI infrastructure: data centers, colocation, AI cloud, bitcoin miners"
DEF_TITLE = "Defense unmanned: drones, counter-drone, autonomy"


def effective(hours_ahead: float = 2) -> dict:
    return {"applies_from": "next_briefing", "next_briefing_at": iso(-hours_ahead), "timezone": "America/New_York"}


def modules() -> dict:
    """GET /modules (5.4): two coverage areas."""
    return {"generated_at": iso(0), "modules": [
        {"id": "ai-infra", "title": AI_TITLE, "configured": True,
         "catalog": {"version": "0.1.0-3f2a9c1b7d4e", "pushed_at": iso(30), "git_sha": "abc123def456"},
         "counts": {"sources": 8, "sources_enabled": 6, "sources_off": 2, "entities": 7, "items_7d": 1840,
                    "briefing_30d": 61},
         "health": {"status": "ok", "stale": False, "minutes_since_run": 4}, "mutes": 2, "stars": 1},
        {"id": "defense-unmanned", "title": DEF_TITLE, "configured": True,
         "catalog": {"version": "0.1.0-77aa88bb99cc", "pushed_at": iso(30), "git_sha": "abc123def456"},
         "counts": {"sources": 1, "sources_enabled": 1, "sources_off": 0, "entities": 1, "items_7d": 61,
                    "briefing_30d": 4},
         "health": {"status": "partial", "stale": False, "minutes_since_run": 21}, "mutes": 0, "stars": 0},
    ]}


def _stats(items_7d: int, briefing_30d: int, items_30d: int | None = None, briefing_7d: int | None = None) -> dict:
    """A row's stats; `briefing_7d` (WF5, gap 12) only where a test gives it, so other rows read as an older hub."""
    out = {"items_7d": items_7d, "items_30d": items_7d * 4 if items_30d is None else items_30d,
           "briefing_30d": briefing_30d, "last_item_at": iso(3)}
    if briefing_7d is not None:
        out["briefing_7d"] = briefing_7d
    return out


def _source(key: str, label: str, lane: str, lane_label: str, column: str, *, origin: str = "module",
            entity_id: str | None = None, connector: str = "rss", kind: str = "News feed", trust: str = "press",
            enabled: bool = True, off_reason: str | None = None, url: str | None = "https://example.com/feed",
            state: str = "ok", items_7d: int = 12, briefing_30d: int = 3, muted: dict | None = None,
            last_ok_at: str | None = None) -> dict:
    labels = {"ok": "Working", "failing": "Not responding", "quiet": "Quiet lately", "off": "Turned off",
              "new": "Not run yet", "retired": "Removed"}
    items_30d = items_7d * 4
    return {
        "key": key, "label": label, "origin": origin, "entity_id": entity_id, "lane": lane, "lane_label": lane_label,
        "column": column, "connector": connector, "kind": kind, "trust": trust, "enabled": enabled,
        "off_reason": off_reason, "url": url, "cadence_minutes": 60,
        "stats": {"items_7d": items_7d, "items_30d": items_30d, "briefing_30d": briefing_30d,
                  "hit_rate": round(briefing_30d / items_30d, 3) if items_30d else None, "last_item_at": iso(2)},
        "health": {"state": state, "label": labels[state], "last_ok_at": last_ok_at or iso(1), "last_status": "ok",
                   "acknowledged": False},
        "muted": muted,
    }


def _entity(eid: str, name: str, category: str, category_label: str, *, ownership: str | None = "public",
            role: str = "core", tickers: list | None = None, coverage: dict | None = None,
            source_keys: list | None = None, items_7d: int = 3, briefing_30d: int = 2, muted: dict | None = None,
            starred: dict | None = None, briefing_7d: int | None = None) -> dict:
    flags = {"own_feed": False, "sec_filings": False, "federal_contracts": False, "news_search": False,
             "name_only": False}
    flags.update(coverage or {})
    return {
        "id": eid, "name": name, "role": role, "category": category, "category_label": category_label,
        "importance": "major", "ownership": ownership, "tickers": tickers or [], "coverage": flags,
        "source_keys": source_keys or [], "stats": _stats(items_7d, briefing_30d, briefing_7d=briefing_7d),
        "muted": muted, "starred": starred,
    }


# Entity order matters: the row index n in widget keys (cv_star_<n>, cv_details_e_<n>) is the position here.
COREWEAVE, NEBIUS, CRUSOE, STARGATE_CO, TVA, GENESIS, EXAMPLE = range(7)
# Source order: cv_mute_s_<n>, cv_details_s_<n>.
DCD, EDGAR, ERCOT, GN_THEMES, OLD_PERMITS, LOUDOUN, ENT_CW_1, ENT_CW_2 = range(8)


def inspect_ai() -> dict:
    """GET /modules/ai-infra/inspect (5.5)."""
    return {
        "module": {"id": "ai-infra", "title": AI_TITLE,
                   "description": "Data center leases, power deals, AI cloud capacity and miners moving to AI.",
                   "catalog_version": "0.1.0-3f2a9c1b7d4e", "pushed_at": iso(30)},
        "generated_at": iso(0),
        "lanes": [
            {"id": "companies", "label": "Company news and filings", "column": "companies",
             "about": "What the companies themselves publish and file.", "source_count": 3, "items_7d": 30},
            {"id": "trade_press", "label": "Trade press", "column": "industry",
             "about": "Industry publications that report data center deals.", "source_count": 1, "items_7d": 12},
            {"id": "power_grid", "label": "Power and grid", "column": "government",
             "about": "Grid operators, utility commissions and FERC dockets about large loads.", "source_count": 1,
             "items_7d": 4},
            {"id": "discovery", "label": "News search", "column": "industry",
             "about": "Searches that look for companies and topics by name.", "source_count": 1, "items_7d": 900},
            {"id": "permitting", "label": "Local permitting and zoning", "column": "government",
             "about": "County agendas and permits for data center sites.", "source_count": 2, "items_7d": 7},
        ],
        "categories": [{"id": "ai_cloud", "label": "AI cloud", "entity_count": 4},
                       {"id": "power", "label": "Power companies", "entity_count": 1}],
        "sources": [
            _source("dcd-news", "Data Center Dynamics", "trade_press", "Trade press", "industry", items_7d=12,
                    briefing_30d=3),
            _source("edgar-dc-cloud", "SEC filings: data center and AI cloud companies", "companies",
                    "Company news and filings", "companies", connector="edgar", kind="Filings", trust="primary",
                    url="https://www.sec.gov/cgi-bin/browse-edgar", items_7d=8, briefing_30d=5),
            _source("ercot-large-load", "ERCOT large-load interconnection reports", "power_grid", "Power and grid",
                    "government", connector="page-watch", kind="Page watch", trust="official", state="failing",
                    last_ok_at="2026-10-01T12:00:00Z", items_7d=0, briefing_30d=0),
            _source("gn-themes", "News search: AI data center themes", "discovery", "News search", "industry",
                    connector="news-search", kind="News search", trust="search", items_7d=900, briefing_30d=2,
                    muted={"mute_id": 4, "created_at": iso(50), "note": None, "kind": "source", "module": "ai-infra",
                           "ref": "gn-themes", "label": "News search: AI data center themes"}),
            _source("old-permits", "Old county permits <page>", "permitting", "Local permitting and zoning",
                    "government", connector="html-list", enabled=False, state="off",
                    off_reason="The site blocks automated access from our servers; we will retry from another network.",
                    url="javascript:alert(1)", items_7d=0, briefing_30d=0),
            _source("loudoun-agendas", "Loudoun County, VA agendas", "permitting", "Local permitting and zoning",
                    "government", connector="legistar", kind="Meeting agendas", trust="official", items_7d=7,
                    briefing_30d=1),
            _source("ent-coreweave-1", "CoreWeave newsroom", "companies", "Company news and filings", "companies",
                    origin="entity", entity_id="coreweave", trust="primary", items_7d=2, briefing_30d=2),
            _source("ent-coreweave-2", "CoreWeave investor relations", "companies", "Company news and filings",
                    "companies", origin="entity", entity_id="coreweave", trust="primary", enabled=False, state="off",
                    off_reason="The site blocks automated access.", items_7d=0, briefing_30d=0),
        ],
        "entities": [
            _entity("coreweave", "CoreWeave", "ai_cloud", "AI cloud", tickers=["NASDAQ:CRWV"],
                    coverage={"own_feed": True, "sec_filings": True}, source_keys=["ent-coreweave-1", "ent-coreweave-2"],
                    items_7d=9, briefing_30d=2, briefing_7d=1,
                    starred={"star_id": 2, "created_at": iso(40), "note": None}),
            _entity("nebius", "Nebius", "ai_cloud", "AI cloud", tickers=["NASDAQ:NBIS"],
                    coverage={"news_search": True}, items_7d=4, briefing_30d=1),
            _entity("crusoe", "Crusoe", "ai_cloud", "AI cloud", ownership="private", coverage={"name_only": True},
                    items_7d=1, briefing_30d=0),
            _entity("stargate-co", "Stargate LLC", "ai_cloud", "AI cloud", ownership="subsidiary",
                    coverage={"news_search": True}, items_7d=2, briefing_30d=1),
            _entity("tva", "Tennessee Valley Authority", "power", "Power companies", ownership="government",
                    coverage={"federal_contracts": True}, items_7d=1, briefing_30d=0),
            _entity("doe-genesis", "DOE Genesis Mission", "program_or_agency", "Programs and agencies",
                    ownership=None, role="program", coverage={"name_only": True}, items_7d=0, briefing_30d=0),
            _entity("example-co", "Example <b>Co</b>", "power", "Power companies", ownership=None,
                    coverage={"news_search": True}, items_7d=5, briefing_30d=0,
                    muted={"mute_id": 5, "created_at": iso(20), "note": "too noisy", "kind": "entity", "module": None,
                           "ref": "example-co", "label": "Example <b>Co</b>"}),
        ],
        "orphans": [{"source_key": "old-key", "events": 41, "retired": True}],
        "totals": {"items_7d": 1840, "items_30d": 7020, "briefing_30d": 61, "briefing_7d": 14},
    }


def inspect_def() -> dict:
    """GET /modules/defense-unmanned/inspect: a small second area."""
    return {
        "module": {"id": "defense-unmanned", "title": DEF_TITLE, "description": "Drones and counter-drone programs.",
                   "catalog_version": "0.1.0-77aa88bb99cc", "pushed_at": iso(30)},
        "generated_at": iso(0),
        "lanes": [{"id": "procurement", "label": "Contracts and solicitations", "column": "government",
                   "about": "Federal awards and notices.", "source_count": 1, "items_7d": 61}],
        "categories": [{"id": "cuas_kinetic", "label": "Counter-drone: kinetic", "entity_count": 1}],
        "sources": [_source("wargov-contracts", "war.gov daily contract announcements", "procurement",
                            "Contracts and solicitations", "government", connector="wargov-contracts",
                            kind="Contracts and solicitations", trust="official", items_7d=61, briefing_30d=4)],
        "entities": [_entity("anduril", "Anduril", "cuas_kinetic", "Counter-drone: kinetic", ownership="private",
                             coverage={"federal_contracts": True, "news_search": True}, items_7d=6, briefing_30d=2)],
        "orphans": [],
        "totals": {"items_7d": 61, "items_30d": 240, "briefing_30d": 4},
    }


def catalog_missing(module: str = "ai-infra") -> dict:
    return {"error": "catalog_missing", "message": f"Coverage details for {module} appear after the next deploy."}


def mutes(include_removed: bool = False) -> dict:
    """GET /mutes (5.6): the two active mutes the inspector shows."""
    rows = [
        {"id": 4, "kind": "source", "module": "ai-infra", "ref": "gn-themes",
         "label": "News search: AI data center themes", "note": None, "active": True, "created_at": iso(50),
         "removed_at": None, "brought_back": False, "rule": "mute:source:ai-infra/gn-themes", "hidden_total": 30,
         "hidden_7d": 12},
        {"id": 5, "kind": "entity", "module": None, "ref": "example-co", "label": "Example Co", "note": "too noisy",
         "active": True, "created_at": iso(20), "removed_at": None, "brought_back": False,
         "rule": "mute:entity:example-co", "hidden_total": 7, "hidden_7d": 7},
    ]
    return {"mutes": rows, "active_count": 2}


def mute_preview(kind: str = "source", module: str | None = "ai-infra", ref: str = "dcd-news",
                 label: str = "Data Center Dynamics") -> dict:
    return {"kind": kind, "module": module, "ref": ref, "label": label, "window_days": 7, "would_hide": 42,
            "in_briefing": 0, "official_records": 3, "already_muted": False,
            "examples": [{"event_id": 1234, "title": "Example story", "published_at": iso(10), "kind": "article",
                          "source_label": label, "in_briefing": False}],
            "text": "Would have hidden 42 stories in the last 7 days; none were in your briefing; 3 were official records."}


def mute_added(mute_id: int = 9, kind: str = "source", module: str | None = "ai-infra", ref: str = "dcd-news",
               label: str = "Data Center Dynamics", applied_now: int = 5) -> dict:
    return {"created": True,
            "mute": {"id": mute_id, "kind": kind, "module": module, "ref": ref, "label": label, "note": None,
                     "active": True, "created_at": iso(0), "removed_at": None, "brought_back": False,
                     "rule": f"mute:{kind}:{ref}", "hidden_total": applied_now, "hidden_7d": applied_now},
            "applied_now": applied_now, "preview": mute_preview(kind, module, ref, label), "effective": effective()}


def mute_removed(mute_id: int = 4, brought_back: int = 12) -> dict:
    return {"mute": {"id": mute_id, "active": False, "removed_at": iso(0), "brought_back": brought_back > 0},
            "brought_back": brought_back, "requeued": brought_back, "effective": effective()}


def star_preview(entity_id: str = "nebius", label: str = "Nebius") -> dict:
    return {"entity_id": entity_id, "label": label, "window_days": 7, "matches": 9, "in_briefing": 2,
            "not_in_briefing": 7, "examples": [],
            "text": f"9 stories about {label} in the last 7 days; 2 were in your briefing."}


def star_added(entity_id: str = "nebius", label: str = "Nebius") -> dict:
    return {"created": True, "star": {"id": 3, "entity_id": entity_id, "label": label, "note": None, "active": True,
                                      "created_at": iso(0), "removed_at": None, "matches_7d": 9, "in_briefing_7d": 2},
            "preview": star_preview(entity_id, label), "effective": effective()}


def star_removed(entity_id: str = "coreweave", label: str = "CoreWeave") -> dict:
    return {"star": {"id": 2, "entity_id": entity_id, "label": label, "active": False, "removed_at": iso(0)},
            "removed": True, "effective": effective()}


def settings(stage: str = "live") -> dict:
    return {"volume": {"mode": "standard", "label": "Standard", "bar": 70, "cap": 12, "near_miss_shelf": False,
                       "updated_at": None, "modes": [{"mode": "top", "label": "Only the big ones", "bar": 80, "cap": 8},
                                                     {"mode": "standard", "label": "Standard", "bar": 70, "cap": 12},
                                                     {"mode": "broad", "label": "Everything notable", "bar": 60, "cap": 20}]},
            "stage": {"stage": stage, "since": "2026-10-01T12:00:00Z"}}


def stage_set(stage: str = "staging") -> dict:
    return {"stage": stage, "since": iso(0), "signoff": None, "effective": effective()}


# ---------------------------------------------------------------------------------------------- coverage requests


def _timeline(*steps: tuple[str, float]) -> list[dict]:
    return [{"stage": stage, "at": iso(hours)} for stage, hours in steps]


PROPOSAL_45 = {
    "summary": "Add the PUCT docket filings feed to ai-infra.",
    "sources": [{"key": "puct-large-load", "label": "Texas PUC large-load docket", "connector": "html-list",
                 "module": "ai-infra", "lane": "power_grid", "trust": "official", "cadence_minutes": 360,
                 "config": {"url": "https://interchange.puc.texas.gov/"}}],
    "registry_changes": [{"op": "add_alias", "entity_id": "oncor", "name": "Oncor Electric Delivery"}],
    "notes": "Verified one fetch: 200, 40 filings listed.",
    "diagnosis": {"cause": "no_source"},
}


def radar_requests() -> dict:
    """GET /radar: one request at every stage (asked, proposal, approved, applied, live, rejected twice)."""
    return {"requests": [
        {"id": 46, "kind": "missed_story", "text": "We missed the Shield AI Hivemind award",
         "url": "https://example.com/missed", "module": "defense-unmanned", "status": "queued", "proposal": None,
         "proposed_at": None, "decision_note": None, "decided_at": None, "created_at": iso(2), "updated_at": iso(2),
         "applied_at": None, "live_at": None, "rule_draft_id": None, "stage": "asked",
         "timeline": _timeline(("asked", 2)), "sources": [], "first_items": None},
        {"id": 45, "kind": "track_source", "text": "Follow the Texas PUC large-load docket", "url": None,
         "module": "ai-infra", "status": "proposed", "proposal": PROPOSAL_45, "proposed_at": iso(20),
         "decision_note": None, "decided_at": None, "created_at": iso(26), "updated_at": iso(20), "applied_at": None,
         "live_at": None, "rule_draft_id": None, "stage": "proposal",
         "timeline": _timeline(("asked", 26), ("proposal", 20)),
         "sources": [{"module": "ai-infra", "key": "puct-large-load", "label": "Texas PUC large-load docket",
                      "state": "waiting"}], "first_items": None},
        {"id": 44, "kind": "new_coverage", "text": "Cover sodium-ion storage for data centers", "url": None,
         "module": None, "status": "approved_pending_apply",
         "proposal": {"summary": "Add two trade feeds about sodium-ion storage.",
                      "sources": [{"key": "sodium-news", "label": "Sodium battery news", "module": "ai-infra",
                                   "connector": "rss", "lane": "trade_press", "trust": "press"}]},
         "proposed_at": iso(95), "decision_note": "Start with the trade feeds", "decided_at": iso(90),
         "created_at": iso(100), "updated_at": iso(90), "applied_at": None, "live_at": None, "rule_draft_id": None,
         "stage": "approved", "timeline": _timeline(("asked", 100), ("proposal", 95), ("approved", 90)),
         "sources": [{"module": "ai-infra", "key": "sodium-news", "label": "Sodium battery news", "state": "waiting"}],
         "first_items": None},
        {"id": 43, "kind": "track_source", "text": "Track the Loudoun County agendas", "url": None, "module": "ai-infra",
         "status": "applied", "proposal": {"summary": "Add the Loudoun Legistar agendas to ai-infra."},
         "proposed_at": iso(200), "decision_note": None, "decided_at": iso(190), "created_at": iso(210),
         "updated_at": iso(5), "applied_at": iso(5), "live_at": None, "rule_draft_id": None, "stage": "applied",
         "timeline": _timeline(("asked", 210), ("proposal", 200), ("approved", 190), ("applied", 5)),
         "sources": [{"module": "ai-infra", "key": "loudoun-agendas", "label": "Loudoun County, VA agendas",
                      "state": "in_catalog"}], "first_items": 0},
        {"id": 42, "kind": "new_coverage", "text": "Cover ERCOT large-load reports", "url": None, "module": "ai-infra",
         "status": "live", "proposal": {"summary": "Watch the ERCOT large-load page.",
                                         "diagnosis": {"cause": "source_failing"}},
         "proposed_at": iso(300), "decision_note": None, "decided_at": iso(290), "created_at": iso(310),
         "updated_at": iso(50), "applied_at": iso(100), "live_at": iso(50), "rule_draft_id": 77, "stage": "live",
         "timeline": _timeline(("asked", 310), ("proposal", 300), ("approved", 290), ("applied", 100), ("live", 50)),
         "sources": [{"module": "ai-infra", "key": "ercot-large-load", "label": "ERCOT large-load interconnection reports",
                      "state": "live"}], "first_items": 5},
        {"id": 41, "kind": "track_source", "text": "Follow a blog nobody reads", "url": None, "module": None,
         "status": "rejected", "proposal": None, "proposed_at": None, "decision_note": "withdrawn by owner",
         "decided_at": iso(400), "created_at": iso(410), "updated_at": iso(400), "applied_at": None, "live_at": None,
         "rule_draft_id": None, "stage": "rejected", "timeline": _timeline(("asked", 410), ("rejected", 400)),
         "sources": [], "first_items": None},
        {"id": 40, "kind": "track_source", "text": "Add a paywalled newsletter", "url": None, "module": None,
         "status": "rejected", "proposal": {"summary": "The newsletter is behind a paywall."}, "proposed_at": iso(500),
         "decision_note": "Paywalled: we cannot read it.", "decided_at": iso(490), "created_at": iso(510),
         "updated_at": iso(490), "applied_at": None, "live_at": None, "rule_draft_id": None, "stage": "rejected",
         "timeline": _timeline(("asked", 510), ("proposal", 500), ("rejected", 490)), "sources": [],
         "first_items": None},
    ]}


def radar_created(radar_id: int = 47, kind: str = "track_source") -> dict:
    """POST /radar/requests answer (a radarView)."""
    return {"id": radar_id, "kind": kind, "text": "...", "url": None, "module": None, "status": "queued",
            "proposal": None, "proposed_at": None, "decision_note": None, "decided_at": None, "created_at": iso(0),
            "updated_at": iso(0), "applied_at": None, "live_at": None, "rule_draft_id": None, "stage": "asked",
            "timeline": _timeline(("asked", 0))}
