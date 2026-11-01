{#
    SCD2 integrity for a dimension or snapshot: per key, versions are valid intervals that never overlap
    (at most one version valid at any instant) and exactly one version is current.
#}
{% test scd2_no_overlap(model, key, valid_from='valid_from', valid_to='valid_to', current_valid_to="cast('9999-12-31' as timestamp)") %}

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

bad_current as (
    select scd_key, 'expected exactly 1 current version, found ' || count(*) filter (
        where version_valid_to = {{ current_valid_to }}
    ) as issue
    from versions
    group by scd_key
    having count(*) filter (where version_valid_to = {{ current_valid_to }}) <> 1
)

select * from bad_intervals
union all
select * from bad_current

{% endtest %}
