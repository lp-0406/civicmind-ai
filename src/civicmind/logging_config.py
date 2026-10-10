"""Structured, configurable logging for CivicMind AI.

Two output formats are supported:

* ``text``  - human-readable, for local development.
* ``json``  - one JSON object per line, for machine ingestion and CI.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEXT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# Attributes present on every LogRecord; anything else is treated as structured
# context and serialised into the payload.
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects.

    Extra fields attached via ``logger.info("...", extra={"source_id": ...})``
    are flattened into the JSON payload, which makes logs greppable and
    machine-parsable without a third-party dependency.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
            else:
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def build_formatter(log_format: str) -> logging.Formatter:
    """Return a formatter instance for ``text`` or ``json`` output."""
    if log_format == "json":
        return JsonFormatter()
    if log_format == "text":
        return logging.Formatter(fmt=TEXT_FORMAT)
    raise ValueError(f"Unknown log format {log_format!r}; expected 'text' or 'json'")


def setup_logging(
    level: str = "INFO",
    log_format: str = "text",
    log_file: Path | None = None,
    *,
    force: bool = True,
) -> None:
    """Configure root logging for the process.

    Parameters
    ----------
    level:
        Minimum level to emit (``DEBUG``..``CRITICAL``).
    log_format:
        ``"text"`` for humans or ``"json"`` for machines.
    log_file:
        Optional file target. The parent directory is created if missing and
        files are written as UTF-8 so non-ASCII place names survive on Windows.
    force:
        Replace any handlers already installed on the root logger.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler(stream=sys.stderr)]
    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(filename=log_file, encoding="utf-8"))

    formatter = build_formatter(log_format)
    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=force)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger (convenience wrapper)."""
    return logging.getLogger(name)
