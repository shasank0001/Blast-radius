"""Structured JSON logging configuration."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON with blast-radius specific fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add blast-radius specific fields if present
        for field in ("run_id", "query_id", "tool_name", "cached", "timing_ms"):
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON formatter."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger("blast_radius")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the blast_radius namespace."""
    return logging.getLogger(f"blast_radius.{name}")
