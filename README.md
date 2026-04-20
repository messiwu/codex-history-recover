# Codex History Recover

一个面向 macOS 的本地命令行工具，用来修复 Codex CLI 在切换 `API`、`model_provider` 或登录方式后，本地历史明明还在，却无法通过 `codex resume` 正常显示的问题。

## 一句话说明

这个工具不恢复消息内容本身，而是修复 Codex 本地历史线程的挂载关系，让旧线程重新出现在当前 provider 下的 `resume` 列表里。

## 为什么会需要它

Codex CLI 的本地历史通常分散在几类状态里：

- `state_5.sqlite` 里的 `threads` 表
- `sessions/**/*.jsonl` 会话文件
- `session_index.jsonl` 历史索引

当你切换：

- API 通道
- `model_provider`
- 登录方式

这些状态之间可能会不同步，结果就是：

- 本地 session 文件还在
- 数据库里的旧线程还在
- 但 `codex resume` 看不到它们

这个工具就是专门处理这类“历史还在，本地显示丢了”的问题。

## 核心能力

- 自动探测 `~/.codex`，不存在时回退到 `~/.code`
- 读取当前 `config.toml` 里的 `model_provider` 作为目标 provider
- 扫描并识别以下问题：
  - `provider_mismatch`
  - `missing_thread_row`
  - `stale_session_index`
  - `orphan_thread_row`
- 支持只读扫描
- 支持 `--dry-run` 预演修复
- 修复前自动备份
- 同步更新数据库和 session 文件里的 provider
- 全量重建 `session_index.jsonl`
- 如果 session 文件还在、数据库缺行，可以从 session 文件补回 `threads` 记录

## 不会做什么

- 不会修改 `logs_2.sqlite`
- 不会伪造不存在的消息内容
- 不会自动修复 session 文件已经丢失的孤儿线程
- 不会绕过备份直接做不可逆写入

## 运行环境

- macOS
- Python 3.12+

建议在真实修复前先关闭 Codex CLI 或桌面端，避免 SQLite 被占用。

## 快速开始

安装：

```bash
python3 -m pip install .
```

安装后直接使用：

```bash
codex-history-recover scan
```

开发态运行：

```bash
PYTHONPATH=src python3 -m codex_history_recover scan
```

## 推荐使用顺序

先做只读扫描：

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

## 常用命令

扫描：

```bash
codex-history-recover scan
```

输出 JSON：

```bash
codex-history-recover scan --json
```

全量修复：

```bash
codex-history-recover repair --all --yes
```

仅预演：

```bash
codex-history-recover repair --all --dry-run
```

仅修复指定线程：

```bash
codex-history-recover repair --thread <thread-id> --yes
```

指定根目录或目标 provider：

```bash
codex-history-recover scan --root ~/.codex --provider crs
```

## 修复行为

- 如果线程挂在旧 provider 上，会统一改写为当前目标 provider
- 如果 `threads` 表里缺少该线程，会从 session 文件反推并补回
- 如果 `session_index.jsonl` 缺失、过旧或排序不一致，会按最终线程视图重建
- 如果 `threads` 表里有记录但 session 文件已经不存在，会标记为孤儿线程，只报告不自动修复

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

## 为什么可以放心先试

当前版本已经覆盖了这几类验证：

- 单元测试
- 源码编译检查
- 本地可编辑安装验证
- 控制台命令入口验证

CI 会在 GitHub Actions 上自动执行：

- `python -m unittest discover -s tests -v`
- `python -m compileall src`

## 仓库结构

```text
src/codex_history_recover/
  cli.py         命令行入口
  inventory.py   状态扫描与问题识别
  repair.py      修复、备份与回滚
  rebuild.py     索引重建
  paths.py       路径与配置解析
  models.py      数据结构
tests/
  test_recovery.py
```

## 本地开发

运行测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

源码编译检查：

```bash
python3 -m compileall src
```

## 发布到 GitHub

如果你本地已经有这个仓库，只需要创建一个空的 GitHub 仓库，然后执行：

```bash
git remote add origin <你的 GitHub 仓库地址>
git push -u origin main
```

创建 GitHub 仓库时建议：

- `Add a README file`：不选
- `Add .gitignore`：`None`
- `Choose a license`：不选

因为这些文件仓库里已经自带。

## 许可证

当前默认使用 `MIT` 许可证。
