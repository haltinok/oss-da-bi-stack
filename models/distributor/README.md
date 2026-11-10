# The "distributor" example model

A second Cube model, deliberately **not** AdventureWorks and not a sales demo in the same shape: a Turkish SME that sells to dealers (bayi) and collects payments (tahsilat).
It exists to prove that the app (renderer, designer, builder, dashspec, lab, admin, auth) knows no model: see [`PLAN-decouple.md`](../../PLAN-decouple.md).

| | |
|---|---|
| Facts | `orders` (order lines), `payments` |
| Dimensions | `dealers`, `items`, `calendar`, `maturity_dates` (the calendar again, in the role of a due date) |
| Text field with `sort_by` | `calendar.month_name` (sorts by the month number) |
| No | channels, fiscal year, territories |
| Database | **Postgres**, schema `dist`: `postgres/init.sql` (deterministic, 6,000 order lines and 2,500 payments, 2024-01 to 2026-03) |

```bash
scripts/dashspec validate --model models/distributor/cube models/distributor/dashboards/*.yml
```

Load the data: `psql -f models/distributor/postgres/init.sql`, or mount the file into `/docker-entrypoint-initdb.d/` of a Postgres container.
