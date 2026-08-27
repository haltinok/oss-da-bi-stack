
    
    

select
    promotion_key as unique_field,
    count(*) as n_records

from "analytics_2"."mart"."dim_promotion"
where promotion_key is not null
group by promotion_key
having count(*) > 1


