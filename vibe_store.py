"""Persistent Vibe preset storage and pending setup state."""

from __future__ import annotations

import json
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VIBE_FILE = Path("config") / "plugins" / "nai_drawer" / "vibe_presets.toml"
_PENDING_FILE = Path("data") / "nai_drawer" / "pending_vibe.json"


class VibeStoreError(RuntimeError):
    """Raised when Vibe preset state is invalid."""


@dataclass(frozen=True)
class VibePreset:
    """Saved Vibe cache preset."""

    name: str
    cache_id: str
    reference_strength: float
    information_extracted: float


@dataclass(frozen=True)
class PendingVibeSetup:
    """Pending Vibe setup waiting for numeric parameters."""

    name: str
    image_base64: str
    stream_id: str
    sender_id: str
    created_at: float


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _ensure_vibe_file(path: Path = VIBE_FILE) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Vibe 预设配置。\n"
        "# 当前启用的 Vibe 预设；空字符串表示关闭。\n"
        'current = ""\n\n'
        "[presets]\n"
        '# 示例：清新画风 = { cache_id = "xxxx", reference_strength = 0.6, information_extracted = 0.7 }\n',
        encoding="utf-8",
    )


def _load_raw(path: Path = VIBE_FILE) -> dict[str, Any]:
    _ensure_vibe_file(path)
    with path.open("rb") as file:
        data = tomllib.load(file)
    return data if isinstance(data, dict) else {}


def _write(current: str, presets: dict[str, VibePreset], path: Path = VIBE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Vibe 预设配置。",
        "# 当前启用的 Vibe 预设；空字符串表示关闭。",
        f'current = "{_escape(current)}"',
        "",
        "[presets]",
    ]
    for name in sorted(presets):
        preset = presets[name]
        lines.append(
            f'"{_escape(name)}" = '
            "{ "
            f'cache_id = "{_escape(preset.cache_id)}", '
            f"reference_strength = {preset.reference_strength}, "
            f"information_extracted = {preset.information_extracted} "
            "}"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _load_state(path: Path = VIBE_FILE) -> tuple[str, dict[str, VibePreset]]:
    data = _load_raw(path)
    current = str(data.get("current", "") or "").strip()
    raw_presets = data.get("presets", {})
    presets: dict[str, VibePreset] = {}
    if isinstance(raw_presets, dict):
        for name, raw in raw_presets.items():
            if not isinstance(raw, dict):
                continue
            cache_id = str(raw.get("cache_id", "") or "").strip()
            if not cache_id:
                continue
            presets[str(name)] = VibePreset(
                name=str(name),
                cache_id=cache_id,
                reference_strength=float(raw.get("reference_strength", 0.6)),
                information_extracted=float(raw.get("information_extracted", 0.7)),
            )
    if current and current not in presets:
        current = ""
    return current, presets


def _validate_ratio(value: float, label: str) -> float:
    if value < 0.01 or value > 1.0:
        raise VibeStoreError(f"{label} 必须在 0.01 到 1 之间。")
    return value


def save_vibe_preset(
    name: str,
    cache_id: str,
    reference_strength: float,
    information_extracted: float,
    path: Path = VIBE_FILE,
) -> VibePreset:
    preset_name = name.strip()
    if not preset_name:
        raise VibeStoreError("Vibe 预设名称不能为空。")
    cache = cache_id.strip()
    if not cache:
        raise VibeStoreError("Vibe cache_id 不能为空。")
    preset = VibePreset(
        name=preset_name,
        cache_id=cache,
        reference_strength=_validate_ratio(reference_strength, "Reference Strength"),
        information_extracted=_validate_ratio(information_extracted, "Information Extracted"),
    )
    _current, presets = _load_state(path)
    presets[preset_name] = preset
    _write(preset_name, presets, path)
    return preset


def load_vibe_preset(name: str, path: Path = VIBE_FILE) -> VibePreset:
    preset_name = name.strip()
    _current, presets = _load_state(path)
    if preset_name not in presets:
        raise VibeStoreError(f"未找到 Vibe 预设：{preset_name}")
    _write(preset_name, presets, path)
    return presets[preset_name]


def disable_vibe(path: Path = VIBE_FILE) -> None:
    _current, presets = _load_state(path)
    _write("", presets, path)


def get_current_vibe(path: Path = VIBE_FILE) -> VibePreset | None:
    current, presets = _load_state(path)
    if not current:
        return None
    return presets.get(current)


def build_current_vibe_payload(path: Path = VIBE_FILE) -> dict[str, Any] | None:
    preset = get_current_vibe(path)
    if preset is None:
        return None
    return {
        "controlnet": {
            "strength": 1.0,
            "images": [
                {
                    "cache_id": preset.cache_id,
                    "strength": preset.reference_strength,
                }
            ],
        }
    }


def _pending_key(stream_id: str, sender_id: str) -> str:
    return f"{stream_id}:{sender_id}"


def set_pending_vibe(setup: PendingVibeSetup, path: Path = _PENDING_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data[_pending_key(setup.stream_id, setup.sender_id)] = {
        "name": setup.name,
        "image_base64": setup.image_base64,
        "stream_id": setup.stream_id,
        "sender_id": setup.sender_id,
        "created_at": setup.created_at,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pop_pending_vibe(stream_id: str, sender_id: str, path: Path = _PENDING_FILE) -> PendingVibeSetup | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    raw = data.pop(_pending_key(stream_id, sender_id), None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not isinstance(raw, dict):
        return None
    return PendingVibeSetup(
        name=str(raw.get("name", "")),
        image_base64=str(raw.get("image_base64", "")),
        stream_id=str(raw.get("stream_id", "")),
        sender_id=str(raw.get("sender_id", "")),
        created_at=float(raw.get("created_at", time.time())),
    )
