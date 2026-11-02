{#
    SCD2 integrity for a dimension or snapshot: per key, versions are valid intervals that never overlap
    (at most one version valid at any instant) and exactly one version is current. With `source_relation`
    (the snapshot's source), a key that is no longer in it may have no current version: the snapshot closed
    its last version (`hard_deletes: invalidate`), e.g. after a landing file was removed.
#}
{% test scd2_no_overlap(model, key, valid_from='valid_from', valid_to='valid_to', current_valid_to="cast('9999-12-31' as timestamp)", source_relation=none) %}

with versions as (
    select
        {{ key }} as scd_key,
        {{ valid_from }} as version_valid_from,
        {{ valid_to }} as version_valid_to,
        lead({{ valid_from }}) over (partition by {{ key }} order by {{ valid_from }}) as next_valid_from
    from {{ model }}
),

bad_intervals as (
    select scd_key, 'version overlaps the next one or has valid_from >= valid_to' as issue
    from versions
    where next_valid_from < version_valid_to or version_valid_from >= version_valid_to
),

current_versions as (
    select scd_key, count(*) filter (where version_valid_to = {{ current_valid_to }}) as n_current
    from versions
    group by scd_key
),

bad_current as (
    select scd_key, 'expected exactly 1 current version, found ' || n_current as issue
    from current_versions
    where
        n_current > 1
        or (
            n_current = 0
            {% if source_relation is not none %}
                and scd_key in (select {{ key }} from {{ source_relation }})
            {% endif %}
        )
)

select * from bad_intervals
union all
select * from bad_current

{% endtest %}
