"""NAI Drawer Action：生成图片。

提供两个 Action 供 LLM 选择：
- DrawSingleImageAction：单人绘图，支持角色参考和自拍检测
- DrawMultiImageAction：多人绘图，不使用角色参考，使用多人专用提示词
"""

from __future__ import annotations

from typing import Annotated

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseAction

from .config import NaiDrawerConfig
from .service.draw_service import draw_from_natural_language

logger = get_logger("nai_drawer")


class DrawSingleImageAction(BaseAction):
    """单人绘图 Action。

    适用于单人场景，支持角色参考图和自拍检测。
    当画面中只有一个角色时使用此工具。
    """

    action_name: str = "draw_single_image"
    dependencies: list[str] = []
    action_description: str = (
        "生成一张单人二次元图片。"
        "当画面中只有一个角色时使用此工具。"
        "支持角色参考图：如果用户提到了角色名（如'蕾耶拉'、'看板娘'等），"
        "系统会自动加载对应的角色参考图，请在描述中保留该角色名。"
        "用户明确索图、要求自拍/拍照/发图，或对话焦点转向视觉展示时，应使用此工具。"
        "纯知识问答、技术讨论等场景不应触发。"
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
            "用自然语言描述想要生成的单人画面内容，包括场景、人物、动作、氛围等。"
            "描述越具体，生成效果越好。"
            "重要：如果用户提到了角色名，必须在描述中保留该角色名，"
            "以便系统自动加载对应的角色参考图。",
        ],
    ) -> tuple[bool, str]:
        """执行单人绘图并发送。

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
        original_text = self._last_message or ""

        try:
            success, message = await draw_from_natural_language(
                config=config,
                stream_id=stream_id,
                text=text,
                original_text=original_text,
                multi_mode=False,
            )
        except Exception as exc:
            logger.error(f"Action 生图异常：{exc}", exc_info=True)
            return False, "生图失败：插件内部异常"

        return success, message


class DrawMultiImageAction(BaseAction):
    """多人绘图 Action。

    适用于多人场景（2~6 个角色），不使用角色参考图，
    使用多人专用提示词确保每个角色的视觉特征被完整描述。
    """

    action_name: str = "draw_multi_image"
    dependencies: list[str] = []
    action_description: str = (
        "生成一张多人二次元图片。"
        "当画面中有两个或更多角色时使用此工具。"
        "此工具不使用角色参考图。"
        "仅使用用户实际描述的角色特征，不要自行补充或猜测用户未提及的外貌细节。"
        "互动场景（如拥抱、对话、对视等）特别适合使用此工具。"
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
            "用自然语言描述想要生成的多人画面内容，包括场景、角色关系和互动。"
            "如用户已经提供发色、瞳色、发型、体型、服装等外貌特征，应原样保留；"
            "用户未提及的外貌细节不要自行补充。"
            "示例：'蕾耶拉和希娜在花园里拥抱，蕾耶拉金发蓝眼白裙，希娜黑发红眼红裙'",
        ],
    ) -> tuple[bool, str]:
        """执行多人绘图并发送。

        Args:
            description: 自然语言多人画面描述

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

        try:
            success, message = await draw_from_natural_language(
                config=config,
                stream_id=stream_id,
                text=text,
                original_text=text,
                multi_mode=True,
            )
        except Exception as exc:
            logger.error(f"Action 多人生图异常：{exc}", exc_info=True)
            return False, "生图失败：插件内部异常"

        return success, message
