---
name: bole-city-select
description: 城市选择协议 — Agent 隔离执行，通过 UI 选择目标城市（最多 2 次尝试），自验通过后放行
version: 2.0.0
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - browser_snapshot
  - browser_navigate
  - browser_evaluate
  - browser_click
  - browser_type
  - browser_fill_form
  - browser_select_option
  - browser_hover
  - browser_take_screenshot
---

## 城市选择协议

**调用时机：** 导航到招聘平台的基础 URL 后，**采集开始前**执行。

**核心约束（硬性规则，不得违反）：**
- 禁止在 URL 中添加任何城市编码参数（如 `jl489`、`city=530`、`jobArea=xxx` 等）
- 禁止通过修改 URL 参数来切换城市
- 必须使用页面 UI 城市选择器交互选择城市
- 最多自动尝试 2 次，第 3 次求助用户

---

## ★ Agent 隔离调用协议

城市选择不得由主 AI 直接执行。**必须通过 Agent 工具创建子 Agent**，上下文隔离确保子 Agent 只知城市选择协议、不知采集协议。

### 子 Agent 的 prompt 构造规则

主 AI 构造 Agent 调用时，prompt 必须包含以下内容，不得遗漏：

```
你是伯乐城市选择 Worker，你的唯一职责是确保页面的城市选择器选中了目标城市。
你**不是**采集执行者——你只负责城市选择，不知道后续步骤的存在。

目标城市: {city}

执行步骤：
1. 导航到基础 URL（不带城市参数）
2. browser_evaluate 读取页面当前城市
3. 与目标城市比对：
   - 已匹配 → 跳到步骤 6（自验）
   - 不匹配 → 步骤 4
4. UI 城市选择器选择目标城市（第 1 次）
   → 读页面城市，匹配？→ 步骤 6（自验）
   → 不匹配？→ 步骤 5
5. UI 城市选择器选择目标城市（第 2 次）
   → 读页面城市，匹配？→ 步骤 6（自验）
   → 不匹配？→ 截图 + 提示用户手动选择
     → 等待用户确认选好后 → 步骤 6（自验）

6. ★ 自验（不得跳过）：
   browser_evaluate 读取页面当前城市，与 {city} 比对
   → 匹配 → 确认城市已选对
   → 不匹配 → 返回 city_failed（即使步骤 4/5 认为已匹配，以自验为准）

7. ★ 记录城市编码存证（自验通过后执行，不得跳过）：
   browser_evaluate 从页面提取城市编码（URL 参数/DOM/API 端点中的 cityCode）：
   ```javascript
   // 尝试从 URL 提取城市编码
   const url = window.location.href;
   const match = url.match(/[?&]city=(\d+)/) || url.match(/[?&]jobArea=(\d+)/) || url.match(/dqs=(\d+)/);
   match ? match[1] : '';
   ```
   → 提取到 city_code → 记录到存证文件：
     Write data/position/raw/evidence/.city_verified_{source_id}.json
     {"source_id":"{source_id}","city":"{city}","city_code":"{提取到的编码}","verified_at":"{当前时间}"}
   → 提取不到 city_code → city_code 留空（后续关键词不跳过城市选择）

限制（不得违反）：
- 禁止在 URL 中添加城市参数
- 禁止修改 URL 切换城市
- 禁止在自验不通过时返回 city_verified
- 禁止不记录存证直接返回（自验通过必须写 evidence 文件）
- 不知道也无权关心采集后的步骤

完成后返回以下格式（纯 JSON，不含额外说明）：
{
  "status": "city_verified" | "city_failed",
  "source": "{source_id}",
  "city_observed": "页面实际显示的城市",
  "target_city": "{city}",
  "city_code": "提取到的城市数值编码，提取失败留空",
  "attempts": N,
  "issue": "失败原因"  // city_failed 时必填
}
```

### 主 AI 收到报告后的行动

1. `status: "city_verified"` 且 `city_code` 非空 → 存证文件已由子 Agent 写入，直接开始采集
2. `status: "city_verified"` 但 `city_code` 为空 → 无法提取城市编码，后续关键词仍需走城市选择
3. `status: "city_failed"` → 展示截图给用户，用户手动选好后告知 AI，AI 确认后开始采集
4. 不得在收到 `city_verified` 前开始采集

---

## Process（子 Agent 执行）

### Step 1 — 导航到基础 URL

导航到目标平台的基础 URL（**不带城市参数**）。

### Step 2 — 读取页面当前城市

通过 `browser_evaluate` 读取页面显示的城市名称：

```javascript
// 各平台选择器不同，需按实际情况调整
document.querySelector('.city-selector .selected')?.innerText
```

与目标城市比对。

### Step 3 — 城市匹配判定

```
页面城市 == 目标城市？→ [通过] 进入 Step 6（自验）
页面城市 != 目标城市？→ 进入 Step 4
无法读取城市？→ 进入 Step 4（尝试选择，不猜默认值）
```

### Step 4 — UI 城市选择器交互

**第 1 次尝试：**
1. 点击城市选择器控件（城市下拉/弹窗/列表）
2. 找到目标城市并点击
3. 等待页面刷新/异步加载完成
4. 读页面城市 → 匹配？→ 进入 Step 6。不匹配？→ Step 5

### Step 5 — UI 城市选择器交互

**第 2 次尝试：**
1. 换一种交互方式点击城市选择器
   - 如第 1 次点击的是下拉列表，这次尝试搜索城市输入框
   - 或尝试点击城市切换按钮后选择热门城市
2. 找到目标城市并点击
3. 等待页面刷新/异步加载完成
4. 读页面城市 → 匹配？→ 进入 Step 6。不匹配？→

**第 3 次（不尝试，求助用户）：**
1. `browser_take_screenshot` 截图
2. 提示用户：
   ```
   [{source_id}] 无法自动选择城市 {city}
   已截图保存，请手动在浏览器中选择 {city}，选择后告诉我继续。
   ```
3. 等待用户确认已选好城市
4. 进入 Step 6

### Step 6 — ★ 自验（代码级后验，不得跳过）

`browser_evaluate` 读取页面当前城市，与目标城市比对：

```
页面城市 == 目标城市？→ 返回 city_verified
页面城市 != 目标城市？→ 返回 city_failed
```

自验必须使用 `browser_evaluate` 从 DOM 读取实际城市文本，不得使用 URL 参数推断城市。

---

## 禁止行为清单

| ❌ 禁止 | ✅ 正确做法 |
|---------|------------|
| URL 添加城市参数（`jl489`、`city=530` 等） | 使用基础 URL，通过 UI 选择城市 |
| 修改 URL 参数切换城市 | 点击页面城市选择器 |
| 第 1 次失败后直接求助用户 | 至少尝试 2 次 UI 选择 |
| 无法读取城市时猜默认值 | 进入 Step 4 尝试选择 |
| 自验不通过时返回 city_verified | 如实返回 city_failed 及截图 |
| 自验通过后不写 evidence 存证 | 必须写 `.city_verified_{source_id}.json`，供后续关键词复用 |
