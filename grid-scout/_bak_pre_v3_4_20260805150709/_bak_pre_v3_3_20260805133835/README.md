# Scout Agent v3(DeepSeek 决策官版,守恒亲手交付)

DeepSeek(幻方量化基因)= 交易台参谋。给方向判断/关键行权价/具体策略/
放弃条件的**分析作业**——给 Lyra 看的参谋作业,Lyra 自己拍板执行。
建议 ≠ 自动下单信号:DS 出分析,人做决定,主频在 Lyra。
宇宙 = S&P 500 & Nasdaq 成分池(Lyra 拍板 2026-08-05,不再是 SPY/QQQ 两 ETF);
候选必须锚定隔夜采集证据,禁凭训练记忆点名。

## 双班
- morning 6:00am PST(=9:00 ET 盘前):结构化交易任务单(拉 workstation GEX+隔夜 raw
  → DS 决策官五段:大盘方向+置信度 / 池内候选(锚定证据) / 关键价位 /
  具体策略含行权价到期最大亏损 / 放弃条件)
- evening 9pm:复盘+明日弹药(要闻催化 / 赔率变化 / 明日日历 / 明日关注方向)

## 三步上岗
1. DeepSeek=本机 Ollama Cloud(`deepseek-v4-pro:cloud`);GLM 5.2 review/编译经 `8501`
   (`.env`:`GATEWAY_URL` + `GLM_MODEL=glm-5.2:cloud`)。晨报强制个股卡 + 禁编权利金。
2. 首跑:`python3 scout_agent.py --mode morning --skip-fetch`
   → `briefs/日期-morning-final.md` 为 GLM 终稿;同文件含 DS 原稿对照
3. 两个 plist 替换 `__SCOUT_DIR__` 与 `CONSOLE_KEY` 后自行 `launchctl load`(晚 21:00 / 晨 6:00)

## 数据联动
morning 先拉 workstation :8620 的 net_gex/gamma_flip/IVP/VRP 喂给 DS;
:8620 不可达则 DS 基于隔夜数据判断,不阻塞。

## 落档
DS 作业 → console deepseek_lane 任务(work_log 入魂器)+ briefs/ 落盘;
console 不可达则仅本地落盘(响亮记录)。
