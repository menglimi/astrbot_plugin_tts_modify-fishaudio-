# fishaudio tts日语优化 插件说明

`astrbot_plugin_tts_modify-fishaudio-` 是面向 AstrBot 的 FishAudio TTS 日语优化插件。它在原插件基础上保留 `<tts>...</tts>` 标签模式，并补充日语文本清洗、随机日语语音模式、原中文文本保留与短文本触发控制等能力。

当前插件内部唯一名为 `astrbot_plugin_tts_modify-fishaudio-`，对外展示名为 `FishAudio TTS 日语优化`。

启用插件后，可对特定文本进行TTS请求。实现LLM根据对话情绪自主调用TTS。  
仅对被`<tts></tts>`标记的文本进行TTS请求。  

## 原插件与改造说明

- 当前插件内部名：`astrbot_plugin_tts_modify-fishaudio-`
- 原插件：`astrbot_plugin_tts_modify`
- 原作者：`L1ke40oz`
- 原仓库：[L1ke40oz/astrbot_plugin_tts_modify](https://github.com/L1ke40oz/astrbot_plugin_tts_modify)
- 当前改版仓库：[menglimi/astrbot_plugin_tts_modify-fishaudio-](https://github.com/menglimi/astrbot_plugin_tts_modify-fishaudio-)
- 当前版本定位：针对 FishAudio TTS 的日语朗读场景做专项优化，并补充自动随机日语语音能力。

## 本次更改总结

- 新增“随机日语语音模式”，可在发送阶段按概率拦截纯文本回复。
- 命中后，会先将原中文回复转换为适合朗读的日语文本，再生成日语语音。
- 自动模式现在会优先生成更连贯的混合输出：允许在 `<tts>` 前保留少量中文铺垫，把更适合强调或收尾的后半句转成日语语音，再复用原有 TTS 标签解析链路发送。
- 新增“完全转换模式”：VTube 插件的 B站直播弹幕监听运行时始终使用完整转换；开关开启后，所有自动日语语音也都会使用完整转换。
- 新增“自动播放TTS语音”：开启后，每次 TTS 音频成功生成并进入发送流程时，会在对应时机自动播放这段语音。
- 新增“联动VTube打字机字幕”：每次成功生成 TTS 音频时，可把实际朗读文本同步推送到 `astrbot_plugin_vtube_studio` 的字幕 overlay。
- 自动模式会保留首个 `<tts>...</tts>` 语音片段，并对标签前后的中文做去重裁剪，尽量避免“前一句中文和语音说的是同一句话”这种重复感。
- 如果原消息链里已经包含语音组件，自动模式会直接跳过，不再重复做日语语音转换。
- 新增会话级触发冷却，避免短时间内连续高频触发自动日语语音。
- 最终发送形式更偏向“少量中文铺垫 + 日语语音收尾”或“中文文本与日语语音自然衔接”的混合表达，而不是固定整段重复。
- 新增最大字数限制，只有短文本回复才会触发，避免长消息频繁进入翻译与 TTS。
- 新增群聊管理员专用概率，可按填写的管理员 QQ 号单独设置更高或更低的自动日语语音命中率。
- 当显式设置了群聊管理员专用概率后，管理员规则会优先于普通“最大字数限制”执行，避免两套条件互相冲突。
- 当管理员 QQ 命中概率时，插件会在 LLM 请求阶段额外注入“本次回复需要包含语音消息”，优先引导模型直接输出带语音标签的回复；如果模型没按要求输出，发送阶段仍会自动兜底补成语音。
- 群聊里如果有人 `@` 到已配置的管理员 QQ，也会被识别为管理员目标消息，并参与上面的提示词注入判定。
- 新增“@管理员 + 关键词词条”专用规则，并改成类似世界书的可视化词条配置：每条词条可单独设置启用状态、多个关键词、概率、冷却时间、每天最多一次、每人每天最多一次开关和提示词。例如 `[At:995051631] 摸摸`。
- 保留原有 `<tts>...</tts>` 显式标签模式，两种模式互不冲突。
- 自动模式默认只处理纯文本回复；如果消息中混有图片、卡片等其他组件，则不会自动拦截。
- 将自动模式相关默认值与配置读取统一收口，减少代码中的硬编码与重复默认值。

### 当前默认配置

- `auto_japanese_voice_enabled = false`
- `auto_japanese_voice_full_conversion_enabled = false`
- `local_audio_playback_enabled = false`
- `vtube_subtitle_sync_enabled = false`
- `auto_japanese_voice_probability = 20`
- `auto_japanese_voice_admin_user_ids = ""`
- `auto_japanese_voice_admin_probability = -1`
- `admin_mention_keyword_voice_entries = []`
- `admin_mention_keyword_voice_keywords = ""`
- `admin_mention_keyword_voice_probability = 0`
- `auto_japanese_voice_max_chars = 50`
- `auto_japanese_voice_cooldown_seconds = 120`

也就是说，默认安装后不会自动启用；启用后，只有纯文本、未自带语音、长度不超过 `50` 字的回复，才会按 `20%` 概率触发，且同一会话两次成功触发之间默认至少间隔 `120` 秒。

其中，`auto_japanese_voice_admin_probability = -1` 表示已填写的管理员 QQ 默认继承全局概率；只有你显式改成 `0-100` 之间的值时，才会对这些管理员 QQ 启用单独概率，并优先于普通“最大字数限制”执行。

如果你额外配置了“@管理员 + 关键词词条”规则，那么这条专用规则会优先于普通的 `@管理员` 提示词注入逻辑：当群聊消息同时满足“@到管理员 QQ”和“文本命中词条关键词”时，会先按命中词条自己的独立概率、冷却时间和提示词决定是否注入。

另外，这个版本支持可选的“随机日语语音模式”：
- 插件会在发送阶段按概率拦截纯文本回复。
- 命中后，会将原中文回复翻译成适合朗读的日语来生成语音。
- 最终发送形式为：`日语语音 + 原中文文本`。
- VTube 插件的 B站直播弹幕监听正在运行时，会始终把整条原回复完整转换成语音；非直播消息默认仍使用混合表达策略。开启 `auto_japanese_voice_full_conversion_enabled` 后，非直播消息也会使用完整转换。
- 默认只处理纯文本回复；如果回复里混有图片、卡片等其他组件，则不会自动拦截，避免影响原有消息结构。

## 配置项说明

TTS触发提示词：在发送LLM请求前，插件会将`tts_prompt`动态注入到System Prompt末尾。提示词可自行修改。

⚠️注意：`<tts></tts>`标签是必要的，即使要修改提示词，也不可省略。

### 随机日语语音模式

- `auto_japanese_voice_enabled`：是否启用随机拦截模式。
- `auto_japanese_voice_full_conversion_enabled`：完全转换模式。默认关闭。直播模式不受此开关影响，会始终完整转换；开启后，非直播消息也会把整条回复完整翻译成一段日语语音，避免只转换前半句、后半句或单个片段。
- `local_audio_playback_enabled`：自动播放TTS语音。开启后，显式 `<tts>` 和自动模式只要成功生成音频，都会在对应时机自动播放同一个音频文件。
- `vtube_subtitle_sync_enabled`：联动VTube打字机字幕。开启后，显式 `<tts>` 和自动模式只要成功生成音频，都会把实际朗读文本推给 `astrbot_plugin_vtube_studio` 的字幕 overlay。需要 VTube 插件自身已启用 `subtitle_enabled`。
- `auto_japanese_voice_probability`：随机触发概率，范围 `0-100`。
- `auto_japanese_voice_admin_user_ids`：群聊中的管理员 QQ 列表，支持逗号、空格或换行分隔。管理员本人发言，以及别人 `@` 到这些 QQ 时，都会被识别为管理员目标消息。
- `auto_japanese_voice_admin_probability`：这些管理员 QQ 的专用触发概率，范围 `-1-100`；`-1` 表示继承全局概率，`0-100` 表示启用管理员优先规则，并跳过普通最大字数限制。管理员 QQ 同时不受冷却限制。
- `admin_mention_keyword_voice_entries`：推荐使用的新词条配置，面板形式参考世界书插件。每条词条都可以单独设置 `名称`、`启用`、`关键词列表`、`触发概率(%)`、`冷却秒数`、`每天最多一次`、`每人每天最多一次`、`提示词`。
- `admin_mention_keyword_voice_entries`：每个词条的 `关键词列表` 支持逗号、分号或换行分隔；命中其中任意一个关键词都会进入这条词条。
- `admin_mention_keyword_voice_entries`：仅在群聊里“`@管理员 + 命中关键词`”时生效。多个词条或多个关键词同时命中时，优先更长的关键词；长度相同则按配置顺序。
- `admin_mention_keyword_voice_entries`：词条命中且概率成功后，会把该词条的提示词注入到本次请求中；插件会自动补上“本次回复需要包含语音消息”。
- `admin_mention_keyword_voice_keywords` / `admin_mention_keyword_voice_probability` / `admin_mention_keyword_voice_prompt`：旧版兼容配置，默认已隐藏。只有当 `admin_mention_keyword_voice_entries` 为空时才会回退使用。
- `auto_japanese_voice_max_chars`：只有回复长度不超过该值时才会触发，`0` 表示不限制；若管理员优先规则已启用，则管理员消息不受此限制。
- `auto_japanese_voice_cooldown_seconds`：同一会话内自动日语语音的触发冷却秒数，`0` 表示不限制；已配置的管理员 QQ 不受此限制。
- `auto_japanese_voice_translate_prompt`：将中文回复转换成日语语音输出时使用的提示词。混合表达时使用原提示词；直播模式或完全转换开关生效时，插件会额外追加“整段完整转换”的要求。如果只输出纯日语文本，插件也会自动补成语音并在后面附上原中文。

词条示例：
- 名称：`摸摸回应`
- 关键词列表：`摸摸, 贴贴, 蹭蹭`
- 触发概率：`100`
- 冷却秒数：`30`
- 每天最多一次：`开启`
- 每人每天最多一次：`开启`
- 提示词：`请温柔地用语音回应对方的撒娇请求。`

上面的含义分别是：
- 关键词列表：消息里只要包含其中任意一个文本，就算命中这条词条。
- 概率：命中这条词条时的单独触发概率。
- 冷却秒数：同一会话里，这条词条两次成功触发之间至少间隔多久。
- 每天最多一次：开启后，这条词条在同一会话里每天最多成功触发一次。
- 每人每天最多一次：开启后，这条词条对同一个发送者每天最多成功触发一次。
- 提示词：本次请求追加注入的专用提示词。

建议：
- 如果你希望只让短句触发，可以把最大字数设为 `30-60`。
- 如果你希望偶尔冒出一条“日语语音+中文字幕”的回复，可以先把概率设为 `10-30`。
- 如果你希望某几个管理员 QQ 更容易触发，可以保持全局概率较低，例如 `10`，再把管理员概率单独设为 `40-80`。
- 如果你希望像“`@管理员 摸摸`”“`@管理员 抱抱`”“`@管理员 贴贴`”这类消息共用同一种回复风格，可以直接在同一个 `admin_mention_keyword_voice_entries` 词条里填写多个关键词。
- 如果你希望每次纯文本回复都附带日语语音，可以直接设为 `100`。

<img src="https://github.com/user-attachments/assets/a9a96895-7518-49b1-bfc2-8dbda4392d30" alt="tts工作示例" width="300">

## 使用限制与注意事项

### 1. 标签规范
插件严格解析 `<tts>内容</tts>` 标签。
- **不支持嵌套**：如 `<tts>外层<tts>内层</tts></tts>` 会导致解析错误。
- **必须闭合**：标签必须成对出现，否则可能被忽略或解析异常。
- **位置**：支持在文本的任意位置插入标签，支持多个标签。

### 2. 安全与资源
- **文件路径**：插件会对 TTS 生成的音频文件路径进行安全校验，仅允许 AstrBot 数据目录下的文件。
- **临时文件**：若启用了文件服务（File Service），生成的音频 URL 对应的临时文件由 AstrBot 的 `file_token_service` 管理。

### 3. 错误处理
- **降级策略**：若 TTS 生成失败或路径不安全，插件会自动降级为纯文本回复，剥离 `<tts>` 标签。
- **失败通知**：可在配置中开启 `notify_on_failure`，当 TTS 失败时会在回复中添加提示。

---

😸经测试，无论`<tts></tts>`标签前后是否带有分段正则表达式，都不会影响TTS请求，可放心食用！  
当前改版仓库：[menglimi/astrbot_plugin_tts_modify-fishaudio-](https://github.com/menglimi/astrbot_plugin_tts_modify-fishaudio-)  
原插件仓库：[L1ke40oz/astrbot_plugin_tts_modify](https://github.com/L1ke40oz/astrbot_plugin_tts_modify)  
兼容修改参考：[AstrBot_mod](https://github.com/L1ke40oz/AstrBot_mod) 
