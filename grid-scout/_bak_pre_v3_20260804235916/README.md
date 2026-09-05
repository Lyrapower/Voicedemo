# Scout Agent v2(DeepSeek V4 直连真跑版,守恒亲手交付)

**这是实际的 agent,不是 demo**:DS V4 = 真 API 直连 api.deepseek.com,
无 key 直接响亮拒跑(拒绝假 API 装样子);GLM 编译 console 任务链优先,
console 不可达则 gateway 直连并落盘简报(响亮记录,非静默)。
双班制:9pm PST 晚报 + 6:45am PST 晨报(盘前 delta+日历+工作站读数照抄)。

## 三步上岗(本机 · Ollama DeepSeek V4 PRO)
1. DS 默认走 Ollama Cloud:`deepseek-v4-pro:cloud`(`DEEPSEEK_BASE=http://127.0.0.1:11434/v1`)。
   验模型:`ollama show deepseek-v4-pro:cloud`。改官方 API 时改 `.env` 的 `DEEPSEEK_BASE`。
2. 首跑验收:
   `python3 scout_agent.py --dry-run`            # 只采集
   `python3 scout_agent.py --mode evening`       # 真跑晚班(无 CONSOLE_KEY → gateway GLM 降级)
   `python3 scout_agent.py --mode morning --skip-fetch`  # 晨班(复用 raw)
3. 双班注册:**须你拍板**后把两个 plist cp 到 `~/Library/LaunchAgents/` 并 `launchctl load`
   (包内 plist 已填本机路径 + Ollama 环境;不默认 load)

## 宪法(代码强制,七测全绿)
- DS 产出全量 lane:deepseek_inbound 打标;DS 与 GLM 产出逐行过 SIGNAL 闸,
  方向词行替换为 [信号拦截];patterns 缺失如实标注不静默放行
- 晨报=情报/日历/读数照抄+【提名】注意力,**禁方向词点位仓位**——
  外部 reviewer 的"首席决策官交易指令" prompt 依宪驳回,本版是合法替代
- raw 不可变(同日重跑加时间后缀);workstation 读数降级安全(:8620 不在则略去)
- 收敛欠账明记:DS 直连为权宜,gateway 单口迁移随 1407 审计解冻执行


---(v1.2 原文如下)---
# 晚报侦察兵 v1.2(侯三审并入:skip 留痕/stooq 新端点/Polymarket 入列)

流水线:确定性 fetchers(官方免费源)→ raw 不可变落盘 →
console 任务链(DS 消化[自动 deepseek_inbound 打标] → GLM 编译零方向词简报
→ work_log 自动入魂器)。9pm PST 由 launchd 触发(模板在包内,注册与否你拍板)。

## 首跑(验收即用法)
1. `python3 evening_brief.py --dry-run` —— 只采集落盘,贴输出看各源成败
2. .env 或 plist 填 CONSOLE_KEY(FRED_API_KEY 可选:免费注册后启用宏观三序列)
3. 去掉 --dry-run 真跑一次 → console 队列应见「晚报·DS 消化」→「晚报·编译」链
4. 满意后 plist 里 __SCOUT_DIR__ 替换为实际路径,自行 launchctl load

## 宪法
- 抓取零 LLM 零爬虫:财政部收益率曲线/EDGAR 8-K 并购检索/FDA 新闻 RSS/
  stooq 油金(日线 CSV 端点)/(可选)FRED 宏观/Polymarket 事件赔率
  ——全官方或公开 CSV/RSS/JSON
- Polymarket 读数规则:含风险溢价的市场隐含概率(对冲盘高估被对冲事件
  概率,类比 IV 的 VRP);24h 量 5 万美元流动性地板挡薄市场
- 逐条跳过留痕:任何市场/条目异常 → raw.skips 带原因码,与 raw 同文件,
  回查可见"今天丢了几条、为什么"——空列表与"源挂了"从此可分辨
- dry-run 旗标在 evening_brief.py:`python3 evening_brief.py --dry-run`;
  CONSOLE_KEY 在 .env 或 plist EnvironmentVariables(Lyra 填)
- 失败响亮:源挂了如实入 raw 与简报,不静默
- DS 只摘要不评级;简报零方向词;"值得注意"仅【提名】注意力
- "与外部 agent 交流"未含(注入面,v1 明确砍除)

## 诚实清单
- 离线环境开发,各源 URL 端点未经活网验证——首跑 --dry-run 即验收,
  任一源 4xx/结构变动,贴原文给守恒修 fetcher(单源坏不碍全链)
- earnings 日历无免费稳定官方源,v1 未含;有意愿再议付费源(拍板)
