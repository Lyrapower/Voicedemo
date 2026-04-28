# 终端启动 · Garden / sound-lab

## 目标

- **8788** — 遥测 stub（`bash scripts/start_telemetry.sh`）  
- **5173** — Vite 粒子 UI（`bash scripts/start_sound_lab.sh`）  
- **8787** — Aster Router，**把浏览器请求反向代理到 5173**，因此打开 **http://127.0.0.1:8787/** 即粒子界面。

## 可选：先清进程

```bash
bash scripts/kill_sound_lab_dev.sh
```

## 三个终端（仓库根目录 `demo`）

```bash
bash scripts/start_telemetry.sh
```

```bash
bash scripts/start_sound_lab.sh
```

```bash
cd repo && ./scripts/run.sh
```

浏览器：**http://127.0.0.1:8787/**

---

说明见 **[`../../docs/README.md`](../../docs/README.md)**。
