# Alpha Platform · Phase 0 部署(2026-07-24 今晚版)

## 今晚这刀切到哪

**有**:docker-compose 双服务(api :8600 + worker)· 1–5 分钟数据循环(TICK_SECONDS,默认 300s,下限 60s)· 加密行情(Coinbase 公共接口,免 key)· 美股 1-min bars(既有 Alpaca key,feed=iex)· 因子 v0 四件(ret_5m/ret_30m/vol_1m/range_pos,占位未验证)· BFS 候选→今日决策(entry=中价,stop/target 占位乘数)· 仪表盘(链路灯带 + 决策板 + 市场脉搏 + BFS 双窗)。
**没有(设计上)**:实盘接口(Grid 安全锁:沙箱验证+显式切换前不存在)· 回测引擎 · 因子挖掘 agents · 期权链全量(BFS 只读现成候选)。这些是 Phase 1+,不是遗漏。

## 部署(Cursor)

```bash
cd <仓库>/alpha-platform          # 解压本包到此
cp .env.example .env               # 填 GRID_STORE_DIR;Alpaca key 可选
docker compose up -d --build
open http://localhost:8600
```

验证:`curl localhost:8600/api/health` 五个组件全部上报;首个周期后 `/api/pulse` 有加密价;交易时段配了 Alpaca 则有美股行;BFS 窗口后 `/api/decisions` 出行。

## 纪律

- grid_store.db **只读**挂载;平台自己的数据在 ./data/platform.db,删目录即重置。
- 决策板所有数字 paper only;stop/target 乘数是占位参数,未经回测,不构成信号。
- 新增数据源/回测库(vectorbt 等)= 新依赖,进代码前先报 Lyra。
- **TICK_SECONDS 默认 300，铁则不动**（可见性/徽章/倒计时可以加，节奏不能改）。

## Sync topology (Alpha ↔ Aether · 2026-07-31)

| Writer | What | Cadence | Reader | Face period |
|--------|------|---------|--------|-------------|
| Aether scan daemons | `grid_store` `aether_scan` / brief | ET 交易窗 | Aether UI + Alpha BFS 原始区 | Aether poll 30s；BFS 原始**即时** |
| Alpha worker | bars/factors/`heat_nominations` | **TICK_SECONDS=300** | Console 热力/决策 | 下轮 tick `T-xxs` |
| Heat 动态提名 | env `WATCHLIST` 可空(无常驻席) + 当日 scan/movers 席≤8(禁 T+3) · `SURFACE_DENY` 仅否决 | worker tick | `/api/pulse` `source=watchlist\|scan`；超额→「扫描候选」 | tick-bound |
| Factory | `8600 → 8501 /factory/task` | on demand | `factor_drafts` | — |

**命名防误诊：** 8501 内任务分类模块代码名 `factory_task_router`，文档/日志显名 **「factory 分类器」**——**不是** `:8500` Grid Router。

## 数据升级梯子(到点再买,均需 Lyra 拍板)

1. Alpaca websocket 流(免费,同 key)——从轮询到推送,第一个零成本升级。
2. 期权深度:ORATS(带托管回测+greeks)或 ThetaData(按量便宜,自建回测)。
3. tick/L2:Databento 计量制(~$100-500/月量级)。

## Phase 1 蓝图(下一张单)

回测引擎接入 · Mock Wallet lane 并入平台账本 · 因子库正式化(替换 v0)· watchdog 四环并入链路灯带 · 加密 paper lane。

---

# Phase 0.5 增量(同夜第二刀)

**新增**:React app(Vite,`/app` 路径)三页——运维台(ws 实时链路灯带+决策+脉搏)、**ALPHA 工坊**(因子回放任务:真实计算流式进度,进度条与生长曲线的每个点都是完成的计算;lightweight-charts 渲染)、**粒子场 v0**(Three.js 方块场:尺寸=波动、颜色=方向、速度=动量;WebAudio 声音开关)。后端新增 `/ws/stream` 扇出、`/api/jobs/factor_replay`、jobs 进度事件表。

**部署差异**:`docker compose up -d --build` 会先跑 `web` 服务(node 容器内 npm ci + vite build,产物进共享卷),api 在 `/app` 挂载。原生运维页仍在 `/`。

**验证**:
1. `open http://localhost:8600/app` → 三页可切换,运维台灯带 2s 级刷新。
2. ALPHA 工坊点「启动回放」→ 进度条爬升、曲线逐点生长(需 worker 已采过美股 bars;无数据则事件流如实显示 no_data,不出假点)。
3. 粒子场:方块随 5 分钟因子变色变速。
