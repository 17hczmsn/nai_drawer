"""Event handler for interactive Vibe preset setup."""

from __future__ import annotations

import re
import time
from typing import Any, Coroutine, cast

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.send_api import send_text
from src.app.plugin_system.base import BaseEventHandler
from src.core.components.types import EventType
from src.kernel.concurrency import get_task_manager
from src.kernel.event import EventDecision

from .client import ImageDrawerError, create_vibe_cache
from .config import NaiDrawerConfig
from .vibe_store import (
    PendingVibeSetup,
    VibeStoreError,
    pop_pending_vibe,
    save_vibe_preset,
    set_pending_vibe,
)
from .message_utils import first_image_data, text_from_message

logger = get_logger("nai_drawer")

_VIBE_COMMAND_RE = re.compile(r"^/vibe(?:\s+(.+))?$", re.IGNORECASE)
_RATIO_REPLY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$")
_PENDING_TTL_SECONDS = 30 * 60
_VIBE_PARAMETER_PROMPT = (
    "请只回复两个数字，不要输入其他内容。\n"
    "两个数字用空格隔开，例如：0.6 0.7\n"
    "第一个数字是 Reference Strength，第二个数字是 Information Extracted。\n"
    "两个数字范围都是 0.01 到 1。"
)


def _parse_two_ratios(text: str) -> tuple[float, float] | None:
    match = _RATIO_REPLY_RE.match(text)
    if match is None:
        return None
    first, second = float(match.group(1)), float(match.group(2))
    if not (0.01 <= first <= 1.0 and 0.01 <= second <= 1.0):
        return None
    return first, second


def _clean_vibe_name(name: str) -> str:
    return re.sub(r"\[(?:图片|image)(?::[^\]]*)?\]", "", name, flags=re.IGNORECASE).strip()


def _queue_vibe_task(
    coro: Coroutine[Any, Any, None],
    stream_id: str,
    preset_name: str,
) -> None:
    get_task_manager().create_task(
        coro,
        name="nai_drawer_vibe_cache",
        daemon=False,
        timeout=None,
        group_name="nai_drawer",
        metadata={
            "stream_id": stream_id,
            "vibe_preset": preset_name,
        },
    )


class VibeSetupHandler(BaseEventHandler):
    """Catch image messages for /Vibe setup and numeric replies."""

    handler_name = "vibe_setup_handler"
    handler_description = "Handle /Vibe image upload and parameter reply"
    weight = 20
    intercept_message = True
    init_subscribe = [EventType.ON_MESSAGE_RECEIVED]

    async def execute(
        self,
        event_name: str,
        params: dict[str, Any],
    ) -> tuple[EventDecision, dict[str, Any]]:
        message = params.get("message")
        if message is None:
            return EventDecision.PASS, params

        text = text_from_message(message)
        stream_id = str(getattr(message, "stream_id", "") or "")
        sender_id = str(getattr(message, "sender_id", "") or "")
        if not stream_id or not sender_id:
            return EventDecision.PASS, params

        vibe_match = _VIBE_COMMAND_RE.match(text)
        if vibe_match:
            handled = await self._handle_vibe_command_message(message, vibe_match, stream_id, sender_id)
            return (EventDecision.STOP if handled else EventDecision.PASS), params

        pending = pop_pending_vibe(stream_id, sender_id)
        if pending is None:
            return EventDecision.PASS, params
        if time.time() - pending.created_at > _PENDING_TTL_SECONDS:
            await send_text("Vibe 参数等待已超时，请重新发送 /Vibe 预设名 并附带图片。", stream_id=stream_id)
            return EventDecision.STOP, params
        if text.startswith("/"):
            set_pending_vibe(pending)
            return EventDecision.PASS, params

        ratios = _parse_two_ratios(text)
        if ratios is None:
            set_pending_vibe(pending)
            await send_text(_VIBE_PARAMETER_PROMPT, stream_id=stream_id)
            return EventDecision.STOP, params

        reference_strength, information_extracted = ratios
        await send_text("已收到参数，开始请求 Vibe 缓存 ID。", stream_id=stream_id)
        _queue_vibe_task(
            self._create_and_save_vibe_cache(pending, reference_strength, information_extracted),
            stream_id=stream_id,
            preset_name=pending.name,
        )
        return EventDecision.STOP, params

    async def _handle_vibe_command_message(
        self,
        message: Any,
        vibe_match: re.Match[str],
        stream_id: str,
        sender_id: str,
    ) -> bool:
        preset_name = _clean_vibe_name(str(vibe_match.group(1) or ""))
        if not preset_name or preset_name == "关闭":
            return False

        image_data = first_image_data(message)
        if not image_data:
            return False

        set_pending_vibe(
            PendingVibeSetup(
                name=preset_name,
                image_base64=image_data,
                stream_id=stream_id,
                sender_id=sender_id,
                created_at=time.time(),
            )
        )
        await send_text(
            f"已收到 Vibe 预设图片：{preset_name}\n{_VIBE_PARAMETER_PROMPT}",
            stream_id=stream_id,
        )
        return True

    async def _create_and_save_vibe_cache(
        self,
        pending: PendingVibeSetup,
        reference_strength: float,
        information_extracted: float,
    ) -> None:
        config = cast(NaiDrawerConfig, self.plugin.config)
        try:
            cache_id = await create_vibe_cache(
                pending.image_base64,
                reference_strength,
                information_extracted,
                config,
            )
            preset = save_vibe_preset(
                pending.name,
                cache_id,
                reference_strength,
                information_extracted,
            )
        except (ImageDrawerError, VibeStoreError) as exc:
            await send_text(str(exc), stream_id=pending.stream_id)
            return
        except Exception as exc:
            logger.error(f"Unexpected Vibe cache error: {exc}", exc_info=True)
            await send_text("Vibe 缓存保存失败：插件内部异常，请查看日志。", stream_id=pending.stream_id)
            return

        await send_text(
            f"已保存并加载 Vibe：{preset.name}\n"
            f"cache_id: {preset.cache_id}\n"
            f"Reference Strength: {preset.reference_strength}\n"
            f"Information Extracted: {preset.information_extracted}",
            stream_id=pending.stream_id,
        )
