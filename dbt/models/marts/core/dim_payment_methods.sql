-- Pay-in methods (Type 1): observed in the data + attributes from the `payment_methods` var.
with

observed as (
    select distinct payment_method
    from {{ ref('stg_felix_backend__payment_events') }}
    where payment_method is not null
),

reference as (
    {{ values_from_var('payment_methods', 'payment_method') }}
),

combined as (
    select
        coalesce(observed.payment_method, reference.payment_method) as payment_method,
        reference.channel,
        reference.chargeback_eligible
    from observed
    full outer join reference on observed.payment_method = reference.payment_method
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['payment_method']) }} as payment_method_sk,
        payment_method,
        channel,
        chargeback_eligible
    from combined
)

select * from final
union all by name
{{ unknown_member(model.columns) }}
