{#
    The dimension's unknown member row, typed from the model's YAML columns (`model.columns`):
      *_sk columns -> '-1', text columns -> 'unknown', everything else -> NULL,
    unless `overrides` gives a SQL expression for the column. Combine with `union all by name`:

        select * from final
        union all by name
        {{ unknown_member(model.columns, {'is_current': 'true'}) }}
#}
{% macro unknown_member(columns, overrides={}) -%}
    {%- if not execute -%}
        select 1 as _unknown_member_placeholder
    {%- else -%}
        {%- set text_types = ['varchar', 'text', 'string'] -%}
        select
        {%- for column in columns.values() %}
            {%- set data_type = (column.data_type or 'varchar') | lower %}
            {%- if column.name in overrides %}
                {%- set value = overrides[column.name] %}
            {%- elif column.name.endswith('_sk') %}
                {%- set value = "'-1'" %}
            {%- elif data_type in text_types %}
                {%- set value = "'unknown'" %}
            {%- else %}
                {%- set value = 'null' %}
            {%- endif %}
            cast({{ value }} as {{ data_type }}) as {{ column.name }}{{ ',' if not loop.last }}
        {%- endfor %}
    {%- endif -%}
{%- endmacro %}
