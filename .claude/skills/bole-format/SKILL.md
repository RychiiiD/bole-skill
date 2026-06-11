---
name: bole-format
description: 知识库导入优化：过滤技术参数，保留面向查询的字段，输出 position_basic.csv
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

Format the scored job data into a clean output CSV for knowledge base import.
Removes internal technical fields (search keywords, collection timestamps, sub-dimension scores)
while keeping essential query fields.

---
## ★ 自检协议

### 操作前
- `data/position/processed/position_scored.csv` 评分数据是否已存在且非空？

### 操作后
- `data/position/output/position_basic.csv` 是否已生成？
- 行数（不含表头）是否与 `position_scored.csv` 一致？（格式化不增减行数）

---

## Steps

### Run Formatting

```bash
python scripts/job/format.py --config config.yaml
```

- Reads: `data/position/processed/position_scored.csv`
- Output: `data/position/output/position_basic.csv`（UTF-8 无 BOM，知识库导入用）
  — removes `search_keyword`, `collect_time`, sub-dimension scores and other internal fields
- Output: `data/position/output/position_basic_bom.csv`（UTF-8 有 BOM，Excel 预览用）
- Output: `data/position/output/position_report.md`（数据报告）

## Usage

```bash
/bole-format
```

Or as part of the full pipeline: `/bole`
