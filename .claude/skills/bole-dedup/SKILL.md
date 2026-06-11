---
name: bole-dedup
description: 多来源去重合并
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

Deduplicate and merge job listings from multiple sources.

---

## ★ 强制自检协议（必须遵守，违反即违规）

### 去重前自检清单

运行去重脚本前，**必须**执行：

```yaml
1. merge_raw.py 是否已运行？→ [是/否]（否→先运行）
2. 合并后的 CSV 文件是否存在？
   - data/position/processed/merged.csv 或类似合并输出
3. 记录去重前总数:
   - 记录合并后 CSV 的总行数（含表头为行数-1）

### 去重后自检清单

去重完成后，**必须**执行：

```yaml
1. 输出文件验证:
   - data/position/processed/deduped.csv 是否存在？
   - 文件是否非空（> 1 行，即至少 1 条数据 + 表头）？
2. 去重效果验证:
   - 去重前总行数（不含表头）: {N_before}
   - 去重后总行数（不含表头）: {N_after}
   - 重复率: (N_before - N_after) / N_before × 100%
   - 如果重复率 > 50% → 检查是否有异常（如同一来源内部大量重复）
   - 如果重复率 = 0% → 仍需确认是否因缺少 company_name 字段导致去重失效
3. 残留重复检查（抽样）:
   - 随机抽查 10 条，检查是否有(company_name, job_title)完全相同的条目
   - 如有残留重复 → 去重脚本需排查
4. 来源分布:
   - 去重后的数据来自哪些来源？
   - 是否有来源被完全去重掉？（所有条目都重复→该来源无独立数据）
```

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 不运行 merge_raw.py 直接去重 | 必须先合并为 CSV |
| 不去记录去重前数量 | 必须记录前/后对比 |
| 看到去重结果为空直接跳过 | 排查是数据问题还是去重逻辑问题 |
| 遇到偏离原始流程的决定（跳过步骤、缩减采集量、用部分结果替代完整结果、流程未明确规定时的替代方案） | 必须暂停并询问用户，不得自行决定 |

## Prerequisites

采集结果 JSON 文件需已通过 `merge_raw.py` 合并为 CSV：

```bash
python scripts/job/merge_raw.py
```

## Steps

1. Run `python scripts/job/dedup.py --config config.yaml`
2. Read `data/position/processed/deduped.csv` and report:
   - Total unique jobs after dedup
   - How many sources were merged
   - Dedup rate (pre/post counts)
