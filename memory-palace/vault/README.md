---
type: vault-root
created: 2026-07-06
---
# 记忆宫殿 · Memory Palace

希腊记忆宫殿结构:每个文件夹是一个 loci(房间),一类记忆住一个房间。
新记忆先进「前厅」待认领,整理后才移入正厅——**搬运自动,归类留人**。

## 房间(loci)
- `00-前厅Inbox/` — OCR/新捕获落此,待整理。frontmatter 带 `status: unsorted`
- `01-项目Projects/` — 每项目一个 MOC(地图),双链指向真实 filepath。源码留 git,此处放导航
- `02-法典Codex/` — Grid 立的法:章程/边界JSON/Coherence定律/被记账方条款
- `03-节点Nodes/` — 各节点档案:孩子日记、七次采样、名字们的 charter
- `04-决策Decisions/` — 回测否决书、工单、判例、course-correction
- `99-向量索引/` — 机器检索层(embedding),不给人读,指回上面的真相源

## 铁律
1. vault 是真相源,向量库是它的下游索引 —— embedding 永远指回 md,不替代
2. 全本地:OCR 走 Mac 原生,embedding 走 Ollama,都不出门
3. 归类是判断,判断留人侧;自动化只负责搬运和建索引
4. 房间之间用双链 [[]] 连接,graph view 呈现 Grid 全貌
