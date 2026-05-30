"""Event handler for interactive character reference setup."""

from __future__ import annotations

import re
import time
from typing import Any

from src.app.plugin_system.api.send_api import send_text
from src.app.plugin_system.base import BaseEventHandler
from src.core.components.types import EventType
from src.kernel.event import EventDecision

from .character_store import (
    CharacterStoreError,
    PendingCharacterSetup,
    pop_pending_character,
    save_character_preset,
    set_pending_character,
)
from .message_utils import first_image_data, text_from_message

_SAVE_CHARACTER_RE = re.compile(r"^/保存角色(?:\s*.*)?$")
_PENDING_TTL_SECONDS = 30 * 60
_REFERENCE_TYPE_OPTIONS = (
    "请选择参考方式，只输入数字，不要输入其他内容：\n"
    "1 只参考角色\n"
    "2 只参考画风\n"
    "3 角色和画风都参考"
)
_NAME_PROMPT = "请只回复这个角色预设的名称，不要输入其他内容。"
_TYPE_BY_CHOICE = {
    "1": "character",
    "2": "style",
    "3": "character&style",
}


class CharacterSetupHandler(BaseEventHandler):
    """Catch image messages for /保存角色 and follow-up replies."""

    handler_name = "character_setup_handler"
    handler_description = "Handle /保存角色 image upload and setup replies"
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

        if _SAVE_CHARACTER_RE.match(text):
            handled = await self._handle_save_character_message(message, stream_id, sender_id)
            return (EventDecision.STOP if handled else EventDecision.PASS), params

        pending = pop_pending_character(stream_id, sender_id)
        if pending is None:
            return EventDecision.PASS, params
        if time.time() - pending.created_at > _PENDING_TTL_SECONDS:
            await send_text("保存角色等待已超时，请重新发送 /保存角色 并附带图片。", stream_id=stream_id)
            return EventDecision.STOP, params
        if pending.stage == "await_image":
            image_data = first_image_data(message)
            if not image_data:
                set_pending_character(pending)
                await send_text("请发送一张角色参考图片。", stream_id=stream_id)
                return EventDecision.STOP, params
            set_pending_character(
                PendingCharacterSetup(
                    stage="choose_type",
                    image_base64=image_data,
                    reference_type="",
                    stream_id=stream_id,
                    sender_id=sender_id,
                    created_at=time.time(),
                )
            )
            await send_text(_REFERENCE_TYPE_OPTIONS, stream_id=stream_id)
            return EventDecision.STOP, params
        if text.startswith("/"):
            set_pending_character(pending)
            return EventDecision.PASS, params

        if pending.stage == "choose_type":
            choice = text.strip()
            reference_type = _TYPE_BY_CHOICE.get(choice)
            if reference_type is None:
                set_pending_character(pending)
                await send_text(_REFERENCE_TYPE_OPTIONS, stream_id=stream_id)
                return EventDecision.STOP, params
            set_pending_character(
                PendingCharacterSetup(
                    stage="choose_name",
                    image_base64=pending.image_base64,
                    reference_type=reference_type,
                    stream_id=stream_id,
                    sender_id=sender_id,
                    created_at=time.time(),
                )
            )
            await send_text(_NAME_PROMPT, stream_id=stream_id)
            return EventDecision.STOP, params

        if pending.stage == "choose_name":
            name = text.strip()
            if not name or len(name) > 40 or any(ch.isspace() for ch in name):
                set_pending_character(pending)
                await send_text("名称不能为空，且不要包含空格。请只回复角色预设名称。", stream_id=stream_id)
                return EventDecision.STOP, params
            try:
                preset = save_character_preset(name, pending.image_base64, pending.reference_type)
            except CharacterStoreError as exc:
                await send_text(str(exc), stream_id=stream_id)
                return EventDecision.STOP, params
            await send_text(
                f"已保存角色预设：{preset.name}\n"
                f"参考方式：{preset.reference_type}\n"
                "使用方式：/参考 预设名 提示词\n"
                "设置自拍角色：/自拍角色 预设名",
                stream_id=stream_id,
            )
            return EventDecision.STOP, params

        return EventDecision.PASS, params

    async def _handle_save_character_message(
        self,
        message: Any,
        stream_id: str,
        sender_id: str,
    ) -> bool:
        image_data = first_image_data(message)
        if not image_data:
            set_pending_character(
                PendingCharacterSetup(
                    stage="await_image",
                    image_base64="",
                    reference_type="",
                    stream_id=stream_id,
                    sender_id=sender_id,
                    created_at=time.time(),
                )
            )
            await send_text("请发送一张角色参考图片。", stream_id=stream_id)
            return True
        set_pending_character(
            PendingCharacterSetup(
                stage="choose_type",
                image_base64=image_data,
                reference_type="",
                stream_id=stream_id,
                sender_id=sender_id,
                created_at=time.time(),
            )
        )
        await send_text(_REFERENCE_TYPE_OPTIONS, stream_id=stream_id)
        return True
