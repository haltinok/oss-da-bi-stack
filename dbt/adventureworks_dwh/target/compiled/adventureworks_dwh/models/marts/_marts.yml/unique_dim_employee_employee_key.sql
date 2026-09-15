
    
    

select
    employee_key as unique_field,
    count(*) as n_records

from "analytics"."mart"."dim_employee"
where employee_key is not null
group by employee_key
having count(*) > 1


