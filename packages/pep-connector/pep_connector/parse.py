"""Heal a PEP reservation export.

Remark fields contain raw newlines, and one download repeats the header several
times. Only the first section is the reservation list. Rows that cannot be
aligned, or that have no external confirmation number, are quarantined.
"""

from __future__ import annotations

from dataclasses import dataclass

from pep_connector.schema import (
    CONFIRMATION,
    HEADERS,
    ROW_START,
    SECTION_HEADER_PREFIX,
    STATUSES,
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
        return [record for record in self.records if record.parse_status != "quarantined"]


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


def _looks_like_guest(value: str) -> bool:
    trimmed = _strip(value)
    return "," in trimmed and trimmed not in STATUSES


def _fit_width(fields: list[str]) -> tuple[list[str], str]:
    canonical = normalize_to_v2(fields)
    if len(canonical) > V2_COLUMN_COUNT:
        head = canonical[: V2_COLUMN_COUNT - 1]
        head.append(",".join(canonical[V2_COLUMN_COUNT - 1 :]))
        return head, "merged_overflow"
    if len(canonical) < V2_COLUMN_COUNT:
        return [*canonical, *[""] * (V2_COLUMN_COUNT - len(canonical))], "padded"
    action = "normalized_v1" if len(canonical) != len(fields) else ""
    return canonical, action


def _valid(fields: list[str]) -> bool:
    if len(fields) != V2_COLUMN_COUNT or not CONFIRMATION.match(_strip(fields[2])):
        return False
    status = _strip(fields[9])
    if status in STATUSES:
        return True
    if status == "" and _looks_like_guest(fields[10]):
        return True
    return _looks_like_guest(status) and _strip(fields[10]) == ""


def heal_text(text: str, source_file: str) -> HealResult:
    section, header_count, truncated = first_section(text)
    lines = section.splitlines()
    if not lines:
        raise ValueError(f"{source_file}: missing CSV header row")
    header_records = parse_csv_records(lines[0])
    if not header_records:
        raise ValueError(f"{source_file}: missing CSV header row")
    validate_display_headers(header_records[0])

    chunks: list[tuple[str, int, int]] = []
    current: list[str] = []
    source_line = 0
    for index, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        if ROW_START.match(line):
            if current:
                chunks.append(("\n".join(current), source_line, len(current)))
            current = [line]
            source_line = index
            continue
        if not current:
            current = [line]
            source_line = index
        else:
            current.append(line)
    if current:
        chunks.append(("\n".join(current), source_line, len(current)))

    records: list[Record] = []
    for chunk, line_no, line_count in chunks:
        parsed = parse_csv_records(chunk)
        raw = parsed[0] if parsed else [""] * V2_COLUMN_COUNT
        fields, action = _fit_width(raw)
        actions: list[str] = []
        if line_count > 1:
            actions.append("merged_continuation")
        if action:
            actions.append(action)
        if not _valid(fields):
            status = "quarantined"
        elif not _strip(fields[5]):
            status = "quarantined"
            actions.append("missing_external_confirmation_number")
        elif actions:
            status = "healed"
        else:
            status = "ok"
        records.append(
            Record(
                fields=dict(zip(HEADERS, fields, strict=True)),
                source_line=line_no,
                parse_status=status,
                heal_action="|".join(actions),
            )
        )
    return HealResult(source_file, header_count, truncated, records)
