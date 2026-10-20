{#- Reservations whose silver row changed since this gold table last saw them. -#}
{% macro pep_changed_reservations() -%}
  SELECT external_confirmation_number
  FROM {{ ref('stg_pep__reservations') }}
  WHERE _loaded_at > (
    SELECT COALESCE(MAX(_silver_loaded_at), TIMESTAMP '1970-01-01')
    FROM {{ this }}
  )
{%- endmacro %}

{#- A changed reservation can lose nights (shorter stay, cancellation), so its
    old gold rows go before the new ones are merged in. -#}
{% macro pep_delete_changed() -%}
  {%- if is_incremental() -%}
    DELETE FROM {{ this }}
    WHERE reservation_id IN ({{ pep_changed_reservations() }})
  {%- endif -%}
{%- endmacro %}
