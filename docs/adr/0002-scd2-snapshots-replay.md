# ADR 0002: SCD Type 2 with dbt snapshots and a monthly replay

- **Status:** accepted
- **Date:** 2026-11-01

## Context
Users change KYC status and state; beneficiaries change payout method and account. Facts must join the
version that was valid when the event happened (for example, chargebacks by the KYC status at payment time).
The extract arrives as one baseline file, so a single `dbt snapshot` would only capture the latest version of
each record.

## Decision
- SCD2 dimensions (`dim_users`, `dim_beneficiaries`) come from **dbt snapshots** (YAML, timestamp strategy,
  `dbt_valid_to_current = 9999-12-31`), not from hand-written history models.
- `python run.py replay` loads the baseline **month by month** and runs `dbt snapshot` after each month.
- Within a month, versioned tables (users) are fed in **passes**: pass *k* inserts each user's *k*-th version
  of that month. Most KYC approvals land days after sign-up, so without passes the snapshot saw 144 users with
  history instead of 865 (40%, matching the raw data). The timestamp strategy uses business time, so the extra
  runs don't distort validity.
- Beneficiary versions are derived from payout attempts (gaps and islands in
  `int_beneficiaries__attribute_changes`) and snapshotted the same way.
- Facts join through `scd2_point_in_time_join`. The first version opens at 1900-01-01, so every event finds a version.

## Consequences
- Real version history from a single extract, and the same mechanism handles later batches (`add-batch`).
- The replay costs about 60 `dbt snapshot` runs (~80 s on a laptop).
- A beneficiary that changes twice within one month keeps only the last change (1 of 26 in the baseline).
- In production, CDC lands continuously and snapshots run on a schedule; the replay is not needed.
