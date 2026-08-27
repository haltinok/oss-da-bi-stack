select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select product_subcategory_key
from "analytics_2"."mart"."dim_product_subcategory"
where product_subcategory_key is null



      
    ) dbt_internal_test