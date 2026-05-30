"""/nai 指令入口。"""

from __future__ import annotations

from typing import Any, Coroutine

from src.app.plugin_system.base import BaseCommand, cmd_route
from src.kernel.concurrency import get_task_manager

from .config import NaiDrawerConfig
from .service import draw_from_natural_language


def _queue_draw_task(
    command: BaseCommand,
    coro: Coroutine[Any, Any, tuple[bool, str]],
) -> tuple[bool, str]:
    """在后台执行较慢的绘图流程。"""

    task_info = get_task_manager().create_task(
        coro,
        name="nai_drawer_nai",
        daemon=False,
        timeout=None,
        group_name="nai_drawer",
        metadata={
            "stream_id": command.stream_id,
            "command": command.command_name,
        },
    )
    return True, f"绘图任务已提交：{task_info.task_id}"


class NaiDrawCommand(BaseCommand):
    """把自然语言转换为英文 tag 后生成图片。"""

    command_name = "nai"
    command_description = "使用 /nai <自然语言描述> 转换并生成图片"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        text = message_text.strip()
        if text in {"help", "-h", "--help"}:
            return await self.help()
        if not text:
            return await self.draw(text)
        config = self.plugin.config
        if not isinstance(config, NaiDrawerConfig):
            return False, "插件配置类型不匹配"
        if not config.enabled:
            return False, "插件已关闭"
        return _queue_draw_task(self, draw_from_natural_language(config, self.stream_id, text))

    @cmd_route()
    async def draw(self, text: str = "") -> tuple[bool, str]:
        if not text.strip():
            return False, "用法：/nai 一个白裙女孩站在森林里"
        config = self.plugin.config
        if not isinstance(config, NaiDrawerConfig):
            return False, "插件配置类型不匹配"
        if not config.enabled:
            return False, "插件已关闭"
        return await draw_from_natural_language(config, self.stream_id, text)

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/nai <自然语言描述>\n"
            "示例：/nai 一个白裙女孩站在森林里，柔和光线\n"
            "角色参考、Vibe、画风请在 config/plugins/nai_drawer/config.toml 中配置。"
        )
        return True, message
