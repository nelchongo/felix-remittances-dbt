-- Pay-in processors (Type 1): observed in the data + `processor_type` from the `payment_processors` var.
with

observed as (
    select distinct payment_processor
    from {{ ref('stg_felix_backend__payment_events') }}
    where payment_processor is not null
),

reference as (
    {{ values_from_var('payment_processors', 'payment_processor') }}
),

combined as (
    select
        coalesce(observed.payment_processor, reference.payment_processor) as payment_processor,
        reference.processor_type
    from observed
    full outer join reference on observed.payment_processor = reference.payment_processor
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['payment_processor']) }} as payment_processor_sk,
        payment_processor,
        processor_type
    from combined
)

select * from final
union all by name
{{ unknown_member(model.columns) }}
