{# Calendar date in IST of a TIMESTAMPTZ, independent of the session time zone. #}
{% macro ist_date(col) -%}
    cast(timezone('Asia/Kolkata', {{ col }}) as date)
{%- endmacro %}
