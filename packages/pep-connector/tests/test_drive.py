from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import os

from pep_connector.drive import (
    drive_impersonate,
    fetch_drive,
    finalize_drive,
    parse_folder_id,
    run_folder_name,
    sync_drive,
)
from pep_connector.schema import V1_DISPLAY_HEADERS


def _csv() -> bytes:
    fields = [""] * len(V1_DISPLAY_HEADERS)
    fields[0] = "BAR"
    fields[2] = "12345678"
    fields[5] = "EXT1"
    fields[9] = "RESERVED"
    fields[10] = "Guest, Test"
    fields[26] = "Jan 15, 2025"
    fields[30] = "Feb 1, 2025"
    fields[32] = "Feb 3, 2025"
    for header, value in {
        "Booking Time": "9:00 AM",
        "Nights": "2",
        "Adults": "1",
        "CHILDREN": "0",
        "Total Charges": "$230.00",
        "Total Room Revenue": "$200.00",
        "Total Taxes": "$30.00",
        "Total Payments": "$0.00",
        "Balance": "$230.00",
        "Average Room Rate": "$100.00",
    }.items():
        fields[V1_DISPLAY_HEADERS.index(header)] = value
    header = ",".join(f'"{header}"' for header in V1_DISPLAY_HEADERS)
    row = ",".join(f'"{value}"' for value in fields)
    return f"{header}\n{row}\n".encode()


class _Call:
    def __init__(self, result: dict) -> None:
        self._result = result

    def execute(self) -> dict:
        return self._result


class FakeDrive:
    def __init__(self, files: list[dict]) -> None:
        self.items = files
        self.moved: list[tuple[str, str, str]] = []
        self.created: list[dict] = []

    def files(self) -> FakeDrive:
        return self

    def get(self, *, fileId: str, **_kwargs: object) -> _Call:
        return _Call({"id": fileId})

    def list(self, **_kwargs: object) -> _Call:
        return _Call({"files": list(self.items)})

    def create(self, *, body: dict, **_kwargs: object) -> _Call:
        self.created.append(body)
        file_id = f"id-{body['name']}"
        self.items.append({"id": file_id, "name": body["name"], "mimeType": body["mimeType"]})
        return _Call({"id": file_id})

    def update(self, *, fileId: str, addParents: str, removeParents: str, **_kwargs: object) -> _Call:
        self.moved.append((fileId, addParents, removeParents))
        return _Call({"id": fileId})


def _download(_service: FakeDrive, file_id: str, dest: Path) -> None:
    dest.write_bytes(_csv())
    dest.touch()
    assert file_id


def test_folder_url_becomes_the_id() -> None:
    url = "https://drive.google.com/drive/u/0/folders/abc-123?usp=sharing"
    assert parse_folder_id(url) == "abc-123"
    assert parse_folder_id("abc-123") == "abc-123"


def test_impersonates_the_drive_service_account() -> None:
    os.environ.pop("PEP_DRIVE_IMPERSONATE", None)
    assert drive_impersonate().endswith("@gn-shared-services-production.iam.gserviceaccount.com")
    os.environ["PEP_DRIVE_IMPERSONATE"] = "other@example.iam.gserviceaccount.com"
    assert drive_impersonate() == "other@example.iam.gserviceaccount.com"
    os.environ.pop("PEP_DRIVE_IMPERSONATE", None)


def test_sync_moves_a_quiet_csv(tmp_path: Path) -> None:
    moment = datetime(2026, 10, 19, 4, 1, 22, tzinfo=timezone.utc)
    old = (moment - timedelta(minutes=5)).isoformat()
    drive = FakeDrive(
        [{"id": "file-1", "name": "Reservations.csv", "mimeType": "text/csv", "modifiedTime": old}]
    )
    outcome = sync_drive(
        "folder-1",
        tmp_path / "out",
        service=drive,
        quiet_seconds=60,
        now=moment,
        download=_download,
    )
    assert outcome.status == "ready"
    assert outcome.bronze_rows == 1
    assert outcome.moved == ["file-1"]
    assert outcome.destination == "processed/2026-10-19T040122Z"
    assert run_folder_name(moment) == "2026-10-19T040122Z"
    assert [item["name"] for item in drive.created] == ["processed", "2026-10-19T040122Z"]
    assert drive.created[1]["parents"] == ["id-processed"]
    assert drive.moved == [("file-1", "id-2026-10-19T040122Z", "folder-1")]
    assert (tmp_path / "out" / "reservations" / "_staging.csv").is_file()


def test_unrecognized_and_failed_streams_stay_in_the_folder(tmp_path: Path) -> None:
    moment = datetime(2026, 10, 19, 4, 1, 22, tzinfo=timezone.utc)
    old = (moment - timedelta(minutes=5)).isoformat()
    drive = FakeDrive(
        [
            {"id": "file-1", "name": "Reservations.csv", "mimeType": "text/csv", "modifiedTime": old},
            {"id": "file-2", "name": "notes.csv", "mimeType": "text/csv", "modifiedTime": old},
        ]
    )

    def download(_service: FakeDrive, file_id: str, dest: Path) -> None:
        dest.write_bytes(_csv() if file_id == "file-1" else b'"Something","Else"\n"1","2"\n')

    outcome = fetch_drive("folder-1", tmp_path / "out", service=drive, now=moment, download=download)
    assert outcome.sources == ["file-1"]
    assert outcome.unrecognized == ["notes.csv"]

    finalize_drive(outcome, service=drive, streams=set())
    assert drive.moved == []
    finalize_drive(outcome, service=drive, streams={"reservations"})
    assert drive.moved == [("file-1", "id-2026-10-19T040122Z", "folder-1")]


def test_fetch_leaves_drive_alone_until_finalize(tmp_path: Path) -> None:
    moment = datetime(2026, 10, 19, 4, 1, 22, tzinfo=timezone.utc)
    old = (moment - timedelta(minutes=5)).isoformat()
    drive = FakeDrive(
        [{"id": "file-1", "name": "Reservations.csv", "mimeType": "text/csv", "modifiedTime": old}]
    )
    outcome = fetch_drive("folder-1", tmp_path / "out", service=drive, now=moment, download=_download)
    assert outcome.status == "ready"
    assert outcome.sources == ["file-1"]
    assert drive.created == []
    assert drive.moved == []

    finalize_drive(outcome, service=drive)
    assert drive.moved == [("file-1", "id-2026-10-19T040122Z", "folder-1")]


def test_sync_waits_when_a_file_is_still_changing(tmp_path: Path) -> None:
    fresh = datetime.now(timezone.utc).isoformat()
    drive = FakeDrive(
        [{"id": "file-1", "name": "Reservations.csv", "mimeType": "text/csv", "modifiedTime": fresh}]
    )
    outcome = sync_drive(
        "folder-1",
        tmp_path / "out",
        service=drive,
        quiet_seconds=60,
        download=_download,
    )
    assert outcome.status == "waiting"
    assert outcome.moved == []
    assert drive.created == []
