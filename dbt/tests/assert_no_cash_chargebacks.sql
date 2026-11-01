-- Cash can't be charged back: a cash payment with a `chargeback` version is a data error.
-- Checked on the event history so the bad row is caught before it reaches fct_payments.
select
    payment_event_id,
    payment_id,
    payment_method,
    status
from {{ ref('stg_felix_backend__payment_events') }}
where payment_method = 'cash'
    and status = 'chargeback'
