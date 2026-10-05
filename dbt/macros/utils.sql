{# Use custom schema names as-is (staging, intermediate, marts) instead of prefixing the target schema. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}


{# Stripe `created` fields are Unix seconds. make_timestamp(micros) returns a naive UTC timestamp,
   so results do not depend on the session time zone. #}
{% macro epoch_to_timestamp(column) -%}
    make_timestamp({{ column }}::bigint * 1000000)
{%- endmacro %}


{# Minor units (cents, or whole yen for zero-decimal currencies) to US dollars. #}
{% macro minor_to_usd(amount, exponent, usd_per_unit) -%}
    ({{ amount }} / pow(10, {{ exponent }}) * {{ usd_per_unit }})
{%- endmacro %}


{% macro experiment_start_ts() -%}
    timestamp '{{ var("experiment_start_date") }}'
{%- endmacro %}

{% macro experiment_end_ts() -%}
    timestamp '{{ var("experiment_end_date") }}'
{%- endmacro %}

{% macro pre_period_start_ts() -%}
    timestamp '{{ var("pre_period_start_date") }}'
{%- endmacro %}

{# Exclusive cutoff for "observed as of analysis_date": the end of that day. #}
{% macro analysis_cutoff_ts() -%}
    (timestamp '{{ var("analysis_date") }}' + interval 1 day)
{%- endmacro %}
