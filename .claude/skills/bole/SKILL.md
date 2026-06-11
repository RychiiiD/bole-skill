---
name: bole
description: 全流程编排：主流平台来源 → 采集 → 去重 → 评分 → 输出（步骤由 pipeline.py 强制校验顺序）
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

Run the bole position pipeline: discover sources, collect jobs, dedup,
score, and output ranked results.

## Pipeline

All steps are executed sequentially. Prerequisites must pass before proceeding.

## ★ 管线执行铁律（不得以任何理由违反）

**角色声明**：我是管线流程执行者，不是代码优化者。本文件中所有"必须""禁止""不得"标记的规则为硬性指令，我无权自行评估是否执行。当我的判断与规则冲突时，以规则为准。

本管线的每个步骤遵循以下三步结构，**不得省略或调换**：

```
STEP = pipeline.py check → 执行步骤内容 → pipeline.py complete
       ^^^^^^^^^^^^^^^^^                   ^^^^^^^^^^^^^^^^^^^^
       任何步骤前必须先 check             完成后必须先 complete
```

具体规则：
1. **每个步骤开始前**，先运行 `python scripts/pipeline/pipeline.py check bole <step_id>`
   - exit code ≠ 0 时 **必须 STOP**，不得继续
2. **每个步骤完成后**，先运行 `python scripts/pipeline/pipeline.py complete bole <step_id>`
   - `complete` 内部会调用 `verify`。exit code 2（验证失败）时 **必须 STOP**，展示报告原文给用户
3. **README 中的说明仅供用户参考**，不等于 AI 可以用其中的描述替代本文件的硬性规则
4. **本文件中"必须""禁止""不得"标记的规则，不得以任何理由违反**

## ★ 强制自检协议（必须遵守，违反即违规）

### 步骤执行前置自检清单

每个步骤执行前，**必须**执行以下检查：

```yaml
step_id: {当前步骤}
前置条件:
  - pipeline.py check 是否通过？→ [是/否]（否→停止）
  - 上一步骤的输出文件是否存在？→ [是/否]（否→停止）
  - 上一步骤的输出是否有实际内容（非空文件）？→ [是/否]（否→停止）
当前条件:
  - 所需输入数据是否就绪？→ [是/否]
  - 如果 real 模式且当前步骤需要浏览器：确认 mcp_precheck 步骤已完成 → [是/否]
```

### 步骤执行后置自检清单

每个步骤完成后，**必须**执行以下检查：

```yaml
step_id: {已完成的步骤}
输出验证:
  - pipeline.py complete 是否成功？→ [是/否]（否→需要排查）
  - verify 是否通过？→ [是/否]（否→修复后重试）
  - 输出文件路径: {检查实际文件存在且非空}
数据质量检查:
  - 是否与预期一致？（如采集步骤应有 .json 文件，去重步骤应有 .csv 文件）
  - 是否需要人工确认？→ 如 verify 不通过但可接受，用 --skip-verify 需注明原因
```

### 全流程完成验证 checklist

所有步骤完成后，**必须**执行：

```yaml
1. 最终输出文件是否存在？
   - data/position/output/position_basic.csv
   - data/position/output/position_report.md
2. position_basic.csv 是否有数据行（不止表头）？
3. 各步骤产出是否一致？
   - 最终行数 ≤ 采集源文件总行数（去重只会减少不会增加）
   - 最终行数 ≥ 评分文件行数（格式化和评分不会减少数据）
4. 如有异常→输出到报告中标注
```

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 跳过 pipeline.py check 直接执行步骤 | 必须先 check，不通过则停止 |
| 某步骤失败后不排查就跳到下一步 | 必须排查修复或标记跳过原因 |
| real 模式下 MCP 不可用仍尝试采集 | 停止并提示用户重启会话 |
| 不读取子 SKILL 文件直接执行 | 每个步骤必须先读对应的 SKILL.md |
| 遇到偏离原始流程的决定（跳过来源/关键词/步骤、缩减采集量、用部分结果替代完整结果、流程未明确规定时的替代方案） | 必须暂停并询问用户，不得自行决定 |
| **pipeline.py verify 失败（exit code 2）后自行重试/补采/跳过** | **必须 STOP**，将校验报告原文展示给用户，等待用户决策 |
| **未获用户确认就使用 --skip-verify** | 必须先向用户展示 verify 失败原因，获得明确确认后才可用 --skip-verify |
| **遇到登录/验证码未写入 data/.auth_blocked 就继续采集** | 必须先截图保存证据，再写入 data/.auth_blocked 阻塞管道，然后暂停提示用户 |

## Steps

每个步骤必须严格按照以下流程执行：

1. **PRE-CHECK** — 运行 `python scripts/pipeline/pipeline.py check bole <step_id>`，确认前置步骤已完成
   - 如果命令返回非 0 退出码（显示 "BLOCKED"），必须停止执行并告诉用户需要先完成哪个步骤
2. **执行步骤内容** — 按步骤说明操作
3. **POST-COMPLETE** — 运行 `python scripts/pipeline/pipeline.py complete bole <step_id>` 标记完成

---

### Step 0 — 意图提取与确认（必须执行，不得跳过）
**step_id**: `confirm_mode`

**重要：伯乐是纯自然语言交互，不依赖任何配置文件。城市、岗位、搜索关键词全部从用户的对话中提取。**

```bash
python scripts/pipeline/pipeline.py check bole confirm_mode || exit 1
```

**1. 从用户消息中提取意图**

Read the user's last message and extract:
- `city` — 城市名称（如 北京、上海、深圳、长春）
- `title_keywords` — 岗位名称（如 产品经理、AI PM、前端开发）
- `search_keywords` — 搜索关键词。默认从 title_keywords 派生 2 个（原词 + 常见变体），不询问用户选择模式。用户主动追加关键词时直接合并。
- `preferences` — (可选) 用户对评分维度的偏好

提取规则：
- 如果用户提到了城市 → 提取城市名（以用户最新消息为准，不继承旧 context 的城市/岗位）
- 如果用户提到了岗位 → 提取岗位标题（同上，以当前对话为准，不合并旧数据）
- 如果用户主动提到了关键词（如"大模型相关"、"AI方向"）→ 合并到 search_keywords，不受默认 2 个限制
- 如果城市没提 → **必须问用户**，不得猜默认值
- 如果岗位没提 → **必须问用户**，不得猜默认值
- 如果用户表达了偏好 → 提取偏好（见下方推理规则）；如果没表达 → 保留旧 preferences（如有），不主动询问
- **新旧城市/岗位切换规则**：用户说新城市/新岗位时，完全以当前消息为准重新提取。如果用户还提到了偏好，旧偏好被覆盖；没提偏好则保留旧偏好。

**偏好推理规则（从自然语言映射到权重）：**

| 用户表述（示例） | 映射结果 |
|----------------|---------|
| "薪资最重要"、"工资高的"、"钱多" | weights.salary → 15-20 |
| "薪资无所谓"、"工资不限" | weights.salary → 3-5 |
| "要资深/经验丰富的"、"经验要求高" | weights.experience → 6-8 |
| "不限经验"、"经验无所谓" | weights.experience → 1-2 |
| "学历重要"、"要本科以上" | weights.education → 5-6 |
| "学历不限"、"学历无所谓" | weights.education → 1-2 |
| "相关度最重要"、"只要AI岗" | weights.relevance → 8-10 |
| "什么岗位都行"、"不限岗位" | weights.relevance → 2-3 |

更多组合同理。用户话说得模糊时，用合理的默认值（例如"薪资最重要"→ salary=18，其他不变）。

如果用户完全没有提到偏好 → 直接跳过，不询问。

**2. 写上下文文件**

提取完成后，将提取结果写入 `data/.bole_context.json`，供后续流程使用：

```json
{
  "city": "提取的城市",
  "title_keywords": ["提取的岗位"],
  "search_keywords": ["{title_keywords[0]}", "{常见变体}"],  // 默认 2 个，不询问用户
  "province": "城市所在省份（自动推断）",
  "region": "城市所在区域（自动推断）",
  "preferences": {
    "weights": {
      "salary": 10,
      "experience": 4,
      "education": 3,
      "relevance": 5
    }
  }
}
```

注：如果用户没有表达偏好，preferences 字段可以省略或留空。score.py 会使用 config.yaml 默认值。

**3. 展示确认并等待用户确认**

打印确认信息：

```
========================================
  伯乐 — 搜索确认
========================================
  城市: {city}
  岗位: {title_keywords[0]}
  搜索: {search_keywords}
  偏好: 薪资×10 经验×4 学历×3 相关度×5 (默认)
  (或: 薪资×18 经验×4 学历×3 相关度×5 — 用户自定义)
========================================
```

Ask the user: "以上信息正确吗？确认后开始采集。"

如果用户说不对 → 追问补充，更新 `.bole_context.json`。

如果用户回答"确认"/"正确"/"可以" → 在 `.bole_context.json` 中添加 `_meta` 确认标记：

```bash
# 写入确认标记（pipeline.py verify 会检查此标记）
python -c "
import json
with open('data/.bole_context.json', 'r') as f:
    ctx = json.load(f)
ctx['_meta'] = ctx.get('_meta', {})
ctx['_meta']['confirmed_by_user'] = True
ctx['_meta']['confirmed_at'] = '$(date -Iseconds)'
with open('data/.bole_context.json', 'w') as f:
    json.dump(ctx, f, ensure_ascii=False, indent=2)
"
```

**AI 不得在用户确认前设置 `_meta.confirmed_by_user`。** 此标记是 pipeline.py verify 的必要条件，缺失时 verify 不通过。

**4. 旧数据处理（如有）**

检查 `data/position/output/` 下是否有之前的产出文件（如 `position_basic.csv`）。
如果有，告知用户旧数据情况并询问处理方式：

```
检测到旧数据: {旧城市} {旧岗位} (共 N 条)
这次怎么处理？
  - 覆盖：删除旧数据，全新采集（默认）
  - 备份：备份旧数据后再跑新的
  - 跳过：不跑采集流程，直接基于旧数据出结果
```

根据用户选择，在 `.bole_context.json` 中记录 `output_strategy` 字段：
- `"overwrite"`（默认）— 不保留旧数据
- `"backup"` — 采集前先备份旧 data/position/ 目录
- `"skip_collect"` — 跳过采集/去重，直接基于已有数据重新评分+输出

如果用户说"覆盖"或没提 → output_strategy = "overwrite"
如果用户说"备份" → output_strategy = "backup"
如果用户说"上次的数据还能用，直接给我评分看看" → output_strategy = "skip_collect"

**重要：如果用户选了 skip_collect，必须先检查新旧城市/岗位是否匹配。**
对比 `.bole_context.json` 中旧的 city/title_keywords 和刚刚提取的新的值：
- 如果城市和岗位都没变 → 可以 skip_collect
- 如果城市或岗位变了 → **警告用户"旧数据和本次需求不匹配，跳过采集会导致结果基于错误数据"**，让用户重新选择（覆盖/备份/取消）

注：output_strategy 只影响当前运行，不会持久化到下一次。

**用户确认后**，标记步骤完成：
```bash
python scripts/pipeline/pipeline.py complete bole confirm_mode
```

---
### Step 0.5 — MCP 预检（★ 运行环境客观判定点）
**step_id**: `mcp_precheck`

```bash
python scripts/pipeline/pipeline.py check bole mcp_precheck || exit 1
```

**MCP 必须经过实际调用验证，不可跳过。此步骤是判定 MCP 可用性的唯一标准，AI 不得在此之前根据任何迹象（IDE 工具可用性、界面特征等）自行推断环境类型。**

1. **直接调用 `browser_snapshot` 验证** — 不要先分析环境，测了再说
2. 如果返回正常截图 → 执行：
   ```bash
   echo '{"verified_at": "'$(date -Iseconds)'"}' > data/.mcp_verified
   ```
3. 如果 MCP 不可用（超时/报错）→ **必须 STOP**，提示用户重启会话
   - 不可用常见原因：会话续存后 MCP 断连、需重启 Claude Code、`.mcp.json` 未正确配置
   - 遇到此情况，打印提示后终止管线，不可自行跳过或降级
4. 标记完成：
   ```bash
   python scripts/pipeline/pipeline.py complete bole mcp_precheck
   ```

**退出码含义：**
- `exit(0)` → MCP 可用，继续
- `exit(1)` → check 未通过（前置步骤未完成）
- **`exit(2)` → MCP 未验证（标记文件缺失），AI 必须 STOP 并提示用户**

---
### 主流平台来源（固定 5 平台模板）
**step_id**: `mainstream_sources`

```bash
python scripts/pipeline/pipeline.py check bole mainstream_sources || exit 1
```

直接将 5 个固定主流平台写入 `data/position/.sources.json`：

| 平台 | id | URL 模板 |
|------|:--:|---------|
| 猎聘 | `liepin` | `https://www.liepin.com/zhaopin/?key={keyword}` |
| 前程无忧 | `51job` | `https://we.51job.com/pc/search?keyword={keyword}` |
| 智联招聘 | `zhaopin` | `https://www.zhaopin.com/sou/?kw={keyword}` |
| 拉勾 | `lagou` | `https://www.lagou.com/jobs/list_{keyword}` |
| **BOSS直聘** | `boss` | `https://www.zhipin.com/web/geek/job?query={keyword}` |

所有平台 `pipeline=job`、`tech_type=searchable`、`enabled=true`，BOSS 放最后采集。

```bash
python scripts/pipeline/pipeline.py complete bole mainstream_sources
```

---
### Step 2 — Collect（★ 严禁跳过子 SKILL 自行采集）
**step_id**: `collect`

```bash
python scripts/pipeline/pipeline.py check bole collect || exit 1
```

**★ 所有来源必须严格按 `skills/bole-collect/SKILL.md` 中规定的平台方案执行。AI 不得自行猜测 API 端点、请求格式或提取方式。每个来源开始采集前，必须先读对应章节。**

**★ 补采隔离：用户追加关键词时，不得在当前会话中直接采集。必须使用 Agent 工具创建子 Agent 执行，协议见 `skills/bole-collect/SKILL.md` 补采协议章节。子 Agent 返回报告后，主 AI 通过 keyword-verify 验证完整性。**

Read `skills/bole-collect/SKILL.md` and follow its instructions.

**采集执行**:

1. 读取 `.bole_context.json` 中的 `output_strategy`：
   - `"skip_collect"` → **跳过采集步骤**，告诉用户"已跳过采集，直接使用旧数据"。然后执行：
     ```bash
     python scripts/pipeline/pipeline.py complete bole collect --skip --skip-verify --skip-verify-ack
     ```
     （注意：必须同时使用 `--skip-verify --skip-verify-ack`，因为旧数据的采集文件与新 sources 不匹配，verify 必然失败）
   - `"backup"` → 先备份旧目录：`cp -r data/position/ data/position_backup_$(date +%Y%m%d_%H%M%S)/`，再清理 `rm -rf data/position/`
   - `"overwrite"`（默认）→ 直接清理：`rm -rf data/position/`
2. 读取 `data/position/.sources.json`（Step 1 生成）获取采集来源列表
   - 筛选 `pipeline=job` 且 `enabled=true` 的来源
   - 按 `tech_type` 分类：searchable（需关键词遍历+翻页）/ notice_list（无关键词，列表翻页+详情提取）
   - `company_list` 类型不在此管线处理
3. 使用 MCP Playwright 工具逐来源采集
4. 采集结果保存到 `data/position/raw/`
   - searchable 类型文件命名：`{id}_{keyword}_page{N}.json`
   - notice_list 类型文件命名：`{id}_all_page{N}.json`
   - 空结果必须在 `note` 字段注明原因（`no_results` / `login_blocked` / `redirect_to_login`）

**重要 — exit code 含义：**
- `exit(0)` → 校验通过，继续下一步
- **`exit(2)` → 校验失败（覆盖率不足/JSON 异常），AI 必须 STOP！** 不得自行重试、不得 --skip-verify、不得进入下一步。将校验报告原文展示给用户，等待用户决策（重试缺失组合 / 接受现状用 --skip-verify / 终止管线）。

---

### Step 3 — Generate Relevance Keywords
**step_id**: `relevance_keywords`

```bash
python scripts/pipeline/pipeline.py check bole relevance_keywords || exit 1
```

Interactively determine scoring relevance keywords:
- Read `data/.bole_context.json` → `title_keywords` and `search_keywords`
- Based on these, suggest high (score 5) and mid (score 4) keywords
- Display to user and ask if they want to adjust
- On user confirmation, save to `data/position/.relevance_keywords.json` **并添加 `_meta` 确认标记**：
  ```json
  {
    "keywords": [{"keyword": "AI产品经理", "level": "high"}, ...],
    "_meta": {"confirmed_by_user": true, "confirmed_at": "2026-06-05T10:00:00+08:00"}
  }
  ```
  AI 不得在用户确认前设置此标记。pipeline.py verify 会校验。

After completion:

```bash
python scripts/pipeline/pipeline.py complete bole relevance_keywords
```

---

### Step 4 — Dedup
**step_id**: `dedup`

```bash
python scripts/pipeline/pipeline.py check bole dedup || exit 1
```

Read `skills/bole-dedup/SKILL.md` and follow its instructions.

**Step 4a — Merge JSON to CSV**（采集结果存为 JSON，需先合并为 CSV 供去重脚本读取）:

```bash
python scripts/job/merge_raw.py
```

**Step 4b — Dedup**:
- 多来源合并，按 (company_name, job_title) 去重
- 输出: `data/position/processed/deduped.csv`
- Run:

```bash
python scripts/job/dedup.py --config config.yaml
```

After completion:

```bash
python scripts/pipeline/pipeline.py complete bole dedup
```

---

### Step 5 — Score & 用户确认
**step_id**: `score`

```bash
python scripts/pipeline/pipeline.py check bole score || exit 1
```

Read `skills/bole-score/SKILL.md` and follow its instructions.
- 五维评分（薪资/经验/学历/相关度）
- 标签: tag_relevance, tag_target_company, tag_need_deep
- 相关度过滤：如 config.yaml 配置了 relevance_filter.min_score，低于阈值的岗位会被筛除
- 输出: `data/position/processed/position_scored.csv`
- Run:

```bash
python scripts/job/score.py --config config.yaml
```

**评分确认环节（用户参与验证）:**

评分完成后，**必须**展示结果给用户确认：

1. 打印 top 15 结果（评分、岗位、公司、薪资）：
```
  Top 15:
  [106] AI产品经理           | 字节跳动           | 25k-42k(月均)
  [ 98] AI产品经理           | 百度               | 22k-38k(月均)
  ...
```

2. 询问用户：
```
  评分结果是否符合你的预期？
  - 如果满意 → 继续
  - 如果不满意 → 告诉我哪里不对，我调整权重或关键词重新评分
```

3. 如果用户不满意：
   - 根据反馈更新 `.bole_context.json` 中的 preferences.weights
   - 或更新 `data/position/.relevance_keywords.json`
   - 重新运行 `python scripts/job/score.py --config config.yaml`
   - 再次展示 top 15，循环直到用户确认

4. 用户确认后标记完成：

```bash
python scripts/pipeline/pipeline.py complete bole score
```

**评分确认交互示例（真实流程中的样子）：**

```
系统:  评分完成！共 42 条岗位。

  Top 15:
  [106] AI产品经理           | 字节跳动           | 25k-42k(月均)
  [ 98] AI产品经理           | 百度               | 22k-38k(月均)
  [ 92] AI产品经理           | 阿里巴巴          | 25k-42k(月均)
  [ 88] 产品经理             | 科大讯飞          | 20k-35k(月均)
  [ 75] 产品经理             | 中软国际          | 15k-25k(月均)
  [ 60] 产品助理             | 某科技公司        | 8k-12k(月均)
  ...

  评分结果是否符合你的预期？

场景 A — 用户满意:
  用户: "可以，挺准的"
  系统: → 继续到下一步

场景 B — 用户觉得某个不应排那么高:
  用户: "中软国际这个不对，我不想去外包"
  系统: 更新 exclude_patterns 加入 "中软国际" → 重新评分 → 展示新的 Top 15

场景 C — 用户觉得权重不对:
  用户: "大厂分太低了，我比较看重公司"
  系统: "那我调高相关度权重？还是你想加一些目标公司关键词？"
  用户: "加几个目标公司吧，字节百度阿里腾讯"
  系统: 更新 config.yaml target_companies → 重新评分 → 展示新的 Top 15

场景 D — 用户有细微调整:
  用户: "整体还行，但第二个百度那个岗位跟我方向不太一样"
  系统: "可以把"百度"的那个岗位调低相关度，或者给你的关键词加一些限定。你想怎么调？"
```

说明：评分确认是用户参与的主观验证。和 `relevance_keywords` 步骤一样，
AI 先做初步处理（评分），用户看了结果后决定是否调整。
核心原则：**用户说好才是真的好。**

---

### Step 6 — Format
**step_id**: `format`

```bash
python scripts/pipeline/pipeline.py check bole format || exit 1
```

Read `skills/bole-format/SKILL.md` and follow its instructions.
- 输出 `data/position/output/position_basic.csv`（UTF-8 无 BOM）— 知识库导入优化版，过滤技术参数保留面向查询字段
- 此为基础岗位数据。如需补充企业资质/福利/规模等富化信息，后续可执行 `/bole-enterprise` + `/bole-enrich`
- Run:

```bash
python scripts/job/format.py --config config.yaml
```

After completion:

```bash
python scripts/pipeline/pipeline.py complete bole format
```

---

### Step 7 — Report
**step_id**: `report`

Generate comprehensive Markdown data report:

```bash
python scripts/pipeline/pipeline.py check bole report || exit 1
python scripts/job/report.py --config config.yaml
```

The report covers 7 sections:
1. **总览** — total jobs, companies, sources, avg/median/min/max scores
2. **评分分布** — tiered distribution + Top 10 jobs table
3. **来源分布** — per-platform breakdown with percentages
4. **薪资分析** — 8 salary bands, median/mean/max
5. **企业分析** — Top 10 by job count, industry distribution, company size, qualification coverage
6. **岗位要求** — education + experience distributions
7. **质量标签** — relevance, need_deep, quality flags

After completion:

```bash
python scripts/pipeline/pipeline.py complete bole report
```

---
### Step 8 — 管线衔接（企业资质）
**step_id**: `handoff`

```bash
python scripts/pipeline/pipeline.py check bole handoff || exit 1
```

展示岗位管线完成状态，**必须**询问用户是否继续企业资质采集：

> **角色约束**：此步骤是三条管线串联的唯一衔接点。AI 不得跳过询问、不得在用户未回应时代替用户做决定。用户不确认 → verify 不通过 → 管线卡死。

```
========================================
  岗位管线 — 采集完成
========================================
  {N} 个平台 × {M} 个关键词，共 {raw_count} 条原始数据
  去重合并后 {deduped_count} 条有效岗位
  评分过滤后 {scored_count} 条

  接下来是否继续企业资质采集？
  企业资质采集将从目标城市政府公示网站获取企业资质名单，
  与岗位数据交叉比对，为评分增加企业质量维度。

  输入选项：
  - 继续 / 是 / 好 → 开始企业资质管线
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
ctx['handoff']['to_enterprise'] = 'approved'  # 或 'skipped'
ctx['handoff']['asked_at'] = '$(date -Iseconds)'
with open('data/.bole_context.json', 'w') as f:
    json.dump(ctx, f, ensure_ascii=False, indent=2)
"
```

标记完成：

```bash
python scripts/pipeline/pipeline.py complete bole handoff
```

**后续流程**：
- 用户确认继续 → 启动企业资质管线（通过 `/bole-enterprise`，城市自动继承当前配置）
- 用户跳过 → 全部完成，展示最终摘要
