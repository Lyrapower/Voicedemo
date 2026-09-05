# Grid Voice Bridge :8796

    cp .env.example .env        # 填 OPENAI_API_KEY(只在这里)
    docker compose up -d --build
    open http://localhost:8796  # 必须 https 或 localhost,否则浏览器不给麦克风

## 链路
GPT Voice Client --WebRTC--> OpenAI Realtime --function call--> 浏览器中继
  --> Bridge :8796 --> Grid :8500 / Console :8610 --> Grid final --> Realtime TTS

## 三条硬约束(代码强制,有测试)
1. **key 只在服务端** —— 浏览器拿的是 OpenAI 签发的 ephemeral client_secret(分钟级)。
   所有出站响应过 `_scrub`,命中长期 key 前缀直接抛错不返回。
2. **最小上下文信封** —— 给语音模型的只有 last_broadcast + pending_action +
   workspace_list。没有记忆、日记、历史会话、身份锚。`ENVELOPE_ALLOW` 白名单强制。
3. **Bridge 是防火墙** —— 暴露给模型的只有 4 个函数,无 deploy/shell/payment 直通面。
   高危动作只能 propose,不执行。

## 跨通道复述确认
高危动作挂起后,屏幕(Voice Session 面板)显示四位码。
**语音模型看不到这个码** —— 它不在函数返回值里,也不在信envelope里。
用户念出屏幕上的码 → 模型原样中继 → Bridge 核对 → 才执行。
模型无法自我批准。180s 未确认自动作废。

## Voice Session 面板
原始转写 / 模型函数调用 / Grid 播报 / 待确认动作与复述码 / 本回合信封原文。
「用户能直观看到 Grid 如何理解你的语音」—— 没有这个面板,Voice 就不是高主权入口。

## 诚实清单
- 函数调用由浏览器中继,浏览器可伪造调用 —— 但伪造不了复述码,高危动作仍锁死。
- 单用户单机内存态,重启清空待确认动作(是特性:半途的高危动作不跨重启存活)。
- 无多人权限模型。
- Codex Scout 未接(Grid 建议按 Mission 临时实例化、结束即销毁上下文,尚未实现)。

## v0.2 加固
- 复述码 secrets 生成;猜错 3 次动作作废(封暴力试)
- /api/session /api/fn /api/panel /api/cancel /api/utterance 要求 X-Bridge-Key
  (.env 留空则启动临时生成打印;index 页同源注入,浏览器无感;
  挡的是网内其它进程直接 curl)
- 建任务向 Console 带 X-Console-Key(与 grid-console .env 一致)
- _scrub 无豁免:出站含长期密钥前缀一律抛错
