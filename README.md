# idea-to-app · 从想法到应用

> 面向零编程经验用户的工程化 Agent Skill：把一句模糊的想法，一步步变成**双击就能用**的应用。
>
> An engineering-grade agent skill that turns a vague idea from a non-programmer into a working, double-click-to-use application — through a simulated big-tech dev team with machine-enforced quality gates.

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

## 它是怎么工作的

装好这个技能后，用户开个新对话直接说想法即可。技能会以"虚拟开发团队项目经理"的身份接管整个流程：

```
服务边界判定 → 复述确认 + 归类（tool/data/admin/front）
   ├─ 需求清晰 → 需求+积木块规划 ─G1→ 设计 ─G2→ 拼块+逐块用户查验 ─G3→ 安全+测试 ─G4→ release
   └─ 说不清 → 探索模式：痛点翻译成方向故事 → 样品让用户挑 → 回主流程
竣工后（可选）：部署建议与带教；迭代期：变更提案制（propose → 用户确认 → release 合并进功能清单）
```

四条设计原则：**判断归模型、机械归脚本**（`pm.py` 机器门禁，不靠模型自觉）；**对用户说人话**（术语禁令只约束用户边界，内部文档专业第一）；**门禁以脚本输出为准**（机器查格式与追溯，人和用户判断质量真伪）；**"现在真相"单一来源**（《00-当前功能清单》只经 release 合并更新）。

完整的流程手册、角色边界、设计与技术规则都在技能内部（`SKILL.md` + `references/` 十册），随对话按需加载——本 README 只讲安装与使用。子代理的派工单会自动附上该岗方法手册的绝对路径与交稿自查三问，并要求调研附来源、开发交稿前真实冒烟。

## 安装

前置：支持 Agent Skills（`SKILL.md`）格式的 agent 环境（如 ZCode）；Python 3.10+ 可选——`pm.py` 为纯标准库，无 Python 时技能内置手动兜底流程。

```bash
# 克隆到用户级技能目录（所有项目可用）
git clone https://github.com/<你的用户名>/idea-to-app.git ~/.agents/skills/idea-to-app
```

Windows 用户也可直接下载 ZIP 解压到 `C:\Users\<你>\.agents\skills\idea-to-app\`。

## 快速开始

装好后开个新对话，直接像聊天一样说：

```
我不会编程，想给我妈做个记买菜账的小工具，她不识几个字，最好一点就能记
```

你会经历：它复述确认 → 给你带选项的问题（或探索模式的方向故事/样品）→ 大白话蓝图确认 → 它开始做并自报进度 → 桌面出现 `买菜记账.html` 和《使用说明.txt》。

其他类型的项目直接说需求即可，它会自动归类：

```
帮我做个小程序，把文件夹里几百张照片按拍摄日期自动改名整理
（→ 数据脚本：交付 .py + 启动.bat，原始照片不会被改动）

我们店三四个人要用一个系统记每天的销售，各有各的账号，只有我能删东西改价格
（→ 管理后台：双击启动、浏览器自动打开、账号登录、角色权限）

我想给我的花店做个官网，顾客手机上看了愿意打电话订花
（→ 商用前台：多页网站 + 设计令牌 + 手机自适应）
```

想继续之前的项目，带上路径说一句即可：

```
用 idea-to-app 继续做 C:\Users\<你>\Desktop\买菜记账，先看看进度
```

## pm.py 命令

```bash
python "<技能目录>/scripts/pm.py" <子命令>
```

| 命令 | 作用 |
|---|---|
| `init <应用名> [--type tool\|data\|admin\|front] [--scale small\|medium\|large\|xl] [--no-data]` | 建项目：目录结构 + 按类型选模板 + 状态机 |
| `status` | 查看类型/阶段/迭代/评审门/bug/变更提案（接手项目第一步） |
| `scaffold <00~07> [--force]` | 按编号落文档模板 |
| `dispatch pm\|design\|tl\|dev\|fe\|be\|sec\|qa` | 生成岗位派工单（自动携带职责边界、退回规则与类型增量）并留痕 |
| `probe <样品.html> --label "…"` | 给样品打"仅方向参考"横幅并归档到 `探索/` |
| `checkpoint M1 --note "…"` | 记录一块积木"经用户查验通过"（先机器校验该块 AC 已全部打勾） |
| `propose <变更名> [--drop]` | 立/放弃一份变更提案（迭代期功能变化：用户原话/大白话/确认原话/功能增量） |
| `gate G1\|G2\|G3\|G4` | 评审门机器校验（AC 追溯、严重 bug、类型化章节；G4 查全部块经用户查验 + 安全清单 + 功能清单在案） |
| `verify` | 交付物静态检查，按类型分派：网页自包含（含本地引用完整性、ESM/过时技术拦截）/ 脚本双击件与编码 / 后台密码加密·登录·备份 |
| `release --note "…"` | 发版（要求本轮已过 G3，中型以上另须 G4），把变更增量机器合并进《00-当前功能清单》并归档提案 |
| `selftest` | 自测：门禁↔模板契约核对 + 全流程回放 + 行为专项（改模板/门禁/数据后必跑；CI 双系统自动跑） |

## 项目结构

```
idea-to-app/
├── SKILL.md                  # 路由层：服务边界 + 四条铁律 + 命令表 + 按需加载地图 + 阶段地图
├── scripts/                  # 三层结构（纯标准库；调用方式不变：python scripts/pm.py <子命令>）
│   ├── pm.py                 # 入口：CLI 装配
│   ├── pm_engine.py          # 引擎：状态机·四道门·verify·提案合并·selftest 自测（四门各自独立函数）
│   └── pm_data.py            # 数据：岗位派工卡·类型画像（TYPE_PROFILES 一表收拢）·门禁↔模板契约常量
├── assets/
│   ├── app-template.html     # 网页样板：自包含/中文/大按钮/备份恢复骨架
│   ├── admin-template.py     # 后台骨架（方案 E）：登录/会话/角色权限/增删改查/备份，纯标准库
│   └── templates/            # 文档模板：00-规划书 + 00-当前功能清单 + 变更提案 + 01~07 + data/admin/front 类型差异版
├── references/               # 十一册按需加载手册
│   ├── phases.md             # 流程编排：五阶段 + 探索模式 + 持续迭代（变更提案制）
│   ├── project-types.md      # 四类项目手册：归类判定/阶段差异/AC 写法/红线/常见坑
│   ├── replica-playbook.md   # 对标复刻手册："做个像剪映/像XX的"——标杆拆解/场景裁剪/重计算能力速查/量化验收
│   ├── team-roles.md         # 职责边界矩阵 + 角色卡（含 fe/be） + 退回机制 + 派工模板 + 调度纪律
│   ├── tech-recipes.md       # 交付形态 A/B/C/E + 现代技术栈基线 + 开源优先 + 能力边界/性能预算
│   ├── design-craft.md       # 设计工艺册：五步法/风格族谱/五套令牌/区块模式库
│   ├── design-baseline.md    # 设计基线册：防 AI 味禁令清单 + 三证明审计法
│   ├── execution-craft.md    # 执行纪律：数字阈值/虚词黑名单/三人格对抗/操作成本预算
│   ├── phrasebook.md         # 各阶段话术示例（含探索/查验/部署/拒绝）
│   ├── file-formats.md       # 文件格式规约：机器解析格式的单一权威（AC/积木块/F-编号/提案/状态机 schema）+ 同步义务表
│   └── deploy-recipes.md     # 阶段 5 部署手册：按类型的部署选项/代价/上线检查清单
└── .github/workflows/selftest.yml  # CI：push 时 ubuntu+windows 双矩阵自动跑 selftest
```

## 适用与限制

- 🛡️ **服务边界**：只帮合法正当用途（自用工具、自家生意、有权处理的数据）；破解、扒隐私、钓鱼、恶意软件、批量骚扰等一律婉拒并给合法替代方向——这条优先于一切流程
- ✅ 单机工具 / 数据脚本 / 管理后台（本地服务形态，同一 WiFi 可访问）/ 商用级前台
- ⛔ 刻意第一版不做：公网部署、云账号、跨互联网同步（前台"发布到网上"是正常迭代项，到时带用户操作）
- 管理后台形态限本机/可信内网（无 HTTPS/CSRF 防护）；浏览器双击场景做不了系统通知、摄像头、推送、定位（技术方案阶段核对能力边界并给替代形态）

## License

[MIT](LICENSE)
