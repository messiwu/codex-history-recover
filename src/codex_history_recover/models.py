from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class IndexEntry:
    thread_id: str
    thread_name: str
    updated_at: str
    position: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.thread_id,
            "thread_name": self.thread_name,
            "updated_at": self.updated_at,
            "position": self.position,
        }


@dataclass(slots=True)
class ThreadRecord:
    thread_id: str
    title: str
    first_user_message: str
    cwd: str
    source: str
    rollout_path: str
    session_path: Path | None
    db_model_provider: str | None
    session_model_provider: str | None
    sandbox_policy: str
    approval_mode: str
    cli_version: str
    model: str | None
    reasoning_effort: str | None
    created_at_ms: int
    updated_at_ms: int
    has_user_event: bool
    archived: bool

    @property
    def session_exists(self) -> bool:
        return self.session_path is not None and self.session_path.is_file()

    @property
    def repairable(self) -> bool:
        return self.session_exists

    def effective_provider(self) -> str | None:
        return self.db_model_provider or self.session_model_provider

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "first_user_message": self.first_user_message,
            "cwd": self.cwd,
            "source": self.source,
            "rollout_path": self.rollout_path,
            "session_path": None if self.session_path is None else str(self.session_path),
            "db_model_provider": self.db_model_provider,
            "session_model_provider": self.session_model_provider,
            "sandbox_policy": self.sandbox_policy,
            "approval_mode": self.approval_mode,
            "cli_version": self.cli_version,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "has_user_event": self.has_user_event,
            "archived": self.archived,
        }


@dataclass(slots=True)
class IssueRecord:
    thread_id: str
    title: str
    cwd: str
    source: str
    db_model_provider: str | None
    session_model_provider: str | None
    updated_at_ms: int
    issue_types: tuple[str, ...]
    session_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "cwd": self.cwd,
            "source": self.source,
            "db_model_provider": self.db_model_provider,
            "session_model_provider": self.session_model_provider,
            "updated_at_ms": self.updated_at_ms,
            "issue_types": list(self.issue_types),
            "session_path": None if self.session_path is None else str(self.session_path),
        }


@dataclass(slots=True)
class ScanReport:
    root: Path
    target_provider: str
    threads: dict[str, ThreadRecord]
    scoped_thread_ids: tuple[str, ...]
    candidates: list[IssueRecord]
    orphan_threads: list[IssueRecord]
    expected_index_entries: list[IndexEntry]
    current_index_entries: list[IndexEntry]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "target_provider": self.target_provider,
            "summary": self.summary,
            "scoped_thread_ids": list(self.scoped_thread_ids),
            "candidates": [item.to_dict() for item in self.candidates],
            "orphans": [item.to_dict() for item in self.orphan_threads],
            "expected_index_entries": [item.to_dict() for item in self.expected_index_entries],
            "current_index_entries": [item.to_dict() for item in self.current_index_entries],
        }


@dataclass(slots=True)
class RepairResult:
    root: Path
    target_provider: str
    selected_thread_ids: list[str]
    provider_updated_ids: list[str]
    inserted_thread_ids: list[str]
    session_updated_ids: list[str]
    index_rebuilt: bool
    dry_run: bool
    backup_dir: Path | None
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "target_provider": self.target_provider,
            "selected_thread_ids": self.selected_thread_ids,
            "provider_updated_ids": self.provider_updated_ids,
            "inserted_thread_ids": self.inserted_thread_ids,
            "session_updated_ids": self.session_updated_ids,
            "index_rebuilt": self.index_rebuilt,
            "dry_run": self.dry_run,
            "backup_dir": None if self.backup_dir is None else str(self.backup_dir),
            "summary": self.summary,
        }
