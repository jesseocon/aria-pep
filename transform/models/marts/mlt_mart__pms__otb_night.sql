{{
  config(
    alias=pep_mart_table_name('pms__otb_night'),
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['reservation_id', 'stay_date', 'as_of_date'],
    on_schema_change='append_new_columns',
    partition_by={'field': 'stay_date', 'data_type': 'date', 'granularity': 'month'},
    cluster_by=['reservation_id', 'as_of_date'],
    pre_hook="{{ pep_delete_changed() }}",
    tags=['gold', 'pms'],
  )
}}

-- depends_on: {{ ref('stg_pep__reservations') }}

{# One row per reservation, per stay night, per as-of date it was on the books:
   booked on or before the as-of date and not cancelled by it. #}
WITH nights AS (
  SELECT *
  FROM {{ ref('mlt_mart__pms__stay_night') }}
  {% if is_incremental() %}
  WHERE reservation_id IN ({{ pep_changed_reservations() }})
  {% endif %}
)

SELECT
  n.pms,
  n.property_id,
  n.stay_date,
  as_of_date,
  n.reservation_id,
  n.confirmation_number,
  n.booking_date,
  n.cancellation_date,
  n.arrival_date,
  n.departure_date,
  n.status,
  n.market_segment,
  n.market_segment_code,
  n.rate_plan,
  n.source,
  n.room_revenue,
  n.room_night,
  n.is_occupied_night,
  n._silver_loaded_at,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM nights AS n
CROSS JOIN UNNEST(
  GENERATE_DATE_ARRAY(COALESCE(n.booking_date, n.arrival_date), n.stay_date)
) AS as_of_date
WHERE n.cancellation_date IS NULL OR n.cancellation_date > as_of_date
