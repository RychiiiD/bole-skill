---
name: bole-score
description: 五维评分 + 标签 + 排序
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

Score, tag, and rank job listings.

---

## ★ 强制自检协议（必须遵守，违反即违规）

### 评分前自检清单

运行评分脚本前，**必须**执行：

```yaml
1. 输入文件验证:
   - data/position/processed/deduped.csv 是否存在？
   - 文件是否非空？
2. 必填列检查:
   - title/company/salary/experience/education 等字段是否存在？
   - 如有缺失列 → 记录并评估是否影响评分
3. 权重配置确认:
   - 默认权重来自 config.yaml scoring.weights
   - **如果用户表达了偏好** → 检查 data/.bole_context.json 中的 preferences.weights
   - 用户偏好会自动覆盖默认权重，优先级: 用户偏好 > config.yaml > 代码硬编码
4. 薪资档位确认:
   - 默认来自 config.yaml scoring.salary_tiers（8 级，1-8 分）
   - 用户可通过偏好自定义 salary_tiers
```

### 评分后自检清单

评分完成后，**必须**执行：

```yaml
1. 输出文件验证:
   - data/position/processed/position_scored.csv 是否存在？
   - 文件是否非空？
2. 必填列完整性检查:
   - 以下评分相关列是否都存在？
     ├─ total_score（数值，0-150）
     ├─ tag_relevance（Y/N）
     ├─ tag_target_company（Y/N）
     └─ tag_need_deep（Y/N）
3. 分数范围验证:
   - total_score 是否都在 0-150 范围内？（含企业加分可达 140+）
   - 如有超出 → 检查评分逻辑是否有 bug
   - 平均分是否合理？（过低说明配置可能有误）
4. 标签分布验证:
   - tag_relevance=Y 的比例是否与预期一致？
   - tag_target_company=Y 是否有值？（需 config.yaml 配置 target_companies）
   - tag_need_deep=Y 的比例是否合理？
5. 异常值检查:
   - 列出总分前 3 和后 3 的条目，评估是否合理
   - 如发现明显不合理（如无关岗位分数很高）→ 检查评分逻辑
6. 行数一致性:
   - 如 config.yaml 配置了 relevance_filter.min_score → position_scored.csv 行数 ≤ deduped.csv（过滤减少）
   - 如未配置 → position_scored.csv 行数应与 deduped.csv 一致（评分不增减行）
   - 不一致 → 排查评分脚本
7. 用户确认:
   - 展示 top 15 给用户看，确认评分是否符合预期
   - 用户不满意 → 调整权重/关键词重新评分
   - 用户确认 → 继续
```

**自动化校验不能替代用户确认。** pipeline.py verify 只检查文件完整性和格式正确性。评分是否合理（权重是否符合个人偏好）由用户说了算。

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 不检查输出文件列完整性 | 必须逐列确认 |
| 看到分数异常不排查 | 必须检查评分逻辑 |
| 跳过 tag 列验证 | 必须确认标签列存在且值有效 |
| 遇到偏离原始流程的决定（跳过步骤、缩减检查量、用部分结果替代完整结果、流程未明确规定时的替代方案） | 必须暂停并询问用户，不得自行决定 |

## 企业名称过滤（个体工商户/小企业）

评分阶段通过 `company_filter` 配置过滤明显的低质企业：

### exclude_patterns（公司名关键词屏蔽）

配置在 `config.yaml → scoring.company_filter.exclude_patterns`，公司名包含任一关键词即筛除：

```
- "某"         # 匿名企业
- "商贸店"      # 个体工商户
- "食品经..."   # 名称截断的小店
- "美容..."
- "汽车..."
- "红圆理疗馆"
- "..."
```

从 enrich-fill 流程已填充数据中观察到的常见个体户名称模式已预配置，可根据实际批次数据持续补充。

### min_chinese_chars（最少中文字符数）

公司名中文字符数低于此值视为个体户/低质企业筛除。例如：
- `灵柏`（2字）→ 筛除
- `汇森`（2字）→ 筛除
- `牛霸霸`（3字）→ 保留（可能为品牌名）

配置位置：`config.yaml → scoring.company_filter.min_chinese_chars`，默认 `3`。

## Dimensions

| Dimension | Default Weight | Description |
|-----------|:-------------:|-------------|
| Salary    | 10            | 8-tier grading, max 8pts (highest tier ≥20k) |
| Experience| 4             | 3-5yr best=5, intern lowest=2 |
| Education | 3             | Bachelor=5,大专=4 |
| Relevance | 5             | Job keyword match (high=5, mid=4, else 3) |

**权重优先级（高到低）：**
1. 用户偏好（`.bole_context.json.preferences.weights`）— 由 AI 从 NL 对话提取
2. config.yaml `scoring.weights` — 算法默认值
3. score.py 代码硬编码 — 最终 fallback

用户偏好可覆盖 weights、salary_tiers、experience、education 四个维度。
未覆盖的部分仍使用 config.yaml 默认值。

Tags: `tag_relevance`, `tag_target_company`, `tag_need_deep`

## Steps

1. Run `python scripts/job/score.py --config config.yaml`
2. Read `data/position/processed/position_scored.csv` and print top 10 results
3. 执行上述评分后自检清单，确认分数范围、标签分布、异常值
