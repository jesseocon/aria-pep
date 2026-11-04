"""PEP packages by email: trimmed reservation exports, the occupancy forecast, and the inbox."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pytest
from aria_runner import mailbox
from aria_runner.connectors import ConnectorManifest
from aria_runner.sessions import FileSessionStore
from test_assemble import _row

from pep_connector.inbox import fetch_inbox, saved_name
from pep_connector.load import replace_snapshots_sql
from pep_connector.manifest import email_manifest
from pep_connector.parse import heal_text
from pep_connector.prepare import classify, prepare_run
from pep_connector.reports import OCCUPANCY_FORECAST_DISPLAY
from pep_connector.schema import V2_DISPLAY_HEADERS

ORG = "1782243883257222643"
CONNECTION = "scenic-esdallas-pep-email"
SENDER = "noreply@hilton.com"
DAY = datetime(2026, 11, 3, 23, 48, tzinfo=timezone.utc)
REMARKS = {"Booking Remarks", "Stay Remarks", "Housekeeping Remarks", "Billing Remarks", "Other Remarks"}
TRIMMED = [header for header in V2_DISPLAY_HEADERS if header not in REMARKS]


def _line(values: list[str]) -> str:
    return ",".join(f'"{value}"' for value in values)


def _trimmed(*rows: list[str], headers: list[str] = TRIMMED) -> str:
    keep = [V2_DISPLAY_HEADERS.index(header) for header in headers]
    lines = [_line(headers), *(_line([row[i] for i in keep]) for row in rows)]
    totals = _line(["" if header not in ("Total Charges", "Nights") else "9" for header in headers])
    return "\n".join([*lines, totals]) + "\n"


def _forecast(first: str, days: int, rooms: int) -> str:
    start = datetime.strptime(first, "%Y-%m-%d")
    lines = [_line(OCCUPANCY_FORECAST_DISPLAY)]
    for offset in range(days):
        day = start + timedelta(days=offset)
        values = [""] * len(OCCUPANCY_FORECAST_DISPLAY)
        values[0], values[1], values[8] = day.strftime("%b %d, %Y"), day.strftime("%A"), str(rooms)
        lines.append(_line(values))
    lines.append(_line(["", "", "$1.00", *[""] * (len(OCCUPANCY_FORECAST_DISPLAY) - 3)]))
    return "\n".join(lines) + "\n"


def test_an_export_without_the_remarks_columns_reads_by_name() -> None:
    text = _trimmed(_row(1, Stay_Requests="Late check-in"), _row(2))
    records = heal_text(text, "reservations-today-plus-90.csv").records
    assert [r.parse_status for r in records] == ["ok", "ok", "removed_summary_row"]
    first = records[0].fields
    assert len(first) == len(V2_DISPLAY_HEADERS)
    assert first["external_confirmation_number"] == "900000001"
    assert first["stay_requests"] == "Late check-in"  # after the dropped columns, still in place
    assert first["booking_remarks"] == first["other_remarks"] == ""


def test_a_trimmed_export_must_keep_every_typed_column() -> None:
    headers = [header for header in TRIMMED if header != "Total Taxes"]
    with pytest.raises(ValueError, match="Expected 63 or 66 columns, got 60"):
        heal_text(_trimmed(_row(1), headers=headers), "reservations.csv")


def test_a_reordered_export_is_not_read_by_name() -> None:
    headers = list(TRIMMED)
    headers[3], headers[4] = headers[4], headers[3]
    with pytest.raises(ValueError):
        heal_text(_trimmed(_row(1), headers=headers), "reservations.csv")


def test_the_occupancy_forecast_keeps_every_snapshot(tmp_path: Path) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "20261102T234800Z_1_occupancy-forecast-today-plus-90.csv").write_text(_forecast("2026-11-02", 3, 10))
    (inbox / "20261103T234800Z_1_occupancy-forecast-today-plus-90.csv").write_text(_forecast("2026-11-03", 3, 12))
    # A resend of the 3 Nov snapshot: the later one replaces it, not the 2 Nov one.
    (inbox / "20261103T235900Z_1_occupancy-forecast-today-plus-90.csv").write_text(_forecast("2026-11-03", 3, 14))
    assert classify(_forecast("2026-11-03", 1, 1)) == "occupancy_forecast"

    run = prepare_run(inbox, tmp_path / "out")
    batch = run.batches["occupancy_forecast"]
    rows = list(csv.DictReader(batch.staging_csv.open(encoding="utf-8")))
    seen = {(row["block_start_date"], row["row_date"], row["total_sold_rooms"]) for row in rows}
    assert seen == {
        ("2026-11-02", "2026-11-02", "10"), ("2026-11-02", "2026-11-03", "10"), ("2026-11-02", "2026-11-04", "10"),
        ("2026-11-03", "2026-11-03", "14"), ("2026-11-03", "2026-11-04", "14"), ("2026-11-03", "2026-11-05", "14"),
    }
    assert all(item.removed == 1 for item in batch.files)  # the totals row


def test_bronze_replaces_only_a_resent_snapshot() -> None:
    sql = replace_snapshots_sql("p.d.staging", "p.d.bronze", "occupancy_forecast")
    assert "WHERE block_start_date IN (SELECT DISTINCT block_start_date FROM `p.d.staging`)" in sql
    assert "row_date" not in sql.split("INSERT")[0]


def _zip(**files: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _mail(attachment: bytes, *, sender: str = SENDER) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = mailbox.address("files", CONNECTION)
    message["Subject"] = "aria-reporting-hilton-pep"
    message.set_content("The report package for Nov 03, 2026 is attached.")
    message.add_attachment(attachment, maintype="application", subtype="zip", filename="aria-reporting.zip")
    return message.as_bytes()


@pytest.fixture
def store(tmp_path: Path) -> FileSessionStore:
    return FileSessionStore(f"file://{tmp_path / 'sessions'}")


def test_an_emailed_package_heals_like_drive_files(tmp_path: Path, store: FileSessionStore) -> None:
    package = _zip(
        **{
            "reservations-today-plus-90.csv": _trimmed(_row(1), _row(2)),
            "reservations-90-365.csv": _trimmed(_row(3)),
            "occupancy-forecast-today-plus-90.csv": _forecast("2026-11-03", 2, 12),
        }
    )
    mailbox.put_message(store, ORG, CONNECTION, _mail(package), received_at=DAY, sender=SENDER)
    mailbox.put_message(store, ORG, CONNECTION, _mail(package, sender="someone@else.example"), received_at=DAY + timedelta(minutes=1))

    box = mailbox.Mailbox(store, ORG, CONNECTION)
    outcome = fetch_inbox(box, mailbox.Cursor(), tmp_path / "work", allowed_senders=["@hilton.com"])

    assert outcome.status == "ready" and outcome.messages == 2 and not outcome.failed
    assert [item.reason for item in outcome.ignored] == ["sender_not_allowed"]
    assert set(outcome.prepared.batches) == {"reservations", "occupancy_forecast"}
    assert outcome.prepared.batches["reservations"].rows == 3
    assert sorted(outcome.files) == sorted(
        saved_name(DAY, i, f"aria-reporting.zip/{name}")
        for i, name in enumerate(["reservations-today-plus-90.csv", "reservations-90-365.csv", "occupancy-forecast-today-plus-90.csv"], 1)
    )

    again = fetch_inbox(box, outcome.cursor, tmp_path / "work")
    assert again.messages == 0 and again.status == "empty"


def test_the_email_manifest_is_an_inbox_connector() -> None:
    manifest = ConnectorManifest.model_validate(email_manifest())
    assert manifest.key == "pep_email" and manifest.inbox and manifest.inbox_local_part == "files"
