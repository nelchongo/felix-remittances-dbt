# Implementation plan: step by step

Work **one phase at a time**. Each phase has **tasks** (tick the boxes), **acceptance checks** (commands that must pass before moving on) and a **prompt** to paste into Claude Code to start it.
Section numbers like "§7" refer to `docs/DESIGN.md`.

| Phase | Goal | Day |
|---|---|---|
| 0 | Repo bootstrap, pinned env, dbt skeleton, `run.py` | 1 |
| 1 | Ingestion: CSV landing → `raw` (incremental, replay, test batches) | 1 |
| 2 | Staging + cleaning macros + sources/YAML docs | 1–2 |
| 3 | Intermediate layer (lifecycle, joins, FX revenue) | 2 |
| 4 | Snapshots (SCD2) + conformed dimensions + time spine | 2 |
| 5 | Facts for the 4 data marts + label models + custom tests | 3 |
| 6 | Semantic layer (MetricFlow): metrics, saved queries, answers | 4 |
| 7 | Streamlit dashboard | 5 |
| 8 | Quality gates, CI, docs, delivery | 5 |

---

## Phase 0: Bootstrap

**Prompt:**
> Read CLAUDE.md, docs/ASSIGNMENT.md and docs/DESIGN.md §3, §9. Then do Phase 0 of docs/IMPLEMENTATION_PLAN.md: initialise the repo skeleton, the pinned environment, the dbt project and `run.py` with the `setup` command. Run the acceptance checks and tick the boxes.

Tasks
- [x] `git init`. Add `.gitignore` (already provided: verify it covers `.venv/ warehouse/ data/landing/ dbt/target/ dbt/logs/ dbt/dbt_packages/ dashboard/compiled/ __pycache__/`)
- [x] `requirements.txt` is already pinned to the verified set. Don't change versions without a reason
- [x] `dbt/dbt_project.yml`: name `felix`, profile `felix`, paths, folder configs (§9), `vars` (§9), `flags: { send_anonymous_usage_stats: false }`, `on-run-end` hook placeholder
- [x] `dbt/profiles.yml` in the repo: target `dev` = duckdb `path: "{{ env_var('DUCKDB_PATH', '../warehouse/felix.duckdb') }}"`, threads 4. Optional `postgres` target commented out
- [x] `dbt/packages.yml`: `dbt-labs/dbt_utils` (pin to the latest 1.x that installs)
- [x] Macro `generate_schema_name`: use the custom schema name as-is (no `main_` prefix). Add a `dev_` prefix only when `target.name` starts with `ci_` (optional)
- [x] Empty folder structure with `.gitkeep` files: `macros/{utils,cleaning,modeling,tests,hooks}`, `snapshots`, `models/{docs,staging/felix_backend,intermediate/{payments,disbursements,remittances,customers},marts/{core,finance,operations,growth,risk},semantic/{semantic_models,metrics}}`, `ingest`, `dashboard/pages`, `tests_py`, `docs/adr`, `warehouse/.gitkeep`
- [x] `run.py` (argparse, cross-platform, `subprocess` with `cwd`/env: `DBT_PROJECT_DIR=dbt`, `DBT_PROFILES_DIR=dbt`, `DO_NOT_TRACK=1`). Subcommands are stubs, except `setup` = `dbt deps` + `dbt debug`

Acceptance
```bash
pip install -r requirements.txt
python run.py setup                 # dbt debug: "All checks passed!"
python run.py --help                # lists every subcommand
```

---

## Phase 1: Ingestion (`raw` schema, no seeds)

**Prompt:**
> Do Phase 1 of docs/IMPLEMENTATION_PLAN.md (DESIGN §4, data/README.md). Build ingest/load_raw.py with the file-level ingestion log, and the run.py commands `reset-data`, `load`, `replay` and `add-batch`. Then declare the dbt sources with freshness. Run the acceptance checks.

Tasks
- [x] `run.py reset-data`: delete `data/landing/`, then copy `data/source/<t>.csv` → `data/landing/<t>/<t>__baseline.csv` for users, payments, receipts, disbursements. Delete `warehouse/felix.duckdb`
- [x] `ingest/load_raw.py`:
  - [x] create schema `raw` and table `raw._ingestion_log(table_name, file_name, file_md5, row_count, batch_id, loaded_at)`
  - [x] for each `data/landing/<table>/*.csv`: **new** file → insert, **changed MD5** → delete that file's rows and re-insert, **missing** file → delete its rows
  - [x] read with `read_csv(path, all_varchar=true, header=true)`. Add `_source_file`, `_file_md5`, `_batch_id` (from the `__<batch>` suffix) and `_loaded_at`. Use `union_by_name` / `INSERT BY NAME` so new columns don't break the load
  - [x] `--replay monthly`: for the first load only, insert baseline rows in month order of `coalesce(updated_at, created_at)` and call a callback after each month (run.py uses it to run `dbt snapshot`)
  - [x] print a summary per table: files new/changed/removed and rows
- [x] `run.py load` = loader. `run.py replay` = loader with `--replay monthly` and `dbt run -s staging intermediate` once, then `dbt snapshot` after each month. `run.py add-batch <name>` copies `data/test_batches/<name>/<t>.csv` → `landing/<t>/<t>__<name>.csv`, then load → `dbt snapshot` → `dbt build`
- [x] `dbt/models/staging/felix_backend/_felix_backend__sources.yml`: source `felix_backend` (schema `raw`), 4 tables, every column described (from data/README.md), `meta: {pii: true}` on name/email/phone/beneficiary_name, freshness on `_loaded_at` (warn 24h, error 48h). **Freshness will warn on synthetic data, which is expected and documented**

Acceptance
```bash
python run.py reset-data && python run.py load    # 4 tables, row counts = data/README.md baseline table
python run.py load                                 # second run: 0 new, 0 changed (idempotent)
python run.py add-batch 2026-07                    # only the 4 new files are loaded
dbt source freshness                               # runs (warnings are fine)
```

---

## Phase 2: Staging + cleaning macros

**Prompt:**
> Do Phase 2 (DESIGN §10, §12, §13; data/README.md "data-quality issues"). Create the cleaning and modelling macros with docs in macros/_macros.yml, the six staging models with full YAML (every column: description, data_type, tests), and the glossary docs blocks. Run the acceptance checks.

Tasks
- [x] Macros + `macros/_macros.yml` (description and arguments for each): `parse_timestamp` (ISO `…Z` and `YYYY-MM-DD HH:MM:SS` → UTC `timestamp`, else NULL), `clean_amount(col, scale=2)`, `normalize_enum`, `mask_pii`, `dedupe_latest(relation, partition_by, order_by)`
- [x] `stg_felix_backend__users`: latest version per `user_id`, `lower(email)`
- [x] `stg_felix_backend__payment_events` (every distinct version) and `stg_felix_backend__payments` (latest)
- [x] `stg_felix_backend__receipts` (dedupe exact rows; keep `reference_fx_rate`)
- [x] `stg_felix_backend__disbursement_events` and `stg_felix_backend__disbursements` (latest per `disbursement_id`)
- [x] `models/docs/_glossary.md`: `{% docs %}` blocks for shared columns (user_id, payment_id, send_amount_usd, fx_revenue_usd, statuses…)
- [x] Tests:
  - PK unique/not_null
  - `accepted_values`: payment_method `[debit_card, cash]`; payment status `[pending, succeeded, failed, expired, refunded, chargeback]`; disbursement status `[processing, completed, failed]`; funding_institution_type `[bank, neobank, retailer]`; payout_method
  - not_null on parsed timestamps (catches unparseable ones)
  - receipts.payment_id → payments **severity warn** (4 known orphans)
  - `expression_is_true`: amount > 0, `fx_rate <= reference_fx_rate`

Acceptance
```bash
dbt build -s staging                  # all pass; only the orphan relationship test warns
dbt docs generate                     # every staging column has a description
```

---

## Phase 3: Intermediate

**Prompt:**
> Do Phase 3 (DESIGN §6.2, §10). Build the intermediate models listed below with YAML, plus the `fx_revenue` macro. Run the acceptance checks.

Tasks
- [x] Macro `fx_revenue(send_amount, fx_rate, reference_fx_rate)` = `send × (1 − fx_rate / reference_fx_rate)`, NULL-safe
- [x] `int_payments__lifecycle` (grain: payment): `created_at`, `succeeded_at`, `failed_at`, `expired_at`, `refunded_at`, `chargeback_at`, `final_status`, `minutes_to_pay`, flags `is_succeeded` (ever succeeded), `is_failed`, `is_expired`, `is_refunded`, `is_charged_back`, `is_first_transfer` (first succeeded per user)
- [x] `int_disbursements__attempts_ranked` (grain: attempt): `is_first_attempt`, `is_final_attempt`, `is_retry`, `minutes_to_resolve`, `final_status`
- [x] `int_remittances__joined` (grain: receipt): lifecycle ⋈ receipt ⋈ final attempt. Includes `fx_revenue_usd`, `chargeback_loss_usd` (send amount if charged back), `remittance_status` (`delivered`, `in_flight`, `failed_refunded`, `charged_back`), corridor
- [x] `int_beneficiaries__attribute_changes` (grain: beneficiary × version): collapse consecutive identical (payout_method, account_last4, name, country). `attributes_changed_at` = first time the combination was seen. Output the **latest** version per beneficiary (it feeds the snapshot)
- [x] Unit tests (dbt `unit_tests:`) for `int_payments__lifecycle` (a chargeback after succeeded keeps `succeeded_at`) and for `fx_revenue`

Acceptance
```bash
dbt build -s intermediate
```

---

## Phase 4: Snapshots + conformed dimensions

**Prompt:**
> Do Phase 4 (DESIGN §6.3, §11, §12). Create the YAML snapshots, the modelling macros (`scd2_point_in_time_join`, `unknown_member`, `values_from_var`), the core dimensions with full YAML and `dim_date` as the MetricFlow time spine. Wire `run.py replay` so history is built. Run the acceptance checks.

Tasks
- [x] `snapshots/snp_users.yml`, `snapshots/snp_beneficiaries.yml` (timestamp strategy, `dbt_valid_to_current: "cast('9999-12-31' as timestamp)"`, schema `snapshots`)
- [x] Macros: `scd2_point_in_time_join(dim_alias, fact_key, dim_key, event_ts)`, `unknown_member(columns)` (sk `'-1'`, text `'unknown'`, numbers NULL), `values_from_var(var_name, key_column)`
- [x] `dim_users` (Type 2 kyc_status/state + Type 1 masked email/phone; the first version's `valid_from` = 1900-01-01; `is_current`; unknown member). Placeholder columns for labels (filled in Phase 5)
- [x] `dim_beneficiaries` (Type 2), `dim_payment_methods`, `dim_payment_processors`, `dim_funding_institutions`, `dim_payout_providers`, `dim_corridors` (observed values + `values_from_var`)
- [x] `dim_date` via `dbt_utils.date_spine` (2024-01-01 → 2027-12-31) + holiday flags. YAML `time_spine: { standard_granularity_column: date_day }` and the column `granularity: day`
- [x] Custom generic test `scd2_no_overlap(key, valid_from, valid_to)`: at most one version valid at any instant, and exactly one current version per key

Acceptance
```bash
python run.py reset-data && python run.py replay && dbt build -s +marts.core
# ≈ 40% of users have > 1 version; beneficiaries with changes have > 1 version
duckdb warehouse/felix.duckdb "select count(*) from (select user_id from core.dim_users group by 1 having count(*)>1)"
```

---

## Phase 5: Facts (4 data marts) + labels + modelling tests

**Prompt:**
> Do Phase 5 (DESIGN §5, §6, §8, §13). Build the label models, the facts for finance/operations/growth/risk with enforced contracts, the incremental config, the `no_derived_metrics_in_facts` and `share_at_least` tests, groups and exposures. Facts must hold ingredients only. Run the acceptance checks, then run the edge-case batch and record which tests fail.

Tasks
- [x] Label models (intermediate/customers, disbursements): `int_customers__volume_ranking` (volume_rank, cumulative share, `volume_segment` from `var('volume_segments')`, crossing user included in top), `int_customers__activity_lifecycle` (user × month spine from first active month: `is_active`, `is_recurring` = active in M and in ≥ 2 of the previous 3 months, `lifecycle_status` new/recurring/returning/at_risk/churned, `cohort_month`, `months_since_first_transfer`), `int_payout_providers__reliability` (`reliability_tier` with `classify_tier`, min-attempts guard), `int_customers__sender_graph_components` (recursive CTE → `cluster_id` = min user_id, `cluster_type` individual/household/high_fan_in using `var('mule_min_senders')`)
- [x] Put the labels into the dims: `dim_users` gets volume_segment, volume_rank, cluster_id, primary_payment_method, first_transfer_month. `dim_payout_providers` gets reliability_tier. New `risk/dim_sender_clusters`
- [x] Facts (§6.2), all with `contract: enforced`, `meta.grain`, `meta.kimball_fact_type`, `meta.additivity` on every measure:
  - [x] `finance/fct_payments` (incremental merge on payment_id, 90-day lookback). SKs to user (PIT), beneficiary (PIT), payment method, processor, funding institution, corridor, date
  - [x] `finance/fct_chargebacks`
  - [x] `operations/fct_remittances` (accumulating snapshot, incremental merge), `operations/fct_disbursement_attempts`
  - [x] `growth/fct_customer_activity_monthly` (periodic snapshot, `cumulative_net_revenue_usd` with `meta.additivity: semi_additive`)
  - [x] `risk/bridge_user_beneficiary`
- [x] Custom tests: `no_derived_metrics_in_facts` (fails on columns matching `_rate$|_pct$|^avg_|_ratio$|^median_`), `share_at_least` (top_50pct segment ≥ 0.5 of volume). Singular tests: no cash chargebacks, `card_last4` only for debit cards, cash ≤ 1000 and card ≤ 2000, attempts ≤ 3
- [x] `marts/_groups.yml` (finance, operations, growth, risk + owners), `marts/_exposures.yml` (dashboard pages, filled in Phase 7)
- [x] Hook `log_run_results` → `audit.dbt_run_results`

Acceptance
```bash
python run.py build                   # all green
python run.py add-batch 2026-07 && python run.py add-batch 2026-08 && python run.py add-batch 2026-09   # incremental merges stay green
python run.py add-batch edge_cases    # EXPECTED failures: negative amount, unknown method 'zelle', unknown status 'on_hold',
                                      # orphan user (warn), cash chargeback, unparseable timestamp. Document them in docs/edge_cases.md
python run.py reset-data              # back to clean
```

---

## Phase 6: Semantic layer (MetricFlow)

**Prompt:**
> Do Phase 6 (DESIGN §7, §8). Create the semantic models, the full metric catalog (incl. ARPU, MoM, YoY, ATV, chargeback rate, LTV) and the saved queries q1–q8 + growth_kpis_monthly + payin_performance. Implement `run.py answers` and the pytest reconciliation tests. Verify the untested features listed in CLAUDE.md "Gotchas". Run the acceptance checks.

Tasks
- [x] `semantic/semantic_models/`: `sem_payments`, `sem_chargebacks`, `sem_disbursement_attempts`, `sem_remittances`, `sem_customer_activity` (use `non_additive_dimension` for the cumulative revenue measure if supported, otherwise document it), `sem_users` (SCD2 with `validity_params` if supported, otherwise a current-state user dim + note)
- [x] `semantic/metrics/{finance,growth,operations,risk}.yml`: the catalog in DESIGN §7.3. Every metric gets a `label` and `description`. Aliases are ≥ 2 characters
- [x] `semantic/saved_queries.yml`: `q1_monthly_volume`, `q2_volume_concentration`, `q3_recurring_customers`, `q4_payout_providers`, `q5_sender_clusters`, `q6_chargeback_rate`, `q7_transaction_value`, `q8_ltv`, `growth_kpis_monthly`, `payin_performance` (+ the dashboard ones). Use `order_by` where useful
- [x] `run.py answers`: run each saved query with `mf query --saved-query <q> --csv`, write `docs/answers.md` (one section per question: definition, table and a 1–2 sentence interpretation template) and replace the block between `<!-- ANSWERS:START -->` and `<!-- ANSWERS:END -->` in README.md
- [x] `tests_py/test_semantic_layer.py`: every saved query returns rows; Σ `gross_volume_usd` (MetricFlow, all time) = Σ in `fct_payments` for succeeded; monthly `arpu_usd × active_senders ≈ net_revenue_usd`; `chargeback_rate` is NULL or 0 for cash
- [x] Remember: `mf` needs `dbt parse`/`build` first, and has to run inside `dbt/`

Acceptance
```bash
cd dbt && mf validate-configs && cd ..       # 0 errors
python run.py answers                         # docs/answers.md written, README block updated
pytest tests_py -q                            # green
```

---

## Phase 7: Dashboard (Streamlit + plotly)

**Prompt:**
> Do Phase 7 (DESIGN §14). Implement `run.py compile-metrics` (mf --explain → dashboard/compiled/*.sql), dashboard/db.py (read-only, cached) and the 5 pages. Business formulas come only from the semantic layer; plotly does presentation only. Register the pages as exposures. Run the acceptance checks.

Tasks
- [x] `run.py compile-metrics`: for each saved query used by the dashboard, run `mf query --saved-query <q> --explain`, strip the header, and write `dashboard/compiled/<q>.sql`
- [x] `dashboard/db.py`: `saved_query(name)` → DataFrame via `duckdb.connect(DB, read_only=True)` + `st.cache_data(ttl=60)`. Show a friendly message if the DB is locked or missing ("run `python run.py all`")
- [x] `dashboard/app.py` (Overview): KPI tiles (volume, net revenue, active senders, ARPU, ATV, take rate) with MoM/YoY deltas; volume bars + YoY line
- [x] `pages/1_Finance.py`, `2_Operations.py`, `3_Growth.py` (ARPU trend with MoM/YoY, recurring share, Pareto, LTV cohort curves), `4_Risk.py`. Filters: date range, payment method, corridor
- [x] `run.py dashboard` = `streamlit run dashboard/app.py`. Update `marts/_exposures.yml`
- [x] Screenshots → `docs/img/` for the README

Acceptance
```bash
python run.py compile-metrics && python run.py dashboard     # every page renders without errors
python run.py build                                          # works while the dashboard is open (no lock errors)
```

---

## Phase 8: Quality gates & delivery

**Prompt:**
> Do Phase 8. Add CI, linting, pre-commit, ADRs, the optional Makefile/Dockerfile, finalize README.md, and run a fresh-clone test. Report anything that differs from DESIGN.md.

Tasks
- [x] `.sqlfluff` (dbt templater, duckdb dialect) + fix lint. `.pre-commit-config.yaml` (sqlfluff, end-of-file, trailing whitespace)
- [x] `.github/workflows/ci.yml`: Python 3.11 and 3.13 matrix → `pip install -r requirements.txt` → `python run.py all` → `python run.py test` → `python run.py lint`. Upload `docs/answers.md` as an artifact
- [x] ADRs: `docs/adr/0001-duckdb.md`, `0002-scd2-snapshots-replay.md`, `0003-semantic-layer-metricflow.md`, `0004-no-seeds-reference-vars.md`
- [x] Optional `Makefile` and `Dockerfile` (`python:3.13-slim`, `pip install -r requirements.txt`, `CMD python run.py all`), both just calling `run.py`
- [x] README.md: fill in screenshots, check every command, make sure the answers block is generated
- [ ] Fresh clone in a temp folder → follow the README literally → everything works

Acceptance
```bash
git clone <repo> /tmp/fresh && cd /tmp/fresh && python -m venv .venv && . .venv/bin/activate \
  && pip install -r requirements.txt && python run.py all && python run.py test
```

---

## Simplification (v6, after delivery review)

The first build followed v5 to the letter. A review against the brief showed that most of the added complexity sat
in extras, not in the dbt core, so v6 trims them without dropping any requirement of `docs/ASSIGNMENT.md`.

- [x] Dashboard: one file, one tab per question, reading the same saved queries as `docs/answers.md`.
  Removed: 4 pages, the filter row, 15 dashboard-only saved queries, 2 semantic models (`sender_clusters`,
  `user_beneficiary_pairs`), 10 metrics outside the v5 catalog and the extra `dim_sender_clusters.first_transfer_at` column
- [x] Root: removed Makefile, Dockerfile, `.dockerignore`, `.pre-commit-config.yaml`, `.sqlfluffignore`, `.streamlit/`
  (`run.py` and CI are the only entry points)
- [x] Moved `ingest/load_raw.py` to `scripts/load_raw.py` (one folder for the Python helpers)
- [x] Docs (DESIGN v6, README, CLAUDE.md, ADR 0004) updated; fresh-clone run green on Python 3.11 and 3.13


---

## Pull-request workflow and fewer files (v7)

- [x] CI on every pull request to `main`/`master`: one `checks` job per Python version (3.11, 3.13) running
  `setup` → `all` → `lint` → `test` → `check-edge-cases`. `main` changes only through pull requests
- [x] Python lint with `ruff` (default rules, pinned in `requirements.txt`); the mechanical fixes it asked for left
  `scripts/generate_sample_data.py` output byte-identical
- [x] Removed `.sqlfluff` (its settings are now flags in `run.py lint`), `scripts/check_edge_cases.py` (now
  `python run.py check-edge-cases`), `warehouse/.gitkeep` (`run.py` creates the folder), `docs/adr/` and
  `docs/edge_cases.md` (now DESIGN.md §15.1 and §18)
- [x] README reduced to the step-by-step guide; `run.py answers` writes only `docs/answers.md`, whose summary table
  replaces the README answers block
- [x] Every Python file except `run.py` moved to `src/` (`dashboard/app.py` → `src/dashboard.py`, `tests_py/` →
  `src/tests/`, `scripts/*` → `src/*`); the compiled metric SQL moved to `warehouse/compiled/` (generated, git-ignored)
- [x] Incremental audit: a business-time watermark (`last_updated_at` > max) missed 12 late-arriving chargebacks and
  refunds in both facts. Now the facts merge on a load-time watermark (`_loaded_at`) plus the maturity lookback, a load
  that deletes raw rows triggers `--full-refresh`, and `run.py check-incremental` (CI) compares them with a full refresh

---

## Menu and brand (v8)

- [x] `python run.py` with no arguments opens a menu (the help when there is no terminal, so CI never hangs). The
  dashboard starts in the background on the first free port from 8501 and its link stays at the top; exiting stops it
- [x] Option 1 is the dbt sequence (`run.py pipeline`): an empty warehouse gets the full ingest (monthly replay) and
  build; afterwards it is incremental (new or changed landing files → snapshot → build), and a no-op when nothing is new.
  Option 2 adds a monthly test batch and runs that increment; options 3–5 run the checks, open the dashboard, reset
- [x] Dashboard in the Félix Pago brand (`src/brand.py`, `src/assets/`): logo header, favicon, light (linen) and dark
  (slate) themes passed as flags, chart palettes derived from the brand tokens and validated with the data-viz checks
  in both modes. Its cache follows the warehouse file, so a refresh after a build shows the new data
- [x] `src/tests/test_run.py`: no menu without a terminal, brand theme flags, `pipeline` command
- [x] The sequence runs step by step: ingest, one `dbt build --select tag:<step>` per tag (`staging`,
  `intermediate`, `snapshot`, `core`, `marts`), then the semantic layer. Tests run where their last parent is built
  (`buildable`, `eager` on the last step); a guard test checks one tag per node, DAG order and the same 258 tests
- [x] Terminal: clean screen, Félix logo in block letters, clickable links (OSC 8); the sequence splits the screen
  (connected dots with a spinner on the left, live dbt output on the right), and the marts step fans out into the
  four groups dbt builds in parallel threads (separate processes are not possible: DuckDB has a single writer)
- [x] `python run.py` resets the data on start, so option 1 always runs the whole sequence; README cut to a 2-minute read
- [x] Dashboard tab **Data model**: star diagram and bus matrix generated from dbt's manifest (relationships tests)
- [x] Dashboard redesign: every tab is a plain-language question, four equal cards and two equal charts; Q1 shows revenue before losses, chargeback losses and net revenue (new metric `revenue_before_losses_usd`)
- [x] Dashboard tab **Data catalog**: dbt docs (descriptions, columns, two-level lineage) plus the embedded static dbt docs site; `run.py docs`, also run by the sequence
- [x] Dashboard light only like felixpago.com, with free look-alikes of its licensed fonts (Inter Tight ExtraBold for Plain, DM Sans for Saans)
