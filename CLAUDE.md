# 伯乐 (bole-skill) — Claude Code 原生 Skill 架构

## 当前阶段

Phase 48.13 — Agent 隔离采集：城市选择 + 翻页采集双子 Agent，主 AI 不直接操作浏览器采集

## ★ 角色声明 — 管线流程执行者

我在此项目中的角色是**管线流程执行者**，不是代码优化者、架构师或问题解决者。我的唯一职责是按 SKILL 文件规定的步骤顺序逐条执行采集管线。任何"这样更高效""这样也可以""数据量已足够"等主观判断都不应取代对 SKILL 文件硬性规则的遵守。当我的想法与 SKILL 文件冲突时，以 SKILL 文件为准。

## ★ 自检协议强制规则（硬性指令，违反即违规）

本会话中，所有 SKILL 文件标注 `★` / `必须` / `禁止` 的规则为**硬性指令**，等同于 pipeline.py 的步骤顺序约束，我无权自行评估是否执行。

### 核心禁令（不得以任何理由违反）

```
1. **城市选择：每个来源首次通过 UI 城市选择器交互选择 config.city，城市选择必须通过子 Agent（skills/bole-city-select/SKILL.md）隔离执行。同来源后续关键词复用已记录的 `.city_verified_{source_id}.json` 城市编码存证，不再重复 UI 选择。主 AI 不得自行处理城市选择或 URL 硬编码。每次管线 `reset` 清除所有城市存证，下一轮从头走 UI 选择。**
2. 每次 browser_navigate 后必须执行「导航后自检 checklist」— 含登录检测（城市检查已由城市选择子 Agent 在采集前完成）
3. 遇到登录/验证码/扫码必须暂停并向用户提示 — 不得自行跳过来源
4. 每完成一个关键词必须执行「关键词遍历自检清单」— 对照矩阵检查下一关键词
5. 每完成一个主流来源（BOSS/猎聘/前程无忧/智联/拉勾）必须暂停等用户确认放行，写入 .source_{id}_confirmed 标记 — pipeline.py verify 校验此标记，缺失则 exit(2) STOP
6. 采集未全量完成（所有来源 × 所有关键词）不得进入去重/评分/输出步骤
7. **pipeline.py verify 失败（exit code 2）时，AI 必须 STOP 并展示校验报告给用户，不得自行重试、不得 --skip-verify、不得进入下一步**
8. **空结果（jobs=[]）必须注明原因不得留空** — login_blocked / no_results / redirect_to_login，pipeline.py verify 会校验
9. **遇到需要登录的页面不得以"页面不存在""没有岗位"等理由自行跳过** — 必须暂停提示用户，如实记录 login_blocked
10. **BOSS 采集前必须执行登录探针检测（1 POST），不得直接全量采集再验证** — pipeline.py check bole collect 强制校验 .boss_login_verified 标记，无标记则阻塞
11. **非 BOSS 主流平台（猎聘/前程无忧/智联/拉勾）导航后必须执行自检留痕** — 保存 evidence/{source_id}_check.json 着陆截图和自检记录（含 login_detected），pipeline.py verify collect 校验缺失则 exit(2) STOP
12. **.restart_required 标记存在时所有 pipeline.py 命令强制 exit(2)** — AI 必须 STOP 并提示用户重启。用户告知已重启后，AI 执行 rm data/.restart_required 清除标记继续管线。
13. **用户表达求职意图（含城市+岗位关键词）时，必须启动 bole MCP 采集管线，禁止以 WebSearch 替代** — 不论句式如何（"帮我在XX看看XX""推荐XX的XX工作""整理XX的XX职位""我想找XX的XX"等），只要语义中包含目标城市和岗位/职位，即强制路由到 bole 管线。城市或岗位不明确时追问用户确认，不得自行 WebSearch。
14. **不得自行编写 Python/Node.js 脚本替代管线流程进行数据采集、保存或处理** — 数据采集必须通过 MCP 浏览器工具（browser_navigate / browser_evaluate / browser_run_code_unsafe / browser_network_request）获取。保存方式三选一：(a) `Write` 工具，(b) `browser_evaluate(+filename)` 原生写盘（SSR 提取模式），(c) `browser_run_code_unsafe` 内 `require('fs').writeFileSync`（API POST 模式 5 页批处理）。数据处理必须调用 scripts/ 下的现有管线脚本（merge_raw.py / dedup.py / score.py / format.py 等）。不得自行写脚本从本地文件读取/转换/保存数据以绕过管线步骤。pipeline.py verify 会校验数据的 MCP 来源标记。
15. **翻页采集由主 AI 编排，按采集协议执行（API POST 模式 5 页一批处理，批间 `rate-tick`；API 拦截/SSR 提取模式逐页循环）。keyword-verify 在每关键词采集完成后由主 AI 执行。**
16. **采集过程中遇到限速/异常中断 → 暂停采集，向用户展示当前采集状态，等待用户决策** — 展示内容含：已采集页数、预期总页数、已采集数据量、唯一数据统计、目标岗位全量唯一数据占比。用户可选择重试/跳过该关键词/跳过该来源/终止。keyword-verify exit(2) 时不得以"有 N 页数据已足够"等理由跳过。
17. **采集步骤内用户追加关键词时，必须通过 Agent 工具创建子 Agent 执行补采，不得在当前会话中直接采集** — 子 Agent 只收到采集协议（不含后续步骤信息），主 AI 收到返回报告后通过 keyword-verify 验证完整性。子 Agent 不得运行 pipeline.py complete/check/verify、不得修改配置、不得向用户发起交互。
18. **每个来源全部关键词采集完成后必须运行 `pipeline.py auth-scan <source_id>` 代码检查** — 这是代码级登录检测门，不依赖 AI 自检。exit(1) 时管道自动冻结，AI 必须 STOP 并展示报告给用户。exit(0) 时方可进入放行流程。**不得跳过此步骤、不得篡改数据文件以绕过检查。**
```

### 执行规则

- 我不得以"推进度"、"数据量已足够"、"该来源卡住了"、"该关键词无结果"等主观判断替代上述硬性规则
- 每完成一项检查在回复中用 `[✔]` 标记，未标记视为未执行
- **采集摘要必须由 `collect_report.py` 脚本生成，我不得自行撰写或篡改脚本输出**
- **pipeline.py 的 exit code 2（校验失败）必须 STOP，不得自行处理后继续**
- **`--skip-verify` 必须获得用户明确确认后方可使用，不得 AI 自行决定**
- **每次关键词采集完成后必须运行 `pipeline.py keyword-verify <source> <keyword>` 确认翻页完整性，未通过不得切换到下一关键词**
- **keyword-verify exit(2) 时不得以"数据量已足够""已有 N 页数据"跳过 — 必须补齐缺页**
- **每个来源完成后必须运行 `pipeline.py auth-scan <source_id>`，不得跳过；exit(1) 时管道冻结，AI 必须 STOP**
- **不得修改/伪造 JSON 文件中的 `note` 字段值 — 采集时写入的内容必须原样保留，`pipeline.py _check_protocol_compliance` 会扫描所有 note 值**
- **标记 `no_results` 时必须同时保存证据截图 `evidence/{id}_{keyword}_no_results.png` — pipeline.py verify collect 会校验截图是否存在，缺失则 exit(2) STOP**
- **不同关键词必须产出不同数据 — pipeline.py 协议合规门会扫描同来源不同关键词的 page1 数据是否相同，相同则判定搜索未生效并阻塞管线**
- 违反上述任一规则，用户有权终止会话并重置管线

## MCP Playwright 安装

> **⚠️ 环境限制**：浏览器自动采集依赖 Playwright MCP，**Claude Code CLI / VS Code 扩展均可支持**。推荐使用 CLI（终端）运行伯乐——扩展自动压缩阈值更低（剩余 ~35% 即压缩），长采集管线中协议细节丢失风险更高。如 MCP 不可用，尝试重启 Claude Code 会话。
> 验证方法：在 Claude Code 中执行 `browser_snapshot`，正常返回截图即环境就绪。
> 详见 README 中的[运行环境要求](../README.md#运行环境要求)。

项目提供 `.mcp.json`，Playwright MCP 自动加载。如需手动编辑 `~/.claude.json`：

```json
"playwright": {
  "command": "npx",
  "args": [
    "-y", "@playwright/mcp@latest",
    "--user-data-dir", ".claude/browser_profile",
    "--viewport-size", "1280x720",
    "--shared-browser-context",
    "--browser", "chrome"
  ]
}
```

## 启动流程

1. `CLAUDE.md` — 本文件
2. `config.yaml` — 算法参数（评分权重/薪资档位等，无需用户编辑）
3. `.claude/skills/` — 16 个原生 Skill

## 安装方式

```bash
# Git clone
git clone <repo-url>
cd bole-skill
pip install -r requirements.txt

# 或 npx 一键安装
npx skills add bole-skill
```

## 架构

```
├── .claude/skills/                   ← 15 个原生 Skill（3 管线 + 3 桥梁 + 1 子 Agent，仅主流平台）
│   ├── bole/SKILL.md                  ← 岗位管线主编排
│   ├── bole-collect/SKILL.md          ← 采集
│   ├── bole-city-select/SKILL.md      ← ★ 子 Agent：城市选择
│   ├── bole-dedup/SKILL.md            ← 去重合并
│   ├── bole-score/SKILL.md            ← 五维评分 + 标签
│   ├── bole-format/SKILL.md           ← 知识库导入优化
│   ├── bole-enrich/SKILL.md           ← ★ 桥梁：企业数据匹配富化
│   ├── bole-enrich-fill/SKILL.md      ← ★ 桥梁：全网检索补充企业信息
│   ├── bole-enrich-format/SKILL.md    ← 桥梁：富化后格式化
│   ├── bole-enterprise/SKILL.md       ← 企业管线主编排
│   ├── bole-enterprise-sources/SKILL.md      ← 企业资质来源发现
│   ├── bole-enterprise-collect/SKILL.md      ← 政府公示网站采集
│   ├── bole-enterprise-clean/SKILL.md        ← 企业名录清洗去重
│   ├── bole-enterprise-score/SKILL.md        ← 企业评分排序
│   └── bole-enterprise-format/SKILL.md       ← 企业知识库导入优化
│
└── scripts/                           ← Python CLI 脚本（按管线分组）
    ├── pipeline/                      ← 管线状态管理 + 校验
    │   ├── pipeline.py                ← ★ check/verify/complete/reset
    │   └── collect_report.py          ← ★ 采集覆盖率客观报告
    ├── job/                           ← 岗位管线（采集→去重→评分→格式化）
    │   ├── dedup.py                   ← 多来源去重合并
    │   ├── score.py                   ← 薪资标准化 + 四维评分
    │   ├── format.py                  ← 岗位格式化输出（CSV + BOM + 报告）
    │   ├── merge_raw.py               ← JSON 合并为 CSV
    │   ├── report.py                  ← 数据报告生成器（7 维度）
    │   └── robots_check.py            ← robots.txt 合规检测
    ├── enterprise/                    ← 企业管线（采集→清洗→评分→格式化）
    │   ├── enterprise_clean.py        ← 企业名称标准化 + 去重
    │   ├── enterprise_score.py        ← 企业评分排序
    │   ├── enterprise_format.py       ← 企业格式化输出
    │   ├── robot_scan.py              ← 下载链接检测器
    │   └── pdf_extract.py             ← PDF 四层递进提取
    ├── enrich/                        ← 富化桥梁（匹配→补充→过滤）
    │   ├── enrich.py                  ← 三阶段公司名匹配 + 字段合并
    │   ├── enrich_fill.py             ← ★ 全网检索补充企业信息
    │   ├── enrich_format.py           ← 富化后格式化
    │   └── final_filter.py            ← ★ 基于企业数据过滤低质岗位
    └── install/                       ← 安装工具
        └── configure_mcp.py           ← Playwright MCP 自动配置
```

## 管线步骤强制校验

```bash
python scripts/pipeline/pipeline.py status
python scripts/pipeline/pipeline.py check <pipeline> <step>
python scripts/pipeline/pipeline.py verify <pipeline> <step>
python scripts/pipeline/pipeline.py complete <pipeline> <step>
python scripts/pipeline/pipeline.py reset [pipeline]
```

校验失败 exit code 2，AI 必须 STOP 展示报告。

## 使用方式

```
/bole                    # 岗位全流程
/bole-score              # 单独评分
/bole-dedup              # 单独去重
/bole-enterprise         # 企业管线
/bole-enrich             # 企业数据富化
/bole-enrich-fill        # 全网检索补充企业信息
```

## Real 模式 MCP 工作流

根据平台技术架构分三种采集模式（详见 `bole-collect/SKILL.md`）：

### 模式 A：API 拦截（猎聘/前程无忧）
```
navigate → snapshot → network_requests → 筛选 API → 提取 JSON → 翻页
```

### 模式 B：SSR 内嵌数据提取（智联招聘）
```
navigate → evaluate window.__INITIAL_STATE__ → 字段映射 → 写盘
```

### 模式 C：Node.js 沙箱 POST（BOSS直聘）
```
navigate → snapshot → run_code_unsafe fetch POST → 解析 → 翻页
```

## 评分体系

| 维度 | 权重 | 说明 |
|------|:----:|------|
| 薪资 | ×10 | 8 级评分（30k=7 分，20k=6 分，>30k=8 分） |
| 经验 | ×4 | 3-5 年最佳=5 |
| 学历 | ×3 | 本科及以上=5 |
| 岗位相关度 | ×5 | 关键词匹配 |
| **企业质量加分** | — | 专精特新小巨人/单项冠军+10，独角兽+8，专精特新/高企/瞪羚+6，雏鹰+4，科技型中小+2 |

总分 140（不含企业加分），≥60 分标记"需深挖"。

## 当前管线状态

| 指标 | 状态 |
|------|:----:|
| 步骤强制校验 | pipeline.py + check/verify/complete |
| 校验覆盖 | 3 管线 15+ 步骤全部有 verify 函数 |
| 采集客观摘要 | collect_report.py 基于实际文件生成 |
| 来源发现输出 | .sources.json（16 来源，6 大类别）|
| 三管线 Skill | 16 个原生 Skill + 18 个 CLI 脚本 |
| MCP 方式 | .mcp.json 项目级 / ~/.claude.json 全局 |
| 数据目录 | data/（.gitignore 排除） |
