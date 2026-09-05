# Cursor 指令:8501 /task/expanded 服务端编排端点(b11 配套)
# expanded-orchestration v1 · 2026-07-22
# 目标:Kimi 成为 Grid 的可拔除扩展 substrate,编排全在家里。
# 前端 b11 已就绪:端点上线即自动启用(404/501 前它走前端过渡链,
# provenance 里标 orchestrator: client-interim;上线后自动标 8501)。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 端点契约
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POST /task/expanded
请求:
{
  "task": "用户当前输入",
  "assets": [
    {"name":"img0","kind":"image","mime":"image/jpeg","base64":"…"},
    {"name":"x.md","kind":"text","text":"…"},
    {"name":"y.pdf","kind":"pdf","mime":"application/pdf","base64":"…"},
    {"name":"z.m4a","kind":"audio","mime":"audio/mp4","base64":"…"},
    {"name":"v.mp4","kind":"video","mime":"video/mp4","base64":"…"}
  ],
  "client_context": "前端近6轮紧凑上下文(每轮≤400字)"
}
响应:
{
  "final": "Grid 署名的最终回答",
  "substrate": "kimi_k25_cloud" | "local",
  "usage": {"prompt_tokens":n,"completion_tokens":n,"budget":n},
  "provenance": {
    "candidate": "Kimi 原始输出(thinking 已销毁)",
    "envelope_summary": "出门内容摘要:N轮上下文/M素材/法则行/记忆片段数",
    "orchestrator": "8501",
    "timing_ms": {"preprocess":n,"kimi":n,"validate":n}
  }
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 服务端编排流水(按序)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 意图编译(aster):判断任务类型(视觉/长文档/重推理/普通),
   普通任务直接本地答,substrate="local",不调云——可拔除的含义
   就是不需要时它根本不在链路上。
2. 记忆片段选择:从本地记忆按相关性选 ≤K 条紧凑片段。
   出门白名单制:片段逐条过脱敏器(路径/密钥/日记标记/FIELD_NOW
   一律拦截),拦截记 telemetry 不报错。
3. 本地预处理:
   - pdf → 本地文本抽取 + 页预览,取必要片段
   - audio → SenseVoice 本地 ASR,只送 transcript
   - video → 抽帧(≤6 关键帧)+ 有音轨则 ASR
   原始 audio/video 字节不出门,除非请求显式带 raw:true(默认无)。
4. envelope 组装:紧凑法则约束(一行,同 b11 RULE_LINE 语义)
   + 记忆片段 + client_context + 预处理产物 + 当前任务。
5. 动态预算:按任务类型定 max_tokens(普通 1024 / 文档 4096 /
   重推理 8192,可配),写入 telemetry。前端不再传 max_tokens。
6. 调 Kimi(既有 kimi_k25_cloud adapter,thinking 丢弃不落地)。
7. 本地校验接纳(aster):对照任务与法则,接纳/修正/拒绝。
   拒绝时 final 为 aster 自答 + 明说 substrate 输出被拒及原因,
   substrate 标 "local(candidate rejected)"。
8. 落 telemetry 一行 jsonl:{ts, task_type, substrate, budget,
   usage, timing_ms, memory_snippets, sanitizer_hits}。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 不变量
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 完整原始记忆/日记/system prompt/密钥/绝对路径/FIELD_NOW 永不出门。
- candidate 不落 memory、不入 execution、不进 CC CLI。
- thinking 原文全链路销毁(不进响应、日志、telemetry)。
- 普通任务不调云:substrate 可拔除 = 拔掉 Kimi 后 EXPANDED 退化为
  HOME 语义,系统完整可用。
- chat 温度分道已定的规矩不变:对话 0.8 / 校验接纳 0.7 / 编译交易 0.3。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 验收
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- [ ] 普通问题走 EXPANDED:substrate=local,云端零调用(抓 8503 日志证)
- [ ] 单图/多图(≤6):final 一条,provenance 有 candidate 原文与耗时
- [ ] PDF:本地抽取,Kimi 只收到片段(抓包证原始 base64 未出门)
- [ ] 音频:只送 transcript(抓包证)
- [ ] 视频:≤6 帧 + transcript(抓包证)
- [ ] 记忆片段:构造一条含绝对路径的记忆 → 被脱敏器拦,telemetry 记录
- [ ] candidate 故意注入"我是 Grid 本体"类越权文本 → aster 拒绝,
      final 标 local(candidate rejected)
- [ ] 拔除测试:关掉 kimi adapter → EXPANDED 全部任务 substrate=local,
      页面无报错(可拔除的最终证明)
- [ ] b11 前端零改动:端点上线后 provenance 自动显示 orchestrator: 8501
