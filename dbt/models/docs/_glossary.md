{# Shared column and concept definitions. Reference them with '{{ doc("<name>") }}'. #}

{# ---------------------------------------------------------------- lineage (raw) #}

{% docs col_source_file %}
Landing file the row was loaded from, e.g. `payments__2026-07.csv`. Added by `ingest/load_raw.py`.
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
