#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
idea-to-app 项目工具箱（项目经理的工程化执行器）

将 skill 的流程固化为状态机 + 机器校验：
  init        初始化项目（目录结构、模板、状态文件；--type 定项目类型）
  status      查看项目状态（类型/阶段/积木块/评审门/bug）
  scaffold    按编号落一份文档模板到团队文档（优先用项目类型的模板）
  dispatch    生成岗位派工单（写入 团队文档/派工/，留审计痕迹；xl 规模含 fe/be 岗）
  probe       给样品页打"仅方向参考"横幅并归档到 探索/
  verify      交付物静态检查（按类型分派：网页自包含 / 脚本双击件 / 后台安全底线）
  gate        评审门机器校验（G1 需求 / G2 设计+规划 / G3 提测 / G4 发布）
  checkpoint  记录一块积木"经用户查验通过"（先机器校验该块 AC 已全部打勾）
  propose     立一份变更提案（迭代期功能变化的动工凭证：用户原话/大白话/确认原话/功能增量）
  release     发版（要求当前迭代 G3 已通过 + 全部积木块经用户查验），写入发布记录；
              把变更提案的功能增量机器合并进 00-当前功能清单 并归档提案

项目类型（init --type，存于状态文件）：
  tool   单机工具（默认，单文件/多页网页）
  data   数据脚本（批量处理/报表/定时任务，py + 启动.bat）
  admin  管理后台（本地服务 + SQLite，登录/角色/备份）
  front  商用前台（多页商用级网站，设计令牌/响应式）

命令一律通过 Bash 执行：python "<本技能目录>/scripts/pm.py" <子命令> ...
用 --dir 指定应用文件夹；缺省时从当前目录向上查找 团队文档/00-项目状态.json。
"""
import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_ROOT / "assets" / "templates"

DOC_FILES = {
    "00": "00-项目规划书.md",
    "01": "01-需求文档-PRD.md",
    "02": "02-设计方案.md",
    "03": "03-技术方案.md",
    "04": "04-测试报告.md",
    "05": "05-发布记录.md",
    "06": "06-开发自查清单.md",
    "07": "07-安全与隐私清单.md",
}

PHASE_AFTER_GATE = {"G1": "design", "G2": "build", "G3": "test"}
PHASE_LABEL = {
    "intake": "阶段0-需求了解",
    "requirements": "阶段1-需求整理",
    "design": "阶段2-设计",
    "build": "阶段3-开发",
    "test": "阶段4-测试发布",
    "iterate": "持续迭代",
}

# 项目类型：决定模板集、派工增量、门禁增量与 verify 分支（详见 references/project-types.md）
TYPE_LABEL = {"tool": "单机工具", "data": "数据脚本", "admin": "管理后台", "front": "商用前台"}

# 各类型文档必须出现的章节（模板与门禁保持一致；改模板必须同步改这里，反之亦然）
G1_HEADERS = {
    "tool": ["产品定义", "用户画像", "用户故事", "用户旅程", "同类调研", "必须有", "以后再说", "不做清单", "待确认"],
    "data": ["产品定义", "用户画像", "用户故事", "用户旅程", "同类调研", "输入与输出", "数据样例", "必须有", "以后再说", "不做清单", "待确认"],
    "admin": ["产品定义", "用户画像", "用户故事", "用户旅程", "同类调研", "实体与角色", "必须有", "以后再说", "不做清单", "待确认"],
    "front": ["产品定义", "用户画像", "用户故事", "用户旅程", "同类调研", "页面结构", "必须有", "以后再说", "不做清单", "待确认"],
}
G2_HEADERS = {
    "tool": ["风格定位", "页面清单", "交互", "视觉", "设计令牌", "趋势侦察", "体验自查", "基线自查"],
    "data": ["处理流程", "输入输出样例", "异常与提示", "输出样式"],
    "admin": ["风格定位", "页面清单", "交互", "视觉", "设计令牌", "趋势侦察", "体验自查", "基线自查", "权限呈现"],
    "front": ["风格定位", "页面清单", "交互", "视觉", "设计令牌", "趋势侦察", "体验自查", "基线自查", "响应式"],
}
# G4 对测试报告的额外章节要求
G4_EXTRA_HEADERS = {"admin": ["角色权限测试"], "data": ["异常输入测试"]}

# 各岗位派工单骨架（判断性内容由项目经理补齐后再派给子代理）
# type_must：按项目类型追加的增量要求（key = init --type，见 references/project-types.md）
DISPATCH = {
    "pm": {
        "title": "产品部·产品经理",
        "docs": [],
        "output": "团队文档/01-需求文档-PRD.md（按模板填写，验收标准用固定格式 - [ ] AC-编号 内容）",
        "must": [
            "用户画像（设备/时段与环境/操作能力/心理状态）、用户旅程与核心动作（应用\"的一件事\"，10 秒内完成）",
            "动笔前过 execution-craft.md 第一节产品五问（一问一句答案写进 PRD「待确认」或正文）；显式写出 3 条最要命的隐含假设（设备/输入/能力），红线问题触发即停——核心动说说不清、AC 写不出数字就不许定稿",
            "同类调研：用 WebSearch 查 2~3 个同类工具，提炼常见做法（借鉴）与用户吐槽（避坑）各至少一条",
            "功能三堆清单（必须有/锦上添花/以后再说），\"必须有\"按实现顺序排序，第 1 条 = 最小可用骨架",
            "每条\"必须有\"配可勾选验收标准：一律带数字阈值（步数/秒数/个数/像素），禁用 execution-craft.md 第二节虚词黑名单（体验好/流畅/简便/美观…）",
            "不做清单、待确认清单、用户原话逐字附录",
        ],
        "type_must": {
            "data": [
                "输入与输出：输入文件从哪来/什么格式什么编码/谁提供；输出成什么、给谁看、多久跑一次",
                "数据样例：贴近真实的输入样例与期望输出样例（脱敏），直接写进 PRD 供设计与测试引用",
            ],
            "admin": [
                "实体与角色：要管理哪些资料（实体/字段/关系）；有哪几类人用，每类能看什么、能改什么（权限矩阵逐格确认）",
            ],
            "front": [
                "页面结构：页面树、每页职责、内容来源（文字图片谁提供、多久更新一次）",
            ],
        },
        "bounds": [
            "不做技术选型、不定视觉/交互方案、不写代码（产品定\"做什么\"，怎么做归技术部）",
            "不替用户做决定，拿不准一律进\"待确认\"",
            "不直接面向用户，对用户的一切承诺由项目经理传达",
        ],
    },
    "design": {
        "title": "设计部·设计师（交互+视觉合一岗）",
        "docs": ["00", "01"],
        "output": "团队文档/02-设计方案.md",
        "must": [
            "按 00-项目规划书的积木块组织交互描述（每块一个小节、标注包含的 AC 编号），便于逐块交付查验",
            "风格定位：动笔前通读 references/design-craft.md（商业级设计工艺手册），按其五步法走——3 个气质形容词 + 从风格族谱选族 + 从行业反模式表认领至少 2 条；ui-ux-pro-max 技能可用时先跑 --design-system 拿专业库推荐（手册第八节），记录采纳情况",
            "设计令牌：照 design-craft.md 第三步把五套令牌（色彩 16 语义位/字体/间距密度/深度阶梯/动效预算）落成 :root 变量表；灰阶随主色染色、每对前景背景对比度≥4.5:1、全站只引用令牌",
            "趋势侦察：用 WebSearch 查当前主流设计风格与同类应用界面，记录\"查到什么/采纳什么手法/为何适合本项目\"，并保证素材原创合规",
            "基线自查：动笔前通读 references/design-baseline.md，把各维取值落进 02「基线自查」节（克制/动效/排版/布局/交互/可访问性/元数据），逐维写具体值或\"不适用\"；把渐变横幅、发光、紫色系、\"什么都在动\"这类 AI 味手法当现代感是最常见的坑",
            "交互：页面清单（每页注明所用布局模式，见 craft 第四节）、每页文字线框、关键交互（点X后发生什么，注明 100ms 内视觉反馈）、空状态/出错状态、危险操作二次确认；细节密度按 craft 第五节（组件五状态、数据四境况）",
            "操作成本预算表（execution-craft.md 第四节，落进「交互」节）：高频动作逐个列点击次数/输入字段数/默认值，超预算的动作先改设计再画线框；每个可填字段给\"90% 场景默认值\"",
            "视觉：依据风格定位写气质与依据（具体值全在「设计令牌」节）；图标单家族同线粗、禁 emoji 当图标、一屏一个主按钮；按画像适配（中老年→正文≥18px、按钮≥48px）",
            "体验自查：即时反馈/错误预防/可达性（触摸目标≥44px）/一致性（阴影只用阶梯值、图标单家族）/行业反模式逐条核对/微文案/核心动作≤3 步，逐项写\"过/不过\"",
            "覆盖 PRD 中每一条 AC 编号（G2 将做追溯校验）",
        ],
        "type_must": {
            "data": [
                "处理流程：从输入到输出分几步、每步做什么（文字流程，代替页面清单；本项目无页面）",
                "输入输出样例：字面展示\"输入长这样 → 输出长这样\"的对照",
                "异常与提示：空文件/编码不对/缺列/超大文件时脚本怎么表现、中文提示怎么写",
                "输出样式：结果文件/报表的排版也算视觉活，给出具体样式（列宽/标题/汇总行等）",
            ],
            "admin": [
                "后台三件套：导航框架 + 列表页（搜索/筛选/分页/批量操作）+ 表单页（校验与错误提示）",
                "权限呈现：不同角色登录后，导航与按钮的差异逐条列出（AC 编号引用）",
            ],
            "front": [
                "设计令牌在基础要求之上按宽松档间距与所选风格族细化（如衬线标题栈、表现档动效），区块间隔用大间距表达章节感",
                "响应式：断点与手机端布局调整逐页写清（导航怎么收、多列怎么变单列）",
            ],
        },
        "bounds": [
            "不增删需求：PRD 之外的想法写进\"建议\"节交项目经理，不落进设计",
            "不做技术选型，产出不含实现细节（不规定用什么库、数据怎么存）",
            "素材合规：参考风格手法但不照搬产品，只用自绘 SVG 或宽松许可证（MIT/CC0）素材内联，不用品牌 logo、不引外部字体文件、禁一切外链",
            "基线约束（references/design-baseline.md 的【禁】【必】条目）不得违反；确需例外必须在 02「基线自查」写明理由",
            "不直接面向用户",
        ],
    },
    "tl": {
        "title": "技术部·技术负责人/架构师",
        "docs": ["01", "02"],
        "output": "团队文档/03-技术方案.md",
        "must": [
            "架构与交付形态（tech-recipes 方案A/B/C/E）+ 为什么它是\"从想用到用上步骤最少\"的",
            "现代技术栈基线（tech-recipes.md 硬约束）：技术栈必须是当前主流、按实际需求最优——JS 用 const/let、fetch、addEventListener、flex/grid，禁 jQuery/XMLHttpRequest/document.write（verify 机器拦截）；确需框架选当前主流大版本本地引用，禁停止维护的大版本；03「选型说明」写明选型原因四要素：① 结论 ② 需求匹配点（接住 PRD 哪几条、为什么对这个需求最合适）③ 主流与维护依据 ④ 否决项及原因（至少 1 个，含代价），末尾加一行大白话版本，供项目经理向用户汇报方案并征求意见时使用",
            "数据层选型：localStorage / IndexedDB / JSON 文件 / SQLite，按数据量与结构定，写明备份恢复",
            "第三方组件：确需图表/图标等能力时下载发行文件放应用文件夹本地引用，记录名称/版本/许可证（MIT、ISC、CC0 等），严禁 CDN 外链",
            "能力边界核对：对照 tech-recipes 的能力边界表逐条核对 PRD，做不了的功能换形态或列入不做",
            "kill 准则（execution-craft.md 第一节）：能力边界命中的红线问题触发即停——写退回单或换形态，不许\"先做着后面绕\"，不带窟窿出方案",
            "文件结构、性能预算（>1000 条分页、>5MB 换 IndexedDB）、风险与规避",
        ],
        "type_must": {
            "data": [
                "库策略：标准库优先；确需第三方库（如 pandas/openpyxl）列名称/用途/许可证，并在使用说明写明\"第一次用前需要装一下\"的步骤",
                "编码与兼容：输入文件编码探测链（utf-8/gbk…）、输出编码（给 Excel 用的 csv 用 utf-8-sig）",
                "健壮性：原始输入文件只读不改；临时文件+原子替换；异常不吞——中文提示\"哪里错了、跳过了什么、结果在哪\"",
            ],
            "admin": [
                "形态 E：本地服务 + SQLite，以 assets/admin-template.py 为骨架（登录/会话/角色/备份已内置）；换型需写明理由与代价",
                "认证与权限：密码 pbkdf2 加密存储、会话失效策略、每个路由的服务端权限校验点清单",
                "备份恢复：界面\"备份数据\"按钮复制数据库到 backups/，写明恢复步骤",
            ],
            "front": [
                "路由与资源：多页 HTML 或单页路由的取舍；共享样式/脚本的组织方式",
                "商用清单：每页 title 与描述、favicon、404 页、加载/空状态、跨页返回、图片压缩与懒加载",
                "性能预算：单页体积与首屏资源上限、图片总量控制",
            ],
        },
        "bounds": [
            "不增删需求；发现需求或设计不可实现→写退回单，不自作主张变通",
            "不直接编写业务代码",
            "架构/数据层/组件一律按 references/tech-recipes.md 的规则拍板，永不抛给用户",
        ],
    },
    "dev": {
        "title": "技术部·开发工程师",
        "docs": ["00", "02", "03"],
        "output": "可运行的交付物（放在应用文件夹根目录；以技能 assets/ 内对应类型样板起步：网页 app-template.html、后台 admin-template.py）+ 团队文档/06-开发自查清单.md",
        "must": [
            "按 00-项目规划书的积木块顺序交付：每拼完一块在汇报中声明\"M 几完成、可查验\"，不打乱顺序（前置块未过用户查验不开始依赖它的块）",
            "界面实现严格照 02-设计方案：动手第一步就把 02「设计令牌」节的值抄进样板的 :root（不抄=样式必然走样）；「基线自查」各维取值（reduced-motion 兜底、tabular-nums、z-index 阶梯、结构骨架等）一并落地，不走样",
            "组件品质五状态：每个可点元素（默认/悬停/按下/禁用/加载）齐全；数据四境况（常/空/错/载）都有实现",
            "提测前对抗自审（execution-craft.md 第三节，必做）：以破坏者/笨用户新手/隐私官三个人格各找 ≥1 条问题（找不到=没找够），能修的修掉，修不掉的写进 06 末尾「自审记录」连同修法说明",
            "界面与文案全部中文，不擅自扩功能",
            "自查清单每条 AC 标注 - [x] AC-xx 已实现：<说明> 或 - [ ] AC-xx 未实现：<原因>",
        ],
        "type_must": {
            "data": [
                "脚本输出与提示信息全部中文；绝不修改用户的原始输入文件，结果写新文件",
                "交付物 = .py + 启动.bat（bat 含 chcp 65001 / cd /d \"%~dp0\" / pause），verify 会逐项检查",
            ],
            "admin": [
                "以 assets/admin-template.py 为骨架扩展（登录/会话/权限/备份不删减）；密码必须 pbkdf2 存储，禁止明文",
                "每个功能在服务端校验角色权限，不能只靠界面藏按钮",
            ],
            "front": [
                "全站样式只从 02 的设计令牌取值；每页有 title/viewport/描述与 favicon",
                "404 页、加载与空状态逐页落实；图片本地且压缩",
            ],
        },
        "bounds": [
            "三不：不改需求范围、不换技术选型、不擅自修改设计",
            "上游文档问题写退回单，禁止静默修改上游产物",
            "不做浏览器自动化测试（真机走查归项目经理）",
        ],
    },
    "fe": {
        "title": "技术部·前端工程师",
        "docs": ["00", "02", "03"],
        "output": "可运行的前端交付物（应用文件夹根目录）+ 团队文档/06-开发自查清单.md（前端相关 AC；前后端分写后由 PMO 合并核对）",
        "must": [
            "界面与文案全部中文；样式只从 02-设计令牌取值，不擅自扩功能",
            "自查清单每条 AC 标注 - [x] AC-xx 已实现：<说明> 或 - [ ] AC-xx 未实现：<原因>（前端相关 AC）",
        ],
        "type_must": {
            "admin": [
                "后台界面以服务端模板呈现，样式脚本内联或本地文件，禁 CDN 外链",
                "权限在界面的呈现严格按 02-权限呈现：无权限的入口不渲染，但不依赖它做安全（安全归后端）",
            ],
            "front": [
                "每页 title/viewport/描述/favicon 齐全；响应式按 02 断点实现；图片本地且压缩",
            ],
        },
        "bounds": [
            "三不：不改需求范围、不换技术选型、不擅自修改设计",
            "上游文档问题写退回单，禁止静默修改上游产物",
            "不做浏览器自动化测试（真机走查归项目经理）",
        ],
    },
    "be": {
        "title": "技术部·后端工程师",
        "docs": ["00", "02", "03"],
        "output": "可运行的服务端/脚本交付物（应用文件夹根目录）+ 团队文档/06-开发自查清单.md（后端相关 AC；前后端分写后由 PMO 合并核对）",
        "must": [
            "提示与报错信息全部中文，不擅自扩功能",
            "自查清单每条 AC 标注 - [x] AC-xx 已实现：<说明> 或 - [ ] AC-xx 未实现：<原因>（后端相关 AC）",
        ],
        "type_must": {
            "admin": [
                "以 assets/admin-template.py 为骨架扩展：登录/会话/权限校验/备份不删减；密码必须 pbkdf2 存储",
                "每个路由的服务端权限校验点与 03-技术方案 的清单一一对应",
            ],
            "data": [
                "绝不修改用户的原始输入文件，结果写新文件；异常不吞（中文提示 + 非零退出码）",
            ],
        },
        "bounds": [
            "三不：不改需求范围、不换技术选型、不擅自修改设计",
            "上游文档问题写退回单，禁止静默修改上游产物",
            "不做浏览器自动化测试（真机走查归项目经理）",
        ],
    },
    "sec": {
        "title": "安全部·安全与隐私工程师",
        "docs": ["00", "01", "03"],
        "output": "团队文档/07-安全与隐私清单.md",
        "must": [
            "数据分级：应用收集/存储了哪些数据，逐类标注敏感级别（公开/内部/敏感/高敏）、存在哪、谁能看到、能不能不收",
            "攻击面检查：登录与会话、文件与路径处理、表单与注入、依赖组件的版本与已知漏洞（逐项写\"测过什么、怎么防\"）",
            "隐私底线：最小化收集、不留后门/不硬编码密钥、用户数据不偷偷上传、有导出与删除路径",
            "风险与缓解：发现的问题按严重度列出并给修复建议，格式 - [严重|一般] 描述 | 建议 | open|fixed；严重问题必须修复后才算完成",
        ],
        "type_must": {
            "data": [
                "输入文件攻击面：路径穿越、超大文件/解压炸弹、伪装成数据的可执行内容；再次确认绝不覆盖用户原始文件",
            ],
            "admin": [
                "重点核对：密码哈希存储、每个路由的服务端角色校验、会话失效、备份文件与数据库文件的保管、内置账号首次改密",
            ],
            "front": [
                "重点核对：表单提交去向、外部内容零依赖、素材版权与本地文件完整性（防供应链投毒）",
            ],
        },
        "bounds": [
            "不改代码：发现安全问题写入清单，通过项目经理转交开发修复",
            "只做防御性检查，不编写利用代码、不做攻击性测试",
            "不降级已确认的安全底线（如密码加密）；发现\"严重\"级问题有一票缓发权，由项目经理裁决修复方案",
        ],
    },
    "qa": {
        "title": "质量部·测试工程师",
        "docs": ["00", "01", "02", "03"],
        "output": "团队文档/04-测试报告.md",
        "must": [
            "测试用例表（编号/步骤/预期/实际/通过否），覆盖每条 AC 编号，按 00-规划书的积木块分组；每条 AC 先转成可测试问句（execution-craft.md 第二节转换表），禁止虚词预期",
            "对抗审查节（必须存在）：以破坏者/笨用户新手/隐私官三个人格各找 ≥1 条问题（execution-craft.md 第三节纪律：找不到=没找够；不许和稀泥；双人格调命中升级）",
            "bug 用固定格式：- BUG-编号 | 严重|一般|建议 | 标题 | open|fixed（定级按 execution-craft.md 第五节四级表映射：4阻断/3重→严重，2轻→一般，1记录→建议）；多条问题按 优先分=频率×严重度×可解性 排序",
            "报告末尾留\"待项目经理走查清单\"（QA 不得做浏览器操作），按\"笨用户新手第一次上手\"视角列出最该真机验证的点",
        ],
        "type_must": {
            "data": [
                "必须包含「样例数据测试」与「异常输入测试」：正常输入跑出预期输出；空文件/坏编码/缺列/超大文件被安全处理且中文提示",
                "脚本由本岗真实运行（不碰浏览器），运行结果截图或原文摘录进报告",
            ],
            "admin": [
                "必须包含「角色权限测试」：每个角色 × 关键功能逐格验证可见/可改；未授权账号直接访问受限地址必须被服务端拒绝",
                "登录/退出/改密/备份/重启后数据保留纳入用例",
            ],
            "front": [
                "逐页检查 title/空状态/404/跨页返回；响应式问题列入\"待项目经理走查清单\"（真机走查归 PMO）",
            ],
        },
        "bounds": [
            "不做浏览器操作（真机走查归项目经理）",
            "不改代码，只报告不修复",
            "bug 定级（严重/一般/建议）由本岗负责，开发申诉时由项目经理裁决",
        ],
    },
}

BRIEF_HEADER = """【角色】{title}，你是虚拟开发团队中的这个岗位
【背景】用户是零编程经验的甲方；项目：{name}；规模：{scale}；
        应用文件夹：{app_dir}（团队文档已建好）
【任务】{task}
【输入】
  1. 用户原话（逐字，项目经理粘贴）：<在这里逐字粘贴用户原话>
  2. 项目经理复述（阶段0已确认）：<在这里写复述和关键标注>
  3. 上游文档（完整阅读后再动笔）：{docs_list}
【产出】写入 {app_dir}/{output}，必须包含：
{must_list}
【边界】以下职责边界不可逾越（越界即返工）：
{bounds_list}
  通用：发现上游文档（PRD/设计/技术方案）有问题时，停止受影响的工作，写退回单到
        {app_dir}/团队文档/派工/退回-<本岗位>-<主题>.md（写明：退给谁/问题/阻塞/建议改法），
        并在返回汇报中说明；禁止静默修改上游产物，禁止自行变更方案。
【约束】界面与文案全部中文；不擅自新增需求（新想法一律写入"以后再说"）；
        拿不准的点写进文末"待确认"，禁止编造；只依据输入内容工作；
        只实现合法用途的功能——发现疑似违法、侵权或未经授权处理他人数据的内容，
        立即停止该部分工作并在返回汇报中说明，禁止照做
【返回】给项目经理不超过 200 字的完成汇报 + 待确认清单（如有）"""


# ---------- 基础设施 ----------

def fail(msg):
    print(f"✗ {msg}")
    sys.exit(1)


def find_project(explicit):
    if explicit:
        p = Path(explicit).resolve()
        if not p.exists():
            fail(f"目录不存在：{p}")
        return p
    cwd = Path.cwd().resolve()
    for p in [cwd, *cwd.parents]:
        if (p / "团队文档" / "00-项目状态.json").exists():
            return p
    fail("未找到项目（向上找不到 团队文档/00-项目状态.json）。请先 init，或用 --dir 指定应用文件夹。")


def load_state(app_dir):
    f = app_dir / "团队文档" / "00-项目状态.json"
    if not f.exists():
        fail(f"状态文件缺失：{f}（该项目可能未 init）")
    return json.loads(f.read_text(encoding="utf-8")), f


def save_state(app_dir, state, f):
    f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def doc_path(app_dir, doc_id):
    return app_dir / "团队文档" / DOC_FILES[doc_id]


def strip_comments(text):
    """剥离 HTML 注释——模板里的示例写在注释里，避免机器误判为已填写。"""
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def read_doc(app_dir, doc_id):
    p = doc_path(app_dir, doc_id)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def ac_ids(text):
    return sorted(set(re.findall(r"AC-\d+", text)), key=lambda x: int(x.split("-")[1]))


def plan_blocks(text):
    """从规划书正文解析积木块，返回有序 [(块号, 章节文本)]。块格式固定：### M1 <块名>。"""
    matches = list(re.finditer(r"^###\s*(M\d+)\b[^\n]*$", text, flags=re.M))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group(1), text[m.end():end]))
    return out


def block_acs(section):
    """积木块章节里「包含 AC：AC-01, AC-02」一行解析出的 AC 列表。"""
    m = re.search(r"包含\s*AC[:：][^\n]*", section)
    return ac_ids(m.group(0)) if m else []


def section_text(text, header):
    """取 markdown 中某二级/三级标题下、到下一个标题为止的正文。"""
    m = re.search(rf"^#+\s*{re.escape(header)}.*$", text, flags=re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^#{1,3}\s+", rest, flags=re.M)
    return rest[: nxt.start()] if nxt else rest


def nonempty(text):
    body = strip_comments(text)
    return bool(re.sub(r"[-*\s>#`]", "", body))


# ---------- 变更提案（迭代期变更管理：提案 → 用户确认 → release 合并进功能清单并归档）----------

FID_HEADER_RE = re.compile(r"^#{3,4}\s*(F-\d+)\b[^\n]*$", re.M)


def parse_entries(text):
    """解析 F-编号功能条目（### 或 #### 标题行起），返回有序 [(编号, 标题行, 条目正文)]。"""
    ms = list(FID_HEADER_RE.finditer(text))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out.append((m.group(1), m.group(0).strip(), text[m.end():end]))
    return out


def parse_delta(text):
    """解析提案「功能增量」节（新增/修改/移除）。
    返回 (新增[(编号,标题,正文)], 修改[(编号,标题,正文)], 移除[编号])。"""
    m = re.search(r"^#{2,3}\s*功能增量\s*$", text, flags=re.M)
    if not m:
        return [], [], []
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, flags=re.M)
    body = rest[: nxt.start()] if nxt else rest
    added, modified, removed = [], [], []
    for key in ("新增", "修改", "移除"):
        sec_m = re.search(rf"^###\s*{key}\s*$", body, flags=re.M)
        if not sec_m:
            continue
        sec_rest = body[sec_m.end():]
        sec_nxt = re.search(r"^###\s", sec_rest, flags=re.M)
        sec = sec_rest[: sec_nxt.start()] if sec_nxt else sec_rest
        if key == "移除":
            removed = re.findall(r"-\s*(F-\d+)\b", sec)
        else:
            (added if key == "新增" else modified).extend(parse_entries(sec))
    return added, modified, removed


def baseline_path(app_dir):
    return app_dir / "团队文档" / "00-当前功能清单.md"


def baseline_items(app_dir):
    """读当前功能清单的功能条目；文件不存在返回 None，存在则返回条目列表（可为空）。"""
    bp = baseline_path(app_dir)
    if not bp.exists():
        return None
    return parse_entries(strip_comments(bp.read_text(encoding="utf-8")))


def append_history(bp, line):
    bp.write_text(bp.read_text(encoding="utf-8").rstrip() + "\n" + line + "\n", encoding="utf-8")


def rewrite_baseline(bp, entries):
    """用合并后的条目重写「功能条目」节，保留文件头注释与「变更史」节。"""
    t = bp.read_text(encoding="utf-8")
    m1 = re.search(r"^##\s*功能条目\s*$", t, flags=re.M)
    m2 = re.search(r"^##\s*变更史\s*$", t, flags=re.M)
    if not (m1 and m2 and m1.start() < m2.start()):
        fail("00-当前功能清单.md 缺「功能条目」或「变更史」章节（格式见技能 assets/templates/00-当前功能清单.md）")
    # 条目标题统一为三级（提案里写的是四级 ####，进基线归一为 ###）
    block = "\n\n".join(f"{re.sub(r'^#{3,4}', '###', title)}\n{txt.strip()}" for _, title, txt in entries) + "\n"
    t = t[: m1.end()] + "\n\n" + block + "\n" + t[m2.start():].rstrip() + "\n"
    bp.write_text(t, encoding="utf-8")


# ---------- 子命令 ----------

def template_for(vtype, fname):
    """项目类型专属模板优先（assets/templates/<type>/<文件>），否则用通用模板。"""
    if vtype and vtype != "tool":
        p = TEMPLATES / vtype / fname
        if p.exists():
            return p
    return TEMPLATES / fname


def cmd_init(args):
    parent = Path(args.dir).resolve() if args.dir else Path.cwd()
    app_dir = parent / args.name
    if app_dir.exists():
        fail(f"目录已存在：{app_dir}")
    scale = args.scale
    vtype = args.type
    (app_dir / "团队文档" / "派工").mkdir(parents=True)
    for doc_id, fname in DOC_FILES.items():
        shutil.copy(template_for(vtype, fname), app_dir / "团队文档" / fname)
    # 当前功能清单（"现在真相"基线）：首版发版前填写，此后只经 release 合并变更增量更新
    shutil.copy(TEMPLATES / "00-当前功能清单.md", app_dir / "团队文档" / "00-当前功能清单.md")
    # 变更提案目录（迭代期：提案 → 用户确认 → release 合并归档）
    chg_dir = app_dir / "团队文档" / "变更"
    chg_dir.joinpath("归档").mkdir(parents=True)
    (chg_dir / "README.md").write_text(
        "# 变更提案目录\n\n"
        "发版后的功能变化先立提案再动工：`pm.py propose <变更名>` 在本目录建 <变更名>/提案.md。\n"
        "提案经用户确认（原话留案）→ 按「任务安排」追加积木块拼装 → release 时机器把功能增量\n"
        "合并进 ../00-当前功能清单.md，提案移入 归档/<日期>-<变更名>/。纯修 bug 不立提案；\n"
        "用户放弃的提案用 `propose <变更名> --drop` 归档。\n",
        encoding="utf-8",
    )
    shutil.copy(TEMPLATES / "我的应用.md", app_dir / "我的应用.md")
    shutil.copy(TEMPLATES / "使用说明.txt", app_dir / "使用说明.txt")
    state = {
        "name": args.name,
        "scale": scale,
        "type": vtype,
        # front 默认视为纯展示站（不存用户数据）；确有数据录入时在 PRD 写明并自行实现导出
        "hasUserData": (not args.no_data) and args.type != "front",
        "phase": "requirements" if scale != "small" else "intake",
        "iteration": 1,
        "gates": {},
        "created": date.today().isoformat(),
    }
    save_state(app_dir, state, app_dir / "团队文档" / "00-项目状态.json")
    print(f"✅ 项目已初始化：{app_dir}")
    print(f"   类型：{TYPE_LABEL.get(vtype, vtype)}；编制：{scale}；阶段：{PHASE_LABEL[state['phase']]}")
    if scale == "small":
        print("   小型编制：不留团队文档流程，直接开发。")
        print("   下一步：开发完成后运行 verify + gate G3 检查交付物，再 release。")
    else:
        if scale == "xl":
            print("   XL 编制：开发拆前端/后端两岗（dispatch fe / dispatch be）。")
        if vtype == "admin":
            print("   开发岗将以 assets/admin-template.py 为骨架（登录/角色/备份已内置）。")
        elif vtype == "data":
            print("   交付物 = .py 脚本 + 启动.bat（verify 会检查双击件与编码处理）。")
        print("   下一步：python pm.py dispatch pm 生成产品经理派工单，补齐输入后派工。")
        print("   （G1 过门后，产品经理先出《00-项目规划书》拆积木块，用户确认后按块推进）")


def cmd_status(args):
    app_dir = find_project(args.dir)
    state, _ = load_state(app_dir)
    vtype = state.get("type", "tool")
    print(f"项目：{state['name']}（{TYPE_LABEL.get(vtype, vtype)} · {state['scale']}）")
    print(f"阶段：{PHASE_LABEL.get(state['phase'], state['phase'])}  迭代：第 {state['iteration']} 轮")
    t00 = read_doc(app_dir, "00")
    if t00:
        blocks = plan_blocks(strip_comments(t00))
        done = state.get("blocks") or {}
        if blocks:
            marks = "  ".join(f"{b}{'✅' if b in done else '⬜'}" for b, _ in blocks)
            n_done = sum(1 for b, _ in blocks if b in done)
            print(f"积木块：{marks}（已查验 {n_done}/{len(blocks)}）")
    cur = {g: v for g, v in state["gates"].items() if v.get("iteration") == state["iteration"]}
    if cur:
        print("评审门（本轮）：" + "  ".join(f"{g}✅" for g in sorted(cur)))
    else:
        print("评审门（本轮）：尚未通过任何门")
    report = read_doc(app_dir, "04")
    if report:
        bugs = re.findall(r"- BUG-\d+\s*\|\s*(严重|一般|建议)\s*\|[^|]*\|\s*(open|fixed)", strip_comments(report))
        open_bugs = [b for b in bugs if b[1] == "open"]
        print(f"bug：共 {len(bugs)} 条，未修复 {len(open_bugs)} 条"
              + (f"（严重 open {sum(1 for b in open_bugs if b[0] == '严重')}）" if open_bugs else ""))
    open_chg = [c["name"] for c in state.get("changes", []) if c.get("state") == "open"]
    if open_chg:
        print("变更提案（进行中）：" + "、".join(open_chg) + "（一次只做一份，其余排队）")
    n_merged = sum(1 for c in state.get("changes", []) if c.get("state") == "merged")
    if n_merged:
        print(f"已归档变更：{n_merged} 份（团队文档/变更/归档/；历史见 00-当前功能清单「变更史」）")


def cmd_scaffold(args):
    app_dir = find_project(args.dir)
    state, f = load_state(app_dir)
    if args.doc_id not in DOC_FILES:
        fail(f"未知文档编号 {args.doc_id}，可选：{' '.join(DOC_FILES)}")
    dest = doc_path(app_dir, args.doc_id)
    if dest.exists() and not args.force:
        fail(f"已存在 {dest.name}（--force 覆盖）")
    shutil.copy(template_for(state.get("type", "tool"), DOC_FILES[args.doc_id]), dest)
    save_state(app_dir, state, f)
    print(f"✅ 已落模板：{dest}")


def cmd_dispatch(args):
    app_dir = find_project(args.dir)
    state, _ = load_state(app_dir)
    role = args.role
    if role not in DISPATCH:
        fail(f"未知岗位 {role}，可选：{' '.join(DISPATCH)}")
    vtype = state.get("type", "tool")
    info = DISPATCH[role]
    must = list(info["must"]) + list(info.get("type_must", {}).get(vtype, []))
    docs_list = "\n".join(
        f"     - {app_dir / '团队文档' / DOC_FILES[d]}" for d in info["docs"]
    ) or "     - （无上游文档，以用户原话为准）"
    brief = BRIEF_HEADER.format(
        title=info["title"],
        name=state["name"],
        scale=f"{state['scale']}（{TYPE_LABEL.get(vtype, vtype)}）",
        app_dir=app_dir,
        task="<一句话说明本次要做什么>",
        docs_list=docs_list,
        output=info["output"],
        must_list="\n".join(f"  {i+1}. {m}" for i, m in enumerate(must)),
        bounds_list="\n".join(f"  {i+1}. {b}" for i, b in enumerate(info["bounds"])),
    )
    out_dir = app_dir / "团队文档" / "派工"
    out_dir.mkdir(exist_ok=True)
    base = out_dir / f"{role}-brief.md"
    dest, n = base, 2
    while dest.exists():
        dest = out_dir / f"{role}-brief-{n}.md"
        n += 1
    dest.write_text(f"# 派工单 · {info['title']}（{date.today().isoformat()}）\n\n```text\n{brief}\n```\n", encoding="utf-8")
    print(brief)
    print(f"\n✅ 派工单已留痕：{dest}")
    print("   请把 <尖括号> 里的占位补齐后，连同 brief 全文派给子代理；子代理的完成汇报请存为同目录 <岗位>-report.md。")


def cmd_checkpoint(args):
    """记录一块积木"经用户查验通过"。先机器校验该块 AC 已在 06 自查清单全部打勾。"""
    app_dir = find_project(args.dir)
    state, f = load_state(app_dir)
    plan = read_doc(app_dir, "00")
    if plan is None:
        fail("00-项目规划书.md 不存在（中型以上项目先由产品经理产出规划书再按块推进）")
    body = strip_comments(plan)
    blocks = dict(plan_blocks(body))
    if args.block not in blocks:
        fail(f"规划书里没有积木块「{args.block}」。已定义：{' '.join(blocks) or '（无，格式应为 ### M1 <块名>）'}")
    acs = block_acs(blocks[args.block])
    t06 = read_doc(app_dir, "06")
    body06 = strip_comments(t06) if t06 is not None else ""
    unchecked = [a for a in acs if not re.search(rf"- \[[xX]\]\s*{a}\b", body06)]
    if unchecked:
        fail(f"块 {args.block} 的 AC 尚未在 06-开发自查清单全部打勾：{unchecked}")
    state.setdefault("blocks", {})[args.block] = {"date": date.today().isoformat(), "note": args.note}
    save_state(app_dir, state, f)
    print(f"✅ 积木块 {args.block} 已记录为【经用户查验通过】（{len(acs)} 条 AC：{' '.join(acs) or '无'}）")
    if args.note:
        print(f"   备注：{args.note}")
    else:
        print("   提醒：checkpoint 应在用户看过该块演示并点头之后记录；用户未确认就记录属于违规。")
    remaining = [b for b in blocks if b not in state["blocks"]]
    print(f"   进度：{len(blocks) - len(remaining)}/{len(blocks)}" + (f"，下一块：{remaining[0]}" if remaining else "，全部查验完毕可走 G3 提测"))


def cmd_propose(args):
    """立一份变更提案（迭代期功能变化的动工凭证）；--drop 放弃一份进行中的提案。"""
    app_dir = find_project(args.dir)
    state, f = load_state(app_dir)
    slug = re.sub(r'[\\/:*?"<>|\s]+', "-", args.name).strip("-").rstrip(".")
    if not slug:
        fail("变更名不能为空（用中文短名，如：加导出）")
    changes_dir = app_dir / "团队文档" / "变更"
    if args.drop:
        target = next((c for c in state.get("changes", []) if c["name"] == slug and c.get("state") == "open"), None)
        if target is None:
            fail(f"没有进行中的变更「{slug}」")
        src = changes_dir / slug
        dest = changes_dir / "归档" / f"{date.today().isoformat()}-{slug}-放弃"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.move(str(src), str(dest))
        target["state"] = "dropped"
        bp = baseline_path(app_dir)
        if bp.exists():
            append_history(bp, f"- [{date.today().isoformat()}] {slug}：用户放弃，未实施")
        save_state(app_dir, state, f)
        print(f"✅ 变更「{slug}」已放弃并归档（未做任何功能改动）：团队文档/变更/归档/{dest.name}/")
        return
    if any(c["name"] == slug and c.get("state") == "open" for c in state.get("changes", [])) or (changes_dir / slug).exists():
        fail(f"变更「{slug}」已存在（团队文档/变更/ 下有同名文件夹；做完发版或 propose {slug} --drop 放弃后再建新的）")
    dest = changes_dir / slug
    dest.mkdir(parents=True)
    shutil.copy(TEMPLATES / "变更提案.md", dest / "提案.md")
    state.setdefault("changes", []).append({"name": slug, "created": date.today().isoformat(), "state": "open"})
    save_state(app_dir, state, f)
    print(f"✅ 变更提案已建立：团队文档/变更/{slug}/提案.md")
    print("   补齐四件事：为什么改（用户原话）/ 改什么（大白话）/ 用户确认（点头原话，动工前拿到）/ 功能增量（对照 00-当前功能清单 写 新增/修改/移除）。")
    print("   用户点头原话留进「用户确认」节才许动工（G3 机器校验）；新积木块照「任务安排」追加进 00-项目规划书。")


def cmd_probe(args):
    """给样品页打"仅方向参考"横幅并归档到 探索/，防止用户误当成品。"""
    src = Path(args.file).resolve()
    if not src.exists():
        fail(f"找不到样品文件：{src}")
    label = args.label or src.stem
    t = src.read_text(encoding="utf-8", errors="replace")
    banner_id = "probe-banner"
    banner = (
        f'<div id="{banner_id}" style="position:sticky;top:0;z-index:9999;background:#e8590c;color:#fff;'
        f'padding:10px 14px;font-size:15px;font-weight:bold;text-align:center;box-shadow:0 2px 6px rgba(0,0,0,.25)">'
        f'设计样品 · {label} —— 只用来选方向，还不是能用的应用</div>'
    )
    t = re.sub(rf'<div id="{banner_id}".*?</div>\s*', "", t, flags=re.S)  # 幂等：替换旧横幅
    m = re.search(r"<body[^>]*>", t, flags=re.I)
    if not m:
        fail("样品文件里没有 <body> 标签，无法打样品标记")
    t = t[: m.end()] + "\n" + banner + t[m.end():]
    out_dir = Path(args.out).resolve() if args.out else src.parent / "探索"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / src.name
    dest.write_text(t, encoding="utf-8")
    rec = out_dir / "00-探索记录.md"
    line = f"- {date.today().isoformat()} 样品：{dest.name} —— {label}\n"
    if not rec.exists():
        rec.write_text(
            "# 探索记录\n\n"
            "<!-- 用户方向未定时的样品与结论；选定方向后由 PMO 摘录进《我的应用.md》 -->\n\n" + line,
            encoding="utf-8",
        )
    else:
        rec.write_text(rec.read_text(encoding="utf-8") + line, encoding="utf-8")
    print(f"✅ 样品已标记并归档：{dest}")
    print(f"   探索记录：{rec}")
    print("   提醒：发给用户时必须说明\"这是样品，用来看方向，不是成品\"。")


def check_html_text(name, t, errors, warns, external="all", check_viewport=True):
    """单个 HTML 文本的通用检查。external: all=src/href 都查（单文件自包含），src=只查资源加载。"""
    pat = r"""(?:src|href)\s*=\s*["']https?://[^"']+|@import\s+url\(\s*["']?https?://[^"')]+|url\(\s*["']?https?://[^"')]+"""
    if external == "src":
        pat = r"""(?:src)\s*=\s*["']https?://[^"']+|@import\s+url\(\s*["']?https?://[^"')]+|url\(\s*["']?https?://[^"')]+"""
    externals = re.findall(pat, t, flags=re.I)
    if externals:
        errors.append(f"{name}：引用了 {len(externals)} 处外部网络资源（{externals[0][:60]}...）——离线可用不能依赖网络，必须改为内联/本地")
    # 现代技术栈基线：过时技术机器拦截（基线见 references/tech-recipes.md）
    # 注：裸 $( 不拦——现代常有人写 const $ = q => document.querySelector(q) 简写，属合法主流
    legacy = sorted({m.group(0) for m in re.finditer(
        r"jquery|\$\.ajax\s*\(|\$\.get\s*\(|\$\.post\s*\(|\$\(\s*document\s*\)\s*\.\s*ready|XMLHttpRequest|document\.write\s*\(",
        t, flags=re.I)})
    if legacy:
        errors.append(f"{name}：发现过时技术「{'、'.join(legacy)}」（现代技术栈基线禁用：用原生 DOM API、fetch、模板字符串等当前主流写法替代，见 tech-recipes.md「现代技术栈基线」）")
    if not re.search(r"<meta[^>]+charset", t, flags=re.I):
        errors.append(f"{name}：缺少 <meta charset>（中文会乱码）")
    if not re.search(r"<title>\S+", t, flags=re.I):
        errors.append(f"{name}：缺少 <title>")
    if check_viewport and not re.search(r'name="viewport"', t, flags=re.I):
        warns.append(f"{name}：缺少 viewport meta（手机上打开会缩小变形）")
    if re.search(r"lang=\"(?!zh)", t, flags=re.I):
        warns.append(f"{name}：<html lang> 不是 zh")


def check_bat(p, app_dir, errors):
    """双击启动 .bat 的通用检查（data/admin 类型交付物）。"""
    t = p.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"chcp\s+65001", t):
        errors.append(f"{p.name}：缺少 chcp 65001（中文输出会乱码）")
    if not re.search(r"cd\s+/d\s+\"?%~dp0\"?", t):
        errors.append(f"{p.name}：缺少 cd /d \"%~dp0\"（从别处双击会找不到同目录文件）")
    if not re.search(r"^pause", t, flags=re.M):
        errors.append(f"{p.name}：结尾缺 pause（窗口会一闪而过，用户看不到结果）")
    refs = re.findall(r"[\w\-一-龥]+\.py", t)
    if refs and not any((app_dir / r).exists() for r in refs):
        errors.append(f"{p.name}：引用的脚本 {refs[0]} 不存在")


def verify_html(app_dir, state, vtype):
    """tool / front：网页交付物检查（front 商用级更严）。"""
    errors, warns = [], []
    htmls = list(app_dir.glob("*.html"))
    if not htmls:
        errors.append("应用文件夹根目录没有找到 .html 交付物")
        return errors, warns
    texts = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in htmls}
    for name, t in texts.items():
        check_html_text(name, t, errors, warns, check_viewport=(vtype != "front"))
        if vtype == "front" and not re.search(r'name="viewport"', t, flags=re.I):
            errors.append(f"{name}：缺少 viewport meta（商用前台必须手机可用）")
    if vtype == "front" and len(htmls) > 1 and not (app_dir / "index.html").exists():
        errors.append("多页前台缺少 index.html 入口（用户要双击的就是它）")
    if state.get("hasUserData", True):
        if not any(re.search(r"导出|备份", t) for t in texts.values()):
            errors.append("有用户数据但找不到\"导出/备份\"功能（质量底线）")
    if vtype == "tool" and not any(re.search(r"localStorage|导出|备份", t) for t in texts.values()):
        warns.append("未发现数据保存机制（localStorage 或导出）")
    return errors, warns


def verify_data(app_dir, state):
    """data：脚本交付物检查——双击件齐全、编码有处理、可移植。"""
    errors, warns = [], []
    pys = list(app_dir.glob("*.py"))
    bats = list(app_dir.glob("*.bat"))
    if not pys:
        errors.append("没有找到 .py 脚本文件")
    if not bats:
        errors.append("没有找到 启动.bat（用户要双击就能用，见 tech-recipes 方案 C）")
    for p in bats:
        check_bat(p, app_dir, errors)
    for p in pys:
        t = p.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"utf-8|utf8|gbk|encoding", t, flags=re.I):
            warns.append(f"{p.name}：未发现编码处理（中文文件常见 utf-8/gbk 差异，建议显式处理）")
        if re.search(r"[A-Za-z]:\\\\", t):
            warns.append(f"{p.name}：疑似写死盘符绝对路径（换电脑会失效），请改相对路径")
    # 脚本生成的 html 报告也算交付物，做基础检查
    for p in app_dir.glob("*.html"):
        check_html_text(p.name, p.read_text(encoding="utf-8", errors="replace"), errors, warns)
    return errors, warns


def verify_admin(app_dir, state):
    """admin：本地服务交付物检查——安全底线（加密存储/登录/备份）+ 双击件。"""
    errors, warns = [], []
    pys = list(app_dir.glob("*.py"))
    bats = list(app_dir.glob("*.bat"))
    if not pys:
        errors.append("没有找到服务端 .py 文件")
    if not bats:
        errors.append("没有找到 启动.bat（用户要双击就能用，见 tech-recipes 方案 E）")
    code = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in pys)
    if not re.search(r"sqlite3|json\.(dump|load)", code):
        errors.append("未发现数据存储层（SQLite 或 JSON 文件；方案 E 默认 SQLite）")
    if not re.search(r"pbkdf2_hmac\(|bcrypt\.hashpw|scrypt\.|passlib|werkzeug|argon2", code):
        errors.append("密码没有用 pbkdf2/bcrypt 等算法加密存储（须有真实调用；禁止明文。骨架 assets/admin-template.py 已内置）")
    if not re.search(r"登录|login", code, flags=re.I):
        errors.append("未发现登录功能（管理后台必须有登录）")
    if state.get("hasUserData", True) and not re.search(r"备份", code):
        errors.append("有数据但找不到「备份」功能（管理后台默认用\"备份数据\"按钮复制数据库文件）")
    if not (re.search(r"webbrowser", code) or any(
            re.search(r"start\b", p.read_text(encoding='utf-8', errors='replace'), flags=re.I) for p in bats)):
        warns.append("双击启动后不会自动打开浏览器（建议 app.py 用 webbrowser.open 或 bat 用 start）")
    for p in bats:
        check_bat(p, app_dir, errors)
    for p in app_dir.glob("*.html"):
        check_html_text(p.name, p.read_text(encoding="utf-8", errors="replace"), errors, warns, external="src")
    return errors, warns


def run_verify(app_dir, state):
    """按项目类型分派交付物静态检查，返回 (hard_errors, warnings) 列表。"""
    vtype = state.get("type", "tool")
    if vtype == "data":
        return verify_data(app_dir, state)
    if vtype == "admin":
        return verify_admin(app_dir, state)
    return verify_html(app_dir, state, vtype)


def cmd_verify(args):
    app_dir = find_project(args.dir)
    state, _ = load_state(app_dir)
    errors, warns = run_verify(app_dir, state)
    for e in errors:
        print(f"❌ {e}")
    for w in warns:
        print(f"⚠️  {w}")
    if errors:
        print(f"\n✗ verify 未通过：{len(errors)} 项必须修复")
        sys.exit(1)
    print(f"\n✅ verify 通过（{len(warns)} 项建议）")


def cmd_gate(args):
    app_dir = find_project(args.dir)
    state, f = load_state(app_dir)
    g = args.gate
    vtype = state.get("type", "tool")
    checks = []  # (ok_hard: None|True|False, msg)

    if g == "G1":
        t = read_doc(app_dir, "01")
        checks.append((t is not None, "01-需求文档-PRD.md 存在"))
        if t is not None:
            body = strip_comments(t)
            for h in G1_HEADERS.get(vtype, G1_HEADERS["tool"]):
                checks.append((bool(re.search(rf"^#+\s*{re.escape(h)}", body, flags=re.M)), f"章节「{h}」存在"))
            acs = ac_ids(body)
            checks.append((len(acs) >= 1, f"有可勾选的验收标准（当前 {len(acs)} 条 AC）"))
            checks.append((nonempty(section_text(body, "不做清单")), "不做清单非空"))
            checks.append((nonempty(section_text(body, "待确认")) or True, "待确认清单（可为空）"))
    elif g == "G2":
        t01, t02 = read_doc(app_dir, "01"), read_doc(app_dir, "02")
        checks.append((t01 is not None and ac_ids(strip_comments(t01)), "01-PRD 存在且含 AC"))
        checks.append((t02 is not None, "02-设计方案.md 存在"))
        if t02 is not None:
            body = strip_comments(t02)
            for h in G2_HEADERS.get(vtype, G2_HEADERS["tool"]):
                checks.append((bool(re.search(rf"^#+\s*{re.escape(h)}", body, flags=re.M)), f"章节「{h}」存在"))
            if t01:
                need = ac_ids(strip_comments(t01))
                missing = [a for a in need if a not in body]
                checks.append((not missing, f"AC 追溯：设计覆盖 {len(need) - len(missing)}/{len(need)}"
                                             + (f"，缺 {missing}" if missing else "")))
        # 积木块规划：新版项目（00 已落模板）强制覆盖性校验；老项目（无 00）跳过并提示
        t00 = read_doc(app_dir, "00")
        if t00 is None:
            checks.append((True, "00-项目规划书.md 不存在（老项目兼容；建议 scaffold 00 补拆积木块）"))
        else:
            pbody = strip_comments(t00)
            blocks = plan_blocks(pbody)
            checks.append((bool(re.search(r"^#+\s*积木块分解", pbody, flags=re.M)) and blocks,
                           f"章节「积木块分解」存在且至少 1 块（当前 {len(blocks)} 块）"))
            if t01:
                need_all = set(ac_ids(strip_comments(t01)))
                must_txt = section_text(strip_comments(t01), "必须有")
                must = set(ac_ids(must_txt))
                plan_acs = set(ac_ids(pbody))
                extra = sorted(plan_acs - need_all)
                uncovered = sorted(must - plan_acs)
                checks.append((not extra, "规划未私加 PRD 之外的 AC" + (f"（多了 {extra}）" if extra else "")))
                checks.append((not must or not uncovered,
                               f"规划覆盖全部第一版 AC" + (f"，缺 {uncovered}" if uncovered else "")))
    elif g == "G3":
        state2, _ = load_state(app_dir)
        errors, _ = run_verify(app_dir, state2)
        checks.append((not errors, "交付物静态检查（verify）" + ("" if not errors else "：" + "；".join(errors))))
        t03 = read_doc(app_dir, "03")
        if t03 is None:
            checks.append((True, "03-技术方案.md 不存在（小型编制兼容；方案用大白话讲清并征得用户同意后开工）"))
        else:
            checks.append((nonempty(section_text(t03, "选型说明")),
                           "03「选型说明」非空（结论 / 需求匹配点 / 主流与维护依据 / 否决项及原因 + 大白话版本）"))
            checks.append((nonempty(section_text(t03, "用户意见")),
                           "03「用户意见」非空（方案提出后征求过用户意见并留原话）"))
        t01, t06 = read_doc(app_dir, "01"), read_doc(app_dir, "06")
        checks.append((t06 is not None, "06-开发自查清单.md 存在"))
        if t01 and t06 is not None:
            need = ac_ids(strip_comments(t01))
            body = strip_comments(t06)
            unchecked = [a for a in need if not re.search(rf"- \[[xX]\]\s*{a}\b", body)]
            checks.append((need and not unchecked,
                           f"自查清单：{len(need) - len(unchecked)}/{len(need)} 条 AC 已实现"
                           + (f"，未勾选 {unchecked}" if unchecked else "")))
        # 变更提案（迭代期）：挂着 open 提案时逐份校验要件齐全
        for c in [c for c in state.get("changes", []) if c.get("state") == "open"]:
            p = app_dir / "团队文档" / "变更" / c["name"] / "提案.md"
            checks.append((p.exists(), f"变更「{c['name']}」：提案文件存在"))
            if not p.exists():
                continue
            body = strip_comments(p.read_text(encoding="utf-8"))
            checks.append((nonempty(section_text(body, "为什么改")), f"变更「{c['name']}」：为什么改 非空（用户原话）"))
            checks.append((nonempty(section_text(body, "改什么")), f"变更「{c['name']}」：改什么 非空（大白话）"))
            checks.append((nonempty(section_text(body, "用户确认")), f"变更「{c['name']}」：用户确认原话在案（点头才许动工）"))
            added, modified, removed = parse_delta(body)
            checks.append((bool(added or modified or removed),
                           f"变更「{c['name']}」：功能增量至少一条（当前 新增{len(added)}/修改{len(modified)}/移除{len(removed)}）"))
            base = baseline_items(app_dir)
            if base:
                ids = {fid for fid, _, _ in base}
                bad = sorted(({fid for fid, _, _ in modified} | set(removed)) - ids)
                checks.append((not bad, f"变更「{c['name']}」：修改/移除的编号都在功能清单里" + (f"（未知 {bad}）" if bad else "")))
    elif g == "G4":
        t01, t04 = read_doc(app_dir, "01"), read_doc(app_dir, "04")
        checks.append((t04 is not None, "04-测试报告.md 存在"))
        if t04 is not None:
            body = strip_comments(t04)
            bugs = re.findall(r"- BUG-\d+\s*\|\s*(严重|一般|建议)\s*\|[^|]*\|\s*(open|fixed)", body)
            sev_open = [b for b in bugs if b[0] == "严重" and b[1] == "open"]
            checks.append((not sev_open, f"无 open 状态的严重 bug（当前 bug {len(bugs)} 条，严重 open {len(sev_open)} 条）"))
            for h in G4_EXTRA_HEADERS.get(vtype, []):
                checks.append((bool(re.search(rf"^#+\s*{re.escape(h)}", body, flags=re.M)), f"测试报告章节「{h}」存在"))
            if t01:
                need = ac_ids(strip_comments(t01))
                missing = [a for a in need if a not in body]
                checks.append((not missing, f"AC 追溯：测试覆盖 {len(need) - len(missing)}/{len(need)}"
                                             + (f"，缺 {missing}" if missing else "")))
        checks.append(((app_dir / "使用说明.txt").exists(), "使用说明.txt 存在"))
        # 积木块：规划书里定义的每一块都必须经用户查验（含用户明示免验并留痕的）
        t00 = read_doc(app_dir, "00")
        if t00 is not None:
            blocks = [b for b, _ in plan_blocks(strip_comments(t00))]
            done = set((state.get("blocks") or {}).keys())
            missing = [b for b in blocks if b not in done]
            checks.append((not missing, f"积木块全部经用户查验（{len(blocks) - len(missing)}/{len(blocks)}）"
                                        + (f"，未查验 {missing}" if missing else "")))
        # 安全底线：有用户数据或后台/脚本类项目必须过安全与隐私清单
        if state.get("hasUserData") or vtype in ("data", "admin"):
            t07 = read_doc(app_dir, "07")
            checks.append((t07 is not None, "07-安全与隐私清单.md 存在（安全工程师产出）"))
            if t07 is not None:
                sbody = strip_comments(t07)
                for h in ("数据分级", "隐私底线", "风险与缓解"):
                    checks.append((bool(re.search(rf"^#+\s*{re.escape(h)}", sbody, flags=re.M)),
                                   f"安全清单章节「{h}」存在"))
                checks.append((nonempty(section_text(sbody, "数据分级")), "数据分级非空"))
        # 当前功能清单（"现在真相"基线）：发版前必须建好；此后只经 release 合并变更增量
        base = baseline_items(app_dir)
        if base is None:
            checks.append((False, "00-当前功能清单.md 存在（从技能 assets/templates/00-当前功能清单.md 复制；首版发版前把已查验的功能填进「功能条目」）"))
        else:
            checks.append((len(base) >= 1, f"00-当前功能清单.md 在案（当前 {len(base)} 项功能）"))
        g3 = state["gates"].get("G3", {})
        checks.append((g3.get("iteration") == state["iteration"], "本轮迭代已过 G3 提测门（项目经理浏览器/真机走查完成）"))
    else:
        fail("未知评审门，可选 G1 G2 G3 G4")

    hard_failed = [m for ok, m in checks if ok is False]
    for ok, m in checks:
        if ok is False:
            print(f"❌ {m}")
        else:
            print(f"✅ {m}")
    if hard_failed:
        print(f"\n✗ {g} 未通过：{len(hard_failed)} 项必须修复后重新执行 gate {g}")
        sys.exit(1)
    state["gates"][g] = {"date": date.today().isoformat(), "iteration": state["iteration"]}
    if g in PHASE_AFTER_GATE:
        state["phase"] = PHASE_AFTER_GATE[g]
    save_state(app_dir, state, f)
    nxt = PHASE_AFTER_GATE.get(g, "执行 release 发版" if g == "G4" else "")
    print(f"\n✅ {g} 通过（已记录）。" + (f"进入：{PHASE_LABEL[nxt]}" if g in PHASE_AFTER_GATE else nxt))


def merge_open_changes(app_dir, state, f):
    """把进行中的变更提案增量合并进 00-当前功能清单 并归档提案文件夹；返回合并的变更名。
    逐份校验（用户确认在案、增量格式合法、编号不冲突）后机器合并：新增追加/修改替换/移除删除。"""
    open_list = [c for c in state.get("changes", []) if c.get("state") == "open"]
    bp = baseline_path(app_dir)
    if not open_list:
        if bp.exists() and state["iteration"] > 1:
            append_history(bp, f"- [{date.today().isoformat()}] 第 {state['iteration']} 轮：修复与打磨（无功能变化）")
        return []
    if not bp.exists():
        fail("有进行中的变更提案，但 团队文档/00-当前功能清单.md 不存在——先从技能 assets/templates/ 复制模板，把当前版本的功能填好再发版")
    for c in open_list:
        p = app_dir / "团队文档" / "变更" / c["name"] / "提案.md"
        if not p.exists():
            fail(f"变更「{c['name']}」缺 提案.md（文件夹损坏；补齐或 propose {c['name']} --drop 放弃）")
        body = strip_comments(p.read_text(encoding="utf-8"))
        if not nonempty(section_text(body, "用户确认")):
            fail(f"变更「{c['name']}」提案「用户确认」为空——用户没点头不许发版（先拿到原话，或 --drop 放弃）")
        added, modified, removed = parse_delta(body)
        if not (added or modified or removed):
            fail(f"变更「{c['name']}」功能增量为空（新增/修改/移除至少一条；纯修 bug 不立提案）")
        entries = parse_entries(strip_comments(bp.read_text(encoding="utf-8")))
        if not entries:
            fail("00-当前功能清单.md 还没有功能条目——先把当前版本的功能补进去，再合并变更")
        ids = [fid for fid, _, _ in entries]
        add_ids = [fid for fid, _, _ in added]
        if len(set(add_ids)) != len(add_ids):
            fail(f"变更「{c['name']}」新增编号重复")
        dup = sorted(set(add_ids) & set(ids))
        if dup:
            fail(f"变更「{c['name']}」新增的 {dup} 已在功能清单里（新增用现有最大号顺延的新编号）")
        mod_map = {fid: (title, txt) for fid, title, txt in modified}
        if len(mod_map) != len(modified):
            fail(f"变更「{c['name']}」修改编号重复")
        rm_set = set(removed)
        unknown = sorted((set(mod_map) | rm_set) - set(ids))
        if unknown:
            fail(f"变更「{c['name']}」修改/移除的 {unknown} 不在功能清单里（改/删只能动清单里已有的编号）")
        clash = sorted(rm_set & (set(add_ids) | set(mod_map)))
        if clash:
            fail(f"变更「{c['name']}」对 {clash} 既移除又新增/修改，先理顺提案")
        merged = []
        for fid, title, txt in entries:
            if fid in rm_set:
                continue
            if fid in mod_map:
                t2, x2 = mod_map[fid]
                merged.append((fid, t2, x2))
            else:
                merged.append((fid, title, txt))
        merged.extend(added)
        rewrite_baseline(bp, merged)
        parts = []
        if added:
            parts.append("新增 " + "、".join(fid for fid, _, _ in added))
        if modified:
            parts.append("修改 " + "、".join(sorted(mod_map)))
        if removed:
            parts.append("移除 " + "、".join(sorted(rm_set)))
        append_history(bp, f"- [{date.today().isoformat()}] {c['name']}：" + "；".join(parts))
        dest = app_dir / "团队文档" / "变更" / "归档" / f"{date.today().isoformat()}-{c['name']}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        n = 2
        while dest.exists():
            dest = dest.with_name(f"{date.today().isoformat()}-{c['name']}-{n}")
            n += 1
        shutil.move(str(p.parent), str(dest))
        c["state"] = "merged"
        c["merged"] = date.today().isoformat()
        save_state(app_dir, state, f)  # 逐份落盘：中途失败已合并的不回滚
        print(f"   ✅ 变更「{c['name']}」已并入功能清单并归档：团队文档/变更/归档/{dest.name}/")
    return [c["name"] for c in open_list]


def cmd_release(args):
    app_dir = find_project(args.dir)
    state, f = load_state(app_dir)
    g3 = state["gates"].get("G3", {})
    if g3.get("iteration") != state["iteration"]:
        fail("本轮迭代尚未通过 G3 提测门，不能发版（先走查、过门）。")
    # 首版发版：功能清单落"初始发布"基线行（此后只经变更合并更新）
    bp = baseline_path(app_dir)
    if state["iteration"] == 1 and bp.exists():
        n = len(parse_entries(strip_comments(bp.read_text(encoding="utf-8"))))
        if n:
            append_history(bp, f"- [{date.today().isoformat()}] 初始发布：首次基线，共 {n} 项功能")
    merged_names = merge_open_changes(app_dir, state, f)
    rec = doc_path(app_dir, "05")
    entry = (f"\n## 第 {state['iteration']} 次发布（{date.today().isoformat()}）\n\n"
             f"- 改动：{args.note or '<由项目经理补写本次大白话改动说明>'}\n"
             f"- 已过评审门：{', '.join(sorted(g for g, v in state['gates'].items() if v.get('iteration') == state['iteration'])) or '—'}\n")
    if merged_names:
        entry += f"- 合并变更：{'、'.join(merged_names)}（功能增量已并入 00-当前功能清单，提案归档于 团队文档/变更/归档/）\n"
    rec.write_text(rec.read_text(encoding="utf-8") + entry, encoding="utf-8")
    state["iteration"] += 1
    state["phase"] = "iterate"
    save_state(app_dir, state, f)
    print(f"✅ 已发版并记录到 {rec.name}，进入第 {state['iteration']} 轮迭代。")
    if merged_names:
        print("   功能清单已更新（00-当前功能清单.md），别忘了据此同步《我的应用.md》和《使用说明.txt》。")
    else:
        print("   别忘了同步更新《我的应用.md》和《使用说明.txt》（用户可见文档）。")


def main():
    ap = argparse.ArgumentParser(description="idea-to-app 项目工具箱")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", help="应用文件夹路径（缺省自动向上查找）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化项目", parents=[common])
    p.add_argument("name")
    p.add_argument("--scale", choices=["small", "medium", "large", "xl"], default="medium",
                   help="编制：small 单人 / medium 标准班组 / large 加独立技术负责人 / xl 前后端分岗")
    p.add_argument("--type", choices=["tool", "data", "admin", "front"], default="tool",
                   help="项目类型：tool 单机工具 / data 数据脚本 / admin 管理后台 / front 商用前台")
    p.add_argument("--no-data", action="store_true", help="应用不保存用户数据（纯计算类），verify 不强制备份按钮")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("status", help="查看项目状态", parents=[common])
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("scaffold", help="按编号落文档模板", parents=[common])
    p.add_argument("doc_id")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_scaffold)

    p = sub.add_parser("dispatch", help="生成岗位派工单", parents=[common])
    p.add_argument("role", choices=sorted(DISPATCH))
    p.set_defaults(fn=cmd_dispatch)

    p = sub.add_parser("probe", help="给样品页打\"仅方向参考\"横幅并归档到 探索/", parents=[common])
    p.add_argument("file", help="样品 html 文件路径")
    p.add_argument("--label", default="", help="方案名，如：方案A-大按钮")
    p.add_argument("--out", default="", help="归档目录（默认：样品同目录/探索/）")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("verify", help="交付物静态检查", parents=[common])
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("gate", help="评审门机器校验", parents=[common])
    p.add_argument("gate", choices=["G1", "G2", "G3", "G4"])
    p.set_defaults(fn=cmd_gate)

    p = sub.add_parser("checkpoint", help="记录一块积木经用户查验通过", parents=[common])
    p.add_argument("block", help="积木块编号，如 M1（须已写在 00-项目规划书中）")
    p.add_argument("--note", default="", help="备注，如：用户已确认 / 用户明示免验（免验须在 05 留用户原话）")
    p.set_defaults(fn=cmd_checkpoint)

    p = sub.add_parser("propose", help="立一份变更提案（迭代期功能变化）", parents=[common])
    p.add_argument("name", help="变更名（中文短名，如：加导出）")
    p.add_argument("--drop", action="store_true", help="放弃一份进行中的提案（归档不合并）")
    p.set_defaults(fn=cmd_propose)

    p = sub.add_parser("release", help="发版", parents=[common])
    p.add_argument("--note", default="", help="本次大白话改动说明")
    p.set_defaults(fn=cmd_release)

    args = ap.parse_args()
    args.dir = getattr(args, "dir", None)
    args.fn(args)


if __name__ == "__main__":
    main()
