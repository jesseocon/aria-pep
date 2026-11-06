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
--
-- One file per business date: a day's Final Audit is never reissued, so a second file for the
-- same date (a resend, a forward) is a duplicate. Bronze may hold every copy; silver keeps the
-- first file loaded, once.
WITH bronze AS (
  {{ pep_block_rows('final_audit') }}
),

first_file AS (
  SELECT row_date, source_file, _run_id
  FROM (SELECT DISTINCT row_date, source_file, _run_id, _loaded_at FROM bronze)
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY row_date ORDER BY _loaded_at, source_file, _run_id) = 1
)

SELECT
  '{{ var("property_id") }}' AS property_id,
  SAFE.PARSE_DATE('%Y-%m-%d', b.row_date) AS business_date,
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
  b.source_file,
  SAFE_CAST(source_line AS INT64) AS source_line,
  b._run_id,
  b._loaded_at AS _bronze_loaded_at,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM bronze AS b
JOIN first_file AS f
  ON b.row_date = f.row_date
  AND b.source_file IS NOT DISTINCT FROM f.source_file
  AND b._run_id IS NOT DISTINCT FROM f._run_id
