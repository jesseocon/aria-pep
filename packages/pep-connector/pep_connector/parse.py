"""Heal a PEP reservation export.

One download repeats the header several times; only the first section is the
reservation list. Its rows are rebuilt by ``assemble`` (unescaped quotes, line breaks
and split fields in text). Rows that cannot be aligned, or that have no external
confirmation number, are quarantined; every row is counted either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from pep_connector.assemble import assemble
from pep_connector.schema import (
    HEADERS,
    RESERVATION_LAYOUTS,
    SECTION_HEADER_PREFIX,
    V2_COLUMN_COUNT,
    normalize_to_v2,
    validate_display_headers,
)


@dataclass(frozen=True)
class Record:
    fields: dict[str, str]
    source_line: int
    parse_status: str
    heal_action: str


@dataclass(frozen=True)
class HealResult:
    source_file: str
    section_header_count: int
    truncated_to_first_section: bool
    records: list[Record]

    @property
    def kept(self) -> list[Record]:
        return [record for record in self.records if record.parse_status in ("ok", "healed")]


def parse_csv_records(text: str) -> list[list[str]]:
    records: list[list[str]] = []
    row: list[str] = []
    field: list[str] = []
    in_quotes = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        nxt = text[index + 1] if index + 1 < length else ""
        if in_quotes:
            if char == '"' and nxt == '"':
                field.append('"')
                index += 2
                continue
            if char == '"':
                in_quotes = False
            else:
                field.append(char)
            index += 1
            continue
        if char == '"':
            in_quotes = True
        elif char == ",":
            row.append("".join(field))
            field = []
        elif char == "\n":
            row.append("".join(field))
            field = []
            if any(row):
                records.append(row)
            row = []
        elif char != "\r":
            field.append(char)
        index += 1
    if field or row:
        row.append("".join(field))
        if any(row):
            records.append(row)
    return records


def first_section(text: str) -> tuple[str, int, bool]:
    lines = text.splitlines()
    header_at = [i for i, line in enumerate(lines) if line.startswith(SECTION_HEADER_PREFIX)]
    if len(header_at) <= 1:
        return text, len(header_at), False
    kept = lines[: header_at[1]]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept), len(header_at), True


def _strip(value: str) -> str:
    return value.strip().strip('"')


def _fit(values: list[str], width: int) -> list[str]:
    return [*values[:width], *[""] * (width - len(values))]


def heal_text(text: str, source_file: str) -> HealResult:
    section, header_count, truncated = first_section(text)
    lines = section.splitlines()
    if not lines:
        raise ValueError(f"{source_file}: missing CSV header row")
    header_records = parse_csv_records(lines[0])
    if not header_records:
        raise ValueError(f"{source_file}: missing CSV header row")
    version = validate_display_headers(header_records[0])

    records: list[Record] = []
    for row in assemble(section, RESERVATION_LAYOUTS[version]):
        actions = list(row.actions)
        if row.problem is None and not row.summary and version == 1:
            fields = normalize_to_v2(row.values)
            actions.append("normalized_v1")
        else:
            fields = _fit(row.values, V2_COLUMN_COUNT)
        if row.summary:
            status = "removed_summary_row"
        elif row.problem is not None:
            status = "quarantined"
            actions.append(row.problem)
        elif not _strip(fields[5]):
            status = "quarantined"
            actions.append("missing_external_confirmation_number")
        else:
            status = "healed" if actions else "ok"
        records.append(
            Record(
                fields=dict(zip(HEADERS, fields, strict=True)),
                source_line=row.line,
                parse_status=status,
                heal_action="|".join(actions),
            )
        )
    return HealResult(source_file, header_count, truncated, records)
