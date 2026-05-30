# NAI Drawer

Neo-MoFox 插件：通过 NovelAI（OpenAI 兼容接口）生成图片，支持 `/tag`、`/nai`、画风预设、角色参考、自拍角色、Vibe 缓存预设和普通聊天工具调用。

## 基础绘图

```text
/tag 1girl, solo, masterpiece, best quality, detailed eyes
/nai 一个白裙女孩站在森林里，柔和光线
```

`/tag` 会把英文 tag 直接发送给绘图 API。绘图 API 要求英文提示词，所以中文、日文假名、韩文和全角字符会在请求前被拒绝。

`/nai` 会先调用 `prompt_api`，把自然语言转换成英文绘图提示词，再调用绘图 API。

## 角色参考

保存角色参考：

```text
/保存角色
[同时附带一张图片]
```

Bot 会固定询问参考方式，只输入数字，不要输入其他内容：

```text
1 只参考角色
2 只参考画风
3 角色和画风都参考
```

用户选择后，Bot 会继续要求输入角色预设名称。保存后的图片会放在：

```text
config/plugins/nai_drawer/characters/
```

角色预设配置会放在：

```text
config/plugins/nai_drawer/characters.toml
```

单次使用角色参考绘图：

```text
/参考 看板娘 standing in a forest, soft light
/参考 看板娘 站在森林里，柔和光线
```

只有使用 `/参考 <角色预设名> <提示词>` 时才会上传该角色参考。普通 `/tag`、`/nai`、工具绘图不会因为文本里出现预设名就自动调用角色参考。

设置自拍角色：

```text
/自拍角色 看板娘
```

使用自拍角色绘图：

```text
/自拍 在窗边微笑，柔和阳光
```

只有 `/自拍 <提示词>` 会使用 `/自拍角色` 设置的角色参考。自动判断出来的“自拍”需求不会使用这个角色参考。

角色参考优先级高于 Vibe。如果一次绘图使用了 `character_references`，插件不会再附加 Vibe，因为 API 文档说明 `controlnet` 和 `character_references` 互斥。

## Vibe

创建 Vibe 预设：

```text
/Vibe 清新画风
[同时附带一张图片]
```

Bot 会固定回复参数说明，不调用模型。用户只能回复两个数字，用空格隔开，不要输入其他内容：

```text
0.6 0.7
```

第一个数字是 `Reference Strength`，第二个数字是 `Information Extracted`，范围都是 `0.01` 到 `1`。插件会用这张图请求绘图 API，让接口回传 `vibe_cache_ids`，然后把 `cache_id` 保存到：

```text
config/plugins/nai_drawer/vibe_presets.toml
```

加载或关闭 Vibe：

```text
/Vibe 清新画风
/Vibe 关闭
```

只要当前 Vibe 没关闭，后续 `/tag`、`/nai`、`/参考`、`/自拍` 和 `draw_image` 工具绘图都会默认上传当前 Vibe 的 `cache_id`，但角色参考存在时会跳过 Vibe。

## 画风

```text
/保存画风 厚涂 masterpiece, best quality, painterly style, 
/加载画风 厚涂
```

画风预设保存位置：

```text
config/plugins/nai_drawer/styles.toml
```

加载画风后，画风词条会放在用户提示词最前面。例如当前画风内容是 `123`，用户输入是 `456`，最终发送给绘图 API 的提示词就是 `123456`。

## 工具

插件注册了 LLM 工具：

```text
draw_image
```

当用户在正常聊天里明确提出绘图、生成图片、发张图、想要自拍等需求时，Bot 可以调用该工具。工具会使用 `prompt_api` 转换当前需求，套用当前画风和当前 Vibe，然后把生成图发回当前聊天。工具不会自动使用已保存的角色参考，也不会使用 `/自拍角色` 保存的图片。

## BOT 人设

BOT 人设配置保存位置：

```text
config/plugins/nai_drawer/profile.toml
```

这个文件会自动生成。用户可以手动填写 BOT 人设。`/自拍 <提示词>` 可按需要使用这些人设文字参与提示词转换；模型工具自动判断出的自拍需求不会调用 `/自拍角色` 里的角色参考图。

## 配置

插件加载一次后会生成：

```text
config/plugins/nai_drawer/config.toml
```

绘图接口：

```toml
[draw_api]
base_url = "https://your-newapi-host"
api_key = "sk-..."
model = "nai-diffusion-4-5-full"
```

自然语言转换接口：

```toml
[prompt_api]
enabled = false
base_url = "https://your-llm-host"
api_key = "sk-..."
model = "gpt-4.1-mini"
system_prompt = "请在这里填写自然语言转绘图提示词的系统提示词。"
```

插件不内置转换提示词内容，需要用户自己替换 `prompt_api.system_prompt`。

请求会发送到 `/v1/chat/completions`。内部绘图参数会序列化成 JSON，放入 `messages[0].content`。
