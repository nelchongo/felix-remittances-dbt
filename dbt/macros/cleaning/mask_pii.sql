{#
    Mask a PII value for analytics-facing models.
      email: first character + *** + domain   (maria.lopez@gmail.com -> m***@gmail.com)
      phone: *** + last 4 digits              (+16558289714 -> ***9714)
      text:  first character + ***            (Teresa -> T***)
#}
{% macro mask_pii(column, kind='text') -%}
    {%- if kind == 'email' -%}
        regexp_replace({{ column }}, '^(.)[^@]*(@.*)$', '\1***\2')
    {%- elif kind == 'phone' -%}
        case when {{ column }} is not null then '***' || right({{ column }}, 4) end
    {%- elif kind == 'text' -%}
        case when {{ column }} is not null then left({{ column }}, 1) || '***' end
    {%- else -%}
        {{ exceptions.raise_compiler_error("mask_pii: kind must be email, phone or text, got '" ~ kind ~ "'") }}
    {%- endif -%}
{%- endmacro %}
