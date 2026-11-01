{# Shared column and concept definitions. Reference them with '{{ doc("<name>") }}'. #}

{# ---------------------------------------------------------------- lineage (raw) #}

{% docs col_source_file %}
Landing file the row was loaded from, e.g. `payments__2026-07.csv`. Added by `scripts/load_raw.py`.
Used by the loader to delete and reload the rows of a changed or removed file.
{% enddocs %}

{% docs col_file_md5 %}
MD5 of the landing file at load time. A different MD5 for the same file name means the file changed and was reloaded.
{% enddocs %}

{% docs col_batch_id %}
Batch the landing file belongs to: the `__<batch>` suffix of the file name (`baseline`, `2026-07`, `edge_cases`, ...).
{% enddocs %}

{% docs col_loaded_at %}
UTC timestamp of the loader run that inserted the row. Drives source freshness.
{% enddocs %}

{# ---------------------------------------------------------------- identifiers #}

{% docs col_user_id %}
Sender identifier (`usr_...`). A user is a US customer who sends money.
{% enddocs %}

{% docs col_payment_id %}
Payment identifier (`pay_...`). A payment is the pay-in leg of a remittance: the money the sender pays Félix.
{% enddocs %}

{% docs col_receipt_id %}
Receipt identifier (`rcp_...`). A receipt is issued once per successful payment and links it to its disbursements. One receipt = one remittance.
{% enddocs %}

{% docs col_disbursement_id %}
Payout attempt identifier (`dsb_...`). A receipt can need up to 3 attempts.
{% enddocs %}

{% docs col_beneficiary_id %}
Beneficiary identifier (`ben_...`): the person in LatAm who receives the money.
{% enddocs %}

{% docs col_batch_id_staging %}
Batch of the landing file the row came from (`baseline`, `2026-07`, ...). Lineage only.
{% enddocs %}

{# ---------------------------------------------------------------- money #}

{% docs col_send_amount_usd %}
Principal the sender transfers, in USD (excludes fees). Called `amount` in payments and `send_amount` in receipts.
{% enddocs %}

{% docs col_fee_amount_usd %}
Félix commission charged to the sender, in USD: $2.99 to a bank account or wallet, $4.98 to cash pickup, the first transfer is free. Félix revenue.
{% enddocs %}

{% docs col_store_fee_amount_usd %}
Store commission on cash payments ($3.98), 0 for cards. A pass-through to the store, **not** Félix revenue.
{% enddocs %}

{% docs col_fx_rate %}
Exchange rate applied to the customer, in receive-currency units per USD.
{% enddocs %}

{% docs col_reference_fx_rate %}
Mid-market exchange rate when the quote was made. Félix's FX spread is the gap between this and `fx_rate`.
{% enddocs %}

{% docs col_fx_revenue_usd %}
FX revenue in USD: `send_amount × (1 − fx_rate / reference_fx_rate)`. The spread Félix keeps by paying out at a rate below mid-market. Computed by the `fx_revenue` macro.
{% enddocs %}

{% docs col_payout_amount_local %}
Amount paid out to the beneficiary, in the local (receive) currency.
{% enddocs %}

{# ---------------------------------------------------------------- pay-in #}

{% docs col_payment_method %}
Pay-in method: `debit_card` (online, through a card processor) or `cash` (barcode paid at a US store through a cash network).
{% enddocs %}

{% docs col_payment_processor %}
Who collects the money for Félix: card processors `Adyen` and `Stripe`, cash network `PayNearMe`.
{% enddocs %}

{% docs col_funding_institution %}
Where the money comes from: the issuing bank of the debit card, or the store where the cash barcode was paid.
{% enddocs %}

{% docs col_funding_institution_type %}
Type of funding institution: `bank`, `neobank` (card issuers) or `retailer` (stores taking cash).
{% enddocs %}

{% docs col_card_last4 %}
Last 4 digits of the debit card. NULL for cash payments.
{% enddocs %}

{% docs col_payment_status %}
Payment status. `pending` → `succeeded` | `failed` (card) | `expired` (cash barcode not paid). A succeeded payment can later become `refunded` or, for cards only, `chargeback`.
{% enddocs %}

{% docs col_payment_failure_reason %}
Reason attached to the status: card decline reason, `barcode_not_paid`, chargeback reason or refund reason. NULL otherwise.
{% enddocs %}

{# ---------------------------------------------------------------- payout #}

{% docs col_provider_name %}
Payout provider that delivers the money in the destination country.
{% enddocs %}

{% docs col_payout_method %}
How the beneficiary receives the money: `bank_deposit`, `cash_pickup` or `mobile_wallet`.
{% enddocs %}

{% docs col_beneficiary_country %}
Destination country (ISO-2), i.e. the corridor: MX, GT, HN, SV, DO, CO.
{% enddocs %}

{% docs col_disbursement_status %}
Payout attempt status: `processing` → `completed` | `failed`. A failed attempt can be retried (up to 3 attempts).
{% enddocs %}

{% docs col_attempt_number %}
Attempt sequence for the receipt: 1 for the first payout attempt, 2–3 for retries.
{% enddocs %}

{# ---------------------------------------------------------------- users #}

{% docs col_kyc_status %}
Know-your-customer status: `pending`, `approved` or `rejected`. Type 2 (history kept) in `dim_users`.
{% enddocs %}

{% docs col_us_state %}
Sender's US state (ISO-2). Type 2 (history kept) in `dim_users`.
{% enddocs %}

{# ---------------------------------------------------------------- time #}

{% docs col_created_at %}
When the record was created, UTC. Parsed from two source formats by `parse_timestamp`.
{% enddocs %}

{% docs col_updated_at %}
When this version of the record was written, UTC. Orders CDC versions.
{% enddocs %}

{# ---------------------------------------------------------------- surrogate keys (marts) #}

{% docs col_user_sk %}
FK to `dim_users.user_sk`: the user version valid at the event time (point-in-time join). `'-1'` = unknown member.
{% enddocs %}

{% docs col_beneficiary_sk %}
FK to `dim_beneficiaries.beneficiary_sk`: the beneficiary version valid at the event time. `'-1'` = unknown member (e.g. a payment without a receipt).
{% enddocs %}

{% docs col_payment_method_sk %}
FK to `dim_payment_methods.payment_method_sk`. `'-1'` = unknown member.
{% enddocs %}

{% docs col_payment_processor_sk %}
FK to `dim_payment_processors.payment_processor_sk`. `'-1'` = unknown member.
{% enddocs %}

{% docs col_funding_institution_sk %}
FK to `dim_funding_institutions.funding_institution_sk`. `'-1'` = unknown member.
{% enddocs %}

{% docs col_payout_provider_sk %}
FK to `dim_payout_providers.payout_provider_sk`. `'-1'` = unknown member.
{% enddocs %}

{% docs col_corridor_sk %}
FK to `dim_corridors.corridor_sk` (destination country). `'-1'` = unknown member (e.g. a payment without a receipt).
{% enddocs %}

{% docs col_destination_country %}
Corridor (ISO-2 destination country): MX, GT, HN, SV, DO, CO. Degenerate copy of the corridor for the semantic layer. NULL when the payment has no receipt.
{% enddocs %}

{# ---------------------------------------------------------------- fact measures #}

{% docs col_fee_revenue_usd %}
Félix fee earned, in USD: the payment's fee when it succeeded, else 0. Additive.
{% enddocs %}

{% docs col_chargeback_loss_usd %}
Principal lost to a chargeback, in USD: the send amount when the card payment was charged back, else 0. Additive.
{% enddocs %}

{% docs col_net_revenue_usd %}
`fee_revenue_usd + fx_revenue_usd − chargeback_loss_usd`. The store fee is a pass-through and not included.
{% enddocs %}
