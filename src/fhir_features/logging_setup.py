"""Deny-by-default structured logging (ADR-0008).

A final structlog processor drops every event key not on the explicit allowlist, so patient
names, clinical values, and file paths cannot leak into logs even by accident. The log-safety
test ingests fixtures and asserts no sentinel strings appear in captured output.
"""

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

#: The only keys that may reach a log sink. Everything else is silently dropped.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "event",
        "level",
        "logger",
        "timestamp",
        "request_id",
        "bundle_hash",
        "source",
        "action",
        "resource_counts",
        "skipped_resource_types",
        "warning_codes",
        "warning_count",
        "row_counts",
        "duration_ms",
        "status_code",
        "method",
        "path",
        "service_version",
        "schema_version",
        "feature_version",
        "valuesets_version",
        "migration_version",
        "patient_count",
        "exc_info",
    }
)


def _allowlist_processor(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    return {k: v for k, v in event_dict.items() if k in ALLOWED_KEYS}


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structlog for JSON output with the deny-by-default allowlist."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _allowlist_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Named logger; call :func:`configure_logging` once at startup first."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
