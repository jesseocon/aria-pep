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
        "progress": "v1",
        "config_schema": CONFIG_SCHEMA,
        "run_params_schema": RUN_PARAMS_SCHEMA,
    }


EMAIL_KEY = "pep_email"
EMAIL_STREAMS = ["reservations", "rate_plan_summary", "occupancy_summary", "occupancy_forecast", "transactions"]

EMAIL_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "PEP property (emailed reports)",
    "additionalProperties": False,
    "required": ["org_id", "development_property_id", "production_property_id"],
    "properties": {
        "org_id": CONFIG_SCHEMA["properties"]["org_id"],
        "development_property_id": CONFIG_SCHEMA["properties"]["development_property_id"],
        "production_property_id": CONFIG_SCHEMA["properties"]["production_property_id"],
        "bronze_connection_id": {
            "type": "string",
            "title": "Takes over from connection",
            "description": "Id of the PEP (Drive) connection this one replaces. Its bronze tables are kept and added to. Empty for a new property.",
        },
        "allowed_senders": {
            "type": "array",
            "title": "Allowed senders",
            "description": "Addresses or @domain, e.g. @hilton.com. Email from anyone else is skipped. Empty takes any sender.",
            "items": {"type": "string"},
            "default": [],
        },
        "expected_reports": {
            "type": "array",
            "title": "Reports expected every day",
            "items": {"enum": EMAIL_STREAMS},
            "uniqueItems": True,
            "default": ["reservations", "rate_plan_summary", "occupancy_forecast"],
        },
        "alert_at": {
            "type": "string",
            "title": "Alert when missing by",
            "description": "HH:MM. The first run after this time fails, naming each expected report that has not arrived in the 24 hours before it. Empty (the default) turns the check off.",
            "pattern": r"^$|^([01]\d|2[0-3]):[0-5]\d$",
            "default": "",
        },
        "alert_timezone": {
            "type": "string",
            "title": "Alert time zone",
            "default": "America/Chicago",
        },
        "environments": CONFIG_SCHEMA["properties"]["environments"],
    },
}

EMAIL_RUN_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "environment": {"enum": ["development", "production"], "title": "Only this warehouse"},
        "reprocess_from": {
            "type": "string",
            "format": "date-time",
            "title": "Re-read stored emails from",
            "description": "Read every email received from this time again (after fixing a file that failed).",
        },
        "transform_only": {"type": "boolean", "title": "Run dbt only", "default": False},
    },
}


def email_manifest() -> dict[str, Any]:
    return {
        "key": EMAIL_KEY,
        "display_name": "PEP - Email",
        "version": _version(),
        "description": "Hilton PEP report packages emailed on a schedule to the connection's address (shown on the connection; files-…@aria-ingest.com) to bronze, silver and gold: the same tables as PEP (Drive).",
        "job": {"name": JOB_NAME, "timeout_seconds": 60 * 60},
        "inbox": True,
        "inbox_local_part": "files",
        "progress": "v1",
        "config_schema": EMAIL_CONFIG_SCHEMA,
        "run_params_schema": EMAIL_RUN_PARAMS_SCHEMA,
    }
