-- Payout providers (Type 1) with the corridors and payout methods they serve.
-- `reliability_tier` (Q4 label) is added in Phase 5 from int_payout_providers__reliability.
with

attempts as (
    select * from {{ ref('stg_felix_backend__disbursements') }}
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
        {{ dbt_utils.generate_surrogate_key(['provider_name']) }} as payout_provider_sk,
        provider_name,
        corridors_served,
        payout_methods_served,
        first_attempt_at,
        cast(null as varchar) as reliability_tier
    from providers
)

select * from final
union all by name
{{ unknown_member(model.columns) }}
