-- Corridors = destination countries (Type 1): observed in the data + name, currency and region from the
-- `corridors` var.
with

observed as (
    select distinct beneficiary_country as country_code
    from {{ ref('stg_felix_backend__disbursements') }}
    where beneficiary_country is not null
),

reference as (
    {{ values_from_var('corridors', 'country_code') }}
),

combined as (
    select
        coalesce(observed.country_code, reference.country_code) as country_code,
        reference.country_name,
        reference.currency,
        reference.region
    from observed
    full outer join reference on observed.country_code = reference.country_code
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['country_code']) }} as corridor_sk,
        country_code,
        country_name,
        currency,
        region
    from combined
)

select * from final
union all by name
{{ unknown_member(model.columns) }}
