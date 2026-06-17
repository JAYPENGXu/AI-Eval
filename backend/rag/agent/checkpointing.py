from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

_CHECKPOINTER: Any | None = None
_CHECKPOINTER_CONTEXT: Any | None = None


def get_agent_checkpointer():
    """Return a process-local SQLite checkpointer for LangGraph agent state."""
    global _CHECKPOINTER, _CHECKPOINTER_CONTEXT
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        logger.warning(
            "LangGraph SQLite checkpointer is not installed. "
            "Install langgraph-checkpoint-sqlite to enable persisted agent threads: %s",
            exc,
        )
        return None

    db_path = Path(settings.LANGGRAPH_CHECKPOINT_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _CHECKPOINTER = SqliteSaver(conn)
    except TypeError:
        candidate = SqliteSaver.from_conn_string(str(db_path))
        if hasattr(candidate, "__enter__"):
            _CHECKPOINTER_CONTEXT = candidate
            _CHECKPOINTER = candidate.__enter__()
        else:
            _CHECKPOINTER = candidate

    setup = getattr(_CHECKPOINTER, "setup", None)
    if callable(setup):
        setup()

    logger.info("LangGraph SQLite checkpointer enabled at %s", db_path)
    return _CHECKPOINTER
