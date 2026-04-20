# v0.1.0 发布文案

## 中文版

`Codex History Recover` 是一个面向 macOS 的本地命令行工具，用来修复 Codex CLI 在切换 API 通道、`model_provider` 或登录方式后，旧历史线程仍然保存在本地，但无法通过 `codex resume` 正常显示的问题。

### 当前能力

- 扫描本地 `state_5.sqlite`、`sessions/**/*.jsonl`、`session_index.jsonl`
- 识别 `provider_mismatch`、`missing_thread_row`、`stale_session_index`、`orphan_thread_row`
- 将旧线程重新挂到当前 `model_provider`
- 从 session 文件补回缺失的 `threads` 记录
- 全量重建 `session_index.jsonl`
- 修复前自动备份，失败自动回滚
- 支持 `scan`、`repair`、`--dry-run`、`--json`

### 推荐使用顺序

先只读确认：

```bash
codex-history-recover scan --root ~/.codex --json
```

再做预演：

```bash
codex-history-recover repair --root ~/.codex --all --dry-run
```

确认输出符合预期后，再执行真实修复：

```bash
codex-history-recover repair --root ~/.codex --all --yes
```

### 验证

当前版本已通过：

- 单元测试
- 源码编译检查
- 本地可编辑安装验证
- 控制台命令入口验证

## English

`Codex History Recover` is a local macOS CLI tool that restores missing Codex CLI history after API channel, `model_provider`, or auth changes.

### What it does

- Scans `state_5.sqlite`, `sessions/**/*.jsonl`, and `session_index.jsonl`
- Detects provider mismatches and missing thread rows
- Reattaches old threads to the current `model_provider`
- Rebuilds `session_index.jsonl`
- Creates backups before real repair
- Supports `scan`, `repair`, `--dry-run`, and `--json`

### Safe workflow

```bash
codex-history-recover scan --root ~/.codex --json
codex-history-recover repair --root ~/.codex --all --dry-run
codex-history-recover repair --root ~/.codex --all --yes
```
