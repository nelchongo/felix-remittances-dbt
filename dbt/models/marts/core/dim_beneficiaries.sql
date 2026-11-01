-- Beneficiary dimension, Type 2 (from snp_beneficiaries): payout method, account, name, country.
-- First version opens at 1900-01-01. The name is masked. Unknown member: beneficiary_sk = '-1'.
with

snapshot as (
    select * from {{ ref('snp_beneficiaries') }}
),

versions as (
    select
        dbt_scd_id as beneficiary_sk,
        beneficiary_id,
        beneficiary_name,
        beneficiary_country,
        payout_method,
        beneficiary_account_last4,
        first_seen_at,
        dbt_valid_from,
        dbt_valid_to,
        row_number() over (partition by beneficiary_id order by dbt_valid_from) as version_number
    from snapshot
),

final as (
    select
        beneficiary_sk,
        beneficiary_id,
        cast(version_number as integer) as version_number,
        {{ mask_pii('beneficiary_name', 'text') }} as beneficiary_name_masked,
        beneficiary_country,
        payout_method,
        beneficiary_account_last4,
        first_seen_at,
        case when version_number = 1 then cast('1900-01-01' as timestamp) else dbt_valid_from end as valid_from,
        dbt_valid_to as valid_to,
        dbt_valid_to = cast('9999-12-31' as timestamp) as is_current
    from versions
)

select * from final
union all by name
{{ unknown_member(model.columns, {
    'beneficiary_id': "'unknown'",
    'valid_from': "cast('1900-01-01' as timestamp)",
    'valid_to': "cast('9999-12-31' as timestamp)",
    'is_current': 'true',
}) }}
