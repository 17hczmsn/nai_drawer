"""自然语言转绘图提示词客户端。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.app.plugin_system.api import llm_api
from src.app.plugin_system.api.log_api import get_logger
from src.kernel.llm import LLMPayload, ROLE, Text

from ..config import NaiDrawerConfig
from ..constants import PROMPT_CONVERSION_SYSTEM
from .image_client import ImageDrawerError, validate_prompt

logger = get_logger("nai_drawer")

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_CHAR_LINE_RE = re.compile(r"^char(\d+)\s*:\s*(.+)$", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef]")
# 默认多人位置网格（5×5），按角色数分配
_DEFAULT_POSITIONS_2 = ["B3", "D3"]
_DEFAULT_POSITIONS_3 = ["A3", "C3", "E3"]
_DEFAULT_POSITIONS_4 = ["A2", "A4", "E2", "E4"]
_DEFAULT_POSITIONS_5 = ["A2", "A3", "A4", "E2", "E4"]
_DEFAULT_POSITIONS_6 = ["A2", "A3", "A4", "E2", "E3", "E4"]


def _get_default_positions(char_count: int) -> list[str]:
    """根据角色数量返回默认位置分配。"""
    mapping = {2: _DEFAULT_POSITIONS_2, 3: _DEFAULT_POSITIONS_3,
               4: _DEFAULT_POSITIONS_4, 5: _DEFAULT_POSITIONS_5,
               6: _DEFAULT_POSITIONS_6}
    return mapping.get(char_count, [f"C{i+1}" for i in range(char_count)])


@dataclass(frozen=True)
class PromptConversionResult:
    """提示词转换结果。"""

    prompt: str
    extra_payload: dict[str, Any]


def _resolve_model_set(config: NaiDrawerConfig):
    """按配置解析转换模型；留空则使用 model_tasks.sub_actor。"""

    model_name = config.prompt.model_name.strip()
    if model_name:
        return llm_api.get_model_set_by_name(
            model_name,
            temperature=config.prompt.temperature,
            max_tokens=config.prompt.max_tokens,
        )
    model_set = llm_api.get_model_set_by_task("sub_actor")
    if model_set and config.prompt.temperature is not None:
        for entry in model_set:
            entry["temperature"] = config.prompt.temperature
            entry["max_tokens"] = config.prompt.max_tokens
    return model_set


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """尝试从原始文本中提取 JSON 对象。"""
    text = raw.strip()
    block = _JSON_BLOCK_RE.search(text)
    if block:
        text = block.group(1).strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_json_multi(obj: dict[str, Any]) -> PromptConversionResult | None:
    """解析旧版 JSON 多人格式（mode:multi + characters 数组）。"""
    if obj.get("mode") != "multi" or not isinstance(obj.get("characters"), list):
        return None
    global_prompt = str(obj.get("global", "") or "").strip()
    characters = [item for item in obj["characters"] if isinstance(item, dict)]
    if not global_prompt or not characters:
        return None
    payload: dict[str, Any] = {"characters": characters, "use_coords": True}
    if "use_coords" in obj:
        payload["use_coords"] = bool(obj.get("use_coords"))
    if "use_order" in obj:
        payload["use_order"] = bool(obj.get("use_order"))
    return PromptConversionResult(prompt=global_prompt, extra_payload=payload)


def _parse_text_multi(lines: list[str]) -> PromptConversionResult | None:
    """解析 char1:/char2: 文本格式的多人场景。

    格式示例：
        2girls, indoors, soft lighting, year 2025,
        char1:1girl, blonde hair, blue eyes, source#hugging,
        char2:1girl, black hair, red eyes, target#hugging,
    """
    char_lines: list[tuple[int, str]] = []
    global_parts: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = _CHAR_LINE_RE.match(stripped)
        if match:
            idx = int(match.group(1))
            tags = match.group(2).strip().rstrip(",")
            char_lines.append((idx, tags))
        else:
            global_parts.append(stripped.rstrip(","))

    if len(char_lines) < 2:
        return None

    # 按 char 索引排序
    char_lines.sort(key=lambda x: x[0])
    global_prompt = ", ".join(global_parts)
    if not global_prompt:
        return None

    positions = _get_default_positions(len(char_lines))
    characters: list[dict[str, str]] = []
    for i, (_idx, tags) in enumerate(char_lines):
        characters.append({
            "prompt": tags,
            "negative_prompt": "",
            "position": positions[i] if i < len(positions) else f"C{i+1}",
        })

    return PromptConversionResult(
        prompt=global_prompt,
        extra_payload={"characters": characters, "use_coords": True},
    )


def _strip_cjk(text: str) -> str:
    """移除提示词中的 CJK 字符（安全网）。"""
    return _CJK_RE.sub("", text).strip()


def _parse_conversion_output(raw: str) -> PromptConversionResult:
    """解析模型输出，支持 JSON 多人、文本多人、单人三种格式。"""
    cleaned = raw.strip()
    if not cleaned:
        raise ImageDrawerError("提示词转换模型返回了空内容。")

    # 1. 尝试 JSON 多人格式（_extract_json_object 会处理代码块）
    obj = _extract_json_object(cleaned)
    if obj is not None:
        result = _parse_json_multi(obj)
        if result is not None:
            validate_prompt(result.prompt)
            return result
        # JSON 存在但不是多人格式 → 当作单人处理
        # 尝试从 JSON 中提取 prompt 字段
        if "prompt" in obj and isinstance(obj["prompt"], str):
            prompt = obj["prompt"].strip()
            if prompt:
                validate_prompt(prompt)
                return PromptConversionResult(prompt=prompt, extra_payload={})
        # JSON 无法识别，回退到文本解析

    # 2. 尝试 char1:/char2: 文本多人格式
    text_for_parsing = cleaned.strip("` \n\r\t")
    lines = text_for_parsing.split("\n")
    result = _parse_text_multi(lines)
    if result is not None:
        validate_prompt(result.prompt)
        return result

    # 3. 单人纯文本格式
    prompt = text_for_parsing
    # 安全网：如果包含 CJK 字符，尝试移除后继续
    if _CJK_RE.search(prompt):
        stripped = _strip_cjk(prompt)
        if stripped:
            prompt = stripped
        else:
            raise ImageDrawerError(
                "绘图接口要求英文提示词，不能包含中文、日文假名、韩文或全角字符。"
            )

    validate_prompt(prompt)
    return PromptConversionResult(prompt=prompt, extra_payload={})


async def convert_to_english_prompt(text: str, config: NaiDrawerConfig) -> PromptConversionResult:
    """把自然语言描述转换为英文绘图提示词，失败时自动重试。"""

    source = text.strip()
    if not source:
        raise ImageDrawerError("自然语言描述不能为空。")

    max_retries = config.prompt.max_retries
    last_error: Exception | None = None

    for attempt in range(1 + max_retries):
        model_set = _resolve_model_set(config)
        request = llm_api.create_llm_request(model_set, request_name="nai_drawer_prompt_convert")
        request.add_payload(LLMPayload(ROLE.SYSTEM, Text(PROMPT_CONVERSION_SYSTEM)))
        request.add_payload(LLMPayload(ROLE.USER, Text(source)))

        try:
            response = await request.send(stream=False)
            await response
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(f"提示词转换请求失败（第 {attempt + 1} 次），重试中：{exc}")
                continue
            raise ImageDrawerError(f"提示词转换请求失败（已重试 {max_retries} 次）：{exc}") from exc

        raw = (response.message or "").strip()
        try:
            return _parse_conversion_output(raw)
        except ImageDrawerError as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(f"提示词解析失败（第 {attempt + 1} 次），重试中：{exc}")
                continue
            raise ImageDrawerError(f"转换后的提示词不符合要求（已重试 {max_retries} 次）：{exc}") from exc

    # 理论上不会到达，但作为安全网
    raise ImageDrawerError(f"提示词转换失败（已重试 {max_retries} 次）：{last_error}") from last_error
