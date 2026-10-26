"""Structured logging with request/job context and redaction (spec §10.6)."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar

from app.config import AppEnv, Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)
analysis_id_var: ContextVar[str | None] = ContextVar("analysis_id", default=None)

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "message",
    "asctime", "taskName",
}

_REDACT_KEYS = {"authorization", "api_key", "openrouter_api_key", "prompt", "content", "text"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line in prod; key/value survives log shippers."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "job_id", "analysis_id"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in payload or key.startswith("_"):
                continue
            payload[key] = "[redacted]" if key.lower() in _REDACT_KEYS else value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Readable in a terminal, with the same context prefixes."""

    def format(self, record: logging.LogRecord) -> str:
        parts = [self.formatTime(record, "%H:%M:%S"), record.levelname[0], record.name]
        request_id = getattr(record, "request_id", None)
        job_id = getattr(record, "job_id", None)
        if request_id:
            parts.append(f"req={request_id}")
        if job_id:
            parts.append(f"job={job_id}")
        prefix = " ".join(parts)
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        return f"{prefix} | {message}"


class ContextFilter(logging.Filter):
    """Copies contextvars onto every record so both formatters can read them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or request_id_var.get()
        record.job_id = getattr(record, "job_id", None) or job_id_var.get()
        record.analysis_id = getattr(record, "analysis_id", None) or analysis_id_var.get()
        return True


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if settings.APP_ENV is AppEnv.PROD else HumanFormatter()
    )
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.value)

    # These libraries log full request URLs and can echo bodies at DEBUG.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
