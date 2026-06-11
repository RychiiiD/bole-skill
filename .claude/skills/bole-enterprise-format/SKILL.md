---
name: bole-enterprise-format
description: 企业知识库导入优化：过滤技术参数，保留面向查询的字段，输出 enterprise_basic.csv
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

Format the scored enterprise data into a clean output CSV for knowledge base import.
Removes technical/intermediate fields (raw names, sub-dimension scores) while
keeping all essential query fields (company name, qualifications, tier, score, priority).

---
## ★ 自检协议

### 操作前
- `data/enterprise/processed/enterprise_scored.csv` 评分数据是否已存在且非空？

### 操作后
- `data/enterprise/output/enterprise_basic.csv` 是否已生成？
- 行数是否与 `enterprise_scored.csv` 一致？

---

## Steps

### Run Formatting

```bash
python scripts/enterprise/enterprise_format.py --config config.yaml
```

- Reads: `data/enterprise/processed/enterprise_scored.csv`
- Output: `data/enterprise/output/enterprise_basic.csv`（UTF-8 无 BOM，知识库导入用）
  — removes `company_name_raw` and intermediate scoring fields
- Output: `data/enterprise/output/enterprise_basic_bom.csv`（UTF-8 有 BOM，Excel 预览用）
- Output: `data/enterprise/output/enterprise_report.md`（数据报告）

## Usage

```bash
/bole-enterprise-format
```

Or as part of the full pipeline: `/bole-enterprise`
