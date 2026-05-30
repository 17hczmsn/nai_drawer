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
/nai 两个女孩在咖啡厅里聊天
/nai 自拍
```

`/nai` 会把自然语言转换为英文 Danbooru tag，再调用绘图 API。中文、日文、韩文描述会自动走转换模型；留空 `prompt.model_name` 时使用 `model_tasks.sub_actor`。

### 方式二：LLM 自主调用

插件注册了 `draw_image` Action，LLM 可在对话中自主判断何时生成图片。触发场景包括：

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
├── client/
│   ├── image_client.py
│   └── prompt_client.py
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
