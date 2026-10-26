# Evaluating the dashboard-author skill

Give the agent each request cold (no hints beyond the skill). A result passes when **all** of its checks hold.

Always: `scripts/dashspec validate` is `ok`; `scripts/dashspec build` leaves the committed JSON current; the PR touches `dashboards/` only;
`shot.py` shows no console error and no sideways scroll at 390 px for every role the page lists; the agent did not invent a member.

## 1. A sales overview for managers, in English
> "A monthly sales overview for the regional managers: revenue, orders and average order value, revenue by month split by channel, the top
> products, and a table of the latest orders. Let me filter by fiscal year and region, and click a month to focus its fiscal year."

- `roles` include `manager` and the page uses no profit/margin member that a manager may not see (managers may, reps may not: if `rep` is
  listed, there is no profit member).
- KPIs use `sum`/`ratio` across the two channels, not one channel only.
- A `fy` filter and a region filter exist; the month chart has `on_click: { set_filter: fy }`.
- With the stack up: Revenue, Orders and Avg order value equal `spike/cube/check.py`'s totals for the same fiscal year, and equal the
  tiles of `/` (the sales dashboard) for that year.

## 2. An inventory health page in Turkish, in lira
> "Envanter sağlığını gösteren bir sayfa: stoksuz, sipariş gerekli ve fazla stoklu ürün sayıları, duruma göre dağılım, önerilen sipariş
> tutarı ve fazla stok listesi. Türkçe olsun, tutarlar lira ile gösterilsin. Satın alma ekibi kullanacak."

- `locale: tr-TR`, `currency: TRY`; every title, label and the description are Turkish.
- `roles` are `purchasing` (and `admin`), not `marketing`/`manager`/`rep`: supplier and order data are for purchasing only.
- Only `inventory_health` / `products` members (no sales cubes); no Approve or write of any kind.
- The data is not in lira: the page says so (a `text` panel) instead of presenting converted amounts.

## 3. A regional page that must respect row-level security
> "A page for the sales reps showing revenue and orders for their own territories: by month, by country and the top products."

- `roles: [rep]` (managers optionally) and **no** `gross_profit`, `margin_pct` or `product_cost` anywhere (the validator fails it otherwise).
- No filter or member of the `customers` cube; no territory filter that tries to widen access (access is Cube's row-level security, not the
  spec's): the agent must not add a "territory" select that implies a rep can pick another territory's data. (A country select is fine:
  Cube still limits the rows.)
- As a rep and as a manager the page renders with different numbers, never an error (check with `shot.py --role rep` and `--role manager`,
  and with the stack up, as `de_rep` and `na_manager`).

## Scoring
Record per request: passed or not, the number of validator rounds, anything the agent invented or got wrong. The point of the skill is
that a new dashboard is a reviewed YAML file in minutes and the numbers are consistent by construction.
