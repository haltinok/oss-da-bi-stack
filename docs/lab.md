# The SQL lab

Ask the data in SQL, at `/lab/` (the **SQL lab** card on the start page). It is for analysts who want rows and ad-hoc numbers rather than a dashboard, and it runs under **exactly the rules the dashboards run under**.

```
browser ── Keycloak token ──> lab service (lab/) ── same token ──> auth service ── Cube token (role, territories, blocked cubes, lab) ──┐
                                                                                                                                      │
                  Cube's SQL API (Postgres protocol), signed in as the person, the Cube token as the password  <─────────────────────────┘
                                   │  queryRewrite: role rules, row-level security by territory, blocked cubes  ->  StarRocks
```

## What you can write
Cubes are tables, **measures** are used with `MEASURE(name)`, **dimensions** are plain columns, and cubes are joined with `CROSS JOIN` (the model knows how they relate):

```sql
select category, measure(revenue) as revenue
from internet_sales cross join products
group by 1
order by 2 desc
```

`SELECT` and `WITH ... SELECT` only, one statement at a time. Row detail works too (`select order_number, order_date from internet_sales limit 50`), and `COUNT(*)` / `COUNT(DISTINCT dimension)`.
Other expressions over measures are not available: use the measure. The schema browser on the left lists the cubes and fields **you** may query; click a name to put it in the query.
The result grid sorts by column, and **Copy** puts it on the clipboard as tab-separated text (paste into Excel). Tabs and the history are kept in your browser.

## Who gets it, and what they see
- **Who:** admins always. Anyone else needs the **SQL lab** permission on a dataset: in the admin console (**Datasets**), tick *Also give the SQL lab* when adding a person, group or role to a dataset. A person with a grant on any dataset with the lab permission has the lab. Off by default.
- **What they see:** the same as on a dashboard. A field or cube kept back by a dataset (profit, customers, inventory, say) is refused; territories limit every number to the person's regions; cubes in a dataset they have no grant on are refused. This is not re-implemented in the lab:
  the statement is sent to Cube's SQL API signed in as the person with their own Cube token as the password, and Cube applies `queryRewrite` to it like any other query. Warehouse tables behind the cubes are not reachable at all (Cube only knows the cubes).
- A change to someone's grants or rules shows at their next token (15 minutes by default).

## Saved queries
**Save** keeps the query under a name; saved queries are listed on the left (yours, and those shared with you), grouped by the dashboards' folders. Open one to load it into a tab. **Share…** works like sharing a dashboard: named people and groups, *view* (see and run it) or
*edit* (also change the SQL and title), put it in a folder (the same folders as dashboards; a folder shared with someone shares what is in it), or hand it to someone else. Only the owner (or an admin) shares, moves, hands over or deletes it.

**Sharing a query shares the question, never the answer.** Running a saved query always runs it as *the person who runs it*, under their own rules (territories, role, blocked cubes), so the same query gives each person their own numbers.
The **last result** of a saved query is kept for the person who ran it (a snapshot, up to 10,000 rows, `LAB_SNAPSHOT_HOURS`, 24 by default, then it expires). It is that person's own copy: it is never shown to anyone else, whoever the query is shared with.
Opening a saved query shows your own last result without running anything; **Run** refreshes it. Queries and snapshots are kept in Postgres (schema `lab`); without `LAB_DB_PASSWORD` the lab runs but cannot save.
When an admin deletes a person in the console, their saved queries are handed to the admin first (with their dashboards).

**Not here, on purpose: materialized views.** The lab cannot create objects in the warehouse (it has no write access to it, which is what keeps it safe). A number that is slow and wanted by many belongs in the semantic layer: a Cube
**pre-aggregation** (already how the dashboards stay fast) or a dbt model. Snapshots cover the analyst's own "keep this result for a while".

## Export
**CSV** and **Excel** buttons appear under a result. The statement runs again as an export, under the same gate, rules, time limit and audit (`event: lab_export`), and may return more rows than the grid shows: up to **100,000** (`LAB_EXPORT_ROWS`);
the page says when the file was cut. CSV is UTF-8 with a byte-order mark (Excel reads Turkish letters right). **Nothing in a cell is run as a formula:** in CSV a text that starts with `=`, `+`, `-` or `@` gets a leading apostrophe, and in Excel every
non-number is written as text. Numbers stay numbers.

## Limits
At most **10,000 rows** per query on screen (100,000 in an export) (the grid says when a result was cut), **60 seconds**, **2 queries at a time** per person, 8 across the lab, 20,000 characters. Each statement writes one audit line (`event: lab`: who, role, the statement, rows, time, error) to the service's stdout.
Settings: `LAB_ROW_LIMIT`, `LAB_TIMEOUT`, `LAB_MAX_PER_USER`, `LAB_MAX_CONCURRENT` in `.env`.

## Running it
`docker compose --profile starrocks up -d --build lab cube` (Cube reads its SQL API settings at start: `CUBEJS_PG_SQL_PORT` is on the compose network only and is never published). Behind Caddy the service is `/lab-api/*` and the page `/lab/`.
For an existing install: run `postgres/sync-access.sh` once (the lab permission widens the grants table) and `postgres/sync-lab.sh` (saved queries; needs `LAB_DB_PASSWORD` in `.env`), rebuild `auth`, `admin`, `lab`, `dashboard-cube`, and restart `cube`.
