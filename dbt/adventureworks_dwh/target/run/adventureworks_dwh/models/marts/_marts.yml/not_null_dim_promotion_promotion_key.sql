select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select promotion_key
from "analytics_2"."mart"."dim_promotion"
where promotion_key is null



      
    ) dbt_internal_test