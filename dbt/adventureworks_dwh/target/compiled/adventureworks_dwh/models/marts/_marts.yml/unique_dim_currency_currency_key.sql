
    
    

select
    currency_key as unique_field,
    count(*) as n_records

from "analytics_2"."mart"."dim_currency"
where currency_key is not null
group by currency_key
having count(*) > 1


