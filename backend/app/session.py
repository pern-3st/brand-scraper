import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from app.models import ScrapeRequest

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class ScrapeSession:
    id: str
    request: ScrapeRequest
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


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
