# ZENUX dashboard

The Zenux news-intelligence dashboard, built with Streamlit. It is a Zenux app, separate from the legacy PHYSAI news dashboard, and never talks to the legacy system. Its look is a black base with white accents: a full-width brand-green top bar (the ZENUX mark and wordmark, then the five tabs), dark cards with hairline borders, bold white headlines, coloured tags (violet for ai-infra, teal for defense-unmanned, a stable palette colour for any other module), and a green footer. The theme is in `.streamlit/config.toml`; `feed.css` carries the rest.

## Tabs

| Tab | What it shows | Hub routes |
| --- | --- | --- |
| **Feed** | Published editions, newest first. Each edition opens with its line (edition, age, time, items) and its one-sentence summary as the title (for an older edition without one, a sentence built from its items, such as "9 items across AI infrastructure (4) and defense unmanned (5), led by ..."). The latest edition is the hero: a LATEST pill, and on the right 2x2 tiles (items, reviewed, lead 90+, digest 70-89) over a bar that splits its items by module, with a legend. Each item card shows its source, its headline and its module tags, and opens to its factual text, metrics and sources. The Grader's grading note sits in a collapsed **Grading notes** expander at the bottom of its edition. Use **Search** to filter the loaded items, and **Load earlier editions** to page back. | `GET /editions?limit=10&before=` |
| **Rejected** | Graded events that did not make an edition: rejected, duplicate or already covered. Each shows its score, tier, reason code and the Grader's rationale. You can filter by window (1–14 days), module and decision. | `GET /rejected?days=N` |
| **Rules** | The learned layer of the rubric. Write a rule or a worked example, approve or reject the Zenux Rule refiner's proposal (editing it first if you like), and retire active rules. | `GET /rules`, `POST /rules/drafts`, `POST /rules/:id/{approve,reject,retire}` |
| **Radar** | Changes to what the workspace collects. Ask to track a source, report a missed story or ask for new coverage, then approve or reject the Zenux Radar scout's proposal. | `GET /radar`, `POST /radar/requests`, `POST /radar/:id/{approve,reject}` |
| **Diagnostics** | The control room, across every configured workspace (see below). | `GET /diagnostics`, `GET /snapshot`, `GET /sources`, module `/health` and `/backfill` |

### Diagnostics, from top to bottom

1. **Backfill.** Pick a workspace, a module, optional sources and a number of days (1–30), then press **Run backfill**.
   - The source list combines the sources the hub has seen from that module (`GET /sources?module=`) with any that the module's `/health` reports as failing or silent. You can also type a source key; the module refuses unknown ones.
   - The dashboard sends `POST <module>/backfill` with `{days, sources?}`, using that module's `run_token`.
   - While the job is queued or running, it polls `GET <module>/backfill` every 10 seconds and shows the progress. The module works through the sources on its scheduled runs.
2. **Live health**, refreshed every 60 seconds. There is one card per workspace, and **Refresh now** forces a fresh read. Each card combines the hub's `/diagnostics` with every module's public `/health`. It shows:
   - status pills
   - the last edition, the review backlog and the Grader lease
   - dead letters, and failing and silent sources
   - a module table with each module's status, last run, events in the last 24 hours and 7 days, failing and silent counts, and backfill state
   - expandable tables of failing sources, silent sources and recent dead letters
3. **Module snapshot.** For each module: event counts by lane for the last 24 hours and 7 days, and its latest 20 events (`GET /snapshot?module=<id>&limit=20`).
4. **Configuration.** Shows which URLs and tokens are set, plus any configuration notes. It never shows a value.

## Owner actions and the PIN

Reads use each workspace's `read_token`. Writes need the owner PIN. Writes are:

- grades and feedback
- rule drafts and decisions
- radar requests and decisions
- backfills

Type the PIN under **Owner** (top right). The dashboard checks it against the workspace's `owner_pin` from the secrets. The comparison is constant-time: both values are hashed, then compared with `hmac.compare_digest`. A match unlocks that workspace's `owner_token`, which is then sent as the bearer token for hub writes. A backfill uses the module's `run_token` instead, behind the same PIN.

- The PIN stays in your browser session's widget state. It is never logged, cached or sent anywhere.
- A PIN unlocks only its own workspace.
- A PIN needs 8 or more characters. A placeholder from `secrets.example.toml` or this README (`REPLACE_WITH_...`, `...`, `<your PIN>`) counts as no PIN, because anyone can read it. In both cases owner writes stay off, and the Diagnostics tab's **Configuration** notes say why.
- Guessing is limited across the whole app, not per browser session. After 5 wrong PINs, every PIN for that workspace is refused for 1 minute, even the right one. Each further lockout doubles the wait, up to 1 hour, so a patient guesser gets about 5 tries an hour. The right PIN clears the count of misses, and misses are forgotten after a day without one. A wrong PIN also waits 1 second. A wrong PIN and a refused PIN show the same message, so the page never says whether a PIN typed during a lockout was right. A session that already unlocked stays unlocked. Workspaces that share a PIN share the limit.
- To grade items on the Feed and Rejected tabs, tick **Load grading controls** under **Owner**.
- An approval on the **Rules** or **Radar** tab names the proposal you saw (its `proposed_at`). If the Zenux Rule refiner or Radar scout proposed something newer after the page loaded, the hub refuses the approval (`409 proposal_changed`), nothing is approved, and the page reloads the list for you to review. **Approve as written** on a waiting draft sends your own words and kind, bound to "no proposal yet", so it can never activate wording you have not seen.

## Configuration (`st.secrets`)

Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml` and fill it in. Both paths are inside `dashboard/`, and `secrets.toml` is gitignored.

```toml
owner_pin = "..."                 # optional default PIN for every workspace

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
run_token = "..."                 # module RUN_TOKEN
```

- Add one `[[workspaces]]` table per analyst workspace. The workspace switcher and the control room then include it.
- URLs must use `https`. Plain `http` is accepted only for `localhost`, `127.0.0.1`, `[::1]` and `*.localhost`, for the local hub (`hub/dev-server.mjs`) or a `wrangler dev` Worker.
- A missing token turns off only the features that need it. The Diagnostics tab lists what is missing.
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

## Tests

```bash
dashboard/.venv/Scripts/python -m unittest discover -s dashboard/tests
```

The tests use `streamlit.testing.v1.AppTest` and a routed fake for `requests.get` and `requests.post`, so nothing touches the network. They cover:

- every tab
- the backfill flow (start, polling, finish, PIN gate, refusal)
- the health panel with two workspaces
- PIN gating, including a PIN for one workspace not unlocking another, the app-wide limit on wrong PINs, the wait after a wrong PIN, and placeholder and short PINs
- approvals bound to the proposal shown (`409 proposal_changed`)
- error and empty states
- that no token or PIN reaches the page, a URL or a query string

`python -m pytest dashboard/tests` also works if pytest is installed. It is deliberately not a requirement.

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
5. Only now, under **Settings**, then **Secrets**, paste the contents of your `secrets.toml`, with an `owner_pin` of 8 or more characters. Community Cloud restarts the app with the values.

To rotate a token or the PIN, edit the app's secrets. Community Cloud restarts the app with the new values. A restart also clears the PIN-guessing counters, so rotate the PIN if you suspect someone has been guessing.

## Files

| Path | Purpose |
| --- | --- |
| `streamlit_app.py` | Entry point: page config, masthead, navigation, Owner popover, view dispatch |
| `feed.css` | The design system: Roboto, the black base, the brand-green bars, cards, the hero, coloured pills, tables |
| `assets/zenux-mark.png`, `assets/zenux-favicon.png` | The logo mark (inlined into the top bar) and the browser-tab icon |
| `zenux_dashboard/config.py` | Parses and validates `st.secrets` into workspaces and modules |
| `zenux_dashboard/api.py` | `requests` client for the hub and module Workers (bearer tokens in headers only) |
| `zenux_dashboard/data.py` | Cached reads, plus the parallel health gather |
| `zenux_dashboard/owner.py` | PIN gate (`hmac.compare_digest`) and the app-wide limit on wrong PINs |
| `zenux_dashboard/fmt.py` | Time formatting, HTML escaping, safe links, pills and tables |
| `zenux_dashboard/{feed,rejected,rules,radar,diagnostics}_view.py` | The five tabs |
| `zenux_dashboard/grading.py` | Shared grade form (`POST /feedback`) |
| `.streamlit/config.toml`, `.streamlit/secrets.example.toml` | Theme and the secrets template (committed) |
| `tests/` | AppTest and unit tests |

## Hub contract (hub/src/brain.js)

The dashboard reads fields tolerantly: a missing field is left out of the display, never guessed. Below are the shapes it uses, as the hub returns them.

Reads:

- **`GET /editions?limit=10&before=<edition id>`**
  - `{editions: [...], next_before, has_more}`
  - each edition: `{id, run_id, published_at, item_count, candidate_count, backlog, note, summary, items}` (`summary` is null on editions published before it existed)
  - each item: `{id, rank, event_id, score, tier, headline, text, module, modules, story_id, metrics: [{label, value, source_url?}], sources: [{url, title?}], feedback: [...]}` (`modules`: every module the story draws on; the card falls back to `[module]`)
- **`GET /rejected?days=N`**: `{days, total, counts, items: [{event_id, decision, score, tier, reason_code, rationale, canonical_event_id, decided_at, title, url, module, source_key, lane, feedback}]}`
- **`GET /rules`**
  - `{precedents: [...], drafts: [...], counts}`
  - each precedent: `{id: "R-NNNN" | "I-NNNN", kind, text, status, origin, activated_at}`
  - each draft: `{id, kind, text, origin, context, status, proposal: {text, rationale, kind?}, proposed_at, precedent_id, decision_note}`
- **`GET /radar`**
  - `{requests: [{id, kind, text, url, module, status, proposal, proposed_at, decision_note}]}`
  - `status` is one of `queued`, `proposed`, `approved_pending_apply` or `rejected`
  - `proposal` is `{summary, sources: [module source configs], registry_changes: [...], notes}`
- **`GET /diagnostics`**
  - top level: `{status, modules: [...], dead_letters: {total, by_reason, recent}, review: {backlog, lease: {state, held, run_id, lease_expires_at}, last_run}, last_edition: {id, published_at, item_count}}`
  - each module: `{module_id, status, stale, retired, last_run, events: {last_24h: {lane: n}, last_7d: {lane: n}}, failing, silent, dead_letters}`
  - a module's `status` is one of `ok`, `partial`, `failed` or `no_runs`
- **`GET /sources?module=<id>`**: the hub's per-source health rows. The backfill picker uses each row's `source_key` and skips rows marked `retired`.
- **`GET /snapshot?module=<id>&limit=20`**: `{module, counts: {last_24h, last_7d}, events: [compact events]}`. Without `counts`, the dashboard falls back to that module's counts in `/diagnostics`.
- **Module `GET /health`**: the module SDK shape, plus `backfill`. The backfill picker also reads an optional `sources` list.
- **Module `GET /backfill`**: the current or last job, or 404 `no_backfill_job` when none exists.
- **Module `POST /backfill`** `{days, sources?}`: answers 202 with a new job, or 200 with the job already in flight, which is left unchanged.

Writes (bearer `OWNER_TOKEN` after the PIN):

- **`POST /feedback`**
  - body: `{item_id | edition_id + item_rank | event_id, verdict, score?, note?, scope}`
  - `verdict` is one of `lead`, `digest`, `watch`, `reject` or `factual_error`; `scope` is `item`, `case` or `rule`
  - answers `{id, draft_id}`. A rule or case grade also queues a draft for the Rule refiner.
- **`POST /rules/drafts`**: `{text, kind}`
- **`POST /rules/:id/approve`** `{text?, kind?, proposed_at}`, **`POST /rules/:id/reject`** `{note?}`, **`POST /rules/R-NNNN/retire`**
  - `proposed_at` is the draft's `proposed_at` exactly as `GET /rules` returned it (`null` when no proposal was shown). The hub answers `409 proposal_changed` and activates nothing when the draft's proposal is different.
  - **Approve as written** on a waiting draft sends `{text, kind, proposed_at: null}`: the owner's words and kind as shown.
- **`POST /radar/requests`**: `{kind, text, url?, module?}`
- **`POST /radar/:id/approve`** `{note?, proposed_at}` (bound the same way) and **`POST /radar/:id/reject`** `{note?}`

## Try it against a local hub

`hub/dev-server.mjs` serves the real hub Worker on `http://localhost:8787` over the locally collected events (`.local/<ws>/hub.sqlite`), with the workspace's tokens from `.local/<ws>/tokens.json`. It is never deployed.

```bash
node hub/dev-server.mjs pilot                       # leave it running; stop it with --stop or Ctrl+C
node deploy/streamlit-secrets.mjs pilot --local     # writes the pilot block of .streamlit/secrets.toml
dashboard/.venv/Scripts/python -m streamlit run dashboard/streamlit_app.py
node hub/dev-server.mjs pilot --stop
```

`--local` sets `hub_url = "http://localhost:8787"` and the read and owner tokens from the same `tokens.json`. No module Worker runs locally, so module URLs are placeholders on the reserved `.invalid` domain (marked as such in the file). Module health and backfill show those modules as unreachable; the hub's own view of each module (last runs, failing and silent sources, event counts) still shows. Pass `--module-url <id>=<url>` for a module you do run locally, for example with `wrangler dev`. Owner writes stay locked until you add your `owner_pin`. Run `node deploy/streamlit-secrets.mjs pilot` without `--local` after deploying to point the block at the Workers.

`brain/dev-hub.mjs` is a scratch alternative: an in-memory hub with synthetic events (`--seed`) and tokens taken from the environment.
