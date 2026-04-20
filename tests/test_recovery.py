import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from codex_history_recover.cli import main
from codex_history_recover.inventory import scan_root
from codex_history_recover.repair import RepairError, repair_root


THREADS_SCHEMA = """
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    cwd TEXT NOT NULL,
    title TEXT NOT NULL,
    sandbox_policy TEXT NOT NULL,
    approval_mode TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    has_user_event INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    archived_at INTEGER,
    git_sha TEXT,
    git_branch TEXT,
    git_origin_url TEXT,
    cli_version TEXT NOT NULL DEFAULT '',
    first_user_message TEXT NOT NULL DEFAULT '',
    agent_nickname TEXT,
    agent_role TEXT,
    memory_mode TEXT NOT NULL DEFAULT 'enabled',
    model TEXT,
    reasoning_effort TEXT,
    agent_path TEXT,
    created_at_ms INTEGER,
    updated_at_ms INTEGER
);
"""


def isoformat_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, UTC).isoformat().replace("+00:00", "Z")


class RecoveryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.db_path = root / "state_5.sqlite"
        self.index_path = root / "session_index.jsonl"
        self.sessions_root = root / "sessions"
        self.healthy_id = "healthy-thread"
        self.mismatch_id = "mismatch-thread"
        self.missing_id = "missing-thread"
        self.orphan_id = "orphan-thread"

    def build(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "config.toml").write_text('model_provider = "crs"\n', encoding="utf-8")
        self._init_db()
        self._write_sessions()
        self._write_index()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(THREADS_SCHEMA)
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
                self.healthy_id,
                str(self.session_path(self.healthy_id)),
                1713600000,
                1713600500,
                "cli",
                "crs",
                "/tmp/project-healthy",
                "健康线程",
                '{"type":"workspace-write"}',
                "on-request",
                1,
                "0.121.0",
                "健康线程",
                "gpt-5.4",
                "high",
                1713600000000,
                1713600500000,
            ),
        )
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
                self.mismatch_id,
                str(self.session_path(self.mismatch_id)),
                1713600000,
                1713600400,
                "cli",
                "OpenAI",
                "/tmp/project-mismatch",
                "旧 provider 线程",
                '{"type":"workspace-write"}',
                "on-request",
                1,
                "0.121.0",
                "旧 provider 线程",
                "gpt-5.4",
                "high",
                1713600000000,
                1713600400000,
            ),
        )
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
                self.orphan_id,
                str(self.root / "sessions/2026/04/20/rollout-orphan-thread.jsonl"),
                1713600000,
                1713600200,
                "cli",
                "OpenAI",
                "/tmp/project-orphan",
                "孤儿线程",
                '{"type":"workspace-write"}',
                "on-request",
                1,
                "0.121.0",
                "孤儿线程",
                "gpt-5.4",
                "high",
                1713600000000,
                1713600200000,
            ),
        )
        conn.commit()
        conn.close()

    def _write_sessions(self) -> None:
        self.write_session(
            self.healthy_id,
            provider="crs",
            message="健康线程",
            cwd="/tmp/project-healthy",
            start_ms=1713600000000,
            end_ms=1713600500000,
        )
        self.write_session(
            self.mismatch_id,
            provider="OpenAI",
            message="旧 provider 线程",
            cwd="/tmp/project-mismatch",
            start_ms=1713600000000,
            end_ms=1713600400000,
        )
        self.write_session(
            self.missing_id,
            provider="OpenAI",
            message="缺失数据库线程",
            cwd="/tmp/project-missing",
            start_ms=1713600000000,
            end_ms=1713600300000,
        )

    def _write_index(self) -> None:
        entries = [
            {
                "id": self.healthy_id,
                "thread_name": "健康线程",
                "updated_at": isoformat_from_ms(1713600500000),
            },
            {
                "id": self.orphan_id,
                "thread_name": "孤儿线程",
                "updated_at": isoformat_from_ms(1713600200000),
            },
        ]
        content = "\n".join(json.dumps(item, ensure_ascii=False) for item in entries) + "\n"
        self.index_path.write_text(content, encoding="utf-8")

    def session_path(self, thread_id: str) -> Path:
        return self.sessions_root / "2026" / "04" / "20" / f"rollout-2026-04-20T00-00-00-{thread_id}.jsonl"

    def write_session(
        self,
        thread_id: str,
        *,
        provider: str,
        message: str,
        cwd: str,
        start_ms: int,
        end_ms: int,
    ) -> None:
        path = self.session_path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            {
                "timestamp": isoformat_from_ms(start_ms),
                "type": "session_meta",
                "payload": {
                    "id": thread_id,
                    "timestamp": isoformat_from_ms(start_ms),
                    "cwd": cwd,
                    "originator": "codex-tui",
                    "cli_version": "0.121.0",
                    "source": "cli",
                    "model_provider": provider,
                },
            },
            {
                "timestamp": isoformat_from_ms(start_ms + 1000),
                "type": "turn_context",
                "payload": {
                    "turn_id": f"{thread_id}-turn",
                    "cwd": cwd,
                    "approval_policy": "on-request",
                    "sandbox_policy": {"type": "workspace-write"},
                    "model": "gpt-5.4",
                    "effort": "high",
                },
            },
            {
                "timestamp": isoformat_from_ms(start_ms + 2000),
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": message,
                    "images": [],
                    "local_images": [],
                    "text_elements": [],
                },
            },
            {
                "timestamp": isoformat_from_ms(end_ms),
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": f"{thread_id}-turn",
                    "completed_at": end_ms // 1000,
                },
            },
        ]
        path.write_text(
            "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
            encoding="utf-8",
        )


class RecoveryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.fixture = RecoveryFixture(Path(self.temp_dir.name) / ".codex")
        self.fixture.build()

    def test_scan_reports_expected_anomalies(self) -> None:
        report = scan_root(self.fixture.root)

        self.assertEqual(report.target_provider, "crs")
        self.assertEqual(report.summary["session_count"], 3)
        self.assertEqual(report.summary["thread_count"], 4)
        self.assertEqual(report.summary["session_index_count"], 2)
        self.assertTrue(report.summary["index_out_of_sync"])

        candidate_map = {item.thread_id: set(item.issue_types) for item in report.candidates}
        self.assertEqual(candidate_map[self.fixture.mismatch_id], {"provider_mismatch", "stale_session_index"})
        self.assertEqual(
            candidate_map[self.fixture.missing_id],
            {"missing_thread_row", "provider_mismatch", "stale_session_index"},
        )
        self.assertNotIn(self.fixture.healthy_id, candidate_map)

        orphan_ids = {item.thread_id for item in report.orphan_threads}
        self.assertEqual(orphan_ids, {self.fixture.orphan_id})

    def test_repair_dry_run_does_not_modify_files(self) -> None:
        original_db_provider = self._thread_provider(self.fixture.mismatch_id)
        original_missing_exists = self._thread_exists(self.fixture.missing_id)
        original_session_line = self.fixture.session_path(self.fixture.mismatch_id).read_text(encoding="utf-8").splitlines()[0]
        original_index = self.fixture.index_path.read_text(encoding="utf-8")

        result = repair_root(self.fixture.root, select_all=True, dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertEqual(self._thread_provider(self.fixture.mismatch_id), original_db_provider)
        self.assertEqual(self._thread_exists(self.fixture.missing_id), original_missing_exists)
        self.assertEqual(
            self.fixture.session_path(self.fixture.mismatch_id).read_text(encoding="utf-8").splitlines()[0],
            original_session_line,
        )
        self.assertEqual(self.fixture.index_path.read_text(encoding="utf-8"), original_index)

    def test_repair_updates_provider_rebuilds_index_and_inserts_missing_threads(self) -> None:
        result = repair_root(self.fixture.root, select_all=True)

        self.assertFalse(result.dry_run)
        self.assertTrue(result.index_rebuilt)
        self.assertTrue(result.backup_dir.is_dir())
        self.assertTrue((result.backup_dir / "manifest.json").is_file())
        self.assertEqual(self._thread_provider(self.fixture.mismatch_id), "crs")
        self.assertEqual(self._thread_provider(self.fixture.missing_id), "crs")

        session_meta = json.loads(
            self.fixture.session_path(self.fixture.mismatch_id).read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(session_meta["payload"]["model_provider"], "crs")

        index_entries = [
            json.loads(line)
            for line in self.fixture.index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(
            [entry["id"] for entry in index_entries],
            [self.fixture.healthy_id, self.fixture.mismatch_id, self.fixture.missing_id],
        )

    def test_repair_with_cwd_filter_preserves_other_index_entries(self) -> None:
        result = repair_root(
            self.fixture.root,
            select_all=True,
            cwd_filter="/tmp/project-mismatch",
        )

        self.assertEqual(result.selected_thread_ids, [self.fixture.mismatch_id])
        index_entries = [
            json.loads(line)
            for line in self.fixture.index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(
            [entry["id"] for entry in index_entries],
            [self.fixture.healthy_id, self.fixture.mismatch_id, self.fixture.missing_id],
        )

    def test_repair_rebuilds_index_even_without_candidates(self) -> None:
        repair_root(self.fixture.root, select_all=True)
        dangling_entry = {
            "id": "dangling-only-index",
            "thread_name": "脏索引条目",
            "updated_at": isoformat_from_ms(1713600600000),
        }
        with self.fixture.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dangling_entry, ensure_ascii=False) + "\n")

        result = repair_root(self.fixture.root)

        self.assertEqual(result.selected_thread_ids, [])
        self.assertTrue(result.index_rebuilt)
        index_entries = [
            json.loads(line)
            for line in self.fixture.index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(
            [entry["id"] for entry in index_entries],
            [self.fixture.healthy_id, self.fixture.mismatch_id, self.fixture.missing_id],
        )

    def test_repair_rolls_back_when_session_write_fails(self) -> None:
        original_db_provider = self._thread_provider(self.fixture.mismatch_id)
        original_session = self.fixture.session_path(self.fixture.mismatch_id).read_text(encoding="utf-8")
        original_index = self.fixture.index_path.read_text(encoding="utf-8")

        with mock.patch("codex_history_recover.repair.atomic_write_text", side_effect=RuntimeError("boom")):
            with self.assertRaises(RepairError):
                repair_root(self.fixture.root, select_all=True)

        self.assertEqual(self._thread_provider(self.fixture.mismatch_id), original_db_provider)
        self.assertEqual(self.fixture.session_path(self.fixture.mismatch_id).read_text(encoding="utf-8"), original_session)
        self.assertEqual(self.fixture.index_path.read_text(encoding="utf-8"), original_index)

    def test_cli_scan_json_outputs_machine_readable_summary(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(["scan", "--root", str(self.fixture.root), "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["target_provider"], "crs")
        self.assertEqual(payload["summary"]["candidate_count"], 2)
        self.assertEqual(payload["summary"]["orphan_count"], 1)

    def _thread_provider(self, thread_id: str) -> str | None:
        conn = sqlite3.connect(self.fixture.db_path)
        row = conn.execute("SELECT model_provider FROM threads WHERE id = ?", (thread_id,)).fetchone()
        conn.close()
        return None if row is None else row[0]

    def _thread_exists(self, thread_id: str) -> bool:
        return self._thread_provider(thread_id) is not None


if __name__ == "__main__":
    unittest.main()
