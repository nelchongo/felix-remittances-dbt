{#
    The rows matching `condition` hold at least `min_share` of sum(`value_column`).
    Used for Q2: the top volume segment must hold >= 50% of the volume.
#}
{% test share_at_least(model, value_column, condition, min_share) %}

with totals as (
    select
        sum(case when {{ condition }} then {{ value_column }} else 0 end) as matching_value,
        sum({{ value_column }}) as total_value
    from {{ model }}
)

select
    matching_value,
    total_value,
    'segment holds less than {{ min_share }} of the total' as issue
from totals
where total_value > 0
    and matching_value < {{ min_share }} * total_value

{% endtest %}
