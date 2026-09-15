select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select reseller_key
from "analytics"."mart"."dim_reseller"
where reseller_key is null



      
    ) dbt_internal_test