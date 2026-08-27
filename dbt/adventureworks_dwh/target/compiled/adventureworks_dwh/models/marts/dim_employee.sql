with employee as (
    select * from "analytics_2"."stage"."stg_employee"
),

person as (
    select * from "analytics_2"."stage"."stg_person"
),

email as (
    select distinct on (business_entity_id)
        business_entity_id,
        email_address
    from "analytics_2"."stage"."stg_email_address"
    order by business_entity_id, email_address_id
),

sales_person as (
    select * from "analytics_2"."stage"."stg_sales_person"
),

emp_dept_hist as (
    select distinct on (business_entity_id)
        business_entity_id,
        department_id,
        shift_id
    from "analytics_2"."stage"."stg_employee_department_history"
    where end_date is null
    order by business_entity_id, start_date desc
),

department as (
    select * from "analytics_2"."stage"."stg_department"
),

renamed as (
    select
        e.business_entity_id as employee_key,
        e.national_id_number as employee_national_id_alternate_key,
        sp.territory_id as sales_territory_key,
        p.first_name,
        p.last_name,
        p.middle_name,
        p.name_style,
        p.title,
        e.hire_date,
        e.birth_date,
        e.login_id,
        em.email_address,
        e.marital_status,
        e.salaried_flag,
        e.gender,
        e.vacation_hours,
        e.sick_leave_hours,
        e.current_flag,
        (sp.business_entity_id is not null) as sales_person_flag,
        d.name as department_name
    from employee e
    left join person p on e.business_entity_id = p.business_entity_id
    left join email em on e.business_entity_id = em.business_entity_id
    left join sales_person sp on e.business_entity_id = sp.business_entity_id
    left join emp_dept_hist edh on e.business_entity_id = edh.business_entity_id
    left join department d on edh.department_id = d.department_id
)

select * from renamed