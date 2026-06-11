---
name: bole-collect
description: 从招聘平台采集岗位数据 — API 拦截/SSR 提取双模式
version: 1.0.0
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - browser_navigate
  - browser_snapshot
  - browser_evaluate
  - browser_network_request
  - browser_network_requests
  - browser_run_code_unsafe
  - browser_screenshot
---

Collect job listings from configured sources via **network request interception** or **SSR embedded data extraction**.

---

## ★ 角色声明 — 采集协议执行者

我是采集协议的执行者，不是采集流程的设计者。以下所有标注 `★` / `必须` / `禁止` 的规则，我必须逐条执行、不得省略。任何"这样更高效""跳过这个检查也能用""先采了再说"等想法都不能取代对协议的遵守。

## ★ 采集前重读指令（必须执行，不可凭记忆）

开始采集或切换到下一来源前，**必须先 Read 对应来源的协议章节**，禁止凭之前的记忆执行。全文件 ~900 行，上下文压缩后协议细节可能丢失，必须重新确认。

来源协议章节位置（行号范围）：

| 来源 | 章节 | 行号 |
|------|------|------|
| 智联招聘（SSR 提取） | 智联招聘章节 | ~L564-L578 |
| BOSS直聘（page.request.post） | BOSS直聘章节 + 登录探针 | ~L582-L670 |
| 猎聘 / 前程无忧（API 拦截） | 猎聘/前程无忧章节 | ~L675-L682 |
| 通用 Tier-2+ searchable | 通用 searchable 流程 | ~L484-L513 |
| 通用 Tier-2+ notice_list | 通用 notice_list 流程 | ~L515-L560 |

重读方式：`Read .claude/skills/bole-collect/SKILL.md` + 指定行号范围。读完确认关键步骤后再操作。

## ★ 强制自检协议（必须遵守，违反即违规）

每次 `browser_navigate` 后，**必须**执行以下自检流程，不得跳过、不得臆断：

### 导航后自检 checklist

```yaml
1. browser_snapshot          → 确认页面渲染结果
2. 检查页面是否包含以下禁止状态:
   - "登录"/"注册"/"验证码"/"扫码"  → 暂停，提示用户手动操作
   - "不存在"/"没有找到"/"暂无"/"没有合适的" → 此为客观结果，如实记录，不臆断原因
   - 页面跳转到 about:blank           → 页面异常，尝试重新导航
3. ★ 城市选择（Agent 隔离执行）:
   - 城市选择已由「城市选择子 Agent」在采集前完成
   - 本步骤不再执行城市检查
4. 检查结果分类处理:
   - 正常显示岗位列表 → 继续采集
   - 登录/验证码拦截  → 暂停脚本，提示用户手动处理（见下方协议）
   - 空结果（暂无岗位）→ 记录到日志，跳过该关键词/来源
   - 页面异常/跳转    → 尝试重新导航一次，仍失败则跳过
5. ★ 证据留痕（代码强制校验）: 首次导航到该来源时，必须保存以下证据到 data/position/raw/evidence/:
   a. 着陆页截图: 自检第一步的 browser_snapshot 保存为 {source_id}_landing.png
   b. 自检记录: Write 以下 JSON 到 {source_id}_check.json:
      {"source_id":"{来源ID}","check_time":"{当前时间}","url_loaded":"{实际URL}",
       "page_loaded":true/false,"login_detected":true/false,
       "page_type":"job_listing/notice_board/login_page/other"}
   ※ BOSS 除外（about:blank 跳转不可避免，用登录探针代替）
   ※ 仅首次导航到每个来源时保存一次，翻页/换关键词不重复
   ※ pipeline.py verify collect 校验证据文件，缺失则 exit(2) STOP
```

### ★ 关键词遍历自检清单（每次切换关键词/来源前必须执行）

在**每次关键词遍历完成、准备切换到下一个关键词或来源时**，必须执行此自检，不得跳过：

```yaml
0. ★ keyword-verify 闸门（代码强约束 — 每次关键词采集完成后必须执行）:
   运行以下命令确认当前关键词的翻页连续性和数据完整性:
   python scripts/pipeline/pipeline.py keyword-verify <source> <keyword>
   ├─ exit(0) → 校验通过，继续第 1 步
   └─ exit(2) → 采集不完整（有 page 未采集/页码不连续/实际页数 < totalPages），
                不得切换到下一关键词，必须补齐缺失页面后再运行 keyword-verify
                确认通过，方可继续
   ※ 遇到限速 → 暂停采集，展示状态给用户决策
   ※ 缺页必须用新 tab/新会话补齐，不得因限速跳过该关键词

1. 确认当前关键词当前来源的采集是否完成（已到末页 or 已无下一页）
2. 对照「采集计划矩阵」检查:
   - 当前来源是否还有未完成的关键词？
     ├─ 是 → 自动切换到下一关键词 → 返回「导航后自检 checklist」继续采集
     └─ 否 → 进入第 3 步
3. 当前来源所有关键词已完成 → ★ 执行来源级登录闸门 auth-scan（代码强制阻塞）:
   运行 python scripts/pipeline/pipeline.py auth-scan <source_id>
   ├─ exit(0) → 无登录检测异常，进入下方放行流程
   └─ exit(1) → 检测到登录证据，data/.auth_blocked 已写入，管道已冻结
   ↓
   判断当前来源所属层级:
   ├─ [主流招聘平台] → ★ 暂停，向用户展示「采集结果摘要」，询问是否放行到下一来源
   │   └─ 用户确认放行 → ★ 写入放行标记:
   │       touch data/position/.source_{source_id}_confirmed
   │       (pipeline.py verify 校验此标记，缺失则 exit(2) STOP)
   │   └─ 用户拒绝/要求调整 → 按用户指示操作
   └─ [Step 3 各层级] → 不暂停，直接进入第 4 步
4. 对照「采集计划矩阵」检查:
   ├─ 当前层级内是否还有未完成的来源？
   │  └─ 是 → 切换到下一来源 → 返回「导航后自检 checklist」继续采集
   └─ 当前层级内所有来源已完成 → 判断当前层级:
      ├─ [主流招聘平台] → 已在前一步放行，自动进入下一层级
      └─ [Step 3 层级] → ★ 暂停，向用户展示「层级采集结果摘要」，询问是否放行到下一层级
          ├─ 放行 → 切换到下一层级第一个来源
          ├─ 重试失败项 → 重试该层级中异常的关键词/来源
          └─ 终止 → 进入采集完成验证
5. 所有来源、所有关键词均已采集完成 → 执行「采集完成验证」
```

**禁止行为**：
- 不得跳过剩余关键词直接结束采集
- 不得跳过剩余来源直接结束采集
- 不得在来源/层级间切换时擅自放行自己——放行权在用户手中
- 不得用"该来源卡住了""该关键词无结果"等主观判断替代用户决定
- 主流平台以外的 Step 3 层级不得在单来源完成后暂停（必须等整个层级完成）

### 登录/验证码处理协议（严格禁止跳过）

**遇到以下任何情况，必须暂停脚本并向用户提示，不得自行跳过来源：**

1. 页面出现登录弹窗/注册页面 → 提示用户登录
2. 出现验证码/扫码登录 → 提示用户手动验证
3. 页面提示"登录后可查看更多" → 提示用户登录
4. 数据被隐藏（显示脱敏/模糊）→ 提示用户登录

**★ 截图证据强制要求（代码硬约束）：**

在提示用户之前，**必须先截图保存为证据**，否则 `pipeline.py verify` 自检会拦截：

```yaml
1. browser_snapshot 截图当前页面（保留登录/验证码现场）
2. 保存到 data/position/raw/evidence/{id}_{keyword}.png
   （{id} 来源ID, {keyword} 搜索关键词，含中文）
3. 写入管道阻塞标记 data/.auth_blocked（{"source": "{id}", "keyword": "{keyword}"}）
   所有 pipeline.py 命令（除 status 和 auth-release）会检测此文件，
   存在时阻止一切后续操作。用户处理后运行 auth-release 解锁。
   这是代码级阻塞——AI 无权绕过。
4. 然后暂停提示用户
```

**★ 来源级 auth-scan 二次校验（代码强制门）：**

每个来源全部关键词采集完成后，**必须**运行 `auth-scan` 代码检查：

```bash
python scripts/pipeline/pipeline.py auth-scan <source_id>
```

- exit(0) → 该来源数据无登录异常，继续放行流程
- exit(1) → 检测到登录证据（未写 .auth_blocked 的记录、空薪资率 > 80%、无效 note 值），
  .auth_blocked 已自动写入，管道冻结

`auth-scan` 是独立的代码扫描，不依赖 AI 在采集过程中的判断——即使 AI 漏写了 .auth_blocked，
`auth-scan` 也会通过分析数据文件特征检测到登录证据并阻塞管道。这是「AI 未执行协议」的兜底防线。

**提示格式（截图已保存 + 管道已阻塞后）：**
```
[来源名称] 需要登录才能采集。
截图已保存到 evidence/ 目录，请查看。
管道已阻塞（data/.auth_blocked），采集流程已暂停。
  请在浏览器中完成登录后告诉我"继续"
  或输入"跳过"跳过此来源
```

**用户登录完成后，刷新页面继续采集，不跳过该来源。** 选择跳过 → 运行 `python scripts/pipeline/pipeline.py auth-release` 解除阻塞，该来源所有关键词记 `login_blocked`。

### 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| 看到登录弹窗就主观认为"该城市无结果" | 检查页面客观内容，如实报告 |
| 看到空结果就跳转到下一来源 | 先确认是否需要登录才能显示结果 |
| 连续失败时自行跳过来源 | 提示用户，让用户决定 |
| 以"可能""也许""大概"推测页面状态 | 用 browser_snapshot 获取客观事实 |
| **在 URL 中硬编码任何城市参数**（city=530 / jobArea=xxx / dqs=xxx） | URL 中不得包含城市参数，通过页面 UI 选择器选城市 |
| 遇到偏离原始流程的决定（跳过来源/关键词/步骤、缩减采集量、用部分结果替代完整结果、流程未明确规定时的替代方案） | 必须暂停并询问用户，不得自行决定 |
| **自行撰写采集摘要代替脚本输出**（主流/层级摘要必须由 collect_report.py 生成） | 运行 collect_report.py，**原文展示脚本输出**，不得修改 |
| verify 失败后自行重试/补采/--skip-verify | 停止，展示失败报告给用户，等待用户决策 |
| **限速触发时自行跳过该关键词（或该关键词所有页面采集完成前切换下一关键词）** | 暂停采集，展示状态给用户，由用户决定重试/跳过/终止 |
| **检测到登录墙但不写 .auth_blocked 继续采集** | 见上方「登录/验证码处理协议」——**必须**写 .auth_blocked 阻塞管道 |
| **修改/伪造 note 字段值以绕过校验** | note 由脚本在采集时写入，**事后修改属于数据篡改**，pipeline.py _check_protocol_compliance 会扫描所有 note 值 |

---

## ★ 速率限制硬约束（必须遵守，不得突破）

以下为采集过程中必须遵守的速率限制数值。**这些不是建议值，是硬性约束。**

### 基础约束（所有来源通用）

| 限制项 | 数值 | 说明 |
|-------|:----:|------|
| 连续采集上限 | 5 页 | 同一来源连续翻页 5 页后，必须停顿 ≥ 3 秒 |
| 单来源小时上限 | 180 页/小时 | 同一来源每小时翻页总量不超过 180 页 |
| 全局小时上限 | 500 请求/小时 | 所有来源合计每小时不超过 500 次浏览器请求 |

### ★ 先验代码门禁：rate-tick（强制，不可跳过）

每次发起翻页/导航请求**之前**，AI 必须运行以下命令：

```bash
python scripts/pipeline/pipeline.py rate-tick <source_id>
```

- **exit(0)** → 速率门禁通过，可以发送请求
- **exit(1)** → 速率限制触发，AI 必须等待后重试，不得自行绕过

`rate-tick` 内部维护一个状态文件 `data/.rate_state.json`，代码级校验两项：

| 检查项 | 逻辑 | 阻塞条件 |
|:-------|:-----|:---------|
| 突发 | 连续 N 页后是否已长停 | ≥ 5 页且距上次 < 3s |
| 小时上限 | 本小时总请求数 | ≥ 180 |

**pipeline.py verify bole collect 会自动检查 `.rate_state.json` 是否存在且记录完整，缺失则 exit(2) STOP。**

### 辅助执行方式

```yaml
1. AI 在翻页循环中：
   - 每次请求前先调用 rate-tick
   - 通过后发请求
   - 如果 rate-tick exit(1) → 暂停采集，向用户展示状态

2. 主 AI 直接 page++ 循环，每页前调用 rate-tick：
   "每页前运行 rate-tick, 连续 5 页后停 ≥ 3s"

3. 遇到平台返回限速/429/频率过高时：
   - 立即暂停当前关键词的采集
   - 向用户展示当前采集状态
   - 等待用户决策（等待后重试 / 跳过该关键词 / 跳过该来源 / 终止）
   - 不得自行降低间隔继续采集
```



### ★ 翻页完整性自检（每次关键词采集完成后执行）

每次完成一个关键词的翻页采集后，在进入「关键词遍历自检清单」前，**必须**执行以下自检：

```yaml
1. 确认已采集的页码范围:
   - 列出 raw/ 目录下该来源×关键词的所有文件
   - 最大页码 N = page{N} 中的 N
   - 实际采集页数 = 文件数量

2. 判断翻页是否完整:
   - 查看 page 1 JSON 中的 jobList 长度（或 jobs 数组长度）
   - BOSS 直聘: 检查 JSON 中 zpData.resCount 字段
     resCount > 15 且只有 page 1 → 翻页不完整
     resCount / 15 = 实际页码数 → 翻页完整
   - 通用规则: page 1 数据量 ≥ 10 条但只有 page 1 → 翻页可能不完整
     页码数 ≥ 2 → 翻页正常

3. 翻页不完整的处理:
   - 有下一页但未采集 → 继续翻页
   - 因页面跳转中断 → 暂停采集，展示状态给用户决策
   - ★ 遇到限速 → 暂停采集，展示状态给用户决策
   - 该关键词确实只有 1 页数据 → 在 page 1 JSON 的 totalPages 字段记录为 1

4. ★ keyword-verify 代码校验（翻页自检完成后必须执行）:
   运行:
   python scripts/pipeline/pipeline.py keyword-verify <source_id> <keyword>
   ├─ exit(0) → 翻页连续 & 数据完整 → 进入「关键词遍历自检清单」
   └─ exit(2) → 翻页缺失/不完整 → 补齐后再运行 keyword-verify，通过后方可切换关键词

5. ★ 关键词溯源检查（代码级，pipeline.py 协议合规门已自动扫描）:
   - 打开 page 1 JSON，检查 jobs[].title 中是否包含本关键词
   - ≥ 5 条岗位但含关键词的比例 < 5% → 搜索可能未生效，数据标错关键词
   - 对比同来源不同关键词的 page1 数据 → 若内容完全相同 → 搜索未生效
   - pipeline.py 的 _check_protocol_compliance 和 _v_bole_collect 会自动拦截此类问题

6. 📌 pipeline.py verify 实际翻页检查逻辑:
   - 文件名有 `_page{N}` 后缀 → 检查页码连续性（如缺 page3 则报错）
   - 文件名无 `_page{N}` 后缀 → 视为单文件全量数据，跳过翻页检查
   - 报错后必须向用户展示校验报告，等待用户决策
   - 用户可通过 --skip-verify 确认接受现状
```

**翻页终止条件**（满足任一即视为末页）：
1. API 响应中 `currentPage * pageSize >= total`（分页参数明确）
2. 翻页后内容为空（空数组或 404）
3. 翻页后内容与上一页完全重复（防无限循环）
4. BOSS 连续 3 页无新 `lid`（仅剩重复数据）

---

## ★ 城市选择协议（Agent 隔离 + 存证复用）

**首次 UI 选择，同来源后续关键词复用城市编码存证。**

每个来源的首个关键词，必须通过 Agent 工具调用城市选择子 Agent，通过 UI 选择目标城市。自验通过后子 Agent 会写入 `.city_verified_{source_id}.json` 存证文件（含 city_code）。同一来源的后续关键词先检查存证：

```
检查 evidence/.city_verified_{source_id}.json 是否存在:
  ├─ 存在且 city_code 非空 → 跳过城市选择，直接使用已记录的 city_code
  └─ 不存在或 city_code 为空 → 执行城市选择子 Agent，自验后写存证
```

**每次管线 `reset` 自动清除所有城市存证**，下一轮所有来源从头走 UI 选择。

详见 `skills/bole-city-select/SKILL.md`。

---

## Input

Read `data/.bole_context.json`:
- `city` — 目标城市
- `title_keywords` — 岗位关键词
- `search_keywords` — 搜索关键词

Also read `data/position/.sources.json` (generated by Step 1 — Discover Sources) to get the list of enabled sources.

## MCP 工具健康检查

MCP 浏览器进程可能因长时间空闲已失效。

**在开始任何 browser_navigate 前，先执行：**

1. 调用 `browser_snapshot` 检查 MCP 是否可用
2. 如果正常返回 snapshot → 继续采集
3. 如果返回错误（如"playwright MCP not found"或超时）→ **必须停止并提示用户**：
   ```
   MCP Playwright 工具不可用。请执行 /clear 重启会话后重试。
   ```

**不要**在 MCP 不可用时尝试任何浏览器操作——所有 browser_navigate/browser_click 等都会失败。

## ★ 采集前合规三步检查（必须执行，不可跳过）

**开始第一个来源的采集前，必须先执行以下合规检查。** 后续来源切换时不重复执行（标记文件已存在即通过）。

### 1. 合规确认（首次运行）

检查 `data/.compliance_accepted` 是否存在：

```bash
python scripts/pipeline/pipeline.py compliance-check
```

- **exit(0)** → 已确认，继续
- **exit(1)** → 展示合规声明给用户，获得用户明确同意后：
  ```bash
  python scripts/pipeline/pipeline.py compliance-accept
  ```

### 2. 来源 robots.txt 检测（每个新来源首次采集前执行）

采集每个来源前（首次 navigation），必须检测该来源的 robots.txt 是否禁止采集路径：

```bash
python scripts/pipeline/pipeline.py robots-check <source_url>
```

- **exit(0)** → robots.txt 允许或不存在，继续采集
- **exit(1)** → robots.txt Disallow 匹配，暂停并向用户展示：
  - 展示 robots.txt 检测报告原文
  - 用户明确确认可继续后放行
  - 用户不同意则跳过该来源

**注意**：同一来源下不同关键词/翻页不重复检测，仅首次 navigation 到该来源时执行一次。

### 3. 数据 TTL 检查（每轮采集开始前）

```bash
python scripts/pipeline/pipeline.py preflight
```

- 检测 data/position/raw/ 中是否存在超过 7 天的旧数据
- 如有，提示用户清理或保留

---

## 采集方式

## 核心方法：三模式采集

根据不同平台的技术架构，选用三种模式之一：

| 模式 | 适用场景 | 方法 |
|------|---------|------|
| **API 拦截** | 岗位数据通过 XHR/fetch 加载 | `browser_network_requests` + `browser_network_request` 获取 API JSON |
| **page.request.post** | BOSS 直聘（页面 fetch 被拦截跳转） | `browser_run_code_unsafe` 中执行 `page.request.post()` |
| **SSR 提取** | 岗位数据嵌在 HTML `<script>` 中 | `browser_evaluate` 读取 `window.__INITIAL_STATE__` 等全局变量 |

### 模式 A：API 拦截（猎聘/前程无忧）

```
browser_navigate → 页面加载时发出 XHR/fetch 请求
    ↓
browser_network_requests(static: false) → 列出所有网络请求
    ↓
筛选匹配岗位数据的 API 请求（按 URL 关键词：search/list/job/position 等）
    ↓
browser_network_request(index, part: "response-body") → 获取完整 JSON
    ↓
解析结构化字段（title/salary/company/experience/education/posting_date 等）
    ↓
提取分页信息（total/pageSize/pageNo），决定是否翻页
    ↓
翻页：更新 URL page 参数 → browser_navigate → 重复捕获
```

**优势**：API 响应是结构化 JSON，字段完整稳定，翻页参数直观，不受字体影响。

### 模式 B：SSR 内嵌数据提取（智联招聘）

智联招聘使用 React SSR，岗位数据直接嵌入 HTML 的 `<script>` 标签中，不存在独立的 XHR API 请求。

```
browser_navigate → 页面加载 SSR 完成
    ↓
browser_evaluate(function) → 读取 window.__INITIAL_STATE__.positionList
    ↓
直接在浏览器端解析字段，返回结构化 JSON
    ↓
翻页：更新 URL page 参数 → browser_navigate → 重复
    ↓
文件保存：browser_evaluate(+filename) 直接写盘
```

**智联招聘字段映射**（`window.__INITIAL_STATE__.positionList[]` 每个元素）：

| 输出字段 | JSON 路径 | 示例 |
|---------|-----------|------|
| title | `job.name` | "产品经理" |
| company | `job.companyName` | "某某公司" |
| salary | `job.salary60` | "8000-12000元" |
| salary_real | `job.salaryReal` | "8001-12000" |
| education | `job.education` | "本科" |
| experience | `job.workingExp` | "3-5年" |
| industry | `job.industryName` | "软件/IT服务" |
| company_size | `job.companySize` | "100-299人" |
| company_type | `job.property` | "民营" |
| publish_time | `job.publishTime` | "2026-05-21 16:51:50" |
| url | `job.positionURL` | "http://www.zhaopin.com/jobdetail/..." |

**翻页 URL 模式**：
- 首页：`https://www.zhaopin.com/sou/?kw={keyword}`（含城市参数需去掉，通过页面 UI 选择城市）
- 用城市选择器选目标城市后，页面刷新，URL 自动带上对应的 city 参数
- 翻页：`{base_url}/p{page}?city={从当前页URL提取的city值}`
- 分页数通过 DOM 获取：`document.querySelectorAll('.pagination a')` 取最大数字

**关键发现**：`browser_evaluate` 返回的如果是 `JSON.stringify()` 结果 + `filename` 参数，
文件会保存为**双编码 JSON**（字符串内嵌字符串）。解决方法：之后用 Python 修复，或者在 evaluate 中直接返回对象而非字符串（由 Playwright 自动序列化）。

### 模式对比

| | API 拦截模式 | page.request.post 模式 | SSR 提取模式 |
|--|------------|----------------------|------------|
| 工具 | `browser_network_requests`, `browser_network_request` | `browser_run_code_unsafe` | `browser_evaluate` |
| 数据来源 | 网络请求响应体 | Node.js 沙箱 POST 请求 | `window.__INITIAL_STATE__` |
| 分页判断 | API 响应中的 total/pageSize/pageNo | API 响应中的 resCount | DOM 分页组件数字 |
| 保存方式 | `browser_network_request` + Python 写盘 | `browser_run_code_unsafe` 内 fs.writeFileSync（5页批处理） | `browser_evaluate` + `filename` 直接写盘 |
| 适用平台 | 猎聘、前程无忧（页面不跳转） | **BOSS直聘**（页面自动跳转 about:blank） | 智联招聘 |

## ★ 采集前规划（必须执行，不可跳过）

在开始任何 browser_navigate 前，**必须先输出采集计划矩阵**，枚举所有来源 × 关键词的组合，并按来源技术类型分组：

```yaml
采集计划矩阵:
  来源分组（按技术类型 + 放行层级）:
    [Tier-1 主流招聘平台]（每来源人工放行，tech_type=searchable）:
      - 读取 .sources.json 获取 id/name/url
      - 所有主流平台统一按 searchable 流程处理
      - 行为差异仅在 URL 模板和页面交互细节（保留 site-specific 描述）
    
    [Tier-2+ searchable 来源]（按来源组人工放行，tech_type=searchable）:
      - 读取 .sources.json，筛选 tech_type=searchable 且非 Tier-1 的来源
      - 统一按通用 searchable 流程处理
      - 无 site-specific 描述，通过 browser_snapshot 自适应各站 UI
    
    [Tier-2+ notice_list 来源]（按来源组人工放行，tech_type=notice_list）:
      - 读取 .sources.json，筛选 tech_type=notice_list 的来源
      - 按通用 notice_list 流程处理
      - 无关键词概念，文件名使用 all 代替关键词段
    
  关键词列表: [从 data/.bole_context.json → search_keywords 读取]
  城市: [从 data/.bole_context.json → city 读取]
  总组合数:
    - Tier-1 searchable: len(Tier-1来源) × len(关键词)
    - Tier-2+ searchable: len(Tier-2+ searchable来源) × len(关键词)
    - Tier-2+ notice_list: len(notice_list来源) × 1（只有 all）

执行规则:
  - 遍历顺序：Tier-1（逐来源人工放行）→ Tier-2+ searchable（逐组人工放行）→ Tier-2+ notice_list（逐组人工放行）
  - 同组来源之间自动切换，不停顿、不询问
  - 每一来源/关键词完成后执行「关键词遍历自检清单」
  - 人工放行规则（见下方「★ 分层人工放行协议」）
```

此矩阵在执行过程中作为进度追踪依据，每完成一个来源标记一个。

**阅读 .sources.json：** 采集前必须读取 `data/position/.sources.json`，使用 `id` 字段作为文件名前缀，`tech_type` 决定采集流程，`pipeline` 过滤（只处理 pipeline=job 的来源）。

---

## 通用采集流程

```
输出「采集计划矩阵」（含技术类型分组）
↓
=== Tier-1 主流平台 ===
来源循环（逐个来源，每完成一个暂停人工放行）:
  keyword 循环:
    browser_navigate → 打开搜索页（URL 中无城市编码，仅含 {keyword}）
    ↓
    ★ 执行「导航后自检 checklist」← 必须，不可跳过
    ↓
    ★ 城市存证检查:
       evidence/.city_verified_{source_id}.json 存在且 city_code 非空?
       ├─ 是 → 跳过城市选择，直接使用 city_code
       └─ 否 → 执行城市选择子 Agent（详见 skills/bole-city-select/SKILL.md）
    Agent(
      description: "城市选择",
      prompt: "...城市选择协议，目标城市={city}"
    )
    ├─ city_verified → 继续
    └─ city_failed → 展示截图，用户手动选完后继续
    ↓
    login_check → 是否出现登录/验证码?
      ├─ 是 → 暂停，提示用户手动处理 → 处理后刷新页面继续
      └─ 否 → 继续
    ↓
    ★ city_select_agent → 城市已由子 Agent 确认匹配或存证复用，无需再次检查
    ↓
    ★ 翻页采集（主 AI 直接 page++ 循环，每页前 rate-tick）
    调用前向用户展示进度预告：
      "[{来源名称} × {keyword}] 正在翻页采集..."
      （如 page1 已知 totalPages，附加 "约 {N} 页，完成后自动校验"）
    Agent(
      description: "翻页采集",
      prompt: "{采集协议，含该来源技术类型 URL/API/提取方式} 目标关键词={keyword}"
    )
    子 Agent 返回后展示结果摘要：
      ├─ success → "[{来源名称} × {keyword}] 完成：{total_pages} 页，{total_count} 条"
      ├─ partial → 展示 issues + "[{来源名称} × {keyword}] 部分完成（{total_pages} 页），存在异常"
      └─ failed → 展示 issues + "[{来源名称} × {keyword}] 采集失败，等待处理"
    ↓
    ★ 执行「关键词遍历自检清单」（主 AI 已执行 keyword-verify）
    清单确认有下一关键词 → 自动切换，不询问
  ↓
  ★ 执行「关键词遍历自检清单」（全部关键词完成）
  ↓
  ★ 来源级登录闸门 auth-scan（代码强制门）:
      python scripts/pipeline/pipeline.py auth-scan <source_id>
      ├─ exit(0) → 无登录证据，继续放行流程
      └─ exit(1) → 检测到登录证据，管道冻结，展示报告等待用户处理
  ↓
  ★ 暂停 → 运行 collect_report.py --source <id> → 展示原文 → 等待用户放行
    用户确认放行 → 继续下一来源

=== Tier-2+ searchable 来源 ===
来源循环（逐来源，同组内自动切换不暂停）:
  同 Tier-1 的 keyword 循环逻辑（通用 searchable 流程）:
    browser_navigate → 搜索页
    ★ 执行「导航后自检 checklist」
    ↓
    ★ 城市存证检查:
       evidence/.city_verified_{source_id}.json 存在且 city_code 非空?
       ├─ 是 → 跳过城市选择，直接使用 city_code
       └─ 否 → 执行城市选择子 Agent
    ├─ city_verified → 继续
    └─ city_failed → 展示截图，用户手动选完后继续
    ↓
    ★ 翻页采集（主 AI 直接 page++ 循环，每页前 rate-tick）
    调用前向用户展示进度预告：
      "[{来源名称} × {keyword}] 正在翻页采集..."
    Agent(...)
    子 Agent 返回后展示结果摘要：
      ├─ success → "[{来源名称} × {keyword}] 完成：{total_pages} 页，{total_count} 条"
      └─ failed → 展示 issues + 采集失败
    ↓
  ★ 当前来源全部关键词完成 → 执行后置自检:
      python scripts/pipeline/pipeline.py verify bole collect
      ├─ exit(0) → 校验通过，继续
      └─ exit(2) → 展示失败报告给用户，等待决策
  ↓
  ★ 来源级登录闸门 auth-scan（代码强制门）:
      python scripts/pipeline/pipeline.py auth-scan <source_id>
      ├─ exit(0) → 无登录证据，继续放行流程
      └─ exit(1) → 检测到登录证据，管道冻结，展示报告等待用户处理
  ↓
★ 全部 Tier-2+ searchable 完成 → 暂停 → 运行 collect_report.py --config config.yaml → 展示原文 → 等待用户放行

=== Tier-2+ notice_list 来源 ===
来源循环（逐来源，同组内自动切换不暂停）:
  通用 notice_list 流程:
    ★ 采集前下载链接检测:
        0. 运行 robot_scan.py（首次导航到该来源时执行一次）:
           python scripts/enterprise/robot_scan.py \
             --url "{来源 URL}" \
             --output "data/position/raw/evidence/.robot_check_{source_id}.json" \
             --source-name "{source_name}"
        1. 运行代码门:
           python scripts/pipeline/pipeline.py robot-check position <source_id>
           ├─ exit(0) → 有下载链接，继续采集
           └─ exit(1) → 无下载链接，跳过该来源
                         → 在放行协议中展示 ⛔ 跳过（无下载链接）
                         → 如用户仍确认要采集，用户确认后才可继续
    ↓
    browser_navigate → 列表页 URL
    ★ 执行「导航后自检 checklist」
    ↓
    ★ 城市存证检查:
       evidence/.city_verified_{source_id}.json 存在且 city_code 非空?
       ├─ 是 → 跳过城市选择，直接使用 city_code
       └─ 否 → 执行城市选择子 Agent
    ├─ city_verified → 继续
    └─ city_failed → 展示截图，用户手动选完后继续
    ↓
    ★ 翻页采集（主 AI 直接 page++ 循环，每页前 rate-tick）
    调用前向用户展示进度预告：
      "[{来源名称}] 正在翻页采集..."
    Agent(...)
    子 Agent 返回后展示结果摘要：
      ├─ success → "[{来源名称}] 完成：{total_pages} 页"
      └─ failed → 展示 issues + 采集失败
    ↓
  ★ 当前来源完成 → 执行后置自检:
      python scripts/pipeline/pipeline.py verify bole collect
      ├─ exit(0) → 校验通过，继续
      └─ exit(2) → 展示失败报告给用户，等待决策
  ↓
  ★ 来源级登录闸门 auth-scan（代码强制门）:
      python scripts/pipeline/pipeline.py auth-scan <source_id>
      ├─ exit(0) → 无登录证据，继续放行流程
      └─ exit(1) → 检测到登录证据，管道冻结，展示报告等待用户处理
  ↓
★ 全部 Tier-2+ notice_list 完成 → 暂停 → 运行 collect_report.py --config config.yaml → 展示原文 → 等待用户放行

↓
★ 执行「采集完成验证」
```

**翻页终止**（满足任一即末页）：
1. API 响应中 `currentPage * pageSize >= total`
2. 翻页后内容为空
3. 翻页后内容与上一页相同（防无限循环）

### Tier-2+ searchable 通用采集流程（无 site-specific 行为）

对于非主流平台的 searchable 类型来源，不预设任何站点特定的 URL/选择器/流程。通过以下通用策略自适应：

```
1. browser_navigate 到 .sources.json 中该来源的 url
2. ★ 执行「导航后自检 checklist」
   ↓
   ★ 城市存证检查:
      evidence/.city_verified_{source_id}.json 存在且 city_code 非空?
      ├─ 是 → 跳过城市选择，直接使用 city_code
      └─ 否 → 执行城市选择子 Agent
   ├─ city_verified → 继续
   └─ city_failed → 展示截图，用户手动选完后继续
   ↓
3. browser_snapshot 观察页面结构:
   a. 是否存在搜索框（input/搜索/关键字等标识）？
      → 有：输入当前 keyword，触发搜索（点击搜索按钮或回车）
      → 无：URL 中是否已包含 keyword（{keyword} 占位符）？
   b. 是否存在城市/地区选择器？
      → 有：确认已选中 config.city，如不是则切换
      → 无：跳过
4. 页面加载搜索结果后:
   a. browser_snapshot 确认显示的是岗位列表
   b. 如显示登录弹窗/验证码 → ★ 暂停，提示用户，不得自行跳过
   c. 如显示空结果 → browser_take_screenshot 保存证据截图到 evidence/{id}_{keyword}_no_results.png，在 note 注明 no_results，保存空数组
   d. 如已有数据 → 提取前先验证页面内容已更新:
      browser_evaluate: 取第 1 条岗位的 title/岗位名文本
      ├─ 标题含当前 keyword → 页面已刷新 → 继续采集
      └─ 不含当前 keyword 且与上一关键词的首条标题相同
          → SPA 缓存，browser_navigate 强制硬刷新
          → 重新验证，仍相同 → 注为 keyword_not_applicable
   e. 通过验证后 → 提取字段（观察 DOM 结构/网络请求/SSR 数据）
5. 翻页: 找翻页控件（页码/下一页按钮/加载更多）
   → 有：逐页采集到末页
   → 无：当前页面已包含全部数据 → 保存为 page1
6. 保存格式: data/position/raw/{id}_{keyword}_page{page}.json
```

**关键行为约束**：
- **不得**在 URL 中写任何 site-specific 的判断逻辑
- **不得**预设某个来源的页面结构
- **必须**通过 browser_snapshot 观察每次交互结果
- **空结果必须注明原因**：`"note": "login_blocked"` / `"note": "no_results"` / `"note": "redirect_to_login"`

### Tier-2+ notice_list 通用采集流程

notice_list 类型来源是公告列表页，无关键词搜索能力。每条公告详情页可能有岗位列表附件下载，或正文直接包含岗位信息。采集方式：

```
0. ★ 采集前下载链接检测（必须执行，仅首次导航到该来源时执行一次）:
   用 robot_scan.py 检测页面是否有可下载数据文件链接:
   a. 运行下载链接检测:
      python scripts/enterprise/robot_scan.py \
        --url "{来源 URL}" \
        --output "data/position/raw/evidence/.robot_check_{source_id}.json" \
        --source-name "{source_name}"
   b. 运行代码门验证:
      python scripts/pipeline/pipeline.py robot-check position <source_id>
      ├─ exit(0) → 有下载链接，继续
      └─ exit(1) → 无下载链接，跳过来源
   c. 如 .robot_check_{source_id}.json 已存在且 collectable=true，跳过此步骤

1. browser_navigate 到 .sources.json 中该来源的 url
2. ★ 执行「导航后自检 checklist」
   ↓
   ★ 城市存证检查:
      evidence/.city_verified_{source_id}.json 存在且 city_code 非空?
      ├─ 是 → 跳过城市选择，直接使用 city_code
      └─ 否 → 执行城市选择子 Agent
   ├─ city_verified → 继续
   └─ city_failed → 展示截图，用户手动选完后继续
   ↓
3. browser_snapshot 观察:
   a. 页面是否正常加载（非登录页/非404）
   b. 列表项结构（链接 + 日期）
4. page = 1
5. loop:
   a. 提取当前页所有公告链接（标题 + 发布日期）
   b. 对于每条公告:
      - 打开公告详情页（新页签或当前页）
      - browser_snapshot 观察页面内容
      - ★ 执行「详情页自检: 岗位信息提取」:
        ① 检测是否有可下载附件（.xlsx/.xls/.pdf/.doc 等链接）
        ② 判断附件是否为岗位列表:
           - 检查附件链接标题/附近文本是否含「岗位」「招聘」「职位」「引进」
            「需求」「计划」「一览表」等岗位相关关键词
           - 匹配 ✅ → 下载附件 → 解析表格提取岗位数据
           - 不匹配 ❌ → 跳过该附件，不从附件提取（避免登记表/简介等垃圾数据）
        ③ 如无岗位附件:
           - 从页面正文中提取岗位信息（文本描述/HTML表格）
      - 提取结果合并到当前页的输出列表
   c. 保存到 data/position/raw/{id}_all_page{page}.json
   d. page += 1
   e. 找翻页控件（"下一页"/页码链接）:
      → 有：翻页，继续循环
      → 无：break
6. 登录检测：如页面跳转到登录页/显示验证码 → ★ 暂停提示用户
   → 不得以"页面不存在""没有找到岗位"等理由自行跳过
```

**附件判断关键词**（用于筛选岗位列表附件，可扩展）：
```
岗位/招聘/职位/引进/需求/计划/一览表/岗位表/职位表/招聘计划/人才需求
```

附件文件名不含上述关键词的视为非岗位附件（如报名登记表、单位简介、承诺书），不下载。

**notice_list 文件名约定**：
- 关键词段固定为 `all`（如 `ccrs_all_page1.json`、`jlgzw_all_page1.json`）
- 即使只有一页也标注 `_page1` 以符合文件名正则
- 空结果同样保存，在 note 注明原因

---

### 智联招聘（zhaopin.com）— SSR 提取模式

**技术特征**：React SSR，数据在 `window.__INITIAL_STATE__` 中，无独立 API 端点。

**采集技术参考（主 AI 采集协议）**：
```
- 数据位置: browser_evaluate 读取 window.__INITIAL_STATE__.positionList
- 字段映射: 见上方智联招聘字段映射表
- 翻页方式: 从当前 URL 提取 base（页面会自动跳转到签名 URL），
            navigate 到 {base}/p{page} 翻页
- 分页总数: document.querySelectorAll('.pagination a') 取最大数字
```

---

### BOSS直聘（zhipin.com）— page.request.post 搜索API采集模式

#### ★ 强制前置：登录探针检测（1 次 POST，非全量，先执行再采集）

BOSS 的登录墙是 API 级别的（无登录态不返薪资字段），页面截图无法检测。
**必须在全量采集前用 1 次 POST 检查薪资数据是否可达，不得先全量采集再验证。**

```
pipeline.py check bole collect  →  如 BOSS 在来源列表中且无 .boss_login_verified 标记，
                                    会 exit(1) 阻塞并要求执行以下探针检测。

探针步骤:
0. ★ 用户明确确认 — 执行探针前必须告知用户：
   "BOSS直聘的采集方式为程序化 API 请求，并非模拟鼠标点击的浏览行为。
   每次翻页都会向 BOSS API 发送 POST 请求获取数据。
   是否继续？"
   用户确认后方可执行探针请求。用户拒绝则跳过 BOSS 来源并记 login_blocked。
1. browser_navigate → 建立 BOSS 会话
2. 选取第一个搜索关键词，用 page.request.post() 发 1 次请求（仅 page=1，不翻页）
3. 检查返回数据:
   - jobList 中的 salaryDesc 字段有值（薪资可达） → 写入标记：
     echo 'ok' > data/.boss_login_verified
     然后重新运行 pipeline.py check bole collect 确认
   - salaryDesc 全部为空（登录墙） → 写入 auth_block：
     touch data/.auth_blocked
     然后告知用户 BOSS 需要登录才能采集，等待用户处理
     **约束：只告知「需要登录」，不得展示 API code / resCount / 样本数 / 薪资状态等技术细节**

※ 只需 1 次 POST × 1 个关键词，不得在此阶段开始全量翻页。
※ 此探针由 pipeline.py check bole collect 强制校验，无标记则阻塞。
```

**核心问题**：
1. 部分平台存在页面跳转行为（如 BOSS 导航后约 5-10 秒跳转 about:blank）
2. 网络请求响应体在跳转后被 Playwright 销毁，`browser_network_request` 返回 "No resource with given identifier found"
3. Python Playwright 脚本同样因响应体销毁而失败

**解决方案**：使用 `browser_run_code_unsafe`（在 Playwright Node.js 沙箱中运行），通过 `page.request.post()` 从页面返回的数据中提取岗位信息。

**采集方式**：导航到 BOSS 搜索页后，通过 Playwright 的 page.request.post() 从页面返回的数据中提取岗位信息。以 **5 页为一批次**，在 `browser_run_code_unsafe` 内部 JS 循环中逐页 POST + `fs.writeFileSync` 直接写盘，批间由主 AI 执行 `rate-tick` 控制突发速率。

#### 搜索列表采集（browser_run_code_unsafe 5页批处理）

以 **5 页为一批**，每批一次 `browser_run_code_unsafe` 调用。JS 内部循环 POST + `require('fs').writeFileSync` 直接写盘，批间由主 AI 执行 `rate-tick`。

```
1. browser_navigate 到 https://www.zhipin.com/web/geek/job?query={keyword}
2. ★ 执行导航后自检 checklist → 检查 about:blank 跳转
   ↓
   ★ 城市存证检查:
      evidence/.city_verified_{source_id}.json 存在且 city_code 非空?
      ├─ 是 → 跳过城市选择，直接使用 city_code
      └─ 否 → 执行城市选择子 Agent
   ├─ city_verified → 继续
   └─ city_failed → 展示截图，用户手动选完后继续
   ↓
3. ★ BOSS 登录探针检测
4. 采集循环（5 页一批，共 N 批）:
   batch = 1:
     browser_run_code_unsafe:
       // 一页一页采，5 页写 5 个文件，不返回数据到 AI
       const page = await browser.newPage();
       await page.goto('https://www.zhipin.com/web/geek/job?query={keyword}', {
         waitUntil: 'networkidle', timeout: 15000
       }).catch(() => {});
       await page.waitForTimeout(2000);
       const fs = require('fs');
       const results = [];
       for (let i = 0; i < 5; i++) {
         const p = (batch-1)*5 + i + 1;
         try {
           const resp = await page.request.post(
             'https://www.zhipin.com/wapi/zpgeek/search/joblist.json',
             {
               headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8' },
               data: `page=${p}&pageSize=15&query=${keyword}&city=${cityCode}`
             }
           );
           const raw = await resp.json();
           if (!raw?.zpData?.jobList?.length) break;
           const jobs = raw.zpData.jobList.map(j => ({
             title: j.jobName, company: j.brandName, salary: j.salaryDesc,
             experience: j.jobExperience, education: j.jobDegree,
             lid: j.lid, jobId: j.jobId, encryptJobId: j.encryptJobId
           }));
           fs.writeFileSync(
             `data/position/raw/boss_${keyword}_page${p}.json`,
             JSON.stringify({
               source: 'boss', keyword, city, page: p,
               totalCount: raw.zpData.resCount || 0,
               totalPages: Math.ceil((raw.zpData.resCount || 0) / 15),
               collect_time: 'YYYY-MM-DD', jobs
             }, null, 2),
             'utf-8'
           );
           results.push({ page: p, count: jobs.length });
           if (!raw.zpData.hasMore) break;
         } catch (e) {
           results.push({ page: p, error: e.message });
         }
       }
       await page.close();
       return results;  // 轻量结果报告，不含岗位数据

     ↓
     AI 检查 results：如有 error 记录，决定是否重试该页
     ↓
     ★ save-verify 代码门禁 — 每批写入后立即校验字段完整性:
       python scripts/pipeline/pipeline.py save-verify boss {keyword}
       ├─ exit(0) → 字段完整，继续
       └─ exit(2) → 字段缺失/文件损坏，STOP 展示报告给用户
     ↓
     rate-tick ← 突发 5 页已达上限，门禁停 ≥3s
     ↓
   batch = 2:
     browser_run_code_unsafe（同上）
     ↓
     rate-tick
     ↓
   ... 直到末页

★ 终止条件（满足任一即止）:
   ─ hasMore === false（API 自然终止）
   ─ 连续 3 页无新 lid
   ─ 安全上限 50 页
   ─ API 返回空 jobList

★ 限速处理协议:
   遇到限速 → 暂停采集，展示当前状态给用户:
   - 已采集页数 / 预期总页数
   - 已采集数据量 / 唯一数据统计
   等待用户决策: (重试 / 跳过该关键词 / 跳过该来源 / 终止)
```

**关键约束**：
- `browser_run_code_unsafe` 在 Playwright MCP 服务器的 Node.js 进程中执行（RCE 环境），`require('fs')` 可用
- 每批复用同一个 `page`，不重复开 tab → 节省导航开销
- try/catch 逐页兜底：单页失败不丢整批，`results` 中记录错误供 AI 判断
- 批间 `rate-tick` 保证突发约束（5 页 ≥ 3s），JS 内不跑 rate-tick
- `page.request.post()` 必须使用 `post(url, {headers, data})` 签名
- `setTimeout` 在 JS 沙箱中不可用，改用 `page.waitForTimeout(ms)`
- `URLSearchParams` 不可用，手动拼接 form-encoded 字符串

---

### 猎聘 / 前程无忧 — API 拦截模式

参考通用 API 拦截流程。导航后执行强制自检 checklist：
- 如遇登录弹窗 → 按「登录/验证码处理协议」暂停，提示用户登录
- 如显示空结果 → browser_snapshot 确认是否因登录导致，登录后刷新重试
- 如仍无结果 → 如实记录"该来源该关键词返回空结果"

**猎聘**：搜索 URL `https://www.liepin.com/zhaopin/?key={keyword}`（城市选择统一通过子 Agent 处理，详见 skills/bole-city-select/SKILL.md）**前程无忧**：搜索 URL `https://we.51job.com/pc/search?keyword={keyword}`（城市选择统一通过子 Agent 处理，详见 skills/bole-city-select/SKILL.md）


---

## ★ 分层人工放行协议（核心变更，必须遵守）

根据来源所属层级，执行不同的放行粒度：

| 层级 | 放行粒度 | 说明 |
|------|---------|------|
| **Tier-1 主流招聘平台** | 单来源放行 | 每个平台完成后单独暂停，等待用户确认 |
| **Tier-2+ searchable** | 整组放行 | 该组下**所有**来源完成后才暂停，组内来源自动切换不询问 |
| **Tier-2+ notice_list** | 整组放行 | 该组下**所有**来源完成后才暂停，组内来源自动切换不询问 |

### Tier-1 — 单来源放行

每个主流平台所有关键词采集完成后，**不得自行写摘要**。必须运行以下命令生成客观报告：

```bash
python scripts/pipeline/collect_report.py --source <id> --config config.yaml
```

**将脚本输出的内容原文展示给用户，不得修改、不得添加、不得删减。** 展示后询问：

```
是否放行到下一来源？(放行 / 重试失败项 / 跳过该来源 / 终止)
```

注意：脚本输出的 `[NO FILE]` 状态表示该关键词在该来源未采集到任何数据文件；`[EMPTY]` 表示采集过但无结果；`[OK]` 表示有数据。

### Tier-2+ 整组放行

该组下**所有来源全部完成**后，**不得自行写摘要**。必须运行以下命令生成客观报告：

```bash
python scripts/pipeline/collect_report.py --config config.yaml
```

**将脚本输出的内容原文展示给用户，不得修改、不得添加、不得删减。** 展示后询问：

```
是否放行到下一组？(放行 / 重试失败项 / 终止)
```

### 执行规则

- Tier-1：每来源展示后必须等待用户输入，不得自行继续
- Tier-2+：每组展示后必须等待用户输入，不得自行继续
- 用户选择「放行」→ 切换到下一来源/组
- 用户选择「重试失败项」→ 重试该来源/组中因验证码/登录/空结果未完成的关键词
- 用户选择「跳过该来源」（仅 Tier-1）→ 跳过当前来源，继续下一来源（用户明确授权，不视为 AI 擅自跳过）
- 用户选择「终止」→ 结束采集，进入采集完成验证

---

### 全量遍历执行结构（★ 每次切换时执行「关键词遍历自检清单」）

```
[Tier-1 主流招聘平台] — 每来源人工放行:

  - 从 .sources.json 读取 Tier-1（id: liepin/51job/zhaopin/lagou/boss，BOSS 放最后）
  - 每个来源按 site-specific 流程（BOSS→page.request.post / 智联→SSR / 其他→API 拦截）
  - 遍历全部 keyword → 逐页翻页到末页
  - ★ 每关键词完成 → 执行自检清单 → 有下一关键词则自动切换
  - ★ 全部关键词完成 → 暂停 → collect_report --source <id> → 展示原文 → 等待用户放行
  - 用户确认放行 → 下一来源

[Tier-2+ searchable 来源] — 整组人工放行:

  - 从 .sources.json 读取 tech_type=searchable 的非 Tier-1 来源
  - 遍历每个来源:
    ├── keyword 1 → 通用 searchable 流程 → 翻页到末页
    │   ★ 执行自检清单 → 有下一关键词
    ├── keyword 2 → 通用 searchable 流程 → 翻页到末页
    │   ★ 执行自检清单 → 有下一关键词
    └── ...全部关键词完成
        ↓ 自动继续下一来源（组内不暂停）
  - ★ 全部 searchable 来源完成 → 暂停 → collect_report --config → 展示原文 → 等待用户放行
  - 用户确认放行 → 进入 notice_list 组

[Tier-2+ notice_list 来源] — 整组人工放行:

  - 从 .sources.json 读取 tech_type=notice_list 的来源
  - 遍历每个来源:
    └── 通用 notice_list 流程 → 翻页列表 + 提取详情
        ↓ 自动继续下一来源（组内不暂停）
  - ★ 全部 notice_list 来源完成 → 暂停 → collect_report --config → 展示原文 → 等待用户放行
  - 用户确认放行 → 进入采集完成验证
```

---

### 数据保存

**★ 核心规则：每个 source × keyword 组合无论结果如何，都必须保存一个 JSON 文件。** 不得因空结果跳过保存，因为 verify 依靠文件名来验证覆盖率。

文件名格式：`{id}_{keyword}_page{N}.json`
- `{id}` 来自 `.sources.json` 中的 `id` 字段（如 `zhaopin`、`boss`、`mohrss`）
- `{keyword}` 为搜索关键词（中文关键词会被 URL 编码但文件名保持原文字符）
- `{N}` 为页码
- notice_list 类型的来源使用 `all` 替代 keyword 段：`{id}_all_page{N}.json`

```
data/position/raw/
├── zhaopin_产品经理_page1.json       ← 有数据
├── zhaopin_AI PM_page1.json         ← 空结果（jobs 为空数组）
├── mohrss_产品经理_page1.json        ← 中国公共招聘网
├── ccrs_all_page1.json              ← notice_list 类型，使用 all
└── ...
```

**★ 空结果原因标注强制要求：** 当 `jobs` 为空数组时，`note` 字段**必须**注明原因，否则 pipeline.py verify 会报错。可选值：

| 原因值 | 适用场景 | 证据要求 |
|--------|---------|:---------:|
| `no_results` | 页面正常加载，但该关键词确实无匹配岗位 | 必须保存证据截图 `evidence/{id}_{keyword}_no_results.png` |
| `login_blocked` | 页面需要登录/验证码，无法获取数据 | 必须保存证据截图 `evidence/{id}_{keyword}.png` |
| `redirect_to_login` | 页面自动跳转到登录页 | 必须保存证据截图 |
| `keyword_not_applicable` | 该来源不支持关键词搜索（已在 note 说明） | — |

**★ `totalCount` / `totalPages` 字段（page 1 必须包含）：** page 1 JSON 必须记录本次采集的预期总量，用于 `keyword-verify` 判断翻页是否完整。来源不同获取方式不同:
- BOSS 直聘: `zpData.resCount` → `totalCount`, `Math.ceil(resCount / 15)` → `totalPages`
- API 拦截: API 响应中的 `total` / `pageSize` → `totalPages = Math.ceil(total / pageSize)`
- SSR 提取: DOM 分页数字 → `totalPages`
- 通用: 页面实际总条数 / 每页条数 → 估算 `totalPages`
- 空结果 / 登录阻塞: `totalCount=0, totalPages=1`

JSON 结构（有数据时）：
```json
{
  "source": "zhaopin.com",
  "keyword": "{关键词}",
  "city": "{城市名}",
  "page": 1,
  "totalCount": 246,
  "totalPages": 17,
  "collect_time": "2026-05-21",
  "jobs": [
    {"title": "", "company": "", "salary": "", "experience": "", "education": ""}
  ]
}
```

JSON 结构（空结果时，必须保存该文件以便 verify 识别"已检索"，且必须注明原因）：
```json
{
  "source": "zhaopin.com",
  "keyword": "{关键词}",
  "city": "{城市名}",
  "page": 1,
  "totalCount": 0,
  "totalPages": 1,
  "collect_time": "2026-05-21",
  "jobs": [],
  "note": "no_results"
}
```

如遇登录/验证码拦截无法采集，同样保存空文件：
```json
{
  "source": "zhaopin.com",
  "keyword": "{关键词}",
  "city": "{城市名}",
  "page": 1,
  "totalCount": 0,
  "totalPages": 1,
  "collect_time": "2026-05-21",
  "jobs": [],
  "note": "login_blocked"
}
```

notice_list 类型保存格式：
```json
{
  "source": "ccrs.changchun.gov.cn",
  "keyword": "all",
  "city": "{城市名}",
  "page": 1,
  "totalCount": 0,
  "totalPages": 1,
  "collect_time": "2026-05-21",
  "jobs": [
    {"title": "", "company": "", "salary": "", "experience": "", "education": ""}
  ]
}
```

#### 浏览器标签管理

- 每个来源使用独立页签
- 不关闭浏览器，登录态跨页签共享
- 采集完成后由用户手动关闭

## ★ 采集完成验证（必须执行，不可跳过）

所有来源和关键词采集完成后，**必须**调用 pipeline.py verify 进行自动化校验：

```bash
python scripts/pipeline/pipeline.py verify bole collect
```

- **exit(0)** → 校验通过，可以继续下一步
- **exit(2)** → **校验失败，AI 不得自行处理！** 必须将校验报告原文展示给用户，等待用户决策：
  - 重试缺失的组合 / 接受现有数据 / 终止管线

**禁止 AI 自行：**
- 补采缺失组合而不询问用户
- 使用 `--skip-verify` 跳过校验
- 直接进入下一管线步骤

验证完成后，输出采集汇总报告（使用 collect_report.py 生成全量报告）。

---

### ★ 补采协议 — Agent 隔离调用

**当用户在采集进行中追加新的搜索关键词时，AI 不得在当前会话中直接执行补采。必须使用 Agent 工具创建子 Agent，上下文隔离确保子 Agent 只知采集协议、不知后续步骤（去重/评分/格式化等）。**

#### 触发条件

以下任一情况触发补采隔离：
- 用户在采集过程中追加新关键词
- 用户要求补采已跳过的来源×关键词组合
- collect 步骤内的关键词列表发生变更（追加/修改）

#### 子 Agent 的 prompt 构造规则

主 AI 构造 Agent 调用时，prompt 中必须包含以下内容，不得遗漏：

```
你是伯乐采集 Worker，你的唯一职责是执行以下采集任务并写文件。
你**不是**管线执行者——你只负责采集，不知道后续步骤的存在。

采集目标:
- 来源ID: {source_id}
- 关键词: {keyword}
- 城市: {city}

采集协议:
{skills/bole-collect/SKILL.md 中对应来源的采集方式 +
对应来源的采集方式（BOSS SSR / API 拦截等）+
数据保存格式（含 totalCount/totalPages）+
限速处理铁律（rate limit 不构成采集完成条件）}

采集完成后返回报告。

限制（不得违反）:
- 不得在当前会话中查看或引用 .bole_context.json 以外的配置
- 不知道也无权关心采集后的步骤
- 遇到登录/验证码/限速无法继续时，如实记录异常并返回报告，不得自行决定"完成"

完成后返回以下格式（纯 JSON，不含额外说明）:
{
  "status": "success" | "partial" | "failed",
  "source": "{source_id}",
  "keyword": "{keyword}",
  "files_written": ["{source_id}_{keyword}_page1.json", ...],
  "total_pages": N,
  "total_count": N,
  "issues": ["描述遇到的异常"]  // 无异常为空数组
}
```

**不得包含在 prompt 中的内容：**
- 去重/评分/格式化的步骤或代码
- 评分权重、config.yaml 评分配置
- 企业管线、资质核验的存在
- "采集完成后数据会用于..." 等用途说明

#### 子 Agent 的权限

子 Agent **允许**的操作：
- Read bole-collect/SKILL.md（采集协议）
- 使用 MCP 浏览器工具（navigate/snapshot/evaluate/network_request/run_code_unsafe）
- Write 文件到 `data/position/raw/`
- 运行 `python scripts/pipeline/pipeline.py keyword-verify`（翻页自检）

子 Agent **禁止**的操作：
- 运行 `pipeline.py complete`、`pipeline.py check`、`pipeline.py verify`
- 运行 `collect_report.py`
- 修改 `.sources.json`、`.bole_context.json`、`config.yaml`
- 向用户发起交互（异常通过返回报告由主 AI 展示）

#### 主 AI 收到报告后的行动

1. 确认报告中的 `files_written` 在 `data/position/raw/` 中实际存在
2. 确认子 Agent 内部 keyword-verify 已通过（`status: "success"` 表示已验证通过）
   - 已通过 → 更新采集计划矩阵，继续「关键词遍历自检清单」
   - 未通过（partial/failed）→ 查看步骤 3
3. 如子 Agent 返回 `status: "partial"` 或 `"failed"` → 向用户展示 issue 内容，询问处理方式
4. 正常继续关键词遍历 → 放行 → 进入去重步骤

---

## Output

所有来源采集完成后运行全量报告：

```bash
python scripts/pipeline/collect_report.py --config config.yaml
```

**将脚本输出原文展示给用户。** 最终数据文件：`data/position/raw/*.json`。

全部来源采集完成后标记：
```bash
python scripts/pipeline/pipeline.py complete bole collect
```
