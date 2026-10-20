{{
  config(
    alias=pep_stream_table_name('reservations'),
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='external_confirmation_number',
    on_schema_change='append_new_columns',
    cluster_by=['external_confirmation_number'],
    tags=['silver', 'pep'],
  )
}}

WITH bronze AS (
  SELECT *
  FROM {{ source('pep', 'reservations') }}
  WHERE parse_status IN ('ok', 'healed')
    AND NULLIF(TRIM(external_confirmation_number), '') IS NOT NULL
  {% if is_incremental() %}
    AND _loaded_at > (
      SELECT COALESCE(MAX(_bronze_loaded_at), TIMESTAMP '1970-01-01')
      FROM {{ this }}
    )
  {% endif %}
)

SELECT
  '{{ var("property_id") }}' AS property_id,
  TRIM(external_confirmation_number) AS external_confirmation_number,
  NULLIF(TRIM(confirmation_number), '') AS confirmation_number,
  NULLIF(TRIM(status), '') AS status,
  NULLIF(TRIM(market_segment), '') AS market_segment,
  NULLIF(TRIM(market_segment_code), '') AS market_segment_code,
  NULLIF(TRIM(rate_plan), '') AS rate_plan,
  NULLIF(TRIM(source), '') AS source,
  SAFE.PARSE_DATE('%b %e, %Y', NULLIF(TRIM(booking_date), '')) AS booking_date,
  SAFE.PARSE_DATE('%b %e, %Y', NULLIF(TRIM(cancellation_date), '')) AS cancellation_date,
  SAFE.PARSE_DATE('%b %e, %Y', NULLIF(TRIM(arrival_date), '')) AS arrival_date,
  SAFE.PARSE_DATE('%b %e, %Y', NULLIF(TRIM(departure_date), '')) AS departure_date,
  SAFE_CAST(NULLIF(REGEXP_REPLACE(TRIM(average_room_rate), r'[$,]', ''), '') AS NUMERIC) AS average_room_rate,
  SAFE.PARSE_DATE('%Y-%m-%d', range_start) AS range_start,
  SAFE.PARSE_DATE('%Y-%m-%d', range_end) AS range_end,
  source_file,
  SAFE_CAST(source_line AS INT64) AS source_line,
  parse_status,
  _run_id,
  _loaded_at AS _bronze_loaded_at,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM bronze
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY TRIM(external_confirmation_number)
  ORDER BY range_end DESC, source_file DESC, SAFE_CAST(source_line AS INT64) DESC
) = 1
