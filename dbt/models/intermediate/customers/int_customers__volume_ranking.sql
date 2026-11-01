-- Q2 label. One row per sender (user with at least one succeeded payment): lifetime volume, rank and
-- volume segment. Users are ranked by volume; the segment comes from the cumulative share *before* the
-- user, so the user who crosses 50% is still in the top segment (thresholds in var('volume_segments')).
{%- set segments = var('volume_segments') %}
{%- set top_label = 'top_' ~ (segments.top * 100) | round | int ~ 'pct' %}
{%- set middle_label = 'middle_' ~ ((segments.middle - segments.top) * 100) | round | int ~ 'pct' %}
{%- set tail_label = 'tail_' ~ (100 - (segments.middle * 100) | round | int) ~ 'pct' %}
with

payments as (
    select * from {{ ref('int_payments__lifecycle') }}
),

sender_volume as (
    select
        user_id,
        sum(send_amount_usd) as lifetime_volume_usd,
        count(*) as n_transfers
    from payments
    where is_succeeded
    group by user_id
),

ranked as (
    select
        user_id,
        lifetime_volume_usd,
        n_transfers,
        row_number() over (order by lifetime_volume_usd desc, user_id asc) as volume_rank,
        sum(lifetime_volume_usd) over (
            order by lifetime_volume_usd desc, user_id asc rows between unbounded preceding and current row
        ) as cumulative_volume_usd,
        sum(lifetime_volume_usd) over () as total_volume_usd
    from sender_volume
),

final as (
    select
        user_id,
        lifetime_volume_usd,
        n_transfers,
        cast(volume_rank as integer) as volume_rank,
        cumulative_volume_usd,
        total_volume_usd,
        {{ classify_tier(
            safe_divide('cumulative_volume_usd - lifetime_volume_usd', 'total_volume_usd'),
            'volume_segments',
            tail_label,
            {'top': top_label, 'middle': middle_label}
        ) }} as volume_segment
    from ranked
)

select * from final
