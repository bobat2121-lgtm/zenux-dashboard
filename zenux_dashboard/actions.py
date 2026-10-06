"""Card actions shared by Briefing (its stories, shelves, left-out rows and search), Tuning and Coverage
(docs/SPEC-PHASE03-UI.md 5.4; docs/SPEC-SIMPLIFY.md 2.2).

A story's actions are icons (docs/SPEC-ICON-ACTIONS.md): thumb up (More like this), thumb down (Less like this), a star
(Rate this story) and, where the caller offers it, an arrow up (Should have been in). They sit on the right of one row
under the headline, with the story's tags on the left (action_bar). The words are each icon's label, for screen
readers (feed.css hides them), and its tooltip. An icon glows Northland green while the story holds what it stands
for, and a click on a glowing icon undoes that, at any time (story_icons says what selects each icon). The lazy "More"
popover (Wrong facts, Mute source, Mute company or Unmute company, Star or Remove from watchlist, Mute this story) is
off for now (SHOW_MORE_MENU). A left-out row has one lazy "Why was it left out?" expander (left_out); a briefing lists
every story's Why in one section under the editor's notes (feed_view). Lazy means the popover and the expanders draw their contents only while
open (`on_change="rerun"` and `.open`), so a page of 60 cards stays light.

Every write button goes through `ui.write_button` (drawn disabled with "Unlock to edit" while the workspace is
locked, so nothing fails after submit because of the lock), and every write through `ui.write` (the owner token,
the read caches cleared, a toast that says when the change takes effect from the answer's `effective` object, and an
undo where the hub has an inverse route). Dialogs are registered here at import time and opened through
`ui.open_dialog`; the shell draws the one open dialog at the end of the run. Dialog widgets use the shared `dlg_*`
keys (only one dialog is open at a time). A dialog gets the workspace id, never the Workspace (whose tokens stay in
st.secrets), and looks the workspace up again when it draws.

What each write does (docs/SPEC-PHASE02.md; the copy below says exactly this and nothing more):

- More / Less like this: POST /preferences. A click on a plain thumb saves at once with the defaults (stories like
  this, no end date, no words; toggle_preference); when the other thumb glows, the same click switches (`replace:
  true` ends that one in the same step). A click on a glowing thumb undoes its preference: POST /rules/<id>/retire
  {reason: "undone"}; it stops applying from the next briefing. Ctrl+click (Cmd+click on a Mac) opens the dialog with
  every option (just this story, the analyst's own words, an end date; set to replace what the story holds):
  Streamlit buttons do not report modifier keys, so the page script (CTRL_CLICK_JS, drawn by ctrl_click_support)
  forwards such a click to the story's hidden twin button (act_morefull_<key> / act_lessfull_<key>, hidden in
  feed.css). Phones and tablets have no Ctrl key: a tap saves or undoes, and a preference's options are in Tuning
  (its row's menu: Edit, End date). The preference is active at once (the wording assistant may later suggest a clearer
  wording, which the analyst approves or not). The Undo bar after a save retires it; after a switch it also brings
  back the preference the switch replaced (POST /rules/<id>/reactivate).
- Wrong facts: POST /feedback {verdict: "factual_error", item_id, note} on a briefing item. The ZENITH editor
  re-checks the item at the next briefing and either corrects it or explains why it stands. No undo route.
- Rate this story: POST /feedback {scope: "item", verdict, score}. The 0-100 slider and the four ratings move
  together (a score picks its rating, a rating moves the score into its band); the hub stores both and the next lease
  shows them to the editor when the rating's band differs from the editor's score. A click on the glowing star
  withdraws the story's ratings: POST /feedback/withdraw {item_id} on a briefing item, else {event_id}; the editor stops
  using them from its next run. Ctrl+click on it opens the dialog through its hidden twin (act_ratefull_<key>), and the
  new rating becomes the newest. No undo route (the star rates again).
- Should have been in: POST /promote {event_id, note}. The story goes back to the editor with the note; it may still
  stay out if the evidence is thin. A click on the glowing arrow withdraws the request: POST /promote/withdraw
  {event_id} (when the editor already looked at the story again, only the note is withdrawn and the story stays where
  it is). No undo route.
- Mute (source, company, story): the 7-day preview (GET /mutes/preview) is the confirmation step, then POST /mutes
  {action: "add"}. Muted stories are still collected and kept out of the briefing. Undo: remove the mute and bring
  back the last 7 days. A briefing story offers every company it is about (why.companies: subjects, vendors and
  buyers); a left-out story its subject companies.
- Unmute: GET /mutes/bring-back-preview says how many stories would come back, then POST /mutes {action: "remove",
  bring_back_days: 7 or 0}. Undo: mute it again.
- Star / Remove from watchlist: GET /stars/preview, then POST /stars {action: "add" | "remove"}. Undo reverses.
- Bring back (a removed mute): POST /mutes {action: "bring_back", days: 7}. No undo route.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Mapping

import streamlit as st

from . import api, data, labels, links, ui
from .config import Workspace, load_config
from .fmt import (MIN_TIME, as_int, as_list, dicts, domain_of, esc, fmt_clock, fmt_date, md_label, one_line, parse_time,
                  pick, plural, safe_url)

TEXT_MAX = 500
SHOW_MORE_MENU = False  # the card's More popover; off for now (owner, 2026-10-04)
WRONG_FACTS_MIN = 10
PROMOTE_MIN = 3
UNTIL_DEFAULT_DAYS = 30
UNTIL_MAX_DAYS = 366
PREVIEW_EXAMPLES = 5
TITLE_CLIP = 80
SCOPES = ("this_story", "similar", "standing")
DEFAULT_SCOPE = "similar"
DIRECTIONS = ("more", "less")
PLACEHOLDERS = {"more": "e.g. production orders for small drones", "less": "e.g. stock-move articles with no new facts"}
PREFERENCE_ID_RE = re.compile(r"^[RI]-\d{4,9}$")
# A source key used as a label ("dcd-news", "ent-coreweave-1"): lowercase words joined by - or _, no space or dot.
KEY_LIKE_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$")

NO_STORY_YET = "Just this story is available once the story has been in a briefing."
ACTIVE_AT_ONCE = ("No approval needed: it applies from the next briefing. The wording assistant may suggest a clearer "
                  "wording later; you decide.")
UNMUTE_ANY_TIME = "You can unmute any time and bring back the last 7 days."
WRONG_FACTS_LABEL = "What's wrong? Name the claim or number and, if you know it, the right one."
WRONG_FACTS_SHORT = "Write a sentence so the editor knows what to check."
PROMOTE_LABEL = "Why should it have been in? The editor reads this."
PROMOTE_SHORT = "Write a few words (3 characters or more) so the editor knows why it belongs."
CALIBRATED_TEXT = "The editor matched this to your earlier ratings."
BRING_BACK_CHOICES = {7: "Bring back what it hid in the last 7 days", 0: "Only from now on"}
NOT_ABOUT_TOAST = "Noted: that story isn't about {name}. It leaves {name}'s watchlist shelf, and the builder fixes the name match."
COMPANY_MUTE_RULE = "A company mute hides a story only when every company it is about is muted."
ALSO_ABOUT = ("Stories that are also about a company you haven't muted still show (this one is also about {names}). "
              "To hide this story, use Mute this story.")
NOT_ITS_SUBJECT = ("This story names {label} but isn't about it, so muting {label} doesn't hide it. To hide this story, "
                   "use Mute this story.")
REPLACE_KEY = "dlg_replace"  # set after the hub answered preference_exists: the Save button becomes "Replace it"
RATE_CHOICE_KEY = "dlg_choice"
RATE_SCORE_KEY = "dlg_score"
RATE_SCORE_SET_KEY = "dlg_score_set"  # True once the analyst moved the slider: only then is the exact score sent
# Where the slider lands when a rating is picked (inside the rating's band).
RATING_SCORES = {"lead": 95, "digest": 80, "watch": 55, "reject": 20}
# The firm core's bands, as the ZENITH editor reads a score (rubric/core/firm-core.md section 1).
SCORE_SCALE = (
    ("90–100", "Top story", "A major, confirmed event. Leads the briefing."),
    ("70–89", "In the briefing", "Material news worth reporting."),
    ("40–69", "Near miss", "Relevant, but not enough to report. Listed under the briefing as left out."),
    ("0–39", "Not relevant", "Off-topic, minor or old news."),
)
RATE_SCALE_NOTE = ("Your rating and score go to the editor beside its own score. When your band differs from the "
                   "editor's, it scores similar stories in your band from the next briefing.")
EXISTS_FALLBACK = "You already have a preference made from this story. Replace it?"
CHANGE_REPLACES = "Saving replaces what you asked for on this story."
# The story icons (docs/SPEC-ICON-ACTIONS.md): the words are each icon's label (hidden in feed.css, read by screen
# readers) and, with what a click does, its tooltip. A selected icon is a primary button (it glows), a plain one tertiary.
ICON_LABELS = {"more": "More like this", "less": "Less like this", "rate": "Rate this story",
               "promote": "Should have been in"}
ICONS = {"more": ":material/thumb_up:", "less": ":material/thumb_down:", "rate": ":material/star:",
         "promote": ":material/arrow_upward:"}
# The hidden twins a Ctrl/Cmd+click lands on (CTRL_CLICK_JS); never seen, but their words stay plain.
TWIN_LABELS = {"more": "More like this, with options", "less": "Less like this, with options",
               "rate": "Rate this story, with options"}
CTRL_OPTIONS = "Ctrl+click (Cmd+click on a Mac) for options."
# (icon, selected) -> (what it is, what a click does); the tooltip is both. Locked, the second gives way to
# labels.LOCKED_HELP. {rating}: the newest rating in plain words.
ICON_TIPS: dict[tuple[str, bool], tuple[str, str]] = {
    ("more", False): ("More like this.", "Click to save it for stories like this, with no end date. " + CTRL_OPTIONS),
    ("more", True): ("More like this is on.", "Click to undo it. Ctrl+click to change it."),
    ("less", False): ("Less like this.", "Click to save it for stories like this, with no end date. " + CTRL_OPTIONS),
    ("less", True): ("Less like this is on.", "Click to undo it. Ctrl+click to change it."),
    ("rate", False): ("Rate this story.", ""),
    ("rate", True): ("You rated it: {rating}.", "Click to withdraw your rating. Ctrl+click to change it."),
    ("promote", False): ("Should have been in.", ""),
    ("promote", True): ("You asked for it to be in your briefing.", "Click to withdraw the request."),
}
OTHER = {"more": "less", "less": "more"}
WHAT = {"more": "more like this", "less": "less like this"}
UNDO_CHAIN_MAX = 10  # the most versions of one preference a thumb's undo ends (each undone version restores the last)
ON_STATUSES = ("active", "paused", "")  # a preference that is on (the hub lists only those; "" from an older hub)
PROMOTE_NOTE = "Should have been in"  # the hub's note on the digest grade it stores with a request: not a rating
RATING_WITHDRAWN = "Rating withdrawn. The editor stops using it from the next briefing."
REQUEST_WITHDRAWN = "Request withdrawn."
REQUEST_WITHDRAWN_LATE = ("Request withdrawn. The editor had already looked at this story again, so it stays where "
                          "it is.")
# Ctrl+click (Cmd+click on a Mac) on a thumb or the star: Streamlit buttons do not report modifier keys, so this page
# script catches such a click before the button sees it and clicks the story's hidden twin button instead
# (act_morefull_<key>, act_lessfull_<key>, act_ratefull_<key>), whose callback opens the dialog. (V2: the star joined;
# a tab still running the first script keeps both, and each click is forwarded once.)
CTRL_CLICK_JS = r"""
(function () {
  if (window.zxCtrlClickV2) return;
  window.zxCtrlClickV2 = true;
  document.addEventListener('click', function (ev) {
    if (!(ev.ctrlKey || ev.metaKey) || !ev.target || !ev.target.closest) return;
    var holder = ev.target.closest('[class*="st-key-act_more_"], [class*="st-key-act_less_"], [class*="st-key-act_rate_"]');
    if (!holder) return;
    var m = /(?:^|\s)st-key-act_(more|less|rate)_(\S+)/.exec(holder.className);
    if (!m) return;
    var twin = document.querySelector('.st-key-act_' + m[1] + 'full_' + CSS.escape(m[2]) + ' button');
    if (!twin || twin.disabled) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    twin.click();
  }, true);
})();
"""

DIALOG_PREF = "pref"
DIALOG_WRONG_FACTS = "wrong_facts"
DIALOG_RATE = "rate"
DIALOG_PROMOTE = "promote"
DIALOG_MUTE = "mute"
DIALOG_UNMUTE = "unmute"
DIALOG_STAR = "star"


@dataclass(frozen=True)
class Target:
    """What a card action is about: a published briefing story or a story that was left out."""
    workspace_id: str
    title: str
    event_id: int | None
    item_id: int | None = None
    edition_id: int | None = None
    story_id: str | None = None
    module: str | None = None
    source_key: str | None = None
    source_label: str | None = None
    subjects: tuple[dict, ...] = ()      # [{entity_id, name, muted, starred}]: why.companies (else why.subjects) /
    #                                      row.subjects
    url: str | None = None
    published: bool = False              # True for a briefing item (Wrong facts is offered only then)
    in_briefing: bool = False            # True for a briefing item (promote is never offered then)
    reason: str | None = None            # the plain reason line (Should have been in shows it)
    item_rank: int | None = None         # a briefing item without an id is rated by edition_id + item_rank
    outlet: str | None = None            # WF5 AW-1: the outlet behind a news-search story ("Yahoo Finance")
    outlet_domain: str | None = None     # its domain, what an outlet mute keys on ("finance.yahoo.com")
    my_prefs: tuple[dict, ...] = ()      # WF5 AW-2: the analyst's preferences made from this story [{id, direction}]
    score: int | None = None             # the ZENITH editor's score (the Rate dialog shows it beside the slider)
    rating: str | None = None            # the analyst's newest rating of it (lead, digest, watch, reject): the star glows
    requested: bool = False              # its "Should have been in" request is open: the arrow glows


# ---------------------------------------------------------------------------------------------- targets


def subjects_of(raw: Any) -> tuple[dict, ...]:
    """Subject companies as {entity_id, name, muted, starred}: unique by id, in the hub's order."""
    out: list[dict] = []
    seen: set[str] = set()
    for subject in dicts(raw):
        entity_id = one_line(pick(subject, "entity_id", "id"))
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        out.append({"entity_id": entity_id, "name": one_line(subject.get("name")) or entity_id,
                    "muted": subject.get("muted") is True, "starred": subject.get("starred") is True})
    return tuple(out)


def item_sources(item: Mapping) -> list[tuple[str, str]]:
    """[(url, label)] for an item's http(s) sources only, at most 4 (label: name, publisher, title or domain)."""
    out: list[tuple[str, str]] = []
    raw = as_list(item.get("sources"))
    if not raw and item.get("url"):
        raw = [item.get("url")]
    for source in raw:
        if isinstance(source, Mapping):
            url = safe_url(pick(source, "url", "href"))
            label = one_line(pick(source, "name", "publisher", "title", "domain")) or domain_of(url)
        else:
            url = safe_url(source)
            label = domain_of(url)
        if url:
            out.append((url, label or "source"))
    return out[:4]


def plain_source_label(label: Any, key: Any, url: Any = None) -> str:
    """A source's plain name: the hub's label unless it is only the source key (no catalog yet), then the domain."""
    text, code = one_line(label), one_line(key)
    if text and text != code:
        return text
    return domain_of(url) if safe_url(url) else ""


def item_source_label(item: Mapping) -> str:
    """A briefing item's plain source name: why.source.label (the hub's plain name, never the key), guarded against a
    label that equals the key, then the first source's publisher or domain, then the story link's domain; '' when
    nothing plain is known."""
    source = pick(item, "why.source")
    source = source if isinstance(source, Mapping) else {}
    label = one_line(source.get("label"))
    key = one_line(source.get("source_key")) or one_line(pick(item, "event.source_key"))
    if label and label != key:
        return label
    sources = item_sources(item)
    if sources:
        return sources[0][1]
    return plain_source_label(None, None, pick(item, "event.url"))


def outlet_of(publisher: Any, domain: Any, label: Any) -> tuple[str, str]:
    """(name, domain) of the outlet behind a story (the record's publisher), or ('', '') when there is none or the source
    is that outlet itself (its name already says it): a news-search source collects from many outlets (WF5 AW-1)."""
    name, dom = one_line(publisher), one_line(domain).lower()
    if dom.startswith("www."):
        dom = dom[4:]
    if not name or not dom:
        return "", ""
    text = one_line(label).casefold()
    if name.casefold() in text or dom in text:
        return "", ""
    return name, dom


def with_outlet(label: Any, outlet: Any) -> str:
    """'Yahoo Finance via News search: data center deals', or the one that is known."""
    label, outlet = one_line(label), one_line(outlet)
    return f"{outlet} via {label}" if outlet and label else outlet or label


def item_source_line(item: Mapping) -> str:
    """The dateline's source: the plain source name, with the outlet in front for a news-search story."""
    label = item_source_label(item)
    outlet, _ = outlet_of(pick(item, "why.source.publisher"), pick(item, "why.source.publisher_domain"), label)
    return with_outlet(label, outlet)


def my_prefs_of(raw: Any) -> tuple[dict, ...]:
    """The analyst's preferences made from a story (why.my_preferences / row.my_preferences): [{id, direction}]."""
    out = []
    for p in dicts(raw):
        pid = one_line(p.get("id"))
        if PREFERENCE_ID_RE.match(pid):
            out.append({"id": pid, "direction": one_line(p.get("direction")), "status": one_line(p.get("status"))})
    return tuple(out)


def asked_text(pref: Mapping) -> str:
    """'You asked for less like this' for a preference made from this story (the options dialog says it)."""
    direction = one_line(pref.get("direction"))
    words = WHAT.get(direction, "a rule about this")
    return f"You asked for {words}" + (" (paused)" if one_line(pref.get("status")) == "paused" else "")


def newest_rating(feedback: Any) -> str | None:
    """The verdict of the analyst's newest rating of a story (lead, digest, watch or reject) from its `feedback` list, or
    None. The digest grade the hub stores with "Should have been in" (its note starts so) is not a rating, and a
    withdrawn one (withdrawn_at; the hub leaves those out) no longer counts."""
    rows = [f for f in dicts(feedback) if one_line(f.get("verdict")) in labels.RATING_CHOICES
            and one_line(f.get("scope")) in ("", "item") and not one_line(f.get("withdrawn_at"))
            and not one_line(f.get("note")).startswith(PROMOTE_NOTE)]
    if not rows:
        return None
    newest = max(enumerate(rows), key=lambda nf: (parse_time(nf[1].get("created_at")), as_int(nf[1].get("id")) or 0,
                                                  nf[0]))[1]
    return one_line(newest.get("verdict"))


def requested_of(raw: Any) -> dict | None:
    """An open "Should have been in" request (a left-out row's `requested`: reason promote, not cancelled), else
    None."""
    if isinstance(raw, Mapping) and one_line(raw.get("reason")) == "promote" and not one_line(raw.get("cancelled_at")):
        return dict(raw)
    return None


def live_prefs(target: Target) -> list[dict]:
    """The story's preferences that are on (active or paused)."""
    return [p for p in target.my_prefs if one_line(p.get("status")) in ON_STATUSES]


def prefs_on(target: Target, direction: str) -> list[str]:
    """Ids of the story's preferences in `direction` that are on: thumb up glows for "more", thumb down for "less"."""
    return [p["id"] for p in live_prefs(target) if one_line(p.get("direction")) == direction]


def item_title(item: Mapping) -> str:
    """The headline the card shows: a corrected item's new headline, else its own."""
    correction = item.get("correction") if isinstance(item.get("correction"), Mapping) else {}
    if one_line(correction.get("state")) == "corrected" and one_line(correction.get("headline")):
        return one_line(correction.get("headline"))
    return one_line(pick(item, "headline", "title", "event.title"))


def target_from_item(ws: Workspace, edition: dict, item: dict) -> Target:
    """A published briefing story."""
    why = item.get("why") if isinstance(item.get("why"), Mapping) else {}
    source = why.get("source") if isinstance(why.get("source"), Mapping) else {}
    event = item.get("event") if isinstance(item.get("event"), Mapping) else {}
    url = safe_url(event.get("url")) or next((u for u, _ in item_sources(item)), "")
    reason = labels.reason_label(why.get("reason_code"), why.get("reason")) if why else ""
    source_label = item_source_label(item)
    outlet, outlet_domain = outlet_of(source.get("publisher"), source.get("publisher_domain"), source_label)
    return Target(
        workspace_id=ws.id,
        title=item_title(item) or "This story",
        event_id=as_int(item.get("event_id")),
        item_id=as_int(item.get("id")),
        edition_id=as_int(pick(edition, "id", "edition_id")),
        story_id=one_line(item.get("story_id")) or None,
        module=one_line(source.get("module")) or one_line(event.get("module")) or one_line(
            pick(item, "module", "module_id")) or None,
        source_key=one_line(source.get("source_key")) or one_line(event.get("source_key")) or None,
        source_label=source_label or None,
        subjects=subjects_of(why.get("companies") or why.get("subjects")),
        url=url or None,
        published=True,
        in_briefing=True,
        reason=reason or None,
        item_rank=as_int(item.get("rank")),
        outlet=outlet or None,
        outlet_domain=outlet_domain or None,
        my_prefs=my_prefs_of(why.get("my_preferences")),
        score=as_int(item.get("score")) if as_int(item.get("score")) is not None else as_int(why.get("score")),
        rating=newest_rating(item.get("feedback")),
    )


def target_from_row(ws: Workspace, row: dict) -> Target:
    """A GET /rejected row or a briefing shelf row (watchlist, near misses): a story that is not in a briefing."""
    url = safe_url(row.get("url"))
    source_label = plain_source_label(row.get("source_label"), row.get("source_key"), url)
    outlet, outlet_domain = outlet_of(row.get("publisher"), row.get("publisher_domain"), source_label)
    return Target(
        workspace_id=ws.id,
        title=one_line(row.get("title")) or "This story",
        event_id=as_int(row.get("event_id")),
        item_id=None,
        edition_id=as_int(row.get("edition_id")),
        story_id=one_line(row.get("story_id")) or None,
        module=one_line(pick(row, "module", "module_id")) or None,
        source_key=one_line(row.get("source_key")) or None,
        source_label=source_label or None,
        subjects=subjects_of(row.get("subjects")),
        url=url or None,
        published=False,
        in_briefing=False,
        reason=labels.reason_label(row.get("reason_code"), row.get("reason")),
        outlet=outlet or None,
        outlet_domain=outlet_domain or None,
        my_prefs=my_prefs_of(row.get("my_preferences")),
        score=as_int(row.get("score")),
        rating=newest_rating(row.get("feedback")),
        requested=requested_of(row.get("requested")) is not None,
    )


# ---------------------------------------------------------------------------------------------- the action bar


def action_bar(ws: Workspace, target: Target, *, key: str, promote: bool = False, tags: str = "",
               extra: Callable[[], None] | None = None) -> None:
    """The story's row under its headline (docs/SPEC-ICON-ACTIONS.md): its tags on the left (`tags`, an HTML block the
    caller built and escaped), then `extra` (the caller's own widgets for this row: Show it), and the story icons on
    the right (story_icons), in one horizontal container that wraps on a narrow screen while the icons stay together.
    The lazy More menu (Wrong facts, mutes, star) is drawn only while SHOW_MORE_MENU is on; it is off for now (the
    owner's call, 2026-10-04): mutes and stars stay in Coverage and Tuning."""
    with st.container(horizontal=True, key=f"zx_actions_{key}", gap="small", vertical_alignment="center"):
        if tags:
            st.markdown(tags, unsafe_allow_html=True)
        if extra is not None:
            extra()
        story_icons(ws, target, key=key, promote=promote)
        if SHOW_MORE_MENU:
            menu = st.popover("More", key=f"zx_more_{key}", on_change="rerun", icon=":material/more_horiz:",
                              type="tertiary")
            with menu:
                if menu.open:
                    more_menu(ws, target, key)


def story_icons(ws: Workspace, target: Target, *, key: str, promote: bool = False) -> None:
    """Thumb up, thumb down, the star and (when `promote` and the story is not in a briefing) the arrow up, together on
    the right of the story's row. Each one glows while the story holds what it stands for, and a click on it then
    undoes that, at any time. Every click runs in its button's callback, so the page draws once, in its new state, and
    a refusal is said in a toast; the hidden twins take a Ctrl/Cmd+click (CTRL_CLICK_JS).

    - Thumb up / down glows while the story holds an active or paused "more" / "less" preference (my_preferences). A
      click saves one at once, switches from the other thumb in one click, or, glowing, undoes it (toggle_preference).
    - The star glows while the story holds a rating (Target.rating). A click opens the rating dialog, or, glowing,
      withdraws the rating (toggle_rating); Ctrl+click opens the dialog either way.
    - The arrow glows while the story's "Should have been in" request is open (Target.requested). A click opens its
      dialog (it needs a note), or, glowing, withdraws the request (toggle_request)."""
    with st.container(horizontal=True, key=f"zx_icons_{key}", gap="xxsmall", vertical_alignment="center",
                      width="content"):
        for direction in DIRECTIONS:
            icon_button(ws, direction, key=f"act_{direction}_{key}", on=bool(prefs_on(target, direction)),
                        on_click=toggle_preference, args=(ws, target, direction))
            ui.write_button(TWIN_LABELS[direction], ws=ws, key=f"act_{direction}full_{key}", on_click=open_options,
                            args=(ws, target, direction))
        if target.event_id is not None or target.item_id is not None:
            icon_button(ws, "rate", key=f"act_rate_{key}", on=bool(target.rating), on_click=toggle_rating,
                        args=(ws, target), rating=target.rating)
            ui.write_button(TWIN_LABELS["rate"], ws=ws, key=f"act_ratefull_{key}", on_click=open_rate,
                            args=(ws, target))
        if promote and not target.in_briefing and target.event_id is not None:
            icon_button(ws, "promote", key=f"act_promote_{key}", on=target.requested, on_click=toggle_request,
                        args=(ws, target))


def icon_tip(name: str, on: bool, rating: str | None = None) -> tuple[str, str]:
    """(what the icon is, what a click does) in plain words; its tooltip is both."""
    lead, act = ICON_TIPS[(name, on)]
    return lead.format(rating=labels.VERDICT_LABELS.get(one_line(rating), "a rating")), act


def icon_button(ws: Workspace, name: str, *, key: str, on: bool, on_click: Callable[..., Any], args: tuple,
                rating: str | None = None) -> None:
    """One story icon: its words as the label (feed.css hides them; screen readers read them) and the tooltip, the
    icon, and `on` (selected) as a primary button, which feed.css fills green and makes glow; plain, tertiary. Locked,
    it is drawn disabled and its tooltip keeps the words."""
    lead, act = icon_tip(name, on, rating)
    ui.write_button(ICON_LABELS[name], ws=ws, key=key, type="primary" if on else "tertiary", icon=ICONS[name],
                    help=f"{lead} {act}".strip(), locked_help=f"{lead} {labels.LOCKED_HELP}", on_click=on_click,
                    args=args)


def more_menu(ws: Workspace, target: Target, key: str) -> None:
    """The More popover's contents (drawn only while it is open). Each item closes the popover and opens its dialog
    (or, for Remove from watchlist, writes) in its button's callback (ui.menu_item)."""
    pop = f"zx_more_{key}"
    if target.published and target.item_id is not None:
        ui.menu_item("Wrong facts", ws=ws, key=f"act_wrong_{key}", popover_key=pop, action=open_wrong_facts,
                     args=(ws, target))
    if target.outlet and target.outlet_domain:
        # WF5 AW-1: one outlet behind a news-search source, without muting the whole search.
        ui.menu_item(f"Mute outlet: {target.outlet}", ws=ws, key=f"act_mute_outlet_{key}", popover_key=pop,
                     action=open_mute, args=(ws,), kwargs={"kind": "outlet", "ref": target.outlet_domain,
                                                           "label": target.outlet, "event_id": target.event_id})
    if target.module and target.source_key:
        label = target.source_label or "this source"
        text = f"Mute every outlet in {label}" if target.outlet else f"Mute source: {label}"
        ui.menu_item(text, ws=ws, key=f"act_mute_source_{key}", popover_key=pop, action=open_mute,
                     args=(ws,), kwargs={"kind": "source", "ref": target.source_key, "label": label,
                                         "module": target.module, "event_id": target.event_id})
    for n, subject in enumerate(target.subjects):
        company_buttons(ws, subject, key, n, event_id=target.event_id)
    if target.story_id:
        ui.menu_item("Mute this story", ws=ws, key=f"act_mute_story_{key}", popover_key=pop, action=open_mute,
                     args=(ws,), kwargs={"kind": "story", "ref": target.story_id,
                                         "label": story_label(target.title)})
    st.caption(labels.STILL_COLLECTED)


def company_buttons(ws: Workspace, subject: Mapping, key: str, n: int, *, event_id: int | None = None) -> None:
    """Mute company (or Unmute company when muted; disabled while starred) and Star (or Remove from watchlist when
    starred; disabled while muted) for one subject company, and, when it is starred, "Not about <company>" (a
    look-alike name; WF5 AW-10). `n` is its index: entity ids may hold any character."""
    pop = f"zx_more_{key}"
    entity_id = one_line(subject.get("entity_id"))
    name = one_line(subject.get("name")) or entity_id
    muted, starred = subject.get("muted") is True, subject.get("starred") is True
    mute_key = f"act_mute_co_{key}_{n}"
    if muted:
        mute = active_mute(ws, "entity", entity_id)
        if mute is None:
            st.button(md_label(f"Unmute company: {name}"), key=mute_key, type="tertiary", disabled=True,
                      help="Find it in Tuning, under Your rules.")
        else:
            ui.menu_item(f"Unmute company: {name}", ws=ws, key=mute_key, popover_key=pop, action=open_unmute,
                         args=(ws, mute))
    elif starred:
        st.button(md_label(f"Mute company: {name}"), key=mute_key, type="tertiary", disabled=True,
                  help=md_label(f"{name} is on your watchlist. Remove the star first."))
    else:
        ui.menu_item(f"Mute company: {name}", ws=ws, key=mute_key, popover_key=pop, action=open_mute,
                     args=(ws,), kwargs={"kind": "entity", "ref": entity_id, "label": name, "event_id": event_id})
    if starred:
        if event_id is not None:
            ui.menu_item(f"Not about {name}", ws=ws, key=f"act_not_about_{key}_{n}", popover_key=pop,
                         action=report_not_about, args=(ws, entity_id, name, event_id), kwargs={"rerun": False})
        ui.menu_item(f"Remove {name} from watchlist", ws=ws, key=f"act_unstar_{key}_{n}", popover_key=pop,
                     action=unstar, args=(ws, entity_id, name), kwargs={"rerun": False})
    elif muted:
        st.button(md_label(f"Star {name}"), key=f"act_star_{key}_{n}", type="tertiary", disabled=True,
                  help=md_label(f"{name} is muted. Unmute it first."))
    else:
        ui.menu_item(f"Star {name}", ws=ws, key=f"act_star_{key}_{n}", popover_key=pop, action=open_star,
                     args=(ws, entity_id, name))


def story_label(title: Any) -> str:
    """How a story mute names its story: the headline in quotes."""
    text = one_line(title)
    if not text:
        return "this story"
    clipped = text if len(text) <= TITLE_CLIP else text[: TITLE_CLIP - 1].rstrip() + "…"
    return f"“{clipped}”"


def active_mute(ws: Workspace, kind: str, ref: str) -> dict | None:
    """The active mute of (kind, ref) from GET /mutes, or None (also when the list cannot be read)."""
    try:
        body = data.mutes(ws.id)
    except api.ApiError:
        return None
    for mute in dicts(pick(body, "mutes", default=[])):
        if (one_line(mute.get("kind")) == kind and one_line(mute.get("ref")) == ref
                and mute.get("active") is not False and as_int(mute.get("id")) is not None):
            return dict(mute)
    return None


# ---------------------------------------------------------------------------------------------- why


def why_expander(ws: Workspace, target: Target, why: Mapping | None, *, key: str, expanded: bool = False,
                 extra: list[tuple[str, str]] | None = None) -> None:
    """"Why am I seeing this?" (briefing items) or "Why was it left out?" (left-out rows), lazy: its rows are built
    only while it is open. `why` is the hub's why object, or a left-out row as left_out.why_of maps it."""
    label = "Why am I seeing this?" if target.published else "Why was it left out?"
    box = st.expander(label, expanded=expanded, key=f"zx_why_{key}", on_change="rerun")
    with box:
        if box.open:
            why_body(ws, target, why if isinstance(why, Mapping) else {}, key, extra or [])


def why_rows(target: Target, why: Mapping, tz: str | None = None) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """The rows before and after "Your preferences that applied", each (label, text), only those with content. tz:
    the workspace's time zone, for when a "Should have been in" was asked. A left-out story's first row also gives
    the bar in force for its briefing (`bar`): "Near miss · score 64 of 100 · bar 70"."""
    first: list[tuple[str, str]] = []
    reason = labels.reason_label(why.get("reason_code"), why.get("reason")) if (
        one_line(why.get("reason_code")) or one_line(why.get("reason"))) else ""
    score = as_int(why.get("score"))
    bar = as_int(why.get("bar")) if not target.published else None
    if reason or score is not None:
        line = reason + (f" · score {score} of 100" if score is not None else "")
        line += f" · bar {bar}" if bar is not None and score is not None else ""
        first.append(("Why it's here" if target.published else "Why it was left out", line.lstrip(" ·")))
    # the hub's plain reasoning (rationale_plain); clean_rationale stays the last guard (and drops the calibration note
    # the "Calibrated" row says)
    rationale = labels.clean_rationale(why.get("rationale_plain") or why.get("rationale"))
    if rationale:
        first.append(("The editor's reasoning", rationale))
    if as_list(why.get("calibrated_by")):
        first.append(("Calibrated", CALIBRATED_TEXT))
    after: list[tuple[str, str]] = []
    stars = [one_line(pick(s, "name", "label")) for s in dicts(why.get("stars"))]
    stars = [s for s in stars if s]
    if stars:
        after.append(("On your watchlist", ", ".join(stars)))
    promoted = why.get("promoted") if isinstance(why.get("promoted"), Mapping) else None
    if promoted is not None:
        note = one_line(promoted.get("note"))
        asked = promoted.get("requested_at")
        when = f" (asked {fmt_date(asked, tz)})" if tz and parse_time(asked) != MIN_TIME else ""
        after.append(("You asked for this",
                      (f"Should have been in: “{note}”" if note else "You said it should have been in.") + when))
    source = why.get("source") if isinstance(why.get("source"), Mapping) else {}
    lane = one_line(source.get("lane_label"))
    source_line = " · ".join(p for p in (with_outlet(target.source_label, target.outlet), lane) if p)
    if source_line:
        after.append(("Source", source_line))
    companies = []
    for subject in target.subjects or subjects_of(why.get("subjects")):
        state = " (muted)" if subject.get("muted") else " (on your watchlist)" if subject.get("starred") else ""
        companies.append(f"{subject.get('name')}{state}")
    if companies:
        after.append(("Companies", ", ".join(companies)))
    return first, after


def rows_html(rows: list[tuple[str, str]]) -> str:
    body = "".join(f'<div class="why-row"><span class="why-label">{esc(label)}</span><span>{esc(text)}</span></div>'
                   for label, text in rows if one_line(text))
    return f'<div class="why-block">{body}</div>' if body else ""


def applied_preferences(ws: Workspace, why: Mapping) -> list[tuple[str, str, str]]:
    """[(preference id, its words, its plain status)] for why.rules: hub entries {id, text, plain_text, status} (a
    briefing item's rules, a left-out row's rules_detail). A bare id, or an entry without text or status (a
    preference that no longer exists), is looked up in GET /preferences."""
    out: list[tuple[str, str, str]] = []
    lookup: dict[str, Mapping] | None = None
    for raw in as_list(why.get("rules")):
        entry = raw if isinstance(raw, Mapping) else {"id": raw}
        pid = one_line(entry.get("id"))
        text = one_line(entry.get("plain_text")) or one_line(entry.get("text"))
        status = one_line(entry.get("status"))
        known: Mapping = {}
        if pid and (not text or not status):
            if lookup is None:
                lookup = preference_lookup(ws)
            known = lookup.get(pid) or {}
        if text:
            words = labels.preference_text(entry)
        else:
            words = labels.preference_text(known) if known else ""
        status = status or one_line(known.get("status"))
        out.append((pid, words or "One of your preferences", labels.STATUS_LABELS.get(status, "")))
    return out


def preference_lookup(ws: Workspace) -> dict[str, Mapping]:
    try:
        body = data.preferences(ws.id)
    except api.ApiError:
        return {}
    return {one_line(p.get("id")): p for p in dicts(pick(body, "preferences", default=[])) if one_line(p.get("id"))}


def why_body(ws: Workspace, target: Target, why: Mapping, key: str, extra: list[tuple[str, str]]) -> None:
    first, after = why_rows(target, why, ws.timezone)
    html = rows_html(first)
    if html:
        st.markdown(html, unsafe_allow_html=True)
    prefs = applied_preferences(ws, why)
    if prefs:
        st.markdown('<div class="why-block"><div class="why-row"><span class="why-label">Your preferences that applied'
                    '</span></div></div>', unsafe_allow_html=True)
        for n, (pid, words, status) in enumerate(prefs):
            with st.container(horizontal=True, gap="small", vertical_alignment="center"):
                st.markdown(f'<div class="why-row"><span>{esc(words)}</span>'
                            + (f'<span class="why-label">{esc(status)}</span>' if status else "") + '</div>',
                            unsafe_allow_html=True)
                if PREFERENCE_ID_RE.match(pid) and st.button("See it in Tuning", key=f"why_pref_{key}_{n}",
                                                             type="tertiary"):
                    links.go("tuning", pref=pid)
    html = rows_html(after + [(one_line(label), one_line(text)) for label, text in extra])
    if html:
        st.markdown(html, unsafe_allow_html=True)
    if not (first or prefs or after or extra):
        st.caption("No details were recorded for this story.")


# ---------------------------------------------------------------------------------------------- openers


def open_preference(ws: Workspace, target: Target, direction: str, replace_note: str | None = None) -> None:
    """The dialog for More like this ("more") or Less like this ("less") with every option. replace_note: the story
    already holds a preference and saving replaces it (the dialog shows the note and its button says "Replace it")."""
    direction = direction if direction in DIRECTIONS else "more"
    ui.open_dialog(DIALOG_PREF, workspace_id=ws.id, target=target, direction=direction)
    if replace_note:
        st.session_state[REPLACE_KEY] = replace_note  # after open_dialog, which clears the dialog's widgets


def open_options(ws: Workspace, target: Target, direction: str) -> None:
    """A Ctrl/Cmd+click on a thumb (its hidden twin's callback): the dialog with every option, set to replace what the
    story holds when it holds a preference (one preference per story; this is how the one made from it changes)."""
    open_preference(ws, target, direction, replace_note=CHANGE_REPLACES if live_prefs(target) else None)


def toggle_preference(ws: Workspace, target: Target, direction: str) -> None:
    """A thumb's click (its button's callback). Glowing: undo the story's preference in this direction. Plain: save one
    at once ("stories like this", no end date, no words), replacing the other thumb's in the same step when that one
    glows (a switch). The hub refusing because the story holds another preference (one the page did not show yet, or
    one in the analyst's own words) opens the options instead, set to replace it."""
    direction = direction if direction in DIRECTIONS else "more"
    on = prefs_on(target, direction)
    if on:
        undo_preferences(ws, direction, on)
        return
    switch = bool(prefs_on(target, OTHER[direction]))
    _, handled = save_preference(ws, target, direction, scope=DEFAULT_SCOPE, words="", expires=None, replacing=switch,
                                 switch=switch, in_callback=True)
    if handled is not None:
        open_preference(ws, target, direction, replace_note=one_line(handled.detail) or EXISTS_FALLBACK)


def save_preference(ws: Workspace, target: Target, direction: str, *, scope: str, words: str, expires: str | None,
                    replacing: bool, switch: bool = False,
                    in_callback: bool = False) -> tuple[Any | None, api.ApiError | None]:
    """POST /preferences for this story, with its toast and Undo; a "preference_exists" refusal comes back to the
    caller instead of being drawn. switch: a thumb's one-click switch from the other direction (`replacing` too): its
    toast says "Switched to ...", and its Undo also brings back the preference it replaced. in_callback: run from a
    button's callback (ui.write's). -> (result or None, the refusal or None)."""
    item_id = target.item_id
    event_id = None if item_id is not None else target.event_id

    def call(token: str) -> Any:
        result = api.add_preference(ws, token, direction=direction, scope=scope or DEFAULT_SCOPE, text=words,
                                    item_id=item_id, event_id=event_id, expires_at=expires, replace=replacing)
        # an Undo bar that would end a preference this one just replaced has nothing left to do
        ui.forget_undo(ws, {f"pref:{one_line(old)}" for old in as_list(pick(result, "replaced"))})
        return result

    def undo(result: Any) -> tuple | None:
        pid = one_line(pick(result, "preference.id"))
        if not pid:
            return None

        def retire(token: str) -> Any:
            return api.rule_action(ws, token, pid, "retire", {"reason": "undone"})

        if not switch:
            return "Saved a preference.", retire, "Preference removed.", f"pref:{pid}"
        replaced = [r for r in (one_line(x) for x in as_list(pick(result, "replaced"))) if PREFERENCE_ID_RE.match(r)]

        def switch_back(token: str) -> None:
            retire(token)
            for old in replaced:
                api.rule_action(ws, token, old, "reactivate")

        back = f"Switched back to {WHAT[OTHER[direction]]}." if replaced else "Preference removed."
        return f"Switched to {WHAT[direction]}.", switch_back, back, f"pref:{pid}"

    toast = (lambda r: switch_toast(direction, r, ws.timezone)) if switch else (
        lambda r: preference_toast(direction, r, ws.timezone))
    from .brief_view import write_or_handle  # brief_view imports nothing of this module; late to keep imports light
    return write_or_handle(ws, call, toast=toast, undo=undo, codes=("preference_exists",), in_callback=in_callback)


def undo_preferences(ws: Workspace, direction: str, pref_ids: list[str]) -> None:
    """A glowing thumb's click (in its callback): end the story's preference(s) in this direction as undone (POST
    /rules/<id>/retire {reason: "undone"}); they stop applying from the next briefing. Undoing a version that replaced
    another (an edited one, an approved wording) brings that one back (the answer's `restored`), so it is ended too,
    and the thumb goes plain. One more click saves a new one; Tuning (Ended) can bring the old one back. An Undo bar
    that would have done just this is dropped quietly."""
    refs = {f"pref:{pid}" for pid in pref_ids}

    def call(token: str) -> Any:
        result = None
        done: set[str] = set()
        todo = list(pref_ids)
        while todo and len(done) < UNDO_CHAIN_MAX:
            pid = todo.pop(0)
            done.add(pid)
            result = api.rule_action(ws, token, pid, "retire", {"reason": "undone"})
            restored = one_line(pick(result, "restored"))
            if PREFERENCE_ID_RE.match(restored) and restored not in done:
                todo.append(restored)
        ui.forget_undo(ws, refs)
        return result

    ui.write(ws, call, toast=lambda r: undone_toast(direction, r, ws.timezone), in_callback=True)


def toggle_rating(ws: Workspace, target: Target) -> None:
    """The star's click (its button's callback): the rating dialog (a rating needs a choice), or, while the star glows,
    withdraw the story's ratings, by its briefing item when it has one, else by the story (POST /feedback/withdraw). The
    editor stops using them from its next run. No undo route: the star rates again."""
    if not target.rating:
        open_rate(ws, target)
        return
    item_id = target.item_id
    event_id = None if item_id is not None else target.event_id
    ui.write(ws, lambda token: api.withdraw_ratings(ws, token, item_id=item_id, event_id=event_id),
             toast=RATING_WITHDRAWN, in_callback=True)


def toggle_request(ws: Workspace, target: Target) -> None:
    """The arrow's click (its button's callback): the Should have been in dialog (it needs a note), or, while the arrow
    glows, withdraw the request (POST /promote/withdraw). It is cancelled when the editor has not looked at the story
    again yet; else only the note is withdrawn and the story stays where the editor put it. No undo route."""
    if not target.requested or target.event_id is None:
        open_promote(ws, target)
        return
    event_id = target.event_id
    ui.write(ws, lambda token: api.withdraw_promote(ws, token, event_id), toast=request_toast, in_callback=True)


def ctrl_click_support() -> None:
    """The page script behind Ctrl/Cmd+click on the thumbs and the star (CTRL_CLICK_JS). Drawn once per run by each
    view that shows story icons, in a container feed.css hides (zx_ctrl_click), so it takes no room."""
    with st.container(key="zx_ctrl_click"):
        st.html(f"<script>{CTRL_CLICK_JS}</script>", unsafe_allow_javascript=True)


def open_wrong_facts(ws: Workspace, target: Target) -> None:
    ui.open_dialog(DIALOG_WRONG_FACTS, workspace_id=ws.id, target=target)


def open_rate(ws: Workspace, target: Target) -> None:
    ui.open_dialog(DIALOG_RATE, workspace_id=ws.id, target=target)


def open_promote(ws: Workspace, target: Target) -> None:
    ui.open_dialog(DIALOG_PROMOTE, workspace_id=ws.id, target=target)


def open_mute(ws: Workspace, *, kind: str, ref: str, label: str, module: str | None = None,
              event_id: int | None = None) -> None:
    """kind: source (module required), outlet (a publisher's domain), entity (a subject company) or story (a story
    id). event_id: the story the mute is made from (its preview leads with it and, for a company, says whether this
    story would be hidden)."""
    ui.open_dialog(DIALOG_MUTE, workspace_id=ws.id, kind=kind, ref=ref, label=label, module=module, event_id=event_id)


def open_unmute(ws: Workspace, mute: Mapping) -> None:
    """A GET /mutes row (active)."""
    ui.open_dialog(DIALOG_UNMUTE, workspace_id=ws.id, mute=dict(mute))


def open_star(ws: Workspace, entity_id: str, name: str) -> None:
    ui.open_dialog(DIALOG_STAR, workspace_id=ws.id, entity_id=entity_id, company=name)


# ---------------------------------------------------------------------------------------------- direct writes


def unstar(ws: Workspace, entity_id: str, name: str, *, rerun: bool = True) -> None:
    """Remove a company from the watchlist at once (no dialog: it is reversible), with undo, then rerun (rerun=False
    from a button callback, after which the app reruns anyway; a failure is then said in a toast, which shows wherever
    the analyst is scrolled)."""
    result = ui.write(ws, lambda token: api.remove_star(ws, token, entity_id),
                      toast=f"{name} removed from your watchlist.",
                      undo=lambda r: (f"Removed {name} from your watchlist.",
                                      lambda token: api.add_star(ws, token, entity_id)),
                      in_callback=not rerun)
    if result is not None and rerun:
        st.rerun()


def report_not_about(ws: Workspace, entity_id: str, name: str, event_id: int, *, rerun: bool = True) -> None:
    """"Not about <company>" (WF5 AW-10): the story leaves the company's watchlist shelf and counts, the builder gets the
    report to fix the look-alike name; undo puts it back. rerun=False from a button callback."""
    result = ui.write(ws, lambda token: api.not_about(ws, token, entity_id, event_id),
                      toast=NOT_ABOUT_TOAST.format(name=name),
                      undo=lambda r: (f"Said a story isn't about {name}.",
                                      lambda token: api.not_about(ws, token, entity_id, event_id, undo=True),
                                      "Put back."),
                      in_callback=not rerun)
    if result is not None and rerun:
        st.rerun()


def bring_back(ws: Workspace, mute: Mapping) -> None:
    """Bring back what a removed mute hid in the last 7 days (409 mute_active shows the hub's sentence), then rerun.
    No undo route."""
    mute_id = as_int(pick(mute, "id", "mute_id"))
    label = mute_label(mute)
    if mute_id is None:
        st.warning("This mute can't be found any more. Refresh the page and try again.")
        return
    result = ui.write(ws, lambda token: api.bring_back(ws, token, mute_id, days=7),
                      toast=lambda r: bring_back_toast(label, r))
    if result is not None:
        st.rerun()


# ---------------------------------------------------------------------------------------------- dialog parts


def dialog_ws(workspace_id: Any) -> Workspace | None:
    """The dialog's workspace, looked up again from the secrets (a dialog's arguments never hold a token)."""
    ws = load_config().workspace(one_line(workspace_id))
    if ws is None:
        st.error("This workspace is no longer configured. Close this and reload the page.")
        cancel_button()
    return ws


def story_line(target: Target) -> None:
    """The story a dialog is about: its headline and, when known, its source."""
    source = one_line(target.source_label)
    st.markdown(f'<div class="feed-item-headline">{esc(one_line(target.title) or "This story")}</div>'
                + (f'<div class="feed-dateline">{esc(source)}</div>' if source else ""), unsafe_allow_html=True)


def plain_line(text: str) -> None:
    st.markdown(f'<div class="why-row"><span>{esc(text)}</span></div>', unsafe_allow_html=True)


def buttons(ws: Workspace, label: str) -> bool:
    """[label] (primary, drawn disabled with "Unlock to edit" while locked) and [Cancel], which closes the dialog."""
    with st.container(horizontal=True, gap="small"):
        save = ui.write_button(label, ws=ws, key="dlg_save", type="primary")
        cancel = st.button("Cancel", key="dlg_cancel")
    if cancel:
        close()
    return save


def cancel_button() -> None:
    if st.button("Cancel", key="dlg_cancel"):
        close()


def close() -> None:
    ui.close_dialog()
    st.rerun()


def effective_of(result: Any) -> Mapping | None:
    value = pick(result, "effective")
    return value if isinstance(value, Mapping) else None


def clean_text(value: Any) -> str:
    return one_line(value)[:TEXT_MAX]


def preview_error(exc: Exception) -> None:
    headline, explanation = ui.plain_error(exc)
    st.caption(md_label(" ".join(p for p in ("Couldn't load the 7-day preview.", headline, explanation or "") if p)))


# ---------------------------------------------------------------------------------------------- toasts


def preference_toast(direction: str, result: Any, tz: str) -> str:
    replaced = " It replaces your earlier one on this story." if as_list(pick(result, "replaced")) else ""
    return f"Saved: {labels.DIRECTION_LABELS.get(direction, '')}.{replaced} {ui.effective_text(effective_of(result), tz)}"


def switch_toast(direction: str, result: Any, tz: str) -> str:
    """"Switched to less like this. Applies from the 12:30 PM briefing." """
    return f"Switched to {WHAT.get(direction, 'this')}. {ui.effective_text(effective_of(result), tz)}"


def stops_text(effective: Mapping | None, tz: str) -> str:
    """When an undone preference stops applying, in ui.effective_text's words: "Stops applying from the 12:30 PM
    briefing." """
    text = ui.effective_text(effective, tz)
    lead = "Applies from"
    return "Stops applying from" + text[len(lead):] if text.startswith(lead) else text


def undone_toast(direction: str, result: Any, tz: str) -> str:
    """"Undone: more like this. Stops applying from tomorrow's 7:30 AM briefing." """
    return f"Undone: {WHAT.get(direction, 'this')}. {stops_text(effective_of(result), tz)}"


def request_toast(result: Any) -> str:
    """A withdrawn "Should have been in": cancelled, or, when the editor already looked at the story again, only the
    note withdrawn."""
    return REQUEST_WITHDRAWN_LATE if pick(result, "already_reconsidered") is True else REQUEST_WITHDRAWN


def wrong_facts_toast(result: Any, tz: str) -> str:
    when = pick(effective_of(result), "next_briefing_at")
    at = f"the {fmt_clock(when, tz)} briefing" if parse_time(when) != MIN_TIME else "the next briefing"
    return f"Flagged. The ZENITH editor re-checks it at {at} and either corrects it or explains why it stands."


def rating_toast(score: int | None = None) -> str:
    saved = f"Rating saved with your score of {score}. " if score is not None else "Rating saved. "
    return saved + labels.RATING_HONEST


def promote_toast(result: Any, tz: str) -> str:
    return (f"Sent back to the ZENITH editor with your note. {ui.effective_text(effective_of(result), tz)} "
            "It may still stay out if the evidence is thin.")


def mute_toast(label: str, result: Any) -> str:
    text = f"Muted {label}. {labels.STILL_COLLECTED}"
    applied = as_int(pick(result, "applied_now")) or 0
    if applied > 0:
        verb = "was" if applied == 1 else "were"
        text += f" {plural(applied, 'waiting story', 'waiting stories')} {verb} set aside now."
    return text


def unmute_toast(label: str, result: Any) -> str:
    text = f"Unmuted {label}."
    back = as_int(pick(result, "brought_back")) or 0
    if back > 0:
        verb = "comes" if back == 1 else "come"
        text += f" {plural(back, 'story', 'stories')} {verb} back for the editor to look at."
    return text


def star_toast(name: str) -> str:
    return f"{name} is on your watchlist. {labels.STAR_PROMISE}"


def bring_back_toast(label: str, result: Any) -> str:
    back = as_int(pick(result, "brought_back")) or 0
    return f"Brought back what {label} hid in the last 7 days: {plural(back, 'story', 'stories')}."


def mute_label(mute: Mapping) -> str:
    """A mute's plain name: the hub's label, else "this source" / "this company" / "this story"."""
    label = one_line(mute.get("label")) if isinstance(mute, Mapping) else ""
    if label:
        return label
    kind = labels.MUTE_KIND_LABELS.get(one_line(mute.get("kind")) if isinstance(mute, Mapping) else "", "")
    return f"this {kind.lower()}" if kind else "this mute"


# ---------------------------------------------------------------------------------------------- dialogs


def preference_dialog(workspace_id: str, target: Target, direction: str) -> None:
    """More like this / Less like this: scope, a few optional words, an optional end date; active at once."""
    ws = dialog_ws(workspace_id)
    if ws is None:
        return
    story_line(target)
    # WF5 AW-2: one preference per story. Say what is already there; after the hub's "Replace it?" the button replaces.
    replace = st.session_state.get(REPLACE_KEY)
    if isinstance(replace, str) and replace:
        st.warning(md_label(replace))
    elif live_prefs(target):
        st.caption(md_label(f"{asked_text(live_prefs(target)[0])} on this story. Saving asks whether to replace it."))
    scopes = [s for s in SCOPES if s != "this_story" or target.story_id]
    scope = st.radio("Apply to", scopes, index=scopes.index(DEFAULT_SCOPE), key="dlg_scope",
                     format_func=lambda s: labels.SCOPE_LABELS.get(s, s),
                     captions=[labels.SCOPE_HELP.get(s, "") for s in scopes])
    if not target.story_id:
        st.caption(NO_STORY_YET)
    text = st.text_input("In a few words, what about it? (optional)", key="dlg_text", max_chars=TEXT_MAX,
                         placeholder=PLACEHOLDERS.get(direction, ""))
    until: date | None = None
    if st.checkbox("Only for a while", key="dlg_until_on"):
        today = ui.local_today(ws.timezone)
        until = st.date_input("Until", value=today + timedelta(days=UNTIL_DEFAULT_DAYS),
                              min_value=today + timedelta(days=1), max_value=today + timedelta(days=UNTIL_MAX_DAYS),
                              key="dlg_until")
    replacing = isinstance(replace, str) and bool(replace)
    save = buttons(ws, "Replace it" if replacing else "Save")
    st.caption(ACTIVE_AT_ONCE)
    if not save:
        return
    words = clean_text(text)
    expires = ui.local_midnight_iso(until, ws.timezone) if isinstance(until, date) else None
    result, handled = save_preference(ws, target, direction, scope=scope or DEFAULT_SCOPE, words=words,
                                      expires=expires, replacing=replacing)
    if handled is not None:
        st.session_state[REPLACE_KEY] = one_line(handled.detail) or EXISTS_FALLBACK
        st.rerun()
    if result is not None:
        close()


def wrong_facts_dialog(workspace_id: str, target: Target) -> None:
    """Wrong facts on a briefing item: a required sentence; the editor re-checks it at the next briefing."""
    ws = dialog_ws(workspace_id)
    if ws is None:
        return
    story_line(target)
    note = st.text_area(WRONG_FACTS_LABEL, key="dlg_text", max_chars=TEXT_MAX, height=110)
    st.caption(labels.NO_UNDO)
    if not buttons(ws, "Flag it"):
        return
    words = clean_text(note)
    if len(words) < WRONG_FACTS_MIN:
        st.warning(WRONG_FACTS_SHORT)
        return
    if target.item_id is None:  # never offered without an item id; a stale dialog after a reload
        st.warning("This story can't be flagged from here. Reload the page and try again.")
        return
    result = ui.write(ws, lambda token: api.add_feedback(ws, token, verdict="factual_error", item_id=target.item_id,
                                                         note=words),
                      toast=lambda r: wrong_facts_toast(r, ws.timezone))
    if result is not None:
        close()


def _rating_picked() -> None:
    """A rating was picked: the slider moves into its band (unless it is already there)."""
    verdict = st.session_state.get(RATE_CHOICE_KEY)
    if verdict in RATING_SCORES and labels.band_of(st.session_state.get(RATE_SCORE_KEY)) != verdict:
        st.session_state[RATE_SCORE_KEY] = RATING_SCORES[verdict]


def _score_moved() -> None:
    """The slider moved: its band picks the rating, and the exact score is sent with it."""
    st.session_state[RATE_SCORE_SET_KEY] = True
    band = labels.band_of(st.session_state.get(RATE_SCORE_KEY))
    if band in RATING_SCORES:
        st.session_state[RATE_CHOICE_KEY] = band


def score_scale_html() -> str:
    """What each part of the 0-100 scale means to the ZENITH editor (the firm core's bands)."""
    rows = "".join(f'<div class="why-row"><span class="why-label">{esc(span)} · {esc(name)}</span>'
                   f'<span>{esc(meaning)}</span></div>' for span, name, meaning in SCORE_SCALE)
    return f'<div class="why-block score-scale">{rows}</div>'


def rate_dialog(workspace_id: str, target: Target) -> None:
    """A plain rating and, if the analyst moves it, an exact 0-100 score; used to calibrate the next briefing when its
    band differs from the editor's score."""
    ws = dialog_ws(workspace_id)
    if ws is None:
        return
    story_line(target)
    choices = list(labels.RATING_CHOICES)
    default = "digest" if target.published else "watch"
    # dialog widgets start fresh on every open (ui.open_dialog clears the dlg_* keys); the defaults go in first
    st.session_state.setdefault(RATE_CHOICE_KEY, default)
    st.session_state.setdefault(RATE_SCORE_KEY, RATING_SCORES[st.session_state[RATE_CHOICE_KEY]]
                                if st.session_state[RATE_CHOICE_KEY] in RATING_SCORES else RATING_SCORES[default])
    verdict = st.radio("How would you rate it?", choices, key=RATE_CHOICE_KEY, on_change=_rating_picked,
                       format_func=lambda v: labels.VERDICT_LABELS.get(v, v))
    note = st.text_input("A note for the editor (optional)", key="dlg_text", max_chars=TEXT_MAX)
    score = st.slider("Your score, 0 to 100 (optional)", min_value=0, max_value=100, step=1, key=RATE_SCORE_KEY,
                      on_change=_score_moved)
    if target.score is not None:
        st.caption(f"The ZENITH editor scored it {target.score}.")
    st.markdown(score_scale_html(), unsafe_allow_html=True)
    st.caption(RATE_SCALE_NOTE)
    if not buttons(ws, "Save"):
        return
    exact = as_int(score) if st.session_state.get(RATE_SCORE_SET_KEY) is True else None
    # the story: its briefing item, else the briefing and rank (an item without an id), else the story itself
    item_id = target.item_id
    by_rank = item_id is None and target.published and target.edition_id is not None and target.item_rank is not None
    result = ui.write(ws, lambda token: api.add_feedback(
        ws, token, verdict=verdict or default, item_id=item_id,
        edition_id=target.edition_id if by_rank else None, item_rank=target.item_rank if by_rank else None,
        event_id=None if item_id is not None or by_rank else target.event_id,
        note=clean_text(note), scope="item", score=exact), toast=rating_toast(exact))
    if result is not None:
        close()


def promote_dialog(workspace_id: str, target: Target) -> None:
    """Should have been in: a required note; the story goes back to the editor, who may still leave it out."""
    ws = dialog_ws(workspace_id)
    if ws is None:
        return
    story_line(target)
    if target.reason:
        st.caption(md_label(f"Left out: {target.reason}"))
    note = st.text_area(PROMOTE_LABEL, key="dlg_text", max_chars=TEXT_MAX, height=100)
    if not buttons(ws, "Send it back"):
        return
    words = clean_text(note)
    if len(words) < PROMOTE_MIN or target.event_id is None:
        st.warning(PROMOTE_SHORT)
        return
    result = ui.write(ws, lambda token: api.promote(ws, token, target.event_id, words),
                      toast=lambda r: promote_toast(r, ws.timezone))
    if result is not None:
        close()


def example_source(label: Any, *keys: Any) -> str:
    """A preview example's source name, or '' when the hub could only give the source key (no catalog yet): the
    examples carry no key or link to compare with, so a label that is a known key or looks like one is left out."""
    text = one_line(label)
    if not text or text in {one_line(k) for k in keys if one_line(k)} or KEY_LIKE_RE.match(text):
        return ""
    return text


def preview_examples_html(examples: list[dict], tz: str, ref: str | None = None, more: Any = None) -> str:
    """Up to 5 preview examples: "title · date · source", "this story" for the one the menu was opened from and "in
    your briefing" when it was; then "+4 more" when the preview counted more than it shows (WF5 AW-14)."""
    rows = []
    shown = examples[:PREVIEW_EXAMPLES]
    for ex in shown:
        when = ex.get("published_at")
        date_text = fmt_date(when, tz) if parse_time(when) != MIN_TIME else ""
        parts = [one_line(ex.get("title")) or "A story", date_text, example_source(ex.get("source_label"), ref)]
        chip = ('<span class="zx-chip chip-state chip-starred">this story</span>' if ex.get("this_story") is True else "")
        chip += ('<span class="zx-chip chip-state chip-flagged">in your briefing</span>'
                 if ex.get("in_briefing") is True else "")
        rows.append(f'<div class="why-row"><span>{esc(" · ".join(p for p in parts if p))}</span>{chip}</div>')
    extra = (as_int(more) or 0) + max(0, len(examples) - len(shown))
    if rows and extra > 0:
        rows.append(f'<div class="why-row"><span class="why-label">+{extra} more</span></div>')
    return f'<div class="why-block">{"".join(rows)}</div>' if rows else ""


def this_story_line(kind: str, label: str, preview: Mapping) -> str:
    """For a company mute made from a story (WF5 AW-7): why that story keeps showing, or '' when the mute hides it."""
    this = preview.get("this_story") if isinstance(preview.get("this_story"), Mapping) else None
    if kind != "entity" or this is None or this.get("hidden") is True:
        return ""
    if this.get("is_subject") is False:
        return NOT_ITS_SUBJECT.format(label=label)
    names = [one_line(n) for n in as_list(this.get("also_about")) if one_line(n)]
    if not names:
        return ""
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return ALSO_ABOUT.format(names=joined)


def mute_dialog(workspace_id: str, kind: str, ref: str, label: str, module: str | None = None,
                event_id: int | None = None) -> None:
    """"Mute {label}?": the 7-day preview is the confirmation step, then POST /mutes. Muted stories are still
    collected. A failing preview read is said plainly and the Mute button is still offered. A company mute says its
    rule and, made from a story that would keep showing, why (WF5 AW-7)."""
    ws = dialog_ws(workspace_id)
    if ws is None:
        return
    preview: Mapping | None = None
    try:
        body = data.mute_preview(ws.id, kind, ref, module, as_int(event_id))
        preview = body if isinstance(body, Mapping) else None
    except api.ApiError as exc:
        preview_error(exc)
    if preview is not None:
        text = one_line(preview.get("text"))
        if text:
            plain_line(text)
        examples = preview_examples_html(dicts(preview.get("examples")), ws.timezone, ref, preview.get("more"))
        if examples:
            st.markdown(examples, unsafe_allow_html=True)
        if preview.get("already_muted") is True:
            st.info("Already muted.")
            cancel_button()
            return
    if kind == "entity":
        plain_line(COMPANY_MUTE_RULE)
        stays = this_story_line(kind, label, preview or {})
        if stays:
            st.warning(md_label(stays))
    plain_line(labels.STILL_COLLECTED)
    st.caption(UNMUTE_ANY_TIME)
    note = st.text_input("A note for yourself (optional)", key="dlg_text", max_chars=TEXT_MAX)
    if not buttons(ws, "Mute"):
        return

    def undo(result: Any) -> tuple | None:
        mute_id = as_int(pick(result, "mute.id"))
        if pick(result, "created") is not True or mute_id is None:
            return None
        return (f"Muted {label}.", lambda token: api.remove_mute(ws, token, mute_id, bring_back_days=7),
                "Unmuted. The stories it hid this week come back.")

    result = ui.write(ws, lambda token: api.add_mute(ws, token, kind=kind, ref=ref, module=module,
                                                     note=clean_text(note) or None),
                      toast=lambda r: mute_toast(label, r), undo=undo)
    if result is not None:
        close()


def unmute_dialog(workspace_id: str, mute: dict) -> None:
    """"Unmute {label}?", by default bringing back what the mute hid in the last 7 days (GET
    /mutes/bring-back-preview says how many stories that is first); undo mutes it again."""
    ws = dialog_ws(workspace_id)
    if ws is None:
        return
    label = mute_label(mute)
    mute_id = as_int(pick(mute, "id", "mute_id"))
    coming: int | None = None
    if mute_id is not None:
        try:
            preview = data.bring_back_preview(ws.id, mute_id, 7)
        except api.ApiError as exc:
            headline, explanation = ui.plain_error(exc)
            st.caption(md_label(" ".join(p for p in ("Couldn't count what it hid.", headline, explanation or "") if p)))
        else:
            coming = as_int(pick(preview, "would_bring_back"))
            text = one_line(pick(preview, "text"))
            if text:
                plain_line(text)
            examples = preview_examples_html(dicts(pick(preview, "examples", default=[])), ws.timezone)
            if examples and coming:
                st.markdown(examples, unsafe_allow_html=True)

    def choice_label(days: Any) -> str:
        text = BRING_BACK_CHOICES.get(days, str(days))
        return f"{text} ({plural(coming, 'story', 'stories')})" if days == 7 and coming is not None else text

    choice = st.radio("What it hid", list(BRING_BACK_CHOICES), index=0, key="dlg_choice", format_func=choice_label)
    if not buttons(ws, "Unmute"):
        return
    if mute_id is None:
        st.warning("This mute can't be found any more. Refresh the page and try again.")
        return
    days = int(choice) if choice in BRING_BACK_CHOICES else 7
    kind, ref = one_line(mute.get("kind")), one_line(mute.get("ref"))
    module = one_line(pick(mute, "module", "module_id")) or None

    def undo(result: Any) -> tuple | None:
        if not (kind and ref):
            return None
        return (f"Unmuted {label}.", lambda token: api.add_mute(ws, token, kind=kind, ref=ref, module=module),
                "Muted again.")

    result = ui.write(ws, lambda token: api.remove_mute(ws, token, mute_id, bring_back_days=days),
                      toast=lambda r: unmute_toast(label, r), undo=undo)
    if result is not None:
        close()


def star_dialog(workspace_id: str, entity_id: str, company: str) -> None:
    """"Add {company} to your watchlist?": its stories are read first and get their own shelf; scores don't
    change. (The argument is `company`: open_dialog's own first parameter is `name`.)"""
    ws = dialog_ws(workspace_id)
    if ws is None:
        return
    try:
        text = one_line(pick(data.star_preview(ws.id, entity_id), "text"))
        if text:
            plain_line(text)
    except api.ApiError as exc:
        preview_error(exc)
    st.caption(labels.STAR_PROMISE)
    note = st.text_input("A note for yourself (optional)", key="dlg_text", max_chars=TEXT_MAX)
    if not buttons(ws, "Star"):
        return

    def undo(result: Any) -> tuple | None:
        if pick(result, "created") is not True:
            return None
        return (f"Added {company} to your watchlist.", lambda token: api.remove_star(ws, token, entity_id),
                "Removed from your watchlist.")

    result = ui.write(ws, lambda token: api.add_star(ws, token, entity_id, note=clean_text(note) or None),
                      toast=star_toast(company), undo=undo)
    if result is not None:
        close()


def preference_title(direction: str = "more", **_: Any) -> str:
    return "Less like this" if direction == "less" else "More like this"


def unmute_title(mute: Mapping | None = None, **_: Any) -> str:
    return f"Unmute {mute_label(mute or {})}?"


ui.register_dialog(DIALOG_PREF, preference_title, preference_dialog)
ui.register_dialog(DIALOG_WRONG_FACTS, "Wrong facts", wrong_facts_dialog)
ui.register_dialog(DIALOG_RATE, "Rate this story", rate_dialog)
ui.register_dialog(DIALOG_PROMOTE, "Should have been in", promote_dialog)
ui.register_dialog(DIALOG_MUTE, "Mute {label}?", mute_dialog)
ui.register_dialog(DIALOG_UNMUTE, unmute_title, unmute_dialog)
ui.register_dialog(DIALOG_STAR, "Add {company} to your watchlist?", star_dialog)
