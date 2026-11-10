-- Seed data for the "distributor" example model: a Turkish SME that sells to dealers (bayi) and collects payments (tahsilat).
-- Deterministic (hash-based, no random()), a few thousand rows, no simulator.  psql -f init.sql, or mount it into /docker-entrypoint-initdb.d.
create schema if not exists dist;

create table dist.dim_calendar as
select to_char(d, 'YYYYMMDD')::int as date_key, d::date as full_date,
       extract(year from d)::int as calendar_year, extract(quarter from d)::int as calendar_quarter, extract(month from d)::int as month_of_year,
       (array['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'])[extract(month from d)::int] as month_name,
       extract(year from d)::int * 100 + extract(month from d)::int as year_month_number
from generate_series('2024-01-01'::date, '2026-03-31'::date, '1 day') d;

create table dist.dim_dealer as
select g as dealer_key, 'Bayi ' || lpad(g::text, 3, '0') as dealer_name,
       (array['Marmara','Ege','İç Anadolu','Akdeniz','Karadeniz','Doğu Anadolu'])[1 + g % 6] as region,
       (array['İstanbul','İzmir','Ankara','Antalya','Trabzon','Erzurum'])[1 + g % 6] as city,
       (array['Büyük','Orta','Küçük'])[1 + (g / 6) % 3] as segment
from generate_series(1, 48) g;

create table dist.dim_item as
select g as item_key, 'Ürün ' || lpad(g::text, 3, '0') as item_name,
       (array['Gıda','Temizlik','Kırtasiye','Hırdavat'])[1 + g % 4] as category,
       (array['Anadolu','Marmara','Ege','Toros','Karadeniz'])[1 + (g / 4) % 5] as brand
from generate_series(1, 60) g;

create table dist.fact_order_line as
select g::text as line_id, 'S' || lpad(((g + 2) / 3)::text, 5, '0') as order_number,
       1 + (hashtext('d' || g) & 2147483647) % 48 as dealer_key,
       1 + (hashtext('i' || g) & 2147483647) % 60 as item_key,
       c.full_date as order_date, c.date_key as order_date_key,
       q as quantity,
       round((q * (20 + (hashtext('p' || g) & 2147483647) % 180) * (1 - ((hashtext('x' || g) & 2147483647) % 4) * 0.05))::numeric, 2) as amount
from (select g, 1 + (hashtext('q' || g) & 2147483647) % 40 as q, date '2024-01-01' + ((g + 2) / 3) % 820 as dt from generate_series(1, 6000) g) s
join dist.dim_calendar c on c.full_date = s.dt;

create table dist.fact_payment as
select g as payment_id,
       1 + (hashtext('pd' || g) & 2147483647) % 48 as dealer_key,
       c.full_date as paid_date, c.date_key as paid_date_key, d.date_key as due_date_key,
       (array['Havale','Çek','Kredi kartı','Nakit'])[1 + (hashtext('pm' || g) & 2147483647) % 4] as method,
       round((500 + (hashtext('pa' || g) & 2147483647) % 9500)::numeric, 2) as amount
from (select g, date '2024-02-01' + (g % 780) as pd, date '2024-02-01' + (g % 780) - ((hashtext('dd' || g) & 2147483647) % 20) as dd from generate_series(1, 2500) g) s
join dist.dim_calendar c on c.full_date = s.pd
join dist.dim_calendar d on d.full_date = s.dd;
