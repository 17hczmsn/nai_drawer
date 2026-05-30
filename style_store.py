"""Persistent style preset storage."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


STYLE_FILE = Path("config") / "plugins" / "nai_drawer" / "styles.toml"
_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")


class StyleStoreError(RuntimeError):
    """Raised when style storage cannot fulfill a request."""


@dataclass(frozen=True)
class StyleState:
    """Loaded style state."""

    current: str
    styles: dict[str, str]


def _escape_toml_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _validate_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise StyleStoreError("画风名称不能为空。")
    if not _VALID_NAME_RE.fullmatch(normalized):
        raise StyleStoreError("画风名称只能包含中文、英文、数字、下划线或短横线。")
    return normalized


def _ensure_store_exists(path: Path = STYLE_FILE) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# NAI Drawer style presets.\n"
        "# Edit current to switch the loaded style manually.\n"
        'current = ""\n\n'
        "[styles]\n"
        '# example = "masterpiece, best quality, anime style, "\n',
        encoding="utf-8",
    )


def load_styles(path: Path = STYLE_FILE) -> StyleState:
    """Load style presets from the TOML file."""

    _ensure_store_exists(path)
    with path.open("rb") as file:
        data = tomllib.load(file)

    raw_current = data.get("current", "")
    raw_styles = data.get("styles", {})

    current = raw_current if isinstance(raw_current, str) else ""
    styles = {
        str(name): value
        for name, value in raw_styles.items()
        if isinstance(value, str)
    } if isinstance(raw_styles, dict) else {}

    if current and current not in styles:
        current = ""

    return StyleState(current=current, styles=styles)


def save_styles(state: StyleState, path: Path = STYLE_FILE) -> None:
    """Write style presets to the TOML file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# NAI Drawer style presets.",
        "# Edit current to switch the loaded style manually.",
        f'current = "{_escape_toml_string(state.current)}"',
        "",
        "[styles]",
    ]
    for name in sorted(state.styles):
        lines.append(f'"{_escape_toml_string(name)}" = "{_escape_toml_string(state.styles[name])}"')
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def save_style(name: str, tags: str, path: Path = STYLE_FILE) -> StyleState:
    """Save or replace a named style preset."""

    normalized_name = _validate_name(name)
    if not tags.strip():
        raise StyleStoreError("画风词条不能为空。用法：/保存画风 名称 画风词条")

    state = load_styles(path)
    styles = dict(state.styles)
    styles[normalized_name] = tags
    new_state = StyleState(current=state.current, styles=styles)
    save_styles(new_state, path)
    return new_state


def load_style(name: str, path: Path = STYLE_FILE) -> str:
    """Set the named style as current and return its tags."""

    normalized_name = _validate_name(name)
    state = load_styles(path)
    if normalized_name not in state.styles:
        raise StyleStoreError(f"未找到画风：{normalized_name}")
    save_styles(StyleState(current=normalized_name, styles=state.styles), path)
    return state.styles[normalized_name]


def save_current_as(name: str, path: Path = STYLE_FILE) -> StyleState:
    """Save the current loaded style under a new name."""

    normalized_name = _validate_name(name)
    state = load_styles(path)
    if not state.current:
        raise StyleStoreError("当前没有已加载画风，无法另存。")
    current_tags = state.styles.get(state.current, "")
    if not current_tags:
        raise StyleStoreError("当前画风词条为空，无法另存。")
    styles = dict(state.styles)
    styles[normalized_name] = current_tags
    new_state = StyleState(current=normalized_name, styles=styles)
    save_styles(new_state, path)
    return new_state


def apply_current_style(prompt: str, path: Path = STYLE_FILE) -> tuple[str, str]:
    """Prefix the prompt with the current style tags when one is loaded."""

    state = load_styles(path)
    if not state.current:
        return prompt, ""
    tags = state.styles.get(state.current, "")
    if not tags:
        return prompt, ""
    return f"{tags}{prompt}", state.current
