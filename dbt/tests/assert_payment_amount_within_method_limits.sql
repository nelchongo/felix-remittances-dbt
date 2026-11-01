-- Félix limits: $2,000 per debit card transfer and $1,000 per cash barcode.
select
    payment_event_id,
    payment_id,
    payment_method,
    send_amount_usd
from {{ ref('stg_felix_backend__payment_events') }}
where (payment_method = 'debit_card' and send_amount_usd > 2000)
    or (payment_method = 'cash' and send_amount_usd > 1000)
