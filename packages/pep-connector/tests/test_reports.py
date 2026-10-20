import csv
from pathlib import Path

from pep_connector.load import replace_blocks_sql
from pep_connector.prepare import classify, prepare_run
from pep_connector.reports import (
    OCCUPANCY_DISPLAY,
    RATE_PLAN_DISPLAY,
    TRANSACTIONS_COMBINED_DISPLAY,
    TRANSACTIONS_V2_DISPLAY,
    display_date,
    heal_rate_plan_summary,
    heal_transactions,
)
from pep_connector.schema import V1_DISPLAY_HEADERS


def _line(values: list[str]) -> str:
    return ",".join(f'"{value}"' for value in values)


def _rate_plan(rows: list[tuple[str, str, str]]) -> str:
    lines = [_line(RATE_PLAN_DISPLAY)]
    for day, code, name in rows:
        lines.append(_line([day, "Monday", name, code, "Active", "SEG", "S", "NONE", "NONE", "$1.00", "1", "$1.00", "0", "$0.00"]))
    lines.append(_line(["", "", "", "", "", "", "", "", "", "$9.00", "9", "", "", ""]))
    return "\n".join(lines) + "\n"


def test_header_row_decides_the_stream() -> None:
    assert classify(_line(V1_DISPLAY_HEADERS)) == "reservations"
    assert classify(_line(RATE_PLAN_DISPLAY)) == "rate_plan_summary"
    assert classify(_line(OCCUPANCY_DISPLAY)) == "occupancy_summary"
    assert classify(_line(TRANSACTIONS_V2_DISPLAY)) == "transactions"
    assert classify('"Something","Else"') is None


def test_all_transactions_export_reads_guest_rows_from_the_combined_section() -> None:
    def combined(day: str, confirmation: str, group: str, amount: str) -> str:
        row = dict.fromkeys(TRANSACTIONS_COMBINED_DISPLAY, "")
        row.update({"Date": day, "Time": "09:33 AM", "Confirmation Number": confirmation, "Group Code": group})
        row.update({"Transaction Code": "RR", "Transaction Type": "CHARGE", "Amount": amount, "Folio Number": "000123"})
        return _line(list(row.values()))

    text = "\n".join(
        [
            '"Company Name","Folio Number","Date","Time"',
            '"","000123","Oct 02, 2026","09:33 AM"',
            '"Date","Time","Group Code","Rate Plan","Group Name"',
            '"Oct 05, 2026","02:00 AM","TN5","C-","Tax Notch"',
            _line(TRANSACTIONS_COMBINED_DISPLAY),
            combined("Oct 02, 2026", "12345678", "", "$125.00"),
            combined("Oct 05, 2026", "", "TN5", "-$500.00"),
        ]
    )
    assert classify(text) == "transactions"
    heal = heal_transactions(text)
    assert heal.sections == 3
    assert [record.parse_status for record in heal.records] == ["ok", "out_of_scope"]
    first = dict(zip(TRANSACTIONS_V2_DISPLAY, heal.records[0].fields, strict=True))
    assert (first["Confirmation Number"], first["Folio Number"], first["Amount"]) == ("12345678", "000123", "$125.00")


def test_display_dates_and_the_totals_row() -> None:
    assert display_date('"Jan 05, 2026"') == "2026-01-05"
    assert display_date("") is None
    heal = heal_rate_plan_summary(_rate_plan([("Jan 05, 2026", "LV0", "Best")]))
    assert [record.parse_status for record in heal.records] == ["ok", "removed_summary_row"]


def test_for_each_date_the_export_ending_last_wins(tmp_path: Path) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "a.csv").write_text(
        _rate_plan([("Jan 01, 2026", "LV0", "Old"), ("Jan 02, 2026", "LV0", "Old")]), encoding="utf-8"
    )
    (inbox / "b.csv").write_text(
        _rate_plan([("Jan 02, 2026", "LV0", "New"), ("Jan 03, 2026", "LV0", "New")]), encoding="utf-8"
    )
    (inbox / "c.csv").write_text('"Something","Else"\n', encoding="utf-8")

    run = prepare_run(inbox, tmp_path / "out")

    assert run.unrecognized == ["c.csv"]
    batch = run.batches["rate_plan_summary"]
    with batch.staging_csv.open(newline="", encoding="utf-8") as handle:
        staged = {row["row_date"]: row["rate_plan_name"] for row in csv.DictReader(handle)}
    assert batch.rows == 3
    assert staged == {"2026-01-01": "Old", "2026-01-02": "New", "2026-01-03": "New"}
    assert {(item.range_start, item.range_end) for item in batch.files} == {
        ("2026-01-01", "2026-01-02"),
        ("2026-01-02", "2026-01-03"),
    }


def test_bronze_replaces_only_the_export_date_ranges() -> None:
    sql = replace_blocks_sql("p.d.staging", "p.d.bronze", "rate_plan_summary")
    assert sql.startswith("BEGIN TRANSACTION;")
    assert "WHERE row_date IN (" in sql
    assert "GENERATE_DATE_ARRAY" in sql
    assert "TRUNCATE" not in sql.upper()
    assert sql.rstrip().endswith("COMMIT TRANSACTION;")
