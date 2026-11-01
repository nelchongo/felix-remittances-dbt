-- One row per beneficiary: its current attribute combination (payout method, account, name, country)
-- and when that combination started. Consecutive identical observations are collapsed
-- (gaps and islands), so A → B → A gives three versions. Feeds the snp_beneficiaries snapshot.
with

disbursement_events as (
    select * from {{ ref('stg_felix_backend__disbursement_events') }}
),

observations as (
    select distinct
        beneficiary_id,
        beneficiary_name,
        beneficiary_country,
        payout_method,
        beneficiary_account_last4,
        created_at as observed_at,
        {{ dbt_utils.generate_surrogate_key([
            'payout_method', 'beneficiary_account_last4', 'beneficiary_name', 'beneficiary_country'
        ]) }} as attributes_hash
    from disbursement_events
    where beneficiary_id is not null
),

flagged as (
    select
        beneficiary_id,
        beneficiary_name,
        beneficiary_country,
        payout_method,
        beneficiary_account_last4,
        observed_at,
        attributes_hash,
        case
            when
                lag(attributes_hash) over (
                    partition by beneficiary_id order by observed_at, attributes_hash
                ) = attributes_hash
                then 0
            else 1
        end as is_new_version
    from observations
),

versioned as (
    select
        beneficiary_id,
        beneficiary_name,
        beneficiary_country,
        payout_method,
        beneficiary_account_last4,
        observed_at,
        sum(is_new_version) over (
            partition by beneficiary_id
            order by observed_at, attributes_hash
            rows between unbounded preceding and current row
        ) as version_number,
        min(observed_at) over (partition by beneficiary_id) as first_seen_at
    from flagged
),

versions as (
    select
        beneficiary_id,
        version_number,
        any_value(beneficiary_name) as beneficiary_name,
        any_value(beneficiary_country) as beneficiary_country,
        any_value(payout_method) as payout_method,
        any_value(beneficiary_account_last4) as beneficiary_account_last4,
        min(first_seen_at) as first_seen_at,
        min(observed_at) as attributes_changed_at
    from versioned
    group by beneficiary_id, version_number
),

latest as (
    {{ dedupe_latest('versions', 'beneficiary_id', 'version_number desc') }}
),

final as (
    select
        beneficiary_id,
        beneficiary_name,
        beneficiary_country,
        payout_method,
        beneficiary_account_last4,
        cast(version_number as integer) as n_attribute_versions,
        first_seen_at,
        attributes_changed_at
    from latest
)

select * from final
