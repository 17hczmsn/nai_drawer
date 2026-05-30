"""Client for natural-language to English image prompt conversion."""

from __future__ import annotations

import httpx

from .client import ImageDrawerError, _build_chat_url, _parse_error_response, validate_prompt
from .config import NaiDrawerConfig, PROMPT_SYSTEM_PLACEHOLDER


async def convert_to_english_prompt(text: str, config: NaiDrawerConfig) -> str:
    """Convert a natural-language request into English prompt tags."""

    source = text.strip()
    if not source:
        raise ImageDrawerError("自然语言描述不能为空。")

    api = config.prompt_api
    if not api.enabled:
        raise ImageDrawerError("请先启用 prompt_api.enabled。")
    if not api.base_url.strip():
        raise ImageDrawerError("请先配置 prompt_api.base_url。")
    if not api.api_key.strip():
        raise ImageDrawerError("请先配置 prompt_api.api_key。")
    if not api.system_prompt.strip() or api.system_prompt.strip() == PROMPT_SYSTEM_PLACEHOLDER:
        raise ImageDrawerError("请先在 prompt_api.system_prompt 填写自然语言转换提示词。")

    body = {
        "model": api.model,
        "messages": [
            {"role": "system", "content": api.system_prompt},
            {"role": "user", "content": source},
        ],
        "stream": False,
        "temperature": api.temperature,
        "max_tokens": api.max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api.api_key.strip()}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=api.timeout_seconds) as client:
            response = await client.post(
                _build_chat_url(api.base_url, "prompt_api.base_url"),
                headers=headers,
                json=body,
            )
    except httpx.RequestError as exc:
        raise ImageDrawerError(f"提示词转换请求失败：{exc}") from exc

    if response.status_code >= 400:
        detail = _parse_error_response(response)
        raise ImageDrawerError(f"提示词转换接口返回 {response.status_code}：{detail}")

    payload = response.json()
    try:
        prompt = payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ImageDrawerError("提示词转换接口响应缺少 choices[0].message.content。") from exc

    prompt = prompt.strip("` \n\r\t")
    if not prompt:
        raise ImageDrawerError("提示词转换接口返回了空内容。")

    try:
        validate_prompt(prompt)
    except ImageDrawerError as exc:
        raise ImageDrawerError(f"转换后的提示词不符合绘图接口要求：{exc}") from exc

    return prompt
