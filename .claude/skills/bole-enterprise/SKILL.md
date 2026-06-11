---
name: bole-enterprise
description: 企业信息管线编排：发现来源 → 采集资质名单 → 清洗去重 → 评分 → 格式化输出（步骤由 pipeline.py 强制校验顺序）
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

Run the complete enterprise pipeline: discover government qualification sources,
collect enterprise lists, clean/dedup, and score by qualification level.

## Pipeline Overview

```
enterprise-sources → enterprise-collect → enterprise-clean → enterprise-score → enterprise-format
```

企业管线仅产出企业资质数据（不含福利/规模/官网等画像信息）。
画像信息由富化管线的 enrich-fill 步骤统一全网检索补充。

---

## ★ 强制自检协议（必须遵守，违反即违规）

### 步骤执行前置自检清单

每个步骤执行前，**必须**执行：

```yaml
step_id: {当前步骤}
前置条件:
  - pipeline.py check 是否通过？→ [是/否]（否→停止）
  - 上一步骤的输出文件是否存在？→ [是/否]（否→停止）
  - data/enterprise/ 相关目录是否存在？
当前步骤说明:
  - 如果 real 模式 + Step 2（collect）: 清理残留 `rm -rf data/enterprise/` 是否已执行？
```

### 步骤执行后置自检清单

每个步骤完成后，**必须**执行：

```yaml
step_id: {已完成的步骤}
输出验证:
  - pipeline.py complete 是否成功？→ [是/否]
  - verify 是否通过？→ [是/否]（否→修复后重试）
  - 输出文件路径: {确认文件存在且非空}
Step 1（sources）: .sources.json 是否写入 enterprise 相关来源？
Step 2（collect）: qualification_lists/ 目录下是否有 CSV 文件？
Step 3（clean）: enterprise_cleaned.csv 是否有数据？
Step 4（score）: enterprise_scored.csv 的 priority 分布是否合理？
Step 5（format）: enterprise_basic.csv 是否存在且非空？
```

### 全流程完成验证

所有步骤完成后，**必须**执行：

```yaml
1. 最终文件验证:
   - data/enterprise/output/enterprise_basic.csv 是否存在？
   - 文件是否非空（至少 1 条企业）？
   - data/enterprise/output/enterprise_report.md 是否存在？
2. 数据完整性:
   - 企业总数: {count}
   - 资质覆盖类型: {列举所有资质类型}
3. 产出说明:
   - 企业管线仅产出资质数据
   - 画像步骤已移除，职能由 enrich-fill 统一承担
```

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 清理 data/enterprise/ 前不确认 | rm -rf 前确认已备份或确认可丢弃 |
| 遇到偏离原始流程的决定（跳过来源/步骤、缩减采集量、用部分结果替代完整结果、流程未明确规定时的替代方案） | 必须暂停并询问用户，不得自行决定 |

## Steps

每个步骤必须严格按照以下流程执行：

1. **PRE-CHECK** — 运行 `python scripts/pipeline/pipeline.py check enterprise <step_id>`，确认前置步骤已完成
   - 如果命令返回非 0 退出码，必须停止执行
2. **执行步骤内容**
3. **POST-COMPLETE** — 运行 `python scripts/pipeline/pipeline.py complete enterprise <step_id>` 标记完成

---

### Step 0 — 意图确认（必须执行，不得跳过）
**step_id**: `confirm_mode`

企业管线同样纯自然语言交互。从用户消息中提取城市名，
提取规则同岗位管线 Step 0：城市没提则问用户，不得猜默认值。

```bash
python scripts/pipeline/pipeline.py check enterprise confirm_mode || exit 1
```

打印确认信息（城市 + 企业资质采集范围），等待用户确认。

```bash
python scripts/pipeline/pipeline.py complete enterprise confirm_mode
```

---

### Step 1 — Enterprise Sources
**step_id**: `discover_sources`

```bash
python scripts/pipeline/pipeline.py check enterprise discover_sources || exit 1
```

Read `skills/bole-enterprise-sources/SKILL.md` and follow its instructions.
- WebSearch 发现目标城市政府资质公示网站
- 确认哪些资质类型在城市存在可用数据源
- 输出来源发现报告

---

### Step 2 — Collect
**step_id**: `collect`

```bash
python scripts/pipeline/pipeline.py check enterprise collect || exit 1
```

#### ★ 采集前合规检查（必须执行，不可跳过）

开始采集前必须先执行以下检查：

```bash
# 1. 合规确认
python scripts/pipeline/pipeline.py compliance-check
# exit(1) → 展示合规条款给用户，确认后运行 compliance-accept 再继续

# 2. 来源 robots.txt 检测（每个新来源首次采集前执行）
python scripts/pipeline/pipeline.py robots-check <source_url>
# exit(1) → Disallow 匹配，用户确认方可继续
```

Read `skills/bole-enterprise-collect/SKILL.md` and follow its instructions.
- 使用 MCP 浏览器访问政府公示页面
- 采集企业资质名单（PDF/Excel/网页表格）
- 文件保存到 `data/enterprise/raw/qualification_lists/`

---

### Step 3 — Clean & Dedup
**step_id**: `clean`

```bash
python scripts/pipeline/pipeline.py check enterprise clean || exit 1
```

Read `skills/bole-enterprise-clean/SKILL.md` and follow its instructions.

```bash
python scripts/enterprise/enterprise_clean.py --config config.yaml
```

- 输入: `data/enterprise/raw/qualification_lists/` 下的所有采集文件
- 企业名称标准化（去括号、全角转半角、去后缀）
- 多来源去重合并
- 输出: `data/enterprise/processed/enterprise_cleaned.csv`

```bash
python scripts/pipeline/pipeline.py complete enterprise clean
```

---

### Step 4 — Score
**step_id**: `score`

```bash
python scripts/pipeline/pipeline.py check enterprise score || exit 1
```

Read `skills/bole-enterprise-score/SKILL.md` and follow its instructions.

```bash
python scripts/enterprise/enterprise_score.py --config config.yaml
```

- 按岗位覆盖 + 资质等级评分
- 三层级（A/B/C）+ 行业匹配
- 输出: `data/enterprise/processed/enterprise_scored.csv`

```bash
python scripts/pipeline/pipeline.py complete enterprise score
```

---

### Step 5 — Format
**step_id**: `format`

```bash
python scripts/pipeline/pipeline.py check enterprise format || exit 1
```

Read `skills/bole-enterprise-format/SKILL.md` and follow its instructions.

```bash
python scripts/enterprise/enterprise_format.py --config config.yaml
```

- 读取: `data/enterprise/processed/enterprise_scored.csv`
- 过滤技术参数字段（保留公司名/资质/层级/行业/总分/优先级等知识库查询字段）
- 输出: `data/enterprise/output/enterprise_basic.csv`（UTF-8 无 BOM，知识库导入用）
- 输出: `data/enterprise/output/enterprise_basic_bom.csv`（UTF-8 有 BOM，Excel 预览用）
- 输出: `data/enterprise/output/enterprise_report.md`（数据报告）

```bash
python scripts/pipeline/pipeline.py complete enterprise format
```

---
### Step 6 — 管线衔接（富化匹配）
**step_id**: `handoff`

```bash
python scripts/pipeline/pipeline.py check enterprise handoff || exit 1
```

展示企业管线完成状态，**必须**询问用户是否继续富化匹配管线：

> **角色约束**：此步骤是企业管线到富化管线的唯一衔接点。AI 不得跳过询问、不得代替用户做决定。用户不确认 → verify 不通过 → 管线卡死。

```
========================================
  企业资质管线 — 采集完成
========================================
  目标城市: {city}
  企业总数: {enterprise_count} 家
  资质覆盖: {qualification_types}
  优先级 A: {priority_a} 家, B: {priority_b} 家, C: {priority_c} 家

  接下来是否继续富化匹配？
  富化步骤将把企业资质数据与岗位数据进行交叉匹配，
  为评分的"企业质量加分"维度提供数据支持。

  输入选项：
  - 继续 / 是 / 好 → 开始富化匹配管线
  - 跳过 / 不用 → 跳过，直接结束
========================================
```

根据用户回应写 `.bole_context.json` 的 handoff 字段（**AI 不得在用户回应前写入**）：

- 用户确认继续 → `"approved"`
- 用户跳过 → `"skipped"`

```bash
python -c "
import json
with open('data/.bole_context.json', 'r') as f:
    ctx = json.load(f)
ctx['handoff'] = ctx.get('handoff', {})
ctx['handoff']['to_enrich'] = 'approved'  # 或 'skipped'
ctx['handoff']['asked_at'] = '$(date -Iseconds)'
with open('data/.bole_context.json', 'w') as f:
    json.dump(ctx, f, ensure_ascii=False, indent=2)
"
```

标记完成：

```bash
python scripts/pipeline/pipeline.py complete enterprise handoff
```

**后续流程**：
- 用户确认继续 → 启动富化匹配管线（通过 `/bole-enrich`，城市自动继承当前配置）
- 用户跳过 → 全部完成，展示最终摘要

---

## Output

| 文件 | 说明 |
|------|------|
| `data/enterprise/processed/enterprise_cleaned.csv` | 去重清洗后的企业名单 |
| `data/enterprise/processed/enterprise_scored.csv` | 评分排序后的企业名单（含 priority） |
| `data/enterprise/output/enterprise_basic.csv` | 格式化输出—知识库导入（过滤技术参数，保留查询字段） |
| `data/enterprise/output/enterprise_basic_bom.csv` | 格式化输出—Excel 预览版 |
| `data/enterprise/output/enterprise_report.md` | 企业数据报告 |

企业数据不包含福利/规模/官网等画像信息，这些由 enrich-fill 在富化管线中统一补充。

## 与富化管线的连接

```
企业管线产出                     富化管线
enterprise_scored.csv  ──→ enrich.py（三段式公司名匹配 + 双侧评分）
                               │
                          matched（58条）→ final_score 含企业加分
                          unmatched（340条）→ enrich-fill（全网检索补充）
```

企业画像信息不再由企业管线负责，统一由富化管线的 enrich-fill 步骤通过 WebSearch 全网检索补充。
