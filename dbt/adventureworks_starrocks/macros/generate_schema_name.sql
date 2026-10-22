{# Custom schema names are used as given, plus var mart_suffix when it is set: a benchmark or
   development scale builds into stage_25m / mart_25m / adventureworks_dwh_25m / rls_25m and never touches
   the live stage, mart and rls schemas (or the 500M `mart`). Without the var nothing changes. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}{{ var('mart_suffix', '') }}
    {%- else -%}
        {{ custom_schema_name | trim }}{{ var('mart_suffix', '') }}
    {%- endif -%}
{%- endmacro %}
