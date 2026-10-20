"""Local prepare: `python -m pep_connector prepare --input <dir> --out <dir>`."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from pep_connector.drive import build_service, list_children, parse_folder_id, require_folder, sync_drive
from pep_connector.prepare import prepare_run


def _print_prepare(
    summaries: list,
    rows: int,
    status: str = "ready",
    moved: list[str] | None = None,
    unrecognized: list[str] | None = None,
    failed: dict[str, str] | None = None,
) -> None:
    print(
        json.dumps(
            {
                "status": status,
                "files": [asdict(item) for item in summaries],
                "rows": rows,
                "moved": moved or [],
                "unrecognized": unrecognized or [],
                "failed": failed or {},
            },
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pep_connector")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Heal a local folder of PEP CSV exports")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)

    listing = sub.add_parser("drive-ls", help="List a Drive folder by id")
    listing.add_argument("--folder-id", required=True)

    sync = sub.add_parser("sync", help="Heal the CSVs in a Drive folder and move them to processed")
    sync.add_argument("--folder-id", required=True)
    sync.add_argument("--out", type=Path, required=True)
    sync.add_argument("--quiet-seconds", type=int, default=60)

    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepared = prepare_run(args.input, args.out)
        _print_prepare(prepared.files, prepared.rows, unrecognized=prepared.unrecognized, failed=prepared.failed)
        return 1 if prepared.failed else 0
    if args.command == "drive-ls":
        service = build_service()
        folder_id = parse_folder_id(args.folder_id)
        require_folder(service, folder_id)
        children = list_children(service, folder_id)
        print(
            json.dumps(
                [{"id": item.get("id"), "name": item.get("name"), "mimeType": item.get("mimeType")} for item in children],
                indent=2,
            )
        )
        return 0
    outcome = sync_drive(args.folder_id, args.out, quiet_seconds=args.quiet_seconds)
    _print_prepare(outcome.files, outcome.bronze_rows, outcome.status, outcome.moved, outcome.unrecognized, outcome.failed)
    return 0 if outcome.status in {"ready", "empty", "waiting"} else 1


if __name__ == "__main__":
    sys.exit(main())
