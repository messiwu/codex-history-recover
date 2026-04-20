from __future__ import annotations

from datetime import UTC, datetime
import json

from .models import IndexEntry, ThreadRecord


def isoformat_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, UTC).isoformat().replace("+00:00", "Z")


def build_index_entries(threads: dict[str, ThreadRecord]) -> list[IndexEntry]:
    session_backed = [thread for thread in threads.values() if thread.session_exists]
    session_backed.sort(key=lambda item: (-item.updated_at_ms, item.thread_id))
    entries: list[IndexEntry] = []
    for position, thread in enumerate(session_backed):
        entries.append(
            IndexEntry(
                thread_id=thread.thread_id,
                thread_name=thread.title,
                updated_at=isoformat_from_ms(thread.updated_at_ms),
                position=position,
            )
        )
    return entries


def build_index_content(threads: dict[str, ThreadRecord]) -> str:
    lines = [
        json.dumps(
            {
                "id": entry.thread_id,
                "thread_name": entry.thread_name,
                "updated_at": entry.updated_at,
            },
            ensure_ascii=False,
        )
        for entry in build_index_entries(threads)
    ]
    return ("\n".join(lines) + "\n") if lines else ""
