# factory 分类器（显名）

代码模块：`grid-sovereign-runtime/gateway/factory_task_router.py`  
HTTP：`POST :8501/factory/task`

| 名称 | 是什么 | 不是什么 |
|------|--------|----------|
| **factory 分类器** | 8501 内对 Alpha Factory `propose`/`review_explain`/`fix_error` 的任务分类与路由 | `:8500` Router（Entry A / map_intent） |
| `:8500` Router | Grid Entry A 意图映射 | Factory 提案路径 |

误诊常见点：把「local / glm 路由偏少」归咎于 8500 宕机——应查 **8501 factory 分类器** 的 prompt 长度与 `classify_task_type`，而非 8500。

本仓 Alpha 侧（8600）meta/文档一律写「factory 分类器」；gateway 源码文件名可保留，**零 diff 铁则下不改 gateway 文件**。
