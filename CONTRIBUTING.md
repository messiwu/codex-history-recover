# 贡献指南

欢迎提交 Issue 和 Pull Request。

## 开发环境

建议使用 Python 3.12 或更高版本。

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 本地验证

提交前至少运行：

```bash
.venv/bin/python -m unittest discover -s tests -v
python3 -m compileall src
```

如果你改了命令行行为，也请手动跑一下：

```bash
.venv/bin/codex-history-recover scan --help
```

## 提交建议

- 保持改动聚焦，不要混入无关重构
- 新增行为或修复缺陷时，请补测试
- 文档变更请同步更新 `README.md`
- 提交信息尽量清晰，例如：`fix: preserve unrelated index entries when filtering by cwd`
