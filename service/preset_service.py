"""预设解析与参考图准备。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.app.plugin_system.api.log_api import get_logger

from ..client import ImageDrawerError, create_vibe_cache, encode_image_file
from ..config import (
    CharacterPresetEntry,
    NaiDrawerConfig,
    VibePresetEntry,
)
from ..store import (
    PresetStoreError,
    get_vibe_cache,
    remember_vibe_cache,
)

logger = get_logger("nai_drawer")

_RESERVED_CHARACTER_KEYS = {"selfie"}
_RESERVED_VIBE_KEYS = {"active"}


class PresetServiceError(RuntimeError):
    """预设服务错误。"""


def _iter_character_presets(config: NaiDrawerConfig) -> dict[str, CharacterPresetEntry]:
    raw = config.characters.model_dump()
    presets: dict[str, CharacterPresetEntry] = {}
    for name, data in raw.items():
        if name in _RESERVED_CHARACTER_KEYS or not isinstance(data, dict):
            continue
        entry = CharacterPresetEntry.model_validate(data)
        if entry.enabled and entry.image_path.strip():
            presets[name] = entry
    return presets


def _iter_vibe_presets(config: NaiDrawerConfig) -> dict[str, VibePresetEntry]:
    raw = config.vibes.model_dump()
    presets: dict[str, VibePresetEntry] = {}
    for name, data in raw.items():
        if name in _RESERVED_VIBE_KEYS or not isinstance(data, dict):
            continue
        entry = VibePresetEntry.model_validate(data)
        if entry.enabled and entry.image_path.strip():
            presets[name] = entry
    return presets


def _find_character_name_in_text(user_text: str, characters: dict[str, CharacterPresetEntry]) -> str:
    """从用户文本中匹配角色预设名或别名。"""
    if not user_text:
        return ""
    normalized_text = user_text.lower()
    for name, entry in characters.items():
        if name and name.lower() in normalized_text:
            return name
        for alias in entry.alias_names:
            if alias and alias.lower() in normalized_text:
                return name
    return ""


def _is_selfie_request(user_text: str, config: NaiDrawerConfig) -> bool:
    """判断用户请求是否为自拍/你的照片类型的请求。"""
    if not user_text:
        return False
    normalized_text = user_text.lower()
    selfie_keywords = [keyword.lower() for keyword in config.bot.selfie_keywords if keyword]
    if any(keyword in normalized_text for keyword in selfie_keywords):
        return True

    selfie_nouns = ["照片", "自拍", "照", "写真", "photo", "picture", "portrait"]
    selfie_pronouns = ["你", "你的", "你给我", "给我你", "给我看你", "看看你", "看你"]
    if any(noun in normalized_text for noun in selfie_nouns) and any(pronoun in normalized_text for pronoun in selfie_pronouns):
        return True

    if any(noun in normalized_text for noun in selfie_nouns) and "我的" not in normalized_text and "我" not in normalized_text and "你" in normalized_text:
        return True

    return False


async def ensure_character_ready(name: str, entry: CharacterPresetEntry, config: NaiDrawerConfig) -> dict[str, Any]:
    """按配置路径读取角色参考图。"""

    source = Path(entry.image_path.strip())
    image = encode_image_file(source.as_posix())

    return {
        "character_references": [
            {
                "image": image,
                "type": entry.type,
                "fidelity": entry.fidelity,
                "strength": entry.strength,
            }
        ]
    }


async def ensure_vibe_ready(name: str, entry: VibePresetEntry, config: NaiDrawerConfig) -> dict[str, Any]:
    """确保 Vibe 已上传并取得 cache_id。"""

    source = Path(entry.image_path.strip())
    cached = get_vibe_cache(name)
    if cached and cached.source_path == source.as_posix():
        cache_id = cached.cache_id
    else:
        image = encode_image_file(source.as_posix())
        cache_id = await create_vibe_cache(
            image,
            entry.reference_strength,
            entry.information_extracted,
            config,
        )
        remember_vibe_cache(
            name,
            cache_id=cache_id,
            source_path=source,
            reference_strength=entry.reference_strength,
            information_extracted=entry.information_extracted,
        )

    return {
        "controlnet": {
            "strength": 1.0,
            "images": [
                {
                    "cache_id": cache_id,
                    "strength": entry.reference_strength,
                }
            ],
        }
    }


async def warm_up_presets(config: NaiDrawerConfig) -> None:
    """插件加载时预热需要服务端缓存的 Vibe 预设。"""

    vibes = _iter_vibe_presets(config)

    for name, entry in vibes.items():
        try:
            await ensure_vibe_ready(name, entry, config)
        except (ImageDrawerError, PresetStoreError):
            continue


async def build_reference_payload(config: NaiDrawerConfig, user_text: str) -> tuple[dict[str, Any], list[str]]:
    """根据配置构建角色参考与 Vibe 附加参数。

    角色参考加载优先级：
    1. 用户文本中包含角色预设名 → 自动加载该角色参考
    2. 自拍场景（命中 selfie_keywords）→ 加载 characters.selfie 指定的角色参考
    3. 以上均未命中 → 不加载角色参考

    角色参考与 Vibe 互斥：加载角色参考时跳过 Vibe。
    """

    labels: list[str] = []
    payload: dict[str, Any] = {}

    characters = _iter_character_presets(config)
    vibes = _iter_vibe_presets(config)

    # 优先级 1：用户文本中包含角色预设名或别名
    character_name = _find_character_name_in_text(user_text, characters)

    # 优先级 2：自拍场景加载 characters.selfie
    if not character_name:
        selfie = _is_selfie_request(user_text, config)
        if selfie:
            character_name = config.characters.selfie.strip()

    if character_name:
        if character_name not in characters:
            raise PresetServiceError(f"未找到角色预设：{character_name}")
        char_payload = await ensure_character_ready(character_name, characters[character_name], config)
        payload.update(char_payload)
        labels.append(f"角色参考：{character_name}")
        logger.info(f"已加载角色参考：{character_name} (type={characters[character_name].type}, fidelity={characters[character_name].fidelity}, strength={characters[character_name].strength})")
    else:
        logger.info("未加载任何角色参考")

    vibe_name = config.vibes.active.strip()
    if vibe_name and "character_references" not in payload:
        if vibe_name not in vibes:
            raise PresetServiceError(f"未找到 Vibe 预设：{vibe_name}")
        vibe_payload = await ensure_vibe_ready(vibe_name, vibes[vibe_name], config)
        payload.update(vibe_payload)
        labels.append(f"Vibe：{vibe_name}")
        logger.info(f"已加载 Vibe：{vibe_name} (reference_strength={vibes[vibe_name].reference_strength}, information_extracted={vibes[vibe_name].information_extracted})")
    elif vibe_name and "character_references" in payload:
        logger.info(f"已加载角色参考，跳过 Vibe：{vibe_name}")
    else:
        logger.info("未加载任何 Vibe")

    return payload, labels
