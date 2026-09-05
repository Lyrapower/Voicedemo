# Grid Voice Mode — Implementation Spec v1.0

> Target: 8501 Grid 对话页面语音功能。Streaming half-duplex + barge-in(一期),全本地,零 egress。
> 新增组件:`voice_daemon.py`(8504)+ `grid_voice.js`(前端)。Gateway 只加一条 WS 代理路由。
> 本文档为 Cursor Composer 实现依据。所有接口以此为准,实现偏离需回写本文档。

---

## 0. 决策记录(不可协商项)

| 项 | 决定 | 理由 |
|---|---|---|
| TTS | CosyVoice 2 (0.5B), streaming mode | 原生中英句内混切;首包 ~150ms |
| TTS fallback | Kokoro-82M | 纯英文段落;CosyVoice 故障降级 |
| ASR | SenseVoice-Small (FunASR) | zh/en 双语,快;情绪/事件标签进 telemetry |
| VAD | Silero VAD v5, browser 端 ONNX (onnxruntime-web) | barge-in 延迟最低,不占服务端 |
| LLM | 现有 LM Studio Qwen 路由,**不新开** | 沿用 per-route token budget 与 finish_reason 转发 |
| 频率分析 | 前端 WebAudio AnalyserNode,双路 | 服务端不做判断,只给指标 |
| Egress | 零。所有流量 localhost | 8503 audit 不涉及(无外呼) |
| 安全 | TTS 入口前过 impersonation pattern check | 语音不绕过 Aster 校验层 |

---

## 1. 拓扑

```
Browser (8501 page)
  ├─ mic capture (AudioWorklet, 16kHz PCM16 mono)
  ├─ Silero VAD (onnxruntime-web, 本地 onnx 文件, 不走 CDN)
  ├─ WS ──► Gateway /voice (仅代理+鉴权) ──► voice_daemon :8504
  │                                            ├─ SenseVoice ASR
  │                                            ├─ LM Studio /v1/chat/completions (stream)
  │                                            ├─ sentence splitter
  │                                            ├─ impersonation check (复用 gateway pattern 模块)
  │                                            └─ CosyVoice2 streaming TTS
  ├─ WebAudio playback queue (24kHz)
  ├─ AnalyserNode ×2 (mic tap / TTS tap)
  └─ SSE ──► 现有 telemetry endpoint (voice.* 指标)
```

Gateway 职责最小化:WS upgrade、keyholder 校验、转发。业务逻辑全在 8504。

---

## 2. voice_daemon.py — 服务定义

FastAPI, 单 WS endpoint + health。

### 2.1 Endpoints

```
GET  /health            → {"status":"ok","asr":"loaded","tts":"loaded","tts_engine":"cosyvoice2"}
WS   /ws/voice          → 主通道(经 gateway 代理暴露为 /voice)
```

### 2.2 会话生命周期

一个 WS 连接 = 一个 voice session。断线即 session 结束,服务端 abort 所有在途任务(LLM stream、TTS stream)。对话历史由前端持有并随每轮上送(daemon 无状态,与 Grid 现有架构一致:decision layer 不在 daemon 沉淀状态)。

### 2.3 进程重启与权重下载(守秤 — 优先于 cache 路径排查)

**`:8504` LaunchAgent:** `com.demo.grid.voice8504` · `KeepAlive: true` · `ThrottleInterval: 30`(仅进程真退后重启,health 抖动不补刀)。

**`/health` 三态:**

| `status` | 含义 |
|---|---|
| `initializing` | 绑口已就绪;CosyVoice/SenseVoice 后台加载中,见 `progress` / `phase` / `asr_download` |
| `ok` | 引擎就绪,可接 WS |
| `error` | 启动失败(503) |

**权重 cache:** 固定 `grid-sovereign-runtime/data/model_cache/modelscope`(launchd 经 `MODELSCOPE_CACHE` 注入)。ModelScope `snapshot_download` / `model.pt.incomplete` 支持断点续传——**前提是进程不被强杀打断 incomplete**。

#### 重启铁律(比查 cache 路径优先)

1. **`status=initializing` 或 `asr_download` < 1.0 期间:禁止一切形式的重启** — 包括 `kickstart -k`、`kill -9`、脚本内隐式 kickstart。新代码等本轮下载到 100% 且翻 `ok` 后再部署。
2. **进行中禁用 `-k`:** `launchctl kickstart -k` 向 launchd 发 SIGKILL,会打断 `model.pt.incomplete`,表现为进度归零或回退——续传实验可证,但运维上视为事故。
3. **稳态外要重启 → graceful only:**
   ```bash
   launchctl kill SIGTERM "gui/$(id -u)/com.demo.grid.voice8504"
   # 等进程自行退出;KeepAlive 拉起新实例。勿 -k。
   curl -s http://127.0.0.1:8504/health   # 确认 status / asr_download 未意外回退
   ```
4. **`-k` 仅允许在 `status=ok` 稳态下使用** — 且仅当确需硬换二进制/不可 graceful 退出的极端情况。默认不用。

**守秤验收(续传):** 记录 kill 前 `asr_download` 或磁盘 `model.pt.incomplete` 占比 → SIGTERM 或自然退出 → 再起 → 占比**不得从 0 重计**(允许 ±2% 读数误差)。`RESUME_OK` 须实验判定,非代码自述。

**health 探针:** bootstrap 在 `ThreadPoolExecutor` 内执行;`GET /health` 只读锁内 `BootState`,零磁盘 I/O。初始化期间连打应稳定 <10ms,证明 event loop 不被下载/模型加载饿死。

---

## 3. WS 消息协议

混合帧:**JSON text frame**(控制面)+ **binary frame**(音频数据面)。

### 3.1 Binary frame 封包

所有 binary frame 首字节为 channel tag:

```
byte[0] = 0x01  client→server  mic audio chunk   (PCM16LE mono 16kHz)
byte[0] = 0x02  server→client  TTS audio chunk   (PCM16LE mono 24kHz)
byte[1..]        payload
```

chunk 粒度:mic 端 20ms(640 bytes payload);TTS 端由 CosyVoice2 流式输出决定,daemon 不重新分块,透传。

### 3.2 Client → Server(JSON)

```jsonc
// 会话初始化(连接后第一帧,必发)
{"type":"session.init",
 "session_id":"<uuid4, 前端生成>",
 "history":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}],
 "lang_hint":"auto",            // "auto" | "zh" | "en" — 只是 hint, SenseVoice 自检为准
 "tts_engine":"cosyvoice2"}     // "cosyvoice2" | "kokoro"

// 用户开口(VAD onset)。若此刻 state==SPEAKING,即 barge-in 信号
{"type":"speech.start","ts":<epoch_ms>}

// 用户停顿(VAD offset + 800ms hangover,见 §6)
{"type":"speech.end","ts":<epoch_ms>}

// 前端主动取消本轮(用户点停止按钮)
{"type":"turn.cancel"}

// 心跳,10s 间隔
{"type":"ping"}
```

`speech.start` 与 `speech.end` 之间的 0x01 音频帧属于同一 utterance。`speech.end` 后到达的散帧丢弃。

### 3.3 Server → Client(JSON)

```jsonc
{"type":"session.ready"}                          // init 处理完毕,可以开始
{"type":"state","value":"listening|thinking|speaking|idle"}  // 状态机每次迁移都推

// ASR 结果(utterance 级,一次性;SenseVoice 非流式增量)
{"type":"asr.final",
 "text":"...",
 "lang":"zh|en|mixed",
 "emotion":"neutral|happy|sad|angry|...",         // SenseVoice 标签,原样透传
 "event":"speech|bgm|applause|...",
 "duration_ms":1234}

// LLM 增量文本(供前端字幕/记录)
{"type":"llm.delta","text":"..."}
{"type":"llm.done","finish_reason":"stop|length|abort"}   // 诚实转发,沿用 gateway 语义

// TTS 分句进度
{"type":"tts.sentence.start","idx":0,"text":"..."}
{"type":"tts.sentence.end","idx":0}
{"type":"tts.done"}                               // 本轮全部句子播完(服务端发完)

// barge-in 确认:收到 speech.start 且在 SPEAKING 态时立即回,前端据此 flush 播放队列
{"type":"interrupt.ack","aborted":{"llm":true,"tts":true},"spoken_text":"实际已送出音频对应的文本"}

// 安全拦截:TTS 前 impersonation check 命中
{"type":"security.block","pattern_id":"<gateway pattern id>","sentence_idx":2}

{"type":"error","code":"asr_fail|tts_fail|llm_fail|budget_exceeded","detail":"...","recoverable":true}
{"type":"pong"}
```

**`interrupt.ack.spoken_text` 是硬要求**:barge-in 后,前端用它替换 assistant 消息内容再写入 history——历史里记的必须是用户实际听到的,不是 LLM 生成了多少。否则下一轮 context 与用户感知脱节。

---

## 4. Daemon 内部流水线

### 4.1 一轮 turn 的处理

```
speech.end 收到
  → utterance PCM 拼接 → SenseVoice → asr.final 下发
  → state: thinking
  → POST LM Studio /v1/chat/completions stream=true
      body: {model: <现有配置>, messages: history + [{"role":"user","content":asr_text}],
             max_tokens: <voice 路由预算,见 §8>}
  → 逐 delta 下发 llm.delta,同时进 sentence splitter
  → 每凑齐一句:
      1. impersonation check(复用 gateway 模块,import,不复制代码)
         命中 → security.block 下发,该句丢弃,后续句照常(策略:句级拦截,不中断整轮;
         若一轮内命中 ≥2 句 → abort 整轮 + error code "security_abort")
      2. 送 CosyVoice2 streaming → 0x02 帧透传下发
  → state: speaking(第一个 0x02 帧发出时迁移,不是 LLM 开始时)
  → llm 流结束 + 最后一句 TTS 发完 → tts.done → state: listening
```

### 4.2 分句器(sentence splitter)

- 切分符:`。！？!?;；\n` + 英文 `. ` 后跟大写/结尾
- 中英混合句**不在语言切换点切**,只按标点
- 最小句长 6 chars(避免 "好。" 单独进 TTS 造成碎片音频;不足则与下句合并)
- 最大缓冲 120 chars 强制切(防 LLM 长句无标点憋死流式)
- 数字/小数点保护:`3.14` 不切

### 4.3 Abort 语义

`speech.start`(during SPEAKING)或 `turn.cancel` 触发:

1. cancel LM Studio HTTP stream(httpx aclose)
2. cancel CosyVoice 生成任务
3. 清空 daemon 侧发送队列中未发出的 0x02 帧
4. 计算 `spoken_text`:已发出 0x02 帧对应到句边界(按 `tts.sentence.start/end` 记账;正在播一半的句子按整句计入——宁多勿少)
5. 下发 `interrupt.ack`
6. state → listening,新 utterance 立即开始收音频

全程 async,abort 必须 < 100ms 完成(不含前端 flush)。

---

## 5. 状态机

Daemon 与前端各持一份,以 daemon 为权威(`state` 消息同步)。

```
        session.init/ready
IDLE ──────────────────────► LISTENING
                              │  ▲
              speech.end 且   │  │ interrupt.ack 处理完
              utterance 非空  │  │ 或 tts.done
                              ▼  │
                            THINKING ──first 0x02──► SPEAKING
                              │                        │
                              │ turn.cancel            │ speech.start (=barge-in)
                              │ 或 llm_fail            │ 或 turn.cancel
                              └────────► LISTENING ◄───┘
                                        (经 abort 流程)

任意态 → IDLE:WS 断开
THINKING 期间 speech.start:合法,视为用户追加/改口 → abort LLM → 新 utterance 并入
  (实现:THINKING 态收到 speech.start = turn.cancel + 保留上一 utterance 文本,
   speech.end 后新旧文本以 "\n" 拼接作为本轮 user content)
SPEAKING 期间 speech.end 且 utterance < 300ms:忽略(咳嗽/桌响误触,VAD 层已过滤大半,这里兜底)
```

**Barge-in 竞态规则**:daemon 收到 `speech.start` 的瞬间即停止发送 0x02 帧,`interrupt.ack` 之后到达前端的任何 0x02 帧(在途)前端必须丢弃——前端以收到 `interrupt.ack` 为界闸门。

---

## 6. grid_voice.js — 前端定义

### 6.1 模块结构

```
grid_voice.js
  ├─ MicPipeline      ScriptProcessor: getUserMedia → 16kHz resample → PCM16 → 20ms chunk
  ├─ VadGate          Energy RMS VAD (Silero v5 onnx 为二期; 阈值同 §8)
  │                     onset:  prob > 0.6 连续 3 窗 → speech.start
  │                     offset: prob < 0.35 持续 800ms → speech.end
  ├─ VoiceWS          §3 协议实现;binary 收发;interrupt 闸门
  ├─ PlaybackQueue    24kHz AudioBufferSource 队列;flush() 即停
  ├─ SpectralTap      mic AnalyserNode + telemetry POST /voice/telemetry
  └─ VoiceUI          按钮/状态灯/字幕(llm.delta)/security.block 提示
```

**实现注记 (2026-07-10):**

| 组件 | 状态 | 注记 |
|---|---|---|
| TTS primary | CosyVoice2-0.5B | Kokoro **仅** fallback; 禁止作主引擎。模型路径 `pretrained_models/CosyVoice2-0.5B` |
| TTS routing | `tts_engine: auto` | warmup `tts_decision=code_switch_specialist` 时 **en→Kokoro, zh/mixed→CosyVoice2**; `primary` 时全 CosyVoice2 |
| TTS blockers | 见 `/health` → `voice.blockers` | grpcio 全量 requirements 在 Py3.13 构建失败; 已用最小依赖 + `third_party/CosyVoice` 源码 import |
| Gateway `/voice` | keyholder gate | `session.init.keyholder{nonce,ts,response}` HMAC 回签; 3 连失败锁 60s; audit 不落 key |
| Boot warmup | kickstart 阶段 | CosyVoice 预载 + dummy 合成; 冷启动成本不进用户路径 |
| ASR primary | SenseVoice-Small | faster_whisper fallback; emotion/event 在 SenseVoice 路径为真值 |
| Daemon bind | `127.0.0.1:8504` | tailnet 只走 `8501/voice` 代理,禁止暴露 8504 |
| 重启 / 续传 | §2.3 | 下载中禁 `-k`;graceful SIGTERM;`-k` 仅 `status=ok`;cache 见 `data/model_cache` |

### 2.4 可观测性 — 禁止静默降级(守秤横规)

与 `finish_reason` 诚实转发同律:**系统真实状态必须对用户可见**。任何引擎切换 / fallback / API 缺失不得静默跳过。

| 事件 | 必须留痕的位置 |
|---|---|
| TTS 路由 | WS `tts.sentence.start{engine,locale,route}` + `#vst` 行 |
| TTS 实测 | WS `tts.sentence.end.metrics{device,rtf,first_packet_ms}` + daemon `TTS synthesis` 日志 |
| TTS fallback | `metrics.fallback_from` + `#vdeg` 降级行 |
| ASR fallback | `/health.blockers` + WS `error` / `#vdeg` |
| `navigator.audioSession` | `#vas` 行:`supported\|unsupported · type=…`; 设置失败写 `#vdeg` |

**判定口径:** 含 CJK → `zh`/`mixed` → CosyVoice2; **仅**纯英(无 CJK 且有拉丁词) → Kokoro。不得以”含英文 token”单独判 en。

`session.init` 扩展字段:

```jsonc
"keyholder": {"nonce":"…","ts":123.4,"response":"<hmac hex>"}
```

手机端: `grid_keyholder.js` — 一次性 hex 录入 → `localStorage.voice_kh_key_bytes`(仅设备) + `voice_keyholder` 仅存 `{configured,key_ref}` 引用; Challenge UI 在 `grid.html` · 配置区。

### 6.2 前端硬性规则

- VAD 在 mic 常开时本地判断,**只有 speech.start→speech.end 区间才上送音频帧**(mic 数据不无差别上传,即使是 localhost——习惯问题)
- `interrupt.ack` 收到 → `PlaybackQueue.flush()` + 丢弃后续在途 0x02 直到下一个 `tts.sentence.start`
- TTS 播放期间 mic 不静音(barge-in 依赖它),但 VAD 阈值抬高 0.6→0.75 抗回声;若设备无 AEC(`echoCancellation: true` 申请失败)则提示建议耳机
- history 由前端维护,assistant 内容以 `spoken_text` / 完整文本为准(§3.3)

---

## 7. 频率分析(SpectralTap)

双路,同构输出,供 telemetry 与后续 Garden 粒子场喂养。

```
路A: mic MediaStreamSource ──► AnalyserNode (fftSize 2048)
路B: PlaybackQueue 输出节点 ──► AnalyserNode (fftSize 2048)
```

每 100ms 计算一帧,SSE POST 到现有 telemetry endpoint:

```jsonc
{"ns":"voice","ch":"mic|tts","ts":<epoch_ms>,"session":"<session_id>",
 "f0_hz": 182.4,            // YIN/autocorrelation, 无声段 null
 "f0_stability": 0.91,      // 滑窗(1s) F0 变异系数取反归一 [0,1]
 "centroid_hz": 1420.7,     // spectral centroid
 "centroid_drift": 12.3,    // 滑窗 centroid 标准差
 "hnr_db": 14.2,            // harmonic-to-noise ratio
 "energy_var": 0.08,        // 滑窗 RMS 方差
 "vad_prob": 0.87}          // 路A 独有;路B 置 null
```

原始指标,不做 coherence 裁决。命名空间 `voice.*` 与 Garden telemetry 并列,schema 对齐其现有帧格式(实现时以 Garden 侧实际字段名为准做映射)。

---

## 8. 配置(并入现有 gateway JSON config)

```jsonc
"voice": {
  "daemon_port": 8504,
  "asr": {"model": "SenseVoiceSmall", "device": "mps", "lang": "auto"},
  "tts": {
    "engine": "cosyvoice2",
    "cosyvoice": {"model_dir": "<local path>", "stream": true, "sample_rate": 24000,
                  "speaker": "<预置音色 id,实现后固定一个默认>"},
    "kokoro":    {"model_dir": "<local path>", "voice": "af_heart", "sample_rate": 24000}
  },
  "llm_route": "voice",              // gateway per-route budget 表新增此路由
  "budgets":  {"voice_max_tokens": 400},   // 语音回复短于文本;finish_reason 诚实转发
  "vad": {"onset": 0.6, "onset_speaking": 0.75, "offset": 0.35, "hangover_ms": 800},
  "security": {"per_sentence_check": true, "abort_after_blocks": 2}
}
```

---

## 9. 验收标准(Cursor 自测清单)

1. **延迟**:speech.end → 首个 0x02 帧 ≤ 1.5s(M 系 Mac,MPS);≤ 2.5s 为及格线
2. **Barge-in**:说话打断 → 播放停止 ≤ 150ms(interrupt.ack 往返 + flush)
3. **中英混切**:"帮我把这个 function 的 return type 改成 Optional" 一句话,ASR 正确、TTS 不断句不换音色
4. **spoken_text 一致性**:barge-in 后 history 中 assistant 内容 == 实际播出内容(句级精度)
5. **安全**:构造一条会命中 impersonation pattern 的 LLM 输出(测试用 mock),确认 security.block 下发且该句无音频
6. **预算**:voice 路由 400 token 上限生效,finish_reason=="length" 如实到达前端
7. **零 egress**:全流程抓包(或 8503 audit log 为空)确认无外呼;onnx/模型文件全部本地加载
8. **降级**:kill CosyVoice 进程 → error(recoverable) → 切 kokoro 继续工作

---

## 10. 二期占位(本期不做)

- Qwen2.5-Omni-3B 真双工评估(speech-native,省去 ASR→LLM→TTS 三跳)
- CosyVoice 音色克隆(3s reference audio)
- voice.* 指标 → Garden 粒子场实时映射
- 情绪标签(asr.final.emotion)参与 LLM prompt 的开关
