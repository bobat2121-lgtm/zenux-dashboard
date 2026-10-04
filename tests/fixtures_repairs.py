"""Hub bodies for source repairs (docs/SPEC-REPAIR-PHASE-B.md 1.2 and 1.4): GET /repairs with one repair of every
action and status, the answer of POST /repairs/<id>/<approve|reject|withdraw>, and GET /modules with `repairs_open`.
Fresh copies per call. Hostile values (markup in a title and a label, a javascript: link) check the escaping."""

from __future__ import annotations

import fixtures_coverage as fc
from fixtures import iso

# The repair queue's plain labels (hub/src/monitor.js REPAIR_CLASS_LABELS), which the hub copies into class_label.
CLASS_LABELS = {"throttled": "The site asked us to slow down", "bot_check": "The site shows our servers a bot check",
                "moved": "The page moved or is gone", "layout_changed": "The page's layout changed",
                "format": "The feed's format changed", "quota": "The service's daily allowance is used up",
                "quiet": "Nothing new for longer than usual", "other": "Failing for another reason"}
TITLES = {"ai-infra": fc.AI_TITLE, "defense-unmanned": fc.DEF_TITLE}
STATUSES = ("proposed", "approved", "applied", "recovered", "rejected", "withdrawn")


def current(key: str, label: str, *, connector: str = "rss", url: str | None = "https://example.com/feed",
            lane: str = "companies", trust: str = "primary", kind: str = "News feed", enabled: bool = True,
            off_reason: str | None = None, cadence_minutes: int | None = 360, origin: str = "module",
            entity_id: str | None = None) -> dict:
    """proposal.current: the catalog's entry for the source when the repair was proposed (the "before")."""
    return {"key": key, "label": label, "connector": connector, "url": url, "lane": lane, "trust": trust, "kind": kind,
            "enabled": enabled, "off_reason": off_reason, "cadence_minutes": cadence_minutes, "origin": origin,
            "entity_id": entity_id}


def evidence(status: str = "ok", http_status: int | None = 200, items: list | None = None, *,
             items_total: int | None = None, hours_ago: float = 2.0, notes: list | None = None) -> dict:
    """The probe's answer as the hub keeps it (trimmed: at most 5 items; a test may pass more to check the cut)."""
    items = items if items is not None else []
    return {"status": status, "http_status": http_status, "items_total": len(items) if items_total is None else items_total,
            "items": items, "probed_at": iso(hours_ago), "notes": notes if notes is not None else []}


def item(title: str, url: str, hours_ago: float) -> dict:
    return {"title": title, "url": url, "published_at": iso(hours_ago)}


def repair(rid: int, status: str, action: str, *, module: str, source_key: str, source_label: str, cls: str,
           diagnosis: str, before: dict | None, source: dict | None = None, alternates: tuple = (),
           off_reason: str | None = None, cadence_minutes: int | None = None, proof: dict | None = None,
           note: str | None = None, created: float = 30.0, decided: float | None = None, applied: float | None = None,
           recovered: float | None = None) -> dict:
    """One repair object (1.4). The times are hours ago; updated_at is the newest of them."""
    stamps = [h for h in (created, decided, applied, recovered) if h is not None]
    return {
        "id": rid, "module_id": module, "module_title": TITLES.get(module, module), "source_key": source_key,
        "source_label": source_label, "class": cls, "class_label": CLASS_LABELS[cls], "action": action,
        "diagnosis": diagnosis,
        "proposal": {"current": before, "source": source, "alternates": [key for key, _ in alternates],
                     "off_reason": off_reason, "cadence_minutes": cadence_minutes},
        "alternates": [{"key": key, "label": label} for key, label in alternates],
        "evidence": proof, "status": status, "note": note, "fingerprint": f"failing:error:{rid}",
        "created_at": iso(created), "updated_at": iso(min(stamps)),
        "decided_at": iso(decided) if decided is not None else None,
        "applied_at": iso(applied) if applied is not None else None,
        "recovered_at": iso(recovered) if recovered is not None else None,
    }


HAVOC_BEFORE = current("havocai-medium", "HavocAI blog (Medium)", url="https://medium.com/feed/@havocai", kind="Blog")
HAVOC_AFTER = {"key": "havocai-news", "label": "HavocAI newsroom", "connector": "html-list", "lane": "companies",
               "trust": "primary", "kind": "Newsroom", "cadence_minutes": 360,
               "config": {"url": "https://www.havocai.com/news", "link_pattern": "/news/[a-z0-9-]+"},
               "gates": ["unmanned_relevance"]}
HAVOC_ITEMS = [
    item("HavocAI unveils the <b>Rampage</b> autonomous boat", "https://www.havocai.com/news/rampage", 30),
    item("HavocAI raises $85M to build boats at scale", "https://www.havocai.com/news/raise", 200),
    item("HavocAI joins the Navy's swarm trials", "javascript:alert(1)", 400),
    item("HavocAI opens a Rhode Island factory", "https://www.havocai.com/news/factory", 600),
    item("HavocAI names a chief technology officer", "https://www.havocai.com/news/cto", 800),
    item("A sixth item the hub never keeps", "https://www.havocai.com/news/six", 900),
]
FI_BEFORE = current("fi-defmin", "Finnish defence ministry <news>", connector="html-list",
                    url="https://www.defmin.fi/en/news", trust="official", kind="Ministry news")
FI_OFF_REASON = "The ministry's site shows our servers a bot check; NATO and EDA news carry its announcements."
SAM_BEFORE = current("sam-opps", "SAM.gov opportunities", connector="sam", url="https://sam.gov/", lane="procurement",
                     trust="official", kind="Contract notices", cadence_minutes=120)
ERCOT_BEFORE = current("ercot-large-load", "ERCOT large-load interconnection reports", connector="page-watch",
                       url="https://www.ercot.com/gridinfo/load", lane="power_grid", trust="official", kind="Page watch",
                       cadence_minutes=1440)
ERCOT_AFTER = {"key": "ercot-large-load-2026", "label": "ERCOT large-load reports (2026 page)",
               "connector": "page-watch", "lane": "power_grid", "trust": "official",
               "config": {"url": "https://www.ercot.com/services/rq/large-load"}}
DCD_BEFORE = current("dcd-news", "Data Center Dynamics", url="https://www.datacenterdynamics.com/en/rss/",
                     lane="trade_press", trust="press")
DCD_AFTER = {"key": "dcd-news", "label": "Data Center Dynamics", "connector": "rss", "lane": "trade_press",
             "trust": "press", "config": {"url": "https://www.datacenterdynamics.com/en/news/rss/"}}
APPLY = "node tools/zenux.js repair apply pilot 17"


def repairs_list() -> list[dict]:
    """Newest first: four proposed (replace, turn_off, slow_down, add), then approved, applied, recovered, rejected
    and withdrawn."""
    return [
        repair(21, "proposed", "replace", module="defense-unmanned", source_key="havocai-medium",
               source_label="HavocAI blog (Medium)", cls="bot_check",
               diagnosis="Medium shows Cloudflare's servers a bot check; HavocAI posts the same news on its own "
                         "newsroom, which answers the probe.",
               before=HAVOC_BEFORE, source=HAVOC_AFTER, proof=evidence(items=HAVOC_ITEMS, items_total=7,
                                                                       notes=["preview"]), created=1),
        repair(20, "proposed", "turn_off", module="defense-unmanned", source_key="fi-defmin",
               source_label="Finnish defence ministry <news>", cls="bot_check",
               diagnosis="The ministry's site answers Cloudflare's servers with a bot check, and it publishes no feed "
                         "or other official channel.",
               before=FI_BEFORE, off_reason=FI_OFF_REASON,
               alternates=(("nato-news", "NATO newsroom"), ("eda-news", "European Defence Agency news")),
               proof=evidence("blocked", 403, notes=["challenge page"]), created=2),
        repair(19, "proposed", "slow_down", module="defense-unmanned", source_key="sam-opps",
               source_label="SAM.gov opportunities", cls="quota",
               diagnosis="SAM.gov allows each key 10 calls a day; checking every 6 hours stays inside that allowance.",
               before=SAM_BEFORE, cadence_minutes=360, created=3),
        repair(18, "proposed", "add", module="ai-infra", source_key="ercot-large-load",
               source_label="ERCOT large-load interconnection reports", cls="layout_changed",
               diagnosis="ERCOT moved this year's large-load reports to a new page; the old page keeps the archive.",
               before=ERCOT_BEFORE, source=ERCOT_AFTER,
               proof=evidence(items=[item("Large load interconnection status, September",
                                          "https://www.ercot.com/files/docs/2026/10/01/ll-sep.pdf", 80),
                                     item("Large load interconnection status, August",
                                          "https://www.ercot.com/files/docs/2026/09/01/ll-aug.pdf", 800)]),
               created=4),
        repair(17, "approved", "replace", module="ai-infra", source_key="dcd-news", source_label="Data Center Dynamics",
               cls="moved", diagnosis="The old feed address answers 404; the site's news page links a new feed.",
               before=DCD_BEFORE, source=DCD_AFTER,
               proof=evidence(items=[item("Operator signs 300 MW campus lease", "https://example.com/dcd-1", 5)]),
               note="Checked the new feed by hand.", created=8, decided=3),
        repair(16, "applied", "replace", module="defense-unmanned", source_key="defense-post",
               source_label="The Defense Post", cls="moved",
               diagnosis="The Defense Post retired its old feed; its sitemap lists the new one.",
               before=current("defense-post", "The Defense Post", url="https://www.thedefensepost.com/feed/"),
               source={"key": "defense-post", "connector": "rss", "lane": "trade_press", "trust": "press",
                       "config": {"url": "https://www.thedefensepost.com/news/feed/"}},
               proof=evidence(items=[item("Drone maker wins Army order", "https://example.com/tdp-1", 9)]),
               created=12, decided=7, applied=5),
        repair(15, "recovered", "slow_down", module="defense-unmanned", source_key="eu-ted-uas",
               source_label="EU tenders: drones", cls="quota",
               diagnosis="The EU tenders service allows a few searches an hour; checking every 12 hours is enough.",
               before=current("eu-ted-uas", "EU tenders: drones", connector="ted", lane="procurement",
                              trust="official", cadence_minutes=360),
               cadence_minutes=720, created=48, decided=41, applied=40, recovered=20),
        repair(14, "rejected", "turn_off", module="ai-infra", source_key="loudoun-agendas",
               source_label="Loudoun County, VA agendas", cls="other",
               diagnosis="The county's agenda site failed for three days with server errors and names no other "
                         "channel.",
               before=current("loudoun-agendas", "Loudoun County, VA agendas", connector="legistar",
                              lane="permitting", trust="official"),
               off_reason="The county's agenda site keeps failing; our permitting searches cover its hearings.",
               note="Loudoun is back; keep it on.", created=60, decided=50),
        repair(13, "withdrawn", "add", module="ai-infra", source_key="gn-themes",
               source_label="News search: AI data center themes", cls="quiet",
               diagnosis="The news search has found nothing new for a week; a second search with narrower words "
                         "finds this week's stories.",
               before=current("gn-themes", "News search: AI data center themes", connector="news-search",
                              lane="discovery", trust="search"),
               source={"key": "gn-themes-narrow", "connector": "news-search", "lane": "discovery", "trust": "search",
                       "config": {"query": "AI data center lease"}},
               proof=evidence(items=[item("Hyperscaler leases a campus", "https://example.com/gn-1", 30)]),
               created=70, decided=65),
    ]


def repairs(rows: list[dict] | None = None, counts: dict | None = None) -> dict:
    """GET /repairs: {repairs: newest first, counts: by status (over every repair)}."""
    rows = repairs_list() if rows is None else rows
    if counts is None:
        counts = {status: sum(1 for r in rows if r["status"] == status) for status in STATUSES}
    return {"repairs": rows, "counts": counts}


def by_id(rid: int) -> dict:
    return next(r for r in repairs_list() if r["id"] == rid)


def answer(rid: int, status: str, note: str | None = None) -> dict:
    """The answer of POST /repairs/<id>/<action>: {repair} in its new status."""
    row = by_id(rid)
    row.update(status=status, note=note, decided_at=iso(0), updated_at=iso(0))
    return {"repair": row}


def moved_on(rows: list[dict], rid: int, status: str) -> dict:
    """GET /repairs after a write: the same list with repair `rid` in its new status."""
    out = [dict(r, status=status, decided_at=iso(0), updated_at=iso(0)) if r["id"] == rid else r for r in rows]
    return repairs(out)


def modules(ai_open: int | None = 1, def_open: int | None = 3) -> dict:
    """GET /modules (fixtures_coverage.modules) with each area's `repairs_open` (None: an older hub sends none)."""
    body = fc.modules()
    for module, n in zip(body["modules"], (ai_open, def_open)):
        if n is not None:
            module["repairs_open"] = n
    return body
