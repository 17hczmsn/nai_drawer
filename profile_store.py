"""Bot profile settings for prompt conversion."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


PROFILE_FILE = Path("config") / "plugins" / "nai_drawer" / "profile.toml"
_PERSONA_PLACEHOLDER = "请在这里填写 BOT 的外貌、人设、服装等设定。"


class ProfileStoreError(RuntimeError):
    """Raised when profile settings are invalid."""


def _ensure_profile_exists(path: Path = PROFILE_FILE) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# BOT 人设配置。\n"
        "[bot]\n"
        "# BOT 人物设定；触发自拍相关自然语言时会追加给提示词转换模型。\n"
        f'persona_prompt = "{_PERSONA_PLACEHOLDER}"\n'
        "# 这些词出现时，只追加 BOT 人设；不会自动调用 /自拍角色 设置的角色参考。\n"
        'selfie_keywords = ["自拍", "发张自拍", "照片", "发张图"]\n',
        encoding="utf-8",
    )


def _load_profile(path: Path = PROFILE_FILE) -> dict[str, Any]:
    _ensure_profile_exists(path)
    with path.open("rb") as file:
        data = tomllib.load(file)
    return data if isinstance(data, dict) else {}


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def get_bot_persona(path: Path = PROFILE_FILE) -> str:
    data = _load_profile(path)
    bot = data.get("bot", {})
    if not isinstance(bot, dict):
        return ""
    persona = str(bot.get("persona_prompt", "")).strip()
    if persona == _PERSONA_PLACEHOLDER:
        return ""
    return persona


def should_use_selfie_reference(text: str, path: Path = PROFILE_FILE) -> bool:
    data = _load_profile(path)
    bot = data.get("bot", {})
    if not isinstance(bot, dict):
        return False
    keywords = _as_string_list(bot.get("selfie_keywords", []))
    return any(keyword and keyword in text for keyword in keywords)


def enrich_request_with_persona(text: str, path: Path = PROFILE_FILE) -> str:
    """Append bot persona for selfie-like natural-language requests."""

    persona = get_bot_persona(path)
    if not persona or not should_use_selfie_reference(text, path):
        return text
    return f"{text}\n\nBOT 人物设定：{persona}"
