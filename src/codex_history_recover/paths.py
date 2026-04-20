from __future__ import annotations

from pathlib import Path
import tomllib


def detect_root(explicit_root: str | Path | None = None) -> Path:
    if explicit_root is not None:
        root = Path(explicit_root).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"指定的数据目录不存在: {root}")
        return root

    home = Path.home()
    for candidate in (home / ".codex", home / ".code"):
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError("未找到 Codex 本地数据目录，默认会检查 ~/.codex 和 ~/.code")


def load_config(root: Path) -> dict:
    config_path = root / "config.toml"
    if not config_path.is_file():
        return {}
    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def resolve_target_provider(root: Path, provider_override: str | None = None) -> str:
    if provider_override:
        return provider_override

    config = load_config(root)
    provider = config.get("model_provider")
    if isinstance(provider, str) and provider.strip():
        return provider
    raise ValueError("未能从 config.toml 读取 model_provider，请通过 --provider 显式指定")
