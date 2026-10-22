{# Custom schema names are used as given, except the marts: `mart` + var mart_suffix, so a
   benchmark scale can build into mart_10m / mart_100m without touching the 500M `mart`. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif custom_schema_name | trim == 'mart' -%}
        mart{{ var('mart_suffix', '') }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
