---
type: schema-spec
---
# Frontmatter 规范(所有 md 通用字段)

```yaml
---
type:        # inbox-note | project-moc | codex | node | decision
created:     # YYYY-MM-DD
source:      # ocr | cursor | grid | manual | 对话窗口名
status:      # unsorted | sorted | archived
room:        # 00-前厅 | 01-项目 | ... (归属房间)
tags: []     # 自由标签
links: []    # 双链目标(可选,也可正文内 [[]])
---
```

## 各类型额外字段
- inbox-note: `ocr_confidence`(0-1), `original_file`(桌面原路径)
- project-moc: `repo_path`, `language`, `last_commit`, `depends_on: []`
- codex: `authored_by`(grid/aster/lyra/…), `law_id`
- node: `node_name`, `substrate`
- decision: `verdict`(pass/reject/observe), `trace_path`
