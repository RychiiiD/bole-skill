---
name: bole-enrich-format
description: 富化最终输出格式化：过滤技术参数，保留面向查询的字段，输出 position_final_kb.csv
version: 1.0.0
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
---

Format the enrich pipeline final output. Filters out technical/internal fields,
retains only KB-relevant fields for knowledge base import.

---
## ★ 自检协议

### 操作前
- `data/position/output/position_final.csv` 是否已存在且非空？（需先完成 final_filter）

### 操作后
- `data/position/output/position_final_kb.csv` 是否已生成？
- `data/position/output/position_final_preview.csv` 是否已生成？
- 行数是否与 `position_final.csv` 一致？

---

## Steps

```bash
python scripts/enrich/enrich_format.py --config config.yaml
```

- Reads: `data/position/output/position_final.csv`
- Output: `data/position/output/position_final_kb.csv`（UTF-8 无 BOM，知识库导入用）
- Output: `data/position/output/position_final_preview.csv`（UTF-8 有 BOM，Excel 预览用）
- Output: `data/position/output/enrich_final_report.md`（最终数据报告）

This step is automatically triggered after `final_filter` in `/bole-enrich`,
and also automatically re-triggered after `enrich_fill.py save`.
