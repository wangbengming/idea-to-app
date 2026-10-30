# 文件格式规约（机器解析格式的单一权威说明）

本册定义 pm.py 引擎**靠正则/常量解析**的全部文件格式。这些格式同时约束三处，改任何一处必须同步另两处并跑 `python scripts/pm.py selftest`（它做契约核对与全流程回放）：

1. `assets/templates/` 的模板（格式的示范载体）
2. `scripts/pm_data.py` 的契约常量与类型画像（格式的声明）
3. `scripts/pm_engine.py` 的解析正则（格式的执行）

三层代码结构：`pm.py`（入口/CLI 装配）→ `pm_engine.py`（引擎：状态机·门禁·verify·提案合并·自测）→ `pm_data.py`（数据：岗位卡·类型画像·契约常量）。调用方式只有一种：`python scripts/pm.py <子命令>`。

## 00-项目状态.json（状态机）

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | int | 当前 1；未来字段迁移的版本钩子，读取方对未知字段宽容 |
| `name` / `scale` / `type` | str | 应用名 / 编制（small·medium·large·xl）/ 类型（TYPE_PROFILES 的键） |
| `hasUserData` | bool | 决定 verify 是否强制"导出/备份"与 G4 是否强制 07 安全清单 |
| `phase` | str | intake→requirements→design→build→test→iterate；G1/G2/G3 过门自动推进 |
| `iteration` | int | 发版轮次，release 时 +1；门禁记录按轮次判定"本轮已过" |
| `gates` | {G1..G4: {date, iteration}} | 过门记录；`iteration` 等于当前轮才算本轮已过 |
| `blocks` | {M编号: {date, note}} | 积木块"经用户查验通过"的记录（checkpoint 写入） |
| `changes` | [{name, created, state, merged?}] | 变更提案台账；state ∈ open / merged / dropped |

## 01-PRD：验收标准（AC）

```
- [ ] AC-01 内容（带数字阈值）
```
- 解析：`ac_ids()`（`AC-\d+`，按数字排序去重）；G2/G3/G4 的三层追溯都以它为键
- 06 自查行：`- [x] AC-01 已实现：<说明>`（勾选态由 `- \[[xX]\]` 判定）

## 00-项目规划书：积木块

```
### M1 <块名>
- 包含 AC：AC-01, AC-02
```
- 解析：`plan_blocks()`（`^### M\d+`）+ `block_acs()`（`包含 AC：` 行）；checkpoint / G2 覆盖性 / G4 查验完整性依赖
- 必备章节：`PLAN_DOC_SECTIONS`（积木块分解）

## 04-测试报告：bug 行

```
- BUG-001 | 严重|一般|建议 | 标题 | open|fixed
```
- 解析：`- BUG-\d+ | (严重|一般|建议) | … | (open|fixed)`；status 与 G4 的"无 open 严重 bug"依赖
- 类型额外章节：TYPE_PROFILES 的 `g4_extra`（admin=角色权限测试、data=异常输入测试）

## 00-当前功能清单（基线）

```
## 功能条目

### F-001 <功能名>
- 说明：…
- 来源：AC-01 / 提案名

## 变更史
- [YYYY-MM-DD] 初始发布：首次基线，共 N 项功能
- [YYYY-MM-DD] <变更名>：新增 F-x；修改 F-y；移除 F-z
```
- 两节顺序固定（`BASELINE_DOC_SECTIONS`）；条目解析 `parse_entries()`（`^#{3,4} F-\d+`，正文止于下一 F-标题或一二级章节头）
- **只经 release 合并更新，不手改**；`F-1` 与 `F-001` 视为同一编号（`fid_num()` 按数字比较），合并后保留基线侧的规范拼写

## 变更提案（团队文档/变更/<名>/提案.md）

固定四节 + 增量三小节（`PROPOSAL_DOC_SECTIONS`；G3 逐节非空校验）：

```
## 为什么改      ← 用户原话逐字
## 改什么        ← 大白话
## 用户确认      ← 用户点头原话（动工前拿到，G3/release 双重校验）
## 功能增量
### 新增
#### F-009 <功能名>
- 说明：… / - 来源：…
### 修改        ← 整条重写，合并时覆盖基线同编号条目
### 移除        ← `- F-002：<理由>`（理由里别再写别的 F-编号）
## 任务安排      ← 新积木块怎么追加（回改 PRD 重过 G1）
```
- 解析：`parse_delta()`；release 按 新增追加/修改替换/移除删除 机器合并进基线，提案移入 `变更/归档/<日期>-<名>/`

## 交付物 HTML（verify 的机器约定）

- **外部资源**：`src/href` 指向 http(s) 即拦（自包含红线）；本地引用必须真实存在于应用文件夹（防白屏）
- **过时技术**：jQuery 按脚本块粒度拦——块内含 `typeof jQuery`/`window.jQuery` 检测形态整块放行，其余照拦；另有 `$.ajax(`、`XMLHttpRequest`、`document.write(`
- **体感禁令**：`confirm(`/`alert(`/`prompt(` 系统弹窗与内联事件（`onclick=` 等拼在标签或模板字符串里）即拦——先剥 HTML 注释再查（教学注释里的字样不拦）
- **代码风格**：`var` 声明与 `debugger` 语句即拦；`console.log` 类调试输出为提醒级（warns）
- **ES module**：file:// 形态（tool/front/data）拦 `type="module"` 外部引用；admin（localhost）豁免
- **许可证留痕**：出现 `.min.js` 或 `lib/`、`vendor/` 本地组件时，G3 校验 03 含"许可证"字样
- **产品先审留痕**：中型以上（scale ≠ small），G2 校验 `团队文档/派工/pm-审核-设计.md` 存在、G3 校验 `团队文档/派工/pm-审核-技术.md` 存在（phases 阶段 2/3 的先审关卡机器化）

## 03-技术方案 / 07-安全清单（契约章节）

- 03：`G3_DOC_SECTIONS`（选型说明/逻辑架构/用户意见，非空校验）+ 组件来源行
- 07：`G4_DOC_SECTIONS_07`（数据分级/隐私底线/风险与缓解，存在性）+ `G4_07_NONEMPTY`（数据分级非空）

## 同步义务（改完必跑 selftest）

| 你改了 | 必须同步 | 校验方 |
|---|---|---|
| 某类文档模板的章节 | pm_data 契约常量 / TYPE_PROFILES | selftest 契约核对 |
| 门禁新增检查项 | 对应模板章节 + 本册对应小节 | selftest 全流程回放 |
| 派工单要求（DISPATCH） | 角色手册 team-roles.md | 人工比对 |
| 新增项目类型 | TYPE_PROFILES + 模板目录 + 各岗 type_must + SKILL/README 表 | selftest 画像一致性 |
