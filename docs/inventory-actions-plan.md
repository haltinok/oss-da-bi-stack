# Plan: from dashboard to decisions — stockouts, overstock, reorders and campaigns

Status: **plan, not started**. Written to be picked up and implemented with Claude Code, one phase per PR.

## Goal

Turn the StarRocks + Cube demo from "a fast dashboard on 250M rows" into something management acts on:

1. **Find** items that are out of stock or about to be (stockout risk) and items carrying too much stock (overstock, dead stock).
2. **Propose** a reorder quantity per at-risk item and a campaign (discount tier) per overstocked item, with the reasoning visible.
3. **Act**: approve a proposal and have it written back to the simulated ERP (`postgres_active`) as a purchase order, work order or special offer, then flow back through the pipeline so the item leaves the list.
4. *(Optional)* an agent drafts the weekly proposal; a human approves every action.

Headline the demo should be able to show: *"€X of capital is tied up in overstock, and these N items stock out within their lead time."*

Non-goals: ML demand forecasting, seasonality models, multi-echelon optimisation. Velocity is a moving average against reorder rules: explainable, and what most mid-size companies lack. Seasonality is a later upgrade, and the demo must not claim "AI forecasting".

## Decisions already taken

- **Data size: 250M order lines**, not 500M (rollup-served latency is about the same; build and RAM are roughly halved). See Phase 0.
- **Demo host**: one Contabo Cloud VPS (12 vCPU, 48 GB, 200 GB NVMe), 1-month term first. 48 GB is enough to build 250M on the box itself (`STARROCKS_MEM_LIMIT=38g` with Cube and Keycloak stopped during the build, about 16 GB when serving).
- **Services for the demo**: only the `starrocks` profile serving set, started by name (Postgres/Airflow have no profile and would otherwise start too). `postgres_active` and the ingest DAG are added back only from Phase 2 (write-back loop).

```bash
STARROCKS_MEM_LIMIT=16g docker compose --profile starrocks up -d --build \
  starrocks-fe starrocks-be starrocks-init cubestore cubestore-worker cube keycloak auth dashboard-cube
```

## What the source already has

All of these are in `postgres_active/init/02_adventureworks_schema.sql` and seeded (10% sample) by `03_adventureworks_seed.sql.gz`:

| Table | Columns that matter |
|---|---|
| `product` | `make_flag`, `finished_goods_flag`, `safety_stock_level`, `reorder_point`, `standard_cost`, `list_price`, `days_to_manufacture`, `sell_end_date` |
| `product_inventory` | `product_id`, `location_id`, `quantity` (on hand), `modified_date` — already mutated by `simulate_adventureworks.py` (`update_rows`) |
| `location` | `location_id`, `name`, `cost_rate`, `availability` |
| `product_vendor` | `product_id`, `business_entity_id` (vendor), `average_lead_time` (days), `standard_price`, `min_order_qty`, `max_order_qty`, `on_order_qty` |
| `vendor` | `business_entity_id`, `name`, `preferred_vendor_status`, `active_flag` |
| `purchase_order_header` | `purchase_order_id`, `status` (1 pending, 2 approved, 3 rejected, 4 complete), `vendor_id`, `order_date`, `ship_date` |
| `purchase_order_detail` | `purchase_order_id`, `product_id`, `due_date`, `order_qty`, `received_qty`, `rejected_qty`, `stocked_qty` |
| `work_order` | `product_id`, `order_qty`, `stocked_qty`, `start_date`, `end_date`, `due_date` |
| `special_offer` | `special_offer_id`, `description`, `discount_pct`, `type`, `category`, `start_date`, `end_date`, `min_qty`, `max_qty` |
| `special_offer_product` | `special_offer_id`, `product_id` |
| `sales_order_detail` | `special_offer_id`, `unit_price_discount` — links past sales to past offers (campaign lift) |

**AdventureWorks nuance:** finished bikes are *manufactured* (`make_flag = true`, replenished by **work orders**, lead time `days_to_manufacture`); components and resale accessories are *purchased* (rows in `product_vendor`, replenished by **purchase orders**, lead time `average_lead_time`). The replenishment action and lead time must branch on this.

None of the purchasing/inventory tables are dbt sources yet (`dbt/adventureworks_starrocks/models/staging/_sources.yml`), so they are not ingested into StarRocks today. The live ingest (`airflow/scripts/ingest_starrocks.py`) ingests whatever `dbt_source_tables()` returns, so adding them as sources adds them to ingestion. The SQL Server spike path needs matching lines in `spike/ingest/tables.csv` (it has `product_inventory`, `location`, `special_offer`, but not `product_vendor`, `vendor`, `purchase_order_*`, `special_offer_product`, `work_order`).

## Phase 0 — 250M tier and the scaling trap

### 0.1 A direct 250M tier in `spike/scale/build.py`

Today `SCALES = {"10m": 83, "100m": 825, "500m": 4120}` and the smaller tiers are copy-index subsets of `scale_500m`, so building 250M would first require building 500M.

- Add `"250m": 2060`.
- Generalise `build_500m()` into `build_tier(name)` that cross-joins `raw` up to `SCALES[name]` copies directly; derive the smaller tiers from the largest tier that was built (or from `raw` when only one is asked for).
- `--only 250m` builds just that tier. Keep the 500M behaviour unchanged.
- dbt: `--vars '{aw_source_schema: scale_250m, date_shift_years: 0}'`. Cube: the 500M-tuned model in `spike/cube/model` (year partitions) is the starting point; check whether the 250M run is served by the same rollups.

### 0.2 Scale supply to match demand (must-do before any inventory metric)

`build.py` multiplies **sales** (K copies, dates shifted by `k % 8` years) but leaves **inventory, purchase orders and work orders at the original scale**. Unfixed, every product shows as out of stock because daily demand is ~K/8 times higher than any stock level.

- Compute the factor empirically, not from K: `factor = units sold in the trailing 90 days (scaled schema) / units sold in the trailing 90 days (raw)`, each trailing window anchored at that schema's own `max(order_date)`. Expect roughly K/8 (≈257 for 250M).
- In the scaled schema, materialise `product_inventory`, `purchase_order_detail` quantities (`order_qty`, `received_qty`, `stocked_qty`, `rejected_qty`), `work_order` quantities, `product_vendor.min_order_qty / max_order_qty / on_order_qty`, and `product.safety_stock_level / reorder_point` multiplied by `factor` (rounded). Record the factor in a small `scale_meta.supply_factor` table so dbt and the docs can show it.
- Purchase-order and work-order *dates* get the same year shift as the sales copy they are paired with, or (simpler) are shifted once so the open orders sit just after the scaled data's "today".
- The 10% source sample may break referential integrity (offers/vendors referencing missing rows). Add a reconciliation query and decide per table: drop orphans, or keep and flag.

### 0.3 "Today" is the data's today

All trailing windows (28/90 days, "no sales in 90 days", "due within lead time") anchor on `as_of_date = max(order_date)` of the fact in use, never `current_date` (scaled history ends in the past; the live sandbox moves forward). Expose it as a single model (`int_as_of_date`) every inventory model joins to.

Acceptance: after Phase 0, the share of products in "stockout" on the scaled schema is within a few points of the share on the unscaled base.

## Phase 1 — analytics (read-only)

### 1.1 dbt staging (`models/staging/`)

Add sources and `stg_` models for: `product_inventory`, `location`, `product_vendor`, `vendor`, `purchase_order_header`, `purchase_order_detail`, `work_order`, `special_offer`, `special_offer_product`. Extend `stg_product` with `make_flag`, `finished_goods_flag`, `safety_stock_level`, `reorder_point`, `days_to_manufacture`, `sell_end_date` if missing. Add `unique`/`not_null` tests on keys, following the style in `_sources.yml` / `_marts.yml`.

### 1.2 Intermediate models (`models/intermediate/`)

- `int_as_of_date` — one row, see 0.3.
- `int_product_demand` — per product: units sold in the last 28 and 90 days (internet + reseller facts), `avg_daily_demand_28d`, `avg_daily_demand_90d`, `last_sale_date`, demand std-dev over the 90 days (weekly buckets) for an optional safety-stock check. This is the only model that scans the 250M facts; make it a partitioned table, not a view, and check its build time and memory (spill on).
- `int_product_supply` — per product: `on_hand` (sum over locations; keep the per-location split in `int_inventory_by_location`), `on_order` = open PO quantity (`status in (1,2)`, `order_qty - received_qty`, `due_date` after as-of) + open work-order quantity (`order_qty - stocked_qty`, `end_date is null`), next due date.
- `int_product_replenishment` — per product: `replenishment_type` (`purchase` when the product has an active `product_vendor` row, `manufacture` when `make_flag`), chosen vendor (preferred + active, then lowest `standard_price`), `lead_time_days` (`average_lead_time` or `days_to_manufacture`, with a floor of 1), `min_order_qty`, `max_order_qty`, `unit_cost`.

### 1.3 Mart: `inventory_health` (one row per product)

Columns and rules (keep thresholds as dbt vars so they can be changed in the demo):

| Column | Rule |
|---|---|
| `daily_demand` | `avg_daily_demand_28d`, falling back to the 90-day figure when the 28-day window has no sales |
| `days_of_cover` | `(on_hand + on_order) / nullif(daily_demand, 0)` |
| `projected_at_lead_time` | `on_hand + on_order_due_within_lead_time - daily_demand * lead_time_days` |
| `status` | `stockout`: `on_hand = 0 and daily_demand > 0` · `reorder_now`: `projected_at_lead_time <= reorder_point` · `dead_stock`: no sales in `var('dead_stock_days', 90)` and `on_hand > 0` · `overstock`: `days_of_cover > var('overstock_days', 120)` · `discontinued`: `sell_end_date` before as-of (excluded from reordering) · else `healthy` |
| `suggested_order_qty` | `ceil(daily_demand * (lead_time_days + var('review_period_days', 14)) + safety_stock_level - on_hand - on_order)`, floored at 0, raised to `min_order_qty`, capped at `max_order_qty` (purchased items; manufactured items skip the vendor clamps) |
| `suggested_order_value` | `suggested_order_qty * unit_cost` |
| `target_stock` | `daily_demand * var('target_cover_days', 60)` |
| `excess_units` / `excess_value` | `greatest(on_hand - target_stock, 0)` and that times `standard_cost`; dead stock = all of `on_hand` |
| `suggested_discount_pct` | tier by excess and age: e.g. 10% for overstock < 2x target, 20% above, 30-40% for dead stock — refined by 1.4 |
| `reason` | short text for the UI and the agent, e.g. `"4 days of cover, 12-day lead time, vendor min 100 → order 300"` |

Also `inventory_health_by_location` if the per-location view is wanted in the UI.

Tests: `status` accepted values; `suggested_order_qty >= 0`; no `discontinued` row has a suggested order; a singular test that the totals of `excess_value` and `suggested_order_value` reconcile with a direct SQL recomputation.

### 1.4 Campaign evidence: `offer_performance`

From `sales_order_detail.special_offer_id` + `special_offer`: per offer type / category and discount band, the units per day during the offer versus the 28 days before. Use it to label the overstock suggestion ("past 15% volume discounts on Accessories lifted units ~1.8x"). Treat it as descriptive evidence, not elasticity modelling.

### 1.5 Cube

- New cube `inventory_health` over `mart.inventory_health` (and `offer_performance`), joined to `products`. Measures: count by status, sum of `excess_value`, sum of `suggested_order_value`, sum of `suggested_order_qty`. Dimensions: status, replenishment type, vendor, category/subcategory (through `products`), `reason`, `suggested_discount_pct`.
- This mart is small (one row per product), so a rollup is probably unnecessary; confirm with `spike/cube/probe.py` and the bench.
- Security: inventory is not territory-bound, so the territory RLS in `cube/cube.js` does not apply. Add roles in Keycloak + `cube.js`: `purchasing` (sees reorder data, costs), `marketing` (sees overstock + discounts, no supplier costs), `admin` (all). Reps see neither. Extend `cube/tests/test_rls.py` with cases for the new cube (including ordering by a hidden measure, the hole the spike found).

### 1.6 Dashboard (`dashboard/static/app.js`, `dashboard/cube/`)

Two new panels, rendered independently like the existing ones:

- **Reorder list**: stockout + reorder_now items, sorted by days of cover; columns product, status, on hand, on order, daily demand, lead time, suggested qty, value, vendor, reason. Excel export (reuse `xlsx.js`) = a purchase-order draft.
- **Overstock list**: overstock + dead stock, sorted by `excess_value`; columns product, days of cover, excess units/value, suggested discount, evidence from `offer_performance`.
- KPI tiles: items at stockout risk, value of suggested reorders, capital tied in excess stock.

Acceptance for Phase 1: the panels load under 1 s at p95 on the demo host; numbers reconcile with direct SQL; each role sees only its panels; `dbt build` passes.

## Phase 2 — close the loop (write-back)

- **Actions service**: a small FastAPI service, modelled on `auth/` (same JWT validation via Keycloak), with a Postgres user that can only insert into specific tables of `postgres_active`:
  - `POST /actions/purchase-orders` (role `purchasing`): creates `purchase_order_header` (status 1 pending → 2 approved on approval) + `purchase_order_detail` rows for the approved lines.
  - `POST /actions/work-orders` (role `purchasing` or a `production` role): inserts `work_order` rows for manufactured items.
  - `POST /actions/campaigns` (role `marketing`): inserts `special_offer` + `special_offer_product` rows with the chosen discount and dates.
  - Every action writes an audit row (`actions_log`: who, when, payload, source recommendation id). Validate server-side against the current `inventory_health` row (no client-supplied prices or quantities beyond allowed edits), idempotency key per proposal.
- **Simulator**: extend `simulate_adventureworks.py` so approved POs/work orders are received after their lead time (status 4, `received_qty`/`stocked_qty` set, `product_inventory.quantity` increased), and sales consume inventory (decrement `quantity` for sold products) instead of the random ±5 drift. Keep the random drift small or remove it.
- **Pipeline**: ingest picks the new rows up (the new tables are already dbt sources from 1.1); the next dbt run moves `on_order` up and the item leaves the reorder list. Measure end-to-end freshness (approval → item gone) and show it in the demo.
- **UI**: "Approve" on a row or a selection, with editable quantity/discount within limits; a pending/approved badge driven by the audit log.
- Services needed again for Phase 2: `postgres_active`, the Airflow ingest + dbt DAG (or a lighter scheduler), plus the actions service.

Acceptance: approving three reorder lines and one campaign produces the expected rows in `postgres_active`, they appear in StarRocks after one pipeline cycle, the items change status, and the audit log has four entries. Security tests: a marketing user cannot create a PO; a purchasing user cannot create a campaign; tampered quantities above `max_order_qty` are rejected.

## Phase 3 — agent layer (optional, ties into the AI positioning)

- A weekly job (Airflow DAG or a scheduled script) runs an LLM agent with **read-only** access to Cube's REST API (a dedicated service account role) and **no** direct write access.
- It drafts the week's proposal: top reorders and campaigns, each with the numbers behind it and a one-line rationale, grouped by vendor (one PO draft per vendor) and by category for campaigns.
- Output is a set of *pending proposals* the actions service stores (`status = proposed`); a manager approves or edits them in the UI, which then goes through the Phase 2 endpoints. The agent never approves its own proposals.
- Evaluate it: the agent's suggested quantities must equal the mart's `suggested_order_qty` unless it explains a deviation; log prompts, tool calls and outputs for review.

## Order of work (one PR each)

1. Phase 0: 250M tier, supply scaling with `scale_meta.supply_factor`, `int_as_of_date`, orphan reconciliation.
2. Phase 1.1–1.3: staging, intermediate, `inventory_health` + tests.
3. Phase 1.4–1.5: `offer_performance`, Cube cube, new roles + RLS tests.
4. Phase 1.6: dashboard panels and KPIs; bench on the demo host.
5. Phase 2: actions service, simulator receipts/consumption, approve UI, security tests.
6. Phase 3: agent, proposals, evaluation.

## Open questions

- Per-location or company-wide reorder logic? AdventureWorks locations are production locations, not stores; company-wide is simpler and probably enough for the demo.
- Do campaigns target the internet channel only (special offers apply to `sales_order_detail` on both channels)?
- Thresholds (`overstock_days`, `target_cover_days`, `review_period_days`, `dead_stock_days`): pick defaults that produce a believable mix of statuses on the 250M data, then expose them in the UI.
- Does the 10% seed leave enough `product_vendor` / `purchase_order_*` coverage for the purchased items? If not, generate vendor rows for products with sales but no vendor.
