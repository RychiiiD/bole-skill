---
name: bole-enrich-fill
description: 逐批全网检索，补充岗位列表中的企业信息（福利/规模/官网等）
version: 1.0.0
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - WebSearch
---

逐批搜索岗位中的企业详细信息。与 enterprise 管线解耦，不写入 enterprise_cleaned.csv。

---

## 数据流向

```
position_final.csv（低质过滤后的岗位，企业信息空白的需补充）
       ↓
分批（每批 <=50 条岗位）→ WebSearch 逐企检索
       ↓
回填 → position_final.csv（同一文件，空字段被补充）
```

---

## ★ 强制自检协议

### 操作前

```yaml
1. position_final.csv 是否存在且非空？（需先完成 /bole-enrich）
2. enrich_fill 临时文件是否已清理（如跨轮次使用）？
3. 上一批是否已完成？(检查 position_final.csv 中已填充条数)
```

### 搜索前

```yaml
1. 批次中的公司名在 position_final.csv 中是否都能匹配？
   (运行 python scripts/enrich/enrich_fill.py --config config.yaml batch 后
    检查输出的公司列表有无异常)
```

### 保存前

```yaml
1. 填充结果 JSON 的字段名是否与 position_final.csv 表头一致？
   (enrich_fill.py save 会自动校验，不一致会拒绝写入并提示可用字段)
2. 将填充内容摘要展示给用户确认（不允许跳过此步骤）
```

### 禁止行为

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 编造搜索结果 | snippets 必须是 WebSearch 原始返回文本，不得润色/编造 |
| 编造 extract 中的 extracted 字段 | extracted 字段必须从 snippets 中提取，extract 命令会代码校验 |
| 跨批次批量搜索 | 每批最多 50 条岗位，逐企搜索 |
| 回填到 enterprise_cleaned.csv | 只更新 position_final.csv |
| 跳过企业直接标记空 | 至少尝试一次 WebSearch |
| 跳过证据 JSON 直接构建 result | 必须经过 extract 命令验证，不得手动写 .enrich_fill_result.json |
| 跳过用户预览确认直接保存 | 先将填充摘要展示给用户，获得确认后再 save |
| 匹配数为 0 时强制写入 | save 命令内置保护，匹配 0 条拒绝写入 |

---

## Steps

### Step 0 — 清理残留（可选）

如果需要确保当前批次从干净状态开始：

```bash
python scripts/enrich/enrich_fill.py --config config.yaml clean
```

删除 batch 临时文件、上次结果文件、证据文件、备份。

---

### Step 1 — 查看当前进度

```bash
python scripts/enrich/enrich_fill.py --config config.yaml status
```

展示当前已填充数和待填充数。

---

### Step 2 — 获取待填充批次（__先校验再搜索__）

```bash
python scripts/enrich/enrich_fill.py --config config.yaml batch
```

输出 <=50 条待填充的岗位到 `data/position/.enrich_fill_batch.json`，同时在终端展示本批涉及的企业名单和空字段。

**★ 必须先确认 batch 中的公司在 position_final.csv 中都能匹配**，否则重新生成批次：

```bash
python -c "import json; d=json.load(open('data/position/.enrich_fill_batch.json','r')); print(json.dumps(d['companies'], ensure_ascii=False))"
```

向用户展示批次信息并请求确认是否开始搜索。

---

### Step 3 — 逐企全网检索 + 保存证据

按 JSON 中的 `companies` 列表，逐家企业进行 **WebSearch** 检索（每企 2-3 次搜索）：

**搜索关键词模板：**
- `"{company_name} 招聘 福利待遇 薪资结构"`
- `"{company_name} 五险一金 年终奖 股权"`
- `"{company_name} 公司简介 法定代表人 规模 官网"`
- `"{company_name} 招聘 {keyword}"`（如有匹配岗位关键词）

**信息提取清单（越完善越好）：**

```
【福利制度】
  - 五险/六险一金/二金、是否入职缴纳、缴纳基数
  - 餐补、交通补、通讯补贴、住房补贴
  - 年终奖（月数）、项目奖金、分红机制
  - 股权激励/期权
  - 晋升机制、涨薪制度（每年几次调薪）
  - 弹性工作/打卡制度
  - 健身房、下午茶、年度体检、员工旅游

【企业信息】
  - 法定代表人
  - 公司规模（xx-xx 人）
  - 主营业务/行业
  - 官网 URL
  - 企业资质（专精特新/高新技术企业等）

【岗位信息】（与当前岗位匹配的）
```

**每家企业只搜索 2-3 次**，不要过度搜索。如某字段查不到，该字段标记为"目前未检索到该企业{字段名}详细信息"。
**注意**：不要对已匹配到企业资质（enterprise_categories 非空）的岗位重复搜索企业资质，仅补充其空字段。

---

### Step 4 — ★ 构建证据 JSON + 代码提取（打破 AI 编造闭环）

#### 4a. AI 构建搜索证据 JSON（保存原始搜索结果）

搜索完成后，将所有搜索原始文本片段和 AI 提取的结构化字段保存为证据文件：

```json
{
  "searched": [
    {
      "company_name": "xxx",
      "job_title": "xxx",
      "snippets": [
        "搜索结果原始文本1（包含福利待遇的段落...）",
        "搜索结果原始文本2（包含企业规模的段落...）"
      ],
      "extracted": {
        "benefits": "五险一金（入职缴纳，基数按实际工资）；年终奖（1-3个月）",
        "company_size": "100-499人",
        "official_website": "https://www.xxx.com",
        "enterprise_categories": "国家高新技术企业"
      }
    }
  ]
}
```

**关键规则：**
- `snippets` 必须是 WebSearch 返回的原始文本片段，**不得编造、不得润色**
- `extracted` 是 AI 从 snippets 中提取的结构化字段，**必须基于 snippets 内容**
- 每家企业一个 entry，条目覆盖 batch 中所有公司
- 保存到 `data/position/.enrich_fill_evidence.json`

#### 4b. 代码提取验证（enrich_fill.py extract）

```bash
python scripts/enrich/enrich_fill.py --config config.yaml extract --evidence data/position/.enrich_fill_evidence.json
```

extract 命令自动执行：
1. 对每个字段值检查**可疑模式**（纯数字、重复字符、无中文等）
2. 对每个字段值进行**内容词匹配**（字段中 ≥30% 的内容词必须在 snippets 中出现）
3. 验证失败的字段自动标记为 `"目前未检索到该企业{字段名}详细信息"`
4. 输出到 `data/position/.enrich_fill_result.json`

**验证逻辑（代码执行，AI 无法干预）：**
- 将字段值拆分为内容词（中文词 + 英文单词）
- 检查每个词是否出现在原始 snippets 文本中
- 覆盖率 ≥30% 即通过（允许小幅概括）
- 覆盖率 <30% 视为"编造"，自动丢弃

---

### Step 5 — ★ 用户预览确认（不可跳过）

读取填充结果，将 **本批将写入的内容摘要** 展示给用户：

```bash
python -c "import json; d=json.load(open('data/position/.enrich_fill_result.json','r')); [print(f'[{i}] {e[\"company_name\"]} → 福利:{e[\"benefits\"][:30]} 规模:{e[\"company_size\"][:20]}') for i,e in enumerate(d['filled'],1)]"
```

**必须获得用户明确确认后**，才能进入保存步骤。用户确认后，执行 Step 6。

---

### Step 6 — 保存到 position_final.csv

```bash
python scripts/enrich/enrich_fill.py --config config.yaml save --input data/position/.enrich_fill_result.json
```

save 命令内置保护机制：
- 自动校验字段名是否与 CSV 表头匹配，不匹配则拒绝写入
- 写入前自动备份，写入失败自动回滚
- 匹配数为 0 时拒绝写入，提示重新生成批次

---

### Step 7 — 确认进度并继续

```bash
python scripts/enrich/enrich_fill.py --config config.yaml status
```

展示更新后的进度。询问用户是否继续下一批。

---

### Step 8 — 确认全部完成

```bash
python scripts/enrich/enrich_fill.py --config config.yaml status
```

确认所有待填充岗位已处理完毕。填充结果已写入 `position_final.csv`，format 已自动更新 `position_final_kb.csv` 及报告。

---

## 重复执行

每批完成后询问用户"已填充 X/370 条，是否继续下一批？"用户确认后，回到 Step 1。
