from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any

from .inventory import normalize_provider, scan_root
from .models import RepairResult, ScanReport, ThreadRecord
from .rebuild import build_index_content


class RepairError(RuntimeError):
    """修复失败。"""


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def build_session_provider_content(path: Path, target_provider: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RepairError(f"session 文件为空，无法修复: {path}")
    first = json.loads(lines[0])
    if first.get("type") != "session_meta":
        raise RepairError(f"session 文件首行不是 session_meta: {path}")
    payload = first.setdefault("payload", {})
    payload["model_provider"] = target_provider
    lines[0] = json.dumps(first, ensure_ascii=False, separators=(",", ":"))
    return "\n".join(lines) + "\n"

def select_candidate_ids(
    report: ScanReport,
    *,
    selected_thread_ids: list[str] | None,
    select_all: bool,
) -> list[str]:
    repairable_ids = {item.thread_id for item in report.candidates}
    if selected_thread_ids:
        unknown = [thread_id for thread_id in selected_thread_ids if thread_id not in repairable_ids]
        if unknown:
            raise RepairError(f"指定线程不可修复或不存在: {', '.join(unknown)}")
        return list(dict.fromkeys(selected_thread_ids))
    if select_all:
        return [item.thread_id for item in report.candidates]
    if not report.candidates and report.summary["index_out_of_sync"]:
        return []
    raise RepairError("未选择需要修复的线程，请使用 --all、--thread 或交互选择")


def prepare_final_threads(report: ScanReport, selected_ids: list[str]) -> dict[str, ThreadRecord]:
    threads = deepcopy(report.threads)
    for thread_id in selected_ids:
        thread = threads[thread_id]
        thread.db_model_provider = report.target_provider
        if thread.session_exists:
            thread.session_model_provider = report.target_provider
    return threads


def timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def backup_file_if_exists(source: Path, backup_root: Path, manifest: list[dict[str, Any]]) -> None:
    if not source.exists():
        return
    relative = source.name if source.is_absolute() else str(source)
    target = backup_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    manifest.append({"source": str(source), "backup": str(target)})


def create_backup(root: Path, selected_threads: list[ThreadRecord], include_index: bool) -> Path:
    backup_root = root / "recovery-backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / timestamp_slug()
    backup_dir.mkdir(parents=True, exist_ok=False)
    manifest: list[dict[str, Any]] = []
    for suffix in ("state_5.sqlite", "state_5.sqlite-wal", "state_5.sqlite-shm"):
        backup_file_if_exists(root / suffix, backup_dir, manifest)
    for thread in selected_threads:
        if thread.session_path is not None:
            backup_file_if_exists(thread.session_path, backup_dir / "sessions", manifest)
    if include_index:
        backup_file_if_exists(root / "session_index.jsonl", backup_dir, manifest)
    (backup_dir / "manifest.json").write_text(
        json.dumps({"files": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return backup_dir


def restore_backup(backup_dir: Path, root: Path, selected_threads: list[ThreadRecord], include_index: bool) -> None:
    for suffix in ("state_5.sqlite-wal", "state_5.sqlite-shm", "state_5.sqlite"):
        current = root / suffix
        backup = backup_dir / suffix
        if backup.exists():
            shutil.copy2(backup, current)
        elif current.exists():
            current.unlink()

    for thread in selected_threads:
        if thread.session_path is None:
            continue
        backup_path = backup_dir / "sessions" / thread.session_path.name
        if backup_path.exists():
            shutil.copy2(backup_path, thread.session_path)
        elif thread.session_path.exists():
            thread.session_path.unlink()

    if include_index:
        current_index = root / "session_index.jsonl"
        backup_index = backup_dir / "session_index.jsonl"
        if backup_index.exists():
            shutil.copy2(backup_index, current_index)
        elif current_index.exists():
            current_index.unlink()


def insert_thread_row(conn: sqlite3.Connection, thread: ThreadRecord, target_provider: str) -> None:
    created_at = thread.created_at_ms // 1000
    updated_at = thread.updated_at_ms // 1000
    conn.execute(
        """
        INSERT INTO threads (
            id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
            sandbox_policy, approval_mode, tokens_used, has_user_event, archived,
            cli_version, first_user_message, memory_mode, model, reasoning_effort,
            created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, 'enabled', ?, ?, ?, ?)
        """,
        (
            thread.thread_id,
            thread.rollout_path,
            created_at,
            updated_at,
            thread.source or "cli",
            target_provider,
            thread.cwd,
            thread.title,
            thread.sandbox_policy or "{}",
            thread.approval_mode,
            1 if thread.has_user_event else 0,
            thread.cli_version,
            thread.first_user_message or thread.title,
            thread.model,
            thread.reasoning_effort,
            thread.created_at_ms,
            thread.updated_at_ms,
        ),
    )


def apply_database_changes(
    root: Path,
    report: ScanReport,
    selected_ids: list[str],
) -> tuple[list[str], list[str]]:
    db_path = root / "state_5.sqlite"
    provider_updated_ids: list[str] = []
    inserted_thread_ids: list[str] = []
    conn = sqlite3.connect(db_path, timeout=0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for thread_id in selected_ids:
            thread = report.threads[thread_id]
            if thread.db_model_provider is None:
                insert_thread_row(conn, thread, report.target_provider)
                inserted_thread_ids.append(thread_id)
            elif normalize_provider(thread.db_model_provider) != normalize_provider(report.target_provider):
                conn.execute(
                    "UPDATE threads SET model_provider = ? WHERE id = ?",
                    (report.target_provider, thread_id),
                )
                provider_updated_ids.append(thread_id)
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        raise RepairError("SQLite 数据库被占用，请先关闭 Codex CLI 或桌面端后重试") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return provider_updated_ids, inserted_thread_ids


def repair_root(
    root: str | Path | None = None,
    *,
    provider_override: str | None = None,
    selected_thread_ids: list[str] | None = None,
    select_all: bool = False,
    dry_run: bool = False,
    cwd_filter: str | None = None,
) -> RepairResult:
    report = scan_root(root=root, provider_override=provider_override, cwd_filter=cwd_filter)
    selected_ids = select_candidate_ids(report, selected_thread_ids=selected_thread_ids, select_all=select_all)
    final_threads = prepare_final_threads(report, selected_ids)
    index_rebuilt = bool(report.summary["index_out_of_sync"])

    session_update_ids = [
        thread_id
        for thread_id in selected_ids
        if (
            final_threads[thread_id].session_exists
            and normalize_provider(report.threads[thread_id].session_model_provider)
            != normalize_provider(report.target_provider)
        )
    ]
    provider_update_ids = [
        thread_id
        for thread_id in selected_ids
        if (
            report.threads[thread_id].db_model_provider is not None
            and normalize_provider(report.threads[thread_id].db_model_provider)
            != normalize_provider(report.target_provider)
        )
    ]
    inserted_thread_ids = [
        thread_id for thread_id in selected_ids if report.threads[thread_id].db_model_provider is None
    ]
    summary = {
        "selected_count": len(selected_ids),
        "provider_update_count": len(provider_update_ids),
        "insert_count": len(inserted_thread_ids),
        "session_update_count": len(session_update_ids),
        "index_rebuilt": index_rebuilt,
    }

    if dry_run:
        return RepairResult(
            root=report.root,
            target_provider=report.target_provider,
            selected_thread_ids=selected_ids,
            provider_updated_ids=provider_update_ids,
            inserted_thread_ids=inserted_thread_ids,
            session_updated_ids=session_update_ids,
            index_rebuilt=index_rebuilt,
            dry_run=True,
            backup_dir=None,
            summary=summary,
        )

    selected_threads = [report.threads[thread_id] for thread_id in selected_ids]
    backup_dir = create_backup(report.root, selected_threads, include_index=index_rebuilt)
    new_session_contents = {
        report.threads[thread_id].session_path: build_session_provider_content(
            report.threads[thread_id].session_path,
            report.target_provider,
        )
        for thread_id in session_update_ids
        if report.threads[thread_id].session_path is not None
    }
    index_content = build_index_content(final_threads)

    try:
        actual_provider_updates, actual_inserted = apply_database_changes(report.root, report, selected_ids)
        for path, content in new_session_contents.items():
            atomic_write_text(path, content)
        if index_rebuilt:
            atomic_write_text(report.root / "session_index.jsonl", index_content)
    except Exception as exc:
        restore_backup(backup_dir, report.root, selected_threads, include_index=index_rebuilt)
        if isinstance(exc, RepairError):
            raise
        raise RepairError(str(exc)) from exc

    return RepairResult(
        root=report.root,
        target_provider=report.target_provider,
        selected_thread_ids=selected_ids,
        provider_updated_ids=actual_provider_updates,
        inserted_thread_ids=actual_inserted,
        session_updated_ids=session_update_ids,
        index_rebuilt=index_rebuilt,
        dry_run=False,
        backup_dir=backup_dir,
        summary=summary,
    )
