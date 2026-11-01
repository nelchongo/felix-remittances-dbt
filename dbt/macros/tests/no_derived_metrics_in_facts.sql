{#
    Facts store ingredients, not recipes (DESIGN §5). Fails for every column whose name looks like a derived
    metric: *_rate, *_pct, *_ratio, avg_*, median_*. Those belong in the semantic layer.
#}
{% test no_derived_metrics_in_facts(model, pattern='(_rate|_pct|_ratio)$|^(avg|median)_') %}

select
    column_name,
    'derived metric stored in a fact: define it in models/semantic/ instead' as issue
from information_schema.columns
where table_catalog = '{{ model.database }}'
    and table_schema = '{{ model.schema }}'
    and table_name = '{{ model.identifier }}'
    and regexp_matches(lower(column_name), '{{ pattern }}')

{% endtest %}
