{#
    on-run-end hook: append one row per executed node to audit.dbt_run_results
    (invocation, node, status, timing, rows affected, message). Gives a queryable run history.
#}
{% macro log_run_results(results) -%}
    {%- if not execute or not results -%}
        {{ return('') }}
    {%- endif -%}
    {%- set audit_schema = generate_schema_name('audit', none) | trim -%}
    {%- do run_query('create schema if not exists ' ~ audit_schema) -%}
    {%- do run_query(
        'create table if not exists ' ~ audit_schema ~ '.dbt_run_results ('
        ~ 'invocation_id varchar, command varchar, node_unique_id varchar, resource_type varchar, '
        ~ 'node_name varchar, status varchar, execution_time_s double, rows_affected bigint, '
        ~ 'message varchar, logged_at timestamp)'
    ) -%}
    {%- set rows = [] -%}
    {%- for result in results -%}
        {%- set response = result.adapter_response or {} -%}
        {%- set rows_affected = response.get('rows_affected') -%}
        {%- set message = (result.message or '') | string | replace("'", "''") -%}
        {%- do rows.append(
            "('" ~ invocation_id ~ "', '" ~ (flags.WHICH or '') ~ "', '" ~ result.node.unique_id ~ "', '"
            ~ result.node.resource_type ~ "', '" ~ result.node.name ~ "', '" ~ result.status ~ "', "
            ~ (result.execution_time or 0) ~ ", "
            ~ (rows_affected if rows_affected is number else 'null') ~ ", '" ~ message[:500] ~ "', "
            ~ "cast(now() at time zone 'UTC' as timestamp))"
        ) -%}
    {%- endfor -%}
    insert into {{ audit_schema }}.dbt_run_results values {{ rows | join(', ') }}
{%- endmacro %}
