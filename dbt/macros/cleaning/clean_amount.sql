{#
    Text amount -> decimal(18, scale). Removes thousands separators ("1,234.56") and whitespace.
    Unparseable values return NULL. The sign is kept so business-rule tests can catch negatives.
#}
{% macro clean_amount(column, scale=2) -%}
    try_cast(replace(trim({{ column }}), ',', '') as decimal(18, {{ scale }}))
{%- endmacro %}
