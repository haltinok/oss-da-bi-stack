{# StarRocks port: only the interval syntax differs from the Postgres project. #}
{% macro shift_history_date(column) -%}
    {%- set years = var('date_shift_years') | int -%}
    {%- if years == 0 -%}
        {{ column }}
    {%- else -%}
        case
            when {{ column }} < '{{ var("date_shift_cutoff") }}'
                then years_add({{ column }}, {{ years }})
            else {{ column }}
        end
    {%- endif -%}
{%- endmacro %}
