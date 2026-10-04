# ZENUX dashboard

The Zenux news-intelligence dashboard, built with Streamlit. It is a Zenux app, separate from the legacy PHYSAI news dashboard, and never talks to the legacy system. Its look is a black base with white accents: a full-width brand-green top bar (the ZENUX mark and wordmark, then the tabs), dark cards with hairline borders, bold white headlines, coloured tags (violet for AI infrastructure, teal for defense unmanned, a stable palette colour for any other coverage area), and a green footer. The theme is in `.streamlit/config.toml`; `feed.css` carries the rest. No text on the page is smaller than 12 px.

It is built for an analyst who has had a ten-minute overview: every label uses plain words (`zenux_dashboard/labels.py` is the one vocabulary), and the engine's terms (event ids, source keys, module ids, lanes, tiers, reason codes) appear only in the builder's Control room.

## Tabs

| Tab | What it shows | Hub routes |
| --- | --- | --- |
| **Briefing** | A status line ("Healthy · last briefing 2h ago · next 12:30 PM ET"), then the published briefings, newest first, each named by its time ("Sun Oct 4 · morning briefing"). The newest opens with the hero (stories, stories screened, top stories, also notable). Each story shows its date and source, a TOP STORY badge at 90+, and three separate buttons: **More like this**, **Less like this** and **Rate this story** (the **More** menu is off for now). Under each briefing: the watchlist and near-miss shelves, the **Editor's notes**, and **Why am I seeing this?** for every story, numbered like the cards ("01"), collapsed. A search box over your briefings of the last 90 days, and **Load earlier briefings**. | `GET /editions`, `/editions/<id>`, `/editions/latest`, `/editions/search`, `/status`; writes `POST /preferences`, `/feedback`, `/mutes`, `/stars`, `/promote` |
| **Filtered out** | What was left out: **Near misses** (the default), All, Same story, Muted (with your mutes, Unmute and bring back) and Old news, each with its true count, with plain reasons and scores, the story a repeat repeats, search over the whole window, **Sort** (newest, highest score or lowest score first) and the same card actions, plus **Should have been in**. | `GET /rejected?filter=&q=&module=&offset=`, `/mutes?all=1`, `/mutes/bring-back-preview`; writes as above |
| **My preferences** | **Needs your OK** (suggested wordings, suggestions from your ratings and merges, each with its 14-day preview and the stories it moves), **Active** preferences with what they changed (pause, resume, edit, end date, remove), **What ZENUX looks for** with **Suggest a change** and **Sign off**, **Muted**, **Watchlist** and **How much** (the dial, with its preview). | `GET /preferences`, `/rules`, `/brief`, `/mutes`, `/mutes/bring-back-preview`, `/stars`, `/settings`, `/settings/volume/preview`; writes `POST /rules/<id>/<action>` (with `reopen` for Undo), `/brief/suggest`, `/signoff`, `/settings/volume` |
| **Coverage** | Pick a coverage area, then **How ZENUX covers this area** in four steps with its live numbers (Watch, Collect, Score, Brief), one line on source health (with "ZENUX is fixing 2 sources." while repairs are under way), and **What ZENUX watches**: Companies or Sources in one sortable table with search and filters; clicking a row opens its details (star, mute, **Request coverage**). Below, your coverage requests and where each one stands (asked, proposal ready, approved, set up, live), with the first stories of a new source. | `GET /modules`, `/modules/<id>/inspect`, `/radar`, `/mutes/bring-back-preview`; writes `POST /mutes`, `/stars`, `/radar/requests` |
| **Control room** | The builder's tab, only while the builder is unlocked (always, under open access); it spans every configured workspace. Today's diagnostics (severity, routines, agreement, backlog, acknowledgements; a module that is not ok has a clickable status light that lists its failing sources and why), the technical view of a coverage area (lanes, connectors, keys, health per source), catch-up of past days, the technical review of coverage requests (approve or reject), the review of source repairs (approve, reject, withdraw), the stage switch, and Configuration. | `GET /diagnostics`, `/snapshot`, `/sources`, `/modules`, `/modules/<id>/inspect`, `/radar`, `/repairs`; writes `POST /admin/sources/{ack,unack}`, `/admin/stage`, `/radar/<id>/{approve,reject}`, `/repairs/<id>/{approve,reject,withdraw}`; module `/health` and `/backfill` |

### What each control does

**Briefing**

- **Status line** (top): how ZENUX is doing, when the last briefing came and when the next is due, from the hub's light status read (`GET /status`); when a briefing is late it says which one. **Refresh** re-reads everything. While the workspace is still collecting (staging) it says so and offers **Review and sign off**.
- **Search** (always visible): searches headlines, story text and companies of your briefings of the last 90 days. Matching stories of the briefings loaded below show as full cards; matches in earlier briefings are listed under them (the hub searches, `GET /editions/search`), each with **Show it**, which opens that briefing at the story. **Load earlier briefings** loads more full briefings.
- **More like this** / **Less like this**: a preference that is active at once. Choose *Just this story*, *Stories like this* or *Standing preference*, optionally say in a few words what it is about, and optionally end it on a date. The toast says from which briefing it applies; **Undo** removes it.
- **Rate this story**: Top story, In the briefing, Near miss or Not relevant, an optional note, and an optional 0-100 score on a slider with the scale beside it (90-100 top story, 70-89 in the briefing, 40-69 near miss, 0-39 not relevant). The slider and the rating move together; the exact score is sent only when you move the slider. When your band differs from the editor's score, the editor scores similar stories in your band from the next briefing.
- **More** menu (off for now, `actions.SHOW_MORE_MENU`; mutes and stars stay in Coverage and My preferences): **Wrong facts** (the editor re-checks the story at the next briefing and corrects it or says why it stands; the card then shows "Flagged by you"), **Rate this story** (Top story, In the briefing, Near miss, Not relevant), **Mute outlet** (a news-search story names its outlet, "Yahoo Finance via News search: ...", and that outlet can be muted alone), **Mute source** (for a news-search story: **Mute every outlet in ...**), **Mute company** / **Unmute company**, **Star** / **Remove from watchlist**, **Not about <company>** (a starred company's look-alike name), **Mute this story**. Choosing an item closes the menu and opens its dialog. A preference already made from the story shows on the card ("You asked for less like this" with **Undo**); a second one asks to replace it.
- **Mute** dialogs show what the mute would have hidden in the last 7 days before you confirm; the story is still collected. **Undo** unmutes and brings back what it hid. The menu offers every company the story is about (buyers and vendors too), not only its subject.
- **Why am I seeing this?** (one collapsed section under the Editor's notes, one entry per story headed by its number): the plain reason and score, the editor's reasoning (in plain words), your preferences that applied (in your words, with a link to them in My preferences), your watchlist, your requests (and when you asked), the source and its group, and the companies.
- **Shelves** under each briefing: stories about your watchlist companies and (when switched on under How much) the near misses, each with **Should have been in**. **Editor's notes** is collapsed at the bottom.

**Filtered out**

- **Show**: *Near misses* (just under the bar in force that day, best first; the score chip shows the score and that bar), *All*, *Same story* (left out because the briefing already had it: "Same story as: <headline> · in your <briefing>", with **Show it**), *Muted* (your mutes with **Unmute** and, for removed ones, **Bring back the last 7 days**, then what they hid) and *Old news* (too old when it arrived, or old news reposted). Each choice carries its true count for the window.
- **Search** and **Filters** (how many days back, which coverage area) are sent to the hub, so they cover every story of the window, not only a loaded page. The count line gives the true total ("Showing 50 of 1,240 stories"); **Show 50 more** reads further pages of 500 as you go.
- **Sort** (on the count line): *Newest first*, *Highest score first* or *Lowest score first*. A score order reads the whole window first, so the order covers every story; stories without a score (old news, mutes) come last. Changing the view resets it to the view's own order (near misses: highest first).
- Each row: the plain reason, the same card actions and **Should have been in** (sends the story back to the editor with your note). A story a later briefing published after all says **Later in your briefing**, with **Show it**. **Why was it left out?** names the preferences that applied in your words and the source's group.
- **Unmute** first says how many stories it would bring back ("12 stories it hid in the last 7 days would go back to the editor"), with examples.

**My preferences**

- **Needs your OK**: wordings the wording assistant suggests for what you wrote, suggestions built from your ratings, and merges of overlapping preferences. Each shows its 14-day preview ("+3 / -9": stories it would have brought in and kept out) and **Which stories** (their headlines and sources). Edit the wording if you like, then **Approve** / **Use this wording** / **Merge them**, or **Not now** / **Keep mine** / **Keep them separate** (with **Undo**). A merge over a preference that has ended since offers only **Keep them separate**.
- **Active**: **Add a preference** in your own words; each preference shows what it changed in 30 days and when it was last used, a hint when it has gone quiet or looks like a mute, and **Pause** / **Resume**, **Edit**, **End date** and **Remove** (asks first; **Undo** brings it back). Ended preferences can be brought back.
- **What ZENUX looks for**: the one-pager the editor works from, in the dashboard's words (Top story, In the briefing, Near miss, Filtered out, Your coverage ...; the hub maps the rubric's own words), **Suggest a change** on each part, and **Sign off** (sends the versions you are looking at).
- **Muted** and **Watchlist**: every mute and starred company, with Unmute, Bring back and Remove.
- **How much**: *Only the big ones*, *Standard* or *Everything notable*, and the near-miss shelf; the preview says how many stories a briefing would hold. **Use this setting** saves it; **Undo** goes back.

**Coverage**

- **Coverage area**, then **How ZENUX covers this area**: *Watch* (companies and sources, and the kinds of sources), *Collect* (stories this week), *Score* (the editor scores every story 0 to 100; its next run) and *Brief* (what made your briefings, with the bar and size of a briefing from How much). Under it one line on source health; when a source is not responding it is named, with **Show them**, and while the builder is fixing sources it says how many ("ZENUX is fixing 1 source.").
- **What ZENUX watches**: **Companies** or **Sources**, a search box (name, ticker, group, kind of source) and a filter (*On your watchlist*, *Muted*, *By name only*; *Not responding*, *Turned off*, *Muted*), then one table (sort by any column). Click a row for its details: a company's feeds, **Star** / **Remove from watchlist**, **Mute company**, **Request coverage**; a source's health and link, **Mute** / **Unmute**.
- **Coverage requests**: ask for a source, a company or a topic, or report a missed story; each request shows its steps (asked, proposal ready, approved, set up, live) and the source finder's plain answer. **Withdraw** while it is still asked or proposed.

**Control room** (builder): today's diagnostics with one row per module (a module that is not ok has a clickable status light, "Degraded · 1 failing source", that opens **Source health**: each failing source with what is wrong in plain words, when it last worked, its failures in a row, the module's last error and its open repair, if any, then the retrying, slowed, acknowledged and quiet ones; a source counts as failing after 2 missed checks in a row, so one missed check is "retrying" and colours nothing, and an ok module with retrying or slowed sources shows a small note, "1 retrying · 1 slowed", that opens the same window), **Acknowledge** on failing sources, the stage switch, **Open a module** for the technical view of a coverage area, catch-up of past days, the technical review of coverage requests (**Approve**, **Reject**, the setup command), the review of source repairs (below), and Configuration.

Mutes never stop collection: every mute says "Still collected, kept out of your briefing." A rating is used to calibrate the next briefing when its band differs from the ZENUX editor's score, and nothing more is claimed. There are no alerts or notifications; a toast is only the page answering your own click.

## Reviewing source repairs

When a source breaks, the Radar scout's repair step (`docs/PLAN-SOURCE-REPAIR.md`, Phase B) proposes one fix and proves it with a probe run on the module Worker itself. The Control room lists the proposals under **Source repairs to review**, right after the coverage requests, for every workspace (`GET /repairs`; `zenux_dashboard/repairs_view.py`):

- Each proposed repair is a card: the action in plain words (**Replace the source**, **Turn it off**, **Check it less often**, **Add a source**), the module, the source's name and key, why it broke (the repair queue's plain label) and the scout's diagnosis, **Before** and **After** side by side (the catalog's entry against the new source definition, as compact JSON, for a replacement or an added source; the off reason the analyst will read and the alternates that cover it, by name, for a source turned off; the old and new pace for a slow-down), and the probe's answer (its status, the HTTP answer, how many items it found, up to 5 titles as links, when it ran).
- **Approve** or **Reject**, with an optional note (`POST /repairs/<id>/approve|reject`). Neither can be undone, so Reject asks first. The hub's own sentence explains a refusal (a repair that moved on meanwhile), and the list is read again.
- Below, collapsed, with their counts: **approved** repairs, each with the command that applies it, `node tools/zenux.js repair apply <ws> <id>` (it writes the change into the module, keeps the old definition in the source's notes, runs the module's tests and puts the files back when they fail), then the deploy, `node deploy/workspace.mjs <ws>`, and **Withdraw** (asks first); **applied** ones (waiting for the source to report ok; **Withdraw** a fix that did not work: the change stays in the module, and the Radar scout may propose another one), **recovered** ones, and the **rejected or withdrawn** ones, most recent first.
- The **Source health** window adds one line to a failing or retrying source with an open repair: "A fix is proposed", "A fix is approved; waiting for the builder to apply it" or "A fix is applied; waiting for the source to report ok".
- Coverage tells the analyst in plain words: "ZENUX is fixing 2 sources." (`GET /modules`, `repairs_open`).

Writes need the owner token like every Control room write (under open access everyone is the builder). A hub older than schema 9 has no `GET /repairs`: the section says so in one line until the hub is deployed.

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

- Every change answers with a toast that says what changed and when it takes effect, from the hub's `effective` answer: "Applies from the 12:30 PM briefing.", "Applies from tomorrow's 7:30 AM briefing.", or "Takes effect once you approve the wording in My preferences."
- When the hub can reverse a change, a slim bar at the top of the page offers **Undo** (and **Dismiss**) until your next change, or for 10 minutes; setting a suggestion aside can be undone too. Changes with no reverse route (Should have been in, a rating, Wrong facts, a suggested change, sign-off) say so where it matters.
- Destructive or consequential actions ask first in a dialog: removing a preference, unmuting, every mute (its dialog is also the preview of what it would hide), signing off, switching the stage, rejecting a coverage proposal, ending a preference on a date.
- A failed read shows "Couldn't load ..." with a plain reason and **Try again**; the technical line is shown to the builder only, collapsed. A refused change says "Not saved: ..." in place (the dialog stays open) with the hub's own plain sentence ("This mute is not complete. The coverage area is missing."); the dashboard's guard against engine words stays as the last check, and puts its own words in place of a sentence that fails it.
- Nothing reruns on a timer while you type. Briefing checks every two minutes for a newer briefing (`GET /editions/latest`, the id only) and offers **Show it**; the Control room refreshes its own health panel.

## Deep links

The query string mirrors where you are, so a reload or a shared link lands on the same tab and object: `tab` (`briefing`, `filtered`, `preferences`, `coverage`, `control`), `ws` (with two or more workspaces), `edition` and `item` (Briefing), `view` (`near`, `all`, `same`, `muted`, `old`), `section` (`ok`, `active`, `looks_for`, `muted`, `watchlist`, `how_much`) and `pref` (`R-0012`), `module` (a coverage area) and `request` (a coverage request). For example `?tab=briefing&edition=12&item=1203` or `?tab=filtered&view=muted`. Invalid values are ignored. A link to the Control room while the builder is locked opens Briefing with a note. Inside the page, navigation uses buttons (a link reload would start a new session and lose the unlock).

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

The tests use `streamlit.testing.v1.AppTest` and a routed fake for `requests.get` and `requests.post` (`tests/helpers.py`), so nothing touches the network, and they never read a secrets file (the harness points Streamlit's secrets path at a file that does not exist; tests pass their secrets through `AppTest.secrets`). `helpers.hub_defaults()` routes every hub read to the v8 bodies in `tests/fixtures.py` (and `GET /repairs` to an empty v9 list); each view keeps extra bodies in its own `fixtures_<area>.py`. Every analyst tab is checked by the jargon guard (`AppCase.assert_plain`: no engine word anywhere a reader can see) and for leaked secrets (`assert_no_secrets`).

- the shell (`test_app_shell.py`, with the views stubbed): tabs and who sees them, sign in to edit, builder access and its fallbacks, deep links, the page-level error box, the unchanged masthead, logo, page icon, theme, footer, configuration states and the workspace switcher
- `test_ui.py`: toasts, the undo bar, dialogs, confirmations, locked buttons, plain errors, `effective_text` (with the DST change)
- `test_status.py`: the status line (from `GET /status`) and the new-briefing banner (from `GET /editions/latest`)
- `test_units.py` and `test_owner_pin.py`: config with the builder PIN, sign-in state, the PIN guard, every hub wrapper, labels, links, formatting and the 12 px floor
- `test_app_errors.py`: each tab's error box, malformed payloads, secrets in URLs and on the page
- each tab's own tests: `test_app_briefing.py`, `test_actions.py`, `test_app_filtered.py`, `test_app_preferences.py`, `test_app_brief.py`, `test_app_coverage.py`, `test_app_requests.py`, `test_app_control_room.py`, `test_app_repairs.py` (source repairs, the Source health window's line and Coverage's line, with `fixtures_repairs.py`) and their `test_units_<area>.py`

## Deploy to Streamlit Community Cloud

The app must never be public while it holds secrets. Reads use the hub's `read_token` on the server, so anyone who can open the app can read the feed, and anyone who can open it can also try PINs. So deploy it **without secrets** first, make it private, and only then add the secrets. With no secrets the app shows "No Zenux workspace is configured" and makes no requests, so there is nothing to see while it is briefly reachable.

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
| `zenux_dashboard/feed_view.py`, `actions.py` | Briefing, and the card actions shared by every tab |
| `zenux_dashboard/filtered_view.py` | Filtered out |
| `zenux_dashboard/preferences_view.py`, `brief_view.py` | My preferences, and What ZENUX looks for with the sign-off |
| `zenux_dashboard/coverage_view.py`, `radar_view.py` | Coverage, and coverage requests (the analyst's part and the builder's review) |
| `zenux_dashboard/control_view.py`, `repairs_view.py` | The Control room, and its review of source repairs |
| `.streamlit/config.toml`, `.streamlit/secrets.example.toml` | Theme and the secrets template (committed) |
| `tests/` | AppTest and unit tests |

## Hub contract

The dashboard reads fields tolerantly: a missing field is left out of the display, never guessed. The shapes are in `docs/SPEC-PHASE02.md` section 5 (schema v8), `docs/SPEC-PHASE05.md` (the WF5 reads and plain fields: `/status`, `/editions/<id>`, `/editions/latest`, `/editions/search`, `/mutes/bring-back-preview`, the views of `/rejected`, `plain_text`, `rationale_plain`, `proposal_plain`, `preview_items`, `briefing_7d` ...) and `docs/SPEC-PHASE01.md` 4.6 (diagnostics, the Control room's read), and `docs/SPEC-REPAIR-PHASE-B.md` 1.2 and 1.4 (schema v9: `/repairs`, the repair object, `repairs_open` on `/modules`); `docs/SPEC-PHASE03-UI.md` describes the screens and section 10 lists the API gaps and which are closed. Every hub refusal is `{error, message, ...}`: the dashboard shows `message` (one plain sentence) and keeps `error` and the HTTP status for the builder. Every write answer carries `effective` (`{applies_from, next_briefing_at, timezone}`), which the toasts turn into "Applies from the ... briefing." Approvals send the `proposed_at` of the proposal shown, and a sign-off sends the versions of the page shown, so nothing you have not seen is ever approved.
