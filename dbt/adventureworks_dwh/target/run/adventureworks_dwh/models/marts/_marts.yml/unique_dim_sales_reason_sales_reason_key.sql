select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

select
    sales_reason_key as unique_field,
    count(*) as n_records

from "analytics_2"."mart"."dim_sales_reason"
where sales_reason_key is not null
group by sales_reason_key
having count(*) > 1



      
    ) dbt_internal_test