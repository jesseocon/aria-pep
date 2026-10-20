"""What the runner renders for a PEP connection. No browser login."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

KEY = "pep"
JOB_NAME = "aria-connector-pep"

DATE = {"type": "string", "format": "date", "pattern": r"^\d{4}-\d{2}-\d{2}$"}

CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "PEP property",
    "additionalProperties": False,
    "required": [
        "org_id",
        "development_property_id",
        "production_property_id",
        "drive_folder_id",
    ],
    "properties": {
        "org_id": {
            "type": "string",
            "title": "Organization id",
            "pattern": r"^\d+$",
        },
        "development_property_id": {"type": "string", "title": "Aria property id (development)"},
        "production_property_id": {"type": "string", "title": "Aria property id (production)"},
        "drive_folder_id": {
            "type": "string",
            "title": "Google Drive folder",
            "description": "Drive id of the reservations folder for this property. The folder name is not read.",
        },
        "environments": {
            "type": "array",
            "title": "Warehouses",
            "items": {"enum": ["development", "production"]},
            "minItems": 1,
            "uniqueItems": True,
            "default": ["development", "production"],
        },
    },
}

RUN_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "environment": {"enum": ["development", "production"], "title": "Only this warehouse"},
        "input_dir": {
            "type": "string",
            "title": "Local folder of CSV drops",
            "description": "Set for a local run. A scheduled run reads drive_folder_id instead.",
        },
        "transform_only": {"type": "boolean", "title": "Run dbt only", "default": False},
    },
}


def _version() -> str:
    try:
        return version("pep-connector")
    except PackageNotFoundError:
        return "0.0.0"


def manifest() -> dict[str, Any]:
    return {
        "key": KEY,
        "display_name": "PEP",
        "version": _version(),
        "description": "Hilton PEP reservation files to PMS stay nights and reservation-night OTB.",
        "job": {"name": JOB_NAME, "timeout_seconds": 60 * 60},
        "config_schema": CONFIG_SCHEMA,
        "run_params_schema": RUN_PARAMS_SCHEMA,
    }
