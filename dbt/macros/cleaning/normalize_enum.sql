{#
    Normalise a categorical code: trim, lower-case, and empty string -> NULL.
    ' Succeeded ' -> 'succeeded'. Pair it with an `accepted_values` test.
#}
{% macro normalize_enum(column) -%}
    nullif(lower(trim({{ column }})), '')
{%- endmacro %}
