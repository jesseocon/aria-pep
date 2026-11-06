{{
  config(
    alias=pep_stream_table_name('final_audit'),
    materialized='incremental',
    incremental_strategy='merge',
    on_schema_change='append_new_columns',
    partition_by={'field': 'business_date', 'data_type': 'date', 'granularity': 'month'},
    pre_hook="{{ pep_delete_blocks('final_audit', 'business_date') }}",
    tags=['silver', 'pep'],
  )
}}

-- PEP's Final Audit: one row per line of each section (Charges, Taxes, Payments, ...) for a
-- business date. Net Today is the day's amount after adjustments; daily balancing compares it
-- with what HIA imported.
SELECT
  '{{ var("property_id") }}' AS property_id,
  SAFE.PARSE_DATE('%Y-%m-%d', row_date) AS business_date,
  NULLIF(TRIM(section), '') AS section,
  NULLIF(TRIM(`group`), '') AS line_group,
  SAFE_CAST(line AS INT64) AS line_number,
  NULLIF(TRIM(name), '') AS name,
  {{ pep_number('actual_today') }} AS actual_today,
  {{ pep_number('adjusted') }} AS adjusted,
  {{ pep_number('adjusted_transferred') }} AS adjusted_transferred,
  {{ pep_number('net_today') }} AS net_today,
  {{ pep_number('m_t_d') }} AS mtd,
  {{ pep_number('ly_m_t_d') }} AS ly_mtd,
  {{ pep_number('m_t_d_variance') }} AS mtd_variance,
  {{ pep_number('y_t_d') }} AS ytd,
  {{ pep_number('ly_t_d') }} AS ly_ytd,
  {{ pep_number('y_t_d_variance') }} AS ytd_variance,
  {{ pep_number('opening_balance') }} AS opening_balance,
  {{ pep_number('net_change') }} AS net_change,
  {{ pep_number('closing_balance') }} AS closing_balance,
  NULLIF(TRIM(hotel), '') AS hotel_name,
  NULLIF(TRIM(hotel_code), '') AS hotel_code,
  source_file,
  SAFE_CAST(source_line AS INT64) AS source_line,
  _run_id,
  _loaded_at AS _bronze_loaded_at,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM ({{ pep_block_rows('final_audit') }})
