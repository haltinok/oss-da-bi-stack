select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select sales_reason_key
from "analytics"."mart"."dim_sales_reason"
where sales_reason_key is null



      
    ) dbt_internal_test