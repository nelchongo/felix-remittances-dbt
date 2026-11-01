# Edge-case batch: expected test results

`data/test_batches/edge_cases/payments.csv` holds 6 hand-crafted bad payment rows. Loading it shows that
each data-quality rule catches the row it is meant for:

```bash
python run.py add-batch edge_cases    # load → dbt snapshot → dbt build (exits non-zero, as expected)
python run.py reset-data              # back to the clean baseline afterwards
```

## Expected results

| Bad row (`payment_id`) | What is wrong | Test that catches it | Severity |
|---|---|---|---|
| `pay_edge_negative_amount` | amount is `-50.00` | `dbt_utils.expression_is_true` `send_amount_usd > 0` on `stg_felix_backend__payment_events` | error |
| `pay_edge_unknown_method` | payment method `zelle` | `accepted_values` on `payment_events.payment_method` | error |
| | …and it carries a `card_last4` without being a debit card | singular `assert_card_last4_only_on_debit_cards` | error |
| `pay_edge_unknown_status` | status `on_hold` | `accepted_values` on `payment_events.status` | error |
| `pay_edge_orphan_user` | `usr_does_not_exist` is not in the users extract | `relationships` `payment_events.user_id → stg_felix_backend__users` | **warn** |
| `pay_edge_cash_chargeback` | a cash payment with status `chargeback` (cash can't be charged back) | singular `assert_no_cash_chargebacks` | error |
| `pay_edge_bad_timestamp` | timestamps `01/10/2026 12:00` (unsupported format → `parse_timestamp` returns NULL) | `not_null` on `payment_events.created_at` **and** `updated_at` | error |

Observed summary of the build (dbt 1.12.6, after the three monthly batches):

```
FAIL 1 accepted_values_stg_felix_backend__payment_events_payment_method__debit_card__cash
FAIL 1 accepted_values_stg_felix_backend__payment_events_status__pending__succeeded__failed__expired__refunded__chargeback
FAIL 1 assert_card_last4_only_on_debit_cards
FAIL 1 assert_no_cash_chargebacks
FAIL 1 dbt_utils_expression_is_true_stg_felix_backend__payment_events_send_amount_usd_0
FAIL 1 not_null_stg_felix_backend__payment_events_created_at
FAIL 1 not_null_stg_felix_backend__payment_events_updated_at
WARN 1 relationships_stg_felix_backend__payment_events_user_id__user_id__ref_stg_felix_backend__users_
Done. PASS=115 WARN=1 ERROR=7 SKIP=170
```

Each failing test returns exactly one row: the bad payment it targets. Two rows trip two tests each:
the `zelle` row also breaks the card rule, and the bad-timestamp row has both timestamps unparseable.

## Why the rules sit on `stg_felix_backend__payment_events`

`dbt build` skips every node downstream of a failing `error` test. That is the point: bad source data never
reaches the marts (`fct_payments` and everything after it are **skipped**, so the dashboard keeps showing the
last good build). It also means a rule placed on a downstream model would never run in the same build. The
row-level source rules therefore live on the event-history model, where every version of every payment is
checked once, in parallel. Mart-level invariants (keys, relationships to dimensions, `no_derived_metrics_in_facts`,
`scd2_no_overlap`, `share_at_least`) run on the marts during a clean build.

The 4 known orphan receipts (`relationships` on `stg_felix_backend__receipts.payment_id`, **warn**) do not
show here because that test depends on `stg_felix_backend__payments`, which is skipped in this build.
