{#
    Moves a historical AdventureWorks date forward so the seeded history meets
    the live simulator data without a gap.

    The seed's business dates end in mid-2014, while the simulator stamps new
    rows with now(), which left a ~12-year hole in every time series. Only dates
    before `date_shift_cutoff` (the historical domain, observed max 2014-08-12)
    are shifted; anything the simulator writes is already current and passes
    through unchanged. The shift is a whole number of years, a multiple of 4 by
    default, so 29 February and the July-June fiscal calendar stay intact.

    Applied in staging, to every business date a fact is keyed on or joins by
    date (order/due/ship, cost history, special offers, quotas, currency rates,
    inventory movements), so the facts stay mutually consistent. Audit columns
    (`modified_date`, used by dlt for incremental loads and by the product
    snapshot) are left alone, except where a model uses one as a business date.

    Set `date_shift_years: 0` to build the star on the original calendar.
#}
{% macro shift_history_date(column) -%}
    {%- set years = var('date_shift_years') | int -%}
    {%- if years == 0 -%}
        {{ column }}
    {%- else -%}
        case
            when {{ column }} < '{{ var("date_shift_cutoff") }}'
                then {{ column }} + interval '{{ years }} years'
            else {{ column }}
        end
    {%- endif -%}
{%- endmacro %}
