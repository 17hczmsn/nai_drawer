"""Configuration for the NAI drawer plugin."""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


PROMPT_SYSTEM_PLACEHOLDER = "请在这里填写自然语言转绘图提示词的系统提示词。"


class NaiDrawerConfig(BaseConfig):
    """Plugin configuration."""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "NAI 绘图插件配置"

    @config_section("draw_api", title="绘图接口", tag="network")
    class DrawApiSection(SectionBase):
        """OpenAI-compatible image generation endpoint settings."""

        base_url: str = Field(
            default="",
            description="绘图接口地址，不带或带 /v1 都可以。",
            label="绘图接口地址",
            placeholder="https://example.com",
            tag="network",
        )
        api_key: str = Field(
            default="",
            description="绘图接口密钥。",
            label="绘图密钥",
            input_type="password",
            placeholder="sk-...",
            tag="security",
        )
        model: str = Field(
            default="nai-diffusion-4-5-full",
            description="绘图模型名称。",
            label="绘图模型",
            input_type="select",
            choices=[
                "nai-diffusion-4-5-full",
                "nai-diffusion-4-5-curated",
                "nai-diffusion-4-full",
                "nai-diffusion-4-curated",
                "nai-diffusion-3",
                "nai-diffusion-furry-3",
            ],
            tag="ai",
        )
        timeout_seconds: float = Field(
            default=180.0,
            ge=10.0,
            le=600.0,
            description="绘图请求超时时间，单位秒。",
            label="绘图超时",
            tag="performance",
        )

    @config_section("prompt_api", title="提示词转换接口", tag="ai")
    class PromptApiSection(SectionBase):
        """OpenAI-compatible language model endpoint for prompt rewriting."""

        enabled: bool = Field(
            default=False,
            description="是否启用 /nai 和工具绘图的自然语言转英文提示词功能。",
            label="启用提示词转换",
            tag="plugin",
        )
        base_url: str = Field(
            default="",
            description="语言模型接口地址，不带或带 /v1 都可以。",
            label="转换接口地址",
            placeholder="https://example.com",
            tag="network",
        )
        api_key: str = Field(
            default="",
            description="语言模型接口密钥。",
            label="转换密钥",
            input_type="password",
            placeholder="sk-...",
            tag="security",
        )
        model: str = Field(
            default="gpt-4.1-mini",
            description="用于自然语言转绘图提示词的语言模型名称。",
            label="转换模型",
            placeholder="gpt-4.1-mini",
            tag="ai",
        )
        timeout_seconds: float = Field(
            default=60.0,
            ge=10.0,
            le=300.0,
            description="提示词转换请求超时时间，单位秒。",
            label="转换超时",
            tag="performance",
        )
        temperature: float = Field(
            default=0.2,
            ge=0.0,
            le=2.0,
            description="提示词转换随机性，越低越稳定。",
            label="转换温度",
            tag="ai",
        )
        max_tokens: int = Field(
            default=800,
            ge=100,
            le=4000,
            description="提示词转换最大输出 token。",
            label="转换输出上限",
            tag="performance",
        )
        system_prompt: str = Field(
            default=PROMPT_SYSTEM_PLACEHOLDER,
            description="自然语言转绘图提示词的系统提示词，请用户自行填写。",
            label="转换系统提示词",
            input_type="textarea",
            rows=4,
            tag="text",
        )

    @config_section("generation", title="绘图参数", tag="ai")
    class GenerationSection(SectionBase):
        """Default image generation parameters."""

        negative_prompt: str = Field(
            default="lowres, bad anatomy, bad hands, text, watermark, blurry",
            description="默认负向提示词。",
            label="负向提示词",
            input_type="textarea",
            rows=3,
            tag="text",
        )
        width: int = Field(
            default=832,
            ge=64,
            le=1216,
            description="图片宽度，必须是 64 的倍数。",
            label="图片宽度",
            tag="ai",
        )
        height: int = Field(
            default=1216,
            ge=64,
            le=1216,
            description="图片高度，必须是 64 的倍数。",
            label="图片高度",
            tag="ai",
        )
        steps: int = Field(
            default=23,
            ge=1,
            le=28,
            description="迭代步数，最大 28。",
            label="迭代步数",
            tag="performance",
        )
        scale: float = Field(
            default=5.0,
            ge=0.0,
            le=20.0,
            description="提示词引导强度。",
            label="引导强度",
            tag="ai",
        )
        sampler: str = Field(
            default="k_euler_ancestral",
            description="采样器。",
            label="采样器",
            input_type="select",
            choices=[
                "k_euler",
                "k_euler_ancestral",
                "k_dpm_2",
                "k_dpm_2_ancestral",
                "k_dpmpp_2m",
                "k_dpmpp_2s_ancestral",
                "k_dpmpp_sde",
                "ddim",
            ],
            tag="ai",
        )
        noise_schedule: str = Field(
            default="karras",
            description="噪声调度方式。",
            label="噪声调度",
            input_type="select",
            choices=["karras", "exponential", "polyexponential"],
            tag="ai",
        )
        variety_boost: bool = Field(
            default=False,
            description="变化增强开关，对应 Variety+。",
            label="变化增强",
            tag="ai",
        )
        cfg_rescale: float = Field(
            default=0.0,
            ge=0.0,
            le=1.0,
            description="提示词引导重缩放，范围 0 到 1。",
            label="引导重缩放",
            tag="ai",
        )
        image_format: str = Field(
            default="png",
            description="输出图片格式，只能是 png 或 webp。",
            label="图片格式",
            input_type="select",
            choices=["png", "webp"],
            tag="file",
        )
        max_tokens: int = Field(
            default=100000,
            ge=10000,
            le=100000,
            description="最大预算，10000 token 约等于 1 Anlas。",
            label="最大预算",
            tag="performance",
        )

    draw_api: DrawApiSection = Field(default_factory=DrawApiSection)
    prompt_api: PromptApiSection = Field(default_factory=PromptApiSection)
    generation: GenerationSection = Field(default_factory=GenerationSection)
