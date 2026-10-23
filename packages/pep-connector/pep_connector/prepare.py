"""Turn a folder of PEP downloads into healed files and one staging file per stream.

The first line of a file says what it is. Files no stream recognizes are left
alone. A file that fails to heal is reported and does not stop the others.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from pep_connector.parse import HealResult, heal_text
from pep_connector.reports import REPORT_STREAMS, ReportStream
from pep_connector.schema import OUTPUT_HEADERS, SECTION_HEADER_PREFIX
from pep_connector.span import output_name, span_dates

RESERVATIONS = "reservations"
STAGING_NAME = "_staging.csv"

# A file loads only when nearly every row came through. If the heal cannot read a
# property's export, the file fails and stays in the folder; it never loads just the
# rows the heal happened to understand.
MAX_QUARANTINED_SHARE = 0.01
QUARANTINE_ALLOWANCE = 5
NOT_COUNTED = frozenset({"removed_summary_row", "out_of_scope"})


@dataclass(frozen=True)
class FileSummary:
    source: str
    output: str
    range_start: str
    range_end: str
    ok: int
    healed: int
    quarantined: int
    sections: int
    stream: str = RESERVATIONS
    removed: int = 0


@dataclass
class StreamBatch:
    stream: str
    files: list[FileSummary]
    staging_csv: Path
    rows: int


@dataclass
class PreparedRun:
    batches: dict[str, StreamBatch] = field(default_factory=dict)
    unrecognized: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def files(self) -> list[FileSummary]:
        return [item for batch in self.batches.values() for item in batch.files]

    @property
    def rows(self) -> int:
        return sum(batch.rows for batch in self.batches.values())

    def stream_of(self, source: str) -> str | None:
        for batch in self.batches.values():
            if any(item.source == source for item in batch.files):
                return batch.stream
        return None


def read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[1:] if text.startswith("\ufeff") else text


def classify(text: str) -> str | None:
    first = text.split("\n", 1)[0]
    if first.startswith(SECTION_HEADER_PREFIX):
        return RESERVATIONS
    for stream in REPORT_STREAMS:
        if first.startswith(stream.header_start):
            return stream.name
    lines = text.splitlines()
    for stream in REPORT_STREAMS:
        if stream.header_anywhere and any(line.startswith(stream.header_start) for line in lines):
            return stream.name
    return None


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _compact(day: str) -> str:
    return date.fromisoformat(day).strftime("%Y%m%d") if day else "empty"


def _unique(base: str, used: dict[str, int]) -> str:
    used[base] = used.get(base, 0) + 1
    return base if used[base] == 1 else base.replace(".csv", f"-{used[base]}.csv")


def _row(result: HealResult, record_fields: dict[str, str], source_line: int, status: str, action: str, start: str, end: str) -> dict[str, str]:
    row = dict(record_fields)
    row.update(
        {
            "source_file": result.source_file,
            "source_line": str(source_line),
            "parse_status": status,
            "heal_action": action,
            "range_start": start,
            "range_end": end,
        }
    )
    return row


class HealedRecord(Protocol):
    source_line: int
    parse_status: str
    heal_action: str


def check_quarantine(name: str, records: Sequence[HealedRecord]) -> None:
    """Raise when more than 1% (and more than a handful) of a file's rows were quarantined."""
    counted = [record for record in records if record.parse_status not in NOT_COUNTED]
    bad = [record for record in counted if record.parse_status == "quarantined"]
    if len(bad) <= max(QUARANTINE_ALLOWANCE, MAX_QUARANTINED_SHARE * len(counted)):
        return
    reasons = Counter(record.heal_action for record in bad).most_common(3)
    lines = [record.source_line for record in bad[:5]]
    raise ValueError(
        f"{name}: {len(bad)} of {len(counted)} rows could not be read (limit 1%), "
        f"first at lines {lines}; reasons: {reasons}"
    )


def prepare_reservations(
    sources: list[tuple[str, str]],
    output_dir: Path,
    staging_name: str = STAGING_NAME,
    failed: dict[str, str] | None = None,
) -> tuple[list[FileSummary], list[dict[str, str]]]:
    """Heal reservation files. One row per external confirmation number; the later range wins."""
    summaries: list[FileSummary] = []
    bronze: dict[str, dict[str, str]] = {}
    used: dict[str, int] = {}
    for name, text in sources:
        try:
            result = heal_text(text, name)
            check_quarantine(name, result.records)
            kept = result.kept
            if not kept:
                raise ValueError(f"{name}: no reservation rows")
            start, end = span_dates(kept)
        except ValueError as exc:
            if failed is None:
                raise
            failed[name] = str(exc)
            continue
        base = _unique(output_name(start, end), used)
        start_iso, end_iso = start.isoformat(), end.isoformat()
        rows = [
            _row(result, record.fields, record.source_line, record.parse_status, record.heal_action, start_iso, end_iso)
            for record in kept
        ]
        _write_csv(output_dir / base, OUTPUT_HEADERS, rows)
        for row in rows:
            key = row["external_confirmation_number"].strip()
            current = bronze.get(key)
            if current is None or (row["range_end"], row["source_file"], row["source_line"]) >= (
                current["range_end"],
                current["source_file"],
                current["source_line"],
            ):
                bronze[key] = row
        summaries.append(
            FileSummary(
                source=name,
                output=base,
                range_start=start_iso,
                range_end=end_iso,
                ok=sum(record.parse_status == "ok" for record in result.records),
                healed=sum(record.parse_status == "healed" for record in result.records),
                quarantined=sum(record.parse_status == "quarantined" for record in result.records),
                sections=result.section_header_count,
                removed=sum(record.parse_status in NOT_COUNTED for record in result.records),
            )
        )
    _write_csv(output_dir / staging_name, OUTPUT_HEADERS, list(bronze.values()))
    return summaries, list(bronze.values())


def prepare_report(
    stream: ReportStream,
    sources: list[tuple[str, str]],
    output_dir: Path,
    failed: dict[str, str] | None = None,
) -> tuple[list[FileSummary], list[dict[str, str]]]:
    """Heal daily report files. For each date, the file whose range ends last supplies the rows."""
    summaries: list[FileSummary] = []
    by_file: dict[str, list[dict[str, str]]] = {}
    ranges: dict[str, tuple[str, str]] = {}
    used: dict[str, int] = {}
    for name, text in sources:
        try:
            heal = stream.heal(text)
            check_quarantine(name, heal.records)
        except ValueError as exc:
            if failed is None:
                raise
            failed[name] = str(exc)
            continue
        kept = [record for record in heal.records if record.parse_status in stream.kept]
        days = sorted(day for day in (stream.row_date(record.fields) for record in kept) if day)
        start, end = (days[0], days[-1]) if days else ("", "")
        rows = []
        for record in kept:
            row = dict(zip(stream.headers, record.fields, strict=True))
            row.update(
                {
                    "block_start_date": start,
                    "block_end_date": end,
                    "source_file": name,
                    "source_line": str(record.source_line),
                    "parse_status": record.parse_status,
                    "heal_action": record.heal_action,
                    "row_date": stream.row_date(record.fields) or "",
                }
            )
            rows.append(row)
        base = _unique(f"{stream.file_prefix}-{_compact(start)}-{_compact(end)}.csv", used)
        _write_csv(output_dir / base, stream.output_headers, rows)
        by_file[name] = rows
        if start:
            ranges[name] = (start, end)
        summaries.append(
            FileSummary(
                source=name,
                output=base,
                range_start=start,
                range_end=end,
                ok=sum(record.parse_status == "ok" for record in heal.records),
                healed=sum(record.parse_status == "healed" for record in heal.records),
                quarantined=sum(record.parse_status == "quarantined" for record in heal.records),
                sections=heal.sections,
                stream=stream.name,
                removed=sum(record.parse_status in NOT_COUNTED for record in heal.records),
            )
        )

    def winner(day: str) -> str:
        covering = [name for name, (start, end) in ranges.items() if start <= day <= end]
        return max(covering, key=lambda name: (ranges[name][1], name))

    staged = [row for name, rows in by_file.items() for row in rows if winner(row["row_date"]) == name]
    _write_csv(output_dir / STAGING_NAME, stream.output_headers, staged)
    return summaries, staged


def prepare_run(input_dir: Path, output_dir: Path) -> PreparedRun:
    run = PreparedRun()
    grouped: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(item for item in input_dir.glob("*.csv") if item.is_file()):
        text = read_text(path)
        stream = classify(text)
        if stream is None:
            run.unrecognized.append(path.name)
        else:
            grouped.setdefault(stream, []).append((path.name, text))

    for name, sources in grouped.items():
        out = output_dir / name
        if name == RESERVATIONS:
            files, rows = prepare_reservations(sources, out, failed=run.failed)
        else:
            stream = next(item for item in REPORT_STREAMS if item.name == name)
            files, rows = prepare_report(stream, sources, out, failed=run.failed)
        if files:
            run.batches[name] = StreamBatch(name, files, out / STAGING_NAME, len(rows))
    return run


def prepare_directory(input_dir: Path, output_dir: Path) -> tuple[list[FileSummary], list[dict[str, str]]]:
    """Reservations only, every CSV in the folder. Writes `bronze.csv`."""
    sources = [(path.name, read_text(path)) for path in sorted(input_dir.glob("*.csv")) if path.is_file()]
    if not sources:
        raise ValueError(f"no csv files in {input_dir}")
    return prepare_reservations(sources, output_dir, staging_name="bronze.csv")
