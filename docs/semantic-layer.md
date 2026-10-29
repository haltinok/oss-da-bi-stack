# The semantic layer

What the Cube model offers a dashboard: the **cubes** (a fact such as `internet_sales`, or a dimension such as `products`), their **measures** (numbers: revenue, orders) and **dimensions** (things to group or filter by: region, category, a date). A dashboard spec names these as `cube.member` and nothing else; every number comes from Cube, which also enforces who may read what.

Generated from `cube/model/cubes/*.yml` by `scripts/dashspec semantic` (descriptions come from the model files; a test keeps this page current). The guide is [dashboards.md](dashboards.md).

## How to think about it

- A **fact** cube holds events (order lines, inventory rows). Its measures can be grouped by the dimensions of the cubes it **joins to**: `internet_sales` and `reseller_sales` join `products`, `dates` and `territories`; `inventory_health` joins `products`.
- Cube cannot join two fact cubes in one query. To show both sales channels together, use `sum: [internet_sales.revenue, reseller_sales.revenue]`, a `ratio` of two sums (a margin over both channels) or a stacked bar; there is no other arithmetic in a spec.
- `orders` is the exact count of distinct orders (right under every filter, slower at scale); `orders_placed` counts each order once on its first line (fast, right for date, territory and channel, wrong for product filters).
- `margin_pct` is in percentage points (0-100). For a percentage in a spec use a `ratio` of `gross_profit` over `revenue` with `format: pct`.
- A text dimension with a natural order (a month's name, a quarter's, a weekday's) **sorts by another dimension** of its cube, declared in the model as `meta: { sort_by: <number field> }` and shown below as "Sorted by": tables, pivots, filter lists and slicers order by that field, so months run January to December, not alphabetically.
- Row-level security: reps and managers only get the territories assigned to them, whatever the dashboard asks for.

## Who can read what

| Role | Can read |
|---|---|
| `admin` | everything |
| `manager` | the sales facts and their dimensions, profit included; not inventory or customers; own territories only |
| `rep` | like a manager but **no profit members** (`gross_profit`, `margin_pct`, `product_cost`); own territories only |
| `purchasing` | inventory data only (`inventory_health`, `products`) |
| `marketing` | inventory and offer data (`inventory_health`, `offer_performance`, `products`), **no supplier or order-size members** (`lead_time_days`, `max_order_qty`, `min_order_qty`, `replenishment_type`, `suggested_order_qty`, `suggested_order_qty_total`, `suggested_order_value`, `suggested_order_value_total`, `unit_cost`, `vendor_id`, `vendor_name`) |

A dashboard that lists a role must only use members that role can read; the validator checks it. Customer data is admin-only.

## `customers`

Customers. Personal data: admin only.

Readable by: `admin`.

### Measures

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `customers.count` | count | Number of customers. | `manager`, `rep`, `purchasing`, `marketing` |

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `customers.key` | number | Customer key. | `manager`, `rep`, `purchasing`, `marketing` |
| `customers.last_name` | string | Customer last name (personal data, admin only). | `manager`, `rep`, `purchasing`, `marketing` |

## `dates`

The calendar: join target for a time axis and fiscal years.

Readable by: `admin`, `manager`, `rep`.

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `dates.calendar_quarter` | number | Calendar quarter number, 1 to 4. | `purchasing`, `marketing` |
| `dates.calendar_year` | number | Calendar year. | `purchasing`, `marketing` |
| `dates.day_name` | string | Day of the week as text (Sunday ... Saturday). Sorted by `dates.day_of_week`. | `purchasing`, `marketing` |
| `dates.day_of_week` | number | Day of the week as a number: 1 is Sunday, 7 is Saturday. | `purchasing`, `marketing` |
| `dates.fiscal_quarter` | number | Fiscal quarter number, 1 to 4 (the fiscal year starts in July: July to September is 1). | `purchasing`, `marketing` |
| `dates.fiscal_quarter_name` | string | Fiscal quarter as text: FQ1 to FQ4. Sorted by `dates.fiscal_quarter`. | `purchasing`, `marketing` |
| `dates.fiscal_year` | number | Fiscal year, named after the year it ends in (the year starts in July: July 2020 is FY2021). | `purchasing`, `marketing` |
| `dates.full_date` | time | Calendar date (a time dimension). | `purchasing`, `marketing` |
| `dates.key` | number | Date key. | `purchasing`, `marketing` |
| `dates.month_name` | string | Month name (January ... December). Sorted by `dates.month_of_year`. | `purchasing`, `marketing` |
| `dates.month_of_year` | number | Month number, 1 (January) to 12 (December). | `purchasing`, `marketing` |
| `dates.quarter_name` | string | Calendar quarter as text: Q1 to Q4. Sorted by `dates.calendar_quarter`. | `purchasing`, `marketing` |
| `dates.week_of_year` | number | ISO week number of the year, 1 to 53. | `purchasing`, `marketing` |
| `dates.year_month` | string | Month and year as text, e.g. Jan 2012. Sorted by `dates.year_month_number`. | `purchasing`, `marketing` |
| `dates.year_month_number` | number | Year and month as a number that sorts in time order: 201201 is January 2012. | `purchasing`, `marketing` |
| `dates.year_quarter` | string | Year and quarter as text, e.g. 2012 Q1. Sorted by `dates.year_quarter_number`. | `purchasing`, `marketing` |
| `dates.year_quarter_number` | number | Year and quarter as a number that sorts in time order: 20121 is the first quarter of 2012. | `purchasing`, `marketing` |

## `due_dates`

The calendar in the role of the due date: the date an order line was due to be delivered. Same fields as `dates`, shown with the prefix Due.

A role of `dates`: the same calendar table and fields, joined by its own key; the fields are named "Due ..." in reports (e.g. "Due month name").

Readable by: `admin`, `manager`, `rep`.

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `due_dates.calendar_quarter` | number | Calendar quarter number, 1 to 4. | `purchasing`, `marketing` |
| `due_dates.calendar_year` | number | Calendar year. | `purchasing`, `marketing` |
| `due_dates.day_name` | string | Day of the week as text (Sunday ... Saturday). Sorted by `due_dates.day_of_week`. | `purchasing`, `marketing` |
| `due_dates.day_of_week` | number | Day of the week as a number: 1 is Sunday, 7 is Saturday. | `purchasing`, `marketing` |
| `due_dates.fiscal_quarter` | number | Fiscal quarter number, 1 to 4 (the fiscal year starts in July: July to September is 1). | `purchasing`, `marketing` |
| `due_dates.fiscal_quarter_name` | string | Fiscal quarter as text: FQ1 to FQ4. Sorted by `due_dates.fiscal_quarter`. | `purchasing`, `marketing` |
| `due_dates.fiscal_year` | number | Fiscal year, named after the year it ends in (the year starts in July: July 2020 is FY2021). | `purchasing`, `marketing` |
| `due_dates.full_date` | time | Calendar date (a time dimension). | `purchasing`, `marketing` |
| `due_dates.key` | number | Date key. | `purchasing`, `marketing` |
| `due_dates.month_name` | string | Month name (January ... December). Sorted by `due_dates.month_of_year`. | `purchasing`, `marketing` |
| `due_dates.month_of_year` | number | Month number, 1 (January) to 12 (December). | `purchasing`, `marketing` |
| `due_dates.quarter_name` | string | Calendar quarter as text: Q1 to Q4. Sorted by `due_dates.calendar_quarter`. | `purchasing`, `marketing` |
| `due_dates.week_of_year` | number | ISO week number of the year, 1 to 53. | `purchasing`, `marketing` |
| `due_dates.year_month` | string | Month and year as text, e.g. Jan 2012. Sorted by `due_dates.year_month_number`. | `purchasing`, `marketing` |
| `due_dates.year_month_number` | number | Year and month as a number that sorts in time order: 201201 is January 2012. | `purchasing`, `marketing` |
| `due_dates.year_quarter` | string | Year and quarter as text, e.g. 2012 Q1. Sorted by `due_dates.year_quarter_number`. | `purchasing`, `marketing` |
| `due_dates.year_quarter_number` | number | Year and quarter as a number that sorts in time order: 20121 is the first quarter of 2012. | `purchasing`, `marketing` |

## `internet_sales` (fact)

Internet (online) channel order lines of the sales fact: one row per product on an order. Rejected and cancelled orders are left out. Row-level security limits reps and managers to their own territories.

Joins: `customers`, `dates`, `due_dates`, `products`, `ship_dates`, `territories`.

Readable by: `admin`, `manager`, `rep`.

### Measures

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `internet_sales.aov` | number | Revenue per placed order (a ratio inside one cube; across both channels use a ratio of revenue over orders). | `purchasing`, `marketing` |
| `internet_sales.discount` | sum | Discount amount given on the order lines. | `purchasing`, `marketing` |
| `internet_sales.gross_profit` | sum | Revenue minus product cost. Hidden from reps. | `rep`, `purchasing`, `marketing` |
| `internet_sales.lines` | count | Number of order lines. | `purchasing`, `marketing` |
| `internet_sales.margin_pct` | number | Gross profit as a percentage of revenue, 0-100 (not a fraction). Hidden from reps. For a margin across both channels use a ratio of gross_profit over revenue with format pct. | `rep`, `purchasing`, `marketing` |
| `internet_sales.orders` | count_distinct | Exact number of distinct orders. Right under any filter, but a rollup cannot serve it, so it can be slow at large scale. | `purchasing`, `marketing` |
| `internet_sales.orders_placed` | sum | Orders counted once, on their first line: exact and fast for any grouping or filter on the order's own date, territory or channel. Not the number of orders containing a given product: use orders for that. | `purchasing`, `marketing` |
| `internet_sales.product_cost` | sum | Standard cost of the products sold. Hidden from reps. | `rep`, `purchasing`, `marketing` |
| `internet_sales.revenue` | sum | Sales amount of the order lines. | `purchasing`, `marketing` |
| `internet_sales.units` | sum | Quantity sold. | `purchasing`, `marketing` |

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `internet_sales.order_date` | time | When the order was placed (a time dimension: use it for a time axis). | `purchasing`, `marketing` |
| `internet_sales.order_line_id` | string | Key of the order line (order number and line number). | `purchasing`, `marketing` |
| `internet_sales.order_number` | string | The sales order number. | `purchasing`, `marketing` |
| `internet_sales.order_status` | number | Order status code: 1 in process, 2 approved, 3 backordered, 5 shipped (4 rejected and 6 cancelled are not in this cube). | `purchasing`, `marketing` |

## `inventory_health`

One row per product that is stocked, sold or on order: its stock position, a status and what to do. Not territory-bound: purchasing and admin see everything, marketing no supplier or order-size members; managers and reps none of it.

Joins: `products`.

Readable by: `admin`, `purchasing`, `marketing`.

### Measures

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `inventory_health.dead_stock_items` | count | Dead stock only: in stock, no recent sale. | `manager`, `rep` |
| `inventory_health.excess_units_total` | sum | Units of all excess stock. | `manager`, `rep` |
| `inventory_health.excess_value_total` | sum | Value of all excess stock. | `manager`, `rep` |
| `inventory_health.items_at_risk` | count | Stockouts plus products to reorder now. | `manager`, `rep` |
| `inventory_health.overstock_items` | count | Overstock plus dead stock products. | `manager`, `rep` |
| `inventory_health.product_count` | count | Number of products. | `manager`, `rep` |
| `inventory_health.reorder_items` | count | Products with status reorder_now. | `manager`, `rep` |
| `inventory_health.stockout_items` | count | Products with status stockout. | `manager`, `rep` |
| `inventory_health.suggested_order_qty_total` | sum | Sum of the suggested order quantities. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.suggested_order_value_total` | sum | Sum of the suggested order values. Supplier data. | `manager`, `rep`, `marketing` |

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `inventory_health.daily_demand` | number | Average units sold per day over the demand window. | `manager`, `rep` |
| `inventory_health.days_of_cover` | number | Days the stock lasts at the current demand. | `manager`, `rep` |
| `inventory_health.excess_units` | number | Units above the target stock (overstock and dead stock). | `manager`, `rep` |
| `inventory_health.excess_value` | number | Value of the excess units. | `manager`, `rep` |
| `inventory_health.key` | number | Product key. | `manager`, `rep` |
| `inventory_health.last_sale_date` | time | Date of the product's last sale (a time dimension). | `manager`, `rep` |
| `inventory_health.lead_time_days` | number | Days from order to delivery. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.max_order_qty` | number | Vendor maximum order quantity. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.min_order_qty` | number | Vendor minimum order quantity. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.on_hand` | number | Units in stock. | `manager`, `rep` |
| `inventory_health.on_order` | number | Units on open purchase or work orders. | `manager`, `rep` |
| `inventory_health.product_name` | string | Product name. | `manager`, `rep` |
| `inventory_health.reason` | string | Why the status was given (in words). | `manager`, `rep` |
| `inventory_health.replenishment_type` | string | How it is replenished: purchase, manufacture or none. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.status` | string | Stock status: stockout, reorder_now, dead_stock, overstock, healthy, not_stocked or discontinued. | `manager`, `rep` |
| `inventory_health.suggested_discount_pct` | number | Suggested discount depth for the excess, in percent. | `manager`, `rep` |
| `inventory_health.suggested_order_qty` | number | Suggested quantity to order or make. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.suggested_order_value` | number | Suggested quantity times unit cost. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.unit_cost` | number | Cost per unit. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.vendor_id` | number | Vendor key. Supplier data. | `manager`, `rep`, `marketing` |
| `inventory_health.vendor_name` | string | Vendor name. Supplier data. | `manager`, `rep`, `marketing` |

## `offer_performance`

Special offers and what happened to unit sales during them versus the 28 days before. Descriptive only: no control group, so it also carries seasonality and trend. Marketing and admin.

Readable by: `admin`, `marketing`.

### Measures

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `offer_performance.avg_lift` | avg | Average of the per-offer lift (offers with no baseline are skipped; one offer with a tiny baseline can dominate it). | `manager`, `rep`, `purchasing` |
| `offer_performance.days_during` | sum | Days offers ran. | `manager`, `rep`, `purchasing` |
| `offer_performance.offers` | count | Number of offers. | `manager`, `rep`, `purchasing` |
| `offer_performance.units_before` | sum | Units sold in the 28 days before offers. | `manager`, `rep`, `purchasing` |
| `offer_performance.units_during` | sum | Units sold during offers. | `manager`, `rep`, `purchasing` |

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `offer_performance.description` | string | Offer description. | `manager`, `rep`, `purchasing` |
| `offer_performance.discount_band` | string | Discount depth band. | `manager`, `rep`, `purchasing` |
| `offer_performance.discount_pct` | number | Discount in percent. | `manager`, `rep`, `purchasing` |
| `offer_performance.end_date` | time | Offer end (a time dimension). | `manager`, `rep`, `purchasing` |
| `offer_performance.key` | number | Offer key. | `manager`, `rep`, `purchasing` |
| `offer_performance.lift` | number | Units per day during the offer over units per day in the 28 days before. | `manager`, `rep`, `purchasing` |
| `offer_performance.offer_category` | string | Offer category. | `manager`, `rep`, `purchasing` |
| `offer_performance.offer_type` | string | Type of offer. | `manager`, `rep`, `purchasing` |
| `offer_performance.start_date` | time | Offer start (a time dimension). | `manager`, `rep`, `purchasing` |

## `products`

Products and their categories: join target for both sales facts and the inventory cube.

Readable by: `admin`, `manager`, `rep`, `purchasing`, `marketing`.

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `products.category` | string | Product category (Bikes, Components, Clothing, Accessories; Uncategorized when none). |  |
| `products.color` | string | Product colour. |  |
| `products.key` | number | Product key. |  |
| `products.name` | string | Product name. |  |
| `products.subcategory` | string | Product subcategory (Uncategorized when none). |  |

## `reseller_sales` (fact)

Reseller channel order lines of the sales fact: one row per product on an order. Rejected and cancelled orders are left out. Row-level security limits reps and managers to their own territories.

Joins: `dates`, `due_dates`, `products`, `ship_dates`, `territories`.

Readable by: `admin`, `manager`, `rep`.

### Measures

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `reseller_sales.aov` | number | Revenue per placed order (a ratio inside one cube; across both channels use a ratio of revenue over orders). | `purchasing`, `marketing` |
| `reseller_sales.discount` | sum | Discount amount given on the order lines. | `purchasing`, `marketing` |
| `reseller_sales.gross_profit` | sum | Revenue minus product cost. Hidden from reps. | `rep`, `purchasing`, `marketing` |
| `reseller_sales.lines` | count | Number of order lines. | `purchasing`, `marketing` |
| `reseller_sales.margin_pct` | number | Gross profit as a percentage of revenue, 0-100 (not a fraction). Hidden from reps. For a margin across both channels use a ratio of gross_profit over revenue with format pct. | `rep`, `purchasing`, `marketing` |
| `reseller_sales.orders` | count_distinct | Exact number of distinct orders. Right under any filter, but a rollup cannot serve it, so it can be slow at large scale. | `purchasing`, `marketing` |
| `reseller_sales.orders_placed` | sum | Orders counted once, on their first line: exact and fast for any grouping or filter on the order's own date, territory or channel. Not the number of orders containing a given product: use orders for that. | `purchasing`, `marketing` |
| `reseller_sales.product_cost` | sum | Standard cost of the products sold. Hidden from reps. | `rep`, `purchasing`, `marketing` |
| `reseller_sales.revenue` | sum | Sales amount of the order lines. | `purchasing`, `marketing` |
| `reseller_sales.units` | sum | Quantity sold. | `purchasing`, `marketing` |

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `reseller_sales.order_date` | time | When the order was placed (a time dimension: use it for a time axis). | `purchasing`, `marketing` |
| `reseller_sales.order_line_id` | string | Key of the order line (order number and line number). | `purchasing`, `marketing` |
| `reseller_sales.order_number` | string | The sales order number. | `purchasing`, `marketing` |
| `reseller_sales.order_status` | number | Order status code: 1 in process, 2 approved, 3 backordered, 5 shipped (4 rejected and 6 cancelled are not in this cube). | `purchasing`, `marketing` |

## `ship_dates`

The calendar in the role of the ship date: the date an order line shipped. Same fields as `dates` (month, quarter, fiscal year ...), shown with the prefix Ship.

A role of `dates`: the same calendar table and fields, joined by its own key; the fields are named "Ship ..." in reports (e.g. "Ship month name").

Readable by: `admin`, `manager`, `rep`.

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `ship_dates.calendar_quarter` | number | Calendar quarter number, 1 to 4. | `purchasing`, `marketing` |
| `ship_dates.calendar_year` | number | Calendar year. | `purchasing`, `marketing` |
| `ship_dates.day_name` | string | Day of the week as text (Sunday ... Saturday). Sorted by `ship_dates.day_of_week`. | `purchasing`, `marketing` |
| `ship_dates.day_of_week` | number | Day of the week as a number: 1 is Sunday, 7 is Saturday. | `purchasing`, `marketing` |
| `ship_dates.fiscal_quarter` | number | Fiscal quarter number, 1 to 4 (the fiscal year starts in July: July to September is 1). | `purchasing`, `marketing` |
| `ship_dates.fiscal_quarter_name` | string | Fiscal quarter as text: FQ1 to FQ4. Sorted by `ship_dates.fiscal_quarter`. | `purchasing`, `marketing` |
| `ship_dates.fiscal_year` | number | Fiscal year, named after the year it ends in (the year starts in July: July 2020 is FY2021). | `purchasing`, `marketing` |
| `ship_dates.full_date` | time | Calendar date (a time dimension). | `purchasing`, `marketing` |
| `ship_dates.key` | number | Date key. | `purchasing`, `marketing` |
| `ship_dates.month_name` | string | Month name (January ... December). Sorted by `ship_dates.month_of_year`. | `purchasing`, `marketing` |
| `ship_dates.month_of_year` | number | Month number, 1 (January) to 12 (December). | `purchasing`, `marketing` |
| `ship_dates.quarter_name` | string | Calendar quarter as text: Q1 to Q4. Sorted by `ship_dates.calendar_quarter`. | `purchasing`, `marketing` |
| `ship_dates.week_of_year` | number | ISO week number of the year, 1 to 53. | `purchasing`, `marketing` |
| `ship_dates.year_month` | string | Month and year as text, e.g. Jan 2012. Sorted by `ship_dates.year_month_number`. | `purchasing`, `marketing` |
| `ship_dates.year_month_number` | number | Year and month as a number that sorts in time order: 201201 is January 2012. | `purchasing`, `marketing` |
| `ship_dates.year_quarter` | string | Year and quarter as text, e.g. 2012 Q1. Sorted by `ship_dates.year_quarter_number`. | `purchasing`, `marketing` |
| `ship_dates.year_quarter_number` | number | Year and quarter as a number that sorts in time order: 20121 is the first quarter of 2012. | `purchasing`, `marketing` |

## `territories`

Sales territories: join target for the sales facts. The unit of row-level security.

Readable by: `admin`, `manager`, `rep`.

### Dimensions

| Member | Type | Meaning | Hidden from |
|---|---|---|---|
| `territories.country` | string | Territory country. | `purchasing`, `marketing` |
| `territories.group_name` | string | Territory group (North America, Europe, Pacific). | `purchasing`, `marketing` |
| `territories.key` | number | Territory key. | `purchasing`, `marketing` |
| `territories.region` | string | Sales territory region (Southwest, Canada, Germany, ...). Reps and managers only ever see the regions assigned to them. | `purchasing`, `marketing` |
