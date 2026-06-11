---
name: bole-enrich
description: 企业数据匹配富化：将企业资质和画像合并到岗位数据中（步骤由 pipeline.py 强制校验顺序）
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

Merge enterprise qualification and profile data into job position data.
This is a bridge step between the independent position and enterprise pipelines.

---

## ★ 强制自检协议（必须遵守，违反即违规）

### 富化前自检清单

运行 enrich.py 前，**必须**执行：

```yaml
1. 两条管线是否都已完成？
   - /bole 管线 → data/position/processed/position_scored.csv
   - /bole-enterprise 管线 → data/enterprise/processed/enterprise_scored.csv
2. 文件完整性:
   - position_scored.csv 行数（不含表头）: {记录数量}
   - enterprise_scored.csv 企业数: {记录数量}
   - 如果任意文件为空 → 先完成对应管线
3. 公司名列确认:
   - position_scored.csv 中用于匹配的公司名列名是什么？
   - enterprise_scored.csv 中用于匹配的公司名列名是什么？
   - 两边的公司名格式是否一致？（如"长春XX科技有限公司" vs "长春 XX 科技有限公司"）
```

### 富化后自检清单

富化完成后，**必须**执行：

```yaml
1. 输出文件验证:
   - data/position/output/position_enriched.csv 是否存在？
   - data/position/output/enrich_report.md 是否存在？
2. 富化率检查:
   - 岗位总数: {total_jobs}
   - 匹配到企业数据的岗位数: {matched_jobs}
   - 富化率: matched_jobs / total_jobs × 100%
   - 如果富化率 < 20% → 检查匹配逻辑（公司名格式差异？）
   - 如果富化率 > 90% → 检查是否有过匹配（如空字符串匹配）
3. 富化字段完整性:
   - has_enterprise_data 列是否存在并正确赋值？
   - 企业相关列（qualification/benefits/company_size/official_website）是否存在？
   - **enrich-fill 补充后**: benefits / company_size / enterprise_categories 是否已完整填充？
4. 抽样验证:
   - 随机抽 3 条 has_enterprise_data=true 的条目，手动核对:
     - matched_company_name 是否确实是正确的公司？
     - qualification 是否源自该公司的资质名单？
   - 随机抽 2 条 has_enterprise_data=false 的条目，确认确实无对应企业数据
5. 行数一致性:
   - position_enriched.csv 行数（不含表头）是否与 position_scored.csv 一致？
   - 富化不增减行数，只增加列
   - 不一致 → 排查 enrich.py 是否有过滤
6. enrich_report.md 验证:
   - 是否包含富化率统计？
   - 是否包含匹配方式分布（exact / normalized / substring）？
```

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 不超过富化率直接提交 | 必须检查匹配覆盖率 |
| 不验证匹配准确性 | 必须抽样核对 3 条以上 |
| 行数变化不排查 | 富化不应增减行数 |
| 遇到偏离原始流程的决定（跳过来源/步骤、缩减匹配量、用部分结果替代完整结果、流程未明确规定时的替代方案） | 必须暂停并询问用户，不得自行决定 |

## Prerequisites

Before running this step, both pipelines must have completed:

- `/bole` completed → `data/position/processed/position_scored.csv` exists
- `/bole-enterprise` completed → `data/enterprise/processed/enterprise_scored.csv` exists

## Steps

每个步骤必须严格按照以下流程执行：

1. **PRE-CHECK** — 运行 `python scripts/pipeline/pipeline.py check enrich <step_id>`，确认前置步骤已完成
2. **执行步骤内容**
3. **POST-COMPLETE** — 运行 `python scripts/pipeline/pipeline.py complete enrich <step_id>` 标记完成

---

### Step 0 — 模式确认
**step_id**: `enrich`

```bash
python scripts/pipeline/pipeline.py check enrich enrich || exit 1
```

确保两条前置管线已完成。验证文件存在：

```bash
test -f data/position/processed/position_scored.csv && echo "[OK] 岗位数据就绪" || echo "[WARN] 缺少岗位数据"
test -f data/enterprise/processed/enterprise_scored.csv && echo "[OK] 企业数据就绪" || echo "[WARN] 缺少企业数据"
```

### Step 1 — Run Enrichment

Merge enterprise data into job data with 3-phase company name matching
(exact → normalized → substring containment), and output the final
enriched CSV directly. Includes company quality bonus scoring.

```bash
python scripts/enrich/enrich.py --config config.yaml
```

- Reads: `data/position/processed/position_scored.csv` + `data/enterprise/processed/enterprise_scored.csv`
- Matches companies by name and merges: qualification categories,
  benefits (deduplicated), company size, official website
- 根据企业资质计算 `company_quality_bonus`（+2/+4/+6/+8/+10 分）
  和 `company_quality_reason`（加分原因说明），输出 `final_score = total_score + bonus`
- Output: `data/position/output/position_enriched.csv` (过程文件, UTF-8 无 BOM)
- Output: `data/position/output/enrich_report.md` (富化报告, 含资质加分分布)

After completion:

```bash
python scripts/pipeline/pipeline.py complete enrich enrich
```

---

### Step 2 — Report
**step_id**: `report`

```bash
python scripts/pipeline/pipeline.py check enrich report || exit 1
```

Read `data/position/output/position_enriched.csv` and print:
- Total jobs
- Enterprise-matched count (has_enterprise_data=true)
- Quality bonus distribution (company_quality_bonus stats)
- Top 5 enriched entries with company name, enterprise categories, and bonus

After completion:

```bash
python scripts/pipeline/pipeline.py complete enrich report
```

---

### Step 3 — Final Filter（标准步骤，自动执行）

在 enrich 匹配评分后直接运行，无需等待 enrich-fill。利用已有企业数据过滤低质岗位。

```bash
python scripts/enrich/final_filter.py --config config.yaml
```

过滤规则（`config.yaml → scoring.enterprise_filter`）：
- **个体工商户名称检测**：以"店/馆/行/坊/庄"结尾、含"经营部/服务部/批发部"、名称截断含"..."
- **企业数据空值检测**：has_enterprise_data=false 且企业信息全网未检索到
- **微小企业检测**：规模少于50人且无企业资质
- **兼职检测**：时薪制（元/时）/日薪制薪资

输出说明：
- 读取 `data/position/output/position_enriched.csv`，输出 `data/position/output/position_final.csv`（最终版本）

```bash
python scripts/pipeline/pipeline.py complete enrich final_filter
```

### Step 4 — Format（输出知识库导入版）

过滤技术参数字段，保留知识库导入所需的检索字段，输出 basic 版 CSV 和数据报告。

```bash
python scripts/enrich/enrich_format.py --config config.yaml
```

After completion:

```bash
python scripts/pipeline/pipeline.py complete enrich format
```

## Usage

```bash
/bole-enrich      # 富化：合并企业数据 → 输出 position_enriched.csv → 最终过滤 → 格式化输出 → position_final_kb.csv
```

Run after both `/bole` and `/bole-enterprise` have completed. 

若后续执行 `/bole-enrich-fill` 补充画像，fill 完成后自动重新执行 format，更新 position_final_kb.csv。
