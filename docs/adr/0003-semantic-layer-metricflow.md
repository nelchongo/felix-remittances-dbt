# ADR 0003: Facts store ingredients, MetricFlow stores the formulas

- **Status:** accepted
- **Date:** 2026-11-01

## Context
The questions mix additive totals (volume) with ratios and distinct counts (chargeback rate, ARPU, LTV,
MoM / YoY). Stored ratios can't be rolled up (a monthly ARPU can't become a quarterly ARPU) and tend to be
re-implemented differently in each dashboard.

## Decision
- Facts hold only additive measures, 0/1 flags and counts; classification labels the brief asks for live on
  dimensions. The custom test `no_derived_metrics_in_facts` fails on `*_rate`, `*_pct`, `*_ratio`, `avg_*` and `median_*` columns.
- Every formula is a **MetricFlow** metric (`dbt/models/semantic/`), defined once with a label and description.
  Answers are **saved queries**; `python run.py answers` writes `docs/answers.md` from them.
- The dashboard runs SQL compiled by MetricFlow (`python run.py compile-metrics`, `mf query --explain`) on a
  read-only connection. Filters select saved queries computed at the requested grain instead of re-aggregating
  in pandas; plotly only draws.

## Consequences
- One definition per metric, correct at any grain; changing a definition is one YAML change, with no backfill.
- pytest reconciles MetricFlow with the facts (volume, net revenue, ARPU × senders, chargeback rate, YoY).
- Verified on the pinned versions: measure-level `agg_time_dimension`, SCD2 `validity_params` (resolved at day
  granularity) and `non_additive_dimension`.
- Offset (YoY) metrics also emit months after the data ends; readers trim trailing empty months.
- Fallback, if MetricFlow ever becomes a blocker: the same formulas can be computed from the stored ingredients
  in a small pandas registry, because the facts keep the ingredients.
