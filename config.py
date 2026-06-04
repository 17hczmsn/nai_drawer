"""NAI Drawer 插件配置。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from pydantic import ConfigDict

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section

logger = get_logger("nai_drawer")


class CharacterPresetEntry(SectionBase):
    """单个角色参考预设。"""

    image_path: str = Field(
        default="",
        description="本地角色参考图路径。首次绘图时会复制到 data 目录并上传。",
        label="参考图路径",
        tag="file",
    )
    type: str = Field(
        default="character&style",
        description="参考类型：character / style / character&style。",
        label="参考类型",
        input_type="select",
        choices=["character", "style", "character&style"],
        tag="ai",
    )
    fidelity: float = Field(default=1.0, ge=0.0, le=1.0, description="保真度。", label="保真度", tag="ai")
    strength: float = Field(default=1.0, ge=0.0, le=1.0, description="参考强度。", label="参考强度", tag="ai")
    alias_names: list[str] = Field(
        default_factory=list,
        description="别名列表，用户可能使用的其他称呼。",
        label="别名列表",
        tag="text",
        input_type="list",
        item_type="str",
    )
    enabled: bool = Field(default=True, description="是否启用该预设。", label="启用", tag="plugin")


class VibePresetEntry(SectionBase):
    """单个 Vibe 预设。"""

    image_path: str = Field(
        default="",
        description="本地 Vibe 参考图路径。首次绘图时会请求 cache_id 并缓存到 data 目录。",
        label="参考图路径",
        tag="file",
    )
    reference_strength: float = Field(
        default=0.6,
        ge=0.01,
        le=1.0,
        description="Reference Strength。",
        label="Reference Strength",
        tag="ai",
    )
    information_extracted: float = Field(
        default=0.7,
        ge=0.01,
        le=1.0,
        description="Information Extracted。",
        label="Information Extracted",
        tag="ai",
    )
    enabled: bool = Field(default=True, description="是否启用该预设。", label="启用", tag="plugin")


class NaiDrawerConfig(BaseConfig):
    """NAI Drawer 插件配置。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "NAI 绘图插件配置"

    enabled: bool = Field(
        default=True,
        description="插件总开关；关闭后所有绘图功能（指令和 Action）均不可用。",
        label="启用插件",
        tag="plugin",
    )

    @config_section("tag_retriever", title="Danbooru Tag 检索增强", tag="ai")
    class TagRetrieverSection(SectionBase):
        """Danbooru Tag 候选检索配置，可大幅提升生成 tag 的质量和规范性。"""

        enabled: bool = Field(
            default=False,
            description="是否启用 Danbooru Tag 检索增强；开启后会在翻译前查询候选标签注入系统提示词。",
            label="启用 Tag 检索",
            tag="plugin",
        )

        mode: str = Field(
            default="online",
            description="检索模式：'online'（HF Space API，推荐首选）| 'local'（本地向量，需预构建数据）。",
            label="检索模式",
            input_type="select",
            choices=["online", "local"],
            tag="plugin",
        )

        api_url: str = Field(
            default="https://sakizuki-danboorusearch.hf.space/api",
            description="DanbooruSearchOnline API 基础地址（仅 online 模式）。",
            label="API 地址",
            tag="network",
        )

        timeout: float = Field(
            default=90.0,
            ge=10.0,
            le=300.0,
            description="API 请求超时时间，单位秒（仅 online 模式）。",
            label="API 超时",
            tag="network",
        )

        search_limit: int = Field(
            default=30,
            ge=5,
            le=100,
            description="语义搜索结果的上限条数（仅 online 模式）。",
            label="搜索结果数",
            tag="ai",
        )

        search_top_k: int = Field(
            default=5,
            ge=1,
            le=50,
            description="语义搜索每个分词段的召回数（仅 online 模式）。",
            label="搜索召回数",
            tag="ai",
        )

        related_limit: int = Field(
            default=20,
            ge=5,
            le=100,
            description="共现推荐结果的上限条数（仅 online 模式）。",
            label="推荐结果数",
            tag="ai",
        )

        related_seed_count: int = Field(
            default=8,
            ge=1,
            le=20,
            description="用多少个搜索结果作为共现推荐的种子（仅 online 模式）。",
            label="推荐种子数",
            tag="ai",
        )

        show_nsfw: bool = Field(
            default=True,
            description="是否包含 NSFW/R-18 标签。",
            label="显示 NSFW 标签",
            tag="ai",
        )

        popularity_weight: float = Field(
            default=0.15,
            ge=0.0,
            le=1.0,
            description="标签热度对搜索排序的影响权重（0 = 纯语义，1 = 纯热度，仅 online 模式）。",
            label="热度权重",
            tag="ai",
        )

        top_k: int = Field(
            default=50,
            ge=10,
            le=200,
            description="本地向量搜索返回的候选数量（仅 local 模式）。",
            label="返回候选数",
            tag="ai",
        )

        min_score: float = Field(
            default=0.05,
            ge=0.0,
            le=1.0,
            description="本地搜索的最小相似度阈值，低于此分数的候选被过滤（仅 local 模式）。",
            label="最小相似度",
            tag="ai",
        )

        cache_online_results: bool = Field(
            default=True,
            description="online 模式检索成功后，将高分搜索结果缓存到本地向量库，供 local 模式和在线降级复用。",
            label="缓存 Online 搜索结果",
            tag="storage",
        )

        cache_min_score: float = Field(
            default=0.45,
            ge=0.0,
            le=1.0,
            description="online 搜索结果写入本地向量库的最低相关度。",
            label="缓存最低相关度",
            tag="storage",
        )

        cache_related_results: bool = Field(
            default=False,
            description="是否缓存共现推荐结果；默认关闭，避免把同作品其它角色写入本地库。",
            label="缓存共现推荐",
            tag="storage",
        )

        cache_max_items: int = Field(
            default=5000,
            ge=100,
            le=100000,
            description="本地在线缓存最多保留的 tag 条数，已存在的手动条目优先保留。",
            label="缓存最大条数",
            tag="storage",
        )

        suppress_character_tags_when_reference: bool = Field(
            default=True,
            description="命中角色参考图时，自动移除最终提示词中对应的 Danbooru 角色 tag，避免模型内置角色形态覆盖参考图。",
            label="角色参考时移除角色 Tag",
            tag="ai",
        )

    @config_section("draw_api", title="绘图接口", tag="network")
    class DrawApiSection(SectionBase):
        """OpenAI 兼容 NovelAI 绘图接口。"""

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

    @config_section("prompt", title="提示词转换", tag="ai")
    class PromptSection(SectionBase):
        """自然语言转英文绘图提示词。"""

        model_name: str = Field(
            default="",
            description="匹配 config/model.toml 中 models 的 name 字段；留空则使用 model_tasks.sub_actor。",
            label="转换模型",
            placeholder="留空使用 sub_actor",
            tag="ai",
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
        max_retries: int = Field(
            default=2,
            ge=0,
            le=5,
            description="提示词转换失败（空内容或解析错误）时的最大重试次数。",
            label="最大重试次数",
            tag="performance",
        )
        prompt_prefix: str = Field(
            default="",
            description="破甲词，自动追加到翻译模型系统提示词末尾，用于引导翻译模型产出更高质量的结果。",
            label="破甲词",
            input_type="textarea",
            rows=2,
            tag="text",
        )

    @config_section("style", title="画风", tag="ai")
    class StyleSection(SectionBase):
        """全局画风前缀。"""

        prefix: str = Field(
            default="",
            description="自动拼接到用户提示词最前面的画风 tag。",
            label="画风前缀",
            input_type="textarea",
            rows=2,
            tag="text",
        )
        skip_with_vibe: bool = Field(
            default=False,
            description="使用 Vibe 预设时是否跳过全局画风前缀；两者可能冲突时建议开启。",
            label="Vibe 时跳过画风前缀",
            tag="ai",
        )

    @config_section("bot", title="BOT 人设", tag="ai")
    class BotSection(SectionBase):
        """自拍相关提示词转换辅助。"""

        persona_prompt: str = Field(
            default="",
            description="BOT 外貌与人设；触发自拍类自然语言时会追加给转换模型。",
            label="BOT 人设",
            input_type="textarea",
            rows=4,
            tag="text",
        )
        selfie_keywords: list[str] = Field(
            default_factory=lambda: ["自拍", "发张自拍", "照片", "发张图", "selfie"],
            description="命中这些词时追加 BOT 人设，并尝试使用 selfie 角色参考。",
            label="自拍关键词",
            tag="text",
        )

    @config_section("characters", title="角色参考预设", tag="ai")
    class CharactersSection(SectionBase):
        """角色参考预设；额外键名为预设名，如 [characters.看板娘]。"""

        model_config = ConfigDict(extra="allow")
        __config_extra_section_model__: ClassVar[type[SectionBase]] = CharacterPresetEntry

        selfie: str = Field(
            default="",
            description="自拍场景使用的角色预设名；留空则自拍时不附加角色参考。",
            label="自拍角色",
            tag="plugin",
        )

    @config_section("vibes", title="Vibe 预设", tag="ai")
    class VibesSection(SectionBase):
        """Vibe 预设；额外键名为预设名，如 [vibes.清新画风]。"""

        model_config = ConfigDict(extra="allow")
        __config_extra_section_model__: ClassVar[type[SectionBase]] = VibePresetEntry

        active: str = Field(
            default="",
            description="默认启用的 Vibe 预设名；留空表示不附加 Vibe。",
            label="默认 Vibe",
            tag="plugin",
        )

    @config_section("generation", title="绘图参数", tag="ai")
    class GenerationSection(SectionBase):
        """默认绘图参数。"""

        negative_prompt: str = Field(
            default="lowres, bad anatomy, bad hands, text, watermark, blurry",
            description="默认负向提示词。",
            label="负向提示词",
            input_type="textarea",
            rows=3,
            tag="text",
        )
        width: int = Field(default=832, ge=64, le=1216, description="图片宽度，64 的倍数。", label="图片宽度", tag="ai")
        height: int = Field(default=1216, ge=64, le=1216, description="图片高度，64 的倍数。", label="图片高度", tag="ai")
        steps: int = Field(default=23, ge=1, le=28, description="迭代步数，最大 28。", label="迭代步数", tag="performance")
        scale: float = Field(default=5.0, ge=0.0, le=20.0, description="提示词引导强度。", label="引导强度", tag="ai")
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
        variety_boost: bool = Field(default=False, description="变化增强开关，对应 Variety+。", label="变化增强", tag="ai")
        cfg_rescale: float = Field(default=0.0, ge=0.0, le=1.0, description="提示词引导重缩放。", label="引导重缩放", tag="ai")
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
    generation: GenerationSection = Field(default_factory=GenerationSection)
    prompt: PromptSection = Field(default_factory=PromptSection)
    style: StyleSection = Field(default_factory=StyleSection)
    bot: BotSection = Field(default_factory=BotSection)
    characters: CharactersSection = Field(default_factory=CharactersSection)
    vibes: VibesSection = Field(default_factory=VibesSection)
    tag_retriever: TagRetrieverSection = Field(default_factory=TagRetrieverSection)


# ---------------------------------------------------------------------------
# TOML 中文键名引号修复
# ---------------------------------------------------------------------------

# 匹配 TOML section header 中点分路径的每个部分
# 裸键: ASCII 字母/数字/_/- 的组合
# 非 ASCII 字符（如中文）在 TOML 规范中必须用引号包裹
_SECTION_HEADER_RE = re.compile(
    r"^(\[\[?)"                       # [ 或 [[
    r"(.+?)"                          # section name (点分路径)
    r"(\]\]?)$"                       # ] 或 ]]
    ,
    re.MULTILINE,
)
_BARE_KEY_PART_RE = re.compile(
    r"(?<=\.)"                        # 前面是点（或行首）
    r"([^.\[\]\"']+)?"               # 键名部分
    r"(?=[.\]]|$)"                    # 后面是点、] 或行尾
)


def _needs_quoting(part: str) -> bool:
    """判断 TOML 键名部分是否需要引号包裹。

    TOML 裸键仅允许 ASCII 字母、数字、``_`` 和 ``-``；
    含非 ASCII 字符（如中文）的部分必须使用引号键。
    """
    if not part:
        return False
    return not all(ch.isascii() and (ch.isalnum() or ch in {"_", "-"}) for ch in part)


def _quote_section_parts(section_name: str) -> str:
    """对点分节名中需要引号的部分添加双引号。

    例如 ``characters.蕾耶拉`` → ``characters."蕾耶拉"``
    """
    parts = section_name.split(".")
    result_parts: list[str] = []
    for part in parts:
        if _needs_quoting(part):
            escaped = part.replace("\\", "\\\\").replace('"', '\\"')
            result_parts.append(f'"{escaped}"')
        else:
            result_parts.append(part)
    return ".".join(result_parts)


def fix_toml_chinese_keys(config_path: str | Path) -> None:
    """修复 TOML 配置文件中 section header 中文键名缺少引号的问题。

    主程序配置系统在 auto_update 写回时，``_toml_format_key`` 使用
    Python 的 ``str.isalnum()`` 判断裸键，而该方法对中文字符也返回 True，
    导致中文键名被当作裸键输出（如 ``[characters.蕾耶拉]``），
    不符合 TOML 规范，编辑器会标红格式错误。

    本函数扫描文件中所有 section header，对含非 ASCII 字符的键名部分
    自动添加双引号（如 ``[characters."蕾耶拉"]``）。

    Args:
        config_path: 配置文件的路径。
    """
    path = Path(config_path)
    if not path.exists():
        return

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    fixed_lines: list[str] = []
    changed = False

    for line in lines:
        stripped = line.strip()
        # 快速跳过非 section header 行
        if not stripped.startswith("["):
            fixed_lines.append(line)
            continue

        m = _SECTION_HEADER_RE.match(stripped)
        if not m:
            fixed_lines.append(line)
            continue

        bracket_open, section_name, bracket_close = m.group(1), m.group(2), m.group(3)
        # 跳过已经是引号键的 section（如 [characters."蕾耶拉"]）
        # 以及 TOML 字符串键内含点的场景（如 ["foo.bar"]）
        if section_name.startswith('"') or section_name.startswith("'"):
            fixed_lines.append(line)
            continue

        quoted = _quote_section_parts(section_name)
        if quoted != section_name:
            indent = line[: len(line) - len(line.lstrip())]
            fixed_lines.append(f"{indent}{bracket_open}{quoted}{bracket_close}")
            changed = True
            logger.debug(f"修复 TOML section header：[{section_name}] → [{quoted}]")
        else:
            fixed_lines.append(line)

    if changed:
        path.write_text("\n".join(fixed_lines) + "\n", encoding="utf-8")
        logger.info(f"已修复配置文件中的中文键名引号：{path}")
