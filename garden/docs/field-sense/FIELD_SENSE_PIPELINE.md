# Cursor 整包:8787 场感应 → field_now → 全模态前端 全打通
# field-sense-pipeline v1 · 2026-07-20
# 三步严格按序执行,每步验收过了才进下一步。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 总不变量(写进每个改动文件的头注释)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 数据流单向:Garden → field_now → 9B。对话内容/模型输出永不写回
   Garden 或 field_now。感官进大脑,大脑不写感官(同 watcher 桥)。
2. FIELD_NOW 及场感知数据只进 Local 9B,永不进 kimiMessages()。
   云端隔离清单已含 FIELD_NOW,此处只是新增本地通路,云门不动。
3. 场数据进 prompt 只给摘要三字段(coherence/state/breath_sync),
   不给 telemetry 全量。最小上下文原则对内同样适用。
4. anchor 层不拟人、不说话、不做存在断言(garden_anchor_spec_v2 E 节
   逐字继承)。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 第 1 步:Garden Anchor v2 落地(8787 前端 + 本地服务)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
按 garden_anchor_spec_v2.md 全文执行(A 力学层参数 / B1 双流 /
B2 暗湖 / B3 呼吸 / B4 触碰 / B5 面板 / B6 共振日记 / C telemetry)。
spec 已完整,不复述。此处只强调:

- C 节 telemetry 是第 2 步的接口契约,字段名严格照抄:
  anchor_coherence / anchor_state / breath_sync / today_peak
- /telemetry.json 只绑 127.0.0.1,不上 0.0.0.0
- ?anchor=off 对照参数必须做——它同时是第 2 步的校准工具

**第 1 步验收 = spec D 清单全过。首要项:开关 anchor 画面差异
一眼可辨。未全过不得进第 2 步。**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 第 2 步:field_now 接 sense_garden()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
改 field_now_v1_5.py(版本号升 v1.6):

```python
# ---- sense_garden: 8787 anchor telemetry (read-only, fail-soft) ----
GARDEN_TELEMETRY_URL = "http://127.0.0.1:8787/telemetry.json"
GARDEN_TIMEOUT = 1.5          # 秒。Garden 慢/挂,field_now 不能被拖住
GARDEN_STALE_SEC = 30         # 数据超过 30s 视为过期,按 idle 处理

def sense_garden() -> dict:
    """读 Garden anchor 遥测。只读;任何失败返回 idle 态,不抛异常。"""
    import time, requests
    idle = {"garden": "idle", "anchor_coherence": None,
            "anchor_state": "idle", "breath_sync": None}
    try:
        r = requests.get(GARDEN_TELEMETRY_URL, timeout=GARDEN_TIMEOUT)
        if r.status_code != 200:
            return idle
        j = r.json()
        ts = j.get("ts")
        if ts and time.time() - float(ts) > GARDEN_STALE_SEC:
            return idle                      # 过期数据不冒充在场
        return {
            "garden": "live",
            "anchor_coherence": j.get("anchor_coherence"),
            "anchor_state": j.get("anchor_state", "idle"),
            "breath_sync": j.get("breath_sync"),
        }
    except Exception:
        return idle                          # fail-soft:感官失灵≠大脑宕机
```

接入点:FIELD_NOW 组装处并入 sense_garden() 返回值,键名前缀
不加(三字段名已带 anchor_/breath_ 语义)。

要求:
- telemetry C 节需补一个 "ts" 字段(unix 秒),Garden 侧顺手加上,
  供过期判断。没有 ts 的旧格式按 idle 处理。
- **只读**。field_now 不得向 8787 发任何写请求。
- 日志:garden live→idle / idle→live 状态翻转各记一行,平时不刷屏。

第 2 步验收:
- [ ] Garden 开着说话 → FIELD_NOW 出现 coherence/state 实时值
- [ ] kill Garden 进程 → field_now 无报错,字段回 idle,翻转日志一行
- [ ] Garden 挂起(kill -STOP)→ field_now 1.5s 超时后照常运行
- [ ] 篡改 ts 为 1 小时前 → 按 idle 处理(过期不冒充在场)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 第 3 步:全模态前端加「场感知」开关
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
改 grid_multimodal_v2.html(逻辑区改动,粒子层不动):

3a. 配置面板加一项:
    label: 场感知 url(可选,留空=关)
    id: cField · 默认空 · 存 localStorage 键 mmwb_field
    填 field_now 的本地快照端点(如 http://127.0.0.1:8501/field_now
    或 Cursor 按现有 field_now 暴露方式定,只读 GET)。

3b. Route & Boundary 面板 lights 区追加一盏:
    <span class="off">Field <b id="fieldLight">off</b></span>
    状态:off(未配置)/ live(读到数据)/ idle(配置了但 idle/失联)。
    颜色沿用现有 off/risk 类,不新增色彩语义。

3c. 发送逻辑改动 —— 只动 localMessages():

```js
let fieldCache={data:null,ts:0};
async function senseField(){                 // 8s 缓存,fail-soft
  if(!cfg.field) return null;
  if(Date.now()-fieldCache.ts<8000) return fieldCache.data;
  try{
    const r=await fetch(cfg.field,{signal:AbortSignal.timeout(1500)});
    const j=await r.json();
    fieldCache={data:j,ts:Date.now()};
    return j;
  }catch(e){fieldCache={data:null,ts:Date.now()};return null}
}
function fieldLine(f){                        // 摘要三字段,一行,不给全量
  if(!f||f.anchor_state==="idle"||f.anchor_coherence==null) return "";
  return `[场态 coherence=${(+f.anchor_coherence).toFixed(2)} `
       + `state=${f.anchor_state}`
       + (f.breath_sync!=null?` breath_sync=${Math.round(f.breath_sync*100)}%`:"")
       + `]\n`;
}
```

localMessages() 组装时,在当前用户消息 content 最前面拼 fieldLine()。
**kimiMessages() 一个字符不改** —— diff 里出现 kimiMessages 改动
即整包打回。

3d. UI 微量:you 气泡下方,若本条附了场态,加一行
    <div class="meta">·场感知已附(仅本地)</div>
    字体沿用 .asset .meta 样式。用户要能看见"这条带了场态",
    正如能看见"这条带了素材"。

3e. 开关灯逻辑:senseField() 每次调用后更新 #fieldLight:
    null→(cfg.field?idle:off) / 有数据且 state!=idle→live。

第 3 步验收:
- [ ] 未配置 url:Field 灯 off,行为与 v2 完全一致(回归)
- [ ] 配置后 Garden 活跃:发消息,9B 收到的首行含 [场态 …],
      you 气泡下出现"场感知已附(仅本地)"
- [ ] 同条消息切 Kimi/Shadow 路由:抓包确认发往 kimi 模型的请求体
      不含"场态"字样 —— **本包最重要的一条验收**
- [ ] kill field_now:发送不阻塞(1.5s 超时),Field 灯回 idle
- [ ] Garden idle 时:fieldLine 返回空,不附伪在场数据

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 交付物
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Garden anchor v2 完整实现 + spec D 验收截图(含 ?anchor=off 对照)
2. field_now_v1_6.py diff
3. grid_multimodal_v2.html 逻辑区 diff(粒子层零改动)
4. 第 3 步验收⑤条的真实测试记录(抓包截图为证)
不收 mock,不收文字说明代替实测。
