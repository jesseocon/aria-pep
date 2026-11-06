"""A Final Audit workbook in PEP's layout (values made up) becomes one row per line."""

import csv
import io
from pathlib import Path

from openpyxl import Workbook

from aria_runner import mailbox
from pep_connector.final_audit import business_day, xlsx_to_csv
from pep_connector.inbox import _reports
from pep_connector.prepare import classify, prepare_run

AMOUNTS = ["Actual Today", "Adjusted", "Adjusted Transferred", "Net Today", "M-T-D", "LY-M-T-D", "Variance", "Y-T-D", "LY-T-D", "Variance"]


def workbook(*, title: str = "Final Audit") -> bytes:
    book = Workbook()
    sheet = book.active
    rows: list[list[object]] = [
        ["Test Hotel - Downtown", None, None, None, None, None, None, None, None, "Date: Nov 05, 2026"],
        ["TSTHT", None, None, None, None, None, None, None, None, "Report Run Date: Nov 06 2026"],
        [None] * 9 + ["Report Run Time: 05:14:16 AM"],
        [], [], [], [],
        [title],
        [], [],
        [None, "Room Revenue"],
        [None, "Charge Type Name", *AMOUNTS],
        [1.0, "0", 0.0, 0.0, 0.0, 0.0, -150.0, 434.0, -584.0, 44.13, 35.07, 9.06],
        [2.0, "GUEST ROOM", 1000.0, -100.0, 0.0, 900.0, 5000.0, 4000.0, 1000.0, 90000.0, 80000.0, 10000.0],
        [None, None, 1000.0, -100.0, 0.0, 900.0, 4850.0, 4434.0, 416.0, 90044.13, 80035.07, 10009.06],
        [None, "Charges"],
        [None, "Charge Type Name", *AMOUNTS],
        [1.0, "BANQUETS COFFEE BRK", 80.0, 0.0, 0.0, 80.0, 80.0, 15200.0, -15120.0, 19271.0, 40192.0, -20921.0],
        [2.0, "PARKING", 224.0, -32.0, 0.0, 192.0, 928.0, 720.0, 208.0, 816.0, 194.0, 622.0],
        [None, None, 304.0, -32.0, 0.0, 272.0, 1008.0, 15920.0, -14912.0, 20087.0, 40386.0, -20299.0],
        [None, "Payments"],
        [None, "Card", *AMOUNTS],
        [3.0, "VISA", 600.0, -50.0, 0.0, 550.0, 3000.0, 4000.0, -1000.0, 80000.0, 60000.0, 20000.0],
        [None, "Other", *AMOUNTS],
        [12.0, "SIMPHONY VISA", 96.07, 0.0, 0.0, 96.07, 396.69, 418.03, -22.03, 2363.36, 1273.34, 1090.02],
        [None, None, 696.07, -50.0, 0.0, 646.07, 3396.69, 4418.03, -1021.34, 82363.36, 61273.34, 21090.02],
        [None, "Statistical Counts"],
        [None, "Type", "Actual Today", "M-T-D", "LY-M-T-D", "Y-T-D", "LY-T-D"],
        [11.0, "Total Sold Rooms", 231.0, 1103.0, 1102.0, 65343.0, 26027.0],
        [None, "Balance Information"],
        [None, "Ledger Name", "Opening Balance", "Net Change", "Closing Balance"],
        [1.0, "In House", 1654.21, -13.54, 1640.67],
        [None, "END OF REPORT"],
    ]
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_every_numbered_line_becomes_a_row_with_its_section_and_group() -> None:
    text = xlsx_to_csv(workbook())
    assert text is not None
    assert business_day(text) == "2026-11-05"
    lines = rows(text)
    assert [(r["Section"], r["Name"]) for r in lines] == [
        ("Room Revenue", "0"),
        ("Room Revenue", "GUEST ROOM"),
        ("Charges", "BANQUETS COFFEE BRK"),
        ("Charges", "PARKING"),
        ("Payments", "VISA"),
        ("Payments", "SIMPHONY VISA"),
        ("Statistical Counts", "Total Sold Rooms"),
        ("Balance Information", "In House"),
    ]
    coffee = lines[2]
    assert (coffee["Group"], coffee["Line"], coffee["Actual Today"], coffee["Net Today"]) == ("Charge Type Name", "1", "80", "80")
    assert (coffee["M-T-D Variance"], coffee["Y-T-D Variance"]) == ("-15120", "-20921")
    assert (lines[3]["Adjusted"], lines[3]["Net Today"]) == ("-32", "192")
    assert (lines[5]["Group"], lines[5]["Net Today"]) == ("Other", "96.07")
    stats = lines[6]
    assert (stats["Actual Today"], stats["M-T-D"], stats["Y-T-D"], stats["Net Today"]) == ("231", "1103", "65343", "")
    ledger = lines[7]
    assert (ledger["Opening Balance"], ledger["Net Change"], ledger["Closing Balance"]) == ("1654.21", "-13.54", "1640.67")
    assert (coffee["Hotel"], coffee["Hotel Code"]) == ("Test Hotel - Downtown", "TSTHT")


def test_other_workbooks_are_not_final_audits() -> None:
    assert xlsx_to_csv(workbook(title="Manager Report")) is None
    assert xlsx_to_csv(b"not a workbook") is None


def test_the_csv_is_classified_and_healed_as_the_final_audit_stream(tmp_path: Path) -> None:
    text = xlsx_to_csv(workbook())
    assert classify(text) == "final_audit"
    source = tmp_path / "in"
    source.mkdir()
    (source / "20261106T121400Z_1_Final Audit.csv").write_text(text)
    run = prepare_run(source, tmp_path / "out")
    batch = run.batches["final_audit"]
    assert batch.rows == 8
    staged = list(csv.DictReader(batch.staging_csv.open()))
    assert {row["row_date"] for row in staged} == {"2026-11-05"}
    assert {row["parse_status"] for row in staged} == {"ok"}
    assert next(row for row in staged if row["name"] == "BANQUETS COFFEE BRK")["net_today"] == "80"


def test_inbox_takes_final_audit_workbooks_and_csvs_and_skips_other_files() -> None:
    attachments = [
        mailbox.Attachment("Final Audit.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", workbook()),
        mailbox.Attachment("Other Report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", workbook(title="Other")),
        mailbox.Attachment("rate-plan-summary.csv", "text/csv", b'"Date","Day Of Week"\n'),
        mailbox.Attachment("logo.png", "image/png", b"\x89PNG"),
    ]
    found = _reports(attachments)
    assert [name for name, _ in found] == ["Final Audit.csv", "rate-plan-summary.csv"]
    assert found[0][1].decode().startswith('"Business Date","Section","Group"')
