
  create view "analytics_2"."stage"."stg_sales_order_header__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."sales_order_header"
),

renamed as (
    select
        sales_order_id,
        revision_number,
        order_date,
        due_date,
        ship_date,
        status,
        online_order_flag,
        sales_order_number,
        purchase_order_number,
        account_number,
        customer_id,
        sales_person_id,
        territory_id,
        bill_to_address_id,
        ship_to_address_id,
        ship_method_id,
        credit_card_id,
        credit_card_approval_code,
        currency_rate_id,
        sub_total,
        tax_amt,
        freight,
        total_due,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );