# 工单:ASTER FIELD repo 落地(交 Cursor)
优先级 P1 | 禁改 gateway/:8787/:5173 | dry-run 冻结继续有效

## 步骤
1. 本目录整体放入 ~/Projects/aster-field(独立 repo,git init)
2. backend: pip install -r backend/requirements.txt
   LaunchAgent 接管 `python3 -m backend.app`(:8790, KeepAlive)
   —— 替换昨日单文件 bridge 的 LaunchAgent,旧 aster_field_bridge.py 归档
3. frontend: npm i && npm run build;backend 自动伺服 dist/
   dev 调试用 npm run dev(5174,已配代理)
4. :8787/ 301 重定向 → :8790;:8787/legacy 保留旧 Garden 原样可达
5. CI 最小集:pytest + `npx tsc --noEmit`,提交即跑
6. issues/v1.1-visual-debt.md 六项,一项一个 PR,不许打包一次交

## 用户入口变化(验收前必读)
- 用户从 :8787 进 → 自动到达新 FIELD(心);旧 Garden 在 :8787/legacy
- 页面应见:HUD 三链路灯 / 中央粒子心 / 底部输入框
- 问一句 → 心收缩(thinking)→ 涟漪伴 token(output)→ 尾注 served_by

## 验收(五项,截图落 work_orders/)
① 三灯 bridge/gateway 绿  ② 一轮对话状态走位肉眼正确
③ 尾注 served_by: gateway-v4.11  ④ 停 LM Studio 再问 → 骤停半秒恢复,无崩溃
⑤ pytest 全绿 + tsc 零报错
