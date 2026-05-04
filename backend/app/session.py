from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import EnrichmentRequest

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TeeingQueue(asyncio.Queue):
    """asyncio.Queue that appends `event: log` items to a JSONL sidecar.

    The log path is set after construction (runner knows it only once the
    run timestamp is chosen). Non-log events pass through unchanged.
    """

    def __init__(self) -> None:
        super().__init__()
        self._log_fp = None

    def set_log_path(self, path: Path) -> None:
        self._log_fp = path.open("a", encoding="utf-8")

    def put_nowait(self, item) -> None:
        super().put_nowait(item)
        if self._log_fp is not None and isinstance(item, dict) and item.get("event") == "log":
            self._log_fp.write(item["data"] + "\n")
            self._log_fp.flush()

    def close(self) -> None:
        if self._log_fp is not None:
            self._log_fp.close()
            self._log_fp = None


@dataclass
class ScrapeSession:
    id: str
    brand_id: str
    source_id: str
    queue: TeeingQueue = field(default_factory=TeeingQueue)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    login_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    # Enrichment-only: when set, the session runs ``run_enrichment`` against
    # ``parent_run_id`` using ``request``. Grid scrape sessions leave both as None.
    parent_run_id: str | None = None
    request: "EnrichmentRequest | None" = None


sessions: dict[str, ScrapeSession] = {}


class QueueLogHandler(logging.Handler):
    """Captures log records and pushes them as SSE-ready dicts onto an asyncio.Queue."""

    def __init__(self, queue: asyncio.Queue):
        super().__init__()
        self.queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        message = ANSI_RE.sub("", self.format(record))
        if not message.strip():
            return

        level = "info"
        if record.levelno >= logging.ERROR:
            level = "error"
        elif record.levelno >= logging.WARNING:
            level = "warning"
        elif record.levelno == 35:  # browser-use RESULT level
            level = "success"

        try:
            self.queue.put_nowait(
                {"event": "log", "data": json.dumps({"message": message, "level": level})}
            )
        except asyncio.QueueFull:
            pass


# ContextVar carrying the in-flight session id. Set by the runner at the top of
# _run_job so every log record emitted on an attached logger knows which session
# owns it. Without this, widening capture to the "app" logger means records
# emitted while session A runs also fan out to session B's queue.
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_session_id", default=None,
)


class SessionLogFilter(logging.Filter):
    """Only pass records that belong to ``session_id``.

    A record belongs to the session if the ``current_session_id`` ContextVar
    matches. As a pragmatic exception, records from the ``browser_use``
    logger (or any child) are passed through when the ContextVar is unset —
    browser_use / playwright frequently emit from threads and subprocess
    workers whose context is not propagated by asyncio, and dropping them
    would regress the grid-scrape LogFeed. Cross-session leakage is still
    prevented, because a record with a *different* session ID set is
    blocked regardless of logger name.
    """

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = current_session_id.get()
        if ctx == self.session_id:
            return True
        if ctx is None and (record.name == "browser_use" or record.name.startswith("browser_use.")):
            return True
        return False


# Loggers whose records get piped into the SSE queue. "browser_use" preserves
# the existing grid-scrape behaviour; "app" covers every project module
# (runner, extractors, brands repo, session) so enrichment warnings and
# Shopee-scrape logs — which use app.* loggers, not browser_use — reach the
# LogFeed. Relies on child loggers under "app.*" keeping propagate = True.
_CAPTURED_LOGGERS: tuple[str, ...] = ("browser_use", "app")


def attach_queue_log_handler(
    queue: asyncio.Queue, *, session_id: str,
) -> logging.Handler:
    """Attach a single ``QueueLogHandler`` — filtered to ``session_id`` — to
    every logger in ``_CAPTURED_LOGGERS``. Returns the handler so the caller
    can detach it in a ``finally`` block."""
    handler = QueueLogHandler(queue)
    handler.setLevel(logging.INFO)
    handler.addFilter(SessionLogFilter(session_id))
    for name in _CAPTURED_LOGGERS:
        logging.getLogger(name).addHandler(handler)
    return handler


def detach_queue_log_handler(handler: logging.Handler) -> None:
    for name in _CAPTURED_LOGGERS:
        logging.getLogger(name).removeHandler(handler)
