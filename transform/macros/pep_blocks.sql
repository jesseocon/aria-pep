{#- Daily report streams. Bronze replaces whole date ranges (blocks); silver
    follows: the days in blocks loaded since silver last ran are deleted from
    silver and their bronze rows inserted. Other days are untouched. -#}

{% macro pep_new_days(table_name) -%}
  SELECT day
  FROM (
    SELECT DISTINCT block_start_date, block_end_date
    FROM {{ source('pep', table_name) }}
    WHERE _loaded_at > (
      SELECT COALESCE(MAX(_bronze_loaded_at), TIMESTAMP '1970-01-01')
      FROM {{ this }}
    )
  ) AS r,
  UNNEST(GENERATE_DATE_ARRAY(
    SAFE.PARSE_DATE('%Y-%m-%d', r.block_start_date), SAFE.PARSE_DATE('%Y-%m-%d', r.block_end_date)
  )) AS day
{%- endmacro %}

{% macro pep_block_rows(table_name) -%}
  SELECT *
  FROM {{ source('pep', table_name) }}
  {% if is_incremental() %}
  WHERE SAFE.PARSE_DATE('%Y-%m-%d', row_date) IN ({{ pep_new_days(table_name) }})
  {% endif %}
{%- endmacro %}

{% macro pep_delete_blocks(table_name, date_column) -%}
  {%- if is_incremental() -%}
    DELETE FROM {{ this }}
    WHERE {{ date_column }} IN ({{ pep_new_days(table_name) }})
  {%- endif -%}
{%- endmacro %}

{#- `$1,234.56` -> 1234.56, `($185.16)` -> -185.16, `97.24` -> 97.24 -#}
{% macro pep_number(column) -%}
  SAFE_CAST(
    CASE
      WHEN STARTS_WITH(TRIM({{ column }}), '(') THEN CONCAT('-', REGEXP_REPLACE(TRIM({{ column }}), r'[$,()%]', ''))
      ELSE NULLIF(REGEXP_REPLACE(TRIM({{ column }}), r'[$,%]', ''), '')
    END AS NUMERIC
  )
{%- endmacro %}

{% macro pep_int(column) -%}
  SAFE_CAST(NULLIF(REGEXP_REPLACE(TRIM({{ column }}), r'[,]', ''), '') AS INT64)
{%- endmacro %}
