# NAI Drawer

NovelAI 二次元图片生成插件，通过 OpenAI 兼容接口调用 NovelAI 绘图模型，支持自然语言描述生图、角色参考、Vibe 画风迁移等功能。

---

## 功能概览

- **自然语言生图**：用中文/日文/韩文描述画面，自动转换为英文 Danbooru tag 后调用绘图 API
- **LLM 自主生图**：注册为 Action 工具，LLM 可在对话中自主判断何时生成图片（无需用户手动输入指令）
- **角色参考**：上传角色参考图，生成时自动附加角色特征（需站点支持 reference）
- **Vibe 画风迁移**：上传画风参考图，生成时自动应用画风（需站点支持 vibe）
- **自拍模式**：命中自拍关键词时自动追加 BOT 人设和角色参考
- **多人场景**：支持多角色提示词转换，自动分配画面位置
- **画风前缀**：全局画风 tag 自动拼接
- **失败重试**：提示词转换失败时自动重试，可配置重试次数

> ⚠ **角色参考和 Vibe 需要站点支持该功能**，并非所有 OpenAI 兼容接口都支持 reference / vibe 参数。如果你的站点不支持，配置后会被忽略，不会影响基础生图功能。

---

## 使用方式

### 方式一：指令触发

```text
/nai 一个白裙女孩站在森林里，柔和光线
/naim 两个女孩在咖啡厅里聊天
/nai 自拍
```

`/nai` 用于单人绘图，支持角色参考图和自拍模式；`/naim` 用于多人场景，不加载角色参考图。两者都会把自然语言转换为英文 Danbooru tag 后再调用绘图 API。中文、日文、韩文描述会自动走转换模型；留空 `prompt.model_name` 时使用 `model_tasks.sub_actor`。

### 方式二：LLM 自主调用

插件注册了 `draw_single_image` 和 `draw_multi_image` 两个 Action，LLM 可在对话中自主判断何时生成图片。触发场景包括：

- 用户明确索图（"画一张"、"发张图"）
- 要求自拍/拍照
- 对话焦点转向视觉展示
- 文字不足以传递画面、氛围或情感

纯知识问答、技术讨论等场景不会触发。

---

## 配置

所有配置集中在：

```text
config/plugins/nai_drawer/config.toml
```

运行时缓存（首次上传后的 Vibe cache_id、复制的角色参考图）存放在：

```text
data/nai_drawer/
```

### 总开关

```toml
# 关闭后所有绘图功能（指令和 Action）均不可用
enabled = true
```

### 绘图接口

```toml
[draw_api]
base_url = "https://your-newapi-host"   # 绘图接口地址
api_key = "sk-..."                       # 绘图接口密钥
model = "nai-diffusion-4-5-full"         # 绘图模型名称
timeout_seconds = 180.0                   # 请求超时（秒）
```

### 提示词转换

```toml
[prompt]
model_name = ""          # 转换模型名称，留空使用 model_tasks.sub_actor
temperature = 0.2        # 转换随机性，越低越稳定
max_tokens = 800         # 转换输出上限
max_retries = 2          # 转换失败时最大重试次数
prompt_prefix = ""       # 破甲词，自动拼接到给翻译模型的提示词最前面
```

> **破甲词**：在自然语言描述发送给翻译模型之前，自动追加到系统提示词末尾的引导词。可用于提升翻译质量、引导模型输出特定风格或绕过限制。例如：`prompt_prefix = "请使用高质量的Danbooru标签描述，不要输出任何解释"`。

### Danbooru Tag 候选检索

Danbooru Tag 候选检索会在“中文自然语言 → 英文 Danbooru tags”之前运行，把与用户描述相关的候选 tag 注入给翻译模型，用来减少中文直译错误、角色名误翻、tag 不规范等问题。

```toml
[tag_retriever]
enabled = true
mode = "online"
api_url = "https://sakizuki-danboorusearch.hf.space/api"
timeout = 90.0
search_limit = 30
search_top_k = 5
related_limit = 20
related_seed_count = 8
show_nsfw = true
popularity_weight = 0.15
top_k = 50
min_score = 0.05
```

#### 模式选择

| 模式 | 当前状态 | 用途 |
| --- | --- | --- |
| `online` | 推荐用于完整 Danbooru 大库 | 调用 DanbooruSearchOnline API，自动执行语义搜索和共现推荐。 |
| `local` | 已可作为本地示例运行 | 读取本地 `danbooru_tags.json` 和 `tag_embeddings.npy`，使用内置字符 n-gram 哈希向量做余弦相似度检索。当前示例库包含崩坏3相关 7 个 tag。 |

> 想马上用全量 tag 请使用 `online`；想固定少量角色/作品名、避免在线候选污染，可使用 `local` 示例库。

#### 在线检索使用步骤

1. 打开 `config/plugins/nai_drawer/config.toml`。
2. 设置：

```toml
[tag_retriever]
enabled = true
mode = "online"
show_nsfw = true
```

3. 重启或热重载插件配置。
4. 使用绘图命令：

```text
/nai 来一张希娜狄雅在教室里看书的图
/naim 来一张希娜狄雅和蕾耶拉一起在学校上课的照片，俩人都穿jk，俩人是同桌
```

运行流程：

1. `/search` 按中文描述检索直接相关 tag。
2. `/related` 基于搜索结果推荐通用共现 tag。
3. 插件把候选写入 `<tag_candidates>`，交给翻译模型参考。
4. 翻译模型输出最终英文 Danbooru tags。

当前实现会过滤 `/related` 中的 `Character` 和 `Copyright` 候选，只保留通用画面类 tag，避免同作品其它角色污染结果。例如防止“蕾耶拉”被共现推荐里的 `helia` 误导。

#### 角色参考时移除角色 Tag

```toml
[tag_retriever]
suppress_character_tags_when_reference = true
```

单人 `/nai` 命中角色参考图时，插件会在翻译模型输出后移除对应 Danbooru 角色 tag，避免 NAI 内置角色形态覆盖参考图服装或形态。此功能只处理已命中的角色参考；如果没有角色参考图，最终提示词会保留翻译模型输出的角色 tag。

> 注意：即使 `mode = "online"`，角色 tag 抑制也需要本地 `data/nai_drawer/danbooru_tags.json` 里的 `Character` 条目作为“中文角色名/别名 → Danbooru tag”的映射表。

#### 在线检索参数建议

| 配置 | 推荐值 | 说明 |
| --- | --- | --- |
| `search_top_k` | `5` | 语义搜索召回数量。过大容易引入弱相关 tag。 |
| `search_limit` | `30` | API 搜索返回上限。 |
| `related_limit` | `20` | 共现推荐上限。当前只保留通用画面类 tag。 |
| `related_seed_count` | `8` | 用前几个搜索结果作为共现推荐种子。 |
| `popularity_weight` | `0.15` | 热度权重。角色名误召回时可降到 `0.0`。 |
| `show_nsfw` | `true` | 是否让服务端返回 NSFW/R-18 tag；插件不做客户端二次过滤。 |

#### 本地向量检索数据准备

本地模式读取两个文件：

```text
data/nai_drawer/danbooru_tags.json
data/nai_drawer/tag_embeddings.npy
```

仓库已提供一个可运行示例，包含：

| 中文 | Danbooru tag |
| --- | --- |
| 蕾耶拉 | `leylah_(honkai_impact)` |
| 希娜狄雅 | `senadina` |
| 赫丽娅 / 赫莉娅 | `erdos_helia` |
| 科拉莉 | `coralie_6626_planck` |
| 松雀 | `songque` |
| 瑟莉姆 / 瑟利姆 | `thelema_nutriscu` |
| 崩坏3 | `honkai_impact_3rd` |

目录结构：

```text
data/
  nai_drawer/
    danbooru_tags.json
    tag_embeddings.npy
```

`danbooru_tags.json` 必须是 UTF-8 JSON，顶层包含 `tags` 数组：

```json
{
  "tags": [
    {
      "tag": "leylah_(honkai_impact)",
      "cn_name": "蕾耶拉, 崩坏3rd",
      "category": "Character"
    },
    {
      "tag": "senadina",
      "cn_name": "希娜狄雅, 崩坏3",
      "category": "Character"
    },
    {
      "tag": "school_uniform",
      "cn_name": "校服, 制服, jk",
      "category": "General"
    }
  ]
}
```

建议字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `tag` | 是 | Danbooru 英文 tag。 |
| `cn_name` | 建议 | 中文名、别名、说明，用于构建 embedding 文本。 |
| `category` | 建议 | `General`、`Character`、`Copyright`、`Artist`、`Meta` 等。 |

`tag_embeddings.npy` 是 numpy 保存的二维浮点矩阵：

```text
shape = (len(tags), embedding_dim)
```

要求：

- 第 1 行向量对应 `danbooru_tags.json` 的第 1 个 tag。
- 第 2 行向量对应第 2 个 tag，以此类推。
- 行数必须等于 `len(tags)`。
- 示例库使用插件内置的 `build_hash_embedding()` 生成本地字符 n-gram 哈希向量，不需要外部 embedding API。
- 如果你替换成真实 embedding 模型，预计算 tag embedding 和运行时 query embedding 必须使用同一个模型。

重新生成示例向量：

```python
import json
from pathlib import Path

import numpy as np

from plugins.nai_drawer.client.tag_retriever import (
    build_hash_embedding,
    build_tag_embedding_text,
)

base = Path("data/nai_drawer")
with open(base / "danbooru_tags.json", "r", encoding="utf-8") as f:
    tags = json.load(f)["tags"]

embeddings = np.stack([
    build_hash_embedding(build_tag_embedding_text(item), dim=256)
    for item in tags
]).astype("float32")

np.save(base / "tag_embeddings.npy", embeddings)
```

#### 启用本地模式

准备好两个文件后修改配置：

```toml
[tag_retriever]
enabled = true
mode = "local"
top_k = 50
min_score = 0.05
```

然后重启或热重载插件。

本地模式会把检索结果写入 `<tag_candidates>`，再交给翻译模型参考。示例：用户输入“蕾耶拉和希娜狄雅”，本地候选会优先包含 `leylah_(honkai_impact)` 与 `senadina`。

#### 本地模式日志

文件存在时会看到类似日志：

```text
加载本地 tags 文件: data/nai_drawer/danbooru_tags.json
加载 embedding 矩阵: data/nai_drawer/tag_embeddings.npy
本地库已加载: 7 个 tags，embedding 维度 (7, 256)
本地向量检索完成：query='蕾耶拉和希娜狄雅' → search=2 条
```

#### 扩展本地库

1. 在 `danbooru_tags.json` 的 `tags` 数组中追加 tag。
2. 为 `cn_name` 和 `aliases` 写清中文名、常见错别字、英文别名和作品名。
3. 用上面的脚本重新生成 `tag_embeddings.npy`。
4. 重启或热重载插件。

#### 排查指南

没有任何候选时检查：

1. `enabled = true`。
2. `mode` 是否为 `online` 或 `local`。
3. `online` 模式下 API 是否超时。
4. `local` 模式下两个数据文件是否存在。
5. `local` 模式下 `min_score` 是否过高；示例库可先用 `min_score = 0.05` 验证召回。

候选太杂时可调低：

```toml
search_top_k = 3
popularity_weight = 0.0
related_limit = 10
```

### 角色参考

> ⚠ 需要站点支持 reference 功能。

```toml
[characters]
selfie = "看板娘"        # 自拍场景使用的角色预设名

[characters."看板娘"]
image_path = "config/plugins/nai_drawer/characters/看板娘.jpg"  # 角色参考图路径
type = "character"       # 参考类型：character / style / character&style
fidelity = 1.0           # 保真度，越高越忠于参考图（0.0~2.0）
strength = 1.0           # 参考强度，越高参考图影响越大（0.0~1.0）
alias_names = ["小看板"]  # 角色别名，识别到别名也会触发该角色参考
enabled = true           # 是否启用
```

首次绘图时会复制图片到 `data/nai_drawer/characters/` 并上传。

### Vibe 画风迁移

> ⚠ 需要站点支持 vibe 功能。

```toml
[vibes]
active = "清新画风"      # 默认启用的 Vibe 预设名

[vibes."清新画风"]
image_path = "config/plugins/nai_drawer/vibes/清新画风.jpg"  # Vibe 参考图路径
reference_strength = 0.6       # 参考强度，越高 Vibe 影响越大（0.0~1.0）
information_extracted = 0.7    # 信息提取量，越高越保留参考图细节（0.0~1.0）
enabled = true                 # 是否启用
```

首次使用时请求 `cache_id` 并写入 `data/nai_drawer/preset_cache.json`。

> ⚠ **角色参考与 Vibe 互斥**：同时配置时角色参考优先，Vibe 不会生效。

### 画风与人设

```toml
[style]
prefix = "masterpiece, best quality, "   # 全局画风前缀，自动拼接到提示词最前

[bot]
persona_prompt = "银发少女，蓝色眼睛，白色连衣裙"  # BOT 外貌与人设
selfie_keywords = ["自拍", "selfie"]               # 触发自拍模式的关键词
```

### 绘图参数

```toml
[generation]
negative_prompt = "lowres, bad anatomy, ..."   # 负向提示词
width = 832                                     # 图片宽度（64 的倍数）
height = 1216                                   # 图片高度（64 的倍数）
steps = 23                                      # 迭代步数（最大 28）
scale = 5.0                                     # 提示词引导强度
sampler = "k_euler_ancestral"                   # 采样器
noise_schedule = "karras"                       # 噪声调度
variety_boost = false                           # 变化增强（Variety+）
cfg_rescale = 0.0                               # 引导重缩放
image_format = "png"                            # 输出格式：png / webp
max_tokens = 100000                             # 最大预算（10000 token ≈ 1 Anlas）
```

## 目录结构

```text
plugins/nai_drawer/
├── plugin.py
├── config.py
├── command.py
├── action.py
├── client/
│   ├── danbooru_online_retriever.py
│   ├── image_client.py
│   ├── prompt_client.py
│   ├── tag_candidate_resolver.py
│   └── tag_retriever.py
├── service/
│   ├── draw_service.py
│   └── preset_service.py
├── store/
│   └── preset_store.py
└── constants/
    └── system_prompt.py
```

## 多人场景

转换模型在检测到 2~6 个可区分角色时，会输出 JSON 并自动附带 `characters` 参数（V4/V4.5 多角色定位）。单人场景仍输出纯英文 tag 字符串。
