# Sample source data

Félix's brief references `payments.csv`, `receipts.csv` and `disbursements.csv`, but the files weren't attached.
These are **synthetic stand-ins** built by `src/generate_sample_data.py` (deterministic, seed 42, stdlib only).
`users.csv` was added so the user-level metrics have a customer dimension.

```bash
python src/generate_sample_data.py            # 2,500 users, seed 42 -> rebuilds source/, test_batches/ and landing/
```

## Folder layout: the original files are never edited

```
data/
├── source/                     # BASELINE extract (transactions 2024-07 → 2026-06-30, 24 months for YoY). Stand-in for Félix's files. Read-only.
│   └── users.csv · payments.csv · receipts.csv · disbursements.csv
├── test_batches/               # extra data for testing incremental loads, snapshots and tests
│   ├── 2026-07/ 2026-08/ 2026-09/   # monthly increments: new rows + LATE UPDATES to old records
│   └── edge_cases/payments.csv      # 6 hand-crafted bad rows that should trip specific tests
└── landing/                    # WORKING COPY the loader reads. One folder per table, one file per batch
    ├── users/users__baseline.csv
    ├── payments/payments__baseline.csv   (+ payments__2026-07.csv after `run.py add-batch 2026-07`)
    └── …
```

- `data/source` holds the "as delivered" files. If Félix sends the real CSVs, they go here.
- `data/landing` starts as a copy of `source`. You can add test batches to it, hand-edit it, or drop your own CSV into a table folder. `python run.py reset-data` restores it.
- Monthly batches are realistic increments, not just new rows. They carry new payment statuses for **old** payments (chargebacks 10–75 days later), KYC approvals, beneficiaries changing payout method, and the final status of payouts that were in flight at the cut-off. They exercise incremental models, the accumulating-snapshot fact and the SCD2 snapshots.

| Batch | users | payments | receipts | disbursements |
|---|---:|---:|---:|---:|
| baseline (`source/`) | 3,126 | 14,222 | 7,403 | 16,097 |
| 2026-07 | 175 | 1,209 | 612 | 1,324 |
| 2026-08 | 186 | 1,378 | 724 | 1,571 |
| 2026-09 | 159 | 1,651 | 848 | 1,851 |

## Entity relationships

```
users 1──* payments 1──0..1 receipts 1──* disbursements (attempts / retries)
                                   └── beneficiary_id ──> beneficiary (denormalised on disbursements)
```

## How a payment is made (pay-in)

| payment_method | payment_processor (collects the money for Félix) | funding_institution (where the money comes from) | Possible statuses |
|---|---|---|---|
| `debit_card` | card processor: `Adyen`, `Stripe` | the customer's **issuing bank**: JPMorgan Chase, Bank of America, Wells Fargo, Citibank, U.S. Bank, Capital One, PNC Bank, Truist, TD Bank, Chime (`funding_institution_type` = `bank` / `neobank`) | pending → succeeded \| failed; succeeded → chargeback \| refunded |
| `cash` | cash network: `PayNearMe` | the **store** where the barcode was paid: 7-Eleven, Walmart, CVS Pharmacy, Family Dollar, Dollar General, Walgreens, ACE Cash Express (`retailer`) | pending (barcode issued) → succeeded \| expired; succeeded → refunded. **Cash payments can't be charged back** |

Names are illustrative examples of the US market, not Félix's actual partners. Fees follow Félix's public pricing: $2.99 to a bank account or wallet, $4.98 to cash pickup, first transfer free. Cash pay-in also carries a $3.98 store commission (pass-through, not Félix revenue). Limits are $2,000 per card transfer and $1,000 per cash barcode.

## Files

### users.csv: one row per profile version (CDC)
`user_id, first_name, last_name, email, phone_number, country, state, kyc_status, created_at, updated_at`

### payments.csv: one row per payment status change (CDC)
| column | notes |
|---|---|
| payment_id, user_id | |
| amount | principal sent, USD. It's a string and can contain a thousands separator |
| fee_amount | Félix commission, USD |
| store_fee_amount | store commission on cash payments (3.98), else 0 |
| currency | USD |
| payment_method | `debit_card`, `cash` |
| payment_processor | `Adyen`, `Stripe`, `PayNearMe` |
| funding_institution, funding_institution_type | issuing bank (`bank` / `neobank`) or store (`retailer`) |
| card_last4 | debit card only |
| status | `pending`, `succeeded`, `failed`, `expired`, `refunded`, `chargeback` |
| failure_reason | decline reason / `barcode_not_paid` / chargeback reason / refund reason |
| created_at, updated_at | |

### receipts.csv: one row per successful payment (the link table)
`receipt_id, payment_id, user_id, beneficiary_id, send_amount, send_currency, fx_rate, reference_fx_rate, receive_amount, receive_currency, created_at`
`reference_fx_rate` is the mid-market rate when the quote was made. **FX revenue = send_amount × (1 − fx_rate / reference_fx_rate)**.

### disbursements.csv: one row per payout attempt status change (CDC)
`disbursement_id, receipt_id, attempt_number, provider_name, payout_method, beneficiary_id, beneficiary_name, beneficiary_country, beneficiary_account_last4, amount, currency, status, failure_reason, created_at, updated_at`

## Patterns planted for the metrics (baseline)
| Metric | What's in the data |
|---|---|
| Monthly volume, MoM, YoY | 24 months of baseline with strong growth (YoY volume +90% to +190%) and seasonal MoM swings (December and Mother's Day, May 1–10) |
| ARPU | ≈ $10 net revenue per active sender per month |
| Top-50% users | ~6% of senders make up 50% of volume |
| Recurring customers | monthly (~30-day) and heavy (~14-day) senders with churn |
| Avg transaction value | card ≈ $509 (median $375) vs cash ≈ $431 (median $350) |
| Lifetime value | fees + FX spread; average ≈ $37 per sender (skewed, median ≈ $12); FX is ~66% of revenue |
| Pay-in performance | card declines 5–10% by bank (Chime and TD highest); cash barcodes expire 10–21% by store (Family Dollar highest, Walmart lowest) |
| Provider (payout) failures | ~2% (Pagos Express) to ~25% (Caribe Remit) |
| Beneficiary clusters | households of 2–4 senders + 2 "mule" beneficiaries with 12–18 unrelated senders |
| Chargeback rate | ~1% of debit card payments overall (0.3% Chase to 2.3% U.S. Bank, 2.1% Chime), ~15% on transfers to the mules, none on cash |
| SCD2 | ~40% of users get a later version (KYC, state). ~8% of beneficiaries change payout method (26 in the baseline, more in the test batches) |

## Data-quality issues injected on purpose
| Issue | Expected handling |
|---|---|
| Exact duplicate rows (~1.5%) | dedupe |
| Several versions per id (CDC) | latest by `updated_at`; history kept in `*_events` models |
| Status casing / whitespace | `normalize_enum` + `accepted_values` |
| Two timestamp formats (ISO-Z and naive) | `parse_timestamp`, UTC |
| Thousands separators in amounts | `clean_amount` |
| Inconsistent email casing | `lower()` |
| 4 orphan receipts | `relationships` test, `severity: warn` |
| In-flight payments/payouts at the cut-off | final status `pending` / `processing`. Resolved by the next test batch |
| `edge_cases/payments.csv` (opt-in) | negative amount, unknown method `zelle`, unknown status, unknown user, a cash chargeback, an unparseable timestamp. Each one should fail or warn a specific test |
