"""NAI Drawer Action：生成图片。

让 LLM 可以通过 Tool Calling 自主选择生成图片，
无需用户手动输入 /nai 指令。
"""

from __future__ import annotations

from typing import Annotated

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseAction

from .config import NaiDrawerConfig
from .service.draw_service import draw_from_natural_language

logger = get_logger("nai_drawer")


class DrawImageAction(BaseAction):
    """生成图片 Action。

    让 bot 在对话中自主选择生成 NovelAI 图片。
    """

    action_name: str = "draw_image"
    dependencies: list[str] = []
    action_description: str = (
        "生成一张 NovelAI 风格的二次元图片。"
        "当你觉得文字不足以传递画面、氛围或情感时，可以主动生成图片。"
        "用户明确索图、要求自拍/拍照/发图，或对话焦点转向视觉展示时，应使用此工具。"
        "纯知识问答、技术讨论等场景不应触发。"
        "重要：如果用户提到了角色名（如'蕾耶拉'、'看板娘'等），必须在描述中保留该角色名，"
        "以便系统自动加载对应的角色参考图。"
    )
    primary_action: bool = True

    async def go_activate(self) -> bool:
        """检查插件总开关和绘图接口是否配置。"""
        config = self.plugin.config
        if isinstance(config, NaiDrawerConfig):
            return config.enabled and bool(config.draw_api.base_url.strip())
        return False

    async def execute(
        self,
        description: Annotated[
            str,
            "用自然语言描述想要生成的画面内容，包括场景、人物、动作、氛围等。"
            "描述越具体，生成效果越好。"
            "重要：如果用户提到了角色名，必须在描述中保留该角色名，"
            "以便系统自动加载对应的角色参考图。",
        ],
    ) -> tuple[bool, str]:
        """执行生图并发送。

        Args:
            description: 自然语言画面描述

        Returns:
            (成功标志, 结果说明)
        """
        config = self.plugin.config
        if not isinstance(config, NaiDrawerConfig):
            return False, "插件配置类型不匹配"

        stream_id = self.chat_stream.stream_id
        text = description.strip()
        if not text:
            return False, "画面描述不能为空"

        # 获取原始用户消息，用于角色名匹配
        # 框架在实例化 Action 时会将 trigger_msg 设置到 _last_message
        original_text = self._last_message or ""

        try:
            success, message = await draw_from_natural_language(
                config=config,
                stream_id=stream_id,
                text=text,
                original_text=original_text,
            )
        except Exception as exc:
            logger.error(f"Action 生图异常：{exc}", exc_info=True)
            return False, "生图失败：插件内部异常"

        return success, message
