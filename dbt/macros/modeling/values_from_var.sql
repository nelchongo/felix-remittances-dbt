{#
    Turn a dict var into an inline table (replaces seeds for small reference data):
        vars: { payment_methods: { debit_card: { channel: online, chargeback_eligible: true }, ... } }
        {{ values_from_var('payment_methods', 'payment_method') }}
    ->  select * from (values ('debit_card', 'online', true), ...) as v (payment_method, channel, chargeback_eligible)
    Attributes missing for an entry become NULL. Strings are quoted, booleans and numbers kept as literals.
#}
{% macro values_from_var(var_name, key_column) -%}
    {%- set entries = var(var_name) -%}
    {%- set attributes = [] -%}
    {%- for attrs in entries.values() -%}
        {%- for name in attrs -%}
            {%- if name not in attributes -%}{%- do attributes.append(name) -%}{%- endif -%}
        {%- endfor -%}
    {%- endfor -%}
    select * from (
        values
        {%- for key, attrs in entries.items() %}
            ({{ _felix_sql_literal(key) }}
            {%- for name in attributes %}, {{ _felix_sql_literal(attrs.get(name)) }}{% endfor -%}
            ){{ ',' if not loop.last }}
        {%- endfor %}
    ) as v ({{ key_column }}{% for name in attributes %}, {{ name }}{% endfor %})
{%- endmacro %}

{% macro _felix_sql_literal(value) -%}
    {%- if value is none -%}null
    {%- elif value is sameas true -%}true
    {%- elif value is sameas false -%}false
    {%- elif value is number -%}{{ value }}
    {%- else -%}'{{ value | string | replace("'", "''") }}'
    {%- endif -%}
{%- endmacro %}
