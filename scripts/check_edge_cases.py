#!/usr/bin/env python3
"""Load the edge-case batch and assert that exactly the expected data tests fail or warn.

Used by CI. It leaves the warehouse with the bad rows loaded; run `python run.py reset-data` afterwards.
See docs/edge_cases.md for what each row breaks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_RESULTS = ROOT / "dbt" / "target" / "run_results.json"

EXPECTED = {
    ("fail", "accepted_values_stg_felix_backend__payment_events_payment_method__debit_card__cash"),
    ("fail", "accepted_values_stg_felix_backend__payment_events_status__pending__succeeded__failed__expired__refunded__chargeback"),
    ("fail", "assert_card_last4_only_on_debit_cards"),
    ("fail", "assert_no_cash_chargebacks"),
    ("fail", "dbt_utils_expression_is_true_stg_felix_backend__payment_events_send_amount_usd_0"),
    ("fail", "not_null_stg_felix_backend__payment_events_created_at"),
    ("fail", "not_null_stg_felix_backend__payment_events_updated_at"),
    ("warn", "relationships_stg_felix_backend__payment_events_user_id__user_id__ref_stg_felix_backend__users_"),
}


def main() -> int:
    result = subprocess.run([sys.executable, "run.py", "add-batch", "edge_cases"], cwd=ROOT, check=False)
    if result.returncode == 0:
        print("error: the edge-case batch was expected to fail the build")
        return 1
    results = json.loads(RUN_RESULTS.read_text())["results"]
    actual = {(r["status"], r["unique_id"].split(".")[2]) for r in results if r["status"] in ("fail", "warn", "error")}
    errors = {r["unique_id"] for r in results if r["status"] == "error"}
    missing, unexpected = EXPECTED - actual, actual - EXPECTED
    for status, name in sorted(missing):
        print(f"MISSING    {status:4} {name}")
    for status, name in sorted(unexpected):
        print(f"UNEXPECTED {status:4} {name}")
    if errors:
        print(f"model errors (should be none): {sorted(errors)}")
    if missing or unexpected or errors:
        return 1
    print(f"OK: the edge-case batch produced exactly the {len(EXPECTED)} expected test results.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
