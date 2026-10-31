{{
  config(
    alias=pep_mart_table_name('pms__stay_night'),
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['reservation_id', 'stay_date'],
    on_schema_change='append_new_columns',
    partition_by={'field': 'stay_date', 'data_type': 'date', 'granularity': 'month'},
    cluster_by=['reservation_id'],
    pre_hook="{{ pep_delete_changed() }}",
    tags=['gold', 'pms'],
  )
}}

WITH reservations AS (
  SELECT *
  FROM {{ ref('stg_pep__reservations') }}
  WHERE arrival_date IS NOT NULL
    AND departure_date IS NOT NULL
    AND departure_date > arrival_date
  {% if is_incremental() %}
    AND external_confirmation_number IN ({{ pep_changed_reservations() }})
  {% endif %}
)

SELECT
  'pep' AS pms,
  property_id,
  stay_date,
  external_confirmation_number AS reservation_id,
  confirmation_number,
  booking_date,
  cancellation_date,
  arrival_date,
  departure_date,
  status,
  market_segment,
  market_segment_code,
  CAST(NULL AS STRING) AS market_group,
  rate_plan,
  source,
  CAST(average_room_rate AS NUMERIC) AS room_revenue,
  1 AS room_night,
  UPPER(COALESCE(status, '')) NOT IN ('CANCELLED', 'CANCELED', 'NO SHOW') AS is_occupied_night,
  _loaded_at AS _silver_loaded_at,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM reservations
CROSS JOIN UNNEST(
  GENERATE_DATE_ARRAY(arrival_date, DATE_SUB(departure_date, INTERVAL 1 DAY))
) AS stay_date
