-- Payout providers (Type 1) with the corridors and payout methods they serve.
-- `reliability_tier` is the Q4 label from int_payout_providers__reliability.
with

attempts as (
    select * from {{ ref('stg_felix_backend__disbursements') }}
),

reliability as (
    select * from {{ ref('int_payout_providers__reliability') }}
),

providers as (
    select
        provider_name,
        string_agg(distinct beneficiary_country, ',' order by beneficiary_country) as corridors_served,
        string_agg(distinct payout_method, ',' order by payout_method) as payout_methods_served,
        min(created_at) as first_attempt_at
    from attempts
    where provider_name is not null
    group by provider_name
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['providers.provider_name']) }} as payout_provider_sk,
        providers.provider_name,
        providers.corridors_served,
        providers.payout_methods_served,
        providers.first_attempt_at,
        coalesce(reliability.reliability_tier, 'insufficient_data') as reliability_tier
    from providers
    left join reliability on providers.provider_name = reliability.provider_name
)

select * from final
union all by name
{{ unknown_member(model.columns) }}
