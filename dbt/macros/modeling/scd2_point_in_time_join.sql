{#
    Join condition from a fact to the SCD2 dimension version valid when the event happened:
        left join {{ ref('dim_users') }} as users
            on {{ scd2_point_in_time_join('users', 'payments.user_id', 'user_id', 'payments.created_at') }}
    Versions are half-open intervals [valid_from, valid_to). The first version starts at 1900-01-01 and the
    current one ends at 9999-12-31, so every event with a timestamp matches exactly one version.
#}
{% macro scd2_point_in_time_join(dim_alias, fact_key, dim_key, event_ts) -%}
    {{ fact_key }} = {{ dim_alias }}.{{ dim_key }}
    and {{ event_ts }} >= {{ dim_alias }}.valid_from
    and {{ event_ts }} < {{ dim_alias }}.valid_to
{%- endmacro %}
