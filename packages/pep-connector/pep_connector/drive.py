"""Read a Drive folder the connection already points at.

The folder id is the whole mapping. Listing uses that id, not the folder's
name. Files stay in the folder until the warehouse is updated, then they move
into `processed/<timestamp>`. Healed rows live in BigQuery, not Drive.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from pep_connector.prepare import FileSummary, PreparedRun, prepare_run

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
# The Cloud Run job impersonates this account. The folder is shared with it.
# Drive calls bill the account's own project, where the Drive API is enabled.
IMPERSONATE = "aria-pep-drive@gn-shared-services-production.iam.gserviceaccount.com"
PROCESSED_NAME = "processed"
_FOLDER = "application/vnd.google-apps.folder"


@dataclass
class SyncOutcome:
    status: str
    files: list[FileSummary] = field(default_factory=list)
    bronze_rows: int = 0
    moved: list[str] = field(default_factory=list)
    destination: str = ""
    folder_id: str = ""
    sources: list[str] = field(default_factory=list)
    moment: datetime | None = None
    prepared: PreparedRun | None = None
    source_streams: dict[str, str] = field(default_factory=dict)
    unrecognized: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def drive_impersonate() -> str:
    return os.environ.get("PEP_DRIVE_IMPERSONATE", IMPERSONATE)


def build_service() -> Any:
    """Drive calls run as the pep-drive service account.

    Local gcloud login and the Cloud Run job both hold cloud-platform, which
    can mint a token for that account. Neither identity asks a user for the
    Drive scope. The folder must be shared with the service account.
    """
    from google.auth import default, impersonated_credentials
    from google.auth.exceptions import DefaultCredentialsError
    from googleapiclient.discovery import build

    target = drive_impersonate()
    try:
        # No forced quota project: billing the token exchange to gn-shared would
        # need serviceusage.services.use there for the Cloud Run job account.
        source, _ = default(scopes=[CLOUD_SCOPE])
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "No Google credentials. Application-default login with cloud-platform "
            f"can impersonate {target}."
        ) from exc
    creds = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=target,
        target_scopes=[DRIVE_SCOPE],
        lifetime=3600,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def require_folder(service: Any, folder_id: str) -> None:
    """Fail with a share instruction when the service account cannot see the folder.

    A files.list of an unshared folder returns no rows. files.get returns 404.
    """
    from googleapiclient.errors import HttpError

    try:
        service.files().get(fileId=folder_id, supportsAllDrives=True, fields="id").execute()
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 404:
            raise RuntimeError(
                f"Drive folder {folder_id} is not shared with {drive_impersonate()}. "
                "Share it with that account as Content manager."
            ) from exc
        raise


def _list(service: Any, query: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageSize=100,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        token = response.get("nextPageToken")
        if not token:
            return files


def list_children(service: Any, folder_id: str) -> list[dict[str, Any]]:
    return _list(service, f"'{folder_id}' in parents and trashed = false")


def list_csvs(service: Any, folder_id: str) -> list[dict[str, Any]]:
    children = list_children(service, folder_id)
    return [item for item in children if item.get("name", "").lower().endswith(".csv")]


def _modified(item: dict[str, Any]) -> datetime:
    raw = str(item.get("modifiedTime") or "")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def download_file(service: Any, file_id: str, dest: Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload

    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with dest.open("wb") as handle:
        loader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = loader.next_chunk()


def run_folder_name(moment: datetime) -> str:
    """UTC name that sorts in run order. `processed/2026-10-19T040122Z`."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _unique_name(service: Any, parent_id: str, name: str) -> str:
    taken = {
        item.get("name")
        for item in list_children(service, parent_id)
        if item.get("mimeType") == _FOLDER
    }
    if name not in taken:
        return name
    suffix = 2
    while f"{name}-{suffix}" in taken:
        suffix += 1
    return f"{name}-{suffix}"


def _folder(service: Any, parent_id: str, name: str, *, reuse: bool) -> str:
    if reuse:
        existing = [
            item
            for item in list_children(service, parent_id)
            if item.get("mimeType") == _FOLDER and item.get("name") == name
        ]
        if existing:
            return str(existing[0]["id"])
    created = (
        service.files()
        .create(
            body={"name": name, "mimeType": _FOLDER, "parents": [parent_id]},
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    return str(created["id"])


def _move(service: Any, file_id: str, folder_id: str, processed_id: str) -> None:
    service.files().update(
        fileId=file_id,
        addParents=processed_id,
        removeParents=folder_id,
        supportsAllDrives=True,
        fields="id, parents",
    ).execute()


def _safe_name(name: str, file_id: str) -> str:
    base = Path(name).name
    if not base or base in {".", ".."}:
        base = f"{file_id}.csv"
    return f"{file_id}-{base}"


def parse_folder_id(value: str) -> str:
    """Accept a Drive folder id or the folder URL from the browser."""
    text = value.strip()
    marker = "/folders/"
    if marker in text:
        text = text.split(marker, 1)[1]
        text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return text


def fetch_drive(
    folder_id: str,
    output_dir: Path,
    *,
    service: Any = None,
    quiet_seconds: int = 60,
    now: datetime | None = None,
    download: Callable[[Any, str, Path], None] = download_file,
) -> SyncOutcome:
    """Download quiet CSVs and heal them. Drive is not changed."""
    folder_id = parse_folder_id(folder_id)
    if not folder_id:
        raise ValueError("drive_folder_id is required")
    client = service if service is not None else build_service()
    require_folder(client, folder_id)
    files = list_csvs(client, folder_id)
    if not files:
        return SyncOutcome(status="empty", folder_id=folder_id)

    moment = now or datetime.now(timezone.utc)
    quiet_after = moment - timedelta(seconds=quiet_seconds)
    if any(_modified(item) > quiet_after for item in files):
        return SyncOutcome(status="waiting", folder_id=folder_id)

    inbox = output_dir / "_inbox"
    if inbox.exists():
        shutil.rmtree(inbox)
    inbox.mkdir(parents=True)
    local_names = {item["id"]: _safe_name(str(item["name"]), str(item["id"])) for item in files}
    for item in files:
        download(client, str(item["id"]), inbox / local_names[item["id"]])

    prepared = prepare_run(inbox, output_dir)
    by_local = {local: file_id for file_id, local in local_names.items()}
    names = {str(item["id"]): str(item["name"]) for item in files}
    source_streams = {
        by_local[item.source]: item.stream for item in prepared.files if item.source in by_local
    }
    return SyncOutcome(
        status="ready" if prepared.batches else "empty",
        files=prepared.files,
        bronze_rows=prepared.rows,
        folder_id=folder_id,
        sources=list(source_streams),
        moment=moment,
        prepared=prepared,
        source_streams=source_streams,
        unrecognized=[names[by_local[local]] for local in prepared.unrecognized],
        failed={names[by_local[local]]: error for local, error in prepared.failed.items()},
    )


def finalize_drive(
    outcome: SyncOutcome,
    *,
    service: Any = None,
    streams: set[str] | None = None,
) -> SyncOutcome:
    """After the warehouse is updated, the originals go to processed/<UTC time>.

    Only files of `streams` move (all healed files when None). Unrecognized and
    failed files stay in the folder. Nothing is uploaded: service accounts have
    no My Drive storage quota.
    """
    if outcome.status != "ready" or outcome.moment is None:
        return outcome
    moving = [
        file_id
        for file_id in outcome.sources
        if streams is None or outcome.source_streams.get(file_id) in streams
    ]
    if not moving:
        return outcome
    client = service if service is not None else build_service()
    processed_id = _folder(client, outcome.folder_id, PROCESSED_NAME, reuse=True)
    destination = _unique_name(client, processed_id, run_folder_name(outcome.moment))
    run_folder = _folder(client, processed_id, destination, reuse=False)
    for file_id in moving:
        _move(client, file_id, outcome.folder_id, run_folder)
        outcome.moved.append(file_id)
    outcome.destination = f"{PROCESSED_NAME}/{destination}"
    return outcome


def sync_drive(
    folder_id: str,
    output_dir: Path,
    *,
    service: Any = None,
    quiet_seconds: int = 60,
    now: datetime | None = None,
    download: Callable[[Any, str, Path], None] = download_file,
) -> SyncOutcome:
    """Heal and file away in one step. The runner calls fetch and finalize around the load."""
    client = service if service is not None else build_service()
    outcome = fetch_drive(
        folder_id,
        output_dir,
        service=client,
        quiet_seconds=quiet_seconds,
        now=now,
        download=download,
    )
    return finalize_drive(outcome, service=client)
