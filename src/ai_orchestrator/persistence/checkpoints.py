"""SQLite checkpointer so interrupted tasks can be resumed (`ai-orchestrator resume`)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


@contextmanager
def open_checkpointer(root: Path) -> Iterator[SqliteSaver]:
    root.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(root / "checkpoints.sqlite")) as saver:
        yield saver
