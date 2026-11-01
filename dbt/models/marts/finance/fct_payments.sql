-- Transaction fact, one row per payment (final state). Ingredients only: additive amounts and 0/1 flags.
-- Incremental merge on payment_id. Each run re-processes payments created in the last
-- var('chargeback_maturity_days') days and any payment updated since the last run, so late
-- chargebacks and refunds update their row.
with

payments as (
    select lifecycle.* from {{ ref('int_payments__lifecycle') }} as lifecycle
    {% if is_incremental() %}
        where lifecycle.created_at is null
            or lifecycle.created_at >= (select max(current_table.created_at) from {{ this }} as current_table)
            - interval '{{ var("chargeback_maturity_days") }} days'
            or lifecycle.last_updated_at > (select max(current_table.last_updated_at) from {{ this }} as current_table)
    {% endif %}
),

remittances as (
    select * from {{ ref('int_remittances__joined') }}
),

users as (
    select * from {{ ref('dim_users') }}
),

beneficiaries as (
    select * from {{ ref('dim_beneficiaries') }}
),

payment_methods as (
    select * from {{ ref('dim_payment_methods') }}
),

payment_processors as (
    select * from {{ ref('dim_payment_processors') }}
),

funding_institutions as (
    select * from {{ ref('dim_funding_institutions') }}
),

corridors as (
    select * from {{ ref('dim_corridors') }}
),

final as (
    select
        payments.payment_id,
        remittances.receipt_id,
        coalesce(users.user_sk, '-1') as user_sk,
        coalesce(beneficiaries.beneficiary_sk, '-1') as beneficiary_sk,
        coalesce(payment_methods.payment_method_sk, '-1') as payment_method_sk,
        coalesce(payment_processors.payment_processor_sk, '-1') as payment_processor_sk,
        coalesce(funding_institutions.funding_institution_sk, '-1') as funding_institution_sk,
        coalesce(corridors.corridor_sk, '-1') as corridor_sk,
        cast(strftime(payments.created_at, '%Y%m%d') as integer) as created_date_sk,
        cast(strftime(payments.succeeded_at, '%Y%m%d') as integer) as succeeded_date_sk,
        payments.user_id,
        remittances.beneficiary_id,
        payments.payment_method,
        payments.payment_processor,
        payments.funding_institution,
        payments.funding_institution_type,
        remittances.destination_country,
        payments.final_status,
        payments.created_at,
        payments.succeeded_at,
        payments.last_updated_at,
        payments.send_amount_usd,
        cast(case when payments.is_succeeded then payments.fee_amount_usd else 0 end as decimal(18, 2))
            as fee_revenue_usd,
        cast(coalesce(remittances.fx_revenue_usd, 0) as decimal(18, 4)) as fx_revenue_usd,
        cast(case when payments.is_charged_back then payments.send_amount_usd else 0 end as decimal(18, 2))
            as chargeback_loss_usd,
        cast(case when payments.is_succeeded then payments.store_fee_amount_usd else 0 end as decimal(18, 2))
            as store_fee_usd,
        payments.is_succeeded,
        payments.is_failed,
        payments.is_expired,
        payments.is_refunded,
        payments.is_charged_back,
        payments.is_pending,
        payments.is_first_transfer
    from payments
    left join remittances on payments.payment_id = remittances.payment_id
    left join users
        on {{ scd2_point_in_time_join('users', 'payments.user_id', 'user_id', 'payments.created_at') }}
    left join beneficiaries
        on {{ scd2_point_in_time_join(
            'beneficiaries', 'remittances.beneficiary_id', 'beneficiary_id', 'remittances.receipt_created_at'
        ) }}
    left join payment_methods on payments.payment_method = payment_methods.payment_method
    left join payment_processors on payments.payment_processor = payment_processors.payment_processor
    left join funding_institutions on payments.funding_institution = funding_institutions.funding_institution
    left join corridors on remittances.destination_country = corridors.country_code
)

select * from final
