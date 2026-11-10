# The semantic layer

What the Cube model offers a dashboard: the **cubes** (a fact, which holds events, or a dimension, which describes them), their **measures** (numbers to add up or count) and **dimensions** (things to group or filter by: a region, a category, a date). A dashboard spec names these as `cube.member` and nothing else; every number comes from Cube, which also enforces who may read what.

Generated from the model's cube files by `scripts/dashspec semantic` (descriptions come from the model files; a test keeps this page current). The guide is [dashboards.md](dashboards.md).

## How to think about it

- A **fact** cube (`meta: { kind: fact }`) holds events. Its measures can be grouped by the dimensions of the cubes it **joins to**: `internet_sales` joins `customers`, `dates`, `due_dates`, `products`, `ship_dates`, `territories`; `inventory_health` joins `products`; `offer_performance` joins ; `reseller_sales` joins `dates`, `due_dates`, `products`, `ship_dates`, `territories`.
- Cube cannot join two fact cubes in one query. To show facts together, use `sum: [internet_sales.revenue, reseller_sales.revenue]`, a `ratio` of two sums or a stacked bar; there is no other arithmetic in a spec.
- A text dimension with a natural order (a month's name, a quarter's, a weekday's) **sorts by another dimension** of its cube, declared in the model as `meta: { sort_by: <number field> }` and shown below as "Sorted by": tables, pivots, filter lists and slicers order by that field, so months run January to December, not alphabetically.
- Row-level security: a person only gets the values a row rule gives them (a rule for them or their groups), on every cube the rule covers, whatever the dashboard asks for.

## Who can read what

Not decided by a role: a person's **role** says what they may *do* (`viewer` views dashboards, `editor` also builds and shares them, `admin` administers), and what data they may read comes from the **datasets** and grants and the **row rules** in the admin console (see [admin.md](admin.md)): a cube or single field that sits in a dataset needs a grant, and the cubes a row rule covers are limited to the person's values. Cube enforces it on every query, so a dashboard that uses something a reader may not read shows Cube's refusal in that panel. Whole cubes or single fields can be kept back by a dataset.

## `customers`

Customers. Personal data: admin only.

### Measures

| Member | Type | Meaning |
|---|---|---|
| `customers.count` | count | Number of customers. |

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `customers.key` | number | Customer key. |
| `customers.last_name` | string | Customer last name (personal data, admin only). |

## `dates`

The calendar: join target for a time axis and fiscal years.

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `dates.calendar_quarter` | number | Calendar quarter number, 1 to 4. |
| `dates.calendar_year` | number | Calendar year. |
| `dates.day_name` | string | Day of the week as text (Sunday ... Saturday). Sorted by `dates.day_of_week`. |
| `dates.day_of_week` | number | Day of the week as a number: 1 is Sunday, 7 is Saturday. |
| `dates.fiscal_quarter` | number | Fiscal quarter number, 1 to 4 (the fiscal year starts in July: July to September is 1). |
| `dates.fiscal_quarter_name` | string | Fiscal quarter as text: FQ1 to FQ4. Sorted by `dates.fiscal_quarter`. |
| `dates.fiscal_year` | number | Fiscal year, named after the year it ends in (the year starts in July: July 2020 is FY2021). |
| `dates.full_date` | time | Calendar date (a time dimension). |
| `dates.key` | number | Date key. |
| `dates.month_name` | string | Month name (January ... December). Sorted by `dates.month_of_year`. |
| `dates.month_of_year` | number | Month number, 1 (January) to 12 (December). |
| `dates.quarter_name` | string | Calendar quarter as text: Q1 to Q4. Sorted by `dates.calendar_quarter`. |
| `dates.week_of_year` | number | ISO week number of the year, 1 to 53. |
| `dates.year_month` | string | Month and year as text, e.g. Jan 2012. Sorted by `dates.year_month_number`. |
| `dates.year_month_number` | number | Year and month as a number that sorts in time order: 201201 is January 2012. |
| `dates.year_quarter` | string | Year and quarter as text, e.g. 2012 Q1. Sorted by `dates.year_quarter_number`. |
| `dates.year_quarter_number` | number | Year and quarter as a number that sorts in time order: 20121 is the first quarter of 2012. |

## `due_dates`

The calendar in the role of the due date: the date an order line was due to be delivered. Same fields as `dates`, shown with the prefix Due.

A role of `dates`: the same calendar table and fields, joined by its own key; the fields are named "Due ..." in reports (e.g. "Due month name").

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `due_dates.calendar_quarter` | number | Calendar quarter number, 1 to 4. |
| `due_dates.calendar_year` | number | Calendar year. |
| `due_dates.day_name` | string | Day of the week as text (Sunday ... Saturday). Sorted by `due_dates.day_of_week`. |
| `due_dates.day_of_week` | number | Day of the week as a number: 1 is Sunday, 7 is Saturday. |
| `due_dates.fiscal_quarter` | number | Fiscal quarter number, 1 to 4 (the fiscal year starts in July: July to September is 1). |
| `due_dates.fiscal_quarter_name` | string | Fiscal quarter as text: FQ1 to FQ4. Sorted by `due_dates.fiscal_quarter`. |
| `due_dates.fiscal_year` | number | Fiscal year, named after the year it ends in (the year starts in July: July 2020 is FY2021). |
| `due_dates.full_date` | time | Calendar date (a time dimension). |
| `due_dates.key` | number | Date key. |
| `due_dates.month_name` | string | Month name (January ... December). Sorted by `due_dates.month_of_year`. |
| `due_dates.month_of_year` | number | Month number, 1 (January) to 12 (December). |
| `due_dates.quarter_name` | string | Calendar quarter as text: Q1 to Q4. Sorted by `due_dates.calendar_quarter`. |
| `due_dates.week_of_year` | number | ISO week number of the year, 1 to 53. |
| `due_dates.year_month` | string | Month and year as text, e.g. Jan 2012. Sorted by `due_dates.year_month_number`. |
| `due_dates.year_month_number` | number | Year and month as a number that sorts in time order: 201201 is January 2012. |
| `due_dates.year_quarter` | string | Year and quarter as text, e.g. 2012 Q1. Sorted by `due_dates.year_quarter_number`. |
| `due_dates.year_quarter_number` | number | Year and quarter as a number that sorts in time order: 20121 is the first quarter of 2012. |

## `internet_sales` (fact)

Internet (online) channel order lines of the sales fact: one row per product on an order. Rejected and cancelled orders are left out. Row-level security limits reps and managers to their own territories.

Joins: `customers`, `dates`, `due_dates`, `products`, `ship_dates`, `territories`.

### Measures

| Member | Type | Meaning |
|---|---|---|
| `internet_sales.aov` | number | Revenue per placed order (a ratio inside one cube; across both channels use a ratio of revenue over orders). |
| `internet_sales.discount` | sum | Discount amount given on the order lines. |
| `internet_sales.gross_profit` | sum | Revenue minus product cost. Hidden from reps. |
| `internet_sales.lines` | count | Number of order lines. |
| `internet_sales.margin_pct` | number | Gross profit as a percentage of revenue, 0-100 (not a fraction). Hidden from reps. For a margin across both channels use a ratio of gross_profit over revenue with format pct. |
| `internet_sales.orders` | count_distinct | Exact number of distinct orders. Right under any filter, but a rollup cannot serve it, so it can be slow at large scale. |
| `internet_sales.orders_placed` | sum | Orders counted once, on their first line: exact and fast for any grouping or filter on the order's own date, territory or channel. Not the number of orders containing a given product: use orders for that. |
| `internet_sales.product_cost` | sum | Standard cost of the products sold. Hidden from reps. |
| `internet_sales.revenue` | sum | Sales amount of the order lines. |
| `internet_sales.units` | sum | Quantity sold. |

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `internet_sales.order_date` | time | When the order was placed (a time dimension: use it for a time axis). |
| `internet_sales.order_line_id` | string | Key of the order line (order number and line number). |
| `internet_sales.order_number` | string | The sales order number. |
| `internet_sales.order_status` | number | Order status code: 1 in process, 2 approved, 3 backordered, 5 shipped (4 rejected and 6 cancelled are not in this cube). |

## `inventory_health` (fact)

One row per product that is stocked, sold or on order: its stock position, a status and what to do. Not territory-bound: purchasing and admin see everything, marketing no supplier or order-size members; managers and reps none of it.

Joins: `products`.

### Measures

| Member | Type | Meaning |
|---|---|---|
| `inventory_health.dead_stock_items` | count | Dead stock only: in stock, no recent sale. |
| `inventory_health.excess_units_total` | sum | Units of all excess stock. |
| `inventory_health.excess_value_total` | sum | Value of all excess stock. |
| `inventory_health.items_at_risk` | count | Stockouts plus products to reorder now. |
| `inventory_health.overstock_items` | count | Overstock plus dead stock products. |
| `inventory_health.product_count` | count | Number of products. |
| `inventory_health.reorder_items` | count | Products with status reorder_now. |
| `inventory_health.stockout_items` | count | Products with status stockout. |
| `inventory_health.suggested_order_qty_total` | sum | Sum of the suggested order quantities. Supplier data. |
| `inventory_health.suggested_order_value_total` | sum | Sum of the suggested order values. Supplier data. |

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `inventory_health.daily_demand` | number | Average units sold per day over the demand window. |
| `inventory_health.days_of_cover` | number | Days the stock lasts at the current demand. |
| `inventory_health.excess_units` | number | Units above the target stock (overstock and dead stock). |
| `inventory_health.excess_value` | number | Value of the excess units. |
| `inventory_health.key` | number | Product key. |
| `inventory_health.last_sale_date` | time | Date of the product's last sale (a time dimension). |
| `inventory_health.lead_time_days` | number | Days from order to delivery. Supplier data. |
| `inventory_health.max_order_qty` | number | Vendor maximum order quantity. Supplier data. |
| `inventory_health.min_order_qty` | number | Vendor minimum order quantity. Supplier data. |
| `inventory_health.on_hand` | number | Units in stock. |
| `inventory_health.on_order` | number | Units on open purchase or work orders. |
| `inventory_health.product_name` | string | Product name. |
| `inventory_health.reason` | string | Why the status was given (in words). |
| `inventory_health.replenishment_type` | string | How it is replenished: purchase, manufacture or none. Supplier data. |
| `inventory_health.status` | string | Stock status: stockout, reorder_now, dead_stock, overstock, healthy, not_stocked or discontinued. |
| `inventory_health.suggested_discount_pct` | number | Suggested discount depth for the excess, in percent. |
| `inventory_health.suggested_order_qty` | number | Suggested quantity to order or make. Supplier data. |
| `inventory_health.suggested_order_value` | number | Suggested quantity times unit cost. Supplier data. |
| `inventory_health.unit_cost` | number | Cost per unit. Supplier data. |
| `inventory_health.vendor_id` | number | Vendor key. Supplier data. |
| `inventory_health.vendor_name` | string | Vendor name. Supplier data. |

## `offer_performance` (fact)

Special offers and what happened to unit sales during them versus the 28 days before. Descriptive only: no control group, so it also carries seasonality and trend. Marketing and admin.

### Measures

| Member | Type | Meaning |
|---|---|---|
| `offer_performance.avg_lift` | avg | Average of the per-offer lift (offers with no baseline are skipped; one offer with a tiny baseline can dominate it). |
| `offer_performance.days_during` | sum | Days offers ran. |
| `offer_performance.offers` | count | Number of offers. |
| `offer_performance.units_before` | sum | Units sold in the 28 days before offers. |
| `offer_performance.units_during` | sum | Units sold during offers. |

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `offer_performance.description` | string | Offer description. |
| `offer_performance.discount_band` | string | Discount depth band. |
| `offer_performance.discount_pct` | number | Discount in percent. |
| `offer_performance.end_date` | time | Offer end (a time dimension). |
| `offer_performance.key` | number | Offer key. |
| `offer_performance.lift` | number | Units per day during the offer over units per day in the 28 days before. |
| `offer_performance.offer_category` | string | Offer category. |
| `offer_performance.offer_type` | string | Type of offer. |
| `offer_performance.start_date` | time | Offer start (a time dimension). |

## `products`

Products and their categories: join target for both sales facts and the inventory cube.

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `products.category` | string | Product category (Bikes, Components, Clothing, Accessories; Uncategorized when none). |
| `products.color` | string | Product colour. |
| `products.key` | number | Product key. |
| `products.name` | string | Product name. |
| `products.subcategory` | string | Product subcategory (Uncategorized when none). |

## `reseller_sales` (fact)

Reseller channel order lines of the sales fact: one row per product on an order. Rejected and cancelled orders are left out. Row-level security limits reps and managers to their own territories.

Joins: `dates`, `due_dates`, `products`, `ship_dates`, `territories`.

### Measures

| Member | Type | Meaning |
|---|---|---|
| `reseller_sales.aov` | number | Revenue per placed order (a ratio inside one cube; across both channels use a ratio of revenue over orders). |
| `reseller_sales.discount` | sum | Discount amount given on the order lines. |
| `reseller_sales.gross_profit` | sum | Revenue minus product cost. Hidden from reps. |
| `reseller_sales.lines` | count | Number of order lines. |
| `reseller_sales.margin_pct` | number | Gross profit as a percentage of revenue, 0-100 (not a fraction). Hidden from reps. For a margin across both channels use a ratio of gross_profit over revenue with format pct. |
| `reseller_sales.orders` | count_distinct | Exact number of distinct orders. Right under any filter, but a rollup cannot serve it, so it can be slow at large scale. |
| `reseller_sales.orders_placed` | sum | Orders counted once, on their first line: exact and fast for any grouping or filter on the order's own date, territory or channel. Not the number of orders containing a given product: use orders for that. |
| `reseller_sales.product_cost` | sum | Standard cost of the products sold. Hidden from reps. |
| `reseller_sales.revenue` | sum | Sales amount of the order lines. |
| `reseller_sales.units` | sum | Quantity sold. |

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `reseller_sales.order_date` | time | When the order was placed (a time dimension: use it for a time axis). |
| `reseller_sales.order_line_id` | string | Key of the order line (order number and line number). |
| `reseller_sales.order_number` | string | The sales order number. |
| `reseller_sales.order_status` | number | Order status code: 1 in process, 2 approved, 3 backordered, 5 shipped (4 rejected and 6 cancelled are not in this cube). |

## `ship_dates`

The calendar in the role of the ship date: the date an order line shipped. Same fields as `dates` (month, quarter, fiscal year ...), shown with the prefix Ship.

A role of `dates`: the same calendar table and fields, joined by its own key; the fields are named "Ship ..." in reports (e.g. "Ship month name").

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `ship_dates.calendar_quarter` | number | Calendar quarter number, 1 to 4. |
| `ship_dates.calendar_year` | number | Calendar year. |
| `ship_dates.day_name` | string | Day of the week as text (Sunday ... Saturday). Sorted by `ship_dates.day_of_week`. |
| `ship_dates.day_of_week` | number | Day of the week as a number: 1 is Sunday, 7 is Saturday. |
| `ship_dates.fiscal_quarter` | number | Fiscal quarter number, 1 to 4 (the fiscal year starts in July: July to September is 1). |
| `ship_dates.fiscal_quarter_name` | string | Fiscal quarter as text: FQ1 to FQ4. Sorted by `ship_dates.fiscal_quarter`. |
| `ship_dates.fiscal_year` | number | Fiscal year, named after the year it ends in (the year starts in July: July 2020 is FY2021). |
| `ship_dates.full_date` | time | Calendar date (a time dimension). |
| `ship_dates.key` | number | Date key. |
| `ship_dates.month_name` | string | Month name (January ... December). Sorted by `ship_dates.month_of_year`. |
| `ship_dates.month_of_year` | number | Month number, 1 (January) to 12 (December). |
| `ship_dates.quarter_name` | string | Calendar quarter as text: Q1 to Q4. Sorted by `ship_dates.calendar_quarter`. |
| `ship_dates.week_of_year` | number | ISO week number of the year, 1 to 53. |
| `ship_dates.year_month` | string | Month and year as text, e.g. Jan 2012. Sorted by `ship_dates.year_month_number`. |
| `ship_dates.year_month_number` | number | Year and month as a number that sorts in time order: 201201 is January 2012. |
| `ship_dates.year_quarter` | string | Year and quarter as text, e.g. 2012 Q1. Sorted by `ship_dates.year_quarter_number`. |
| `ship_dates.year_quarter_number` | number | Year and quarter as a number that sorts in time order: 20121 is the first quarter of 2012. |

## `territories`

Sales territories: join target for the sales facts. The unit of row-level security.

### Dimensions

| Member | Type | Meaning |
|---|---|---|
| `territories.country` | string | Territory country. |
| `territories.group_name` | string | Territory group (North America, Europe, Pacific). |
| `territories.key` | number | Territory key. |
| `territories.region` | string | Sales territory region (Southwest, Canada, Germany, ...). Reps and managers only ever see the regions assigned to them. |
