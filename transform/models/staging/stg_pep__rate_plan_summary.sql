{{
  config(
    alias=pep_stream_table_name('rate_plan_summary'),
    materialized='incremental',
    incremental_strategy='merge',
    on_schema_change='append_new_columns',
    partition_by={'field': 'report_date', 'data_type': 'date', 'granularity': 'month'},
    cluster_by=['rate_plan_code'],
    pre_hook="{{ pep_delete_blocks('rate_plan_summary', 'report_date') }}",
    tags=['silver', 'pep'],
  )
}}

SELECT
  '{{ var("property_id") }}' AS property_id,
  SAFE.PARSE_DATE('%Y-%m-%d', row_date) AS report_date,
  NULLIF(TRIM(day_of_week), '') AS day_of_week,
  NULLIF(TRIM(rate_plan_name), '') AS rate_plan_name,
  NULLIF(TRIM(rate_plan_code), '') AS rate_plan_code,
  NULLIF(TRIM(rate_code_status), '') AS rate_code_status,
  NULLIF(TRIM(market_segment), '') AS market_segment,
  NULLIF(TRIM(market_segment_code), '') AS market_segment_code,
  NULLIF(TRIM(local_market_segment_code), '') AS local_market_segment_code,
  NULLIF(TRIM(local_market_segment), '') AS local_market_segment,
  {{ pep_number('revenue') }} AS revenue,
  {{ pep_int('stays') }} AS stays,
  {{ pep_number('adr') }} AS adr,
  {{ pep_number('occupancy_contribution') }} AS occupancy_contribution,
  {{ pep_number('revpar_contribution') }} AS revpar_contribution,
  source_file,
  SAFE_CAST(source_line AS INT64) AS source_line,
  _run_id,
  _loaded_at AS _bronze_loaded_at,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM ({{ pep_block_rows('rate_plan_summary') }})
