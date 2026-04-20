# 更新日志

## v0.1.0 - 2026-04-20

首个开源版本。

### 新增

- 新增 `scan` 命令，用于扫描本地 Codex 历史状态
- 新增 `repair` 命令，用于修复旧线程的 provider 挂载并重建索引
- 支持自动探测 `~/.codex` 和 `~/.code`
- 支持从 `config.toml` 读取当前目标 `model_provider`
- 支持检测 `provider_mismatch`、`missing_thread_row`、`stale_session_index`、`orphan_thread_row`
- 支持 `--dry-run` 预演模式
- 支持 `--json` 输出
- 支持从 session 文件补回缺失的 `threads` 行

### 安全性

- 真实修复前自动备份数据库、session 文件和索引文件
- 修复失败时自动回滚
- 不自动修复 session 文件已经丢失的孤儿线程
- 不改写 `logs_2.sqlite`

### 工程化

- 增加单元测试
- 增加 GitHub Actions CI
- 增加 `README.md`
- 增加 `CONTRIBUTING.md`
- 增加 `LICENSE`

### 已修复的边界问题

- 修复 `--cwd` 局部修复时可能误伤其他索引条目的问题
- 修复只有索引脏、没有候选线程时无法单独重建索引的问题
- 修复短时间内连续修复时备份目录名冲突的问题
