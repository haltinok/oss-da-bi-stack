# Spike results: StarRocks + Cube + row-level security behind the AdventureWorks dashboard

Branch `spike/starrocks-cube`. Plan: [`../starrocks-cube-spike.md`](../starrocks-cube-spike.md). How to run it: [`README.md`](README.md).

**Setup.** One workstation (8 cores, 62 GB RAM, NVMe), everything in Docker, all free/open source: StarRocks 3.3 (allin1, 40 GB limit), Cube 1.8 + Cube Store, Keycloak 26 (dev mode), FastAPI auth service, nginx, dbt-starrocks 1.12, ingestr 1.1. Source: SQL Server 2022 with AdventureWorks2016 on a second machine, scaled **inside StarRocks** (121k order lines to 10M / 100M / 500M).

## Verdict

**Conditional go, for a bounded pilot, not for a Power BI replacement claim yet.**

The stack does what the spike set out to prove: at 500M order lines, with pre-aggregations, every dashboard panel answers in under 500 ms at p95, row-level security holds under every attack the test suite could think of, and the existing dashboard code runs on it with a one-line hook. Without pre-aggregations it does not: the same queries take 2 to 92 seconds at 500M. So the architecture works only if someone designs and owns the rollups, and that is where the real cost sits. Details and the conditions for a pilot are at the end.

## Pass / fail

| Area | Criterion | Result | Notes |
|---|---|---|---|
| Ingestion | Inserts and updates show up after an incremental run; deletes detected by reconciliation | **Pass** | 10 new + 20 updated orders arrived with no duplicates; 10 hard-deleted orders (21 lines) flagged exactly by the primary-key reconciliation. Deletes are invisible to a merge load, so the reconciliation is mandatory. Run on a copy of the database, never the original. |
| Correctness | Cube totals match direct SQL to the cent, incl. the multi-fact query | **Pass, with a caveat** | 11/11 checks match at 500M, including internet + reseller revenue by category. Cube Store appears to keep 5 decimals per rollup row, so a sum over thousands of cells can drift ~0.001 and round to a different cent (seen once, on 2,353,809,246.575). Totals agree to within 1 cent, not always to the cent. |
| Performance, raw | p95 < 3 s on the 500M fact **without** pre-aggs | **Fail** | 4 of 10 dashboard queries pass; the other 6 take 3.1 s to 92 s (table below). |
| Performance, served | p95 < 500 ms with pre-aggs, 10 concurrent users | **Pass** | All 9 rollup-served queries p95 ≤ 463 ms at 500M. 10 concurrent users, all three roles mixed, row-level security on: p50 38 ms, p95 213 ms, 0 errors. 25 users: p95 660 ms at 20 requests/s. One dashboard view is not rollup-served (see findings). |
| RLS | Each user sees only their territories in every visual; tampering cannot widen access | **Pass** | 29 pytest tests + a browser test per role. One real hole was found by the tests and fixed (ordering by a hidden measure). |
| Ops | Whole stack comes up with one `docker compose up` | **Partial** | The services do. Loading data, building the marts and the first rollup build are separate scripted steps (see README). The first rollup build at 500M was long (hours, for the first, much heavier design); it was not re-timed from scratch for the final model, whose changed rollups rebuilt in ~10 minutes. |

## Performance

p95 per dashboard query, worst of the internet and reseller channels. "Rollup" = the query as the dashboard sends it; "direct" = the same query with a filter no rollup carries, so StarRocks answers it. Each run is distinct SQL (a varied limit / dummy filter value), so Cube's result cache never answers. Rollup: 15 runs; direct: 3 runs at 10M/100M and 2 at 500M, so a direct p95 is close to its max. The machine was otherwise idle.

| Query (dashboard panel) | Rollup 10M | 100M | **500M** | Direct 10M | 100M | **500M** |
|---|---|---|---|---|---|---|
| KPI tiles | 98 ms | 237 ms | **306 ms** | 197 ms | 2.4 s | **16.9 s** |
| KPI tiles, fiscal year (+ prior year) | 101 ms | 316 ms | **289 ms** | 92 ms | 315 ms | **2.4 s** |
| Monthly series | 77 ms | 213 ms | **249 ms** | 973 ms | 19.3 s | **92.3 s** |
| Monthly series, fiscal year | 261 ms | 363 ms | **452 ms** | 143 ms | 1.8 s | **7.8 s** |
| Product mix (category x subcategory), FY | 61 ms | 261 ms | **177 ms** | 136 ms | 1.2 s | **7.6 s** |
| Top 10 products, FY | 164 ms | 311 ms | **440 ms** | 105 ms | 295 ms | **1.9 s** |
| Territories (group x region), FY | 113 ms | 119 ms | **333 ms** | 83 ms | 275 ms | **2.1 s** |
| Monthly, region cross-filter | 93 ms | 102 ms | **463 ms** | 308 ms | 3.0 s | **25.2 s** |
| Product mix, FY + region | 72 ms | 91 ms | **202 ms** | 102 ms | 140 ms | **2.5 s** |
| Territories, FY + product-category filter | 257 ms | 528 ms | 3.5 s (not served by a rollup) | 177 ms | 391 ms | 3.1 s |

Reading it:
- **At 10M rows a rollup buys nothing.** StarRocks answers most of these in 100-300 ms on its own, and an early run with a month-partitioned rollup was slower than StarRocks for several queries. Pre-aggregation starts paying at ~100M and is decisive at 500M.
- **The expensive shapes are whole-table aggregations** (KPI totals, monthly series, region cross-filters). Filtering by fiscal year makes StarRocks fast on its own because it prunes partitions.
- A full dashboard page load in the browser (a dozen queries in parallel, signed in through Keycloak), with panels now drawing as they arrive, had every panel drawn in 5.9 s for the admin, 4.6 s for `na_manager` and 7.0 s for `de_rep` (including the Keycloak round trips).

### Concurrent users (500M, rollups, row-level security on)

Virtual users sign in through Keycloak and the auth service as admin / `na_manager` / `de_rep` (round robin) and loop over the dashboard's panel queries with 0.5-1.5 s think time, 90 s per level.

| Users | Requests | Errors | req/s | p50 | p95 | p99 | Served by a rollup | StarRocks CPU (avg) | Cube Store CPU (avg) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 82 | 0 | 0.9 | 40 ms | 195 ms | 419 ms | 100% | 114% | 4% |
| 10 | 832 | 0 | 9.1 | 38 ms | 213 ms | 338 ms | 96.6% | 135% | 26% |
| 25 | 1,840 | 0 | 20.1 | 83 ms | 660 ms | 1.07 s | 96.7% | 255% | 76% |

StarRocks memory peaked at ~10 GB. The ~3% of requests not served by a rollup are most likely the exact orders-per-category query for the multi-region manager (not broken down further). The raw files for the earlier design (v1, count-distinct rollups) are kept in `bench/` for comparison.

## What we learned (gotchas to carry into any real project)

**StarRocks**
- **Memory is the constraint.** The 16 GB container in the spec ran out of memory on a `count(distinct)` over 100M+ rows and on any wide window function. 32-40 GB was needed for the 500M tier, and even then the two facts must be built one at a time (`--threads 1`) with spill-to-disk enabled (`enable_spill`). Each 500M fact took about 22 minutes to build.
- A `row_number()` over the full joined row ran StarRocks out of memory at 10M rows; numbering over a two-column subquery and joining back fixed it.
- The default 300 s query timeout kills the larger builds (`SET GLOBAL query_timeout`).
- Table-level grants disappear when dbt drops and recreates a table, so read-only grants are re-applied from an `on-run-end` hook.
- The all-in-one image hands Stream Load clients `127.0.0.1:8040` as the backend address, so ingestr must run inside the StarRocks container's network namespace.

**dbt-starrocks 1.12**
- **`dbt snapshot` does not work**: the adapter's merge issues a MySQL multi-table `UPDATE` that StarRocks rejects, and the snapshot table is duplicate-key. We replaced it with an insert-only version log plus a `lead()` view (tested: price change gives two versions, one closed, one current).
- It needs `mysql-connector-python==8.4.0`; newer releases fail with "server_version has no setter".
- Key columns must lead the table in `CREATE TABLE AS`; the existing Postgres models needed `distinct on`, `to_char`, `generate_series` and quoting ported.

**Cube + Cube Store**
- **The stock MySQL dialect defeats StarRocks partition pruning** (it wraps the date column in `CONVERT_TZ`): every monthly rollup partition scanned all 122 fact partitions. Overriding the dialect in `cube.js` brings it to 1 of 122.
- **Non-additive measures are the hard part.** A `count_distinct` can be served from a rollup only when the query's dimensions (including filtered ones) match the rollup's exactly, and not at all when the filter is an `IN` list. That made every order-count query for the multi-region manager a full scan. We first built 20 count-distinct rollups per fact to cover the dashboard's grains, which took hours and loaded StarRocks constantly. The fix was a modeling change: count each order once, on its first line (`orders_placed`). That is exact and additive for any grouping or filter on order-level attributes (date, territory, channel, status), so a single plain rollup serves KPIs, monthly series, territories and multi-region security filters. It is wrong when products are involved (an order has several categories), so the exact distinct count is used there, and only a direct scan or a rollup at that exact grain can answer it. This is a trade-off the BI team has to understand and maintain.
- **Partition granularity matters more than data volume for served latency.** Month-partitioned rollups answered the monthly series in 1.3-2.5 s (a query touches all 122 partitions); the same rollups partitioned by year answer in 80-330 ms.
- **Refresh is not free.** Cube's scheduler cycled for ~8 minutes even when little had changed; with 20+ rollups per fact StarRocks sat at ~5 cores continuously. With three rollups per fact plus four whole-period mix rollups it idles at 3-8% CPU. `update_window` accepts seconds to weeks only (not months or years), `refresh_key` changes and restarts discard in-flight long builds, and the default 10-minute query timeout is too short for whole-table distinct counts (`CUBEJS_DB_QUERY_TIMEOUT`).
- **Cube cannot join two fact cubes in a view**; multi-fact queries work over shared dimensions, so the dashboard fetches each channel separately and merges in the browser.
- Cube Store appears to keep 5 decimals per rollup row (see Correctness). Concurrency must be capped (`CUBEJS_CONCURRENCY`) or several concurrent 500M scans overload StarRocks.
- Cube dev mode does not enforce the default token check (per Cube's source) and returns stack traces in error bodies. Run it in production mode; pin `CUBEJS_PRE_AGGREGATIONS_SCHEMA` if you switch, or every rollup rebuilds.

**Security**
- Row-level security lives in `cube.js` (`checkAuth` + `queryRewrite`), custom JavaScript the team owns, not a configured feature. The filter is added to every query that touches a fact or the territory cube, and ANDed with the client's own filters, so asking for another region, an `or` filter or a `notEquals` returns nothing.
- **The tests caught a hole:** a rep could order a query by `gross_profit` without selecting it and get a 200. The profit check now covers `order`, `segments` and nested filters.
- Auth failures are a generic 401 and policy denials a generic 403 (a thrown plain `Error` is a 500 with a stack trace; use Cube's `CubejsHandlerError`).
- Cube's SQL API port bypasses the REST layer, so it is not published on the host (we did not test whether `queryRewrite` covers it).
- StarRocks users for Cube and the auth service are read-only (`cube_ro`, `auth_ro`). The SQL Server login used for the spike is a sysadmin, which is far more than ingestr needs; a real deployment needs a read-only source login.
- `dashboard` Keycloak client allows direct password grants only so the tests can log in headlessly; the browser uses authorization code + PKCE.

**Dashboard**
- The existing `dashboard/static/app.js` changed by a data-source hook in `getJSON()` plus null-safe handling of profit figures (reps never receive profit, so tiles, columns and the margin chart are hidden). The Cube adapter, sign-in and nginx injection live in `spike/dashboard/`; the legacy Postgres server and page are unaffected.
- **Panels render independently, as their query returns.** Each panel (KPIs, monthly trend, product mix, top products, territories, latest orders) runs its own query and redraws when it is ready; waiting panels are dimmed on their own, and a filter change cancels the in-flight requests (measured: 8-14 requests cancelled per change, no error). The one figure that cannot be quick is the **exact order count under a product filter** (a distinct count over a product subset; no rollup can serve it). Those panels draw at once without it, the Orders and Avg-order-value tiles show "…", and the figure fills in later from two scans (one per channel) instead of eight. Measured as admin with a subcategory filter: panels 1-8 s, exact orders 8-61 s depending on how warm StarRocks is; as the multi-region manager on a cold subcategory: panels 2.7-4.1 s, latest orders 7.9 s, exact orders 20 s, with Cube's concurrency at 6 (at 4, the fast "latest orders" queries sat behind the slow scans for ~100 s). A background refresh no longer cancels a load that is still running.
- The product-mix table's Orders column is the same exact count (a late stage); it is served by rollups for admin and single-territory users, and by a scan otherwise.

## Not done / not proven

- **The real source.** The 500M tier is AdventureWorks multiplied inside StarRocks, not data loaded from a 600 GB SQL Server. Ingestion throughput, the primary-key reconciliation cost at scale, row width, skew and real cardinalities are untested. The 500M rows here occupy ~12.5 GB in StarRocks; a client's rows are probably wider.
- **Realistic security rules.** The spike has three roles and a territory list. Power BI RLS in a bank is often dynamic, hierarchical or many-to-many; each such rule is custom code here.
- **Production hardening:** Keycloak in production mode with the bank's identity provider, TLS, StarRocks and Cube Store high availability, backups, monitoring, secrets management.
- **Freshness.** Rollups were built once on static data. A live feed needs the incremental refresh and the `daily` rollup validated under writes.
- **ClickHouse side-by-side** (optional in the plan) was not run.
- **Dashboard parity.** Only the existing dashboard was re-pointed. Power BI features (self-service, drill-through, subscriptions, exports) are a separate gap.

## Recommendation

A pilot is justified if the client accepts these conditions, and not otherwise:

1. **A named owner for the semantic layer and rollups.** The performance result is entirely dependent on rollups designed for the dashboard's grains, and on understanding trade-offs like `orders_placed`. A new panel or a new cross-filter can fall off a rollup and cost 10-90 s at this size.
2. **Size StarRocks for the data, not the demo:** 40+ GB of RAM for the 500M tier, spill enabled, one heavy build at a time. Re-measure with the client's real row width.
3. **Treat the security layer as code under review.** It passed 29 tests and a browser test per role, and the testing still found a hole. Any real rule set needs the same suite written for it, and a security review.
4. **Budget the data path.** Ingest, reconciliation for deletes, dbt on StarRocks (snapshots must be redone) and rollup rebuilds are each real work.
5. **Pilot on one dashboard with the real 600 GB source first**, with a go/no-go on freshness and on the cost of the first full rollup build, before anything is positioned against Power BI.

What the spike does support, if asked for a one-line answer: the open-source stack can serve a 500M-row, role-secured dashboard in well under a second on one workstation. What it does not show is that it is cheaper or less risky to run than Power BI for this client; that is the pilot's question.
