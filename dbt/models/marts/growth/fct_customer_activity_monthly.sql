-- Periodic snapshot, one row per sender × month from the sender's first active month. Additive monthly
-- measures, Q3 lifecycle labels and the semi-additive `cumulative_net_revenue_usd` (sums across users,
-- not across months) used for LTV curves. The user version is the one valid at the end of the month.
with

activity as (
    select * from {{ ref('int_customers__activity_lifecycle') }}
),

users as (
    select * from {{ ref('dim_users') }}
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['activity.user_id', 'activity.activity_month']) }}
            as customer_month_id,
        coalesce(users.user_sk, '-1') as user_sk,
        cast(strftime(activity.activity_month, '%Y%m%d') as integer) as activity_month_date_sk,
        activity.user_id,
        activity.activity_month,
        activity.cohort_month,
        activity.months_since_first_transfer,
        activity.lifecycle_status,
        activity.is_active,
        activity.is_recurring,
        activity.is_new,
        activity.is_returning,
        activity.is_at_risk,
        activity.is_churned,
        activity.is_newly_churned,
        activity.was_active_last_month,
        activity.n_transfers,
        activity.volume_usd,
        activity.fee_revenue_usd,
        activity.fx_revenue_usd,
        activity.chargeback_loss_usd,
        activity.net_revenue_usd,
        activity.cumulative_net_revenue_usd
    from activity
    left join users
        on {{ scd2_point_in_time_join(
            'users', 'activity.user_id', 'user_id',
            "(activity.activity_month + interval 1 month - interval 1 second)"
        ) }}
)

select * from final
