from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

# SECURITY.md §8: never let these reach a log line, whatever call site forgot to.
_REDACTED = "***REDACTED***"
_SENSITIVE_KEY_PATTERN = re.compile(r"password|token|cookie|authorization|secret|csrf", re.I)

_BASE_RECORD_KEYS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys())


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__):
            if key not in _BASE_RECORD_KEYS and _SENSITIVE_KEY_PATTERN.search(key):
                record.__dict__[key] = _REDACTED
        return True


class RequestContextFilter(logging.Filter):
    """Stamps request_id (set by core/request_id.py's middleware) onto every line."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            from trinol.core.request_id import get_request_id

            record.request_id = get_request_id()
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _BASE_RECORD_KEYS or key in ("msg", "args"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(RequestContextFilter())
    handler.addFilter(RedactionFilter())  # last: redacts whatever the formatter is about to emit

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
