"""绘图流程编排。"""

from __future__ import annotations

import re
from typing import Any

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.send_api import send_image

from ..client import ImageDrawerError, convert_to_english_prompt, generate_image
from ..config import NaiDrawerConfig
from .preset_service import PresetServiceError, build_reference_payload

logger = get_logger("nai_drawer")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef]")


def _apply_style_prefix(prompt: str, config: NaiDrawerConfig) -> tuple[str, str]:
    prefix = config.style.prefix.strip()
    if not prefix:
        return prompt, ""
    return f"{prefix}{prompt}", prefix


def _enrich_with_persona(text: str, config: NaiDrawerConfig) -> str:
    persona = config.bot.persona_prompt.strip()
    if not persona:
        return text
    if not any(keyword and keyword in text for keyword in config.bot.selfie_keywords):
        return text
    return f"{text}\n\nBOT 人物设定：{persona}"


async def prepare_prompt(config: NaiDrawerConfig, stream_id: str, text: str) -> tuple[str, dict[str, Any]]:
    """必要时转换自然语言，并返回英文 prompt 与多人场景附加参数。"""

    prompt_text = _enrich_with_persona(text, config)
    if not _CJK_RE.search(prompt_text):
        return prompt_text, {}

    logger.info("收到，开始转换提示词。")
    result = await convert_to_english_prompt(prompt_text, config)
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
    final_prompt, style_prefix = ("", "") if skip_prefix else _apply_style_prefix(prompt, config)

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
) -> tuple[bool, str]:
    """执行完整的绘图流程（Command 和 Action 共用）。

    Args:
        config: 插件配置
        stream_id: 聊天流 ID
        text: 自然语言画面描述（可能是 LLM 重写后的）
        original_text: 原始用户消息文本，用于角色名匹配；留空则使用 text
    """

    ref_text = original_text.strip() or text
    try:
        prompt, multi_payload = await prepare_prompt(config, stream_id, text)
        ref_payload, ref_labels = await build_reference_payload(config, ref_text)
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
