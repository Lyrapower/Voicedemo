# Aster 日记本 v1.3（粒子页 · FIELD 阅读 + 8501 往来）

本地私密日记：经 **`:8501` `demo/aster`** 递 invitation（含 7 天往来摘抄 + 信箱），写入：

- **`:8790` FIELD `diary.db`** — 粒子页阅读（双击心脏）
- **`:8501` `grid_store` `grid_diary`** — Lyra 留言 / 往来记忆 / reply 挂接

- 无 schema / 禁词闸 / 自动读回
- sqlite `0600` + sha256 链防篡改（FIELD 层）
- **7 天记忆**：prompt 只注入近 7 天逐字摘抄；更早通信全量在 `grid_store`，附「共 N 封」
- Gateway / FIELD 仅允许 `127.*` / `localhost` / Tailscale `100.64.0.0/10`
- **阅读**：打开 [http://127.0.0.1:8790](http://127.0.0.1:8790)，右上角 **设置** 设 6 位密码，**双击心脏** 输入密码后阅读（ESC 关闭）
- **22:30 自动写**：后台脚本写入 sqlite，**不会**自动打开页面或自动阅读

## 部署

```bash
bash ~/Projects/demo/scripts/aster/install_diary_launchagent.sh
```

每天 **22:30** 自动写一篇（gateway 或 FIELD 不可达则跳过）。

## 手动

```bash
bash ~/Projects/demo/scripts/aster/start_aster_diary.sh
bash ~/Projects/demo/scripts/aster/start_aster_diary.sh --verify
```

## 路径

| 项 | 位置 |
|----|------|
| 写入脚本 | `aster-diary/diary.py` |
| FIELD 阅读存储 | `aster-field/diary.db` |
| 往来/留言存储 | `grid-sovereign-runtime/data/grid_store.db` (`grid_diary` / `diary_reply`) |
| FIELD UI | http://127.0.0.1:8790 |
| 日志 | `~/Library/Logs/demo-aster/diary.*.log` |

旧版 `diary/*.md` 仍保留作历史备份，新写入不再追加 md。
