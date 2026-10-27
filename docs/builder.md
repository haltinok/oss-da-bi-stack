# The dashboard builder: operating and trusting it

Describe a dashboard in words on `/d/`; get a draft at `/d/draft` that you can change, edit as YAML, download or save. This page is for whoever runs it and
whoever has to decide whether to trust it. The user's view is in [`builder/README.md`](../builder/README.md) and [`dashboards.md`](dashboards.md).

## What it is, in one picture
```
 browser ── Keycloak token ──> builder service ── request + the catalog this role may read ──> model (Claude, or the rule-based stand-in)
    ^                              │  checks every answer with dashspec (schema, members, joins, click rules, Cube's role rules)
    │                              │  problems go back to the model, at most 3 tries
    └──── validated dashboard spec ┘
 browser ── user's own Cube token ──> Cube (row-level security, role limits) ──> data        (the builder is not in this path)
```
The builder only ever produces a **spec**: YAML that names Cube members. It never queries data, never writes SQL and never sees a row. The finished dashboard
reads data like every other dashboard: from Cube, with the signed-in user's own token.

## Which model: Claude, DeepSeek, or another compatible server
The service talks to any model API that speaks the Anthropic Messages format, through the same SDK and the same loop and checks (`builder/provider.py`):
| You want | Set in `.env` |
|---|---|
| Claude (default; `BUILDER_MODEL` defaults to `claude-opus-5-5`) | `ANTHROPIC_API_KEY=...` |
| **DeepSeek** (cheaper) | `BUILDER_PROVIDER=deepseek`, `DEEPSEEK_API_KEY=...`; the model defaults to `deepseek-flash` (its cheap one), `BUILDER_MODEL=deepseek-v4-pro` for its strongest |
| Another compatible server, for example a gateway to an open model you host | `ANTHROPIC_BASE_URL=https://host/anthropic`, `ANTHROPIC_API_KEY=...`, `BUILDER_MODEL=...` |
then `docker compose --profile starrocks up -d --no-deps builder`. The page shows who reads the request (for example "DeepSeek, deepseek-flash"). To another provider than Anthropic the
service sends the plainest request: the system prompt as one string, no cache markers and no effort setting (Anthropic features a compatible endpoint may reject).
DeepSeek's endpoint is documented at <https://api-docs.deepseek.com/guides/anthropic_api>; its model names change, so check them there.

**The model reads the dashboard spec.** The prompt carries the field reference generated from the schema (the same table as [dashboard-spec-reference.md](dashboard-spec-reference.md): every
field, type, whether required, and what it means), the validator's rules, a cheat sheet, two complete examples that are valid for the user's role (one with a drill-down and a pie
with Turkish labels) and the role's catalog: roughly 6,000-8,000 tokens in and 1,000-3,000 out per build. That is the price of a cheaper model being able to write a valid file;
`BUILDER_SPEC_REFERENCE=0` leaves the reference out (about a third smaller) if a model copes without it. A model that wraps the YAML in a code fence is tolerated.
**None of the three has been run against its real API here** (no keys); the wire format is tested against a fake compatible server through the real SDK.

**Where the provider is:** Anthropic's API and DeepSeek's hosted API are outside your network. DeepSeek is operated from China; the request text and the catalog (names and descriptions, never
data) would go there. For a bank that needs InfoSec's approval like any external service; a model you host yourself behind a compatible gateway keeps everything inside.

## What leaves your network (LLM mode only)
| Sent to the Anthropic API | Never sent |
|---|---|
| The request text (and, when changing a draft, the current YAML) | Data rows, figures, customer or product values |
| The spec format guide, and one valid example composed for the user's role | Other roles' catalogs: a rep's catalog has no profit members and no inventory |
| The catalog the role may read: cube, measure and dimension **names, types and descriptions**, and which cubes join | Tokens, passwords, the API key of anyone else, anything from `.env` except the key itself |

Member names and descriptions describe the bank's data model, so **demo data only until InfoSec has approved real data** ([`SECURITY.md`](../SECURITY.md)). Without
`ANTHROPIC_API_KEY` nothing leaves: the rule-based stand-in runs inside the service.

## Why a draft is safe to show
1. **Role.** The service takes the role from the Keycloak token, sets the draft's `roles` to it (whatever the model wrote), and the validator refuses every member that
   role cannot read (the same rules as `cube/cube.js`; a test keeps them equal). Cube enforces them again on every query.
2. **Row-level security** is Cube's and is untouched: a rep's draft shows that rep's territories, whatever the model asked for.
3. **Validation.** Nothing is returned that dashspec has not accepted: wrong members, joins Cube cannot do, impossible click rules, bad layouts all go back to the model.
4. **No invented metrics.** The model must call `cannot_build` for a metric the catalog lacks; the validator rejects a member that does not exist.
5. **Output is text, not markup.** Everything the model writes is escaped when shown; links in text panels and a logo are removed from drafts, so a draft cannot point
   readers at another site or load an image.
6. **A draft lives in the browser** (localStorage) until a person saves it to the server (below) or downloads it and sends it through a pull request.

What it does **not** protect against: a model that writes a *wrong but valid* dashboard (the numbers are right, the choice of chart or measure may not be what you
meant: you see it and can ask for changes), and a person pasting sensitive text into the request (it is sent in LLM mode and kept, truncated, in the log).

## Limits
| Limit | Default | Setting | What the user sees |
|---|---|---|---|
| Builds per user per hour | 20 | `BUILDER_RATE_LIMIT` | "You can build 20 dashboards an hour; try again in N minutes." and "Builds left this hour" in the box |
| Model tokens per user per UTC day | 300,000 | `BUILDER_DAILY_TOKENS` | "Today's model budget is used up; it resets at midnight UTC." (in memory: a restart resets it) |
| Builds running at once | 4 | `BUILDER_MAX_CONCURRENT` | "The builder is busy…" (503); a refused request does not count against the user |
| Model call timeout | 120 s | `BUILDER_TIMEOUT` | "The dashboard could not be built: the model took too long." |
| Attempts per request | 3 failed submissions | `BUILDER_MAX_ATTEMPTS` | "The dashboard could not be made valid after 3 tries." with the validator's problems |
| Request size | 2,000 characters; YAML 30,000 | fixed | a 422 |
A build is roughly 6-9k input tokens (the format guide and the role's catalog; cached by the API after the first call) and 1-3k output tokens, so 20 builds an hour is a few
hundred thousand tokens at most. Control characters are stripped from the request. The API key is read from the environment only and is never logged or returned.

## Saved dashboards
A person can **Save…** a draft: it is stored in Postgres (schema `builder`, tables `saved_dashboards` and `saved_versions`) and opens at `/d/s/<id>`.
- **Private by default.** The owner can share with chosen roles or with everyone who is signed in, and change that later. A dashboard that is not shared with you
  looks like it does not exist (404). The one exception is the `admin` role, which can see (and share, rename or delete, not edit) every saved dashboard so it can
  moderate; say so to users, and keep that role small.
- **Role rules still apply to the viewer.** Opening re-validates the YAML for the *viewer's* role: a rep cannot open a dashboard that reads profit, and the list
  greys it out with the reason. The owner's share form shows which roles can open it. Cube's row-level security is untouched: a viewer sees their own territories.
- **Who can do what.** Only the owner changes the YAML, restores a version or sees versions; the owner or an admin changes the sharing, the title, or deletes. A
  viewer can *Save a copy* or *Edit a copy* (their own private copy).
- **Tags.** The Save dialog has a **Tags** field (chips; Enter or a comma adds one; at most 5), and the owner of a saved dashboard has a **Tags** button for changing them
  later. The page never edits YAML: the request carries `tags` (`POST /saved`, `PUT /saved/{id}`), the service writes them into the spec after its description and runs the
  same validator as for every other field, so a bad tag is refused with the usual message (`'Board' is not lower case; write 'board'`) before anything is stored. An untouched
  field sends nothing, so the YAML's own tags stand; the same tags again are not a change. Changing tags changes the YAML, so it is the owner's alone and a new version (an admin
  can rename and share, not retag). Tags are visible to everyone who can see the dashboard.
- **Versions.** Saving changed YAML makes version N+1 at the same address; the last 10 are kept; the owner can view or restore one (a restore is a new version).
- **Limits.** `BUILDER_MAX_SAVED` (50) dashboards per person; YAML up to 30,000 characters; title up to 120.
- **The login.** The service connects as `builder_app`, which can read and write only the two tables (it cannot create objects or touch other schemas). Saving is off, and
  the page says so, until `BUILDER_DB_PASSWORD` is set. A new database gets the schema from `postgres/init/02_builder_schema.sql` and `03_builder_user.sh`; on an
  existing volume run `postgres/sync-builder.sh` once (it is idempotent) and then `docker compose --profile starrocks up -d --no-deps builder`.
- **Backups.** The data is in the `postgres` service's volume: back it up like the rest of that database. Only the YAML and names are stored, never data rows.

## Logging and audit
One JSON line per build, to the container's stdout (`docker compose logs builder | grep '"event": "build"'`) and, if `BUILDER_LOG_FILE` is set, appended to that file:
`at`, `user`, `role`, `mode` (llm | standin), `status` (ok | cannot | failed | error), `attempts`, `seconds`, `usage` (tokens, turns), `refine`, and the first 160
characters of the request. Saving writes `event: saved | saved_update | saved_delete | saved_restore` lines (who, role, dashboard id, version, visibility; never the YAML). A model failure is logged as `status: error` with the kind of error only. `GET /usage` returns a user's own counters.

## Configuration (`.env`)
| Setting | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | set it to use Claude (or another compatible server with `ANTHROPIC_BASE_URL`); empty means the stand-in |
| `BUILDER_PROVIDER`, `DEEPSEEK_API_KEY` | `anthropic`, empty | `deepseek` uses DeepSeek's endpoint with its own key |
| `ANTHROPIC_BASE_URL` | empty | the address of an Anthropic-compatible server |
| `BUILDER_SPEC_REFERENCE` | `1` | `0` leaves the field reference out of the prompt |
| `BUILDER_MODE` | `auto` | `auto` (Claude when a key is set), `llm` (refuse to start a build without a key), `standin` |
| `BUILDER_MODEL` | `claude-opus-5-5` (`deepseek-flash` with DeepSeek) | the model |
| `BUILDER_EFFORT` | `medium` | the model's effort setting |
| `BUILDER_DB_PASSWORD`, `BUILDER_MAX_SAVED` | empty, `50` | the `builder_app` login that turns saving on; saved dashboards per person |
| `BUILDER_PORT` | `8350` | the published port (127.0.0.1); public deployments reach it at `/builder-api` through Caddy |
| the limits above, `BUILDER_LOG_FILE` | | |
To switch a running stack to Claude: add the key to `.env`, then `docker compose --profile starrocks up -d --no-deps builder`. The page says which one answered.

## The two models
- **A language model** (Claude, DeepSeek, …). Free text, edits in conversation. **Not yet run against a real API here** (no key was available): the loop, prompts, limits and error handling are tested with
  a scripted model. Before relying on it, run [`builder/evals.md`](../builder/evals.md) with a real key.
- **The rule-based stand-in.** Keywords in English and Turkish (measures, drill levels, chart styles, per-channel charts, breakdowns, top N, table, treemap, pie, a pivot ("by category and month", "heatmap", "crosstab": one measure, rows by a dimension or two, the fiscal year or months/quarters across, optional shading), filters, clicks, language),
  and edits (chart style, columns, top N, add or remove a panel, split a chart per channel). It says what it understood ("Understood: …") and, when it understood nothing
  of a change, says so and changes nothing. It is not an LLM and will miss phrasing it does not know; that is what Claude is for.

## When something is wrong
| Symptom | Cause |
|---|---|
| "The dashboard could not be built: the API key was rejected" | the key in `.env` is wrong or revoked |
| "… the model took too long" / "… not reachable right now" | the API timed out or is down; try again, or raise `BUILDER_TIMEOUT` |
| "The builder is busy" | more than `BUILDER_MAX_CONCURRENT` builds at once |
| 401 from `/builder-api` or the box shows an error | the Keycloak token expired (sign in again), or the public routing/issuer is wrong (`docker-compose.public.yml`) |
| "Cannot be built" with a reason | the role cannot read what was asked (profit for a rep), or a metric does not exist; the reason says which |
| "Could not be built" with problems | the model could not produce a valid file in 3 tries; the problems are the validator's |
| Nothing happens on Build | the service is down (`docker compose ps builder`) or `window.STACK.builder` is missing from `/cube/config.js` (the dashboard container needs `BUILDER_PORT`) |

## Extending it
A new panel type or spec field means: the schema and validator, the renderer, the query mirror (`dashboards/dashspec/queries.py`, compared with the page's JS by a test),
the model's format guide (`builder/core.py` `SPEC_GUIDE`), and, if the stand-in should know it, `builder/composer.py`. New members in the Cube model need descriptions (a test
fails without them) and show up in the catalog by themselves.

## Tests
`builder/tests` (loop with a scripted model, the stand-in over every request × every role, the HTTP service with signed tokens including limits, errors and the audit log;
CI job `builder`) and `dashboard/cube/tests/builderui.py` (the page against the mock stack, whose builder runs the real loop and stand-in).
