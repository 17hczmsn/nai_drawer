"""NAI Drawer 插件入口。"""

from __future__ import annotations

from pathlib import Path

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BasePlugin, register_plugin
from src.kernel.concurrency import get_task_manager

from .action import DrawMultiImageAction, DrawSingleImageAction
from .command import NaiDrawCommand, NaiMultiDrawCommand
from .config import NaiDrawerConfig
from .service import warm_up_presets

logger = get_logger("nai_drawer")


@register_plugin
class NaiDrawerPlugin(BasePlugin):
    """NovelAI 绘图插件，支持配置化角色参考、Vibe 与画风前缀。"""

    plugin_name = "nai_drawer"
    plugin_description = "NovelAI 绘图插件，支持角色参考、画风参考与 Vibe"
    plugin_version = "0.2.0"

    configs: list[type] = [NaiDrawerConfig]
    dependent_components: list[str] = []

    def get_components(self) -> list[type]:
        """返回插件组件类。"""

        return [NaiDrawCommand, NaiMultiDrawCommand, DrawSingleImageAction, DrawMultiImageAction]

    async def on_plugin_loaded(self) -> None:
        """插件加载后预热预设。"""

        from .config import NaiDrawerConfig, fix_toml_chinese_keys

        logger.info("nai_drawer 已加载，开始预热预设")

        # 修复配置文件中 section header 中文键名缺少引号的问题
        fix_toml_chinese_keys(Path("config") / "plugins" / "nai_drawer" / "config.toml")

        config = self.config
        if isinstance(config, NaiDrawerConfig):
            get_task_manager().create_task(
                warm_up_presets(config),
                name="nai_drawer_warm_up",
                daemon=True,
                group_name="nai_drawer",
            )
