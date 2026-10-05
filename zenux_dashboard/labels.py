"""The one vocabulary: every analyst-facing label (docs/SPEC-PHASE03-UI.md 3.4; the plain words of
docs/PLAN-ANALYST-READY.md's vocabulary map and docs/SPEC-PHASE02.md 1.3; the tabs of docs/SPEC-SIMPLIFY.md 2.1).

Pure: no Streamlit calls. Views may add sentence copy of their own, written in these words. Nothing here ever turns
an engine code into visible text: unknown codes fall back to a plain default, never to the code itself.

The jargon guard (JARGON_PATTERNS, find_jargon) is what the tests run over every analyst tab: no event ids, source
keys, module ids, lanes, tiers, reason codes, "lease", "cursor", "dead letters", "refiner", "scout", "hub",
"Grader", "radar", "rule draft", "precedent", "edition", "deploy" or a bare record number ("id 7101", "draft 43")
outside the Control room. The tests also fail on every fixture source key (tests/helpers.assert_plain).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

from .fmt import MIN_TIME, MODULE_NAMES, as_int, one_line, parse_time, zone

# ---------------------------------------------------------------------------------------------- tabs

# docs/SPEC-SIMPLIFY.md 2.1: Briefing (daily), Tuning (weekly) and Coverage (setup); the Control room for the builder.
TABS: tuple[tuple[str, str], ...] = (("briefing", "Briefing"), ("tuning", "Tuning"), ("coverage", "Coverage"),
                                     ("control", "Control room"))
ANALYST_TABS: tuple[str, ...] = ("briefing", "tuning", "coverage")
BUILDER_TAB = "control"
_TAB_NAMES = dict(TABS)


def tab_label(slug: str) -> str:
    return _TAB_NAMES.get(slug, "Briefing")


# ---------------------------------------------------------------------------------------------- reasons

REASON_LABELS: dict[str, str] = {
    "material": "Material news",
    "rubric_priority": "Matches what ranks high for you",
    "new_information": "New information on an ongoing story",
    "material_update": "Update to a story you saw",
    "primary_source": "Official confirmation",
    "analyst_priority": "One of your priorities",
    "duplicate": "Same story as another",
    "syndicated_copy": "Same story as another",
    "roundup_member": "Part of a roundup",
    "already_covered": "Already reported",
    "no_new_facts": "Already reported",
    "below_bar": "Below your \"how much\" setting",
    "below_materiality": "Not significant enough",
    "watch": "Worth watching",  # WF5 SA-3: the hub says "Near miss" for a row within 10 of the bar in force
    "edition_limit": "Cut for space",
    "stale": "Old news",
    "late_repost": "Old news, reposted",
    "out_of_scope": "Outside your coverage",
    "insufficient_evidence": "Not confirmed by a reliable source",
    "source_quality": "Unreliable source",
    "suppressed": "On your ignore list",
    "superseded": "Replaced by a later update",
    "commentary": "Commentary, no new facts",
    "muted": "Muted by you",
}
SAME_STORY_REASONS = ("duplicate", "syndicated_copy", "roundup_member", "already_covered", "no_new_facts", "superseded")
NEAR_MISS_REASONS = ("watch", "edition_limit", "below_bar")
LEFT_OUT = "Left out"


def reason_label(code: Any, hub_label: Any = None) -> str:
    """The hub's label when it gives one (and it is not just the code), else the table's, else "Left out"."""
    code_text = one_line(code)
    hub = one_line(hub_label)
    if hub and hub != code_text:
        return hub
    return REASON_LABELS.get(code_text.lower(), LEFT_OUT)


# ---------------------------------------------------------------------------------------------- ratings and bands

VERDICT_LABELS = {"lead": "Top story", "digest": "In the briefing", "watch": "Near miss", "reject": "Not relevant",
                  "factual_error": "Wrong facts"}
RATING_CHOICES = ("lead", "digest", "watch", "reject")
BAND_LABELS = {"lead": "Top story", "digest": "Also notable", "watch": "Near miss", "reject": "Not relevant"}
TOP_STORY_MIN = 90


def band_of(score: Any) -> str | None:
    """90+ lead, 70-89 digest, 40-69 watch, 0-39 reject; None when the score is unknown."""
    value = as_int(score)
    if value is None:
        return None
    if value >= TOP_STORY_MIN:
        return "lead"
    if value >= 70:
        return "digest"
    if value >= 40:
        return "watch"
    return "reject"


_TIERS = {1: "Your coverage", 2: "Read-through", 3: "Industry and policy",
          "covered": "Your coverage", "read_through": "Read-through", "read-through": "Read-through",
          "industry": "Industry and policy", "catalyst": "Industry and policy"}


def tier_label(tier: Any) -> str:
    """1 / covered "Your coverage"; 2 / read_through "Read-through"; 3 / industry / catalyst "Industry and policy";
    anything else ""."""
    if isinstance(tier, bool):
        return ""
    number = as_int(tier) if isinstance(tier, (int, float)) or one_line(tier).isdigit() else None
    if number is not None:
        return _TIERS.get(number, "")
    return _TIERS.get(one_line(tier).lower(), "")


# ---------------------------------------------------------------------------------------------- preferences

SCOPE_LABELS = {"this_story": "Just this story", "similar": "Stories like this", "standing": "Standing preference"}
SCOPE_HELP = {"this_story": "Only updates of this same story.", "similar": "Stories like this one, from any source.",
              "standing": "A lasting preference for everything ZENUX reads."}
DIRECTION_LABELS = {"more": "Show me more like this", "less": "Show me less like this", "exact": "Exactly as I write it"}
STATUS_LABELS = {"active": "Active", "paused": "Paused", "retired": "Ended"}


def scope_label(code: Any) -> str:
    """A preference's scope; legacy (null) and unknown codes read as a standing preference."""
    return SCOPE_LABELS.get(one_line(code), SCOPE_LABELS["standing"])


def direction_label(code: Any) -> str:
    """A preference's direction; legacy (null) and unknown codes read as "Exactly as I write it"."""
    return DIRECTION_LABELS.get(one_line(code), DIRECTION_LABELS["exact"])


_PREF_LEAD_RE = re.compile(r"^\s*show me (?:more|less) like this\s*:\s*", re.IGNORECASE)
# The hub's example and story sentences, as stored ("Example: event #1234 ...") or as plain_text gives them
# ("Example: "Title" from X.", "Applies only to updates of this story (...)"): the card shows the example on its own line.
_PREF_TAIL_RE = re.compile(r"\s*(?:Example: (?:event #\d+\b|[\"“])|Applies only to updates of (?:this )?story\b).*$",
                           re.DOTALL)
_EVENT_REF_RE = re.compile(r"\b(?:event|story|item)\s+#\d+\b|#\d+\b", re.IGNORECASE)
_DEFAULT_PREF_BODY = "stories like this example"


def _sentence(text: str) -> str:
    text = one_line(text)
    return text[:1].upper() + text[1:] if text else ""


def preference_text(pref: Mapping) -> str:
    """The analyst's words from a preference: its `plain_text` (the hub's words without ids; gap 6), else its `text`,
    without the hub-built lead ("Show me more like this:" / "Show me less like this:", which the card's chip says) and
    the trailing example or story sentence (the card shows the example on its own line); falls back to the full text.
    Never returns an id: any "#<n>" left becomes "another story"."""
    if isinstance(pref, Mapping):
        raw = one_line(pref.get("plain_text")) or one_line(pref.get("text"))
    else:
        raw = one_line(pref)
    if not raw:
        return ""
    body = _PREF_TAIL_RE.sub("", raw)
    body = _PREF_LEAD_RE.sub("", body).strip()
    if not body:
        body = raw
    body = _EVENT_REF_RE.sub("another story", body)
    if body.rstrip(".").strip().lower() == _DEFAULT_PREF_BODY:
        body = "Stories like this example."
    return _sentence(body)


_CALIBRATED_RE = re.compile(
    r"(?:\s*[;,]\s*|\s*\(\s*|\s*\[\s*|\s+-+\s+|\s+[–—]\s+|\s*)"
    r"calibrated(?::\s*owner grades?\s*(?:#\d+(?:\s*(?:,|and|&)\s*)?)+|\s+by your feedback\b)\s*[)\]]?",
    re.IGNORECASE)


_RULE_TAG_RE = re.compile(r"\s*\(rule [A-Za-z0-9_:./-]+\)")  # the stale rule's "(rule stale_backlog)" tail


PREF_ID_RE = re.compile(  # a preference id ("R-0012"), with the words that introduce it ("the analyst's preference")
    r"(?:\b(?:the analyst's|the owner's|your|owner|analyst)\s+)?(?:\b(?:preference|precedent|rule)\s+)?\b([RI]-\d{4,9})\b",
    re.IGNORECASE)
PREF_NAME_MAX = 60


def _pref_name(words: Any) -> str:
    text = one_line(words).rstrip(".")
    if not text:
        return "one of your preferences"
    clipped = text if len(text) <= PREF_NAME_MAX else text[: PREF_NAME_MAX - 1].rstrip() + "…"
    return f"“{clipped}”"


def clean_rationale(text: Any, names: Mapping[str, Any] | None = None) -> str:
    """The last guard on the editor's reasoning (the hub sends `rationale_plain`; this keeps an older text plain):
    drops "calibrated: owner grade #<n>" fragments and the automatic rules'
    "(rule <id>)" tags, turns any remaining "#<digits>" story reference into "another story" and a preference id
    ("R-0012", which the editor and the wording assistant cite) into that preference's words in quotes (`names`:
    {id: the analyst's words}) or "one of your preferences", collapses whitespace."""
    out = _CALIBRATED_RE.sub("", "" if text is None else str(text))
    out = _RULE_TAG_RE.sub("", out)
    out = _EVENT_REF_RE.sub("another story", out)
    def named(m: re.Match) -> str:
        name = _pref_name((names or {}).get(m.group(1).upper()))
        start = m.string[: m.start()].rstrip()
        return name[:1].upper() + name[1:] if not start or start.endswith((".", "!", "?")) else name

    out = PREF_ID_RE.sub(named, out)
    out = one_line(out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    out = re.sub(r"([.;,])\1+", r"\1", out)
    return out.strip(" ;,").lstrip(".").strip()


# ---------------------------------------------------------------------------------------------- routines and volume

ROUTINE_NAMES = {"grader": "ZENUX editor", "refiner": "Wording assistant", "scout": "Source finder"}

VOLUME_LABELS = {"top": "Only the big ones", "standard": "Standard", "broad": "Everything notable"}
_VOLUME_CAPS = {"top": 8, "standard": 12, "broad": 20}


def volume_help(mode: str, cap: int | None) -> str:
    n = as_int(cap) or _VOLUME_CAPS.get(mode, 12)
    if mode == "top":
        return f"Up to {n} stories, only the most significant."
    if mode == "broad":
        return f"Up to {n} stories, including smaller news worth knowing."
    return f"Up to {n} stories that clear the usual bar."


# ---------------------------------------------------------------------------------------------- mutes, stars, locks

MUTE_KIND_LABELS = {"source": "Source", "entity": "Company", "story": "Story", "outlet": "Outlet"}
STILL_COLLECTED = "Still collected, kept out of your briefing."
STAR_PROMISE = "Stories about it are read first and get their own shelf in each briefing. Scores don't change."
RATING_HONEST = "Your rating is used to calibrate the next briefing when it differs from the ZENUX editor's score."
LOCKED_HINT = "Unlock to edit"
LOCKED_HELP = "Unlock to edit: use Sign in to edit at the top right."
NO_UNDO = "This can't be undone from here."

# ---------------------------------------------------------------------------------------------- coverage

SOURCE_STATE_LABELS = {"ok": "Working", "failing": "Not responding", "quiet": "Quiet lately", "off": "Turned off",
                       "new": "Not run yet", "retired": "Removed"}
COVERAGE_ICONS: tuple[tuple[str, str, str], ...] = (
    ("own_feed", "Own feed", "ZENUX reads its own newsroom, investor relations or wire releases."),
    ("sec_filings", "SEC filings", "ZENUX reads its filings with the SEC."),
    ("federal_contracts", "Federal contracts", "ZENUX catches federal contract awards and notices that name it."),
    ("news_search", "News search", "A news search looks for it by name."),
    ("name_only", "Name only", "ZENUX only catches it when another source names it in a story."))
COLUMNS: tuple[tuple[str, str], ...] = (("public", "Public companies"), ("private", "Private and state-owned"),
                                        ("industry", "Industry sources"), ("government", "Government and public record"))


def _capitalised(text: str) -> str:
    return text[:1].upper() + text[1:] if text else ""


def area_name(module_id: Any, title: Any = None) -> str:
    """A coverage area's plain name: the known name capitalised ("Defense unmanned"; the same name the Briefing's
    area tags use, so one area never goes by two names), else the catalog title before ":" ("AI infrastructure"),
    else the id with dashes as spaces, capitalised."""
    mid = one_line(module_id)
    known = MODULE_NAMES.get(mid.lower())
    if known:
        return _capitalised(known)
    head = one_line(title).split(":", 1)[0].strip()
    if head:
        return _capitalised(head)
    return _capitalised(mid.replace("-", " ").replace("_", " ").strip()) or "Coverage area"


# ---------------------------------------------------------------------------------------------- coverage requests

RADAR_KIND_LABELS = {"track_source": "A source", "new_coverage": "A company or topic", "missed_story": "A missed story"}
RADAR_STAGES: tuple[tuple[str, str], ...] = (("asked", "Asked"), ("proposal", "Proposal ready"),
                                             ("approved", "Approved, waiting for setup"), ("applied", "Set up"),
                                             ("live", "Live"))
RADAR_REJECTED = "Not added"
RADAR_SOURCE_STATES = {"waiting": "Waiting for setup", "in_catalog": "Added", "live": "Collecting"}
DIAGNOSIS_LABELS = {"no_source": "No source ZENUX reads covered it.",
                    "source_failing": "A source that covers it wasn't responding.",
                    "gated_out": "It was collected but filtered out before review.",
                    "ranked_low": "It was reviewed and ranked too low.",
                    "no_change": "It was collected and handled as designed.", "unknown": "The cause isn't clear."}

# ---------------------------------------------------------------------------------------------- briefing names, status


def edition_label(published_at: Any, tz: str) -> str:
    """"Sat Oct 4 · morning briefing" from the local publish time: before 11:00 morning, before 16:00 midday, before
    21:00 afternoon, else evening (the hub's own rule; used when an edition carries no `briefing_label`). Unknown
    time: "Briefing"."""
    parsed = parse_time(published_at)
    if parsed == MIN_TIME:
        return "Briefing"
    local: datetime = parsed.astimezone(zone(tz))
    slot = "morning" if local.hour < 11 else "midday" if local.hour < 16 else "afternoon" if local.hour < 21 \
        else "evening"
    return f"{local:%a} {local:%b} {local.day} · {slot} briefing"


STATUS_TEXT = {"green": "Healthy", "amber": "Mostly healthy", "red": "Having trouble",
               "staging": "Collecting · briefings start after sign-off", "unreachable": "Can't reach ZENUX right now",
               "unknown": "Status unavailable"}
# What the analyst can make of amber and red (there are no alerts), said at the end of the status line.
STATUS_HINTS = {"sources": "some sources aren't responding (see Coverage)",
                "editor_stopped": "the editor stopped partway; the next scheduled run picks it up",
                "amber": "a minor issue for the builder; briefings run as usual",
                "red": "briefings may be late or thinner; tell the builder if it lasts"}
SOURCE_REASON_CODES = ("sources_not_responding",)  # GET /status reason codes that point to Coverage
EDITOR_STOPPED_CODE = "editor_stopped"  # GET /status: a Grader run died after it started (its lease ran out)

# ---------------------------------------------------------------------------------------------- the jargon guard

JARGON_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bevent #\d",
    r"#\d{3,}",
    r"\blease\b",
    r"\bcursor\b",
    r"\bdead letters?\b",
    r"\brefiner\b",
    r"\bscout\b",
    r"\bhub\b",
    r"\bgrader\b",
    r"\blanes?\b",
    r"\btier \d",
    r"\bsource keys?\b",
    r"\breason codes?\b",
    r"\bmodules?\b",
    r"\bbackfill\b",
    r"\b[a-z]+_[a-z_]+\b",
    r"\b[RI]-\d{4,9}\b",
    r"\bradar\b",
    r"\brule drafts?\b",
    r"\bprecedents?\b",
    r"\beditions?\b",
    r"\bdeploy(?:s|ed|ing|ment)?\b",
    r"\bid \d+\b",
    r"\b(?:draft|request|item|event|run|edition) #?\d+\b",
    r"\b(?:ai-infra|defense-unmanned)\b",  # the configured coverage-area ids (fmt.MODULE_NAMES)
))


def find_jargon(text: str) -> list[str]:
    """Every jargon match in text (for a test's failure message), in pattern order."""
    found: list[str] = []
    for pattern in JARGON_PATTERNS:
        found.extend(m.group(0) for m in pattern.finditer(text or ""))
    return found
