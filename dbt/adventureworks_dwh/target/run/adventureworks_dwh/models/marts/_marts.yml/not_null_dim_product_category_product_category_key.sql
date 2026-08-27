select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select product_category_key
from "analytics_2"."mart"."dim_product_category"
where product_category_key is null



      
    ) dbt_internal_test