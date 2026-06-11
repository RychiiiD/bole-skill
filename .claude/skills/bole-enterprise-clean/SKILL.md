---
name: bole-enterprise-clean
description: 多来源企业名录清洗去重合并
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

Deduplicate and merge enterprise qualification data from multiple government sources.

---

## ★ 强制自检协议（必须遵守，违反即违规）

### 清洗前自检清单

```yaml
1. 输入文件验证:
   - data/enterprise/raw/qualification_lists/ 目录下是否有 CSV 文件？
   - 文件列表: {列出所有文件}
   - 每个文件是否非空且有 company_name 列？
2. 预处理计数:
   - 各来源去重前的企业总数（粗略统计）
   - 涉及多少个政府来源？
```

### 清洗后自检清单

```yaml
1. 输出文件验证:
   - data/enterprise/processed/enterprise_cleaned.csv 是否存在？
   - data/enterprise/processed/enterprise_cleaned.csv 是否存在？
   - 两个文件是否都非空？
2. 去重效果验证:
   - 去重前企业总数: {N_before}
   - 去重后企业总数: {N_after}
   - 重复率: (N_before - N_after) / N_before × 100%
   - 如重复率 > 60% → 检查是否同一批企业在多个来源中高度重叠
3. 资质分布检查:
   - 每个资质类型的企业数量:
     ├─ 专精特新: {count}
     ├─ 高新技术企业: {count}
     ├─ 瞪羚/独角兽: {count}
     └─ 其他: {count}
   - 是否有某类型数量为 0？→ 确认是该城市确实无该类型企业
4. 残留重复检查:
   - 检查 enterprise_cleaned.csv 中 company_name 是否有重复值
   - 如有 → 去重脚本有问题
5. 画像数据合并验证:
   - enterprise_cleaned.csv 中多来源资质是否已合并去重？
   - benefits/company_size/official_website 列是否有值？
```

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 不去记录清洗前数量 | 必须记录前/后对比 |
| 不检查资质分布 | 必须统计每类企业数量 |
| 不去检查 company_name 是否有残留重复 | 必须验证去重彻底性 |
| 遇到偏离原始流程的决定（跳过清洗步骤、缩减检查量、用部分结果替代完整结果、流程未明确规定时的替代方案） | 必须暂停并询问用户，不得自行决定 |

## Steps

1. Run the cleaning script:
   ```bash
   python scripts/enterprise/enterprise_clean.py --config config.yaml
   ```

2. Read `data/enterprise/processed/enterprise_cleaned.csv` and report:
   - Total unique enterprises after dedup
   - Qualification distribution (count per category)
   - How many sources were merged
   - How many enterprises have profile data (benefits/company_size)
   - Dedup rate (pre/post comparison)

## Output

One file is generated in `data/enterprise/processed/`:
- `enterprise_cleaned.csv` — deduped qualification data (consumed by enterprise_score.py)

Consumed by `enterprise_score.py` → `enterprise_scored.csv` (评分输出), then by `enrich.py`.
