{#
    FX revenue in USD: send_amount × (1 − fx_rate / reference_fx_rate), as decimal(18,4).
    The spread Félix keeps by paying out below the mid-market rate. NULL-safe: returns NULL when any
    input is NULL or the reference rate is not positive (no division by zero).
#}
{% macro fx_revenue(send_amount, fx_rate, reference_fx_rate) -%}
    cast(
        case
            when {{ reference_fx_rate }} > 0
                then {{ send_amount }} * (1 - {{ fx_rate }} / {{ reference_fx_rate }})
        end
        as decimal(18, 4)
    )
{%- endmacro %}
