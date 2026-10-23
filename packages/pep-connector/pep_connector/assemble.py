"""Rebuild the rows of a PEP export section, one record per row, without losing any.

PEP quotes every field but does not escape quotes inside text (``ask for "John"``),
some text holds line breaks, and some holds ``",`` that splits a field in two. Rows
are rebuilt from what PEP's columns are, never from what one property's values look
like:

1. Tokenize leniently: a quote closes a field only when a comma, a line end or the
   end of the text follows it. A stray quote inside text stays text.
2. A record whose leading columns have the layout's row-start types (an anchor)
   begins a row. Records that are not anchors are fragments of the row above. The
   anchor and its fragments are parsed again as one span, line breaks kept as text.
   An anchor is never joined to another row.
3. A row wider than the header has a field split inside text. The extra fields are
   merged back into the first text column where every typed column (dates, times,
   money, counts) then has the right shape; the merged value is cut from the raw
   text, so the separator is restored exactly. A narrower row is padded at the end
   only if its typed columns then hold. Otherwise the row is quarantined.

Every anchor yields exactly one row. A full-width record that is not an anchor is a
totals line (row-start columns blank, flagged ``summary``) or a quarantined stray, and
fragments before the first anchor are quarantined, so nothing is dropped uncounted.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Check = Callable[[str], bool]


def _pattern(regex: str, *, optional: bool) -> Check:
    compiled = re.compile(regex)

    def check(value: str) -> bool:
        value = value.strip()
        return (optional and value == "") or compiled.match(value) is not None

    return check


# Formats PEP generates itself; they do not vary by property.
DATE = r"^[A-Za-z]{3}\s+\d{1,2},\s+\d{4}$"
TIME = r"^\d{1,2}:\d{2}(:\d{2})?\s*[AaPp][Mm]$"
MONEY = r"^-?\(?-?\$?\d[\d,]*(\.\d+)?\)?%?$"
COUNT = r"^-?\d[\d,]*(\.\d+)?$"
CONFIRMATION = r"^\d{8,12}$"
CODE = r"^[A-Za-z0-9*&_-]{1,10}$"


def required(regex: str) -> Check:
    return _pattern(regex, optional=False)


def optional(regex: str) -> Check:
    return _pattern(regex, optional=True)


@dataclass(frozen=True)
class Layout:
    """One export layout: its display headers and the checks on its typed columns.

    ``types`` maps a display header (case-insensitive) to its check. Columns without a
    check are text. ``anchor_width`` leading columns must all pass for a record to
    start a row; each of them needs a check.
    """

    headers: Sequence[str]
    types: dict[str, Check]
    anchor_width: int

    def __post_init__(self) -> None:
        checks = [self.types.get(header.strip().lower()) for header in self.headers]
        object.__setattr__(self, "_checks", checks)
        if any(check is None for check in checks[: self.anchor_width]):
            raise ValueError("every anchor column needs a type check")

    @property
    def width(self) -> int:
        return len(self.headers)

    @property
    def checks(self) -> list[Check | None]:
        return self._checks  # type: ignore[attr-defined]

    def is_anchor(self, values: Sequence[str]) -> bool:
        if len(values) < self.anchor_width:
            return False
        return all(check(value) for check, value in zip(self.checks, values[: self.anchor_width]))  # type: ignore[misc]

    def typed_ok(self, values: Sequence[str]) -> bool:
        return len(values) == self.width and all(
            check is None or check(value) for check, value in zip(self.checks, values)
        )


@dataclass(frozen=True)
class Field:
    value: str
    start: int  # raw offsets of the content, quotes excluded
    end: int


@dataclass(frozen=True)
class RawRecord:
    fields: list[Field]
    start: int  # raw offset where the record starts
    end: int


@dataclass(frozen=True)
class Row:
    values: list[str]
    line: int
    actions: tuple[str, ...]
    problem: str | None  # set when the row could not be aligned
    summary: bool = False  # a totals line: full width, every row-start column blank


def tokenize(text: str, start: int = 0, end: int | None = None, *, newline_ends: bool = True) -> list[RawRecord]:
    """Lenient CSV: a quote closes a field only before a comma, a line end or the end."""
    end = len(text) if end is None else end
    records: list[RawRecord] = []
    fields: list[Field] = []
    pos = record_start = start

    def closes(at: int) -> bool:
        nxt = text[at + 1] if at + 1 < end else ""
        return nxt in ("", ",") or (newline_ends and nxt in ("\n", "\r"))

    while pos < end:
        if text[pos] == '"':
            content_start = pos = pos + 1
            parts: list[str] = []
            while pos < end:
                if text[pos] == '"':
                    if pos + 1 < end and text[pos + 1] == '"' and not closes(pos + 1):
                        parts.append('"')  # escaped quote
                        pos += 2
                        continue
                    if closes(pos):
                        break
                parts.append(text[pos])
                pos += 1
            fields.append(Field("".join(parts), content_start, pos))
            pos += 1  # past the closing quote
        else:
            # PEP quotes every field, so an unquoted one is the tail of a field split by
            # ``",`` in its text; a quote at its end is that field's closing quote.
            content_start = pos
            while pos < end and text[pos] != "," and not (newline_ends and text[pos] in "\r\n"):
                pos += 1
            content_end = pos - 1 if pos > content_start and text[pos - 1] == '"' else pos
            fields.append(Field(text[content_start:content_end], content_start, content_end))
        if pos < end and text[pos] == ",":
            pos += 1
            if pos >= end:
                fields.append(Field("", pos, pos))
            continue
        # a line end or the end of the text completes the record
        if any(field.value.strip() for field in fields):
            records.append(RawRecord(fields, record_start, pos))
        fields = []
        while pos < end and text[pos] in "\r\n":
            pos += 1
        record_start = pos
    if any(field.value.strip() for field in fields):
        records.append(RawRecord(fields, record_start, pos))
    return records


def _merge(text: str, fields: list[Field], at: int, extra: int) -> list[str]:
    first, last = fields[at], fields[at + extra]
    merged = text[first.start : last.end].replace('""', '"')
    return [f.value for f in fields[:at]] + [merged] + [f.value for f in fields[at + extra + 1 :]]


def align(text: str, fields: list[Field], layout: Layout) -> tuple[list[str], str | None, str | None]:
    """Fit a row to the layout width. Returns (values, action, problem)."""
    values = [field.value for field in fields]
    if len(fields) == layout.width:
        return values, None, None if layout.typed_ok(values) else "typed column out of shape"
    if len(fields) < layout.width:
        padded = values + [""] * (layout.width - len(fields))
        if layout.typed_ok(padded):
            return padded, "padded", None
        return values, None, f"{len(fields)} fields, expected {layout.width}"
    extra = len(fields) - layout.width
    for at, check in enumerate(layout.checks):
        if check is not None:
            continue  # only text columns can hold a split
        merged = _merge(text, fields, at, extra)
        if layout.typed_ok(merged):
            return merged, "merged_split_field", None
    return values, None, f"{len(fields)} fields, expected {layout.width}, no text column fits"


def assemble(text: str, layout: Layout) -> list[Row]:
    """Rows of a section whose first record is its header (validated by the caller)."""
    breaks = [index for index, char in enumerate(text) if char == "\n"]

    def line_of(offset: int) -> int:
        return bisect_right(breaks, offset - 1) + 1

    groups: list[list[RawRecord]] = []
    summaries: list[RawRecord] = []
    strays: list[tuple[RawRecord, str, str]] = []
    for record in tokenize(text)[1:]:
        if layout.is_anchor([field.value for field in record.fields]):
            groups.append([record])
        elif len(record.fields) >= layout.width:
            # A whole row on its own that does not start like one is never glued onto
            # the row above: a totals line (every row-start column blank) or a stray.
            if all(not field.value.strip() for field in record.fields[: layout.anchor_width]):
                summaries.append(record)
            else:
                strays.append((record, "not_a_row", "full-width record without a row start"))
        elif groups:
            groups[-1].append(record)
        else:
            strays.append((record, "orphan_fragment", "fragment before any row"))

    rows = [
        Row([field.value for field in record.fields], line_of(record.start), (action,), problem)
        for record, action, problem in strays
    ]
    rows += [
        Row([field.value for field in record.fields], line_of(record.start), ("summary_row",), None, summary=True)
        for record in summaries
    ]
    for group in groups:
        head = group[0]
        actions: list[str] = []
        fields = head.fields
        if len(group) > 1:
            actions.append("merged_continuation")
            reparsed = tokenize(text, head.start, group[-1].end, newline_ends=False)
            fields = reparsed[0].fields
        values, action, problem = align(text, fields, layout)
        if action:
            actions.append(action)
        rows.append(Row(values, line_of(head.start), tuple(actions), problem))
    rows.sort(key=lambda row: row.line)
    return rows
