## ARCHITECTURE – JarvisCoach 结构说明

### 1. 总体结构

- **App 层**: `JarvisCoachApp.swift` – SwiftUI 入口，注入 `SessionViewModel`。
- **Core 层**:
  - `Models.swift` – 核心枚举与数据结构（Mode / Language / Speaker / TalkTracks / SessionViewModel）。
  - `Debouncer.swift` – 用于节流 Claude 请求。
  - `DisplayProvider.swift` – 抽象显示接口，为未来眼镜 / 外接屏预留。
  - `TalkTracksLoader.swift` – 加载话术库（bundle YAML + 用户覆盖 JSON）。
- **Audio & Speech 层**:
  - `AudioSessionManager.swift` – AVAudioSession + AVAudioEngine 管理（当前转写直接在 Speech 层独立实现）。
  - `SpeechTranscriber.swift` – SFSpeechRecognizer 包装，负责连续识别、稳定 utterance 检测。
- **Networking 层**:
  - `AnthropicClient.swift` – 调用 Claude Messages API，处理 HTTP 请求与响应解析。
  - `PromptBuilder.swift` – 组装严格受控的 System Prompt 与 User Content。
- **UI 层**:
  - `HomeView.swift` – 入口页，设置 Mode / Language，进入 Session / Script Library / Settings。
  - `LiveHUDView.swift` – 核心 HUD，两行大字建议 + 控制按钮 + Debug 折叠。
  - `ScriptLibraryView.swift` – 话术库编辑与重置。
  - `SettingsView.swift` – 高级开关（例如 Q&A 模式 ask-back）。
  - `Components/BigCard.swift` – Home 卡片组件。
  - `Components/DebugFold.swift` – HUD 右上角 Debug 折叠组件。
- **Resources**:
  - `talk_tracks.yaml` – bundle 默认话术库。

### 2. 实时链路

1. **音频采集与转写**
   - `SpeechTranscriber.startTranscribing()`：
     - 请求语音识别 + 麦克风权限。
     - 启动 `AVAudioEngine` 并建立音频 tap。
     - 创建 `SFSpeechAudioBufferRecognitionRequest` 并持续向其追加 buffer。
   - `recognitionTask` 的回调中：
     - 更新当前转写文本缓冲；
     - 检测 final 结果或 800ms 无更新时，触发 `onStableUtterance(utterance, isFinal)`。

2. **节流 / 去抖 + 调用 Claude**
   - `SessionViewModel.bindTranscriber()`：
     - 在 `onStableUtterance` 中更新 `lastUtterance`（供 Debug 显示）。
     - 仅在 `SpeakerRole == .them` 且未暂停时，调用 `Debouncer.execute`。
   - `Debouncer` 在 800ms 后执行闭包，触发 `requestSuggestion`：
     - 检查与上次调用 Claude 的间隔 >= 1.2 秒（节流）。
     - 构造：
       - `recentTranscriptWindow()` – 最近 30–60 秒窗口（用字符数近似截断）。
       - `lastQuestion()` – 简化版最近问题文本。
       - 当前 Mode 话术 bullets（最多 5 条）。
     - 调用 `PromptBuilder.build(...)` 生成 System/User 文本。
     - 调用 `AnthropicClient.generateSuggestion(...)`，超时 ~10 秒。

3. **HUD 展示**
   - 成功后，`SessionViewModel` 更新 `suggestion.text / lastUpdated / lastLatency`，并将 `claudeState` 置为 `.ok`。
   - `LiveHUDView` 绑定这些状态，以大字号文本展示建议，并带有轻微淡入缩放动画。
   - UI 保持全屏黑色背景，防止色彩干扰，保证稳定阅读。

### 3. HUD 控件行为

- **Pause/Resume**:
  - 切换 `isPaused` 状态。
  - 当 `isPaused == true` 时，即便有新的 stable utterance，也不会触发 Claude 调用。
- **Shorter**:
  - 显式调用 `requestSuggestion(forceShorter: true, moreDirect: false)`，在 Prompt 中加入“更短、更精炼”的约束。
- **More direct**:
  - 显式调用 `requestSuggestion(forceShorter: false, moreDirect: true)`，在 Prompt 中加入“更直接、少铺垫”的约束。
- **Reset**:
  - 清空 `lastUtterance` 和 `suggestion` 状态；
  - 调用 `SpeechTranscriber.resetContext()` 清空内部转写 buffer。

### 4. Claude 输出约束（由 PromptBuilder 实现）

- System Prompt 中硬性说明：
  - 最多两句；
  - 默认禁止问号；
  - 第一句直接回答，第二句补充价值/下一步；
  - 语气专业、自信、不营销、不提及 AI 身份；
  - 中英文混合策略依据 Language 设定（Auto/EN/ZH）。
- User Content 中补充：
  - 最近对话窗口；
  - `last_question`；
  - 当前 Mode 下话术 bullets（只作参考，不要求逐字输出）。

### 5. DisplayProvider 抽象

- `DisplayProvider` 定义：

  ```swift
  protocol DisplayProvider {
      func display(text: String)
  }
  ```

- 当前实现：
  - `PhoneDisplayProvider` 为空实现，实际由 SwiftUI 直接绑定 ViewModel。
- 未来扩展：
  - 新增如 `GlassesDisplayProvider` / `ExternalScreenDisplayProvider`，在 SessionViewModel 中注入并在更新建议时同时调用，以驱动外部设备 HUD。

