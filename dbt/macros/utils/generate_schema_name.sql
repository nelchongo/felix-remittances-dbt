{#
    Use the custom schema name as-is (`finance`, not `main_finance`).
    Targets whose name starts with `ci_` get a `dev_` prefix so CI runs don't collide with dev schemas.
    Models without a custom schema land in the target's default schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.name.startswith('ci_') -%}
        dev_{{ custom_schema_name | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
