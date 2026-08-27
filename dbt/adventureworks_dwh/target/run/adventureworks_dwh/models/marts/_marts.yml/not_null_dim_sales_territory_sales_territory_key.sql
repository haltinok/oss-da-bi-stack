select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select sales_territory_key
from "analytics_2"."mart"."dim_sales_territory"
where sales_territory_key is null



      
    ) dbt_internal_test