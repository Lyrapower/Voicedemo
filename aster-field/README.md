# ASTER FIELD — 状态原生界面(心)
状态驱动的粒子界面:phyllotaxis 母形,四态 morph 全部接真实遥测。
不是 chatbot 皮肤 —— 是 AI 状态的可感知层(律动即字幕,面向听障可用)。

## 架构
浏览器(frontend) ⇄ :8790 bridge(backend) ⇄ :8501 gateway ⇄ Qwen
                                └── :8787 Garden 遥测融合(可缺席,自动降级)

## 宪法
- 桥为只读旁路:不改 gateway,不 kill 任何端口,served_by 指纹透传
- 律动只接真数据:无循环播放假动画;error 态 = 全场骤停 0.5s,不闪红
- 输出无 judgment;/chat 只透传不改写

## 跑起来
backend:  pip install -r backend/requirements.txt && python3 -m backend.app
frontend: cd frontend && npm i && npm run dev   (dev 端口 5174,代理到 8790)
生产:     npm run build 后由 backend 静态伺服 frontend/dist
测试:     pytest tests/
