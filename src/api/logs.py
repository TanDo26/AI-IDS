"""
Logging for the API, the worker and beat: one line per record on stderr, JSON in the containers
(IDS_LOG_FORMAT=json), readable text otherwise.

Records made while a request is handled carry its request id (the X-Request-ID that Caddy sets and
the API returns); records made by a Celery task carry the task id and name. `docker compose logs api
worker | grep <id>` then follows one request or one job. The API logs one access line per request
(logger `ids.access`) instead of uvicorn's, so it has the request id, the user and the duration.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
task: ContextVar[tuple[str, str] | None] = ContextVar("task", default=None)   # (id, name)

# Attributes every LogRecord has; the others came through `extra=` and are logged as fields
# (except uvicorn's color_message: the message again, with terminal colour codes)
_RECORD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "color_message"}


class ContextFilter(logging.Filter):

    def filter(self, record):
        if getattr(record, "request_id", None) is None:
            record.request_id = request_id.get()
        current = task.get()
        if current is not None and getattr(record, "task_id", None) is None:
            record.task_id, record.task_name = current
        return True


def _fields(record) -> dict:
    return {k: v for k, v in vars(record).items() if k not in _RECORD_ATTRS and v is not None}


class JsonFormatter(logging.Formatter):

    def format(self, record):
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_fields(record),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):

    def __init__(self):
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    def format(self, record):
        line = super().format(record)
        # `data`: Celery's task-result fields, already in its message
        context = " ".join(f"{k}={v}" for k, v in _fields(record).items() if k != "data")
        if not context:
            return line
        head, sep, rest = line.partition("\n")             # keep tracebacks below the context
        return f"{head} [{context}]{sep}{rest}"


def configure_logging(log_format: str = "text", level: str | int = "INFO") -> None:
    """Send every logger to one stderr handler; uvicorn's loggers too. Safe to call again."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if log_format == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    handler.ids_handler = True
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, "ids_handler", False)] + [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    access = logging.getLogger("uvicorn.access")    # replaced by ids.access (src/api/main.py)
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
