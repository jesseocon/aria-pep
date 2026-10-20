"""Staging load and bronze merge, one pair of tables per stream.

Staging is overwritten every run. Bronze is merged into, never rebuilt.

- Reservations: one row per external confirmation number. A staged row
  replaces the bronze row when its export window ends on or after the stored
  one, so an older export cannot undo a newer one.
- Daily reports: each export is the whole truth for its date range. Bronze
  rows inside that range are replaced by the export's rows in one transaction;
  rows outside it are not touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from pep_connector.prepare import RESERVATIONS
from pep_connector.reports import REPORT_STREAMS
from pep_connector.schema import OUTPUT_HEADERS

KEY = "external_confirmation_number"
STAGING_EXPIRY = timedelta(days=7)
STREAM_COLUMNS: dict[str, list[str]] = {
    RESERVATIONS: OUTPUT_HEADERS,
    **{stream.name: stream.output_headers for stream in REPORT_STREAMS},
}


@dataclass(frozen=True)
class BronzeLoad:
    staging: str
    bronze: str
    staged_rows: int
    merged_rows: int


def bronze_table_id(project: str, org_id: str, slug: str, stream: str = RESERVATIONS) -> str:
    return f"{project}.bronze_{org_id}.pep__{stream}_{slug}"


def staging_table_id(project: str, org_id: str, slug: str, stream: str = RESERVATIONS) -> str:
    return f"{bronze_table_id(project, org_id, slug, stream)}__staging"


def _quoted(table_id: str) -> str:
    return f"`{table_id}`"


def create_bronze_sql(bronze: str, stream: str = RESERVATIONS) -> str:
    columns = ",\n  ".join(f"`{name}` STRING" for name in STREAM_COLUMNS[stream])
    cluster = KEY if stream == RESERVATIONS else "row_date"
    return (
        f"CREATE TABLE IF NOT EXISTS {_quoted(bronze)} (\n  {columns},\n"
        "  `_run_id` STRING,\n  `_loaded_at` TIMESTAMP\n)\n"
        f"CLUSTER BY `{cluster}`"
    )


def add_bronze_columns_sql(bronze: str, stream: str = RESERVATIONS) -> str:
    adds = [f"ADD COLUMN IF NOT EXISTS `{name}` STRING" for name in STREAM_COLUMNS[stream]]
    adds += [
        "ADD COLUMN IF NOT EXISTS `_run_id` STRING",
        "ADD COLUMN IF NOT EXISTS `_loaded_at` TIMESTAMP",
    ]
    return f"ALTER TABLE {_quoted(bronze)}\n  " + ",\n  ".join(adds)


def merge_bronze_sql(staging: str, bronze: str) -> str:
    names = [f"`{name}`" for name in OUTPUT_HEADERS]
    updates = ",\n    ".join(f"{name} = S.{name}" for name in names)
    insert_columns = ", ".join([*names, "`_run_id`", "`_loaded_at`"])
    insert_values = ", ".join([*(f"S.{name}" for name in names), "@run_id", "CURRENT_TIMESTAMP()"])
    return f"""MERGE {_quoted(bronze)} AS T
USING (
  SELECT *
  FROM {_quoted(staging)}
  WHERE NULLIF(TRIM(`{KEY}`), '') IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY `{KEY}`
    ORDER BY range_end DESC, source_file DESC, SAFE_CAST(source_line AS INT64) DESC
  ) = 1
) AS S
ON T.`{KEY}` = S.`{KEY}`
WHEN MATCHED AND S.range_end >= T.range_end THEN UPDATE SET
    {updates},
    `_run_id` = @run_id,
    `_loaded_at` = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT ({insert_columns})
  VALUES ({insert_values})"""


def replace_blocks_sql(staging: str, bronze: str, stream: str) -> str:
    names = ", ".join(f"`{name}`" for name in STREAM_COLUMNS[stream])
    return f"""BEGIN TRANSACTION;
DELETE FROM {_quoted(bronze)}
WHERE row_date IN (
  SELECT FORMAT_DATE('%Y-%m-%d', day)
  FROM (SELECT DISTINCT block_start_date, block_end_date FROM {_quoted(staging)}) AS R,
  UNNEST(GENERATE_DATE_ARRAY(
    PARSE_DATE('%Y-%m-%d', R.block_start_date), PARSE_DATE('%Y-%m-%d', R.block_end_date)
  )) AS day
);
INSERT INTO {_quoted(bronze)} ({names}, `_run_id`, `_loaded_at`)
SELECT {names}, @run_id, CURRENT_TIMESTAMP()
FROM {_quoted(staging)};
COMMIT TRANSACTION;"""


def _client(project: str, client: Any) -> Any:
    from google.cloud import bigquery

    return client if client is not None else bigquery.Client(project=project)


def ensure_bronze(project: str, org_id: str, slug: str, stream: str, client: Any = None) -> str:
    """Create the dataset and bronze table so dbt sources exist before any file arrives."""
    from google.cloud import bigquery

    bq = _client(project, client)
    dataset = bigquery.Dataset(f"{project}.bronze_{org_id}")
    dataset.location = "US"
    bq.create_dataset(dataset, exists_ok=True)
    bronze = bronze_table_id(project, org_id, slug, stream)
    bq.query(create_bronze_sql(bronze, stream)).result()
    bq.query(add_bronze_columns_sql(bronze, stream)).result()
    return bronze


def load_bronze(
    csv_path: Path,
    *,
    project: str,
    org_id: str,
    slug: str,
    run_id: str,
    stream: str = RESERVATIONS,
    client: Any = None,
) -> BronzeLoad:
    """Overwrite staging with this run's file, then merge it into bronze."""
    from google.cloud import bigquery

    bq = _client(project, client)
    bronze = ensure_bronze(project, org_id, slug, stream, bq)
    staging = staging_table_id(project, org_id, slug, stream)
    job_config = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField(name, "STRING") for name in STREAM_COLUMNS[stream]],
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        allow_quoted_newlines=True,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with csv_path.open("rb") as handle:
        load_job = bq.load_table_from_file(handle, staging, job_config=job_config)
    load_job.result()
    staged_rows = int(getattr(load_job, "output_rows", 0) or 0)

    table = bq.get_table(staging)
    table.expires = _now() + STAGING_EXPIRY
    bq.update_table(table, ["expires"])

    sql = merge_bronze_sql(staging, bronze) if stream == RESERVATIONS else replace_blocks_sql(staging, bronze, stream)
    merge_job = bq.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
        ),
    )
    merge_job.result()
    if stream == RESERVATIONS:
        merged_rows = int(getattr(merge_job, "num_dml_affected_rows", 0) or 0)
    else:
        merged_rows = staged_rows
    return BronzeLoad(staging=staging, bronze=bronze, staged_rows=staged_rows, merged_rows=merged_rows)


def _now():  # noqa: ANN202
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
