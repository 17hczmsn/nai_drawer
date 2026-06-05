"""/nai 和 /naim 指令入口。"""

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
        name=f"nai_drawer_{command.command_name}",
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
    """单人绘图：把自然语言转换为英文 tag 后生成图片。"""

    command_name = "nai"
    command_description = "使用 /nai <自然语言描述> 生成单人图片"
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
        return _queue_draw_task(self, draw_from_natural_language(config, self.stream_id, text, multi_mode=False))

    @cmd_route()
    async def draw(self, text: str = "") -> tuple[bool, str]:
        if not text.strip():
            return False, "用法：/nai <自然语言描述>\n示例：/nai 一个白裙女孩站在森林里，柔和光线"
        config = self.plugin.config
        if not isinstance(config, NaiDrawerConfig):
            return False, "插件配置类型不匹配"
        if not config.enabled:
            return False, "插件已关闭"
        return await draw_from_natural_language(config, self.stream_id, text, multi_mode=False)

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/nai <自然语言描述>\n"
            "单人绘图，支持角色参考图。\n"
            "示例：/nai 一个白裙女孩站在森林里，柔和光线\n\n"
            "多人绘图请使用 /naim\n"
            "纯英文 tag 直通绘图请使用 /nai0\n"
            "角色参考、Vibe、画风请在 config/plugins/nai_drawer/config.toml 中配置。"
        )
        return True, message


class NaiRawDrawCommand(BaseCommand):
    """单人绘图：直接使用用户输入的纯英文 Danbooru tags。"""

    command_name = "nai0"
    command_description = "使用 /nai0 <英文 Danbooru tags> 跳过翻译模型生成单人图片"
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
        return _queue_draw_task(
            self,
            draw_from_natural_language(config, self.stream_id, text, multi_mode=False, raw_tags_mode=True),
        )

    @cmd_route()
    async def draw(self, text: str = "") -> tuple[bool, str]:
        if not text.strip():
            return False, "用法：/nai0 <英文 Danbooru tags>\n示例：/nai0 1girl, solo, white_dress, forest, soft lighting"
        config = self.plugin.config
        if not isinstance(config, NaiDrawerConfig):
            return False, "插件配置类型不匹配"
        if not config.enabled:
            return False, "插件已关闭"
        return await draw_from_natural_language(config, self.stream_id, text, multi_mode=False, raw_tags_mode=True)

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/nai0 <英文 Danbooru tags>\n"
            "单人绘图，跳过提示词翻译模型；输入必须是纯英文 tag。\n"
            "示例：/nai0 1girl, solo, white_dress, forest, soft lighting\n\n"
            "自然语言绘图请使用 /nai，多人绘图请使用 /naim。"
        )
        return True, message


class NaiMultiDrawCommand(BaseCommand):
    """多人绘图：把自然语言转换为英文 tag 后生成多人图片。"""

    command_name = "naim"
    command_description = "使用 /naim <自然语言描述> 生成多人图片"
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
        return _queue_draw_task(self, draw_from_natural_language(config, self.stream_id, text, multi_mode=True))

    @cmd_route()
    async def draw(self, text: str = "") -> tuple[bool, str]:
        if not text.strip():
            return False, "用法：/naim <自然语言描述>\n示例：/naim 蕾耶拉和希娜在花园里拥抱"
        config = self.plugin.config
        if not isinstance(config, NaiDrawerConfig):
            return False, "插件配置类型不匹配"
        if not config.enabled:
            return False, "插件已关闭"
        return await draw_from_natural_language(config, self.stream_id, text, multi_mode=True)

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/naim <自然语言描述>\n"
            "多人绘图，不使用角色参考图，仅使用用户描述的角色特征。\n"
            "示例：/naim 蕾耶拉和希娜在花园里拥抱\n\n"
            "单人绘图请使用 /nai\n"
            "纯英文 tag 直通绘图请使用 /nai0\n"
            "画风请在 config/plugins/nai_drawer/config.toml 中配置。"
        )
        return True, message
