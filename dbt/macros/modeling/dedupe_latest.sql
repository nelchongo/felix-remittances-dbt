{#
    Keep one row per `partition_by`: the first by `order_by`.
    Used for exact duplicates and for "latest CDC version per key".
    `order_by` must be deterministic for rows that differ (e.g. 'updated_at desc, _loaded_at desc').

        deduped as (
            {{ dedupe_latest('cleaned', 'payment_id', 'updated_at desc nulls last, _loaded_at desc') }}
        )
#}
{% macro dedupe_latest(relation, partition_by, order_by) -%}
    select *
    from {{ relation }}
    qualify row_number() over (partition by {{ partition_by }} order by {{ order_by }}) = 1
{%- endmacro %}
