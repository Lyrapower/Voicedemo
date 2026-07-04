## JarvisCoach – 实时对话军师提词器（iOS）

JarvisCoach 是一个面向 iPhone / iPad 的 SwiftUI MVP，用来在真实通话 / 会议中提供「下一句建议」的实时 HUD。

- **平台**: iOS 17+，SwiftUI，AVAudioEngine，Speech (SFSpeechRecognizer)
- **AI**: 直连 Anthropic Claude Messages API（无后端）
- **场景**: Pitch / Q&A / Negotiation / Sales 等实时对话辅助

### 功能概览

- **实时转写**: 使用系统 Speech framework 对麦克风输入进行中英文混合实时转写。
- **智能建议**: 根据最近对话窗口 + 话术库 talk tracks，调用 Claude 生成最多 2 句、无问号、偏直接回答的建议。
- **HUD 显示**: 全屏两行大号文字，稳定不闪烁、平滑替换新建议。
- **模式与语言**: 支持 Mode（Pitch / Q&A / Negotiation / Sales）与 Language（Auto / EN / ZH）选择。
- **话术库**: `talk_tracks.yaml` 提供默认话术，每种模式可编辑并持久化到本地，支持一键恢复默认。
- **Debug 折叠区**: 仅显示最近一句转写、更新时间与最近一次延迟，可一键清空，不持久化到磁盘。

### 快速启动

完整从零运行步骤见仓库根目录的 `RUN.md`。核心步骤包括：

- 使用 Xcode 15+ 打开 iOS 工程。
- 在 `ios/Config/Secrets.xcconfig` 中配置 `ANTHROPIC_API_KEY`（文件不进版本管理）。
- 确认 Target 的 Build Settings 已加载 Secrets 配置。
- 真机运行，授予麦克风、语音识别与网络权限。

### 安全与隐私

- **不落盘转写**: 转写内容只保存在内存中，不写入磁盘或日志文件。
- **密钥管理**: Anthropic API Key 通过 Xcode `.xcconfig` 注入，示例见 `ios/Config/Secrets.xcconfig.example`，真实文件被 `.gitignore` 忽略。
- 详细安全策略请见 `docs/SECURITY.md`。

### 架构概览

- **Audio 层**: `AudioSessionManager` 管理 AVAudioSession 和 AVAudioEngine。
- **Speech 层**: `SpeechTranscriber` 负责连续语音识别、语言自动识别与稳定段落检测。
- **Networking 层**: `AnthropicClient` 通过 `URLSession` 调用 Claude Messages API；`PromptBuilder` 负责组装系统 Prompt 与用户内容。
- **Core 层**: `Debouncer`、`DisplayProvider` 接口、核心模型与 Session ViewModel。
- **UI 层**: `HomeView`、`LiveHUDView`、`ScriptLibraryView`、`SettingsView` 以及基础组件 `BigCard`、`DebugFold`。

更详细的模块和数据流说明见 `docs/ARCHITECTURE.md`。

