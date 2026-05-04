import asyncio
import json
import logging
from pathlib import Path

import pytest

from app.session import (
    QueueLogHandler,
    SessionLogFilter,
    TeeingQueue,
    attach_queue_log_handler,
    current_session_id,
    detach_queue_log_handler,
)


def test_tee_writes_log_events_to_file(tmp_path: Path):
    log_path = tmp_path / "run.log.jsonl"
    q = TeeingQueue()
    q.set_log_path(log_path)

    q.put_nowait({"event": "log", "data": json.dumps({"message": "hello", "level": "info"})})
    q.put_nowait({"event": "log", "data": json.dumps({"message": "world", "level": "warning"})})
    q.close()

    lines = log_path.read_text().splitlines()
    assert [json.loads(l) for l in lines] == [
        {"message": "hello", "level": "info"},
        {"message": "world", "level": "warning"},
    ]


def test_tee_ignores_non_log_events(tmp_path: Path):
    log_path = tmp_path / "run.log.jsonl"
    q = TeeingQueue()
    q.set_log_path(log_path)

    q.put_nowait({"event": "product", "data": json.dumps({"product_name": "x"})})
    q.put_nowait({"event": "done", "data": json.dumps({"count": 0})})
    q.close()

    assert not log_path.exists() or log_path.read_text() == ""


def test_tee_without_log_path_is_noop(tmp_path: Path):
    q = TeeingQueue()  # no set_log_path call
    q.put_nowait({"event": "log", "data": json.dumps({"message": "x", "level": "info"})})
    q.close()  # must not raise


@pytest.mark.asyncio
async def test_tee_preserves_queue_semantics(tmp_path: Path):
    log_path = tmp_path / "run.log.jsonl"
    q = TeeingQueue()
    q.set_log_path(log_path)

    item = {"event": "log", "data": json.dumps({"message": "x", "level": "info"})}
    q.put_nowait(item)
    got = await q.get()
    assert got == item
    q.close()


# --- SessionLogFilter -------------------------------------------------------


def test_session_log_filter_blocks_records_outside_its_session():
    q = asyncio.Queue()
    h = QueueLogHandler(q)
    h.addFilter(SessionLogFilter("sess-A"))
    h.setLevel(logging.INFO)

    logger = logging.getLogger("app.test_filter_block")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    try:
        token = current_session_id.set("sess-B")  # different session
        try:
            logger.info("should not be captured")
        finally:
            current_session_id.reset(token)
    finally:
        logger.removeHandler(h)

    assert q.empty()


def test_session_log_filter_passes_records_within_its_session():
    q = asyncio.Queue()
    h = QueueLogHandler(q)
    h.addFilter(SessionLogFilter("sess-A"))
    h.setLevel(logging.INFO)

    logger = logging.getLogger("app.test_filter_pass")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    try:
        token = current_session_id.set("sess-A")
        try:
            logger.info("should be captured")
        finally:
            current_session_id.reset(token)
    finally:
        logger.removeHandler(h)

    item = q.get_nowait()
    assert item["event"] == "log"
    assert "should be captured" in item["data"]


def test_session_log_filter_blocks_app_records_with_no_session_context():
    """Records from `app.*` loggers with no session ContextVar set must not
    leak into any session queue — prevents global app-log noise from
    hijacking an SSE stream."""
    q = asyncio.Queue()
    h = QueueLogHandler(q)
    h.addFilter(SessionLogFilter("sess-A"))
    h.setLevel(logging.INFO)

    logger = logging.getLogger("app.test_filter_unset")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    try:
        logger.info("no session context")
    finally:
        logger.removeHandler(h)

    assert q.empty()


def test_session_log_filter_passes_browser_use_records_with_no_session_context():
    """browser_use records emitted from threads/executors won't carry the
    ContextVar (asyncio task context doesn't propagate to bare threads).
    Dropping them would regress today's grid-scrape LogFeed, so the filter
    lets context-less browser_use.* records through."""
    q = asyncio.Queue()
    h = QueueLogHandler(q)
    h.addFilter(SessionLogFilter("sess-A"))
    h.setLevel(logging.INFO)

    logger = logging.getLogger("browser_use.agent")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    try:
        # No ContextVar set — simulates a log from a thread browser_use spawned.
        logger.info("browser_use from thread")
    finally:
        logger.removeHandler(h)

    item = q.get_nowait()
    assert "browser_use from thread" in item["data"]


def test_session_log_filter_blocks_browser_use_records_from_other_session():
    """browser_use records that DO carry a different session ID must still
    be blocked — the passthrough only applies to truly context-less records."""
    q = asyncio.Queue()
    h = QueueLogHandler(q)
    h.addFilter(SessionLogFilter("sess-A"))
    h.setLevel(logging.INFO)

    logger = logging.getLogger("browser_use.other_session")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    try:
        token = current_session_id.set("sess-B")
        try:
            logger.info("should not leak cross-session")
        finally:
            current_session_id.reset(token)
    finally:
        logger.removeHandler(h)

    assert q.empty()


# --- attach/detach helpers --------------------------------------------------


def test_attach_queue_log_handler_captures_both_browser_use_and_app():
    q = asyncio.Queue()
    token = current_session_id.set("sess-X")
    try:
        handler = attach_queue_log_handler(q, session_id="sess-X")
        try:
            logging.getLogger("browser_use.child").warning("bu record")
            logging.getLogger("app.platforms.anything").warning("app record")
        finally:
            detach_queue_log_handler(handler)
    finally:
        current_session_id.reset(token)

    items = []
    while not q.empty():
        items.append(q.get_nowait())
    messages = [i["data"] for i in items]
    assert any("bu record" in m for m in messages)
    assert any("app record" in m for m in messages)


def test_detach_queue_log_handler_removes_from_all_loggers():
    """Cycle attach→detach→log; nothing should land on the queue after detach."""
    q = asyncio.Queue()
    token = current_session_id.set("sess-Y")
    try:
        handler = attach_queue_log_handler(q, session_id="sess-Y")
        detach_queue_log_handler(handler)
        logging.getLogger("browser_use.after_detach").warning("nope")
        logging.getLogger("app.after_detach").warning("nope")
    finally:
        current_session_id.reset(token)

    assert q.empty()


def test_attach_is_isolated_across_two_sessions():
    """Regression: session A's logs must not leak into session B's queue
    even though both handlers are attached to the shared 'app' logger."""
    qA = asyncio.Queue()
    qB = asyncio.Queue()
    hA = attach_queue_log_handler(qA, session_id="A")
    hB = attach_queue_log_handler(qB, session_id="B")
    try:
        tok = current_session_id.set("A")
        try:
            logging.getLogger("app.leak_test").warning("from A")
        finally:
            current_session_id.reset(tok)
    finally:
        detach_queue_log_handler(hA)
        detach_queue_log_handler(hB)

    a_items = []
    while not qA.empty():
        a_items.append(qA.get_nowait())
    assert any("from A" in i["data"] for i in a_items)
    assert qB.empty()
