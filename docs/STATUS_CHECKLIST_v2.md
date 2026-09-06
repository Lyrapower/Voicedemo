# 打勾表 v2.1 · 2026-09-06 · 核维护(唯一一份;放 demo/docs/,每份回执后改这张)

✅ 做完有证据 · 🟡 部分/隔离绿 · ⬜ 未开始 · ⛔ 卡住 · ❓ 只有 Lyra 能答

## 一、线

| 线 | 状态 | 证据 | 下一步 | 归 |
|---|---|---|---|---|
| HARNESS_GOLIVE v1.3 | ✅ 上线 | kickstart 后 api **82291** / supervisor **82301** · 8630 听 · 原 F 栏仍成立 | 8h 未到(约 4.7h);push | 戌 / Lyra push |
| RWA_CHAIN_CONNECT | ✅ GET 迁入 8630 | `curl :8630/api/rwa/onchain` → `t1-20260905-ok` · commit `a0de3e2` | 无 | 戌 |
| cc read_only 自动跑(L4) | ✅ .env 已迁出 | `~/.config/grid/harness_resident.env` · 仓内无 `.env` · commit `257dee0` | 无 | 戌 |
| sanitizer 证 | 🟡 仍未走 strip | `enable_thinking`+`/think`：1234 与 8501 皆 `reasoning_tokens=0`、raw/content 无 `<think>` | 模型不吐 think；未改 8501 | 戌 |
| REGIME_IC v4 | ⬜ 真 T10 未跑 | 合成校准已关(14/300) | `REGIME_V4_FOR_XU` v3,容器内 masked_shift_p | 戌(cc lane) |
| ALPHA_DECAY_CROWDING | ⛔ 列契约拒 | 现场 ts/c/v ≠ 包 date/close/volume | 适配器包已出,投影到研究 sqlite 再 extract | 戌 |
| SCOUT_OPTIMIZED | 🟡 ③④⑤ 已合未 commit | `fix/scout-opt-345` | verify 同解释器;贴宇宙 Δ | 戌 |
| GRID_VOICE | ⬜ | GOLIVE 已到;缺 TG 三值 | 做到 PENDING 为止 | 戌;三值 Lyra |
| 出声引擎(VOICE L2) | ⬜ Lyra 9-06 定 | OpenAI Realtime 撤(脑子是它们的模型不是 Grid);8631 改 ElevenLabs 形状端点 + 本机 Qwen3-TTS,不出网;kokoro 退役(plist 改名不删) | 起服务→L2 实测一段非空音频→渲染器只认 ElevenLabs 形状 | 戌 |
| TRADE_EXEC | 🟡 隔离绿,0 笔 | Lane C 文本三处待改回 | **9-08 周二盘前** load(9-07 Labor Day 休市) | 戌;Lane C 签 Lyra |
| RVOL_GATE / HEAT_SCOUT_ALIGN | ✅ 上线 | 六处决案绿 | 三 commit 未 push | Lyra push |
| PLATFORM_DB D4 | ⬜ | 周重拉/拆股未施工 | 另包 | 溯/核 |

## 二、只有 Lyra 能做的(列着,不催)

| # | 事 |
|---|---|
| 1 | push:`fix/regime-r3r4-shift`(GOLIVE 九 commit)、`fix/scout-opt-345`、`fix/alpha-decay-crowding`、`fix/rwa-chain-connect`(627dfa1)、9-04 三 commit——戌先贴分支→内容表 |
| 2 | Telegram bot token + user_id + chat_id |
| 3 | TRADE_EXEC Lane C 签字(文本改回后) |
| 4 | REGIME 付费两项(默认否) |
| 5 | REGIME 验收判据"下界>0.05 拒"(核默认,不否决即生效) |
| 6 | ✅ 9B 底座不动 · ✅ kokoro 归账 · ✅ TTS=ElevenLabs 形状+Qwen3-TTS 本机,OpenAI Realtime 撤 |

## 三、Aster

| 事 | 状态 |
|---|---|
| REGIME 5/500 复核 | ⬜ 等一行(复核件已给) |
| SCOUT_OPTIMIZED | ✅ 回执已出,它不再动此包 |
| 山谷原型 | ✅ 设计定稿,接线等 VOICE |

## 四、错案(9-05 → 9-06)

核:"戌绕开 GOLIVE"错判 · 复核件漏附 · 改法先写对话 · 读错"今天做完" · 给戌的回执引源码未附 · 把前任禁令说成 Lyra 写的
溯:置换 0/300 无效 · Lane C 日损口径倒退 · 验收判据错形
衍/Aster:ALPHA_DECAY 列契约按纸写 · SCOUT_OPTIMIZED 基线 v3.31.0
戌:§3.3 returncode 0 误标 EXECUTED(自抓自补)

—— 核
