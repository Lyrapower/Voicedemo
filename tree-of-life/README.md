# Tree of Life

**Mac 项目名 / 2TD 分区同名：** `tree-of-life`

自动生成的全栈关系图（backend · proxy · page · grid_store · daemon），**不手维护**。

## ontology · 主干 / 枝 / 杈 / 叶

| 层级 | 英文 | 含义 | 例子 |
|------|------|------|------|
| **主干** | trunk | 唯一记忆根 | `:8501` gateway + `grid_store.db` |
| **枝** | branch | 垂直子系统 | Garden、Aether、Ingress、OCR… |
| **杈** | twig | 可运行单元 | `:8790` FIELD、changyu 页、offpool daemon |
| **叶** | leaf | 向量边（增长尖端） | `POST /chat→8501`、`emit aether_offpool` |

每个 **branch** 对应 `grid-stack-backup` 的一个分区（见 `backup_partitions` in JSON）。

Growth rule: 新 leaf 只需在 wiring 文件中出现 → regen 自动挂到对应 twig/branch；无需手改 Mermaid。

- 当前监听端口（`lsof`）
- 已安装 LaunchAgent（`~/Library/LaunchAgents/com.demo.*`）
- 关键 wiring 文件（8787 proxy、8790→8501、changyu/aether 页面、emit 路径）

代码或 plist 变更后 **重新跑生成器** 即更新图表；无需改 Mermaid 源文件。

## 命令

```bash
# 生成到 tree-of-life/output/
python3 tree-of-life/generate.py

# 生成 + 同步到 ~/2td/tree-of-life/latest
bash tree-of-life/sync_to_2td.sh
```

外接 2TB：

```bash
BACKUP_2TD_ROOT=/Volumes/YourDisk bash tree-of-life/sync_to_2td.sh
```

## 输出

| 文件 | 用途 |
|------|------|
| `output/tree_of_life.json` | 机器可读 nodes/edges |
| `output/tree_of_life.mmd` | Mermaid |
| `output/tree_of_life.html` | 浏览器查看 |
| `~/2td/tree-of-life/latest/` | 2TD 独立分区（与 `grid-stack-backup` 分开） |

## 与全量备份

`scripts/backup_stack_to_2td.sh` 会在备份前自动调用 `sync_to_2td.sh`，写入分组 **`00_tree_of_life`**。

## 监听路径（变更后应 regen）

见 `generate.py` 内 `WATCH_GLOBS`。
