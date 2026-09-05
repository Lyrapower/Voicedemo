# CURSOR 施工单 · SCOUT 简报接线 v1(2026-08-05,守恒出)

## 0. 先把一件事说清:不存在"三个 UI"
brief_sample_{morning,hedge,liquidation,rotation}.html 是**同一个渲染器**在四种日子的产出样例
(候选日/出货日/挤兑日/迁徙日)。渲染器 = `scout_agent.py` 内的
`render_brief_html/_render_structured/_cand_card/_engine_card/_md_fallback` + `BRIEF_CSS`,
scout 每天自动落盘 `briefs/{DATE}-morning.html` 与 `{DATE}-evening.html`(附 .md/.json)。

**Cursor 对渲染器与 CSS 零改动权**(同 v12/AETHER_PLATFORM 先例,手写页规矩)。
样式问题一律回守恒。Cursor 的活只有下面三件接线。

## T1 · 静态服务 briefs/
在 aether platform 既有服务进程加一个静态挂载(勿起新进程、勿加新依赖):
```python
# FastAPI 例(等价实现均可):
from fastapi.staticfiles import StaticFiles
app.mount("/briefs", StaticFiles(directory=SCOUT_DIR + "/briefs"), name="briefs")
```
- `SCOUT_DIR` 从 env 读,禁写死绝对路径
- 页面内一切链接按 `location.hostname` 动态拼,**禁写死 localhost**(07-27 Tailscale 教训)

## T2 · 决策面挂"晨会单入口卡"(不要 iframe 整页)
aether v12 决策面盘前简报槽改为入口卡,数据只从 `briefs/{today}-morning.json` 读,
**不得自己重算任何判断**:
- 读 `_engine.liquidation_watch` → true 则卡上红 chip `全线下跌 WATCH`
- 读 `ds.hedge.distribution_risk`(高=红/中=金/低=绿)与 `ds.hedge.regime` → 两枚 chip
- 卡主体:`SCOUT 晨会单 · {date}` + 三 chip + 按钮「打开」→ `/briefs/{today}-morning.html` 新开
- json 不存在(未产出/降级日无 json)→ 卡显示灰态 `晨会单未产出或降级为文本`,
  按钮仍指向 html(html 永远有,降级日是分节文本版)
- 晚报同理挂 `{today}-evening.html`(晚报无 json,入口卡只有日期+打开)

## T3 · 决策面排序(信息层级,一次定死)
1. **BFS 信号卡**(ground truth,永远第一屏第一位)
2. **SCOUT 晨会单入口卡**(参谋层,紧随其后)
3. 盘后/晚报入口
4. 机房区(log 形内容全折叠,老规矩)
禁止把 SCOUT 卡与 BFS 信号卡混排——参谋不得穿 ground truth 的衣服。

## 验收(逐条可核)
- [ ] 手机经 Tailscale 打开当日 `/briefs/...morning.html` 正常渲染
- [ ] json 三字段(liquidation_watch/distribution_risk/regime)在入口卡渲染为 chip
- [ ] 删掉当日 json 后入口卡呈灰态、按钮仍可打开 html
- [ ] 渲染器/CSS 零改动:对比 html footer build 标
      `build scout v3.3 · … · 渲染:_render_structured/_cand_card/_md_fallback` 仍在
- [ ] 决策面顺序 = BFS → SCOUT晨会 → 晚报 → 机房区
