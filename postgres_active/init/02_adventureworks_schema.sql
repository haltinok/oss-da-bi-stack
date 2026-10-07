-- AdventureWorks2016 OLTP tables for the postgres_active sandbox.
--
-- GENERATED FILE -- do not edit by hand.
-- Regenerate with: python3 scripts/gen_adventureworks_schema.py
--
-- Source: the warehouse analytics.raw schema (loaded from SQL Server by
-- dlt). dlt's bookkeeping columns are dropped and the AdventureWorks
-- primary keys are restored. Foreign keys are deliberately NOT enforced:
-- the seed is a random 10% sample per table and the simulator inserts
-- freely, so referential integrity is illustrative rather than enforced.

\set ON_ERROR_STOP on

create table if not exists public."address" (
    "spatial_location"               text,
    "rowguid"                        text not null,
    "address_id"                     bigint not null,
    "address_line1"                  text not null,
    "city"                           text not null,
    "state_province_id"              bigint not null,
    "postal_code"                    text not null,
    "modified_date"                  timestamptz not null,
    "address_line2"                  text,
    primary key ("address_id")
);
create index if not exists "address_modified_date_idx" on public."address" (modified_date);

create table if not exists public."address_type" (
    "rowguid"                        text not null,
    "address_type_id"                bigint not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("address_type_id")
);
create index if not exists "address_type_modified_date_idx" on public."address_type" (modified_date);

create table if not exists public."aw_build_version" (
    "system_information_id"          bigint not null,
    "database_version"               text not null,
    "version_date"                   timestamptz not null,
    "modified_date"                  timestamptz not null,
    primary key ("system_information_id")
);
create index if not exists "aw_build_version_modified_date_idx" on public."aw_build_version" (modified_date);

create table if not exists public."bill_of_materials" (
    "bill_of_materials_id"           bigint not null,
    "component_id"                   bigint not null,
    "start_date"                     timestamptz not null,
    "unit_measure_code"              text not null,
    "bom_level"                      bigint not null,
    "per_assembly_qty"               numeric not null,
    "modified_date"                  timestamptz not null,
    "end_date"                       timestamptz,
    "product_assembly_id"            bigint,
    primary key ("bill_of_materials_id")
);
create index if not exists "bill_of_materials_modified_date_idx" on public."bill_of_materials" (modified_date);

create table if not exists public."business_entity" (
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id")
);
create index if not exists "business_entity_modified_date_idx" on public."business_entity" (modified_date);

create table if not exists public."business_entity_address" (
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "address_id"                     bigint not null,
    "address_type_id"                bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id", "address_id", "address_type_id")
);
create index if not exists "business_entity_address_modified_date_idx" on public."business_entity_address" (modified_date);

create table if not exists public."business_entity_contact" (
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "person_id"                      bigint not null,
    "contact_type_id"                bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id", "person_id", "contact_type_id")
);
create index if not exists "business_entity_contact_modified_date_idx" on public."business_entity_contact" (modified_date);

create table if not exists public."contact_type" (
    "contact_type_id"                bigint not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("contact_type_id")
);
create index if not exists "contact_type_modified_date_idx" on public."contact_type" (modified_date);

create table if not exists public."country_region" (
    "country_region_code"            text not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("country_region_code")
);
create index if not exists "country_region_modified_date_idx" on public."country_region" (modified_date);

create table if not exists public."country_region_currency" (
    "country_region_code"            text not null,
    "currency_code"                  text not null,
    "modified_date"                  timestamptz not null,
    primary key ("country_region_code", "currency_code")
);
create index if not exists "country_region_currency_modified_date_idx" on public."country_region_currency" (modified_date);

create table if not exists public."credit_card" (
    "credit_card_id"                 bigint not null,
    "card_type"                      text not null,
    "card_number"                    text not null,
    "exp_month"                      bigint not null,
    "exp_year"                       bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("credit_card_id")
);
create index if not exists "credit_card_modified_date_idx" on public."credit_card" (modified_date);

create table if not exists public."culture" (
    "culture_id"                     text not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("culture_id")
);
create index if not exists "culture_modified_date_idx" on public."culture" (modified_date);

create table if not exists public."currency" (
    "currency_code"                  text not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("currency_code")
);
create index if not exists "currency_modified_date_idx" on public."currency" (modified_date);

create table if not exists public."currency_rate" (
    "currency_rate_id"               bigint not null,
    "currency_rate_date"             timestamptz not null,
    "from_currency_code"             text not null,
    "to_currency_code"               text not null,
    "average_rate"                   numeric not null,
    "end_of_day_rate"                numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("currency_rate_id")
);
create index if not exists "currency_rate_modified_date_idx" on public."currency_rate" (modified_date);

create table if not exists public."customer" (
    "rowguid"                        text not null,
    "customer_id"                    bigint not null,
    "store_id"                       bigint,
    "territory_id"                   bigint,
    "account_number"                 text not null,
    "modified_date"                  timestamptz not null,
    "person_id"                      bigint,
    primary key ("customer_id")
);
create index if not exists "customer_modified_date_idx" on public."customer" (modified_date);

create table if not exists public."database_log" (
    "xml_event"                      text not null,
    "database_log_id"                bigint not null,
    "post_time"                      timestamptz not null,
    "database_user"                  text not null,
    "event"                          text not null,
    "schema"                         text,
    "object"                         text,
    "tsql"                           text not null,
    primary key ("database_log_id")
);

create table if not exists public."department" (
    "department_id"                  bigint not null,
    "name"                           text not null,
    "group_name"                     text not null,
    "modified_date"                  timestamptz not null,
    primary key ("department_id")
);
create index if not exists "department_modified_date_idx" on public."department" (modified_date);

create table if not exists public."document" (
    "document_node"                  text not null,
    "rowguid"                        text not null,
    "document_level"                 bigint,
    "title"                          text not null,
    "owner"                          bigint not null,
    "folder_flag"                    boolean not null,
    "file_name"                      text not null,
    "file_extension"                 text not null,
    "revision"                       text not null,
    "change_number"                  bigint not null,
    "status"                         bigint not null,
    "modified_date"                  timestamptz not null,
    "document"                       bytea,
    "document_summary"               text,
    primary key ("document_node")
);
create index if not exists "document_modified_date_idx" on public."document" (modified_date);

create table if not exists public."email_address" (
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "email_address_id"               bigint not null,
    "email_address"                  text,
    "modified_date"                  timestamptz not null,
    primary key ("email_address_id")
);
create index if not exists "email_address_modified_date_idx" on public."email_address" (modified_date);

create table if not exists public."employee" (
    "organization_node"              text,
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "national_id_number"             text not null,
    "login_id"                       text not null,
    "job_title"                      text not null,
    "birth_date"                     date not null,
    "marital_status"                 text not null,
    "gender"                         text not null,
    "hire_date"                      date not null,
    "salaried_flag"                  boolean not null,
    "vacation_hours"                 bigint not null,
    "sick_leave_hours"               bigint not null,
    "current_flag"                   boolean not null,
    "modified_date"                  timestamptz not null,
    "organization_level"             bigint,
    primary key ("business_entity_id")
);
create index if not exists "employee_modified_date_idx" on public."employee" (modified_date);

create table if not exists public."employee_department_history" (
    "business_entity_id"             bigint not null,
    "department_id"                  bigint not null,
    "shift_id"                       bigint not null,
    "start_date"                     date not null,
    "modified_date"                  timestamptz not null,
    "end_date"                       date,
    primary key ("business_entity_id", "department_id", "shift_id", "start_date")
);
create index if not exists "employee_department_history_modified_date_idx" on public."employee_department_history" (modified_date);

create table if not exists public."employee_pay_history" (
    "business_entity_id"             bigint not null,
    "rate_change_date"               timestamptz not null,
    "rate"                           numeric not null,
    "pay_frequency"                  bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id", "rate_change_date")
);
create index if not exists "employee_pay_history_modified_date_idx" on public."employee_pay_history" (modified_date);

create table if not exists public."illustration" (
    "diagram"                        text,
    "illustration_id"                bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("illustration_id")
);
create index if not exists "illustration_modified_date_idx" on public."illustration" (modified_date);

create table if not exists public."job_candidate" (
    "resume"                         text,
    "job_candidate_id"               bigint not null,
    "modified_date"                  timestamptz not null,
    "business_entity_id"             bigint,
    primary key ("job_candidate_id")
);
create index if not exists "job_candidate_modified_date_idx" on public."job_candidate" (modified_date);

create table if not exists public."location" (
    "location_id"                    bigint not null,
    "name"                           text not null,
    "cost_rate"                      numeric not null,
    "availability"                   numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("location_id")
);
create index if not exists "location_modified_date_idx" on public."location" (modified_date);

create table if not exists public."password" (
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "password_hash"                  text not null,
    "password_salt"                  text not null,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id")
);
create index if not exists "password_modified_date_idx" on public."password" (modified_date);

create table if not exists public."person" (
    "additional_contact_info"        text,
    "demographics"                   text,
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "person_type"                    text not null,
    "name_style"                     boolean not null,
    "first_name"                     text not null,
    "middle_name"                    text,
    "last_name"                      text not null,
    "email_promotion"                bigint not null,
    "modified_date"                  timestamptz not null,
    "title"                          text,
    "suffix"                         text,
    primary key ("business_entity_id")
);
create index if not exists "person_modified_date_idx" on public."person" (modified_date);

create table if not exists public."person_credit_card" (
    "business_entity_id"             bigint not null,
    "credit_card_id"                 bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id", "credit_card_id")
);
create index if not exists "person_credit_card_modified_date_idx" on public."person_credit_card" (modified_date);

create table if not exists public."person_phone" (
    "business_entity_id"             bigint not null,
    "phone_number"                   text not null,
    "phone_number_type_id"           bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id", "phone_number", "phone_number_type_id")
);
create index if not exists "person_phone_modified_date_idx" on public."person_phone" (modified_date);

create table if not exists public."phone_number_type" (
    "phone_number_type_id"           bigint not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("phone_number_type_id")
);
create index if not exists "phone_number_type_modified_date_idx" on public."phone_number_type" (modified_date);

create table if not exists public."product" (
    "rowguid"                        text not null,
    "product_id"                     bigint not null,
    "name"                           text not null,
    "product_number"                 text not null,
    "make_flag"                      boolean not null,
    "finished_goods_flag"            boolean not null,
    "safety_stock_level"             bigint not null,
    "reorder_point"                  bigint not null,
    "standard_cost"                  numeric not null,
    "list_price"                     numeric not null,
    "days_to_manufacture"            bigint not null,
    "sell_start_date"                timestamptz not null,
    "modified_date"                  timestamptz not null,
    "color"                          text,
    "class"                          text,
    "weight_unit_measure_code"       text,
    "weight"                         numeric,
    "size"                           text,
    "size_unit_measure_code"         text,
    "product_line"                   text,
    "style"                          text,
    "product_subcategory_id"         bigint,
    "product_model_id"               bigint,
    "sell_end_date"                  timestamptz,
    primary key ("product_id")
);
create index if not exists "product_modified_date_idx" on public."product" (modified_date);

create table if not exists public."product_category" (
    "rowguid"                        text not null,
    "product_category_id"            bigint not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_category_id")
);
create index if not exists "product_category_modified_date_idx" on public."product_category" (modified_date);

create table if not exists public."product_cost_history" (
    "product_id"                     bigint not null,
    "start_date"                     timestamptz not null,
    "end_date"                       timestamptz,
    "standard_cost"                  numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_id", "start_date")
);
create index if not exists "product_cost_history_modified_date_idx" on public."product_cost_history" (modified_date);

create table if not exists public."product_description" (
    "rowguid"                        text not null,
    "product_description_id"         bigint not null,
    "description"                    text not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_description_id")
);
create index if not exists "product_description_modified_date_idx" on public."product_description" (modified_date);

create table if not exists public."product_document" (
    "document_node"                  text not null,
    "product_id"                     bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("document_node", "product_id")
);
create index if not exists "product_document_modified_date_idx" on public."product_document" (modified_date);

create table if not exists public."product_inventory" (
    "rowguid"                        text not null,
    "product_id"                     bigint not null,
    "location_id"                    bigint not null,
    "shelf"                          text not null,
    "bin"                            bigint not null,
    "quantity"                       bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_id", "location_id")
);
create index if not exists "product_inventory_modified_date_idx" on public."product_inventory" (modified_date);

create table if not exists public."product_list_price_history" (
    "product_id"                     bigint not null,
    "start_date"                     timestamptz not null,
    "end_date"                       timestamptz,
    "list_price"                     numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_id", "start_date")
);
create index if not exists "product_list_price_history_modified_date_idx" on public."product_list_price_history" (modified_date);

create table if not exists public."product_model" (
    "catalog_description"            text,
    "instructions"                   text,
    "rowguid"                        text not null,
    "product_model_id"               bigint not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_model_id")
);
create index if not exists "product_model_modified_date_idx" on public."product_model" (modified_date);

create table if not exists public."product_model_illustration" (
    "product_model_id"               bigint not null,
    "illustration_id"                bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_model_id", "illustration_id")
);
create index if not exists "product_model_illustration_modified_date_idx" on public."product_model_illustration" (modified_date);

create table if not exists public."product_model_product_description_culture" (
    "product_model_id"               bigint not null,
    "product_description_id"         bigint not null,
    "culture_id"                     text not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_model_id", "product_description_id", "culture_id")
);
create index if not exists "product_model_product_description_culture_modified_date_idx" on public."product_model_product_description_culture" (modified_date);

create table if not exists public."product_photo" (
    "product_photo_id"               bigint not null,
    "thumb_nail_photo"               bytea,
    "thumbnail_photo_file_name"      text,
    "large_photo"                    bytea,
    "large_photo_file_name"          text,
    "modified_date"                  timestamptz not null,
    primary key ("product_photo_id")
);
create index if not exists "product_photo_modified_date_idx" on public."product_photo" (modified_date);

create table if not exists public."product_product_photo" (
    "product_id"                     bigint not null,
    "product_photo_id"               bigint not null,
    "primary"                        boolean not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_id", "product_photo_id")
);
create index if not exists "product_product_photo_modified_date_idx" on public."product_product_photo" (modified_date);

create table if not exists public."product_review" (
    "product_review_id"              bigint not null,
    "product_id"                     bigint not null,
    "reviewer_name"                  text not null,
    "review_date"                    timestamptz not null,
    "email_address"                  text not null,
    "rating"                         bigint not null,
    "comments"                       text,
    "modified_date"                  timestamptz not null,
    primary key ("product_review_id")
);
create index if not exists "product_review_modified_date_idx" on public."product_review" (modified_date);

create table if not exists public."product_subcategory" (
    "rowguid"                        text not null,
    "product_subcategory_id"         bigint not null,
    "product_category_id"            bigint not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_subcategory_id")
);
create index if not exists "product_subcategory_modified_date_idx" on public."product_subcategory" (modified_date);

create table if not exists public."product_vendor" (
    "product_id"                     bigint not null,
    "business_entity_id"             bigint not null,
    "average_lead_time"              bigint not null,
    "standard_price"                 numeric not null,
    "last_receipt_cost"              numeric,
    "last_receipt_date"              timestamptz,
    "min_order_qty"                  bigint not null,
    "max_order_qty"                  bigint not null,
    "on_order_qty"                   bigint,
    "unit_measure_code"              text not null,
    "modified_date"                  timestamptz not null,
    primary key ("product_id", "business_entity_id")
);
create index if not exists "product_vendor_modified_date_idx" on public."product_vendor" (modified_date);

create table if not exists public."purchase_order_detail" (
    "purchase_order_id"              bigint not null,
    "purchase_order_detail_id"       bigint not null,
    "due_date"                       timestamptz not null,
    "order_qty"                      bigint not null,
    "product_id"                     bigint not null,
    "unit_price"                     numeric not null,
    "line_total"                     numeric not null,
    "received_qty"                   numeric not null,
    "rejected_qty"                   numeric not null,
    "stocked_qty"                    numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("purchase_order_id", "purchase_order_detail_id")
);
create index if not exists "purchase_order_detail_modified_date_idx" on public."purchase_order_detail" (modified_date);

create table if not exists public."purchase_order_header" (
    "purchase_order_id"              bigint not null,
    "revision_number"                bigint not null,
    "status"                         bigint not null,
    "employee_id"                    bigint not null,
    "vendor_id"                      bigint not null,
    "ship_method_id"                 bigint not null,
    "order_date"                     timestamptz not null,
    "ship_date"                      timestamptz,
    "sub_total"                      numeric not null,
    "tax_amt"                        numeric not null,
    "freight"                        numeric not null,
    "total_due"                      numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("purchase_order_id")
);
create index if not exists "purchase_order_header_modified_date_idx" on public."purchase_order_header" (modified_date);

create table if not exists public."sales_order_detail" (
    "rowguid"                        text not null,
    "sales_order_id"                 bigint not null,
    "sales_order_detail_id"          bigint not null,
    "carrier_tracking_number"        text,
    "order_qty"                      bigint not null,
    "product_id"                     bigint not null,
    "special_offer_id"               bigint not null,
    "unit_price"                     numeric not null,
    "unit_price_discount"            numeric not null,
    "line_total"                     numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("sales_order_id", "sales_order_detail_id")
);
create index if not exists "sales_order_detail_modified_date_idx" on public."sales_order_detail" (modified_date);

create table if not exists public."sales_order_header" (
    "rowguid"                        text not null,
    "sales_order_id"                 bigint not null,
    "revision_number"                bigint not null,
    "order_date"                     timestamptz not null,
    "due_date"                       timestamptz not null,
    "ship_date"                      timestamptz,
    "status"                         bigint not null,
    "online_order_flag"              boolean not null,
    "sales_order_number"             text not null,
    "purchase_order_number"          text,
    "account_number"                 text,
    "customer_id"                    bigint not null,
    "sales_person_id"                bigint,
    "territory_id"                   bigint,
    "bill_to_address_id"             bigint not null,
    "ship_to_address_id"             bigint not null,
    "ship_method_id"                 bigint not null,
    "credit_card_id"                 bigint,
    "credit_card_approval_code"      text,
    "sub_total"                      numeric not null,
    "tax_amt"                        numeric not null,
    "freight"                        numeric not null,
    "total_due"                      numeric not null,
    "modified_date"                  timestamptz not null,
    "currency_rate_id"               bigint,
    primary key ("sales_order_id")
);
create index if not exists "sales_order_header_modified_date_idx" on public."sales_order_header" (modified_date);

create table if not exists public."sales_order_header_sales_reason" (
    "sales_order_id"                 bigint not null,
    "sales_reason_id"                bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("sales_order_id", "sales_reason_id")
);
create index if not exists "sales_order_header_sales_reason_modified_date_idx" on public."sales_order_header_sales_reason" (modified_date);

create table if not exists public."sales_person" (
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "bonus"                          numeric not null,
    "commission_pct"                 numeric not null,
    "sales_ytd"                      numeric not null,
    "sales_last_year"                numeric not null,
    "modified_date"                  timestamptz not null,
    "territory_id"                   bigint,
    "sales_quota"                    numeric,
    primary key ("business_entity_id")
);
create index if not exists "sales_person_modified_date_idx" on public."sales_person" (modified_date);

create table if not exists public."sales_person_quota_history" (
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "quota_date"                     timestamptz not null,
    "sales_quota"                    numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id", "quota_date")
);
create index if not exists "sales_person_quota_history_modified_date_idx" on public."sales_person_quota_history" (modified_date);

create table if not exists public."sales_reason" (
    "sales_reason_id"                bigint not null,
    "name"                           text not null,
    "reason_type"                    text not null,
    "modified_date"                  timestamptz not null,
    primary key ("sales_reason_id")
);
create index if not exists "sales_reason_modified_date_idx" on public."sales_reason" (modified_date);

create table if not exists public."sales_tax_rate" (
    "rowguid"                        text not null,
    "sales_tax_rate_id"              bigint not null,
    "state_province_id"              bigint not null,
    "tax_type"                       bigint not null,
    "tax_rate"                       numeric not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("sales_tax_rate_id")
);
create index if not exists "sales_tax_rate_modified_date_idx" on public."sales_tax_rate" (modified_date);

create table if not exists public."sales_territory" (
    "rowguid"                        text not null,
    "territory_id"                   bigint not null,
    "name"                           text not null,
    "country_region_code"            text not null,
    "group"                          text not null,
    "sales_ytd"                      numeric not null,
    "sales_last_year"                numeric not null,
    "cost_ytd"                       numeric not null,
    "cost_last_year"                 numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("territory_id")
);
create index if not exists "sales_territory_modified_date_idx" on public."sales_territory" (modified_date);

create table if not exists public."sales_territory_history" (
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "territory_id"                   bigint not null,
    "start_date"                     timestamptz not null,
    "end_date"                       timestamptz,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id", "territory_id", "start_date")
);
create index if not exists "sales_territory_history_modified_date_idx" on public."sales_territory_history" (modified_date);

create table if not exists public."scrap_reason" (
    "scrap_reason_id"                bigint not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("scrap_reason_id")
);
create index if not exists "scrap_reason_modified_date_idx" on public."scrap_reason" (modified_date);

create table if not exists public."shift" (
    "shift_id"                       bigint not null,
    "name"                           text not null,
    "start_time"                     time not null,
    "end_time"                       time not null,
    "modified_date"                  timestamptz not null,
    primary key ("shift_id")
);
create index if not exists "shift_modified_date_idx" on public."shift" (modified_date);

create table if not exists public."ship_method" (
    "rowguid"                        text not null,
    "ship_method_id"                 bigint not null,
    "name"                           text not null,
    "ship_base"                      numeric not null,
    "ship_rate"                      numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("ship_method_id")
);
create index if not exists "ship_method_modified_date_idx" on public."ship_method" (modified_date);

create table if not exists public."shopping_cart_item" (
    "shopping_cart_item_id"          bigint not null,
    "shopping_cart_id"               text not null,
    "quantity"                       bigint not null,
    "product_id"                     bigint not null,
    "date_created"                   timestamptz not null,
    "modified_date"                  timestamptz not null,
    primary key ("shopping_cart_item_id")
);
create index if not exists "shopping_cart_item_modified_date_idx" on public."shopping_cart_item" (modified_date);

create table if not exists public."special_offer" (
    "rowguid"                        text not null,
    "special_offer_id"               bigint not null,
    "description"                    text not null,
    "discount_pct"                   numeric not null,
    "type"                           text not null,
    "category"                       text not null,
    "start_date"                     timestamptz not null,
    "end_date"                       timestamptz not null,
    "min_qty"                        bigint not null,
    "modified_date"                  timestamptz not null,
    "max_qty"                        bigint,
    primary key ("special_offer_id")
);
create index if not exists "special_offer_modified_date_idx" on public."special_offer" (modified_date);

create table if not exists public."special_offer_product" (
    "rowguid"                        text not null,
    "special_offer_id"               bigint not null,
    "product_id"                     bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("special_offer_id", "product_id")
);
create index if not exists "special_offer_product_modified_date_idx" on public."special_offer_product" (modified_date);

create table if not exists public."state_province" (
    "rowguid"                        text not null,
    "state_province_id"              bigint not null,
    "state_province_code"            text not null,
    "country_region_code"            text not null,
    "is_only_state_province_flag"    boolean not null,
    "name"                           text not null,
    "territory_id"                   bigint not null,
    "modified_date"                  timestamptz not null,
    primary key ("state_province_id")
);
create index if not exists "state_province_modified_date_idx" on public."state_province" (modified_date);

create table if not exists public."store" (
    "demographics"                   text,
    "rowguid"                        text not null,
    "business_entity_id"             bigint not null,
    "name"                           text not null,
    "sales_person_id"                bigint,
    "modified_date"                  timestamptz not null,
    primary key ("business_entity_id")
);
create index if not exists "store_modified_date_idx" on public."store" (modified_date);

create table if not exists public."transaction_history" (
    "transaction_id"                 bigint not null,
    "product_id"                     bigint not null,
    "reference_order_id"             bigint not null,
    "reference_order_line_id"        bigint not null,
    "transaction_date"               timestamptz not null,
    "transaction_type"               text not null,
    "quantity"                       bigint not null,
    "actual_cost"                    numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("transaction_id")
);
create index if not exists "transaction_history_modified_date_idx" on public."transaction_history" (modified_date);

create table if not exists public."transaction_history_archive" (
    "transaction_id"                 bigint not null,
    "product_id"                     bigint not null,
    "reference_order_id"             bigint not null,
    "reference_order_line_id"        bigint not null,
    "transaction_date"               timestamptz not null,
    "transaction_type"               text not null,
    "quantity"                       bigint not null,
    "actual_cost"                    numeric not null,
    "modified_date"                  timestamptz not null,
    primary key ("transaction_id")
);
create index if not exists "transaction_history_archive_modified_date_idx" on public."transaction_history_archive" (modified_date);

create table if not exists public."unit_measure" (
    "unit_measure_code"              text not null,
    "name"                           text not null,
    "modified_date"                  timestamptz not null,
    primary key ("unit_measure_code")
);
create index if not exists "unit_measure_modified_date_idx" on public."unit_measure" (modified_date);

create table if not exists public."vendor" (
    "business_entity_id"             bigint not null,
    "account_number"                 text not null,
    "name"                           text not null,
    "credit_rating"                  bigint not null,
    "preferred_vendor_status"        boolean not null,
    "active_flag"                    boolean not null,
    "modified_date"                  timestamptz not null,
    "purchasing_web_service_url"     text,
    primary key ("business_entity_id")
);
create index if not exists "vendor_modified_date_idx" on public."vendor" (modified_date);

create table if not exists public."work_order" (
    "work_order_id"                  bigint not null,
    "product_id"                     bigint not null,
    "order_qty"                      bigint not null,
    "stocked_qty"                    bigint not null,
    "scrapped_qty"                   bigint not null,
    "start_date"                     timestamptz not null,
    "end_date"                       timestamptz,
    "due_date"                       timestamptz not null,
    "modified_date"                  timestamptz not null,
    "scrap_reason_id"                bigint,
    primary key ("work_order_id")
);
create index if not exists "work_order_modified_date_idx" on public."work_order" (modified_date);

create table if not exists public."work_order_routing" (
    "work_order_id"                  bigint not null,
    "product_id"                     bigint not null,
    "operation_sequence"             bigint not null,
    "location_id"                    bigint not null,
    "scheduled_start_date"           timestamptz not null,
    "scheduled_end_date"             timestamptz not null,
    "actual_start_date"              timestamptz,
    "actual_end_date"                timestamptz,
    "actual_resource_hrs"            numeric,
    "planned_cost"                   numeric not null,
    "actual_cost"                    numeric,
    "modified_date"                  timestamptz not null,
    primary key ("work_order_id", "product_id", "operation_sequence")
);
create index if not exists "work_order_routing_modified_date_idx" on public."work_order_routing" (modified_date);
