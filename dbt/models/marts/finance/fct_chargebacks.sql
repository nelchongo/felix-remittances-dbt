-- Transaction fact, one row per chargeback (a disputed card payment). Two role-playing dates: the
-- payment date (cohort view of the chargeback rate) and the chargeback date (reporting view).
with

payments as (
    select * from {{ ref('int_payments__lifecycle') }}
    where is_charged_back
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
        cast(strftime(payments.succeeded_at, '%Y%m%d') as integer) as payment_date_sk,
        cast(strftime(payments.chargeback_at, '%Y%m%d') as integer) as chargeback_date_sk,
        payments.user_id,
        remittances.beneficiary_id,
        payments.payment_method,
        payments.payment_processor,
        payments.funding_institution,
        payments.funding_institution_type,
        remittances.destination_country,
        payments.chargeback_reason,
        payments.succeeded_at as payment_succeeded_at,
        payments.chargeback_at,
        cast(payments.send_amount_usd as decimal(18, 2)) as chargeback_amount_usd,
        cast({{ dbt.datediff('payments.succeeded_at', 'payments.chargeback_at', 'day') }} as integer)
            as days_to_chargeback
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
