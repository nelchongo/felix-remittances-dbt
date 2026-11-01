{#
    on-run-end hook. Placeholder until Phase 5, which persists `results` to audit.dbt_run_results.
    Returns an empty statement so the hook is a no-op.
#}
{% macro log_run_results(results) -%}
    {{ return('') }}
{%- endmacro %}
