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
- **What they see:** the same as on a dashboard. A rep cannot reach profit or margin; a manager cannot reach customers or inventory; territories limit every number to the person's regions; cubes in a dataset they have no grant on are refused. This is not re-implemented in the lab:
  the statement is sent to Cube's SQL API signed in as the person with their own Cube token as the password, and Cube applies `queryRewrite` to it like any other query. Warehouse tables behind the cubes are not reachable at all (Cube only knows the cubes).
- A change to someone's grants or rules shows at their next token (15 minutes by default).

## Export
**CSV** and **Excel** buttons appear under a result. The statement runs again as an export, under the same gate, rules, time limit and audit (`event: lab_export`), and may return more rows than the grid shows: up to **100,000** (`LAB_EXPORT_ROWS`);
the page says when the file was cut. CSV is UTF-8 with a byte-order mark (Excel reads Turkish letters right). **Nothing in a cell is run as a formula:** in CSV a text that starts with `=`, `+`, `-` or `@` gets a leading apostrophe, and in Excel every
non-number is written as text. Numbers stay numbers.

## Limits
At most **10,000 rows** per query on screen (100,000 in an export) (the grid says when a result was cut), **60 seconds**, **2 queries at a time** per person, 8 across the lab, 20,000 characters. Each statement writes one audit line (`event: lab`: who, role, the statement, rows, time, error) to the service's stdout.
Settings: `LAB_ROW_LIMIT`, `LAB_TIMEOUT`, `LAB_MAX_PER_USER`, `LAB_MAX_CONCURRENT` in `.env`.

## Running it
`docker compose --profile starrocks up -d --build lab cube` (Cube reads its SQL API settings at start: `CUBEJS_PG_SQL_PORT` is on the compose network only and is never published). Behind Caddy the service is `/lab-api/*` and the page `/lab/`.
For an existing install: run `postgres/sync-access.sh` once (the lab permission widens the grants table), rebuild `auth`, `admin`, `lab`, `dashboard-cube`, and restart `cube`.
