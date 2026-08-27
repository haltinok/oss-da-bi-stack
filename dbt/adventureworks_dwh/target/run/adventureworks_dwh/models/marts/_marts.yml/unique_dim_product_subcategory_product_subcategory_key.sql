select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

select
    product_subcategory_key as unique_field,
    count(*) as n_records

from "analytics_2"."mart"."dim_product_subcategory"
where product_subcategory_key is not null
group by product_subcategory_key
having count(*) > 1



      
    ) dbt_internal_test