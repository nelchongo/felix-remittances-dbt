-- Funding institutions (Type 1): card-issuing banks and neobanks, and the stores that take cash.
with

payments as (
    select * from {{ ref('stg_felix_backend__payments') }}
),

institutions as (
    select
        funding_institution,
        any_value(funding_institution_type) as funding_institution_type
    from payments
    where funding_institution is not null
    group by funding_institution
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['funding_institution']) }} as funding_institution_sk,
        funding_institution,
        funding_institution_type
    from institutions
)

select * from final
union all by name
{{ unknown_member(model.columns) }}
