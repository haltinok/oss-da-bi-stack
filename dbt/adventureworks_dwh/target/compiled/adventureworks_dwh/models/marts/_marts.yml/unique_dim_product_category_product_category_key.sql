
    
    

select
    product_category_key as unique_field,
    count(*) as n_records

from "analytics_2"."mart"."dim_product_category"
where product_category_key is not null
group by product_category_key
having count(*) > 1


