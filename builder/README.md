# Dashboard builder

Describe a dashboard in words; get a validated dashboard spec (the YAML of [`docs/dashboards.md`](../docs/dashboards.md)) that the renderer draws at `/d/draft`.

```
prompt ──> model (Claude, or the rule-based stand-in) ──> submit_dashboard(YAML) ──> dashspec checks ──> compiled spec
                 ^                                                                      │ problems
                 └──────────────────────── fixed and resubmitted (at most 3 times) ────┘
```

## What the model is given, and what it is not
- **Given:** the request, the spec format, and the **semantic layer as the signed-in role may read it**: every cube, measure and dimension with its type and
  its description (`docs/semantic-layer.md` is the same information for people). Descriptions live in `cube/model/cubes/*.yml`; a test fails when a
  member has none. A composed, valid example for that role is included.
- **Never given:** data rows, other roles' members (a rep's catalog has no profit members and no inventory; marketing's has no supplier members), secrets.
- **What leaves your network in LLM mode:** the request text and the member names and descriptions above, to the Anthropic API. Demo data only until
  InfoSec has approved real data.

## Why the result is safe to show
1. The service, not the model, sets the dashboard's `id` and `roles` (to the caller's role) and removes a logo (a draft cannot load images).
2. `dashspec` validates every submission: schema, members, joins, click rules, and **Cube's role rules** (a rep's page cannot contain a profit member).
3. Whatever is built, Cube enforces row-level security and role limits on every query the page sends, with the user's own token.
4. The model cannot approximate a missing metric: it must call `cannot_build` and say what is missing.

Operating it, the limits, what is logged and what leaves the network: **[docs/builder.md](../docs/builder.md)**. How to check a real model: [`evals.md`](evals.md).

## Two models, one loop
- **Claude** (`ANTHROPIC_API_KEY` set; `BUILDER_MODEL`, default `claude-opus-5-5`): reads free text, edits a dashboard in conversation. Not yet run against the real
  API in this repository (no key was available): the loop, the prompts and the checks are tested with a scripted model.
- **The rule-based stand-in** (no key): keywords in English and Turkish for measures, a time axis with a drill-down (year, quarter, month, day), a chart per channel, column / line / area
  styles, pie and donut, breakdowns (region, country, category, product), top N, a table, a treemap, filters, clicks, language, and edits (chart style, columns, top N, split a chart per
  channel, add or remove a panel). It says what it understood and what it did not. It is not an LLM and says so (`mode: standin`); it exists so everything else runs, and is tested on every prompt x every role.

## The page
On `/d/` (the dashboards list) a **Describe a dashboard** box: type a request or click an example that fits your role, press Build, and the result is drawn at
`/d/draft` with the same renderer as every other dashboard (so its numbers come from Cube with your own token). The page says plainly whether a language
model or the rule-based stand-in answered. On a draft:
- **Change this dashboard**: ask for a change in words ("make the chart a line", "show the top 3", "add a table"); the model gets the current file.
- **YAML**: the whole file, editable; Apply checks it for your role (`POST /validate`) and draws it, or lists the problems and changes nothing.
- **Semantic layer**: every cube, measure and dimension your role may read, with what it means and what it joins to; search, and click a name to copy it
  (and insert it at the cursor of an open YAML). The same browser is on `/d/` before you build anything.
- **Download YAML** and **Save draft** (kept in this browser, up to 10). A draft only lives in your browser; to keep a dashboard for everyone, download the
  YAML, put it in `dashboards/`, run `scripts/dashspec build` and open a pull request (the [guide](../docs/dashboards.md)).

![A draft built from a request](../docs/images/dashboards/builder.png)

Anything the model writes is shown as text, never as HTML; links in text panels and a logo are removed from drafts.

## Service
`docker compose --profile starrocks up -d --build builder` (port `BUILDER_PORT`, default 8350; `.env.example` has the settings).

| Endpoint | |
|---|---|
| `GET /info` | the mode, the model, the caller's role |
| `GET /catalog` | the semantic layer for the caller's role (cubes, members, descriptions, joins, who else can read each) |
| `POST /build` `{ prompt, current_yaml? }` | `{ status: ok \| cannot \| failed, yaml, spec, message, notes, attempts, mode, model, usage }` |

Every call needs a Keycloak access token of the `dashboard` client. Each user may build `BUILDER_RATE_LIMIT` (20) times an hour; each build writes one log
line (who, role, mode, status, attempts, tokens, the first 160 characters of the prompt).

## Try it without the service
```bash
PYTHONPATH=dashboards:. uv run --with pyyaml --with 'jsonschema>=4.18' python -m builder.cli "monthly revenue by channel, top 5 products" --role rep
PYTHONPATH=dashboards:. ... python -m builder.cli "make the chart a line" --current dashboards/regional-sales.yml
```

## Tests
`PYTHONPATH=dashboards:. uv run --with pytest --with pyyaml --with 'jsonschema>=4.18' --with fastapi --with httpx --with 'pyjwt[crypto]' --with pydantic --with anthropic python -m pytest builder/tests -q`
(CI job `builder`).
