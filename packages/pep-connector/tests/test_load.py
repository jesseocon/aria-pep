from __future__ import annotations

from pathlib import Path

from pep_connector.load import (
    bronze_table_id,
    load_bronze,
    merge_bronze_sql,
    staging_table_id,
)
from pep_connector.schema import OUTPUT_HEADERS

PROJECT = "hospitalityops-dev"
ORG = "1791938321619893710"
SLUG = "dallas-love-field-pep-production"


class _Job:
    def __init__(self, **attrs: object) -> None:
        self.__dict__.update(attrs)

    def result(self) -> None:
        return None


class _Table:
    expires = None


class _Client:
    def __init__(self) -> None:
        self.loads: list[tuple[str, dict]] = []
        self.queries: list[tuple[str, object]] = []
        self.updated: list[list[str]] = []

    def create_dataset(self, dataset: object, exists_ok: bool = False) -> None:
        assert exists_ok

    def load_table_from_file(self, handle, table: str, job_config) -> _Job:  # noqa: ANN001
        assert handle.read(1)
        self.loads.append((table, job_config))
        return _Job(output_rows=1)

    def get_table(self, table: str) -> _Table:
        return _Table()

    def update_table(self, table: _Table, fields: list[str]) -> None:
        assert table.expires is not None
        self.updated.append(fields)

    def query(self, sql: str, job_config: object = None) -> _Job:
        self.queries.append((sql, job_config))
        return _Job(num_dml_affected_rows=1)


def test_staging_is_overwritten_and_bronze_is_merged(tmp_path: Path) -> None:
    from google.cloud import bigquery

    csv_path = tmp_path / "bronze.csv"
    csv_path.write_text("a\n1\n", encoding="utf-8")
    client = _Client()

    result = load_bronze(csv_path, project=PROJECT, org_id=ORG, slug=SLUG, run_id="run-1", client=client)

    staging = staging_table_id(PROJECT, ORG, SLUG)
    bronze = bronze_table_id(PROJECT, ORG, SLUG)
    assert result.staging == staging
    assert result.bronze == bronze
    assert staging.endswith("__staging")
    table, config = client.loads[0]
    assert table == staging
    assert config.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE
    assert [field.name for field in config.schema] == OUTPUT_HEADERS
    assert client.updated == [["expires"]]
    sqls = [sql for sql, _ in client.queries]
    assert sqls[0].startswith(f"CREATE TABLE IF NOT EXISTS `{bronze}`")
    assert sqls[1].startswith(f"ALTER TABLE `{bronze}`")
    assert sqls[2].startswith(f"MERGE `{bronze}`")
    assert result.merged_rows == 1


def test_merge_keys_on_external_confirmation_and_keeps_newer_exports() -> None:
    sql = merge_bronze_sql("p.d.staging", "p.d.bronze")
    assert "ON T.`external_confirmation_number` = S.`external_confirmation_number`" in sql
    assert "WHEN MATCHED AND S.range_end >= T.range_end THEN UPDATE" in sql
    assert "WHEN NOT MATCHED THEN" in sql
    assert "TRUNCATE" not in sql.upper()
    assert "DELETE" not in sql.upper()
