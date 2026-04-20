from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from .models import IndexEntry, IssueRecord, ScanReport, ThreadRecord
from .paths import detect_root, resolve_target_provider
from .rebuild import build_index_entries


ISSUE_ORDER = {
    "missing_thread_row": 0,
    "provider_mismatch": 1,
    "stale_session_index": 2,
}


def normalize_provider(value: str | None) -> str | None:
    if value is None:
        return None
    return value.casefold()


def parse_timestamp_to_ms(value: str | None) -> int:
    if not value:
        return 0
    normalized = value.replace("Z", "+00:00")
    return int(datetime.fromisoformat(normalized).timestamp() * 1000)


def isoformat_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, UTC).isoformat().replace("+00:00", "Z")


def dump_json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def extract_user_text_from_response_item(payload: dict[str, Any]) -> str:
    if payload.get("role") != "user":
        return ""
    contents = payload.get("content")
    if not isinstance(contents, list):
        return ""
    texts: list[str] = []
    for item in contents:
        if item.get("type") == "input_text":
            text = str(item.get("text", "")).strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def parse_session_file(path: Path) -> dict[str, Any]:
    created_at_ms = 0
    updated_at_ms = 0
    thread_id = ""
    cwd = ""
    source = ""
    cli_version = ""
    session_model_provider: str | None = None
    sandbox_policy = ""
    approval_mode = ""
    model: str | None = None
    reasoning_effort: str | None = None
    first_user_message = ""
    title = ""
    has_user_event = False

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle):
            if not line.strip():
                continue
            item = json.loads(line)
            timestamp_ms = parse_timestamp_to_ms(item.get("timestamp"))
            if created_at_ms == 0 or (timestamp_ms and timestamp_ms < created_at_ms):
                created_at_ms = timestamp_ms
            updated_at_ms = max(updated_at_ms, timestamp_ms)

            item_type = item.get("type")
            payload = item.get("payload", {})
            if item_type == "session_meta" and not thread_id:
                thread_id = str(payload.get("id", "")).strip()
                cwd = str(payload.get("cwd", "")).strip()
                source = str(payload.get("source", "")).strip()
                cli_version = str(payload.get("cli_version", "")).strip()
                session_model_provider = payload.get("model_provider")
                payload_timestamp = parse_timestamp_to_ms(payload.get("timestamp"))
                if payload_timestamp:
                    created_at_ms = payload_timestamp if created_at_ms == 0 else min(created_at_ms, payload_timestamp)
            elif item_type == "turn_context" and not approval_mode:
                cwd = cwd or str(payload.get("cwd", "")).strip()
                approval_mode = str(payload.get("approval_policy", "")).strip()
                sandbox_policy = dump_json_compact(payload.get("sandbox_policy", {}))
                model = payload.get("model")
                reasoning_effort = payload.get("effort") or payload.get("reasoning_effort")
            elif item_type == "event_msg" and payload.get("type") == "user_message" and not first_user_message:
                message = str(payload.get("message", "")).strip()
                if message:
                    first_user_message = message
                    title = message
                    has_user_event = True
            elif item_type == "response_item" and not first_user_message:
                message = extract_user_text_from_response_item(payload)
                if message:
                    first_user_message = message
                    title = message
                    has_user_event = True

    if not thread_id:
        raise ValueError(f"session 文件缺少 thread id: {path}")
    if not title:
        title = first_user_message or thread_id
    if not updated_at_ms:
        updated_at_ms = created_at_ms
    return {
        "thread_id": thread_id,
        "title": title,
        "first_user_message": first_user_message or title,
        "cwd": cwd,
        "source": source or "cli",
        "rollout_path": str(path),
        "session_path": path,
        "db_model_provider": None,
        "session_model_provider": session_model_provider,
        "sandbox_policy": sandbox_policy or "{}",
        "approval_mode": approval_mode,
        "cli_version": cli_version,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "created_at_ms": created_at_ms,
        "updated_at_ms": updated_at_ms,
        "has_user_event": has_user_event,
        "archived": False,
    }


def load_session_threads(root: Path) -> dict[str, dict[str, Any]]:
    sessions_root = root / "sessions"
    if not sessions_root.is_dir():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(sessions_root.rglob("*.jsonl")):
        if path.name.startswith("."):
            continue
        session = parse_session_file(path)
        records[session["thread_id"]] = session
    return records


def load_db_threads(root: Path) -> dict[str, dict[str, Any]]:
    db_path = root / "state_5.sqlite"
    if not db_path.is_file():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                sandbox_policy, approval_mode, has_user_event, archived, cli_version,
                first_user_message, model, reasoning_effort, created_at_ms, updated_at_ms
            FROM threads
            """
        ).fetchall()
    finally:
        conn.close()

    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        created_at_ms = row["created_at_ms"] or row["created_at"] * 1000
        updated_at_ms = row["updated_at_ms"] or row["updated_at"] * 1000
        records[row["id"]] = {
            "thread_id": row["id"],
            "title": row["title"] or row["first_user_message"] or row["id"],
            "first_user_message": row["first_user_message"] or row["title"] or row["id"],
            "cwd": row["cwd"] or "",
            "source": row["source"] or "cli",
            "rollout_path": row["rollout_path"],
            "session_path": None,
            "db_model_provider": row["model_provider"],
            "session_model_provider": None,
            "sandbox_policy": row["sandbox_policy"] or "{}",
            "approval_mode": row["approval_mode"] or "",
            "cli_version": row["cli_version"] or "",
            "model": row["model"],
            "reasoning_effort": row["reasoning_effort"],
            "created_at_ms": created_at_ms,
            "updated_at_ms": updated_at_ms,
            "has_user_event": bool(row["has_user_event"]),
            "archived": bool(row["archived"]),
        }
    return records


def load_session_index(root: Path) -> list[IndexEntry]:
    path = root / "session_index.jsonl"
    if not path.is_file():
        return []
    entries: list[IndexEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for position, line in enumerate(handle):
            if not line.strip():
                continue
            data = json.loads(line)
            entries.append(
                IndexEntry(
                    thread_id=str(data.get("id", "")),
                    thread_name=str(data.get("thread_name", "")),
                    updated_at=str(data.get("updated_at", "")),
                    position=position,
                )
            )
    return entries


def merge_threads(
    session_threads: dict[str, dict[str, Any]],
    db_threads: dict[str, dict[str, Any]],
) -> dict[str, ThreadRecord]:
    merged: dict[str, ThreadRecord] = {}
    for thread_id in sorted(set(session_threads) | set(db_threads)):
        session_data = session_threads.get(thread_id)
        db_data = db_threads.get(thread_id)
        session_path: Path | None = None
        rollout_path = ""
        if session_data is not None:
            session_path = session_data["session_path"]
            rollout_path = session_data["rollout_path"]
        elif db_data is not None:
            rollout_path = db_data["rollout_path"]
            candidate = Path(rollout_path)
            if candidate.is_file():
                session_path = candidate
        merged[thread_id] = ThreadRecord(
            thread_id=thread_id,
            title=(db_data or session_data or {}).get("title", thread_id),
            first_user_message=(db_data or session_data or {}).get("first_user_message", thread_id),
            cwd=(db_data or session_data or {}).get("cwd", ""),
            source=(db_data or session_data or {}).get("source", "cli"),
            rollout_path=rollout_path,
            session_path=session_path,
            db_model_provider=None if db_data is None else db_data["db_model_provider"],
            session_model_provider=None if session_data is None else session_data["session_model_provider"],
            sandbox_policy=(db_data or session_data or {}).get("sandbox_policy", "{}"),
            approval_mode=(db_data or session_data or {}).get("approval_mode", ""),
            cli_version=(db_data or session_data or {}).get("cli_version", ""),
            model=(db_data or session_data or {}).get("model"),
            reasoning_effort=(db_data or session_data or {}).get("reasoning_effort"),
            created_at_ms=(db_data or session_data or {}).get("created_at_ms", 0),
            updated_at_ms=(db_data or session_data or {}).get("updated_at_ms", 0),
            has_user_event=bool((db_data or session_data or {}).get("has_user_event", False)),
            archived=bool((db_data or session_data or {}).get("archived", False)),
        )
    return merged


def collect_index_issues(
    current_entries: list[IndexEntry],
    expected_entries: list[IndexEntry],
) -> tuple[set[str], int]:
    current_map = {entry.thread_id: entry for entry in current_entries}
    stale_thread_ids: set[str] = set()
    for expected in expected_entries:
        current = current_map.get(expected.thread_id)
        if current is None:
            stale_thread_ids.add(expected.thread_id)
            continue
        if (
            current.thread_name != expected.thread_name
            or current.updated_at != expected.updated_at
            or current.position != expected.position
        ):
            stale_thread_ids.add(expected.thread_id)

    expected_ids = {entry.thread_id for entry in expected_entries}
    dangling_count = sum(1 for entry in current_entries if entry.thread_id not in expected_ids)
    return stale_thread_ids, dangling_count


def issue_sort_key(item: IssueRecord) -> tuple[int, str]:
    primary = min(ISSUE_ORDER[issue] for issue in item.issue_types)
    return primary, item.thread_id


def filter_threads_by_cwd(threads: dict[str, ThreadRecord], cwd_filter: str | None) -> dict[str, ThreadRecord]:
    if not cwd_filter:
        return threads
    return {thread_id: thread for thread_id, thread in threads.items() if thread.cwd == cwd_filter}


def scan_root(
    root: str | Path | None = None,
    provider_override: str | None = None,
    cwd_filter: str | None = None,
) -> ScanReport:
    resolved_root = detect_root(root)
    target_provider = resolve_target_provider(resolved_root, provider_override)
    session_threads = load_session_threads(resolved_root)
    db_threads = load_db_threads(resolved_root)
    threads = merge_threads(session_threads, db_threads)
    scoped_threads = filter_threads_by_cwd(threads, cwd_filter)

    current_index_entries = load_session_index(resolved_root)
    expected_index_entries = build_index_entries(threads)
    stale_index_thread_ids, dangling_index_count = collect_index_issues(current_index_entries, expected_index_entries)

    candidates: list[IssueRecord] = []
    orphan_threads: list[IssueRecord] = []
    provider_counter = Counter(
        provider
        for provider in (thread.db_model_provider for thread in scoped_threads.values())
        if provider
    )

    for thread in scoped_threads.values():
        issue_types: list[str] = []
        if thread.session_exists and thread.db_model_provider is None:
            issue_types.append("missing_thread_row")

        if thread.session_exists:
            providers_to_check = [value for value in (thread.db_model_provider, thread.session_model_provider) if value]
            if any(normalize_provider(value) != normalize_provider(target_provider) for value in providers_to_check):
                issue_types.append("provider_mismatch")
            if thread.thread_id in stale_index_thread_ids:
                issue_types.append("stale_session_index")
        elif thread.db_model_provider is not None:
            orphan_threads.append(
                IssueRecord(
                    thread_id=thread.thread_id,
                    title=thread.title,
                    cwd=thread.cwd,
                    source=thread.source,
                    db_model_provider=thread.db_model_provider,
                    session_model_provider=thread.session_model_provider,
                    updated_at_ms=thread.updated_at_ms,
                    issue_types=("orphan_thread_row",),
                    session_path=thread.session_path,
                )
            )

        if issue_types:
            candidates.append(
                IssueRecord(
                    thread_id=thread.thread_id,
                    title=thread.title,
                    cwd=thread.cwd,
                    source=thread.source,
                    db_model_provider=thread.db_model_provider,
                    session_model_provider=thread.session_model_provider,
                    updated_at_ms=thread.updated_at_ms,
                    issue_types=tuple(issue_types),
                    session_path=thread.session_path,
                )
            )

    candidates.sort(key=issue_sort_key)
    orphan_threads.sort(key=lambda item: item.thread_id)
    summary = {
        "session_count": sum(1 for thread in scoped_threads.values() if thread.session_exists),
        "thread_count": len(scoped_threads),
        "session_index_count": len(current_index_entries),
        "candidate_count": len(candidates),
        "orphan_count": len(orphan_threads),
        "index_out_of_sync": bool(stale_index_thread_ids or dangling_index_count),
        "dangling_session_index_count": dangling_index_count,
        "db_provider_counts": dict(sorted(provider_counter.items())),
    }
    return ScanReport(
        root=resolved_root,
        target_provider=target_provider,
        threads=threads,
        scoped_thread_ids=tuple(sorted(scoped_threads)),
        candidates=candidates,
        orphan_threads=orphan_threads,
        expected_index_entries=expected_index_entries,
        current_index_entries=current_index_entries,
        summary=summary,
    )
