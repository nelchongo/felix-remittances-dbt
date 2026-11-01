-- card_last4 only exists for debit card payments.
select
    payment_event_id,
    payment_id,
    payment_method,
    card_last4
from {{ ref('stg_felix_backend__payment_events') }}
where payment_method != 'debit_card'
    and card_last4 is not null
