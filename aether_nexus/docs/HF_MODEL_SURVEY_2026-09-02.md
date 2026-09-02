# HF 模型/项目调研 · harness 能力面对齐 · 回执 · 2026-09-02

> 审:Lyra 问"hugging face 上帮我找一下有利于 harness 的模型或项目,比如最新的 tts 模型等"
> 模式:只读 web 调研,未装任何模型、未改任何文件、未 commit。
> 性质:内部对账回执(架构骨架 + HF 链接 + license/参数/Mac-fit)。无密钥/身份/store 正文/user 数据。若外发 review 区,按 `receipt-redaction.mdc` 复核(本件已无活体)。

---

## 0. 前提

- harness 在 Mac(M4)上跑。**MLX 原生/小模型** Mac 可跑;**11B/12B 全双工+大 embedding** 需 NVIDIA CUDA 16GB+,Mac 跑不动。下表标 Mac-fit。
- **不装模型**——装哪个 Lyra 拍(动 capability_registry / 部署形态需授权,见 AGENTS.md R5)。
- harness 能力面(来自 `app/harness/capability_registry.py`):`voice.realtime`(personaplex_local 8631)、`audio.asr`/`audio.tts`、`image.read`/`video.analyze`(minimax_m3)、`crypto.rwa.scan_public`。

---

## 1. TTS(harness `audio.tts`,现 minimax_m3)

| 模型 | 参数 | License | 为什么 | Mac? |
|---|---|---|---|---|
| **[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** | 82M | Apache 2.0 | 速度王:RTX5090 首 28ms,M4 208ms warm TTFA,104× RTFx。voice.realtime 低延首选 | ✅ M4 208ms |
| **[Qwen3-TTS 1.7B](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)** | 0.6B/1.7B | Apache 2.0 | 质量王:长叙事最稳,predefined speakers + voice cloning + text-described voice | ✅ 0.6B |
| **[Raon-OpenTTS-1B](https://huggingface.co/KRAFTON/Raon-OpenTTS-1B)** | 0.3B/1B | Apache 2.0 | **权重+数据双开**,DiT 架构,WER 1.78% / SIM 0.749,对标 Qwen3-TTS/CosyVoice3 | ✅ 0.3B |
| F5-TTS | 0.3B | CC-BY-NC | 零样本克隆,Raon 的基座 | ⚠️ NC |

**戌荐**:voice.realtime 低延 → **Kokoro**;audio.tts 高质量旁路 → **Qwen3-TTS 0.6B**(Mac 友好)或 Raon-OpenTTS-0.3B(双开)。

---

## 2. ASR(harness `audio.asr`,现 minimax_m3)

| 模型 | 参数 | License | 为什么 |
|---|---|---|---|
| **[Nemotron-3.5-ASR-streaming-0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)** | 600M | OpenMDW-1.1 | 流式 80–1120ms chunk,40 locales,H100 上 240 并发流,自带标点/大写 |
| **[Qwen3-ASR 0.6B/1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf)** | 0.6B/1.7B | Apache 2.0 | Whisper encoder + Qwen3 decoder,30 语种自动识别,与 Qwen3 生态同源 |
| [Cohere Transcribe 2B](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026) | 2B | Apache 2.0 | 14 语种,Open ASR Leaderboard 5.42% WER,RTFx 3× |
| IBM Granite Speech 4.1 2B | 2B | Apache 2.0 | 5.33% WER,**keyword biasing**(交易术语/人名)+ 双向语音翻译 |

**戌荐**:voice bridge 流式 → **Nemotron-3.5-ASR**(并发强);本地同源 → **Qwen3-ASR-0.6B**。交易术语 biasing 想要 → Granite。

---

## 3. Realtime voice(harness `voice.realtime`,现 personaplex_local 8631)

| 模型 | 参数 | License | 为什么 | Mac? |
|---|---|---|---|---|
| **[NVIDIA NemotronLabs VoiceChat-11B](https://huggingface.co/nvidia/NVIDIA-NemotronLabs-VoiceChat-11B)** | 11B | — | **首个支持 tool calling 的开源全双工**,450ms turn-taking,Hybrid Mamba/Transformer。直接对齐"能调=该调"铁则 | ❌ 需 CUDA |
| **[KRAFTON Raon-SpeechChat-9B](https://huggingface.co/KRAFTON/Raon-SpeechChat-9B)** | 9B | Apache 2.0 | 全双工,backchannel("嗯哼"),barge-in,**ECAPA 声线克隆**,Qwen3-based | ❌ 需 CUDA 16GB |
| **[Moshi (Kyutai)](https://huggingface.co/kyutai/moshika-mlx-q8)** | 7B | Apache 2.0 | **MLX 原生 Apple Silicon**,Mimi codec 24kHz→12.5Hz,~200ms 实测延迟 | ✅ MLX q4/q8 |

**戌荐**:Mac 本地 → **Moshi MLX**(唯一 Apple 原生全双工);有 NVIDIA GPU 且要 tool-calling 全双工 → **NVIDIA VoiceChat-11B**(铁则同款)。

---

## 4. Agent function-calling(harness agents / 能调=该调)

| 模型 | 参数 | License | 为什么 |
|---|---|---|---|
| **[Hammer2.0-7b](https://huggingface.co/MadeAgents/Hammer2.0-7b)** | 0.5B/1.5B/3B/7B | Apache 2.0 | Qwen2.5-based,function masking,BFCL 强;0.5B/1.5B 可上端 |
| **[TinyAgent-7B](https://huggingface.co/squeeze-ai-lab/TinyAgent-7B)** | 1.1B/7B | Apache 2.0 | ToolRAG 84.95% success(超 GPT-4-turbo),**MacBook Siri-like demo**,edge 部署 |
| **[functionary-small-v2.5](https://huggingface.co/meetkai/functionary-small-v2.5)** | 8B | Apache 2.0 | OpenAI-shape function call,并行工具,兼容现有 /v1/chat/completions 接口 |
| [Breeze-7B-FC](https://huggingface.co/MediaTek-Research/Breeze-7B-FC-v1_0) | 7B | Apache 2.0 | 繁中强 |

**戌荐**:harness worker 本地 FC → **Hammer2.0-1.5B/3B**(Mac 友好);兼容现有 OpenAI 接口 → **functionary-small-v2.5**;Mac edge 全栈 → **TinyAgent-1.1B**。

---

## 5. VLM/multimodal(harness `image.read`/`video.analyze`,现 minimax_m3)

| 模型 | 参数 | License | 为什么 |
|---|---|---|---|
| **[Molmo2-8B](https://huggingface.co/allenai/Molmo2-8B)** | 4B/8B | Apache 2.0 | Qwen3-8B + SigLIP2,图+视频+多图+grounding,15 benchmark 63.1,短视频/计数/captioning 强 |
| **[Penguin-VL-8B](https://huggingface.co/tencent/Penguin-VL-8B)** | 2B/8B | Apache 2.0 | LLM-based vision encoder(Qwen3-0.6B),**TRA token 压缩**,长视频友好 |
| **[ZwZ-8B](https://huggingface.co/inclusionAI/ZwZ-8B)** | 8B | Apache 2.0 | 单 pass 细粒度感知,无需推理时 zoom,**OCR/GUI agent 强** |
| [TimeLens-8B](https://huggingface.co/TencentARC/TimeLens-8B) | 8B | Apache 2.0 | 视频时间定位 SOTA |

**戌荐**:替代 minimax_m3 通用 → **Molmo2-8B**;长视频 → **Penguin-VL-8B**;OCR/细粒度 → **ZwZ-8B**。

---

## 6. Embedding(harness memory,store.search/recent 检索)

| 模型 | 参数 | MMTEB | License | 为什么 |
|---|---|---|---|---|
| **[Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B)** | 4B | 69.45 | Apache 2.0 | **效率/性能最佳**,Mac 可跑 |
| [Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B) | 8B | 70.58 | Apache 2.0 | 开源均衡王 |
| [KaLM-Embedding-Gemma3-12B](https://huggingface.co/tencent/KaLM-Embedding-Gemma3-12B-2511) | 12B | 72.32(#1) | 社区许可 | 质量极限,3840 dim |
| [BGE-M3](https://huggingface.co/BAAI/bge-m3) | 568M | 63.2 | MIT | 轻量,多语 |

**戌荐**:memory 检索 Mac 本地 → **Qwen3-Embedding-4B**(与 Qwen3 生态同源,契约 §一 store.search 可升级语义检索);轻量 → BGE-M3。

---

## 7. 与契约/缺口的对齐点

- **NVIDIA VoiceChat-11B 的 tool-calling 全双工** = "能调=该调"铁则的语音版,若上则 voice.realtime lane 自带 tool 调用留痕(可接 RWA 缺口 G1 的 provenance 链)
- **Qwen3-Embedding-4B** 可让 store.search 从关键词匹配升级语义检索(契约 §一 store.search 现是 SQL LIKE)
- **Hammer2.0/functionary** 的 function-calling 可补 harness worker 的 tool_log/tool_trace(契约 §四,缺口 G7)

---

## 8. Mac vs GPU 提醒

harness 在 M4 Mac 上。

- **MLX 原生/小模型**(Mac 可跑):Kokoro 82M、Qwen3-TTS 0.6B、Qwen3-ASR 0.6B、Moshi MLX、Hammer 1.5B、Qwen3-Embedding-4B、Molmo2-4B
- **11B/12B 全双工+大 embedding**(需 NVIDIA CUDA 16GB+,Mac 跑不动):VoiceChat-11B、Raon-SpeechChat-9B、KaLM-12B

---

## 9. 自检

- [x] 只读 web 调研,未装任何模型、未改任何文件、未 commit
- [x] 每个 candidate 带 HF 链接 + 参数 + license + Mac-fit
- [x] 未宣称"已装/可用";只列候选供 Lyra 拍
- [x] 范围:harness 能力面对齐;未碰 local_gateway.py / 冻结链 / 部署形态

—— 戌,2026-09-02 PDT(只读 web 调研)
