"""Structured JSON logging.

Every log line carries the request id and user id from the request context.
Never log tokens, passwords, bank data, or file contents.
"""
import json
import logging
import sys
from datetime import UTC, datetime

from app.core.context import request_id_var, user_id_var


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = request_id_var.get()
        uid = user_id_var.get()
        if rid:
            payload["request_id"] = rid
        if uid:
            payload["user_id"] = uid
        for key in ("route", "status_code", "duration_ms", "error_code", "method"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(debug: bool = False) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    # Uvicorn access logs are replaced by our request middleware log line.
    logging.getLogger("uvicorn.access").disabled = True
