## JarvisCoach RUN 手册（从零到跑起来）

本手册假设你使用的是 **Xcode 15+**，目标设备为 **iOS 17+ 真机**。

### 1. 获取代码并打开工程

1. 打开 Finder，进入 `JarvisCoach` 目录。
2. 双击打开 `ios/JarvisCoach.xcodeproj`（如果 Xcode 要求迁移/升级，按提示操作即可）。

### 2. 配置 Anthropic API Key（Secrets.xcconfig）

1. 在 `JarvisCoach/ios/Config` 目录下复制示例文件：

   ```bash
   cd JarvisCoach/ios/Config
   cp Secrets.xcconfig.example Secrets.xcconfig
   ```

2. 用任意文本编辑器打开新生成的 `Secrets.xcconfig`，将其中的占位符替换为你的真实密钥：

   ```text
   ANTHROPIC_API_KEY=sk-ant-xxxxxx_your_real_key_here
   ```

3. 在 Xcode 中，选中 `JarvisCoach` Target：
   - 打开 **Project Navigator** → 选中最上层的 `JarvisCoach` 工程。
   - 在 **TARGETS → JarvisCoach → Build Settings** 中找到 **User-Defined** 部分，确认已包含 `ANTHROPIC_API_KEY` 的引用（工程模板已将 `Secrets.xcconfig` 连接到 Debug/Release 的 xcconfig 中；如需检查，可在 **Info → Configurations** 中确认每个 Configuration 都引用了对应的 `.xcconfig` 文件）。

> 注意：`Secrets.xcconfig` 已在 `.gitignore` 中忽略，**不要**将真实密钥提交到版本库。

### 3. 首次构建与依赖

本工程只依赖系统框架（SwiftUI / AVFoundation / Speech），**不需要 CocoaPods / Swift Package 额外安装**。

1. 在 Xcode 左上角 Scheme 菜单中选择一个 **真机设备**（推荐 iPhone 14/15 系列，iOS 17+）。
2. 按 `Cmd + B` 进行一次完整 Build，确认编译通过。

### 4. 权限配置与首次运行

首次在真机上运行时，系统会依次弹出以下权限弹窗：

- **麦克风权限**（Microphone）
- **语音识别权限**（Speech Recognition）
- **网络访问**（用于调用 Claude API，通常由系统透明管理）

请全部选择 **允许 / Allow**。

运行步骤：

1. 在 Xcode 中点击左上角 **Run ▶** 按钮，将 App 安装到真机上。
2. 首次启动时，按提示同意麦克风与语音识别权限。
3. 进入 Home 页面后，选择 Mode / Language，点击 **Start Session** 进入 Live HUD。

### 5. 快速验证闭环（2 秒级延迟）

1. 在 Live HUD 中确认顶部状态显示 `Claude: OK`。
2. 保持右上角 Debug 折叠，默认只看中间两行大字。
3. 保持默认说话人切换为 **Them**（用于模拟对方说话）：
   - 你可以自己读一段“对方问题”，例如：
     - 「你们和竞品的差异是什么？」
   - 在 1–2 秒内，应看到 HUD 给出最多两句、无问号的建议。
4. 切换到 **Me** 再说话，应只更新上下文，不再触发新的建议。

详细的验收用例见 `docs/VERIFY.md`。

### 6. 常见问题

- **没有看到建议 / 一直显示 AI unavailable**
  - 检查 `Secrets.xcconfig` 中的 `ANTHROPIC_API_KEY` 是否正确。
  - 确保真机联网正常（Wi‑Fi 或蜂窝网络）。
- **编译错误：找不到 ANTHROPIC_API_KEY**
  - 检查是否已经创建 `Secrets.xcconfig`，并确认 Xcode 的 Build Configuration 已引用对应的 xcconfig。
- **语音识别无结果**
  - 在系统设置中检查此 App 的麦克风和语音识别权限是否被关闭，如被关闭，重新开启后再尝试。

