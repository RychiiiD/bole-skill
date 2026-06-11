---
name: bole-enterprise-sources
description: 根据目标城市自主发现企业资质获取来源渠道
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

Discover enterprise qualification data sources for the target city using web search.

## Input

Read `data/.bole_context.json`:
- `city` — 目标城市
- `province` — 城市所属省份/直辖市/自治区
- `region` — 所在大区（华北/东北/华东/华南/华中/西南/西北）

搜索方向通过 WebSearch 自主发现，不预设城市存在哪些资质类型。

## 合规说明

本步骤仅通过公开 Web 搜索发现企业资质来源信息，**不访问任何需要登录的页面**。

---

## ★ 强制自检协议（必须遵守，违反即违规）

### 搜索执行自检清单

进入 Process 之前和之后，**必须**确保以下搜索全部执行完毕：

```yaml
Step 1 探测城市企业资质体系 — 市级搜索（共 10 项）:
  1. "{city} 企业梯度培育 政策"                → [已执行/未执行]
  2. "{city} 专精特新 企业名单 公示"           → [已执行/未执行]
  3. "{city} 高新技术企业 认定"                 → [已执行/未执行]
  4. "{city} 瞪羚企业 名单"                     → [已执行/未执行]
  5. "{city} 独角兽 企业"                       → [已执行/未执行]
  6. "{city} 雏鹰企业"                          → [已执行/未执行]
  7. "{city} 专精特新小巨人"                    → [已执行/未执行]
  8. "{city} 单项冠军 企业"                     → [已执行/未执行]
  9. "{city} 科技型中小企业 评价"               → [已执行/未执行]
  10. "{city} 工信局 企业认定 公示"             → [已执行/未执行]

Step 1 探测城市企业资质体系 — 省级搜索（共 6 项）:
  1. "{province}省工信厅 专精特新 企业名单 公示" → [已执行/未执行]
  2. "{province}省科技厅 高新技术企业 认定 名单" → [已执行/未执行]
  3. "{province}省科技厅 瞪羚 独角兽 企业 名单" → [已执行/未执行]
  4. "{province}省工信厅 单项冠军 小巨人"        → [已执行/未执行]
  5. "{province}省 企业技术中心 名单"            → [已执行/未执行]
  6. "{province}省 科技型中小企业 入库 名单"     → [已执行/未执行]

Step 2 企业信息渠道（共 3 项）:
  1. "{city} 公司 福利 评价"                    → [已执行/未执行]
  2. "{city} 招聘 企业 规模"                    → [已执行/未执行]
  3. "{city} 企业信息 平台"                     → [已执行/未执行]
```

**如果任一搜索项标记为「未执行」→ 必须补执行，不得跳过。**

### 来源验证自检清单

```yaml
对每个找到的资质公示页面确认:
  1. URL 是否可以直接访问？（无需登录）
  2. 页面类型是哪种？（网页表格/PDF下载/Excel下载）
  3. 是否需要交互才能看到数据？（年份选择/查询按钮/验证码）
  4. 该来源是否确实包含企业名单（不是政策文件）
  5. ★ 采集可行性预判:
     - 通过 WebSearch 结果观察来源域名是否是政府网站 (.gov.cn)
     - 留意页面摘要/标题中是否有下载链接 (xlsx/xls/pdf/doc)
     - 最终的采集判定由 bole-enterprise-collect 的 robot_scan.py 下载链接检测执行
```

### Report 完整性自检清单

```yaml
- 确认存在的资质类型数量是否覆盖了已找到的所有类型？
- 每个类型是否标注了发布机构、URL、页面类型？
- 未发现的资质类型是否单独列出？
- 企业信息渠道是否都覆盖？
- 采集建议是否明确给出了优先级？
```

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 只搜索省不搜市（或反之） | 省级和市级搜索必须全部执行 |
| 跳过某些搜索项认为"该城市肯定没有" | 必须搜索验证 |
| 不记录未发现的资质类型 | 在报告中明确标注 ❌ |
| 遇到偏离原始流程的决定（跳过来源/资质类型/步骤、缩减搜索量、用部分结果替代完整结果、流程未明确规定时的替代方案） | 必须暂停并询问用户，不得自行决定 |

## Process

Use web search (WebSearch) to discover sources for the target city. Do NOT hardcode — search each time.

### Step 1 — 探测城市企业资质体系

按 `city` 和 `province` 两个维度搜索，因为资质名单有的是市级发布（如市科技局的高企名单），有的是省级发布（如省工信厅的专精特新名单）：

**市级搜索：**
- `"{city}" 企业梯度培育 政策`
- `"{city}" 专精特新 企业名单 公示`
- `"{city}" 高新技术企业 认定`
- `"{city}" 瞪羚企业 名单`
- `"{city}" 独角兽 企业`
- `"{city}" 雏鹰企业`
- `"{city}" 专精特新小巨人`
- `"{city}" 单项冠军 企业`
- `"{city}" 科技型中小企业 评价`
- `"{city}" 工信局 企业认定 公示`

**省级搜索（部分资质由省级部门公示）：**
- `"{province}省工信厅" 专精特新 企业名单 公示`
- `"{province}省科技厅" 高新技术企业 认定 名单`
- `"{province}省科技厅" 瞪羚 独角兽 企业 名单`
- `"{province}省工信厅" 单项冠军 小巨人`
- `"{province}省 企业技术中心 名单"`
- `"{province}省 科技型中小企业 入库 名单"`

For each search result, determine:
1. **该资质类型在城市是否存在**（有相关公示/名单 → 存在）
2. **名单获取方式**（网页表格 / PDF下载 / Excel下载 / 需手动操作）
3. **具体 URL**（公示页面的直接链接）

### Step 2 — 发现企业信息渠道

Search for enterprise info channels with data in the target city:

- `"{city}" 公司 福利 评价`
- `"{city}" 招聘 企业 规模`
- `"{city}" 企业信息 平台`

For each platform, confirm if it covers the target city and can provide:
- 企业福利信息（五险一金、双休等）
- 企业规模（员工人数）
- 企业官网



---

## ★ 来源人工确认协议（必须遵守，不可跳过）

**所有搜索完成后，不得自动输出报告。** 必须先向用户展示发现的资质类型和来源列表，等待用户确认后方可继续。

### 来源确认摘要格式

```
╔══════════════════════════════════════════╗
║  [{city}] 企业资质来源发现结果            ║
║══════════════════════════════════════════║
║  [确认存在的资质类型]                      ║
║  ├─ 专精特新     ✅ {发布机构}           ║
║  ├─ 高新技术企业 ✅ {发布机构}           ║
║  ├─ 瞪羚企业     ⚠️ 需进一步确认         ║
║  └─ 独角兽       ❌ 该城市无此类型        ║
║                                           ║
║  [企业信息渠道]                            ║
║  ├─ {渠道}       ✅ {url}                ║
║  └─ {渠道}       ⚠️ 结果不确定            ║
║                                           ║
║  总计: N 个资质来源, M 个信息渠道          ║
╚══════════════════════════════════════════╝

以上来源是否符合预期？(确认 / 需补充 / 重做)
```

### 执行规则

- 每次展示后必须等待用户输入，不得自行继续
- 用户选择「确认」→ 生成发现报告并继续下一步
- 用户选择「需补充」→ 按用户指示补充缺失的资质类型搜索
- 用户选择「重做」→ 重新执行全量搜索

### Step 3 — 生成发现报告（需先经用户确认）

Based on findings, output a structured report using `{city}` from `data/.bole_context.json`:

```
========================================
  [{city}] 企业资质来源发现报告
========================================

[确认存在的资质类型] 发现 N 类：
  ✅ {资质类型} — {发布机构}
     URL: {公示页面链接}
     类型: {网页表格/PDF下载/Excel下载}
  ...

[该城市未发现的资质类型]：
  ❌ {资质类型} — {城市}无此政策或无上榜企业

[企业信息渠道] 覆盖{city}：
  ✅ {渠道名称} — {URL}
  ...

[采集建议]
  1. 优先采集政府名单（免费，无需登录）
     先确认可自动获取的资质名单
  2. 再通过全网检索补充企业福利和规模信息
     渠道优先级：企业官网 > 招聘平台企业主页 > 点评平台
```

## Output

用户确认后，按以下步骤执行：

### 1. 打印发现报告

Print the structured discovery report to the user.

### 2. 写入结构化来源文件

Write `data/enterprise/.enterprise_sources.json` with the list of all confirmed qualification sources and enterprise info channels.

**文件格式：**
```json
{
  "city": "{城市名}",
  "province": "{省份}",
  "discovered_at": "{ISO 时间戳}",
  "qualification_sources": [
    {
      "qualification_type": "专精特新",
      "source_name": "吉林省工信厅_2025省级专精特新",
      "url": "http://gxj.jl.gov.cn/公示页面.html",
      "page_type": "pdf_download",
      "institution": "吉林省工信厅",
      "year": 2025
    }
  ],
  "enterprise_info_channels": [
    {
      "channel_name": "天眼查",
      "url": "https://www.tianyancha.com/",
      "description": "企业工商信息"
    }
  ],
  "_meta": {
    "total_sources": 5,
    "confirmed_by_user": true,
    "confirmed_at": "{ISO 时间戳}"
  }
}
```

**page_type 可选值：** `pdf_download` / `excel_download` / `word_download` / `web_table` / `interactive_query`

**source_name 命名规则：** `{机构}_{年份}{资质类型}`（如 `吉林省工信厅_2025省级专精特新`）

`_meta.confirmed_by_user` 的校验同岗位管线 — pipeline.py verify 会校验此标记，缺失则 exit(2) STOP，**AI 不得在用户确认前设置此标记**。

### 3. 标记完成

The discovered sources in `.enterprise_sources.json` will be used by `bole-enterprise-collect` in the next step.

```bash
python scripts/pipeline/pipeline.py complete enterprise discover_sources
```
