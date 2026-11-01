-- Q3 labels and the ingredients of the growth periodic snapshot. One row per sender × month, from the
-- sender's first active month (cohort) to the last month with data.
--   is_recurring: active in M and in >= var('recurring_min_active_months') of the previous
--                 var('recurring_lookback_months') months.
--   lifecycle_status: new (cohort month) | recurring | returning (active, not recurring)
--                     | at_risk (inactive, last transfer <= var('churn_after_inactive_days') days before month end)
--                     | churned (inactive longer than that).
-- Revenue is attributed to the month the payment succeeded; a chargeback loss stays in that month.
with

payments as (
    select * from {{ ref('int_payments__lifecycle') }}
),

remittances as (
    select * from {{ ref('int_remittances__joined') }}
),

transfers as (
    select
        payments.user_id,
        cast(date_trunc('month', payments.succeeded_at) as date) as activity_month,
        payments.succeeded_at,
        payments.send_amount_usd,
        payments.fee_amount_usd,
        coalesce(remittances.fx_revenue_usd, 0) as fx_revenue_usd,
        case when payments.is_charged_back then payments.send_amount_usd else 0 end as chargeback_loss_usd
    from payments
    left join remittances on payments.payment_id = remittances.payment_id
    where payments.is_succeeded
),

monthly as (
    select
        user_id,
        activity_month,
        count(*) as n_transfers,
        sum(send_amount_usd) as volume_usd,
        sum(fee_amount_usd) as fee_revenue_usd,
        sum(fx_revenue_usd) as fx_revenue_usd,
        sum(chargeback_loss_usd) as chargeback_loss_usd,
        max(succeeded_at) as last_transfer_at
    from transfers
    group by user_id, activity_month
),

cohorts as (
    select
        user_id,
        min(activity_month) as cohort_month
    from monthly
    group by user_id
),

month_bounds as (
    select
        min(activity_month) as first_month,
        max(activity_month) as last_month
    from monthly
),

months as (
    select cast(unnest(generate_series(first_month, last_month, interval 1 month)) as date) as activity_month
    from month_bounds
),

spine as (
    select
        cohorts.user_id,
        cohorts.cohort_month,
        months.activity_month
    from cohorts
    inner join months on cohorts.cohort_month <= months.activity_month
),

filled as (
    select
        spine.user_id,
        spine.cohort_month,
        spine.activity_month,
        coalesce(monthly.n_transfers, 0) as n_transfers,
        coalesce(monthly.volume_usd, 0) as volume_usd,
        coalesce(monthly.fee_revenue_usd, 0) as fee_revenue_usd,
        coalesce(monthly.fx_revenue_usd, 0) as fx_revenue_usd,
        coalesce(monthly.chargeback_loss_usd, 0) as chargeback_loss_usd,
        monthly.n_transfers is not null as is_active,
        max(monthly.last_transfer_at) over (
            partition by spine.user_id order by spine.activity_month
            rows between unbounded preceding and current row
        ) as last_transfer_to_date_at
    from spine
    left join monthly
        on spine.user_id = monthly.user_id and spine.activity_month = monthly.activity_month
),

windowed as (
    select
        *,
        coalesce(sum(case when is_active then 1 else 0 end) over (
            partition by user_id order by activity_month
            rows between {{ var('recurring_lookback_months') }} preceding and 1 preceding
        ), 0) as active_months_in_lookback,
        coalesce(lag(is_active) over (partition by user_id order by activity_month), false)
            as was_active_last_month,
        date_diff('day', last_transfer_to_date_at, (activity_month + interval 1 month))
            as days_since_last_transfer
    from filled
),

labelled as (
    select
        *,
        is_active and active_months_in_lookback >= {{ var('recurring_min_active_months') }} as is_recurring,
        case
            when activity_month = cohort_month then 'new'
            when is_active and active_months_in_lookback >= {{ var('recurring_min_active_months') }}
                then 'recurring'
            when is_active then 'returning'
            when days_since_last_transfer <= {{ var('churn_after_inactive_days') }} then 'at_risk'
            else 'churned'
        end as lifecycle_status
    from windowed
),

final as (
    select
        user_id,
        activity_month,
        cohort_month,
        cast(date_diff('month', cohort_month, activity_month) as integer) as months_since_first_transfer,
        lifecycle_status,
        is_active,
        is_recurring,
        lifecycle_status = 'new' as is_new,
        lifecycle_status = 'returning' as is_returning,
        lifecycle_status = 'at_risk' as is_at_risk,
        lifecycle_status = 'churned' as is_churned,
        lifecycle_status = 'churned'
        and coalesce(lag(lifecycle_status) over (partition by user_id order by activity_month), '') != 'churned'
            as is_newly_churned,
        was_active_last_month,
        cast(days_since_last_transfer as integer) as days_since_last_transfer,
        cast(n_transfers as integer) as n_transfers,
        cast(volume_usd as decimal(18, 2)) as volume_usd,
        cast(fee_revenue_usd as decimal(18, 2)) as fee_revenue_usd,
        cast(fx_revenue_usd as decimal(18, 4)) as fx_revenue_usd,
        cast(chargeback_loss_usd as decimal(18, 2)) as chargeback_loss_usd,
        cast(fee_revenue_usd + fx_revenue_usd - chargeback_loss_usd as decimal(18, 4)) as net_revenue_usd,
        cast(sum(fee_revenue_usd + fx_revenue_usd - chargeback_loss_usd) over (
            partition by user_id order by activity_month rows between unbounded preceding and current row
        ) as decimal(18, 4)) as cumulative_net_revenue_usd
    from labelled
)

select * from final
