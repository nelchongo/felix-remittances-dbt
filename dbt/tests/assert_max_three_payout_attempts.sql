-- A remittance gets at most 3 payout attempts.
select
    receipt_id,
    count(*) as n_attempts,
    max(attempt_number) as max_attempt_number
from {{ ref('stg_felix_backend__disbursements') }}
group by receipt_id
having count(*) > 3 or max(attempt_number) > 3
