# ADR 0004: No dbt seeds; reference data in vars

- **Status:** accepted
- **Date:** 2026-11-01

## Context
The brief says "don't use seeds for sources". Seeds are also a common shortcut for small reference tables
(payment methods, processors, corridors), which blurs the line between source data and configuration.

## Decision
- **No `seeds/` folder at all.** Source CSVs are loaded by `scripts/load_raw.py` into the `raw` schema, with a
  file-level ingestion log (new / changed / removed files) and lineage columns.
- Small reference attributes live in `dbt_project.yml` `vars` (`payment_methods`, `payment_processors`,
  `corridors`) and are rendered as SQL by the `values_from_var` macro. Dimensions combine them with the values
  observed in the data, so a new value never disappears.

## Consequences
- Reference data is versioned and reviewed like code, and changing it needs no separate load step.
- Values in the data but missing from vars still get a dimension row (with NULL attributes), which the tests surface.
- For large or frequently changing reference data, a proper source table would be the next step.
