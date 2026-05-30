"""Persistent character reference presets."""

from __future__ import annotations

import base64
import json
import re
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CHARACTER_FILE = Path("config") / "plugins" / "nai_drawer" / "characters.toml"
CHARACTER_IMAGE_DIR = Path("config") / "plugins" / "nai_drawer" / "characters"
_PENDING_FILE = Path("data") / "nai_drawer" / "pending_character.json"


class CharacterStoreError(RuntimeError):
    """Raised when character reference state is invalid."""


@dataclass(frozen=True)
class CharacterPreset:
    """Saved character reference preset."""

    name: str
    image_path: str
    reference_type: str
    fidelity: float
    strength: float


@dataclass(frozen=True)
class PendingCharacterSetup:
    """Pending character setup state."""

    stage: str
    image_base64: str
    reference_type: str
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


def _ensure_character_file(path: Path = CHARACTER_FILE) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 角色参考预设配置。\n"
        '# selfie = "自拍时使用的角色预设名；为空表示 /自拍 不使用角色参考。"\n'
        'selfie = ""\n\n'
        "[presets]\n"
        '# 示例：看板娘 = { image_path = "config/plugins/nai_drawer/characters/example.png", type = "character&style", fidelity = 1.0, strength = 1.0 }\n',
        encoding="utf-8",
    )


def _load_raw(path: Path = CHARACTER_FILE) -> dict[str, Any]:
    _ensure_character_file(path)
    with path.open("rb") as file:
        data = tomllib.load(file)
    return data if isinstance(data, dict) else {}


def _load_state(path: Path = CHARACTER_FILE) -> tuple[str, dict[str, CharacterPreset]]:
    data = _load_raw(path)
    selfie = str(data.get("selfie", "") or "").strip()
    raw_presets = data.get("presets", {})
    presets: dict[str, CharacterPreset] = {}
    if isinstance(raw_presets, dict):
        for name, raw in raw_presets.items():
            if not isinstance(raw, dict):
                continue
            image_path = str(raw.get("image_path", "") or "").strip()
            reference_type = str(raw.get("type", "character&style") or "character&style").strip()
            if not image_path or reference_type not in {"character", "style", "character&style"}:
                continue
            presets[str(name)] = CharacterPreset(
                name=str(name),
                image_path=image_path,
                reference_type=reference_type,
                fidelity=float(raw.get("fidelity", 1.0)),
                strength=float(raw.get("strength", 1.0)),
            )
    if selfie and selfie not in presets:
        selfie = ""
    return selfie, presets


def _write(selfie: str, presets: dict[str, CharacterPreset], path: Path = CHARACTER_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 角色参考预设配置。",
        '# selfie = "自拍时使用的角色预设名；为空表示 /自拍 不使用角色参考。"',
        f'selfie = "{_escape(selfie)}"',
        "",
        "[presets]",
    ]
    for name in sorted(presets):
        preset = presets[name]
        lines.append(
            f'"{_escape(name)}" = '
            "{ "
            f'image_path = "{_escape(preset.image_path)}", '
            f'type = "{_escape(preset.reference_type)}", '
            f"fidelity = {preset.fidelity}, "
            f"strength = {preset.strength} "
            "}"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _decode_image(image_base64: str) -> bytes:
    data = image_base64.strip()
    if data.startswith("data:image/"):
        _header, separator, payload = data.partition(",")
        if not separator:
            raise CharacterStoreError("角色参考图 data URI 格式不正确。")
        data = payload
    try:
        return base64.b64decode(data, validate=True)
    except Exception as exc:
        raise CharacterStoreError("角色参考图不是有效的 base64 图片。") from exc


def _safe_file_stem(name: str) -> str:
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name, flags=re.UNICODE).strip("._")
    return stem or "character"


def save_character_preset(
    name: str,
    image_base64: str,
    reference_type: str,
    path: Path = CHARACTER_FILE,
    image_dir: Path = CHARACTER_IMAGE_DIR,
) -> CharacterPreset:
    preset_name = name.strip()
    if not preset_name:
        raise CharacterStoreError("角色预设名称不能为空。")
    if reference_type not in {"character", "style", "character&style"}:
        raise CharacterStoreError("角色参考方式无效。")

    image_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{int(time.time())}_{_safe_file_stem(preset_name)}.png"
    image_path = image_dir / file_name
    image_path.write_bytes(_decode_image(image_base64))

    selfie, presets = _load_state(path)
    preset = CharacterPreset(
        name=preset_name,
        image_path=image_path.as_posix(),
        reference_type=reference_type,
        fidelity=1.0,
        strength=1.0,
    )
    presets[preset_name] = preset
    _write(selfie, presets, path)
    return preset


def load_character_preset(name: str, path: Path = CHARACTER_FILE) -> CharacterPreset:
    preset_name = name.strip()
    _selfie, presets = _load_state(path)
    if preset_name not in presets:
        raise CharacterStoreError(f"未找到角色预设：{preset_name}")
    return presets[preset_name]


def set_selfie_character(name: str, path: Path = CHARACTER_FILE) -> CharacterPreset:
    preset = load_character_preset(name, path)
    _selfie, presets = _load_state(path)
    _write(preset.name, presets, path)
    return preset


def get_selfie_character(path: Path = CHARACTER_FILE) -> CharacterPreset | None:
    selfie, presets = _load_state(path)
    if not selfie:
        return None
    return presets.get(selfie)


def build_character_payload(preset: CharacterPreset) -> dict[str, Any]:
    image_path = Path(preset.image_path)
    if not image_path.exists():
        raise CharacterStoreError(f"角色参考图不存在：{preset.image_path}")
    image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return {
        "character_references": [
            {
                "image": image,
                "type": preset.reference_type,
                "fidelity": preset.fidelity,
                "strength": preset.strength,
            }
        ]
    }


def _pending_key(stream_id: str, sender_id: str) -> str:
    return f"{stream_id}:{sender_id}"


def set_pending_character(setup: PendingCharacterSetup, path: Path = _PENDING_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data[_pending_key(setup.stream_id, setup.sender_id)] = {
        "stage": setup.stage,
        "image_base64": setup.image_base64,
        "reference_type": setup.reference_type,
        "stream_id": setup.stream_id,
        "sender_id": setup.sender_id,
        "created_at": setup.created_at,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pop_pending_character(stream_id: str, sender_id: str, path: Path = _PENDING_FILE) -> PendingCharacterSetup | None:
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
    return PendingCharacterSetup(
        stage=str(raw.get("stage", "")),
        image_base64=str(raw.get("image_base64", "")),
        reference_type=str(raw.get("reference_type", "")),
        stream_id=str(raw.get("stream_id", "")),
        sender_id=str(raw.get("sender_id", "")),
        created_at=float(raw.get("created_at", time.time())),
    )
