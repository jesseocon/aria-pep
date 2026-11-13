"""PEP report packages emailed to the connection's inbox, in place of the Drive folder.

Hilton's PEP report scheduler mails a package (a zip of CSV exports) to the connection's
address, files-{inbox key}@aria-ingest.com (the API shows it as the connection's
inbox_address; PEP never delivers to the older files+{inbox key}@reports.aria-ingest.com form). The runner keeps every email as a raw .eml (ctx.inbox); a run reads the
ones after its bookmark, saves their CSVs (zips unpacked) and heals them exactly as the
Drive flow does, so bronze, silver and gold are the same tables.

Each saved file is named `<received UTC>_<n>_<attachment name>`. Names sort by arrival, so
between two emails of one run the later one supplies a reservation or a day, as a later
Drive file does.

Every email in the inbox is read, whoever sent it (PEP itself, a relay, a Gmail auto-forward):
the address's inbox key keeps other mail out. A package proves itself as it heals.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aria_runner import mailbox

from pep_connector.final_audit import xlsx_to_csv
from pep_connector.prepare import RESERVATIONS, PreparedRun, prepare_run
from pep_connector.reports import OCCUPANCY_FORECAST, RATE_PLAN_SUMMARY

LOCAL_PART = "files"
# What Scenic's package holds (Embassy Suites Dallas Love Field, 2026-11-03). Occupancy
# Summary and Transactions load too when they are mailed.
EXPECTED_REPORTS = [RESERVATIONS, RATE_PLAN_SUMMARY.name, OCCUPANCY_FORECAST.name]
DEFAULT_ALERT_TIMEZONE = "America/Chicago"
# Emails read in one run; the next run continues from the bookmark.
MAX_MESSAGES = 500
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class IgnoredEmail:
    name: str
    sender: str
    subject: str
    reason: str


@dataclass
class SkippedAttachment:
    """An attachment that looked like a report but could not be read: the run raises an alert for it."""

    email: str
    sender: str
    filename: str
    reason: str


# Attachments that are never reports (logos and calendar invites in signatures): skipped without an alert.
_NOT_REPORTS = re.compile(r"\.(png|jpe?g|gif|bmp|svg|webp|ics|vcf|p7s|eml)$", re.IGNORECASE)


@dataclass
class InboxOutcome:
    status: str
    cursor: mailbox.Cursor
    prepared: PreparedRun | None = None
    messages: int = 0
    repeats: int = 0
    files: dict[str, str] = field(default_factory=dict)  # saved name -> email object
    received: dict[str, datetime] = field(default_factory=dict)  # saved name -> arrival
    ignored: list[IgnoredEmail] = field(default_factory=list)
    skipped: list[SkippedAttachment] = field(default_factory=list)
    more: bool = False

    @property
    def unrecognized(self) -> list[str]:
        return self.prepared.unrecognized if self.prepared else []

    @property
    def failed(self) -> dict[str, str]:
        return self.prepared.failed if self.prepared else {}


def saved_name(received: datetime, index: int, filename: str) -> str:
    """`20261103T234818Z_1_reservations-today-plus-90.csv`: arrival order first, PEP's name after."""
    base = _UNSAFE.sub("_", filename.replace("/", "_")).strip("._") or "report.csv"
    return f"{received.astimezone(ZoneInfo('UTC')):%Y%m%dT%H%M%SZ}_{index}_{base}"


def _reports(attachments: list[mailbox.Attachment]) -> list[tuple[str, bytes]]:
    """The CSV exports, plus each Final Audit workbook turned into CSV; other files are skipped."""
    return _sort_attachments(attachments)[0]


def _sort_attachments(attachments: list[mailbox.Attachment]) -> tuple[list[tuple[str, bytes]], list[tuple[str, str]]]:
    """(reports, skipped): the CSV exports and Final Audit workbooks (either PEP layout) as CSV, and each other
    attachment that could have been a report with why it was skipped. Logos and invites are left out of both."""
    out: list[tuple[str, bytes]] = []
    skipped: list[tuple[str, str]] = []
    for item in attachments:
        name = item.filename.lower()
        if name.endswith(".csv"):
            out.append((item.filename, item.data))
        elif name.endswith(".xlsx"):
            text = xlsx_to_csv(item.data)
            if text is not None:
                out.append((item.filename.rsplit(".", 1)[0] + ".csv", text.encode()))
            else:
                skipped.append((item.filename, "a workbook that is not a Final Audit (send PEP's reports as CSV)"))
        elif not _NOT_REPORTS.search(name):
            skipped.append((item.filename, "not a CSV or Excel report"))
    return out, skipped


def fetch_inbox(
    inbox: mailbox.Mailbox,
    cursor: mailbox.Cursor,
    output_dir: Path,
    *,
    limit: int = MAX_MESSAGES,
) -> InboxOutcome:
    """Save the CSV exports of every new email and heal them. The inbox is not changed;
    `outcome.cursor` is where the next run starts once this one's rows are loaded."""
    after = mailbox.Cursor(cursor.last_object, list(cursor.seen))
    listed = inbox.messages(after=cursor.last_object, limit=limit + 1)
    outcome = InboxOutcome(status="empty", cursor=after, more=len(listed) > limit)
    folder = output_dir / "_inbox"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    for message in listed[:limit]:
        outcome.messages += 1
        if after.is_repeat(message):
            outcome.repeats += 1
            after.advance(message)
            continue
        email = mailbox.parse_email(inbox.read(message))
        reports, skipped = _sort_attachments(mailbox.expand_archives(email.attachments))
        for filename, reason in skipped:
            outcome.skipped.append(SkippedAttachment(message.name, email.sender or message.envelope_from, filename, reason))
        if not reports:
            outcome.ignored.append(IgnoredEmail(message.name, email.sender or message.envelope_from, email.subject, "no_csv_attachment"))
        for index, (filename, data) in enumerate(reports, start=1):
            name = saved_name(message.received_at, index, filename)
            (folder / name).write_bytes(data)
            outcome.files[name] = message.name
            outcome.received[name] = message.received_at
        after.advance(message)

    if outcome.files:
        outcome.prepared = prepare_run(folder, output_dir / "healed")
        outcome.status = "ready" if outcome.prepared.batches else "empty"
    return outcome


def latest_by_stream(outcome: InboxOutcome) -> dict[str, datetime]:
    """When each report last arrived, from the files that healed."""
    latest: dict[str, datetime] = {}
    if outcome.prepared is None:
        return latest
    for item in outcome.prepared.files:
        moment = outcome.received.get(item.source)
        if moment is not None and (item.stream not in latest or moment > latest[item.stream]):
            latest[item.stream] = moment
    return latest
