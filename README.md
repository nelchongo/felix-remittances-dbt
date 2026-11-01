# Félix Remittances: dbt + DuckDB analytics project

A take-home for the **Data Engineering Manager** role at Félix Pago: a remittance data warehouse built with **dbt** on **DuckDB**, modelled with **Kimball** data marts, **SCD2 snapshots** and a **MetricFlow semantic layer**, with a **Streamlit** dashboard on top.

It runs on any machine with **Python only**. There's no database server and no Docker requirement.

> The answers to the questions are generated from the semantic layer by `python run.py answers` (see [Answers](#answers)).

---

## Quickstart

```bash
git clone <this repo> && cd felix-remittances-dbt
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run.py all          # load data → build SCD2 history → dbt build (models + tests) → metrics → answers
python run.py dashboard    # open http://localhost:8501
```

Requirements: Python 3.11+ (tested on 3.13). Everything else comes from `requirements.txt`, with pinned versions that were tested together.

| Command | What it does |
|---|---|
| `python run.py setup` | `dbt deps` + `dbt debug` |
| `python run.py all` | full pipeline from scratch |
| `python run.py build` | `dbt build` (models, snapshots, tests) |
| `python run.py add-batch 2026-07` | load a monthly test increment (also `2026-08`, `2026-09`, `edge_cases`) |
| `python run.py reset-data` | restore the working data to the untouched baseline |
| `python run.py answers` | run every saved query → `docs/answers.md` + the block below |
| `python run.py dashboard` | Streamlit dashboard |
| `python run.py test` / `lint` | dbt tests + pytest / sqlfluff |

Optional: `make all` or `docker build -t felix . && docker run --rm felix` (both just call `run.py`).

---

## Architecture

```mermaid
flowchart LR
  CSV[(data/landing CSVs)] -->|ingest/load_raw.py| RAW[raw]
  RAW --> STG[staging<br/>clean · dedupe]
  STG --> INT[intermediate<br/>lifecycle · joins · labels]
  STG & INT --> SNP[(snapshots<br/>SCD2)]
  SNP & INT --> MARTS[marts<br/>core · finance · operations · growth · risk]
  MARTS --> SL{{semantic layer<br/>MetricFlow metrics}}
  SL --> DASH[Streamlit dashboard]
  SL --> ANS[answers.md]
```

| Layer | Schema | What happens |
|---|---|---|
| Raw | `raw` | CSVs loaded **as text** by a Python loader (**no dbt seeds**). File-level incremental with an ingestion log (new / changed / removed files) |
| Staging | `staging` | 1:1 with sources: types cast, values normalised, CDC versions deduped (`*_events` keep the history) |
| Intermediate | `intermediate` | payment lifecycle, remittance joins, FX revenue, classification labels, sender graph clusters |
| Snapshots | `snapshots` | SCD Type 2 history of users (KYC, state) and beneficiaries (payout method, account) |
| Marts | `core`, `finance`, `operations`, `growth`, `risk` | Kimball star schemas: conformed dimensions + facts with **additive measures only** |
| Semantic layer | — | Every metric formula (rates, ATV, ARPU, LTV, MoM, YoY) is defined once in YAML and computed at query time |

**Key design decisions** (details in [`docs/DESIGN.md`](docs/DESIGN.md) and [`docs/adr/`](docs/adr/)):
- **Facts store ingredients, the semantic layer stores the formulas.** No ratios or averages are stored. ARPU is right at month, quarter or corridor grain because the distinct sender count is recomputed each time.
- **Kimball data marts by business process:**
  - **finance**: pay-in, revenue, chargebacks
  - **operations**: payouts
  - **growth**: customer value and engagement
  - **risk**: the sender ↔ beneficiary network
- **SCD2 with dbt snapshots.** Facts join the user/beneficiary version that was valid *at the time of the event*.
- **No seeds.** Reference attributes live in `vars` and are turned into SQL by a macro.
- **Macros** handle cleaning, dedupe, point-in-time joins, unknown members and FX revenue. Custom generic tests enforce the modelling rules.
- **YAML-first metadata.** Every model and column is documented, contracts are enforced on marts, and owners, PII flags and additivity are recorded in `meta`.

### Data marts and facts

| Mart | Facts (Kimball type) | Questions |
|---|---|---|
| finance | `fct_payments` (transaction), `fct_chargebacks` (transaction) | monthly volume, chargeback rate, average transaction value, pay-in performance |
| operations | `fct_remittances` (accumulating snapshot), `fct_disbursement_attempts` (transaction) | payout providers by failed disbursements |
| growth | `fct_customer_activity_monthly` (periodic snapshot) | top-50% users, recurring customers, LTV, ARPU, MoM, YoY |
| risk | `bridge_user_beneficiary` (factless bridge), `dim_sender_clusters` | clusters of users sending to the same beneficiaries |
| core | `dim_users`², `dim_beneficiaries`², `dim_payment_methods`, `dim_payment_processors`, `dim_funding_institutions`, `dim_payout_providers`, `dim_corridors`, `dim_date` | conformed dimensions (² = SCD2) |

---

## Data

The brief's CSVs weren't attached, so `scripts/generate_sample_data.py` builds realistic synthetic data (deterministic, seed 42). It has 2,500 users and 24 months of baseline (2024-07 → 2026-06), plus 3 monthly test batches. See [`data/README.md`](data/README.md).

- **Pay-in:** `debit_card` (processor Adyen/Stripe, funded by the customer's US bank) or `cash` (barcode paid at a store such as 7-Eleven or Walmart, through PayNearMe). Names are illustrative.
- **Payout:** bank deposit, cash pickup or mobile wallet, through per-country payout providers, with retries.
- **Planted patterns** for every metric, plus intentional data-quality issues (duplicates, CDC versions, mixed timestamp formats, thousands separators, orphans).
- `data/source/` is never modified. `data/landing/` is the working copy, and `data/test_batches/` holds increments and edge cases.

---

## Metric definitions

| Metric | Definition |
|---|---|
| **Volume transacted** | Σ principal (USD) of succeeded payments, by month of success |
| **Top-50% users** | users ranked by volume. Those whose cumulative share reaches 50% (crossing user included) are `top_50pct` |
| **Recurring customer** | active in month M **and** in ≥ 2 of the previous 3 months (monthly payday habit). Also new / returning / at-risk / churned |
| **Provider classification** | payout attempt failure rate → `healthy` < 5% · `watch` 5–10% · `critical` ≥ 10% (min. 100 attempts) |
| **Sender clusters** | connected components of the user ↔ beneficiary graph → `individual` · `household` · `high_fan_in` (≥ 10 unrelated senders: AML review) |
| **Chargeback rate** | charged-back ÷ succeeded **debit card** payments (cash can't be charged back). By payment month (cohort) and by chargeback month |
| **ATV** | volume ÷ transfers, plus the median (tickets are skewed) |
| **Net revenue** | Félix fee + FX revenue (spread vs mid-market rate) − chargeback losses. The store fee is a pass-through |
| **ARPU** | net revenue ÷ active senders in the period |
| **MoM / YoY** | `(current − previous) / previous` with a 1-month / 1-year offset |
| **LTV** | historical (lifetime net revenue per sender), cohort curves, and a simple 12-month projection (ARPU × expected lifetime from churn) |

All formulas live in `dbt/models/semantic/metrics/`. Query them directly:
```bash
cd dbt && mf query --metrics gross_volume_usd,arpu_usd,arpu_usd_yoy_pct --group-by metric_time__month
```

---

## Answers

<!-- ANSWERS:START -->
_Generated by `python run.py answers` on 2026-11-01 20:24 UTC from the semantic layer. Full tables and definitions: [docs/answers.md](docs/answers.md)._

| # | Question | Answer |
|---|---|---|
| Q1 | Total amount transacted by month | In 2026-06 Félix moved $285,956 (+106.9% year over year, -31.1% month over month). The peak month was 2026-05 ($414,973), driven by the seasonal peaks. |
| Q2 | Users that represent 50% of the volume | 93 of 1,594 senders (5.8%) make up half of the volume ($1,771,568). They are flagged `top_50pct` in `dim_users.volume_segment`. |
| Q3 | Recurring customers | In 2026-06, 224 of 456 active customers were recurring (49.1%); monthly churn was 14.3%. Over the last 12 months the recurring share ranged from 30.8% to 56.6%. |
| Q4 | Payout providers by failed disbursements | Pagos Express is the most reliable provider (2.4% of attempts fail) and Caribe Remit the least (26.5%). Critical tier: Andes Payouts, CashPoint LatAm, Caribe Remit; retries rescue most failed first attempts. |
| Q5 | Clusters of users sending to the same beneficiaries | 33 senders sit in high fan-in clusters (beneficiaries paid by 10+ unrelated senders) with a chargeback rate of 8.0%, versus 1.1% for individual senders, and 222 senders form households sharing beneficiaries. High fan-in clusters are the AML review queue. |
| Q6 | Chargeback rate | 1.2% of succeeded debit card payments were charged back (0.9% of card volume). By issuing bank it ranges from 0.3% (JPMorgan Chase) to 2.3% (U.S. Bank). Cash can't be charged back; the latest months are still maturing. |
| Q7 | Average transaction value | Debit card: ATV $509.31, median $375.30; Cash: ATV $431.49, median $350.00. The median sits well below the mean: a few large senders skew the average. |
| Q8 | Customer lifetime value | Each sender has generated $22.26 of net revenue so far (FX is 65.8% of gross revenue; chargeback losses take $23,638). At 2026-06 ARPU and churn, the projected 12-month LTV is $33.99. |
| Growth | Growth KPIs: active senders, ARPU, MoM and YoY | In 2026-06: 456 active senders (+132.7% Y/Y), 98 new, ARPU $4.87 (-44.9% M/M, -29.2% Y/Y). |
| Pay-in | Pay-in performance by processor, bank and store | Card declines range from 4.3% (U.S. Bank) to 10.3% (TD Bank); cash barcodes expire unpaid from 10.5% (Walmart) to 20.8% (Family Dollar). |
<!-- ANSWERS:END -->

---

## Testing

- **Source / staging:** keys, accepted values, parsed timestamps, relationships (orphans warn), business rules (amount > 0, `fx_rate ≤ reference rate`, limits per payment method, no cash chargebacks).
- **Modelling rules:** `no_derived_metrics_in_facts`, `scd2_no_overlap`, `share_at_least`, enforced contracts.
- **Unit tests:** dedupe, lifecycle, FX revenue, Pareto boundary, recurring labels.
- **Semantic layer:** `mf validate-configs`, plus pytest checks that metrics reconcile with the facts.
- **Edge cases:** `python run.py add-batch edge_cases` loads 6 bad rows. Each one trips a specific test (see `docs/edge_cases.md`).

CI (GitHub Actions) runs the full pipeline, tests and lint on every push.

---

## Dashboard

`python run.py dashboard` opens five pages: Overview, Finance, Operations, Growth and Risk. The dashboard runs SQL **compiled by MetricFlow** from saved queries, so the formulas never live in plotly. It reads DuckDB in **read-only** mode, so `dbt build` can run while it's open.

---

## Repository layout

```
run.py · requirements.txt · CLAUDE.md
data/        source/ · test_batches/ · landing/ (generated) · README.md
scripts/     generate_sample_data.py
ingest/      load_raw.py
dbt/         dbt_project.yml · profiles.yml · macros/ · snapshots/ · models/{staging,intermediate,marts,semantic}/
dashboard/   app.py · pages/ · db.py
tests_py/    semantic-layer tests
docs/        ASSIGNMENT.md · DESIGN.md · IMPLEMENTATION_PLAN.md · answers.md · adr/
```

## Path to production
- Swap the profile to Snowflake or BigQuery.
- CDC ingestion (Debezium/Fivetran) replaces the CSV landing, and snapshots run daily under an orchestrator.
- The same semantic layer serves BI tools through the dbt Semantic Layer APIs.
- Add PII masking per environment and data contracts with the backend teams.

Details in [`docs/DESIGN.md` §17](docs/DESIGN.md).
