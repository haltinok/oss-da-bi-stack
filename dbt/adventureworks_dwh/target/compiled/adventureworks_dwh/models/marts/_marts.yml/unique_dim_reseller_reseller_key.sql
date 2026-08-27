
    
    

select
    reseller_key as unique_field,
    count(*) as n_records

from "analytics_2"."mart"."dim_reseller"
where reseller_key is not null
group by reseller_key
having count(*) > 1


