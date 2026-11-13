"""PEP's other Final Audit export (FinalAuditV2.xlsx, downloaded by hand) in its own layout, values made up.

The rows mirror the real workbook: title in column B, "Date:" and the date in separate cells, one "Revenue"
table for room and other room revenue, amounts as text ("$1,234.56"), total rows, payments under "Payment
Information", tables the original export does not have (deposits), and the ledgers as label/value pairs.
"""

import csv
import io
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from aria_runner import mailbox
from pep_connector.final_audit import business_day, xlsx_to_csv
from pep_connector.inbox import _sort_attachments
from pep_connector.prepare import classify, prepare_run

# Headings start in column E, as in the real export (column F stays empty).
HEADINGS = [None, None, None, None, "Actual Today", None, "Adjusted", "Net Today", "M-T-D", "LY-M-T-D", "Variance", "Y-T-D", "LY-T-D", "Variance"]


def line(name: str, actual: str, adjusted: str, net: str) -> list[object]:
    return [None, name, None, None, actual, None, adjusted, net, "$10.00", "$9.00", "$1.00", "$100.00", "$90.00", "$10.00"]


def v2_workbook(*, date: str = "Nov 07, 2026") -> bytes:
    book = Workbook()
    sheet = book.active
    rows: list[list[object]] = [
        [None, None, "Test Hotel - Downtown", None, None, None, None, None, None, None, None, "Date:", date],
        [None, None, "Hotel ID: TSTHT", None, None, None, None, None, None, None, None, "Report Run Date:", "Nov 13, 2026"],
        [None] * 11 + ["Night Audit Time:  ", datetime(2026, 11, 8, 2, 31, 44)],
        [None] * 11 + ["Report Run Time:  ", "7:21:24 AM"],
        [None] * 11 + ["Username: ", "Test User"],
        [None, "Final Audit"],
        [],
        [None, "Revenue & Charges"],
        [None, "Revenue", *HEADINGS[2:]],
        line("GUEST ROOM", "$1,000.00", "-$43.12", "$956.88"),
        line("0", "$307.19", "$0.00", "$307.19"),
        line("ADD-ON Traveling w/ Pet ", "$75.00", "$0.00", "$75.00"),
        line("eStandby Room Upgrade", "$0.00", "$0.00", "$0.00"),
        line("Total Room Rent", "$1,382.19", "-$43.12", "$1,339.07"),
        [None, "Charges", *HEADINGS[2:]],
        line("BANQUETS COFFEE BRK", "$80.00", "$0.00", "$80.00"),
        line("PARKING", "$224.00", "-$32.00", "$192.00"),
        line("Total Revenues", "$1,686.19", "-$75.12", "$1,611.07"),
        [None, "Taxes", *HEADINGS[2:]],
        line("Sales Tax 8.25 PERCENT", "$12.00", "$0.00", "$12.00"),
        line("Total Taxes", "$12.00", "$0.00", "$12.00"),
        [None, "Surcharges & Fees", *HEADINGS[2:]],
        line("TOURISM PID REIMB FEE", "$5.00", "$0.00", "$5.00"),
        line("Total Taxes", "$5.00", "$0.00", "$5.00"),
        line("Total Revenue & Charges", "$1,703.19", "-$75.12", "$1,628.07"),
        [],
        [None, "Payment Information"],
        [None, "Cash", *HEADINGS[2:]],
        line("CASH", "$0.00", "$0.00", "$0.00"),
        [None, "Card", *HEADINGS[2:]],
        line("VISA", "$600.00", "-$50.00", "$550.00"),
        [None, "Other", *HEADINGS[2:]],
        line("ACH/Bank Transfer/Wire/Lockbox 1", "$0.00", "$0.00", "$0.00"),
        line("SIMPHONY VISA", "$96.07", "$0.00", "$96.07"),
        [None, "Direct Bill", *HEADINGS[2:]],
        line("BILL TO COMPANY", "$10.00", "-$7.78", "$2.22"),
        line("Total Payments", "$706.07", "-$57.78", "$648.29"),
        [None, "Deposit Information", None, None, None, None, "Actual Today", None, "Adjusted", None, "Net Today", None, "M-T-D"],
        [None, "IN HOUSE", None, None, "$0.00", None, None, None, "$0.00", None, "$0.00", None, "$0.00"],
        [None, "Guest Balance Ledger"],
        [None, "In House Opening Balance:", None, None, None, None, None, None, None, "$1,654.21"],
        [None, "In House Net Change:", None, None, None, None, None, None, None, "-$13.54"],
        [None, "In House Closing Balance:", None, None, None, None, None, None, "$1,640.67"],
        [None, "Group Master Starting Balance:", None, None, None, None, None, None, None, "-$12.00"],
        [None, "Group Master Net Change:", None, None, None, None, None, None, None, "$2.00"],
        [None, "Group Master Ending Balance:", None, None, None, None, None, None, "-$10.00"],
        [None, "Advanced Deposit Balance"],
        [None, None, None, None, "Group Master Opening Balance:", None, None, None, None, "-$30.00"],
        [None, None, None, None, "Group Master Net Change:", None, None, None, None, "-$2.00"],
        [None, None, None, None, "Group Master Closing Balance:", None, None, None, "-$32.00"],
        [None, "Hotel Balance"],
        [None, None, None, None, None, None, None, "Beginning Balance:", "$100.00"],
        [None, "Room Statistics", None, "Today", None, None, "M-T-D"],
        [None, "Rooms sold", None, 226.0, None, None, 1329.0],
    ]
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_the_v2_layout_becomes_the_same_rows_as_the_original_export() -> None:
    text = xlsx_to_csv(v2_workbook())
    assert text is not None
    assert business_day(text) == "2026-11-07"
    lines = rows(text)
    assert [(r["Section"], r["Group"], r["Line"], r["Name"]) for r in lines] == [
        ("Room Revenue", "Charge Type Name", "1", "GUEST ROOM"),
        ("Room Revenue", "Charge Type Name", "2", "0"),
        ("Other Room Revenue", "Charge Type Name", "1", "ADD-ON TRAVELING W/ PET"),
        ("Other Room Revenue", "Charge Type Name", "2", "ESTANDBY ROOM UPGRADE"),
        ("Charges", "Charge Type Name", "1", "BANQUETS COFFEE BRK"),
        ("Charges", "Charge Type Name", "2", "PARKING"),
        ("Taxes", "Tax Type", "1", "SALES TAX 8.25 PERCENT"),
        ("Fees", "Tax Type", "1", "TOURISM PID REIMB FEE"),
        ("Payments", "Cash", "1", "CASH"),
        ("Payments", "Card", "2", "VISA"),
        ("Payments", "Other", "3", "ACH/BANK TRANSFER/WIRE/LOCKBOX 1"),
        ("Payments", "Other", "4", "SIMPHONY VISA"),
        ("Payments", "DIRECT BILL", "5", "BILL TO COMPANY"),
        ("Balance Information", "Ledger Name", "1", "In House"),
        ("Balance Information", "Ledger Name", "2", "Group Master"),
        ("Balance Information", "Ledger Name", "7", "Advance Deposit Group"),
    ]
    guest = lines[0]
    assert (guest["Actual Today"], guest["Adjusted"], guest["Net Today"], guest["Adjusted Transferred"]) == ("1000", "-43.12", "956.88", "")
    assert (guest["M-T-D"], guest["M-T-D Variance"], guest["Y-T-D Variance"]) == ("10", "1", "10")
    assert (guest["Hotel"], guest["Hotel Code"], guest["Business Date"]) == ("Test Hotel - Downtown", "TSTHT", "Nov 07, 2026")
    in_house = lines[13]
    assert (in_house["Opening Balance"], in_house["Net Change"], in_house["Closing Balance"]) == ("1654.21", "-13.54", "1640.67")
    assert (lines[15]["Opening Balance"], lines[15]["Closing Balance"]) == ("-30", "-32")


def test_the_business_date_comes_from_the_workbook_not_its_name() -> None:
    assert business_day(xlsx_to_csv(v2_workbook(date="Nov 12, 2026")) or "") == "2026-11-12"


def test_revenue_and_payments_add_up_to_the_workbook_totals() -> None:
    lines = rows(xlsx_to_csv(v2_workbook()) or "")
    revenue = sum(Decimal(r["Net Today"]) for r in lines if r["Section"] in {"Room Revenue", "Other Room Revenue", "Charges", "Fees", "Taxes"})
    payments = sum(Decimal(r["Net Today"]) for r in lines if r["Section"] == "Payments")
    assert (revenue, payments) == (Decimal("1628.07"), Decimal("648.29"))


def test_the_v2_csv_is_classified_and_healed_as_the_final_audit_stream(tmp_path: Path) -> None:
    text = xlsx_to_csv(v2_workbook())
    assert classify(text) == "final_audit"
    source = tmp_path / "in"
    source.mkdir()
    (source / "20261113T153839Z_1_FinalAuditV2.csv").write_text(text)
    batch = prepare_run(source, tmp_path / "out").batches["final_audit"]
    staged = list(csv.DictReader(batch.staging_csv.open()))
    assert batch.rows == 16
    assert {row["row_date"] for row in staged} == {"2026-11-07"}
    assert {row["parse_status"] for row in staged} == {"ok"}


def test_attachments_that_could_have_been_reports_are_reported_and_logos_are_not() -> None:
    sheet = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    other = Workbook()
    other.active.append(["Manager Report"])
    buffer = io.BytesIO()
    other.save(buffer)
    reports, skipped = _sort_attachments(
        [
            mailbox.Attachment("FinalAuditV2.xlsx", sheet, v2_workbook()),
            mailbox.Attachment("Manager Report.xlsx", sheet, buffer.getvalue()),
            mailbox.Attachment("Final Audit.pdf", "application/pdf", b"%PDF"),
            mailbox.Attachment("logo.png", "image/png", b"\x89PNG"),
            mailbox.Attachment("invite.ics", "text/calendar", b"BEGIN:VCALENDAR"),
        ]
    )
    assert [name for name, _ in reports] == ["FinalAuditV2.csv"]
    assert [name for name, _ in skipped] == ["Manager Report.xlsx", "Final Audit.pdf"]


# The six workbooks a person downloaded from PEP (Nov 6-12, 2026), kept out of the repo like the other real samples.
SAMPLES = Path(os.environ.get("PEP_FINAL_AUDIT_V2_DIR", "/nonexistent"))


@pytest.mark.skipif(not SAMPLES.is_dir(), reason="set PEP_FINAL_AUDIT_V2_DIR to a folder of FinalAuditV2 workbooks")
def test_real_v2_workbooks_add_up_to_their_own_totals() -> None:
    files = sorted(SAMPLES.glob("*.xlsx"))
    assert files
    for path in files:
        data = path.read_bytes()
        lines = rows(xlsx_to_csv(data) or "")
        assert lines, path.name
        totals = {}
        for row in load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True):
            if len(row) > 7 and isinstance(row[1], str) and row[1].strip() in ("Total Revenue & Charges", "Total Payments"):
                totals[row[1].strip()] = Decimal(str(row[7]).replace("$", "").replace(",", ""))
        revenue = sum(Decimal(r["Net Today"] or "0") for r in lines if r["Section"] in {"Room Revenue", "Other Room Revenue", "Charges", "Fees", "Taxes"})
        payments = sum(Decimal(r["Net Today"] or "0") for r in lines if r["Section"] == "Payments")
        assert revenue == totals["Total Revenue & Charges"], path.name
        assert payments == totals["Total Payments"], path.name
        assert len([r for r in lines if r["Section"] == "Balance Information"]) == 7, path.name


def test_a_skipped_attachment_raises_an_alert() -> None:
    import logging

    from pep_connector.email_connector import _report_outcome
    from pep_connector.inbox import InboxOutcome, SkippedAttachment

    class Ctx:
        logger = logging.getLogger("test")

        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, object]]] = []

        def report(self, kind: str, **fields: object) -> None:
            self.events.append((kind, fields))

    ctx = Ctx()
    outcome = InboxOutcome(status="empty", cursor=mailbox.Cursor(None, []), messages=1)
    outcome.skipped.append(SkippedAttachment("20261113T153839Z_x.eml", "jesse@example.com", "Final Audit.pdf", "not a CSV or Excel report"))
    _report_outcome(ctx, outcome)
    warning = next(fields for kind, fields in ctx.events if kind == "warning")
    assert warning["code"] == "ignored_attachment" and warning["alert"] is True
    assert "Final Audit.pdf" in str(warning["message"])
