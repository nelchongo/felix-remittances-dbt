# Original assignment (Félix Pago, Data Engineering Manager take-home)

> Transcribed from the PDF the candidate received. Expected delivery: 4–5 business days.
> Note: the PDF mentions "another doc HERE", but that link was not included.

## Question 1

You work as a data-engineer for a fintech focused on remittances.

We provide you with 3 csv files as data source from backend systems. They are `payments.csv`, `receipts.csv`, `disbursements.csv`.

A remittance is composed of a payment made from the customer sending money, and a disbursement of the money to the person receiving it. Payments and disbursements are linked by receipts.

Using these 3 csv files as data sources, please:
- Create a DBT project connecting to any database of your preference which will work as data warehouse
- Ingest the 3 data sources as raw data on your database. Use a raw schema / dataset for that. **DON'T USE SEEDS FOR SOURCES.**
- Create a first layer of data ingesting the source, deduplicating it and applying schema patterns
- Create any necessary intermediate layer to join common data by business context
- Think about your data modelling
- Generate the following metrics. Create how many marts you think are required. Be creative if you don't have a clear understanding of any of them.
  - Total amount transacted by month
  - Classify users that represent 50% of the total volume transacted
  - Recurring customers (create your definition)
  - Classify providers by failed disbursements
  - Clusters of users sending to same beneficiaries
  - Chargeback rate
- Add data tests to your models
- Send your project to a github repo and share it with us

## Scope added by the candidate (agreed during design)
- The CSVs were not provided, so synthetic data was generated (`src/generate_sample_data.py`), plus a `users.csv` for user-level metrics.
- Extra metrics: average transaction value, customer lifetime value, ARPU, MoM and YoY growth, pay-in performance (processor / bank / store).
- Kimball data marts, SCD2 snapshots, macro library, YAML metadata, MetricFlow semantic layer, Streamlit dashboard, test-data workflow.
- Project-wide decision: **no dbt seeds at all** (not even for reference data).
