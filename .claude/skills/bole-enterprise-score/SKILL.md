---
name: bole-enterprise-score
description: 按岗位覆盖 + 资质等级给企业评分排序（三层级 + 行业匹配）
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

Score enterprises by three-tier classification (A/B/C) with industry fit,
then output a priority-ranked list for profile collection ordering.

---
## ★ 强制自检协议（必须遵守，违反即违规）

### 评分前自检清单

```yaml
1. 输入文件验证:
   - data/enterprise/processed/enterprise_cleaned.csv 是否存在？
   - data/position/processed/position_scored.csv 是否存在？
2. 行业信号词文件:
   - data/enterprise/.industry_keywords.json 是否存在？
   - 如不存在 → 先执行 Step 0 生成
3. 数据格式:
   - enterprise_cleaned.csv 是否有 company_name / enterprise_categories 列？
   - position_scored.csv 是否有 company_name / total_score / salary_score 列？
```

### 评分后自检清单

```yaml
1. 输出文件验证:
   - data/enterprise/processed/enterprise_scored.csv 是否存在？
   - 文件是否非空？
2. 三层级验证:
   - Level A（双在册）: {count} 家（预期 ~37）
   - Level B（仅岗位）: {count} 家（预期 ~791）
   - Level C（仅资质）: {count} 家（预期 ~4676）
   - 总数是否 = 资质企业数 + 岗位独有企业数？（5504）
3. 分数范围验证（0-50）:
   - total_score 列是否都在 0-50 范围内？
4. priority 分布验证:
   - high（≥30 分）: {count} 家 — 是否合理？
   - medium（≥15 分）: {count} 家
   - low（<15 分）: {count} 家
   - 如果 low=0 → 阈值可能偏低，建议向用户提示
5. Level B 前筛确认:
   - 前筛建议是否已展示给用户？
   - 用户确认的阈值是什么？
6. Level C 准入门槛确认:
   - 用户划线的准入门槛是什么？
   - 当前 Level C 中进入画像队列的是哪些资质等级？
7. industry_fit 验证:
   - industry_keywords.json 中的 target_kw / exclude_kw 是否已应用？
   - top 5 企业的 industry_fit_detail 是否合理？
```

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 不运行 Step 0 直接评分 | 行业信号词必须先推理+用户确认 |
| 行业信号词直接写死 | 必须从 config.yaml 动态推理 |
| 自行决定前筛阈值 | 展示分布 → 用户确认 |
| 自行决定 Level C 准入门槛 | 展示资质分布 → 用户划线 |
| 不验证分数范围 | 必须确认 total_score 在 0-50 内 |
| 不检查 priority 映射一致性 | 必须逐条验证 high/medium/low 阈值 |
| 看到 low=0 不提示用户 | 必须告知用户阈值是否合理 |
| 遇到偏离原始流程的决定 | 必须暂停并询问用户，不得自行决定 |

## Three-Tier Scoring Formula

### 三层级分类

```
输入交叉:
  资质企业清单（enterprise_cleaned.csv）× 岗位企业（position_scored.csv）
  
分类:
  Level A = 在资质名单中 + 有岗位匹配（双在册）
  Level B = 仅出现在岗位数据中（不在资质名单）
  Level C = 仅出现在资质名单中（无岗位匹配）
```

### 评分维度（每项 0-5）

| 维度 | 范围 | 含义 |
|------|:----:|------|
| **qual_score** | 0-5 | 政府背书等级（专精特新小巨人=5 → 科技型中小=1） |
| **job_quality** | 0-5 | 岗位质量综合（avg_total_score/20×0.5 + max_salary×0.3 + job_count/2×0.2） |
| **industry_fit** | 0-5 | 企业主营与目标赛道的匹配度（来自 .industry_keywords.json 机械匹配） |

### 分层评分公式

```
Level A（双在册，数据最全）:
  total = qual_score × 4 + job_quality × 4 + industry_fit × 2
  → 资质 + 岗位质量并重，行业匹配辅助，范围 0-50

Level B（仅岗位，无资质标签）:
  total = job_quality × 7 + industry_fit × 3
  → 岗位质量是核心信号，范围 0-50
  → 必须先验证再入画像队列

Level C（仅资质，无招聘动态）:
  total = qual_score × 6 + industry_fit × 4
  → 资质等级主导，行业匹配辅助，范围 0-50
  → 用户划线决定哪些等级入画像
```

### 优先级映射

```
priority = high   if total >= 30
           medium if total >= 15
           low    if total < 15
```

### 排序方式

```
排序 = Level 顺序（A → B → C），同 Level 内按 total_score 降序
```

## Steps

每个步骤必须严格按照以下流程执行：

1. **PRE-CHECK** — 运行 `python scripts/pipeline/pipeline.py check enterprise score`，确认前置步骤已完成
2. **执行步骤内容**
3. **POST-COMPLETE** — 运行 `python scripts/pipeline/pipeline.py complete enterprise score` 标记完成

---

### Step 0 — 推理行业信号词（★ 形式化步骤，pipeline.py 校验）

**step_id**: `industry_keywords`

**目的**：从 config.yaml 中用户的岗位配置动态推理目标赛道和排除赛道的行业信号词，不写死在代码中。

#### 前置检查

```bash
python scripts/pipeline/pipeline.py check enterprise industry_keywords || exit 1
```

#### 执行流程

1. 读取 `data/.bole_context.json` 的以下字段：
   - `title_keywords`（如 `["{岗位名}", "{岗位名EN}"]`）
   - `search_keywords`（如 `["{搜索关键词1}", "{搜索关键词2}"]`）
   - `city` / `province` / `region`

2. LLM 推理（基于岗位类型 + 城市产业背景），输出：

   ```yaml
   target_kw:         # 目标赛道信号词 — 企业名称命中则 industry_fit +1
     - "计算机软件"
     - "互联网"
     - "信息技术"
     - "人工智能"
     - "智能制造"
   
   exclude_kw:        # 排除赛道信号词 — 企业名称命中则 industry_fit -1
     - "建筑"
     - "房地产"
     - "纺织服装"
     - "食品餐饮"
   
   reasoning: >
     基于 title_keywords "产品经理/Product Manager" 和目标城市"{城市名}"的产业特点
     （汽车+光电+IT），推理出以上赛道信号词。
   ```

3. ★ **暂停，向用户展示推理结果**：

   ```
   ┌─────────────────────────────────────────────┐
   │ 基于 title_keywords: 产品经理, Product Manager│
   │ 和 city: 长春, 推理出行业信号词如下:          │
   │                                              │
   │ 目标赛道信号词 target_kw:                    │
   │   ["计算机软件", "互联网", "信息技术",        │
   │    "人工智能", "智能制造"]                   │
   │                                              │
   │ 排除赛道信号词 exclude_kw:                   │
   │   ["建筑", "房地产", "纺织服装", "食品餐饮"]  │
   │                                              │
   │ 请确认是否调整？(确认 / 编辑 / 重推理)         │
   └─────────────────────────────────────────────┘
   ```

   - 用户选「确认」→ 写入 `.industry_keywords.json`，进入下一步
   - 用户选「编辑」→ 用户在输入框中修改后写入
   - 用户选「重推理」→ 回到步骤 2 重新推理

4. 写入 `data/enterprise/.industry_keywords.json`：

   ```json
   {
     "target_kw": ["计算机软件", "互联网", ...],
     "exclude_kw": ["建筑", "房地产", ...],
     "reasoning": "基于 title_keywords ...",
     "_meta": {
       "confirmed_by_user": true,
       "confirmed_at": "2026-06-05T10:00:00+08:00"
     }
   }
   ```

   **AI 不得在用户确认前设置 `_meta.confirmed_by_user`。pipeline.py verify 会校验。**

完成后标记：

```bash
python scripts/pipeline/pipeline.py complete enterprise industry_keywords
```

---

### Step 1 — Run Scoring

Run the scoring script:

```bash
python scripts/enterprise/enterprise_score.py --config config.yaml
```

The script outputs:
- Three-tier classification stats (A/B/C counts)
- Level B pre-filter suggestions
- Level C qualification distribution
- Top 5 per tier

#### ★ 用户确认节点 1：Level B 前筛阈值

读取脚本输出的 Level B 前筛建议，向用户展示：

```
┌─────────────────────────────────────────────┐
│ Level B（仅岗位端）建议前筛阈值:              │
│                                              │
│  ① 最低薪资：< 6k → 建议排除                 │
│    当前 6k 以下企业数: XX 家（占比 X%）       │
│  ② 最少岗位数：1 条且薪资低 → 建议排除        │
│    仅 1 条岗位的企业数: XX 家                 │
│  ③ 最大沉寂天数：发布超 180 天 → 建议排除     │
│    超 180 天无更新的企业数: XX 家              │
│                                              │
│ 调整后预计排除: XX 家，保留: XX 家            │
│ 是否按建议执行？(确认 / 调整阈值)             │
└─────────────────────────────────────────────┘
```

- 用户选「确认」→ 记录阈值，在后面的验证环节使用
- 用户选「调整阈值」→ 用户指定新值，记录

#### ★ 用户确认节点 2：Level C 准入门槛

读取脚本输出的 Level C 资质分布，向用户展示：

```
┌─────────────────────────────────────────────┐
│ Level C（仅资质端）企业分布:                  │
│                                              │
│  专精特新小巨人/单项冠军:  XX 家              │
│  独角兽:                XX 家                │
│  专精特新/高新技术企业/瞪羚: XX 家            │
│  雏鹰企业:              XX 家                │
│  科技型中小企业:         XX 家                │
│                                              │
│ 建议进入画像队列: 专精特新/高企/瞪羚以上       │
│ （理由：这些资质等级与目标岗位相关性高）        │
│                                              │
│ 是否按此门槛执行？(确认 / 调整准入门槛)       │
└─────────────────────────────────────────────┘
```

- 用户选「确认」→ 记录门槛，后续画像只处理该资质等级以上的企业
- 用户选「调整」→ 用户指定准入门槛（如"只要高新技术企业以上"）

---

### Step 2 — Level B 批量验证（★ 新增）

在画像前，对 Level B 企业进行低成本验证。

#### 执行流程

1. **应用前筛阈值**：按 Step 1 用户确认的阈值过滤 Level B 企业
2. **WebSearch 批量验证**：

   对每个通过前筛的企业执行：
   ```bash
   WebSearch("{企业名} 长春 公司")
   ```

   判断标准：
   - 搜到官网/天眼查/企查查/新闻 → ✅ 验证通过
   - 搜到名称相似但不确定 → ❓ 不确定
   - 完全搜不到任何信息 → ❌ 未通过

3. ★ **用户确认节点 3：展示验证结果**：

   ```
   ┌─────────────────────────────────────────────┐
   │ Level B 企业验证结果:                        │
   │                                              │
   │  ✅ 验证通过（有公开信息）:  XXX 家            │
   │  ❌ 未通过（搜不到信息）:    XXX 家            │
   │  ❓ 不确定（信息模糊）:      XXX 家            │
   │                                              │
   │ 示例验证通过企业:                             │
   │   - 一汽解放汽车有限公司 → 官网/天眼查         │
   │   - 吉林银行股份有限公司  → 官网/新闻          │
   │                                              │
   │ 示例未通过企业:                               │
   │   - XX科技工作室 → 无任何公开信息             │
   │                                              │
   │ 是否放行验证通过的企业进入画像队列？            │
   │ (全部放行 / 仅放行通过的 / 查看明细)           │
   └─────────────────────────────────────────────┘
   ```

---

## Input

- `data/.bole_context.json` — title_keywords / search_keywords / city / province
- `data/enterprise/processed/enterprise_cleaned.csv` — deduped enterprise list
- `data/position/processed/position_scored.csv` — scored job data for job quality computation

## Output

- `data/enterprise/.industry_keywords.json` — industry signal keywords (from Step 0)
- `data/enterprise/processed/enterprise_scored.csv` — scored + priority-ranked

### enterprise_scored.csv 字段说明

| 字段 | 说明 |
|------|------|
| `company_name` | 企业名称 |
| `company_name_raw` | 原始企业名称 |
| `enterprise_categories` | 资质类别（分号分隔） |
| `level` | 层级：A(双在册) / B(仅岗位) / C(仅资质) |
| `inferred_industry` | 从企业名称推断的行业 |
| `qual_score` | 资质等级分（0-5） |
| `job_quality` | 岗位质量综合分（0-5） |
| `industry_fit_score` | 行业匹配分（0-5） |
| `industry_fit_detail` | 行业匹配详情（命中的关键词） |
| `avg_job_score` | 该企业岗位平均总分 |
| `job_count` | 岗位数量 |
| `total_score` | 总分（0-50，按层级公式计算） |
| `priority` | high / medium / low |
| `source_list` | 数据来源 |
