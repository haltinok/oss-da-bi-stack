-- The distributor's data (schema dist): empty tables. `distributor-sim` (models/distributor/sim) fills them on its first start with three years of history up to now and then keeps adding
-- orders, invoices, payments and returns every few minutes, so the numbers always end today.
CREATE SCHEMA IF NOT EXISTS dist;

CREATE TABLE dist.meta (key text PRIMARY KEY, value text NOT NULL);       -- last_tick (when the simulator last ran), history_from

CREATE TABLE dist.dim_calendar (
    date_key int PRIMARY KEY, full_date date NOT NULL UNIQUE, calendar_year int NOT NULL, calendar_quarter int NOT NULL, month_of_year int NOT NULL,
    month_name text NOT NULL, year_month_number int NOT NULL, week_of_year int NOT NULL, day_of_week int NOT NULL, weekday_name text NOT NULL,
    is_weekend boolean NOT NULL, is_holiday boolean NOT NULL, holiday_name text NOT NULL DEFAULT ''
);

CREATE TABLE dist.dim_rep (rep_key int PRIMARY KEY, rep_username text NOT NULL UNIQUE, rep_name text NOT NULL, region text NOT NULL);

CREATE TABLE dist.dim_dealer (
    dealer_key int PRIMARY KEY, dealer_code text NOT NULL UNIQUE, dealer_name text NOT NULL, region text NOT NULL, province text NOT NULL, segment text NOT NULL,
    rep_key int NOT NULL, rep_username text NOT NULL, credit_limit numeric(14, 2) NOT NULL, payment_term_days int NOT NULL, opened_date date NOT NULL, is_active boolean NOT NULL DEFAULT true,
    order_weight numeric(10, 4) NOT NULL                                          -- how often it orders, relative to the others (the simulator's)
);

CREATE TABLE dist.dim_item (
    item_key int PRIMARY KEY, sku text NOT NULL UNIQUE, item_name text NOT NULL, category text NOT NULL, subcategory text NOT NULL, brand text NOT NULL,
    unit_price numeric(12, 2) NOT NULL, unit_cost numeric(12, 2) NOT NULL, case_size int NOT NULL, vat_rate numeric(4, 2) NOT NULL, popularity numeric(10, 6) NOT NULL,
    base_price numeric(12, 4) NOT NULL, cost_ratio numeric(6, 4) NOT NULL         -- the price at 2023-01 and the cost's share of it (the simulator's: prices follow an inflation index)
);

CREATE TABLE dist.fact_order_line (
    line_id bigserial PRIMARY KEY, order_number text NOT NULL, order_ts timestamp NOT NULL, order_date date NOT NULL, order_date_key int NOT NULL, dealer_key int NOT NULL, item_key int NOT NULL,
    quantity int NOT NULL, unit_price numeric(12, 2) NOT NULL, discount_pct numeric(5, 2) NOT NULL, net_amount numeric(14, 2) NOT NULL, cost_amount numeric(14, 2) NOT NULL
);
CREATE INDEX ON dist.fact_order_line (order_date);
CREATE INDEX ON dist.fact_order_line (dealer_key);
CREATE INDEX ON dist.fact_order_line (item_key);
CREATE INDEX ON dist.fact_order_line (order_number);

CREATE TABLE dist.fact_invoice (
    invoice_id bigserial PRIMARY KEY, invoice_number text NOT NULL UNIQUE, order_number text NOT NULL, invoice_date date NOT NULL, invoice_date_key int NOT NULL, due_date date NOT NULL,
    due_date_key int NOT NULL, dealer_key int NOT NULL, net_amount numeric(14, 2) NOT NULL, vat_amount numeric(14, 2) NOT NULL, gross_amount numeric(14, 2) NOT NULL, paid_amount numeric(14, 2) NOT NULL DEFAULT 0
);
CREATE INDEX ON dist.fact_invoice (invoice_date);
CREATE INDEX ON dist.fact_invoice (due_date);
CREATE INDEX ON dist.fact_invoice (dealer_key);

CREATE TABLE dist.fact_payment (
    payment_id bigserial PRIMARY KEY, invoice_id bigint NOT NULL, dealer_key int NOT NULL, paid_date date NOT NULL, paid_date_key int NOT NULL, amount numeric(14, 2) NOT NULL, method text NOT NULL
);
CREATE INDEX ON dist.fact_payment (paid_date);
CREATE INDEX ON dist.fact_payment (invoice_id);

CREATE TABLE dist.fact_return (
    return_id bigserial PRIMARY KEY, order_number text NOT NULL, item_key int NOT NULL, dealer_key int NOT NULL, return_date date NOT NULL, return_date_key int NOT NULL,
    quantity int NOT NULL, amount numeric(14, 2) NOT NULL, reason text NOT NULL
);
CREATE INDEX ON dist.fact_return (return_date);

CREATE TABLE dist.fact_stock (
    snapshot_date date NOT NULL, snapshot_date_key int NOT NULL, item_key int NOT NULL, on_hand int NOT NULL, reorder_point int NOT NULL, cover_days numeric(6, 1) NOT NULL,
    stock_value numeric(14, 2) NOT NULL, PRIMARY KEY (snapshot_date, item_key)
);

-- What is going to happen later: a payment on a date, a return on a date. The simulator moves a row into fact_payment / fact_return when its day comes.
CREATE TABLE dist.plan (plan_id bigserial PRIMARY KEY, kind text NOT NULL CHECK (kind IN ('payment', 'return')), due_date date NOT NULL, ref text NOT NULL, payload jsonb NOT NULL);       -- ref: the invoice (payment) or the order (return) it is about
CREATE INDEX ON dist.plan (due_date);
