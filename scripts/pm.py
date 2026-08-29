#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
idea-to-app 项目工具箱（项目经理的工程化执行器）

将 skill 的流程固化为状态机 + 机器校验：
  init      初始化项目（目录结构、模板、状态文件）
  status    查看项目状态（阶段/编制/评审门/bug）
  scaffold  按编号落一份文档模板到团队文档
  dispatch  生成岗位派工单（写入 团队文档/派工/，留审计痕迹）
  probe     给样品页打"仅方向参考"横幅并归档到 探索/
  verify    交付物静态检查（自包含/编码/备份按钮等）
  gate      评审门机器校验（G1 需求 / G2 设计 / G3 提测 / G4 发布）
  release   发版（要求当前迭代 G3 已通过），写入发布记录

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
    "01": "01-需求文档-PRD.md",
    "02": "02-设计方案.md",
    "03": "03-技术方案.md",
    "04": "04-测试报告.md",
    "05": "05-发布记录.md",
    "06": "06-开发自查清单.md",
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

# 各岗位派工单骨架（判断性内容由项目经理补齐后再派给子代理）
DISPATCH = {
    "pm": {
        "title": "产品部·产品经理",
        "docs": [],
        "output": "团队文档/01-需求文档-PRD.md（按模板填写，验收标准用固定格式 - [ ] AC-编号 内容）",
        "must": [
            "用户画像（设备/时段与环境/操作能力/心理状态）、用户旅程与核心动作（应用\"的一件事\"，10 秒内完成）",
            "同类调研：用 WebSearch 查 2~3 个同类工具，提炼常见做法（借鉴）与用户吐槽（避坑）各至少一条",
            "功能三堆清单（必须有/锦上添花/以后再说），\"必须有\"按实现顺序排序，第 1 条 = 最小可用骨架",
            "每条\"必须有\"配可勾选验收标准（能判对错的句子，禁止\"体验良好\"类虚词）",
            "不做清单、待确认清单、用户原话逐字附录",
        ],
        "bounds": [
            "不做技术选型、不定视觉/交互方案、不写代码（产品定\"做什么\"，怎么做归技术部）",
            "不替用户做决定，拿不准一律进\"待确认\"",
            "不直接面向用户，对用户的一切承诺由项目经理传达",
        ],
    },
    "design": {
        "title": "设计部·设计师（交互+视觉合一岗）",
        "docs": ["01"],
        "output": "团队文档/02-设计方案.md",
        "must": [
            "趋势侦察：用 WebSearch 查当前主流设计风格与同类应用界面，记录\"查到什么/采纳什么手法/为何适合本项目\"，并保证素材原创合规",
            "交互：页面清单、每页文字线框、关键交互（点X后发生什么，注明 100ms 内视觉反馈）、空状态/出错状态、危险操作二次确认",
            "视觉：审美基准落点——1 主色+1 强调色+中性灰阶、正文对比度≥4.5:1、字号阶梯与 8pt 网格、圆角阴影统一、动效 150~250ms、按画像适配（中老年→大字号大按钮）",
            "体验自查：即时反馈/错误预防/可达性（触摸目标≥44px）/微文案/核心动作≤3 步，逐项写\"过/不过\"",
            "覆盖 PRD 中每一条 AC 编号（G2 将做追溯校验）",
        ],
        "bounds": [
            "不增删需求：PRD 之外的想法写进\"建议\"节交项目经理，不落进设计",
            "不做技术选型，产出不含实现细节（不规定用什么库、数据怎么存）",
            "素材合规：参考风格手法但不照搬产品，只用自绘 SVG 或宽松许可证（MIT/CC0）素材内联，不用品牌 logo、不引外部字体文件、禁一切外链",
            "不直接面向用户",
        ],
    },
    "tl": {
        "title": "技术部·技术负责人/架构师",
        "docs": ["01", "02"],
        "output": "团队文档/03-技术方案.md",
        "must": [
            "架构与交付形态（tech-recipes 方案A/B/C）+ 为什么它是\"从想用到用上步骤最少\"的",
            "数据层选型：localStorage / IndexedDB / JSON 文件 / SQLite，按数据量与结构定，写明备份恢复",
            "第三方组件：确需图表/图标时下载发行文件放应用文件夹本地引用，记录名称/版本/许可证（MIT、ISC、CC0 等），严禁 CDN 外链",
            "能力边界核对：对照 tech-recipes 的 file:// 能力边界表逐条核对 PRD，做不了的功能换形态或列入不做",
            "文件结构、性能预算（>1000 条分页、>5MB 换 IndexedDB）、风险与规避",
        ],
        "bounds": [
            "不增删需求；发现需求或设计不可实现→写退回单，不自作主张变通",
            "不直接编写业务代码",
            "架构/数据层/组件一律按 references/tech-recipes.md 的规则拍板，永不抛给用户",
        ],
    },
    "dev": {
        "title": "技术部·开发工程师",
        "docs": ["02", "03"],
        "output": "应用文件夹内可运行的交付物（网页类以 assets/app-template.html 样板起步）+ 团队文档/06-开发自查清单.md",
        "must": [
            "界面与文案全部中文，不擅自扩功能",
            "自查清单每条 AC 标注 - [x] AC-xx 已实现：<说明> 或 - [ ] AC-xx 未实现：<原因>",
        ],
        "bounds": [
            "三不：不改需求范围、不换技术选型、不擅自修改设计",
            "上游文档问题写退回单，禁止静默修改上游产物",
            "不做浏览器自动化测试（真机走查归项目经理）",
        ],
    },
    "qa": {
        "title": "质量部·测试工程师",
        "docs": ["01", "02", "03"],
        "output": "团队文档/04-测试报告.md",
        "must": [
            "测试用例表（编号/步骤/预期/实际/通过否），覆盖每条 AC 编号",
            "bug 用固定格式：- BUG-编号 | 严重|一般|建议 | 标题 | open|fixed",
            "报告末尾留\"待项目经理浏览器走查清单\"（QA 不得做浏览器操作）",
        ],
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
        拿不准的点写进文末"待确认"，禁止编造；只依据输入内容工作
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


# ---------- 子命令 ----------

def cmd_init(args):
    parent = Path(args.dir).resolve() if args.dir else Path.cwd()
    app_dir = parent / args.name
    if app_dir.exists():
        fail(f"目录已存在：{app_dir}")
    scale = args.scale
    (app_dir / "团队文档" / "派工").mkdir(parents=True)
    for doc_id, fname in DOC_FILES.items():
        shutil.copy(TEMPLATES / fname, app_dir / "团队文档" / fname)
    shutil.copy(TEMPLATES / "我的应用.md", app_dir / "我的应用.md")
    shutil.copy(TEMPLATES / "使用说明.txt", app_dir / "使用说明.txt")
    state = {
        "name": args.name,
        "scale": scale,
        "hasUserData": not args.no_data,
        "phase": "requirements" if scale != "small" else "intake",
        "iteration": 1,
        "gates": {},
        "created": date.today().isoformat(),
    }
    save_state(app_dir, state, app_dir / "团队文档" / "00-项目状态.json")
    print(f"✅ 项目已初始化：{app_dir}")
    print(f"   编制：{scale}；阶段：{PHASE_LABEL[state['phase']]}")
    if scale == "small":
        print("   小型编制：不留团队文档流程，直接开发。")
        print("   下一步：开发完成后运行 verify + gate G3 检查交付物，再 release。")
    else:
        print("   下一步：python pm.py dispatch pm 生成产品经理派工单，补齐输入后派工。")


def cmd_status(args):
    app_dir = find_project(args.dir)
    state, _ = load_state(app_dir)
    print(f"项目：{state['name']}（{state['scale']}）")
    print(f"阶段：{PHASE_LABEL.get(state['phase'], state['phase'])}  迭代：第 {state['iteration']} 轮")
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


def cmd_scaffold(args):
    app_dir = find_project(args.dir)
    state, f = load_state(app_dir)
    if args.doc_id not in DOC_FILES:
        fail(f"未知文档编号 {args.doc_id}，可选：{' '.join(DOC_FILES)}")
    dest = doc_path(app_dir, args.doc_id)
    if dest.exists() and not args.force:
        fail(f"已存在 {dest.name}（--force 覆盖）")
    shutil.copy(TEMPLATES / DOC_FILES[args.doc_id], dest)
    save_state(app_dir, state, f)
    print(f"✅ 已落模板：{dest}")


def cmd_dispatch(args):
    app_dir = find_project(args.dir)
    state, _ = load_state(app_dir)
    role = args.role
    if role not in DISPATCH:
        fail(f"未知岗位 {role}，可选：{' '.join(DISPATCH)}")
    info = DISPATCH[role]
    docs_list = "\n".join(
        f"     - {app_dir / '团队文档' / DOC_FILES[d]}" for d in info["docs"]
    ) or "     - （无上游文档，以用户原话为准）"
    brief = BRIEF_HEADER.format(
        title=info["title"],
        name=state["name"],
        scale=state["scale"],
        app_dir=app_dir,
        task="<一句话说明本次要做什么>",
        docs_list=docs_list,
        output=info["output"],
        must_list="\n".join(f"  {i+1}. {m}" for i, m in enumerate(info["must"])),
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


def run_verify(app_dir, state):
    """静态检查应用文件夹内的 html 交付物，返回 (hard_errors, warnings) 列表。"""
    errors, warns = [], []
    htmls = [p for p in app_dir.glob("*.html")]
    if state.get("scale") != "small" or not htmls:
        pass
    if not htmls:
        errors.append("应用文件夹根目录没有找到 .html 交付物")
        return errors, warns
    for p in htmls:
        t = p.read_text(encoding="utf-8", errors="replace")
        externals = re.findall(
            r"""(?:src|href)\s*=\s*["']https?://[^"']+|@import\s+url\(\s*["']?https?://[^"')]+|url\(\s*["']?https?://[^"')]+""",
            t, flags=re.I)
        if externals:
            errors.append(f"{p.name}：引用了 {len(externals)} 处外部网络资源（{externals[0][:60]}...）——双击可用不能依赖网络，必须改为内联/本地")
        if not re.search(r"<meta[^>]+charset", t, flags=re.I):
            errors.append(f"{p.name}：缺少 <meta charset>（中文会乱码）")
        if not re.search(r"<title>\S+", t, flags=re.I):
            errors.append(f"{p.name}：缺少 <title>")
        if not re.search(r'name="viewport"', t, flags=re.I):
            warns.append(f"{p.name}：缺少 viewport meta（手机上打开会缩小变形）")
        if state.get("hasUserData", True) and not re.search(r"导出|备份", t):
            errors.append(f"{p.name}：有用户数据但找不到\"导出/备份\"功能（质量底线）")
        if not re.search(r"localStorage|导出|备份", t):
            warns.append(f"{p.name}：未发现数据保存机制（localStorage 或导出）")
        if re.search(r"lang=\"(?!zh)", t, flags=re.I):
            warns.append(f"{p.name}：<html lang> 不是 zh")
    return errors, warns


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
    checks = []  # (ok_hard: None|True|False, msg)

    if g == "G1":
        t = read_doc(app_dir, "01")
        checks.append((t is not None, "01-需求文档-PRD.md 存在"))
        if t is not None:
            body = strip_comments(t)
            for h in ["产品定义", "用户画像", "用户故事", "用户旅程", "同类调研", "必须有", "以后再说", "不做清单", "待确认"]:
                checks.append((bool(re.search(rf"^#+\s*{h}", body, flags=re.M)), f"章节「{h}」存在"))
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
            for h in ["页面清单", "交互", "视觉", "趋势侦察", "体验自查"]:
                checks.append((bool(re.search(rf"^#+\s*{h}", body, flags=re.M)), f"章节「{h}」存在"))
            if t01:
                need = ac_ids(strip_comments(t01))
                missing = [a for a in need if a not in body]
                checks.append((not missing, f"AC 追溯：设计覆盖 {len(need) - len(missing)}/{len(need)}"
                                             + (f"，缺 {missing}" if missing else "")))
    elif g == "G3":
        state2, _ = load_state(app_dir)
        errors, _ = run_verify(app_dir, state2)
        checks.append((not errors, "交付物静态检查（verify）" + ("" if not errors else "：" + "；".join(errors))))
        t01, t06 = read_doc(app_dir, "01"), read_doc(app_dir, "06")
        checks.append((t06 is not None, "06-开发自查清单.md 存在"))
        if t01 and t06 is not None:
            need = ac_ids(strip_comments(t01))
            body = strip_comments(t06)
            unchecked = [a for a in need if not re.search(rf"- \[[xX]\]\s*{a}\b", body)]
            checks.append((need and not unchecked,
                           f"自查清单：{len(need) - len(unchecked)}/{len(need)} 条 AC 已实现"
                           + (f"，未勾选 {unchecked}" if unchecked else "")))
    elif g == "G4":
        t01, t04 = read_doc(app_dir, "01"), read_doc(app_dir, "04")
        checks.append((t04 is not None, "04-测试报告.md 存在"))
        if t04 is not None:
            body = strip_comments(t04)
            bugs = re.findall(r"- BUG-\d+\s*\|\s*(严重|一般|建议)\s*\|[^|]*\|\s*(open|fixed)", body)
            sev_open = [b for b in bugs if b[0] == "严重" and b[1] == "open"]
            checks.append((not sev_open, f"无 open 状态的严重 bug（当前 bug {len(bugs)} 条，严重 open {len(sev_open)} 条）"))
            if t01:
                need = ac_ids(strip_comments(t01))
                missing = [a for a in need if a not in body]
                checks.append((not missing, f"AC 追溯：测试覆盖 {len(need) - len(missing)}/{len(need)}"
                                             + (f"，缺 {missing}" if missing else "")))
        checks.append(((app_dir / "使用说明.txt").exists(), "使用说明.txt 存在"))
        g3 = state["gates"].get("G3", {})
        checks.append((g3.get("iteration") == state["iteration"], "本轮迭代已过 G3 提测门（项目经理浏览器走查完成）"))
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


def cmd_release(args):
    app_dir = find_project(args.dir)
    state, f = load_state(app_dir)
    g3 = state["gates"].get("G3", {})
    if g3.get("iteration") != state["iteration"]:
        fail("本轮迭代尚未通过 G3 提测门，不能发版（先走查、过门）。")
    rec = doc_path(app_dir, "05")
    entry = (f"\n## 第 {state['iteration']} 次发布（{date.today().isoformat()}）\n\n"
             f"- 改动：{args.note or '<由项目经理补写本次大白话改动说明>'}\n"
             f"- 已过评审门：{', '.join(sorted(g for g, v in state['gates'].items() if v.get('iteration') == state['iteration'])) or '—'}\n")
    rec.write_text(rec.read_text(encoding="utf-8") + entry, encoding="utf-8")
    state["iteration"] += 1
    state["phase"] = "iterate"
    save_state(app_dir, state, f)
    print(f"✅ 已发版并记录到 {rec.name}，进入第 {state['iteration']} 轮迭代。")
    print("   别忘了同步更新《我的应用.md》和《使用说明.txt》（用户可见文档）。")


def main():
    ap = argparse.ArgumentParser(description="idea-to-app 项目工具箱")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", help="应用文件夹路径（缺省自动向上查找）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化项目", parents=[common])
    p.add_argument("name")
    p.add_argument("--scale", choices=["small", "medium", "large"], default="medium")
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

    p = sub.add_parser("release", help="发版", parents=[common])
    p.add_argument("--note", default="", help="本次大白话改动说明")
    p.set_defaults(fn=cmd_release)

    args = ap.parse_args()
    args.dir = getattr(args, "dir", None)
    args.fn(args)


if __name__ == "__main__":
    main()
