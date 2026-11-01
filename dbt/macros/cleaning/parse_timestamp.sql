{#
    Parse a text timestamp from the backend extracts into a UTC `timestamp`.
    Accepted: ISO-8601 with `Z` (with or without milliseconds) and naive `YYYY-MM-DD HH:MM:SS`,
    which the backend writes in UTC. Anything else returns NULL, so a `not_null` test catches it.
#}
{% macro parse_timestamp(column) -%}
    try_strptime(
        trim({{ column }}),
        ['%Y-%m-%dT%H:%M:%S.%gZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S']
    )
{%- endmacro %}
