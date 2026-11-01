{#
    numerator / denominator, NULL when the denominator is 0 or NULL. For label logic only:
    ratios are never stored in tables (they live in the semantic layer).
#}
{% macro safe_divide(numerator, denominator) -%}
    ({{ numerator }}) / nullif({{ denominator }}, 0)
{%- endmacro %}
