"""绘图流程编排。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.send_api import send_image

from ..client import ImageDrawerError, convert_to_english_prompt, generate_image, validate_prompt
from ..config import NaiDrawerConfig
from ..constants import PROMPT_CONVERSION_SYSTEM, PROMPT_CONVERSION_SYSTEM_MULTI
from .preset_service import PresetServiceError, build_reference_payload

logger = get_logger("nai_drawer")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef]")
_LOCAL_TAGS_PATH = Path("data/nai_drawer/danbooru_tags.json")


def _normalize_prompt_tag(tag: str) -> str:
    """归一化单个 Danbooru tag 片段。"""
    normalized = tag.strip().strip("{}[]")
    return normalized.strip()


def _canonical_tag_key(tag: str) -> str:
    """将空格/下划线写法统一为可比较的 tag key。"""
    normalized = _normalize_prompt_tag(tag).lower()
    return re.sub(r"\s+", "_", normalized)


def _tag_matches_suppressed_character(tag: str, suppressed_tags: set[str]) -> bool:
    """判断 tag 是否命中需要移除的角色 tag。"""
    normalized = _canonical_tag_key(tag)
    for suppressed in suppressed_tags:
        suppressed_key = _canonical_tag_key(suppressed)
        if normalized == suppressed_key or normalized.startswith(f"{suppressed_key}_"):
            return True
    return False


def _load_character_tag_aliases() -> dict[str, set[str]]:
    """读取本地 Danbooru 角色 tag 与别名映射。"""
    if not _LOCAL_TAGS_PATH.exists():
        return {}
    try:
        data = json.loads(_LOCAL_TAGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("读取本地 Danbooru tag 数据失败，跳过角色 tag 抑制映射。")
        return {}

    alias_map: dict[str, set[str]] = {}
    for item in data.get("tags", []):
        if not isinstance(item, dict) or item.get("category") != "Character":
            continue
        tag = str(item.get("tag", "")).strip()
        if not tag:
            continue
        terms = {tag.lower(), tag.replace("_", " ").lower()}
        cn_name = str(item.get("cn_name", "")).strip()
        if cn_name:
            terms.update(part.strip().lower() for part in cn_name.split(",") if part.strip())
        aliases = item.get("aliases", [])
        if isinstance(aliases, list):
            terms.update(str(alias).strip().lower() for alias in aliases if str(alias).strip())
        for term in terms:
            alias_map.setdefault(term, set()).add(tag)
    return alias_map


def _character_suppressed_tags(config: NaiDrawerConfig, character_name: str) -> set[str]:
    """根据角色预设名与别名查找应移除的 Danbooru 角色 tag。"""
    if not character_name:
        return set()

    raw_characters = config.characters.model_dump()
    raw_entry = raw_characters.get(character_name)
    terms = {character_name.lower()}
    if isinstance(raw_entry, dict):
        terms.update(str(alias).strip().lower() for alias in raw_entry.get("alias_names", []) if str(alias).strip())

    alias_map = _load_character_tag_aliases()
    suppressed: set[str] = set()
    for term in terms:
        suppressed.update(alias_map.get(term, set()))
    return suppressed


def _suppress_character_tags(prompt: str, config: NaiDrawerConfig, reference_labels: list[str]) -> str:
    """命中角色参考时，从最终提示词移除对应角色 tag。"""
    if not config.tag_retriever.suppress_character_tags_when_reference:
        return prompt

    suppressed_tags: set[str] = set()
    for label in reference_labels:
        if not label.startswith("角色参考："):
            continue
        character_name = label.removeprefix("角色参考：").strip()
        suppressed_tags.update(_character_suppressed_tags(config, character_name))

    if not suppressed_tags:
        return prompt

    parts = [part.strip() for part in prompt.split(",")]
    kept_parts = [part for part in parts if part and not _tag_matches_suppressed_character(part, suppressed_tags)]
    suppressed_text = ", ".join(sorted(suppressed_tags))
    if len(kept_parts) != len([part for part in parts if part]):
        logger.info(f"角色参考已加载，移除冲突角色 tag：{suppressed_text}")
    return ", ".join(kept_parts)


def _apply_style_prefix(prompt: str, config: NaiDrawerConfig) -> tuple[str, str]:
    prefix = config.style.prefix.strip().rstrip(",")  # 去掉末尾多余逗号
    if not prefix:
        return prompt, ""
    # 确保画师串与内容之间有逗号分隔
    if prompt:
        return f"{prefix}, {prompt}", prefix
    return prefix, prefix


def _enrich_with_persona(text: str, config: NaiDrawerConfig) -> str:
    persona = config.bot.persona_prompt.strip()
    if not persona:
        return text
    if not any(keyword and keyword in text for keyword in config.bot.selfie_keywords):
        return text
    return f"{text}\n\nBOT 人物设定：{persona}"


async def prepare_prompt(
    config: NaiDrawerConfig,
    stream_id: str,
    text: str,
    multi_mode: bool = False,
    raw_tags_mode: bool = False,
) -> tuple[str, dict[str, Any]]:
    """必要时转换自然语言，并返回英文 prompt 与多人场景附加参数。

    Args:
        config: 插件配置
        stream_id: 聊天流 ID
        text: 自然语言描述或纯英文 Danbooru tags
        multi_mode: 是否为多人模式；多人模式使用多人专用系统提示词
        raw_tags_mode: 是否跳过翻译模型，直接使用用户输入的英文 tags
    """

    if raw_tags_mode:
        prompt = text.strip()
        if not prompt:
            raise ImageDrawerError("英文 tag 不能为空。")
        validate_prompt(prompt)
        logger.info("收到，使用纯英文 tag 直通模式，跳过提示词转换。")
        return prompt, {}

    prompt_text = _enrich_with_persona(text, config)

    if not _CJK_RE.search(prompt_text):
        return prompt_text, {}

    system_prompt = PROMPT_CONVERSION_SYSTEM_MULTI if multi_mode else PROMPT_CONVERSION_SYSTEM

    # 破甲词追加到系统提示词末尾
    prompt_prefix = config.prompt.prompt_prefix.strip()
    if prompt_prefix:
        system_prompt = f"{system_prompt}\n\n{prompt_prefix}"

    logger.info("收到，开始转换提示词。" + (" [多人模式]" if multi_mode else ""))
    result = await convert_to_english_prompt(prompt_text, config, system_prompt=system_prompt)
    logger.info(f"提示词转换完成：{result.prompt}")
    if result.extra_payload:
        logger.info(f"多人场景附加参数：{result.extra_payload}")
    return result.prompt, result.extra_payload


async def send_draw_result(
    config: NaiDrawerConfig,
    stream_id: str,
    prompt: str,
    extra_payload: dict[str, Any] | None = None,
    reference_labels: list[str] | None = None,
    vibe_active: bool = False,
) -> tuple[bool, str]:
    """生成图片并发送到当前聊天。"""

    payload: dict[str, Any] = dict(extra_payload or {})

    # Vibe 激活且配置了跳过画风前缀时，不应用 prefix
    skip_prefix = vibe_active and config.style.skip_with_vibe
    if skip_prefix:
        final_prompt, style_prefix = prompt, ""
    else:
        final_prompt, style_prefix = _apply_style_prefix(prompt, config)

    if style_prefix:
        logger.info(f"已应用画风前缀：{style_prefix}")
    logger.info(f"最终绘图提示词：{final_prompt}")

    try:
        for label in reference_labels or []:
            logger.info(f"已应用{label}")
        if style_prefix:
            logger.info("已应用配置中的画风前缀。")
        logger.info("收到，开始绘图。")
        result = await generate_image(final_prompt, config, extra_payload=payload)
    except (PresetServiceError, ImageDrawerError) as exc:
        message = str(exc)
        logger.error(f"绘图失败：{message}")
        return False, message
    except Exception as exc:
        logger.error(f"绘图异常：{exc}", exc_info=True)
        return False, "绘图失败：插件内部异常，请查看日志。"

    image_sent = await send_image(
        result.image_base64,
        stream_id=stream_id,
        processed_plain_text="[绘图结果]",
    )
    if not image_sent:
        logger.error("图片已生成，但发送失败。")
        return False, "图片已生成，但发送失败。"

    if result.seeds:
        seed_text = ", ".join(str(seed) for seed in result.seeds)
        logger.info(f"seed: {seed_text}")

    return True, "image generated"


async def draw_from_natural_language(
    config: NaiDrawerConfig,
    stream_id: str,
    text: str,
    original_text: str = "",
    multi_mode: bool = False,
    raw_tags_mode: bool = False,
) -> tuple[bool, str]:
    """执行完整的绘图流程（Command 和 Action 共用）。

    Args:
        config: 插件配置
        stream_id: 聊天流 ID
        text: 自然语言画面描述（可能是 LLM 重写后的）或纯英文 Danbooru tags
        original_text: 原始用户消息文本，用于角色名匹配；留空则使用 text
        multi_mode: 是否为多人模式；多人模式下不加载角色参考，使用多人专用提示词
        raw_tags_mode: 是否跳过翻译模型，直接使用用户输入的英文 tags
    """

    ref_text = original_text.strip() or text
    try:
        prompt, multi_payload = await prepare_prompt(
            config,
            stream_id,
            text,
            multi_mode=multi_mode,
            raw_tags_mode=raw_tags_mode,
        )
        # 多人模式下不加载角色参考
        if multi_mode:
            ref_payload, ref_labels = {}, []
            logger.info("多人模式：跳过角色参考加载")
        else:
            ref_payload, ref_labels = await build_reference_payload(config, ref_text)
            prompt = _suppress_character_tags(prompt, config, ref_labels)
        payload = {**multi_payload, **ref_payload}
    except (PresetServiceError, ImageDrawerError) as exc:
        message = str(exc)
        logger.error(f"提示词转换失败：{message}")
        return False, message
    except Exception as exc:
        logger.error(f"提示词转换异常：{exc}", exc_info=True)
        return False, "提示词转换失败：插件内部异常，请查看日志。"

    vibe_active = any("Vibe" in label for label in ref_labels)
    return await send_draw_result(
        config, stream_id, prompt,
        extra_payload=payload,
        reference_labels=ref_labels,
        vibe_active=vibe_active,
    )
