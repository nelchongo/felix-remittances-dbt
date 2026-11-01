{#
    Label an expression with thresholds from a var, ascending: first tier whose upper bound is not reached.
        vars: { provider_failure_tiers: { healthy: 0.05, watch: 0.10 } }
        {{ classify_tier('failed / attempts', 'provider_failure_tiers', 'critical') }}
    ->  case when x is null then null when x < 0.05 then 'healthy' when x < 0.10 then 'watch' else 'critical' end
    `labels` optionally renames tiers (var key -> label).
#}
{% macro classify_tier(expr, var_name, else_label, labels={}) -%}
    {%- set tiers = var(var_name).items() | sort(attribute='1') -%}
    case
        when ({{ expr }}) is null then null
        {%- for name, upper_bound in tiers %}
        when ({{ expr }}) < {{ upper_bound }} then '{{ labels.get(name, name) }}'
        {%- endfor %}
        else '{{ else_label }}'
    end
{%- endmacro %}
