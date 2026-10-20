{{
  config(
    alias=pep_dim_table_name('pms__rate_plan'),
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['pms', 'property_id', 'rate_plan'],
    on_schema_change='append_new_columns',
    tags=['gold', 'pms'],
  )
}}

{# Latest name per rate plan code. A row is replaced only by a report date on
   or after the one stored, so reloading an old export cannot roll a name back. #}
WITH latest AS (
  SELECT
    'pep' AS pms,
    property_id,
    rate_plan_code AS rate_plan,
    rate_plan_name,
    rate_code_status,
    market_segment,
    market_segment_code,
    report_date AS last_seen_date,
    _loaded_at AS _silver_loaded_at
  FROM {{ ref('stg_pep__rate_plan_summary') }}
  WHERE rate_plan_code IS NOT NULL
  {% if is_incremental() %}
    AND _loaded_at > (
      SELECT COALESCE(MAX(_silver_loaded_at), TIMESTAMP '1970-01-01') FROM {{ this }}
    )
  {% endif %}
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY rate_plan_code
    ORDER BY report_date DESC, stays DESC, revenue DESC, market_segment_code
  ) = 1
)

SELECT
  l.pms,
  l.property_id,
  l.rate_plan,
  l.rate_plan_name,
  l.rate_code_status,
  l.market_segment,
  l.market_segment_code,
  l.last_seen_date,
  l._silver_loaded_at,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM latest AS l
{% if is_incremental() %}
LEFT JOIN {{ this }} AS t
  ON t.pms = l.pms AND t.property_id = l.property_id AND t.rate_plan = l.rate_plan
WHERE t.rate_plan IS NULL OR l.last_seen_date >= t.last_seen_date
{% endif %}
