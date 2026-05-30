"""NAI Drawer plugin entry."""

from __future__ import annotations

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BasePlugin, register_plugin

from .character_handler import CharacterSetupHandler
from .command import (
    LoadStyleCommand,
    NaiDrawCommand,
    ReferenceDrawCommand,
    SaveCharacterCommand,
    SaveStyleCommand,
    SelfieCharacterCommand,
    SelfieDrawCommand,
    TagDrawCommand,
    VibeCommand,
)
from .config import NaiDrawerConfig
from .tools import DrawImageTool
from .vibe_handler import VibeSetupHandler

logger = get_logger("nai_drawer")


@register_plugin
class NaiDrawerPlugin(BasePlugin):
    """Generate NovelAI images with character, style, and Vibe references."""

    plugin_name = "nai_drawer"
    plugin_description = "NovelAI 绘图插件，支持角色参考、画风参考与 Vibe"
    plugin_version = "0.1.0"

    configs: list[type] = [NaiDrawerConfig]
    dependent_components: list[str] = []

    def get_components(self) -> list[type]:
        """Return plugin component classes."""

        return [
            NaiDrawCommand,
            TagDrawCommand,
            SaveCharacterCommand,
            ReferenceDrawCommand,
            SelfieCharacterCommand,
            SelfieDrawCommand,
            SaveStyleCommand,
            LoadStyleCommand,
            VibeCommand,
            CharacterSetupHandler,
            VibeSetupHandler,
            DrawImageTool,
        ]

    async def on_plugin_loaded(self) -> None:
        """Log plugin load."""

        logger.info("nai_drawer loaded")
