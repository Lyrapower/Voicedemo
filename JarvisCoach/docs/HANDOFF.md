## HANDOFF – 真机演示指南（JarvisCoach）

本手册帮助你在 5–10 分钟内在真机上完成一次可看的 Demo。

### 1. 准备环境

- 一台安装 **Xcode 15+** 的 macOS 开发机。
- 一台 **iOS 17+ 真机（iPhone 优先）**，用数据线连接到 Mac，并在设备上信任这台电脑。
- 已在 `ios/Config/Secrets.xcconfig` 中正确配置 `ANTHROPIC_API_KEY`（参考根目录 `RUN.md`）。

### 2. 打开工程并选择设备

1. 打开 `JarvisCoach/ios/JarvisCoach.xcodeproj`。
2. 左上角 Scheme 选择 `JarvisCoach`，并将运行目标设为连接的 iPhone 设备。
3. `Cmd + B` 先完整编译一遍，确认无错误。

### 3. 首次运行与权限授权

1. 点击 Xcode 左上角 **Run ▶**，将 App 安装到真机。
2. 首次启动时，系统会弹出：
   - 麦克风权限（Microphone）
   - 语音识别权限（Speech Recognition）
3. 一律选择 **允许**。

### 4. 截图指引（assets/screenshots）

请在真机上按侧边键 + 音量键截图，并将图片拷贝到 `assets/screenshots` 下，对应命名：

- `01_home.png`
  - 画面：Home 页面，能看到「Start Session」、Mode、Language 选择、Talk Tracks、Settings 卡片。
- `02_permissions.png`
  - 画面：首次启动时任一系统权限弹窗（麦克风或语音识别）。
- `03_live_hud.png`
  - 画面：Live HUD 正常工作，中间两行大字显示建议，顶部状态显示 Mode / Lang / Connection。
- `04_mode_switch.png`
  - 画面：在 Home 或 HUD 中展示 Mode 切换（例如从 Pitch 切到 Sales）。
- `05_script_library.png`
  - 画面：Script Library 中编辑话术的界面。
- `06_debug_fold.png`
  - 画面：Live HUD 中右上角 Debug 折叠区域展开，显示最近一句转写、更新时间与 Clear 按钮。

> 当前仓库中已经有对应文件名的占位文件，你只需要用真机截图替换这些文件即可。

### 5. 建议 Demo 流程（60–90 秒）

可直接参考 `docs/DEMO_SCRIPT.md`，这里给一个精简版：

1. 在 Home 页面选中 **Mode = Pitch**，Language 保持 **Auto**。
2. 点击 **Start Session** 进入 Live HUD。
3. 拿起手机，模拟“对方”问：
   - 「你们和竞品最大的差异是什么？」
4. 1–2 秒后，HUD 中间应出现两句建议（无问号、直接回答）。
5. 再问一句「那你们的定价策略是怎样的？」后，点底部 **Shorter** 按钮，再等一次建议，观察回答明显变短。

### 6. 演示注意事项

- **环境噪声**: 尽量在相对安静环境演示，避免语音识别被严重干扰。
- **网络状态**: 确保真机有稳定的 Wi‑Fi 或 4G/5G 网络。
- **语言**: 目前以中英文混合为主，对普通话识别效果最佳。
- **节奏**: 说完“对方问题”后稍停顿 1–2 秒，让系统完成稳定转写与 Claude 调用。

