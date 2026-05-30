"""Command entries for image generation."""

from __future__ import annotations

import re
from typing import Any, Coroutine, cast

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.send_api import send_image, send_text
from src.app.plugin_system.base import BaseCommand, cmd_route
from src.kernel.concurrency import get_task_manager

from .character_store import (
    CharacterStoreError,
    build_character_payload,
    get_selfie_character,
    load_character_preset,
    set_selfie_character,
)
from .client import ImageDrawerError, generate_image
from .config import NaiDrawerConfig
from .profile_store import ProfileStoreError, enrich_request_with_persona
from .prompt_client import convert_to_english_prompt
from .style_store import (
    StyleStoreError,
    apply_current_style,
    load_style,
    save_current_as,
    save_style,
)
from .vibe_store import (
    VibeStoreError,
    build_current_vibe_payload,
    disable_vibe,
    get_current_vibe,
    load_vibe_preset,
)

logger = get_logger("nai_drawer")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef]")


def _queue_draw_task(
    command: BaseCommand,
    coro: Coroutine[Any, Any, tuple[bool, str]],
    name: str,
) -> tuple[bool, str]:
    """Run a slow drawing workflow in the background."""

    task_info = get_task_manager().create_task(
        coro,
        name=name,
        daemon=False,
        timeout=None,
        group_name="nai_drawer",
        metadata={
            "stream_id": command.stream_id,
            "command": command.command_name,
        },
    )
    return True, f"绘图任务已提交：{task_info.task_id}"


async def _prepare_prompt(command: BaseCommand, text: str, *, with_persona: bool = False) -> str:
    """Convert natural language only when the prompt contains non-English text."""

    prompt_text = enrich_request_with_persona(text) if with_persona else text
    if not _CJK_RE.search(prompt_text):
        return prompt_text
    config = cast(NaiDrawerConfig, command.plugin.config)
    await send_text("收到，开始转换提示词。", stream_id=command.stream_id)
    prompt = await convert_to_english_prompt(prompt_text, config)
    await send_text(f"转换后的提示词：\n{prompt}", stream_id=command.stream_id)
    return prompt


async def _send_draw_result(
    command: BaseCommand,
    prompt: str,
    extra_payload: dict[str, Any] | None = None,
    reference_label: str = "",
) -> tuple[bool, str]:
    """Generate and send one image for an already prepared English prompt."""

    config = cast(NaiDrawerConfig, command.plugin.config)
    final_prompt, style_name = apply_current_style(prompt)
    payload: dict[str, Any] = dict(extra_payload or {})

    try:
        if reference_label:
            await send_text(f"已应用角色参考：{reference_label}", stream_id=command.stream_id)

        if "character_references" not in payload:
            vibe_payload = build_current_vibe_payload()
            if vibe_payload is not None and "controlnet" not in payload:
                payload.update(vibe_payload)
                current_vibe = get_current_vibe()
                if current_vibe is not None:
                    await send_text(f"已应用 Vibe：{current_vibe.name}", stream_id=command.stream_id)

        if style_name:
            await send_text(f"已应用画风：{style_name}", stream_id=command.stream_id)
        await send_text("收到，开始绘图。", stream_id=command.stream_id)
        result = await generate_image(final_prompt, config, extra_payload=payload)
    except (ProfileStoreError, VibeStoreError, CharacterStoreError, ImageDrawerError) as exc:
        message = str(exc)
        await send_text(message, stream_id=command.stream_id)
        return False, message
    except Exception as exc:
        logger.error(f"Unexpected image generation error: {exc}", exc_info=True)
        message = "绘图失败：插件内部异常，请查看日志。"
        await send_text(message, stream_id=command.stream_id)
        return False, message

    image_sent = await send_image(
        result.image_base64,
        stream_id=command.stream_id,
        processed_plain_text="[绘图结果]",
    )
    if not image_sent:
        message = "图片已生成，但发送失败。"
        await send_text(message, stream_id=command.stream_id)
        return False, message

    if result.seeds:
        seed_text = ", ".join(str(seed) for seed in result.seeds)
        await send_text(f"seed: {seed_text}", stream_id=command.stream_id)
    if result.vibe_cache_ids:
        await send_text(f"vibe_cache_ids: {result.vibe_cache_ids}", stream_id=command.stream_id)

    return True, "image generated"


class TagDrawCommand(BaseCommand):
    """Generate an image from manual English tags."""

    command_name = "tag"
    command_description = "Use /tag <English tags> to generate one image directly"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        prompt = message_text.strip()
        if prompt in {"help", "-h", "--help"}:
            return await self.help()
        if not prompt:
            return await self.draw(prompt)
        return _queue_draw_task(self, self.draw(prompt), name="nai_drawer_tag")

    @cmd_route()
    async def draw(self, prompt: str = "") -> tuple[bool, str]:
        if not prompt.strip():
            message = "用法：/tag 1girl, solo, masterpiece, best quality"
            await send_text(message, stream_id=self.stream_id)
            return False, message
        return await _send_draw_result(self, prompt)

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/tag <英文 tag>\n"
            "示例：/tag 1girl, solo, masterpiece, best quality, detailed eyes\n"
            "该命令不会调用自然语言转换模型。"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message


class NaiDrawCommand(BaseCommand):
    """Convert natural language into English tags, then generate an image."""

    command_name = "nai"
    command_description = "Use /nai <natural language request> to convert and generate one image"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        text = message_text.strip()
        if text in {"help", "-h", "--help"}:
            return await self.help()
        if not text:
            return await self.draw(text)
        return _queue_draw_task(self, self.draw(text), name="nai_drawer_nai")

    @cmd_route()
    async def draw(self, text: str = "") -> tuple[bool, str]:
        if not text.strip():
            message = "用法：/nai 一个白裙女孩站在森林里"
            await send_text(message, stream_id=self.stream_id)
            return False, message
        try:
            prompt = await _prepare_prompt(self, text, with_persona=True)
        except (ProfileStoreError, ImageDrawerError) as exc:
            message = str(exc)
            await send_text(message, stream_id=self.stream_id)
            return False, message
        except Exception as exc:
            logger.error(f"Unexpected prompt conversion error: {exc}", exc_info=True)
            message = "提示词转换失败：插件内部异常，请查看日志。"
            await send_text(message, stream_id=self.stream_id)
            return False, message
        return await _send_draw_result(self, prompt)

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/nai <自然语言描述>\n"
            "示例：/nai 一个白裙女孩站在森林里，柔和光线\n"
            "该命令会先调用 prompt_api，把自然语言转换成英文绘图提示词。"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message


class ReferenceDrawCommand(BaseCommand):
    """Generate one image with an explicit saved character reference."""

    command_name = "参考"
    command_description = "Use /参考 <角色预设名> <提示词> for one draw with a saved character reference"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        text = message_text.strip()
        if text in {"help", "-h", "--help"} or not text:
            return await self.help()
        return _queue_draw_task(self, self.draw(text), name="nai_drawer_reference")

    @cmd_route()
    async def draw(self, text: str = "") -> tuple[bool, str]:
        parts = text.strip().split(maxsplit=1)
        if len(parts) < 2:
            return await self.help()
        name, request = parts[0], parts[1].strip()
        try:
            preset = load_character_preset(name)
            prompt = await _prepare_prompt(self, request)
            payload = build_character_payload(preset)
        except (CharacterStoreError, ImageDrawerError) as exc:
            message = str(exc)
            await send_text(message, stream_id=self.stream_id)
            return False, message
        return await _send_draw_result(self, prompt, extra_payload=payload, reference_label=preset.name)

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/参考 <角色预设名> <提示词>\n"
            "示例：/参考 看板娘 standing in a forest, soft light\n"
            "只有使用该指令时，才会单次上传对应角色参考。"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message


class SelfieCharacterCommand(BaseCommand):
    """Set the saved character preset used by /自拍."""

    command_name = "自拍角色"
    command_description = "Use /自拍角色 <角色预设名> to set the reference used by /自拍"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        name = message_text.strip()
        if name in {"help", "-h", "--help"} or not name:
            return await self.help()
        try:
            preset = set_selfie_character(name)
        except CharacterStoreError as exc:
            message = str(exc)
            await send_text(message, stream_id=self.stream_id)
            return False, message
        message = f"已设置自拍角色：{preset.name}\n只有使用 /自拍 <提示词> 时才会调用。"
        await send_text(message, stream_id=self.stream_id)
        return True, message

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = "用法：/自拍角色 <角色预设名>\n示例：/自拍角色 看板娘"
        await send_text(message, stream_id=self.stream_id)
        return True, message


class SelfieDrawCommand(BaseCommand):
    """Draw a selfie using the configured selfie character reference."""

    command_name = "自拍"
    command_description = "Use /自拍 <提示词> to draw with the configured selfie character"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        text = message_text.strip()
        if text in {"help", "-h", "--help"} or not text:
            return await self.help()
        return _queue_draw_task(self, self.draw(text), name="nai_drawer_selfie")

    @cmd_route()
    async def draw(self, text: str = "") -> tuple[bool, str]:
        try:
            prompt = await _prepare_prompt(self, text, with_persona=True)
            preset = get_selfie_character()
            payload = build_character_payload(preset) if preset is not None else None
        except (ProfileStoreError, CharacterStoreError, ImageDrawerError) as exc:
            message = str(exc)
            await send_text(message, stream_id=self.stream_id)
            return False, message
        label = preset.name if preset is not None else ""
        return await _send_draw_result(self, prompt, extra_payload=payload, reference_label=label)

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/自拍 <提示词>\n"
            "示例：/自拍 在窗边微笑，柔和阳光\n"
            "该命令才会使用 /自拍角色 设置的角色参考。普通 /nai 发自拍 不会使用自拍角色参考。"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message


class SaveCharacterCommand(BaseCommand):
    """Help entry for saving a character reference through image upload."""

    command_name = "保存角色"
    command_description = "Use /保存角色 with one image to create a character reference preset"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        return await self.help()

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：发送 /保存角色 并同时附带一张图片。\n"
            "Bot 会固定询问参考方式：1 只参考角色，2 只参考画风，3 两者都参考。\n"
            "选择后再按提示输入预设名称。"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message


class SaveStyleCommand(BaseCommand):
    """Save a named style preset."""

    command_name = "保存画风"
    command_description = "Use /保存画风 <名称> <画风词条> to save a style preset"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        text = message_text.strip()
        if text in {"help", "-h", "--help"}:
            return await self.help()
        return await self.save(text)

    @cmd_route()
    async def save(self, text: str = "") -> tuple[bool, str]:
        if not text.strip():
            return await self.help()
        parts = text.split(maxsplit=1)
        name = parts[0]
        try:
            if len(parts) == 1:
                save_current_as(name)
                message = f"已将当前加载画风另存为：{name}"
            else:
                save_style(name, parts[1])
                message = f"已保存画风：{name}"
        except StyleStoreError as exc:
            message = str(exc)
            await send_text(message, stream_id=self.stream_id)
            return False, message
        await send_text(message, stream_id=self.stream_id)
        return True, message

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/保存画风 <名称> <画风词条>\n"
            "示例：/保存画风 厚涂 masterpiece, best quality, painterly style, \n"
            "也可以在已有加载画风时使用：/保存画风 新名称"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message


class LoadStyleCommand(BaseCommand):
    """Load a named style preset."""

    command_name = "加载画风"
    command_description = "Use /加载画风 <名称> to load a saved style preset"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        text = message_text.strip()
        if text in {"help", "-h", "--help"}:
            return await self.help()
        return await self.load(text)

    @cmd_route()
    async def load(self, name: str = "") -> tuple[bool, str]:
        if not name.strip():
            return await self.help()
        try:
            tags = load_style(name)
        except StyleStoreError as exc:
            message = str(exc)
            await send_text(message, stream_id=self.stream_id)
            return False, message
        message = f"已加载画风：{name}\n当前画风词条：{tags}"
        await send_text(message, stream_id=self.stream_id)
        return True, message

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：/加载画风 <名称>\n"
            "示例：/加载画风 厚涂\n"
            "加载后，/tag 和 /nai 的最终绘图提示词都会自动以前置画风开头。"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message


class VibeCommand(BaseCommand):
    """Load or disable a saved Vibe cache preset."""

    command_name = "Vibe"
    command_description = "Use /Vibe <预设名> to load a Vibe preset, or /Vibe 关闭 to disable it"
    command_prefix = "/"

    async def execute(self, message_text: str) -> tuple[bool, str]:
        text = message_text.strip()
        if text in {"help", "-h", "--help"}:
            return await self.help()
        if not text:
            return await self.help()
        if text == "关闭":
            disable_vibe()
            message = "已关闭 Vibe。"
            await send_text(message, stream_id=self.stream_id)
            return True, message

        try:
            preset = load_vibe_preset(text)
        except VibeStoreError as exc:
            message = str(exc)
            await send_text(message, stream_id=self.stream_id)
            return False, message

        message = (
            f"已加载 Vibe：{preset.name}\n"
            f"Reference Strength: {preset.reference_strength}\n"
            f"Information Extracted: {preset.information_extracted}"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message

    @cmd_route("help")
    async def help(self) -> tuple[bool, str]:
        message = (
            "用法：\n"
            "/Vibe <预设名> 并附带一张图片：创建 Vibe 预设\n"
            "/Vibe <预设名>：加载已保存的 Vibe 预设\n"
            "/Vibe 关闭：关闭当前 Vibe\n"
            "创建预设时，Bot 会继续询问 Reference Strength 和 Information Extracted。"
            "只回复两个 0.01 到 1 的数字，用空格隔开，不要输入其他内容。"
        )
        await send_text(message, stream_id=self.stream_id)
        return True, message
