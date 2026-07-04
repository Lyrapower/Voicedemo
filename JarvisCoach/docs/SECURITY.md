## SECURITY – 密钥管理与隐私策略（JarvisCoach）

本文件描述 JarvisCoach MVP 在密钥管理与隐私方面的基本约束。

### 1. 密钥管理（Anthropic API Key）

- **注入方式**: 通过 Xcode 的 `.xcconfig` 注入，不在代码中硬编码。
- **示例文件**: `ios/Config/Secrets.xcconfig.example`，包含占位值：

  ```text
  ANTHROPIC_API_KEY=YOUR_ANTHROPIC_KEY_HERE
  ```

- **真实文件**: `ios/Config/Secrets.xcconfig` 由开发者本地创建，并在 `.gitignore` 中显式忽略：

  ```text
  ios/Config/Secrets.xcconfig
  ```

- **运行时读取**: `AnthropicClient` 通过以下顺序获取 key：
  - 首选进程环境变量 `ANTHROPIC_API_KEY`；
  - 其次读取 Info.plist 中的 `ANTHROPIC_API_KEY`（由 Xcode Build Settings/xcconfig 注入）。

### 2. 数据流与隐私

#### 2.1 音频与转写

- 麦克风音频仅用于本地实时转写，通过 iOS Speech framework（SFSpeechRecognizer）处理。
- JarvisCoach **不**将原始音频写入磁盘，也不自己上传音频到除 Apple / Anthropic 以外的任意服务。
- 转写文字仅保存在内存中，用于：
  - 生成最近 30–60 秒对话窗的文本；
  - 在 Debug 折叠区显示“最近一句转写”。

#### 2.2 不落盘策略

- 应用本身不会将完整转写内容写入 Documents/Cache 等持久化目录。
- 唯一持久化的数据是：
  - 话术库用户覆盖文件 `talk_tracks_overrides.json`（不含实际对话内容，仅为预设话术配置）。
- Debug 折叠区只展示最近一句转写与延迟信息，不提供导出或长期历史列表。

### 3. 与 Anthropic API 的交互

- 调用接口：`https://api.anthropic.com/v1/messages`。
- 传输内容：
  - 最近 30–60 秒内简要对话窗口（文本，经过窗口截断）；
  - `last_question`（对方最新问题的文本）；
  - 当前 Mode 下的最多 5 条话术 bullet。
- 模型参数：
  - `max_tokens = 60`（控制输出长度）；
  - `temperature = 0.2`（偏稳定，不随机）。
- 不在请求中夹带用户真实身份信息或显式账号标识（如邮箱、手机号等），仅使用对话内容本身。

### 4. 未来增强方向（非当前 MVP 范围）

- 支持在 App 内提供隐私说明页面，明确说明音频与文本的用途及发送范围。
- 加入本地加密存储机制，用于可选的“会话回放”功能（默认关闭）。
- 针对不同合规要求（如 GDPR）的数据最小化与保留策略配置。

