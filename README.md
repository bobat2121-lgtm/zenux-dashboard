# ZENITH dashboard

The Zenith news-intelligence dashboard, built with Streamlit. It is a Zenith app, separate from the legacy PHYSAI news dashboard, and never talks to the legacy system. Its look is a black base with white accents: a full-width brand-green top bar (the ZENITH mark and wordmark, then the tabs), dark cards with hairline borders, bold white headlines, coloured tags, one colour per coverage area (amber Your coverage, violet AI infrastructure, teal Defense tech, sky Drones and aviation autonomy, green Autonomous vehicles, orange Robotics and automation, rose Public safety and security, indigo Space and Earth observation, fuchsia Conferences; a stable palette colour for any other), and a green footer. The theme is in `.streamlit/config.toml`; `feed.css` carries the rest. No text on the page is smaller than 12 px.

It is built for an analyst who has had a ten-minute overview: every label uses plain words (`zenux_dashboard/labels.py` is the one vocabulary), and the engine's terms (event ids, source keys, module ids, lanes, tiers, reason codes) appear only in the builder's Control room.

## Tabs

Three tabs for the analyst (`docs/SPEC-SIMPLIFY.md`): **Briefing** (daily), **Tuning** (weekly) and **Coverage** (setup); the **Control room** for the builder. Old links to the tabs this replaced still land: `tab=preferences` opens Tuning (a `pref=` link still highlights its rule) and `tab=filtered` opens Briefing.

| Tab | What it shows | Hub routes |
| --- | --- | --- |
| **Briefing** | A status line ("Healthy · last briefing 2h ago · next 12:30 PM ET"), at most two one-line banners (suggestions that need your OK; the weekly tune-up), one search box over your briefings and what was left out of them, then the published briefings, newest first, each named by its time ("Sun Oct 4 · morning briefing") with a one-line tuning receipt under its summary. The newest opens with the hero (stories, stories screened, top stories, also notable). Each story shows its date and source, a TOP STORY badge at 90+, and its icons: **More like this**, **Less like this** and **Rate this story** (the **More** menu is off for now). Under each briefing: the watchlist and near-miss shelves, **Left out of this briefing**, the **Editor's notes**, and **Why am I seeing this?** for every story, numbered like the cards ("01"), collapsed. **Load earlier briefings** at the end. | `GET /editions`, `/editions/<id>`, `/editions/latest`, `/editions/search`, `/status`, `/rejected?edition_id=` (once opened), `/rejected?q=&days=90` (search), `/tuneup`, `/preferences` and `/rules` (the banner's count); writes `POST /preferences`, `/feedback`, `/feedback/withdraw`, `/promote`, `/promote/withdraw`, `/tuneup/dismiss`, `/stars` (Not about) |
| **Tuning** | One page, in this order: the title and this week's summary; **Needs your OK** (only when something waits); **How much** in one row; **Your rules** (your preferences, mutes and watchlist in one list, with filter pills, **+ Add a rule** and one ⋯ menu per rule); **Ended** (collapsed). | `GET /preferences`, `/rules`, `/mutes?all=1`, `/mutes/bring-back-preview`, `/stars`, `/settings`, `/settings/volume/preview`, `/brief` (to name a line a suggestion changes); writes `POST /preferences`, `/rules/<id>/<action>` (with `reopen` for Undo), `/mutes`, `/stars`, `/settings/volume`, `/companies/suggestions/<id>/approve\|reject` |
| **Coverage** | **What ZENITH looks for** first (an expander titled with its sign-off state, open while the workspace is staging, with **Suggest a change** and **Sign off**; inside it, after Your coverage, **Your companies' big names**: each covered company's big products, units, customers and read-through names, **Find a name**, **Show all** and **Suggest a change** per company), then pick a coverage area: **How ZENITH covers this area** in four steps with its live numbers (Watch, Collect, Score, Brief), one line on source health (with "ZENITH is fixing 2 sources." while repairs are under way), and **What ZENITH watches**: Companies or Sources in one sortable table with search and filters; clicking a row opens its details (star, mute, **Request coverage**). Below, your coverage requests and where each one stands (asked, proposal ready, approved, set up, live), with the first stories of a new source. | `GET /brief`, `/modules`, `/modules/<id>/inspect`, `/radar`, `/mutes/bring-back-preview`; writes `POST /brief/suggest`, `/signoff`, `/companies/suggestions`, `/mutes`, `/stars`, `/radar/requests` |
| **Control room** | The builder's tab, only while the builder is unlocked (always, under open access); it spans every configured workspace. Today's diagnostics (severity, routines with their prompt in plain words, agreement, backlog, acknowledgements; a module that is not ok has a clickable status light that lists its failing sources and why), one line per routine with its last 7 days of scheduled fires and **Allow one extra run**, the technical view of a coverage area (lanes, connectors, keys, health per source), catch-up of past days, the technical review of coverage requests (approve or reject), the review of source repairs (approve, reject, withdraw), the company names to build in (with their commands), the stage switch, and Configuration. | `GET /diagnostics`, `/snapshot`, `/sources`, `/modules`, `/modules/<id>/inspect`, `/radar`, `/repairs`, `/companies/suggestions`; writes `POST /admin/sources/{ack,unack}`, `/admin/stage`, `/admin/routines/allow-once`, `/radar/<id>/{approve,reject}`, `/repairs/<id>/{approve,reject,withdraw}`; module `/health` and `/backfill` |

### What each control does

**Briefing**

- **Status line** (top): how ZENITH is doing, when the last briefing came and when the next is due, from the hub's light status read (`GET /status`); when a briefing is late it says which one. **Refresh** re-reads everything. While the workspace is still collecting (staging) it says so and offers **Review and sign off**, which opens Coverage, where What ZENITH looks for waits open.
- **Banners** (at most two, one line each, only when they apply): "3 suggestions need your OK" with **Review** (opens Tuning, where Needs your OK comes first); and the **weekly tune-up** while it is due ("Weekly tune-up: rate 5 stories so the editor learns your bar (about 2 minutes)."). **Start** opens a panel right there: one compact row per story the hub picked (the stories of this week's briefings whose scores sat closest to their bar), with its title, dateline and what the editor did ("In your briefing at 74", "Left out at 66, bar 70"), and four one-click ratings: Top story, In the briefing, Near miss, Not relevant (no dialog, score or note; `POST /feedback`). A rated row says so; when every row is rated: "Thanks. The editor uses your ratings from the next briefing." **Skip this week** hides it until next week (`POST /tuneup/dismiss`).
- **Search** (one box, always visible: "Search your briefings and what was left out (last 90 days)"): two groups. **In your briefings · N**: matching stories of the briefings loaded below show as full cards, and matches in earlier briefings are listed under them (the hub searches, `GET /editions/search`), each with **Show it**, which opens that briefing at the story. **Left out · N**: what the hub finds among the stories left out of your briefings of the last 90 days (`GET /rejected?q=&days=90`), 20 at a time with **Show more**, each as a left-out row (below). **Load earlier briefings** loads more full briefings.
- **Tuning receipt** (one line under a briefing's summary, only when a count is above zero): "Your tuning here: 2 stories brought in and 1 kept out by your rules; the editor used 3 of your ratings." (the briefing's `tuning`).
- **Story icons** (one row under each headline: the story's tags on the left, the icons on the right; `docs/SPEC-ICON-ACTIONS.md`): thumb up (**More like this**), thumb down (**Less like this**) and a star (**Rate this story**); a left-out story adds an arrow up (**Should have been in**). Hover an icon for its words. An icon glows green while the story holds what it stands for (a preference, a rating, an open request), and clicking a glowing icon undoes it, at any time; it then goes back to plain grey. The **Undo** bar still reverses your newest change; the icons are the lasting way back.
- **More like this** / **Less like this**: a preference that is active at once. Clicking a plain thumb saves it straight away as *Stories like this* with no end date (the toast says from which briefing it applies); clicking the other thumb while one glows switches in one click (the old one is replaced); clicking a glowing thumb undoes it ("Undone: more like this", it stops applying from the next briefing). **Ctrl+click** (**Cmd+click** on a Mac) opens every option: *Just this story*, *Stories like this* or *Standing preference*, a few words on what it is about, and an optional end date; on a story that already holds a preference, saving replaces it. Phones and tablets have no Ctrl key: a tap saves or undoes, and a preference's options are in Tuning (its ⋯ menu: **Edit**, **End date**). A story keeps one preference.
- **Rate this story**: clicking the plain star opens Top story, In the briefing, Near miss or Not relevant, an optional note, and an optional 0-100 score on a slider with the scale beside it (90-100 top story, 70-89 in the briefing, 40-69 near miss, 0-39 not relevant). The slider and the rating move together; the exact score is sent only when you move the slider. When your band differs from the editor's score, the editor scores similar stories in your band from the next briefing. The star then glows ("You rated it: Top story"); clicking it withdraws your rating (the editor stops using it from the next briefing), and **Ctrl+click** rates it again (the new rating counts as your newest).
- **Should have been in** (the arrow on a left-out story): sends the story back to the editor with your note (it may still stay out if the evidence is thin). The arrow glows while your request is open; clicking it withdraws the request (if the editor already looked at the story again, only your note is withdrawn and the story stays where it is).
- **More** menu (off for now, `actions.SHOW_MORE_MENU`; mutes and stars live in Coverage and Tuning): **Wrong facts**, **Rate this story**, **Mute outlet**, **Mute source**, **Mute company** / **Unmute company**, **Star** / **Remove from watchlist**, **Not about <company>**, **Mute this story**. Choosing an item closes the menu and opens its dialog.
- **Conferences coming up** (docs/SPEC-MIGRATION-BUILD.md section 7): the first briefing of Friday's first scheduled time opens with this card instead of a story: the next six months by month, one line per conference (lines with NEW, DATES SET, NOW PRESENTING: TICKER or MOVED first, each with its event page), then the later months and the conferences whose dates are not posted yet. It has no number, score, tags or icons, and it is not counted among the stories (`feed_view.conference_html`; the hub's item of kind `conference_list`).
- **Why am I seeing this?** (one collapsed section under the Editor's notes, one entry per story headed by its number): the plain reason and score, the editor's reasoning (in plain words), your preferences that applied (in your words, with **See it in Tuning**), your watchlist, your requests (and when you asked), the source and its group, and the companies.
- **Shelves** under each briefing: stories about your watchlist companies and (when switched on under How much) the near misses, each a left-out row; a watchlist row also offers **Not about <company>** for a look-alike name.
- **Left out of this briefing · N** (collapsed; it reads `GET /rejected?edition_id=N` only once opened): three groups, **Near misses**, **Below your bar** and **Same story as one in your briefings**, each best score first, 10 rows and **Show N more**; then one caption, "Kept out before the editor read them: 4 muted, 12 old news.", with **See your mutes** (Tuning, Your rules, Muted). A briefing from a hub older than schema 11 has no such section.
- **A left-out row** (the shelves, Left out of this briefing, the search's Left out group): the title (linked), the dateline (date · source · coverage area), one reason chip ("Near miss", "Cut for space", "Later in your briefing" ...), the story icons with the arrow where Should have been in applies, **Show it** when a later briefing published it (or, for the same story, the briefing that ran it), and **Why was it left out?**, which holds the score and the bar in force for that briefing ("Near miss · score 64 of 100 · bar 70"), the editor's reasoning, your preferences that applied, your request, the source's group and the companies. The row itself shows no score.

**Tuning** (one page, no sub-tabs)

- **Tuning** and this week's summary ("This week your preferences changed 23 decisions: ..."), with **Refresh**; a line when suggestions you sent are still with the wording assistant.
- **Needs your OK · N** (only when something waits): wordings the wording assistant suggests for what you wrote, suggestions built from your ratings, merges of overlapping preferences, your suggested changes to What ZENITH looks for and suggestions from coverage requests. Each card: its kind, the suggestion, one impact line ("Would have brought 3 stories in and kept 1 out over the last 14 days."), and its two buttons: **Approve** / **Not now**, **Use this wording** / **Keep mine**, **Merge them** / **Keep them separate** (with **Undo**). **Details** holds the rest: the ratings behind it, which stories it would bring in and drop out, the wording assistant's reasoning, the wording box (edit before approving if you like) and the preferences it may conflict with (each ended on approval unless you untick it). A merge over a preference that has ended since offers only **Keep them separate**; a suggestion changed meanwhile is shown again instead of approved. Suggested company names the source finder has checked (`docs/SPEC-COMPANY-MAP.md` 6.3, from GET `/preferences` `company_suggestions`) are cards of the same list, counted by the Briefing's banner: "Suggested name for Red Cat Holdings", what it changes ("Add Army Drone Dominance program to Customers & programs"), your own words when the source finder cleaned them up, the note, a big customer's reason and the source finder's result ("Confirmed: <title>, <date>" with the link, or "Could not confirm"); **Approve** (the version shown) and **Reject** (`POST /companies/suggestions/<id>/approve|reject`, never `/rules`; no route reverses either, so there is no Undo, and Reject asks first). A name the hub leaves out (the company's, or the one a removal or fix is about) comes from the names on file. After approval: "The ZENITH editor uses it from the next briefing. The builder adds it to story tagging with the next update." **Details** holds what the source finder found, its sources and what you sent.
- **How much** (one row): *Only the big ones*, *Standard* or *Everything notable*, the switch for near misses under each briefing, the preview line ("Would show about 6 per briefing instead of about 9.") and **Use this setting** (enabled only when changed; **Undo** goes back).
- **Your rules · N**: your preferences, mutes and watchlist in one list. The pills **All · More · Less · Muted · Watchlist** (with counts) filter it; **+ Add a rule** opens a dialog (more like this, less like this or exactly as I write it, in your own words, optionally only for a while; active at once, **Undo** ends it). Each row says what kind it is, its words or name, one impact line (a preference: what it did in 30 days; a mute: what it hid this week; the watchlist: its stories this week) and, when one applies, a hint (paused; a clearer wording is waiting; it kept out mostly one source; not used in 30 days). Its ⋯ menu: a preference has **Edit**, **End date** and **Remove** (asks first; **Undo** brings it back), plus **Resume** when it is paused and **Mute <source> instead** when it looks like a mute; a mute has **Unmute** (it says first how many stories it would bring back); the watchlist has **Remove from watchlist**. There is no Pause: remove a rule, and bring it back from Ended. A link to a preference (`pref=`) highlights its row.
- **Ended · N** (collapsed): ended preferences with **Bring back** (one whose end date passed asks for a new one) and removed mutes with **Bring back the last 7 days**, the most recently ended first, 100 at most.

**Coverage**

- **What ZENITH looks for** (an expander at the top, titled "What ZENITH looks for · signed off by you on Oct 3" or "· not signed off yet", open while the workspace is staging, under a banner that says so): the one-pager the editor works from, in the dashboard's words (Top story, In the briefing, Near miss, Your coverage ...; the hub maps the rubric's own words), **Suggest a change** on each part (the wording assistant words it, and it comes back in Tuning under Needs your OK), and **Sign off** (sends the versions you are looking at).
- **Your companies' big names** (inside What ZENITH looks for, right after Your coverage; `docs/SPEC-COMPANY-MAP.md` 6.1 and 6.2, from `GET /brief` `companies`): one row per covered company in ticker order, its name and summary, then four columns (**Products & brands**, **Units & acquisitions**, **Big customers & programs**, **Read-through**) with only the big names as chips. A big customer's chip shows its reason on hover (73% of 2025 revenue; big means 5% or more of revenue, or treated or expected to be that big); ☎ marks a name the company gives only on calls or in filings, and a legend says so; an empty column says "None on file". **Find a name** searches every name and other name, big or not, keeps the companies that have it and highlights it. **Show all N** (drawn only while open) lists every name with what it is ("Bought Sep 2024", "Agreed to buy Aug 2026"), a note (its dates in plain words), how it is known, since when ("Since ...", "First named ...") and "Not used to tag stories" where that applies. Suggestions not built in yet show under their company: "Being checked", "Needs your OK" or "Approved: the ZENITH editor uses it from the next briefing" ("... stops counting it ..." for a removal; a fix that only takes "big" away says so). **Suggest a change** per company opens a dialog: add, remove or fix a name, which column, the name (or the one on file), one line on what it is, for customers whether it is big and why, and an optional link (`POST /companies/suggestions`); the toast says "Sent. The source finder checks it on its next run; then it shows in Tuning under Needs your OK." Under 900 px each company's columns stack.
- **Coverage area**, then **How ZENITH covers this area**: *Watch* (companies and sources, and the kinds of sources), *Collect* (stories this week), *Score* (the editor scores every story 0 to 100; its next run) and *Brief* (what made your briefings, with the bar and size of a briefing from How much; the rest show under each briefing, in Left out of this briefing). Under it one line on source health; when a source is not responding it is named, with **Show them**, and while the builder is fixing sources it says how many ("ZENITH is fixing 1 source.").
- **What ZENITH watches**: **Companies** or **Sources**, a search box (name, ticker, group, kind of source) and a filter (*On your watchlist*, *Muted*, *By name only*; *Not responding*, *Turned off*, *Muted*), then one table (sort by any column). Click a row for its details: a company's feeds, **Star** / **Remove from watchlist**, **Mute company**, **Request coverage**; a source's health and link, **Mute** / **Unmute**. Mute dialogs show what the mute would have hidden in the last 7 days before you confirm.
- **Coverage requests**: ask for a source, a company or a topic, or report a missed story; each request shows its steps (asked, proposal ready, approved, set up, live) and the source finder's plain answer. **Withdraw** while it is still asked or proposed.

**Control room** (builder): today's diagnostics with one row per module (a module that is not ok has a clickable status light, "Degraded · 1 failing source", that opens **Source health**: each failing source with what is wrong in plain words, when it last worked, its failures in a row, the module's last error and its open repair, if any, then the retrying, slowed, acknowledged and quiet ones; a source counts as failing after 2 missed checks in a row, so one missed check is "retrying" and colours nothing, and an ok module with retrying or slowed sources shows a small note, "1 retrying · 1 slowed", that opens the same window); the routines table, whose Prompt column says each routine's prompt in plain words (`prompt_state`: current, "picks up its updated instructions at its next run, 7:30 AM ET", or "ran with an old copy of its instructions"); under the card one line per routine with its last 7 days of scheduled fires (`slots_7d`: ran, skipped as not due, catch-ups, by hand) and **Allow one extra run** (the next due check of that routine lets one run through within 2 hours, so a run you start by hand from claude.ai/code/routines goes ahead; a hub older than schema 11 shows neither); **Acknowledge** on failing sources, the stage switch, **Open a module** for the technical view of a coverage area, catch-up of past days, the technical review of coverage requests (**Approve**, **Reject**, the setup command), the review of source repairs (below), and Configuration.

Mutes never stop collection: every mute says "Still collected, kept out of your briefing." A rating is used to calibrate the next briefing when its band differs from the ZENITH editor's score, and nothing more is claimed. There are no alerts or notifications; a toast is only the page answering your own click.

## Reviewing source repairs

When a source breaks, the Radar scout's repair step (`docs/PLAN-SOURCE-REPAIR.md`, Phase B) proposes one fix and proves it with a probe run on the module Worker itself. The Control room lists the proposals under **Source repairs to review**, right after the coverage requests, for every workspace (`GET /repairs`; `zenux_dashboard/repairs_view.py`):

- Each proposed repair is a card: the action in plain words (**Replace the source**, **Turn it off**, **Check it less often**, **Add a source**), the module, the source's name and key, why it broke (the repair queue's plain label) and the scout's diagnosis, **Before** and **After** side by side (the catalog's entry against the new source definition, as compact JSON, for a replacement or an added source; the off reason the analyst will read and the alternates that cover it, by name, for a source turned off; the old and new pace for a slow-down), and the probe's answer (its status, the HTTP answer, how many items it found, up to 5 titles as links, when it ran).
- **Approve** or **Reject**, with an optional note (`POST /repairs/<id>/approve|reject`). Neither can be undone, so Reject asks first. The hub's own sentence explains a refusal (a repair that moved on meanwhile), and the list is read again.
- Below, collapsed, with their counts: **approved** repairs, each with the command that applies it, `node tools/zenux.js repair apply <ws> <id>` (it writes the change into the module, keeps the old definition in the source's notes, runs the module's tests and puts the files back when they fail), then the deploy, `node deploy/workspace.mjs <ws>`, and **Withdraw** (asks first); **applied** ones (waiting for the source to report ok; **Withdraw** a fix that did not work: the change stays in the module, and the Radar scout may propose another one), **recovered** ones, and the **rejected or withdrawn** ones, most recent first.
- The **Source health** window adds one line to a failing or retrying source with an open repair: "A fix is proposed", "A fix is approved; waiting for the builder to apply it" or "A fix is applied; waiting for the source to report ok".
- Coverage tells the analyst in plain words: "ZENITH is fixing 2 sources." (`GET /modules`, `repairs_open`).

Writes need the owner token like every Control room write (under open access everyone is the builder). A hub older than schema 9 has no `GET /repairs`: the section says so in one line until the hub is deployed.

Right after the source repairs, **Company names to build in · N** lists, for every workspace (`GET /companies/suggestions?status=approved` and `?status=applied`; `zenux_dashboard/company_names_view.py`), the company names the analyst approved, each with `node tools/zenux.js company apply <ws> <id>` (it writes the company's sheet, rebuilds the registries and the bundle, runs their tests and marks it applied), then the deploy, `node deploy/workspace.mjs <ws>`, then the applied ones waiting for that deploy. A hub older than schema 13 says so in one line.

## Open access (beta testing)

While the owner beta tests, **open access is on by default** (`config.OPEN_ACCESS_DEFAULT`): no PIN is asked anywhere, every visitor can change every workspace that has a `hub_url` and an `owner_token`, and the Control room is open. The top bar says **Open for testing** instead of **Sign in to edit**. The dashboard's URL is public, so anyone who has the link can edit; restrict who can open the app in Streamlit Community Cloud (the app's **Share** settings) if that matters.

To require the PINs again, add `open_access = false` at the top of the app's Secrets (Streamlit Community Cloud: your app › **⋮** › **Settings** › **Secrets**; locally `.streamlit/secrets.toml`). The PINs stay in the secrets either way, so nothing else changes. Turn it off before other analysts get the link.

## Sign in to edit, and the builder

With `open_access = false`: reads use each workspace's `read_token`; nothing to unlock. Every change (a preference, a mute, a star, a rating, a sign-off, a coverage request, an acknowledgement, a catch-up) needs **Sign in to edit** (top right):

- Type the workspace's PIN once and press Enter or **Unlock**. The PIN is checked once, in constant time, against the workspace's `owner_pin` from the secrets; the field is cleared right away, and the session keeps only a keyed fingerprint (never the PIN), so a changed PIN in the secrets locks the session again. The popover then says **Signed in** and offers **Lock** (which also disables a pending **Undo**). A browser reload is a new session and asks again.
- While locked, every change button is drawn but disabled, with the hint "Unlock to edit: use Sign in to edit at the top right." Nothing fails after you press it.
- A PIN unlocks only its own workspace, and needs 8 or more characters. A placeholder from `secrets.example.toml` or this README (`REPLACE_WITH_...`, `...`, `<your PIN>`) counts as no PIN, because anyone can read it; editing then stays off and the Control room's **Configuration** notes say why.
- Guessing is limited across the whole app, not per browser session. After 5 wrong PINs, every PIN is refused for 1 minute, even the right one; each further lockout doubles the wait, up to 1 hour. The right PIN clears the count, and misses are forgotten after a day without one. A wrong PIN waits 1 second. A wrong PIN and a refused PIN show the same message. Workspaces (and the builder) that share a PIN share the limit.
- **The builder** opens the Control room under the divider in the same popover (**Builder PIN**, **Open the Control room**). The builder PIN is the top-level `builder_pin` (8+ characters). Without one, and only with exactly one workspace (the pilot, where the owner is the builder: one PIN unlocks both), the top-level `owner_pin`, else that workspace's `owner_pin`. With two or more workspaces `builder_pin` is required: no owner PIN opens the Control room, so an analyst who knows a shared PIN never reaches the other workspaces. A builder may change every configured workspace. These roles live in the dashboard only (the hub has one OWNER_TOKEN for every write); identity sign-in comes later.

## Toasts, undo and confirmations

- Every change answers with a toast that says what changed and when it takes effect, from the hub's `effective` answer: "Applies from the 12:30 PM briefing.", "Applies from tomorrow's 7:30 AM briefing.", or "Takes effect once you approve the wording in Tuning." A toast goes away by itself after 9 seconds.
- When the hub can reverse a change, a slim bar at the top of the page offers **Undo** (and **Dismiss**) until your next change, or for 10 minutes; setting a suggestion aside can be undone too. Changes with no reverse route (Should have been in, a rating, Wrong facts, a suggested change, sign-off) say so where it matters.
- Destructive or consequential actions ask first in a dialog: removing a preference, unmuting, every mute (its dialog is also the preview of what it would hide), signing off, switching the stage, rejecting a coverage proposal, ending a preference on a date. A tune-up rating and Skip this week are one click each (neither has an undo route; the story's star withdraws a rating).
- A failed read shows "Couldn't load ..." with a plain reason and **Try again**; the technical line is shown to the builder only, collapsed. A refused change says "Not saved: ..." in place (the dialog stays open) with the hub's own plain sentence ("This mute is not complete. The coverage area is missing."); the dashboard's guard against engine words stays as the last check, and puts its own words in place of a sentence that fails it.
- Nothing reruns on a timer while you type. Briefing checks every two minutes for a newer briefing (`GET /editions/latest`, the id only) and offers **Show it**; the Control room refreshes its own health panel. Lists that could be long are lazy: Left out of this briefing reads only once opened, Why only while open, Ended only while open.

## Deep links

The query string mirrors where you are, so a reload or a shared link lands on the same tab and object: `tab` (`briefing`, `tuning`, `coverage`, `control`), `ws` (with two or more workspaces), `edition` and `item` (Briefing), `rules` (Tuning's filter: `more`, `less`, `muted`, `watchlist`) and `pref` (`R-0012`, highlighted in Your rules), `module` (a coverage area) and `request` (a coverage request). For example `?tab=briefing&edition=12&item=1203` or `?tab=tuning&rules=muted`. Old links still land: `tab=preferences` opens Tuning (`section=looks_for` opens Coverage instead, `section=muted` or `watchlist` picks that filter; `section` is never written), and `tab=filtered` (with any `view`) opens Briefing. Invalid values are ignored. A link to the Control room while the builder is locked opens Briefing with a note. Inside the page, navigation uses buttons (a link reload would start a new session and lose the unlock).

## Configuration (`st.secrets`)

Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml` and fill it in. Both paths are inside `dashboard/`, and `secrets.toml` is gitignored.

```toml
owner_pin = "..."                 # optional default PIN for every workspace
builder_pin = "..."               # optional: opens the Control room (8+ characters)

[[workspaces]]
id = "pilot"
title = "Pilot"                   # optional
timezone = "America/New_York"     # optional (the default)
hub_url = "https://zenux-pilot-hub.<account>.workers.dev"
read_token = "..."                # hub READ_TOKEN
owner_token = "..."               # hub OWNER_TOKEN
owner_pin = "..."                 # the PIN you type (8+ characters); overrides the default

[[workspaces.modules]]
id = "ai-infra"
url = "https://zenux-pilot-ai-infra.<account>.workers.dev"
run_token = "..."                 # module RUN_TOKEN: catch-up and the detailed /health
```

- Add one `[[workspaces]]` table per analyst workspace. The workspace switcher and the Control room then include it. With two or more, add `builder_pin`.
- URLs must use `https`. Plain `http` is accepted only for `localhost`, `127.0.0.1`, `[::1]` and `*.localhost`.
- A missing token turns off only the features that need it. The Control room's **Configuration** lists what is missing, and whether the builder PIN is set (never a value).
- Generated Worker tokens live in `.local/<ws>/tokens.json`, which `deploy/workspace.mjs` writes and which is gitignored. Never commit them.

## Run locally

From the repository root (Windows paths shown; on macOS or Linux use `.venv/bin/`):

```bash
python -m venv dashboard/.venv
dashboard/.venv/Scripts/python -m pip install -r dashboard/requirements.txt
cp dashboard/.streamlit/secrets.example.toml dashboard/.streamlit/secrets.toml   # then fill it in
dashboard/.venv/Scripts/python -m streamlit run dashboard/streamlit_app.py
```

Streamlit reads `dashboard/.streamlit/config.toml` (the theme) and `dashboard/.streamlit/secrets.toml` because they sit next to the main script. If no workspace is configured, the app says so and makes no requests.

### Against a throwaway local hub (never production)

To try changes without touching a deployed hub, run a scratch copy of `dashboard/` (without its `.streamlit/secrets.toml`) against an in-memory hub with throwaway tokens:

```bash
ZENUX_READ_TOKEN=<random> ZENUX_OWNER_TOKEN=<random> ZENUX_REVIEW_TOKEN=<random> ZENUX_HUB_TOKEN=<random> \
  node brain/dev-hub.mjs pilot --seed --db <scratch>/hub.sqlite --port 8791
```

Then write `<scratch>/dashboard/.streamlit/secrets.toml` with `hub_url = "http://127.0.0.1:8791"`, those tokens, a throwaway `owner_pin`, and module URLs on the reserved `.invalid` domain, and run `dashboard/.venv/Scripts/python -m streamlit run <scratch>/dashboard/streamlit_app.py --server.port 8601`. Never point a scratch copy at `.local/<ws>/tokens.json`: those tokens are the deployed ones.

To see real data, run the local hub on a **copy** of the pilot database, with every file it writes in the scratch folder (it generates fresh tokens into `--tokens`, upgrades the copy's schema and takes its backup at `--backup`, which otherwise defaults to `.local/<ws>/`):

```bash
cp .local/pilot/hub.sqlite .local/pilot/hub.sqlite-wal .local/pilot/hub.sqlite-shm <scratch>/   # the -wal/-shm files when present
node hub/dev-server.mjs pilot --port 8796 --db <scratch>/hub.sqlite --backup <scratch>/hub.before.sqlite \
  --tokens <scratch>/tokens.json --control <scratch>/dev-server.json
```

Push the coverage catalogs with `deploy/lib/catalog.mjs` `buildCatalog` and `POST /admin/catalog` (owner token from `<scratch>/tokens.json`), and stop the hub with `node hub/dev-server.mjs pilot --stop --control <scratch>/dev-server.json`.

## Tests

```bash
cd dashboard
.venv/Scripts/python -m unittest discover -s tests
```

The tests use `streamlit.testing.v1.AppTest` and a routed fake for `requests.get` and `requests.post` (`tests/helpers.py`), so nothing touches the network, and they never read a secrets file (the harness points Streamlit's secrets path at a file that does not exist; tests pass their secrets through `AppTest.secrets`). `helpers.hub_defaults()` routes every hub read to the v8 bodies in `tests/fixtures.py` (`GET /repairs` to an empty v9 list, `GET /tuneup` to a tune-up that is not due); each view keeps extra bodies in its own `fixtures_<area>.py` (the schema 11 shapes of `docs/SPEC-SIMPLIFY.md` section 1: `fixtures_leftout.editions_v11`, `edition_rows`, `fixtures.tuneup_due`). Every analyst tab is checked by the jargon guard (`AppCase.assert_plain`: no engine word anywhere a reader can see) and for leaked secrets (`assert_no_secrets`).

- the shell (`test_app_shell.py`, with the views stubbed): tabs and who sees them, sign in to edit, builder access and its fallbacks, deep links and the old links of the removed tabs, the page-level error box, the unchanged masthead, logo, page icon, theme, footer, configuration states and the workspace switcher
- `test_ui.py`: toasts, the undo bar, dialogs, confirmations, locked buttons, plain errors, `effective_text` (with the DST change)
- `test_status.py`: the status line (from `GET /status`) and the new-briefing banner (from `GET /editions/latest`)
- `test_units.py` and `test_owner_pin.py`: config with the builder PIN, sign-in state, the PIN guard, every hub wrapper, labels, links, formatting and the 12 px floor
- `test_app_errors.py`: each tab's error box, malformed payloads, secrets in URLs and on the page
- each tab's own tests: `test_app_briefing.py`, `test_actions.py`, `test_app_banners.py` (the two banners, the weekly tune-up and the tuning receipt), `test_app_left_out.py` (Left out of this briefing, the shared left-out row, the shelves and the search's Left out group, with `fixtures_leftout.py`), `test_app_tuning.py` (Tuning, with `fixtures_tuning.py`), `test_app_brief.py` (What ZENITH looks for, on Coverage), `test_app_company_map.py` (Your companies' big names and its Suggest a change) with `test_units_company_names.py` (the suggested names' cards), `test_app_coverage.py`, `test_app_requests.py`, `test_app_control_room.py` (with the routines' prompt state, fires and Allow one extra run), `test_app_repairs.py` (source repairs, the Source health window's line and Coverage's line, with `fixtures_repairs.py`) and their `test_units_<area>.py`

## Deploy to Streamlit Community Cloud

The app must never be public while it holds secrets. Reads use the hub's `read_token` on the server, so anyone who can open the app can read the feed, and anyone who can open it can also try PINs. So deploy it **without secrets** first, make it private, and only then add the secrets. With no secrets the app shows "No Zenith workspace is configured" and makes no requests, so there is nothing to see while it is briefly reachable.

1. Push the repository (private repo `zenux`) to GitHub. The orchestrator owns git; this folder needs nothing extra.
2. At share.streamlit.io, choose **Create app** and deploy from GitHub with:
   - **Repository:** `<owner>/zenux`, **Branch:** `main`
   - **Main file path:** `dashboard/streamlit_app.py`
   - **App URL:** for example `zenux-<name>`
   - **Advanced settings:** **Python version** 3.12 or newer (these pins are tested on 3.14). Leave **Secrets** empty for now.
3. Press **Deploy**.
   - Community Cloud installs `dashboard/requirements.txt` (it looks in the main file's folder first).
   - The theme comes from `dashboard/.streamlit/config.toml`, and `feed.css` carries the rest of the look.
4. Under **Settings**, then **Sharing**, make the app private and invite only the viewers who need it. Open the app in a private browser window to check that it asks you to sign in.
5. Only now, under **Settings**, then **Secrets**, paste the contents of your `secrets.toml`, with an `owner_pin` of 8 or more characters (and a `builder_pin` once there are two workspaces). Community Cloud restarts the app with the values.

To rotate a token or a PIN, edit the app's secrets. Community Cloud restarts the app with the new values. A restart also clears the PIN-guessing counters, so rotate the PIN if you suspect someone has been guessing.

## Files

| Path | Purpose |
| --- | --- |
| `streamlit_app.py` | Entry point: page config, masthead, tabs, sign-in popover, the undo bar, view dispatch, dialogs, deep links |
| `feed.css` | The design system: Roboto, the black base, the brand-green bars, cards, the hero, pills, the shell's status line, undo bar, error boxes and narrow-screen rules |
| `assets/zenux-mark.png`, `assets/zenux-favicon.png` | The logo mark (inlined into the top bar) and the browser-tab icon |
| `zenux_dashboard/config.py` | Parses and validates `st.secrets` into workspaces, modules and the builder PIN |
| `zenux_dashboard/api.py` | `requests` client for the hub and module Workers: one wrapper per route, local validation, plain hub messages on `ApiError` |
| `zenux_dashboard/data.py` | Cached reads (60 s; coverage areas 120 s; the coverage inspector and the brief 300 s), plus the parallel health gather |
| `zenux_dashboard/owner.py` | Sign in to edit: the PIN guard (`hmac.compare_digest`), the session's unlock and the builder |
| `zenux_dashboard/labels.py` | The one vocabulary: tab names, reasons, ratings, scopes, coverage words, briefing names, the jargon guard |
| `zenux_dashboard/ui.py` | Toasts, the undo bar, dialogs and confirmations, `write()`, locked buttons, plain errors |
| `zenux_dashboard/links.py`, `zenux_dashboard/status.py` | Deep links and in-app navigation; the status line and the new-briefing check |
| `zenux_dashboard/fmt.py` | Time formatting, HTML escaping, safe links, pills and tables |
| `zenux_dashboard/feed_view.py`, `actions.py` | Briefing (its banners, search, receipt, shelves), and the card actions shared by every tab |
| `zenux_dashboard/left_out.py`, `tuneup.py` | The shared left-out row, Left out of this briefing and the search's Left out group; the weekly tune-up |
| `zenux_dashboard/tuning_view.py` | Tuning: Needs your OK, How much, Your rules, Ended, and the preference dialogs |
| `zenux_dashboard/coverage_view.py`, `brief_view.py`, `radar_view.py` | Coverage, What ZENITH looks for with the sign-off (at its top), and coverage requests (the analyst's part and the builder's review) |
| `zenux_dashboard/control_view.py`, `repairs_view.py` | The Control room, and its review of source repairs |
| `zenux_dashboard/company_map_view.py` | Your companies' big names (in What ZENITH looks for) and its Suggest a change dialog |
| `zenux_dashboard/company_names_view.py` | Suggested company names: their Needs your OK card (shapes and HTML) and the Control room's Company names to build in |
| `.streamlit/config.toml`, `.streamlit/secrets.example.toml` | Theme and the secrets template (committed) |
| `tests/` | AppTest and unit tests |

## Hub contract

The dashboard reads fields tolerantly: a missing field is left out of the display, never guessed. The schema 11 additions are in `docs/SPEC-SIMPLIFY.md` section 1 (`left_out` and `tuning` on every edition, `GET /rejected?edition_id=` with each row's `group`, `GET /tuneup`, `POST /tuneup/dismiss`, `POST /admin/routines/allow-once`, and the routines' `prompt_state`, `slots_7d`, `allow_once_until`, `last_skipped_at`); an older hub simply shows no receipt, no left-out section, no tune-up and no Allow one extra run. The older shapes are in `docs/SPEC-PHASE02.md` section 5 (schema v8), `docs/SPEC-PHASE05.md` (the WF5 reads and plain fields: `/status`, `/editions/<id>`, `/editions/latest`, `/editions/search`, `/mutes/bring-back-preview`, the views of `/rejected`, `plain_text`, `rationale_plain`, `proposal_plain`, `preview_items`, `briefing_7d` ...) and `docs/SPEC-PHASE01.md` 4.6 (diagnostics, the Control room's read), and `docs/SPEC-REPAIR-PHASE-B.md` 1.2 and 1.4 (schema v9: `/repairs`, the repair object, `repairs_open` on `/modules`); `docs/SPEC-PHASE03-UI.md` describes the screens and section 10 lists the API gaps and which are closed. Every hub refusal is `{error, message, ...}`: the dashboard shows `message` (one plain sentence) and keeps `error` and the HTTP status for the builder. Every write answer carries `effective` (`{applies_from, next_briefing_at, timezone}`), which the toasts turn into "Applies from the ... briefing." Approvals send the `proposed_at` of the proposal shown, and a sign-off sends the versions of the page shown, so nothing you have not seen is ever approved.
