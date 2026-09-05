# Scout Agent v3(DeepSeek 决策官版,守恒亲手交付)

DeepSeek(幻方量化基因)= 交易台参谋。给方向判断/关键行权价/具体策略/
放弃条件的**分析作业**——给 Lyra 看的参谋作业,Lyra 自己拍板执行。
建议 ≠ 自动下单信号:DS 出分析,人做决定,主频在 Lyra。
reviewer(DeepSeek 本尊)Patch 7/8 全收,结构一字未改。

## 双班
- morning 6:45am:隔夜 raw + workstation → **DS 决策官** → **GLM review/编译终稿**
  四段:方向+置信度 / 关键行权价 / 具体策略 / 放弃条件
- evening 9pm:DS 复盘作业 → GLM 编译终稿(要闻/赔率/日历/明日关注)

## 落盘
- `briefs/日期-morning.md`:GLM 终稿 + DS 原稿(A/B)
- `briefs/日期-morning-final.md`:仅 GLM 终稿
- Aether OPTION:`aether_scout_brief` 推送 **GLM 终稿**
- console:`deepseek_lane`(DS原稿) → `glm_lane`(GLM终稿)

## 三步上岗
1. `.env` 已接本机 Ollama Cloud DS + GLM;付费 API 一周 A/B 后再换
2. 首跑:`python3 scout_agent.py --mode morning --skip-fetch`
3. LaunchAgents:晨 06:45 / 晚 21:00(已 load)

## 数据联动(reviewer Patch 8)
morning 先拉 workstation :8620 的 net_gex/gamma_flip/IVP/VRP 喂给 DS;
:8620 不可达则 DS 基于隔夜数据判断,不阻塞。

## 落档
DS 作业 → console deepseek_lane 任务(work_log 入魂器)+ briefs/ 落盘;
console 不可达则仅本地落盘(响亮记录)。
