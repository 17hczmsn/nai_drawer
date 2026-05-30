"""LLM-callable tools for image drawing."""

from __future__ import annotations

from typing import Annotated, Any, Coroutine, cast

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.send_api import send_text
from src.app.plugin_system.base import BaseTool
from src.kernel.concurrency import get_task_manager

from .client import ImageDrawerError
from .command import _send_draw_result
from .config import NaiDrawerConfig
from .prompt_client import convert_to_english_prompt

logger = get_logger("nai_drawer")


class DrawImageTool(BaseTool):
    """Let the bot proactively draw an image when the user clearly asks for one."""

    tool_name = "draw_image"
    tool_description = (
        "当用户明确提出画图、生成图片、发张图、来一张图、想要自拍等绘图需求时调用。"
        "输入用户当前的自然语言绘图需求；工具会转换成英文绘图提示词并把图片发送到当前聊天。"
        "模型自动判断出的自拍需求只使用提示词、当前画风和当前 Vibe，不使用 /自拍角色 保存的角色参考图。"
        "不要在用户只是普通聊天、讨论图片、分析图片或没有明确要生成图片时调用。"
    )

    def _queue_tool_task(
        self,
        coro: Coroutine[Any, Any, tuple[bool, str | dict]],
    ) -> tuple[bool, dict[str, str]]:
        task_info = get_task_manager().create_task(
            coro,
            name="nai_drawer_tool",
            daemon=False,
            timeout=None,
            group_name="nai_drawer",
            metadata={
                "stream_id": self.get_current_stream_id(),
                "tool": self.tool_name,
            },
        )
        return True, {
            "status": "submitted",
            "message": "绘图任务已提交，图片生成后会直接发送到当前聊天。",
            "task_id": task_info.task_id,
        }

    async def execute(
        self,
        request: Annotated[str, "用户当前明确提出的自然语言绘图需求，保留主体、动作、场景、风格等关键信息"],
    ) -> tuple[bool, str | dict]:
        """Submit a drawing task for the current chat."""

        text = request.strip()
        if not text:
            return False, "绘图需求不能为空。"

        if not self.get_current_stream_id():
            return False, "缺少当前聊天上下文，无法发送绘图结果。"

        return self._queue_tool_task(self._draw_from_request(text))

    async def _draw_from_request(self, text: str) -> tuple[bool, str | dict]:
        """Convert a natural-language request, draw, and send the result."""

        stream_id = self.get_current_stream_id()
        self.stream_id = stream_id

        config = cast(NaiDrawerConfig, self.plugin.config)
        try:
            await send_text("收到绘图需求，开始转换提示词。", stream_id=stream_id)
            prompt = await convert_to_english_prompt(text, config)
            await send_text(f"转换后的提示词：\n{prompt}", stream_id=stream_id)
        except ImageDrawerError as exc:
            message = str(exc)
            await send_text(message, stream_id=stream_id)
            return False, message
        except Exception as exc:
            logger.error(f"Unexpected prompt conversion error: {exc}", exc_info=True)
            message = "提示词转换失败：插件内部异常，请查看日志。"
            await send_text(message, stream_id=stream_id)
            return False, message

        success, result = await _send_draw_result(self, prompt)  # type: ignore[arg-type]
        return success, result
