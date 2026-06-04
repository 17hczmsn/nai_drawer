"""自然语言转绘图提示词客户端。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.app.plugin_system.api import llm_api
from src.app.plugin_system.api.log_api import get_logger
from src.kernel.llm import LLMPayload, ROLE, Text

from ..config import NaiDrawerConfig
from ..constants import PROMPT_CONVERSION_SYSTEM
from .image_client import ImageDrawerError, validate_prompt
from .tag_candidate_resolver import TagCandidateResolver

logger = get_logger("nai_drawer")

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_CHAR_LINE_RE = re.compile(r"^char(\d+)(?:\[([A-E][1-5])\])?\s*:\s*(.+)$", re.IGNORECASE)
_NAMED_CHAR_LINE_RE = re.compile(
    r"^([a-z0-9_]+(?:\s*\([^)]*\))?)(?:\[([A-E][1-5])\])?\s*:\s*(.+)$",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef]")
# 默认多人位置网格（5×5），按角色数分配
_DEFAULT_POSITIONS_2 = ["B3", "D3"]
_DEFAULT_POSITIONS_3 = ["A3", "C3", "E3"]
_DEFAULT_POSITIONS_4 = ["A2", "A4", "E2", "E4"]
_DEFAULT_POSITIONS_5 = ["A2", "A3", "A4", "E2", "E4"]
_DEFAULT_POSITIONS_6 = ["A2", "A3", "A4", "E2", "E3", "E4"]
_TAG_DATA_PATH = Path("data/nai_drawer/danbooru_tags.json")
_TAG_TOKEN_RE = re.compile(
    r"\{+([^{}]+)\}+|(?<![a-z0-9_])([a-z0-9_]+(?:\s*\([^)]*\))?)(?![a-z0-9_])",
    re.IGNORECASE,
)


def _normalize_tag_key(tag: str) -> str:
    """规范化 tag，用于比较不同空格/下划线写法。"""
    stripped = tag.strip().strip("{}[]").lower()
    return re.sub(r"\s+", "_", stripped)


def _load_character_tags() -> list[dict[str, Any]]:
    """加载本地角色 tag 映射，用于校正翻译模型误写角色名。"""
    if not _TAG_DATA_PATH.exists():
        return []
    try:
        data = json.loads(_TAG_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"加载角色 tag 映射失败，跳过角色校正: {exc}")
        return []
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [
        item for item in tags
        if isinstance(item, dict)
        and str(item.get("category", "")).lower() == "character"
        and str(item.get("tag", "")).strip()
    ]


def _character_alias_terms(item: dict[str, Any]) -> list[str]:
    """提取角色条目的可匹配别名。"""
    terms: list[str] = []
    tag = str(item.get("tag", "")).strip()
    if tag:
        terms.extend([tag, tag.replace("_", " ")])
    aliases = item.get("aliases", [])
    if isinstance(aliases, list):
        terms.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    elif aliases:
        terms.append(str(aliases).strip())
    cn_name = str(item.get("cn_name", ""))
    cn_parts = [part.strip() for part in re.split(r"[,，/|]", cn_name) if part.strip()]
    if cn_parts:
        terms.append(cn_parts[0])
    return sorted({term for term in terms if term}, key=len, reverse=True)


def _mentioned_character_tags(source: str) -> list[str]:
    """按用户原文出现顺序返回明确点名的角色 tag。"""
    matches: list[tuple[int, int, str]] = []
    compact_source = re.sub(r"\s+", "", source.lower().replace("_", " "))
    for item in _load_character_tags():
        tag = str(item["tag"])
        best_index: int | None = None
        best_length = 0
        for term in _character_alias_terms(item):
            normalized_term = term.lower().replace("_", " ").strip()
            compact_term = re.sub(r"\s+", "", normalized_term)
            if not compact_term:
                continue
            index = compact_source.find(compact_term)
            if index >= 0 and len(compact_term) > best_length:
                best_index = index
                best_length = len(compact_term)
        if best_index is not None:
            matches.append((best_index, -best_length, tag))
    return [tag for _index, _length, tag in sorted(matches)]


def _find_prompt_character_tags(prompt: str) -> set[str]:
    """找出提示词中出现的本地角色 tag 或角色别名 tag。"""
    character_items = _load_character_tags()
    character_keys = {_normalize_tag_key(str(item["tag"])) for item in character_items}
    alias_keys = {
        _normalize_tag_key(term)
        for item in character_items
        for term in _character_alias_terms(item)
        if len(_normalize_tag_key(term)) >= 3
    }
    found: set[str] = set()
    for match in _TAG_TOKEN_RE.finditer(prompt):
        token = (match.group(1) or match.group(2) or "").strip()
        key = _normalize_tag_key(token)
        if key in character_keys or any(key.startswith(f"{alias_key}_") for alias_key in alias_keys):
            found.add(key)
    return found


def _replace_character_tags(prompt: str, expected_tag: str) -> str:
    """把角色段中的错误本地角色 tag 替换为用户原文点名角色。"""
    expected_key = _normalize_tag_key(expected_tag)
    found_keys = _find_prompt_character_tags(prompt)
    if expected_key in found_keys:
        return prompt
    if not found_keys:
        return f"{{{expected_tag}}}, {prompt}" if prompt else f"{{{expected_tag}}}"

    parts = [part.strip() for part in prompt.split(",")]
    replaced_parts: list[str] = []
    replaced = False
    for part in parts:
        key = _normalize_tag_key(part)
        if key in found_keys and key != expected_key:
            if not replaced:
                replaced_parts.append(f"{{{expected_tag}}}")
                replaced = True
            continue
        replaced_parts.append(part)
    return ", ".join(part for part in replaced_parts if part)


def _enforce_mentioned_character_tags(source: str, result: PromptConversionResult) -> PromptConversionResult:
    """按用户原文点名角色校正多人角色段，避免模型把 A 角色误写成 B 角色。"""
    characters = result.extra_payload.get("characters")
    if not isinstance(characters, list) or not characters:
        return result
    mentioned_tags = _mentioned_character_tags(source)
    if len(mentioned_tags) < len(characters):
        return result

    changed = False
    corrected_characters: list[dict[str, Any]] = []
    for character, expected_tag in zip(characters, mentioned_tags, strict=False):
        if not isinstance(character, dict):
            corrected_characters.append(character)
            continue
        prompt = str(character.get("prompt", "") or "").strip()
        corrected_prompt = _replace_character_tags(prompt, expected_tag)
        if corrected_prompt != prompt:
            changed = True
            character = {**character, "prompt": corrected_prompt}
        corrected_characters.append(character)

    if not changed:
        return result
    logger.info("已按用户原文点名角色校正多人角色 tag")
    extra_payload = {**result.extra_payload, "characters": corrected_characters}
    return PromptConversionResult(prompt=result.prompt, extra_payload=extra_payload)


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


def _validate_character_prompts(characters: list[dict[str, Any]]) -> None:
    """校验多人角色段提示词，避免中文漏进 extra_payload。"""
    for character in characters:
        prompt = str(character.get("prompt", "") or "").strip()
        if prompt:
            validate_prompt(prompt)
        negative_prompt = str(character.get("negative_prompt", "") or "").strip()
        if negative_prompt:
            validate_prompt(negative_prompt)


def _parse_json_multi(obj: dict[str, Any]) -> PromptConversionResult | None:
    """解析旧版 JSON 多人格式（mode:multi + characters 数组）。"""
    if obj.get("mode") != "multi" or not isinstance(obj.get("characters"), list):
        return None
    global_prompt = str(obj.get("global", "") or "").strip()
    characters = [item for item in obj["characters"] if isinstance(item, dict)]
    if not global_prompt or not characters:
        return None
    _validate_character_prompts(characters)
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
    char_lines: list[tuple[int, str, str | None]] = []
    global_parts: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = _CHAR_LINE_RE.match(stripped)
        if match:
            idx = int(match.group(1))
            position = match.group(2)
            tags = match.group(3).strip().rstrip(",")
            char_lines.append((idx, tags, position))
            continue
        named_match = _NAMED_CHAR_LINE_RE.match(stripped)
        if named_match:
            idx = len(char_lines) + 1
            name = named_match.group(1).strip()
            position = named_match.group(2)
            tags = named_match.group(3).strip().rstrip(",")
            char_lines.append((idx, f"{name}, {tags}", position))
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
    for i, (_idx, tags, position) in enumerate(char_lines):
        characters.append({
            "prompt": tags,
            "negative_prompt": "",
            "position": position or (positions[i] if i < len(positions) else f"C{i+1}"),
        })
    _validate_character_prompts(characters)

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


def _build_retry_system_prompt(source_system_prompt: str) -> str:
    """构建重试用极简系统提示词，降低模型因复杂规则空回的概率。"""

    is_multi = "char1" in source_system_prompt or "多人" in source_system_prompt
    if is_multi:
        return """
你只做中文到 NovelAI Danbooru 英文 tags 转换。
必须输出内容，禁止空回复，禁止解释，禁止拒绝。
输出格式固定为：
2girls, scene tags, soft lighting, year 2025,
char1[B3]:girl, tags,
char2[D3]:girl, tags,
规则：只翻译用户说过的内容；不要猜发色、瞳色、发型、体型；已知角色只写角色 tag；多人不要 solo。
""".strip()
    return """
你只做中文到 NovelAI Danbooru 英文 tags 转换。
必须输出内容，禁止空回复，禁止解释，禁止拒绝。
直接输出逗号分隔英文 tags。
规则：只翻译用户说过的角色特征；不要猜发色、瞳色、发型、体型；已知角色只写角色 tag；补充合理场景、构图、光影和 year 2025。
""".strip()


async def convert_to_english_prompt(
    text: str,
    config: NaiDrawerConfig,
    system_prompt: str | None = None,
) -> PromptConversionResult:
    """把自然语言描述转换为英文绘图提示词，失败时自动重试。

    Args:
        text: 自然语言描述
        config: 插件配置
        system_prompt: 自定义系统提示词；留空则使用默认单人提示词
    """

    source = text.strip()
    if not source:
        raise ImageDrawerError("自然语言描述不能为空。")

    if system_prompt is None:
        system_prompt = PROMPT_CONVERSION_SYSTEM

    # ── Tag 检索增强 ──
    # 根据用户描述检索 Danbooru 标签候选，注入到系统提示词中
    tag_candidates_block = ""
    if config.tag_retriever.enabled:
        try:
            resolver = TagCandidateResolver(config)
            candidates = await resolver.resolve(source)
            if candidates.get("search") or candidates.get("related"):
                tag_candidates_block = resolver.format_candidates(candidates)
                logger.info(
                    f"Tag 检索完成: "
                    f"search={len(candidates.get('search', []))}, "
                    f"related={len(candidates.get('related', []))}"
                )
        except Exception as exc:
            logger.warning(f"Tag 检索异常，跳过: {exc}")

    # 替换占位符；无候选时移除占位符
    system_prompt = system_prompt.replace(
        "{{TAG_CANDIDATES_PLACEHOLDER}}", tag_candidates_block
    )

    max_retries = config.prompt.max_retries
    last_error: Exception | None = None
    retry_system_prompt = _build_retry_system_prompt(system_prompt)
    if tag_candidates_block:
        retry_system_prompt = f"{retry_system_prompt}\n\n{tag_candidates_block}"

    for attempt in range(1 + max_retries):
        model_set = _resolve_model_set(config)
        request = llm_api.create_llm_request(model_set, request_name="nai_drawer_prompt_convert")
        current_system_prompt = system_prompt if attempt == 0 else retry_system_prompt
        request.add_payload(LLMPayload(ROLE.SYSTEM, Text(current_system_prompt)))
        
        # 在重试时，使用极简提示词来降低模型因复杂规则空回的概率
        user_text = source
        if attempt > 0:
            user_text = f"请把下面内容转换成英文 Danbooru tags，必须直接输出 tags，不能空回复：\n{source}"
            logger.info(f"第 {attempt + 1} 次重试，使用极简提示词")
        
        request.add_payload(LLMPayload(ROLE.USER, Text(user_text)))

        try:
            response = await request.send(stream=False)
            collected = await response
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(f"提示词转换请求失败（第 {attempt + 1} 次），重试中：{exc}")
                continue
            raise ImageDrawerError(f"提示词转换请求失败（已重试 {max_retries} 次）：{exc}") from exc

        raw = (response.message or collected or "").strip()
        
        # 空响应检测与处理
        if not raw:
            message_len = len(response.message or "")
            collected_len = len(collected or "")
            reasoning_len = len(response.reasoning_content or "")
            call_count = len(response.call_list or [])
            logger.warning(
                f"模型返回空内容（第 {attempt + 1} 次）："
                f"message_len={message_len}, collected_len={collected_len}, "
                f"reasoning_len={reasoning_len}, tool_calls={call_count}"
            )
            if response.reasoning_content:
                logger.warning("模型只有 reasoning_content，没有最终文本输出。")
            last_error = ImageDrawerError("模型返回了空内容")
            if attempt < max_retries:
                logger.warning("空内容触发重试中...")
                continue
            raise ImageDrawerError(f"模型持续返回空内容（已重试 {max_retries} 次）") from last_error
        
        try:
            result = _parse_conversion_output(raw)
            return _enforce_mentioned_character_tags(source, result)
        except ImageDrawerError as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(f"提示词解析失败（第 {attempt + 1} 次），重试中：{exc}")
                continue
            raise ImageDrawerError(f"转换后的提示词不符合要求（已重试 {max_retries} 次）：{exc}") from exc

    # 理论上不会到达，但作为安全网
    raise ImageDrawerError(f"提示词转换失败（已重试 {max_retries} 次）：{last_error}") from last_error
