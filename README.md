# Codex History Recover

一个面向 macOS 的本地命令行小工具，用来修复 Codex CLI 因切换 `API/provider/登录方式` 导致的历史线程“明明还在本地，但 `resume` 看不到或 resume 不到”的问题。

## 解决什么问题

当你切换：

- API 通道
- `model_provider`
- 登录方式

Codex CLI 有时会出现一种很烦的状态：

- `sessions/` 里的历史会话文件还在
- `state_5.sqlite` 里也还有旧线程
- 但 `codex resume` 只能看到当前 provider 下的新线程，旧线程像“丢了”一样

这个工具的目标不是恢复消息内容，而是把本地历史线程重新挂回当前正在使用的 `model_provider`，让它们重新出现在 `resume` 列表里。

## 它会检查什么

工具会检查本地状态目录中的三类数据源：

- `state_5.sqlite` 里的 `threads` 表
- `sessions/**/*.jsonl` 会话文件
- `session_index.jsonl` 历史索引

## 核心能力

- 自动探测 `~/.codex`，不存在时回退到 `~/.code`
- 读取当前 `config.toml` 里的 `model_provider` 作为目标 provider
- 扫描 `provider_mismatch`、`missing_thread_row`、`stale_session_index`、`orphan_thread_row`
- 支持 `scan` 只读检查
- 支持 `repair --dry-run` 预演修改
- 修复时自动备份
- 同步更新数据库、session 文件，并全量重建索引
- 如果 session 文件存在但数据库缺行，会从 session 文件反推并补回 `threads` 记录

默认策略是：

- 自动探测 `~/.codex`，不存在时回退到 `~/.code`
- 读取当前 `config.toml` 里的 `model_provider` 作为目标 provider
- 先扫描，再选择修复
- 执行修复时自动创建备份
- 同步更新数据库、session 文件，并全量重建索引

## 运行要求

- macOS
- Python 3.12+
- 建议在执行修复前关闭 Codex CLI 或桌面端，避免 SQLite 被占用

## 快速开始

安装到当前环境：

```bash
python3 -m pip install .
```

开发态运行：

```bash
PYTHONPATH=src python3 -m codex_history_recover scan
```

安装后运行：

```bash
codex-history-recover scan
```

## 常用命令

先扫描：

```bash
PYTHONPATH=src python3 -m codex_history_recover scan
```

输出 JSON：

```bash
PYTHONPATH=src python3 -m codex_history_recover scan --json
```

全量修复：

```bash
PYTHONPATH=src python3 -m codex_history_recover repair --all --yes
```

仅预览修复内容：

```bash
PYTHONPATH=src python3 -m codex_history_recover repair --all --dry-run
```

只修复指定线程：

```bash
PYTHONPATH=src python3 -m codex_history_recover repair --thread <thread-id> --yes
```

指定根目录或目标 provider：

```bash
PYTHONPATH=src python3 -m codex_history_recover scan --root ~/.codex --provider crs
```

## 推荐使用顺序

先只读确认：

```bash
codex-history-recover scan --root ~/.codex --json
```

再做预演，不落盘：

```bash
codex-history-recover repair --root ~/.codex --all --dry-run
```

确认输出符合预期后，再执行真实修复：

```bash
codex-history-recover repair --root ~/.codex --all --yes
```

## 修复行为

- 如果 session 文件存在，但 `threads` 表里缺少该线程，会从 session 文件反推并补回记录
- 如果线程挂在旧 provider 上，会统一改写为当前目标 provider
- 如果 `session_index.jsonl` 缺失、过旧或排序不一致，会按最终线程视图重建
- 如果 `threads` 表里有记录，但 session 文件不存在，会标记为孤儿线程，只报告不自动修复

## 不会做什么

- 不会修改 `logs_2.sqlite`
- 不会伪造不存在的消息内容
- 不会自动修复 session 文件已经丢失的孤儿线程
- 不会绕过备份直接做不可逆写入

## 备份与回滚

每次真实修复都会在数据目录下创建：

```text
recovery-backups/<UTC时间戳>/
```

其中会包含：

- `state_5.sqlite`
- `state_5.sqlite-wal`
- `state_5.sqlite-shm`
- 本次会改动到的 session 文件备份
- 原始 `session_index.jsonl`
- `manifest.json`

如果修复过程中任一步失败，工具会自动回滚已改动的文件。

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

CI 会在 GitHub Actions 上自动执行：

- `python -m unittest discover -s tests -v`
- `python -m compileall src`

## 发布到 GitHub

建议最少准备这些文件后再公开仓库：

- `README.md`
- `LICENSE`
- `.gitignore`
- `CONTRIBUTING.md`
- `.github/workflows/ci.yml`

本仓库已经补齐了这些基础文件。你接下来只需要：

```bash
git init
git add .
git commit -m "feat: initial open source release"
git branch -M main
git remote add origin <你的 GitHub 仓库地址>
git push -u origin main
```

## 许可证

当前默认使用 `MIT` 许可证。
