"""Client for the OpenAI-compatible image generation endpoint."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .config import NaiDrawerConfig


_IMG_RE = re.compile(r"!\[[^\]]*\]\((data:image/[^;)]+;base64,[^)]+)\)")
_SEED_RE = re.compile(r"<!--\s*seeds:(\[.*?\])\s*-->")
_VIBE_RE = re.compile(r"<!--\s*vibe_cache_ids:(\[.*?\])\s*-->")
_BLOCKED_PROMPT_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef]")


class ImageDrawerError(RuntimeError):
    """Raised when image generation fails."""


@dataclass(frozen=True)
class DrawResult:
    """Parsed draw response."""

    image_base64: str
    seeds: list[int | None]
    vibe_cache_ids: list[dict[str, Any]]
    usage: dict[str, Any] | None


def validate_prompt(prompt: str) -> None:
    """Validate the API's strict English-only prompt requirement."""

    if not prompt.strip():
        raise ImageDrawerError("提示词不能为空。用法：/tag 1girl, solo, masterpiece")
    if _BLOCKED_PROMPT_RE.search(prompt):
        raise ImageDrawerError("绘图接口要求英文提示词，不能包含中文、日文假名、韩文或全角字符。")


def _build_chat_url(base_url: str, field_name: str = "base_url") -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ImageDrawerError(f"请先配置 {field_name}。")
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _parse_error_response(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        code = error.get("code")
        if code and message:
            return f"{code}: {message}"
        if message:
            return str(message)
    return json.dumps(payload, ensure_ascii=False)[:300]


def _extract_seeds(content: str) -> list[int | None]:
    match = _SEED_RE.search(content)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return parsed
    return []


def _extract_vibe_cache_ids(content: str) -> list[dict[str, Any]]:
    match = _VIBE_RE.search(content)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _data_uri_to_base64(data_uri: str) -> str:
    """Convert data:image/<fmt>;base64,<payload> to raw base64."""

    header, separator, payload = data_uri.partition(",")
    if not separator or not header.startswith("data:image/") or ";base64" not in header:
        raise ImageDrawerError("绘图接口返回的图片 data URI 格式不正确。")
    if not payload.strip():
        raise ImageDrawerError("绘图接口返回的图片 base64 为空。")
    return payload.strip()


async def generate_image(
    prompt: str,
    config: NaiDrawerConfig,
    extra_payload: dict[str, Any] | None = None,
) -> DrawResult:
    """Generate one image and return the parsed data URI."""

    validate_prompt(prompt)

    api = config.draw_api
    generation = config.generation

    if not api.api_key.strip():
        raise ImageDrawerError("请先配置 draw_api.api_key。")
    if generation.width % 64 != 0 or generation.height % 64 != 0:
        raise ImageDrawerError("generation.width 和 generation.height 必须是 64 的倍数。")

    draw_params: dict[str, Any] = {
        "prompt": prompt.strip(),
        "negative_prompt": generation.negative_prompt.strip(),
        "size": [generation.width, generation.height],
        "steps": generation.steps,
        "scale": generation.scale,
        "sampler": generation.sampler,
        "noise_schedule": generation.noise_schedule,
        "variety_boost": generation.variety_boost,
        "cfg_rescale": generation.cfg_rescale,
        "image_format": generation.image_format,
    }
    if extra_payload:
        draw_params.update(extra_payload)

    body = {
        "model": api.model,
        "messages": [
            {
                "role": "user",
                "content": json.dumps(draw_params, ensure_ascii=False),
            }
        ],
        "stream": False,
        "max_tokens": generation.max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {api.api_key.strip()}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=api.timeout_seconds) as client:
            response = await client.post(
                _build_chat_url(api.base_url, "draw_api.base_url"),
                headers=headers,
                json=body,
            )
    except httpx.RequestError as exc:
        raise ImageDrawerError(f"绘图请求失败：{exc}") from exc

    if response.status_code >= 400:
        detail = _parse_error_response(response)
        raise ImageDrawerError(f"绘图接口返回 {response.status_code}：{detail}")

    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ImageDrawerError("绘图接口响应缺少 choices[0].message.content。") from exc

    images = _IMG_RE.findall(content)
    if not images:
        raise ImageDrawerError("绘图接口响应中没有找到 data:image 图片。")

    usage = payload.get("usage")
    return DrawResult(
        image_base64=_data_uri_to_base64(images[0]),
        seeds=_extract_seeds(content),
        vibe_cache_ids=_extract_vibe_cache_ids(content),
        usage=usage if isinstance(usage, dict) else None,
    )


async def create_vibe_cache(
    image_base64: str,
    reference_strength: float,
    information_extracted: float,
    config: NaiDrawerConfig,
) -> str:
    """Upload one Vibe reference image and return the gateway cache_id."""

    result = await generate_image(
        "masterpiece, best quality",
        config,
        extra_payload={
            "controlnet": {
                "strength": 1.0,
                "images": [
                    {
                        "image": image_base64,
                        "info_extracted": information_extracted,
                        "strength": reference_strength,
                    }
                ],
            }
        },
    )
    for entry in result.vibe_cache_ids:
        cache_id = str(entry.get("cache_id", "") or "").strip()
        if cache_id:
            return cache_id
    raise ImageDrawerError("绘图接口没有返回 vibe_cache_ids，无法保存 Vibe 预设。")
