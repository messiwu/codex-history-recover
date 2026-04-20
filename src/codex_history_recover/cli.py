from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .inventory import scan_root
from .repair import RepairError, repair_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-history-recover", description="恢复 Codex 本地历史会话显示")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="扫描本地历史状态")
    add_common_arguments(scan_parser)

    repair_parser = subparsers.add_parser("repair", help="修复旧线程挂载并重建索引")
    add_common_arguments(repair_parser)
    repair_selection = repair_parser.add_mutually_exclusive_group()
    repair_selection.add_argument("--all", action="store_true", help="修复全部候选线程")
    repair_selection.add_argument("--thread", action="append", dest="threads", help="仅修复指定线程，可重复传入")
    repair_parser.add_argument("--dry-run", action="store_true", help="仅展示计划修改，不落盘")
    repair_parser.add_argument("--yes", action="store_true", help="跳过最终确认")
    return parser


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="Codex 本地数据目录，默认自动探测 ~/.codex 或 ~/.code")
    parser.add_argument("--provider", help="覆盖 config.toml 中的目标 model_provider")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--cwd", help="只处理指定工作目录下的线程")


def format_issue_line(index: int, item) -> str:
    issues = ",".join(item.issue_types)
    provider = item.db_model_provider or item.session_model_provider or "-"
    return f"{index:>2}. {item.thread_id} | {provider} -> {issues} | {item.title}"


def print_scan_report(report) -> None:
    print(f"数据目录: {report.root}")
    print(f"目标 provider: {report.target_provider}")
    print(
        "摘要:"
        f" sessions={report.summary['session_count']}"
        f" threads={report.summary['thread_count']}"
        f" index={report.summary['session_index_count']}"
        f" candidates={report.summary['candidate_count']}"
        f" orphans={report.summary['orphan_count']}"
    )
    if report.candidates:
        print("候选线程:")
        for index, item in enumerate(report.candidates, start=1):
            print(format_issue_line(index, item))
    else:
        print("候选线程: 无")
    if report.orphan_threads:
        print("孤儿线程:")
        for item in report.orphan_threads:
            print(f"- {item.thread_id} | {item.title}")


def print_repair_result(result) -> None:
    print(f"目标 provider: {result.target_provider}")
    print(f"选中线程数: {result.summary['selected_count']}")
    print(f"更新 provider: {result.summary['provider_update_count']}")
    print(f"补回 threads 行: {result.summary['insert_count']}")
    print(f"更新 session 文件: {result.summary['session_update_count']}")
    print(f"重建索引: {'是' if result.index_rebuilt else '否'}")
    if result.dry_run:
        print("本次为 dry-run，未写入任何文件。")
    elif result.backup_dir is not None:
        print(f"备份目录: {result.backup_dir}")


def prompt_for_selection(report) -> list[str]:
    if not report.candidates:
        return []
    print("候选线程列表:")
    for index, item in enumerate(report.candidates, start=1):
        print(format_issue_line(index, item))
    raw = input("输入 all 修复全部，或输入编号列表（如 1,3），输入 q 取消: ").strip()
    if raw.lower() in {"q", "quit", "exit"}:
        raise RepairError("已取消修复")
    if raw.lower() == "all":
        return [item.thread_id for item in report.candidates]

    selected_ids: list[str] = []
    indexes = {str(position): item.thread_id for position, item in enumerate(report.candidates, start=1)}
    for token in [part.strip() for part in raw.split(",") if part.strip()]:
        if token not in indexes:
            raise RepairError(f"无效编号: {token}")
        selected_ids.append(indexes[token])
    if not selected_ids:
        raise RepairError("未选择任何线程")
    return selected_ids


def confirm_or_raise(message: str) -> None:
    answer = input(f"{message} [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise RepairError("已取消修复")


def handle_scan(args: argparse.Namespace) -> int:
    report = scan_root(root=args.root, provider_override=args.provider, cwd_filter=args.cwd)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0
    print_scan_report(report)
    return 0


def handle_repair(args: argparse.Namespace) -> int:
    report = scan_root(root=args.root, provider_override=args.provider, cwd_filter=args.cwd)
    if not report.candidates and not report.summary["index_out_of_sync"]:
        payload = {
            "root": str(report.root),
            "target_provider": report.target_provider,
            "summary": {"selected_count": 0, "message": "没有需要修复的线程"},
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("没有需要修复的线程。")
        return 0

    if args.threads:
        selected_ids = args.threads
        select_all = False
    elif args.all:
        selected_ids = None
        select_all = True
    elif not report.candidates and report.summary["index_out_of_sync"]:
        selected_ids = []
        select_all = False
    else:
        selected_ids = prompt_for_selection(report)
        select_all = False

    if not args.dry_run and not args.yes:
        confirm_or_raise("确认执行修复吗？")

    result = repair_root(
        root=args.root,
        provider_override=args.provider,
        selected_thread_ids=selected_ids,
        select_all=select_all,
        dry_run=args.dry_run,
        cwd_filter=args.cwd,
    )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0
    print_repair_result(result)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            return handle_scan(args)
        return handle_repair(args)
    except (FileNotFoundError, RepairError, ValueError) as exc:
        print(f"错误: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
