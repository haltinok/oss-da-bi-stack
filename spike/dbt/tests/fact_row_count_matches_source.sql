-- Reconciliation vs source: every order line in the source (detail joined to its
-- header) must be in exactly one fact, and the amounts must add up. Returns a
-- row (= failure) when either differs.
with src as (
    select count(*) as n, sum(d.line_total) as amount
    from {{ ref('stg_sales_order_detail') }} d
    inner join {{ ref('stg_sales_order_header') }} h on h.sales_order_id = d.sales_order_id
),

facts as (
    select count(*) as n, sum(sales_amount) as amount
    from (
        select sales_amount from {{ ref('fact_internet_sales') }}
        union all
        select sales_amount from {{ ref('fact_reseller_sales') }}
    ) f
)

select src.n as source_rows, facts.n as fact_rows, src.amount as source_amount, facts.amount as fact_amount
from src cross join facts
where src.n <> facts.n or abs(src.amount - facts.amount) > 0.01
