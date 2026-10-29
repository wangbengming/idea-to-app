#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""idea-to-app 引擎层（pm_engine）——状态机、命令实现、verify、四道门、提案合并、自测。

入口 pm.py 只做 CLI 装配；数据（岗位卡/类型画像/契约常量）在 pm_data.py；
机器格式权威说明见 references/file-formats.md。
"""
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from pm_data import (BASELINE_DOC_SECTIONS, BRIEF_HEADER, DISPATCH, DOC_FILES, G3_DOC_SECTIONS,
                     G4_07_NONEMPTY, G4_DOC_SECTIONS_07, PHASE_AFTER_GATE, PHASE_LABEL,
                     PLAN_DOC_SECTIONS, PROPOSAL_DOC_SECTIONS, TYPE_PROFILES)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_ROOT / "assets" / "templates"


def type_profile(vtype):
    """类型画像（未知类型按 tool 兜底）；机器差异一表收拢，见 pm_data.TYPE_PROFILES。"""
    return TYPE_PROFILES.get(vtype, TYPE_PROFILES["tool"])

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
    try:
        return json.loads(f.read_text(encoding="utf-8")), f
    except json.JSONDecodeError as e:
        fail(f"状态文件不是合法 JSON：{f}（第 {e.lineno} 行 {e.msg}）——手工编辑过？修好再继续，或删掉重新 init（会丢门禁与查验记录）")


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


def fid_num(fid):
    """F-编号按数字比较（F-1 与 F-001 视为同一编号，避免写法差异造成编号混乱）。"""
    return int(fid.split("-")[1])


def parse_entries(text):
    """解析 F-编号功能条目（### 或 #### 标题行起），返回有序 [(编号, 标题行, 条目正文)]。
    条目正文止于下一个 F-编号标题或一二级章节标题（防止末条目吞掉后续章节，如「变更史」）。"""
    ms = list(FID_HEADER_RE.finditer(text))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        seg = text[m.end():end]
        cut = re.search(r"^#{1,2}\s", seg, flags=re.M)
        if cut:
            seg = seg[: cut.start()]
        out.append((m.group(1), m.group(0).strip(), seg))
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
    head, tail = BASELINE_DOC_SECTIONS
    m1 = re.search(rf"^##\s*{re.escape(head)}\s*$", t, flags=re.M)
    m2 = re.search(rf"^##\s*{re.escape(tail)}\s*$", t, flags=re.M)
    if not (m1 and m2 and m1.start() < m2.start()):
        fail(f"00-当前功能清单.md 缺「{head}」或「{tail}」章节（格式见技能 assets/templates/00-当前功能清单.md）")
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
    if re.search(r'[\\/:*?"<>|]|\.\.', args.name):
        fail('应用名不能包含 / \\ : * ? " < > | 或 ..（会导致文件夹位置错乱）——换个纯名字，如：我的小助手')
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
        "schema_version": 1,
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
    print(f"   类型：{type_profile(vtype)['label']}；编制：{scale}；阶段：{PHASE_LABEL[state['phase']]}")
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
    print(f"项目：{state['name']}（{type_profile(vtype)['label']} · {state['scale']}）")
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
    manuals_list = "\n".join(
        f"     - {SKILL_ROOT / 'references' / m}" for m in info.get("manuals", [])
    ) or "     - （本岗无额外手册，按【产出】要求执行）"
    brief = BRIEF_HEADER.format(
        title=info["title"],
        name=state["name"],
        scale=f"{state['scale']}（{type_profile(vtype)['label']}）",
        app_dir=app_dir,
        skill_root=SKILL_ROOT,
        task="<一句话说明本次要做什么>",
        docs_list=docs_list,
        manuals_list=manuals_list,
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
        src = changes_dir / slug
        if target is None:
            if not src.exists():
                fail(f"没有进行中的变更「{slug}」，文件夹也不存在")
            dest = changes_dir / "归档" / f"{date.today().isoformat()}-{slug}-清理"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            print(f"✅ 变更文件夹「{slug}」无状态记录（手工误建的孤儿），已收编归档：团队文档/变更/归档/{dest.name}/")
            return
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


def check_local_refs(name, t, app_dir, errors):
    """本地引用完整性：src/href 指向的应用文件夹内文件必须真实存在（开源组件本地化后的白屏防线）。"""
    missing = []
    for r in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", t):
        r = r.strip()
        if not r or re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|#)", r):
            continue  # 协议地址 / 协议相对 / 锚点
        path = r.split("#", 1)[0].split("?", 1)[0]
        if path and not (app_dir / path).exists():
            missing.append(r)
    if missing:
        shown = "、".join(missing[:3]) + ("等" if len(missing) > 3 else "")
        errors.append(f"{name}：本地引用的文件不存在：{shown}（开源组件必须真的下载进应用文件夹，漏文件 = 用户双击白屏）")


def check_html_text(name, t, errors, warns, external="all", check_viewport=True, app_dir=None, esm_ok=False):
    """单个 HTML 文本的通用检查。external: all=src/href 都查（单文件自包含），src=只查资源加载；
    app_dir 提供时校验本地引用文件存在；esm_ok=True 放行 ES module（本地服务形态走 localhost，不受 file:// 限制）。"""
    pat = r"""(?:src|href)\s*=\s*["']https?://[^"']+|@import\s+url\(\s*["']?https?://[^"')]+|url\(\s*["']?https?://[^"')]+"""
    if external == "src":
        pat = r"""(?:src)\s*=\s*["']https?://[^"']+|@import\s+url\(\s*["']?https?://[^"')]+|url\(\s*["']?https?://[^"')]+"""
    externals = re.findall(pat, t, flags=re.I)
    if externals:
        errors.append(f"{name}：引用了 {len(externals)} 处外部网络资源（{externals[0][:60]}...）——离线可用不能依赖网络，必须改为内联/本地")
    # 现代技术栈基线：过时技术机器拦截（基线见 references/tech-recipes.md）
    # 注1：裸 $( 不拦——现代常有人写 const $ = q => document.querySelector(q) 简写，属合法主流
    # 注2：jQuery 按脚本块粒度拦——块内出现 typeof/window jQuery 检测形态（二开库的兼容分支）整块放行；
    #     无检测形态的应用代码块、脚本外引用（如 src="lib/jquery.min.js"）照拦
    legacy_pat = r"jquery|\$\.ajax\s*\(|\$\.get\s*\(|\$\.post\s*\(|\$\(\s*document\s*\)\s*\.\s*ready|XMLHttpRequest|document\.write\s*\("

    def _legacy_hits(text):
        return {m.group(0) for m in re.finditer(legacy_pat, text, flags=re.I)}

    legacy = set()
    pos = 0
    for m in re.finditer(r"<script\b[^>]*>.*?</script\s*>", t, flags=re.I | re.S):
        legacy |= _legacy_hits(t[pos:m.start()])
        block = m.group(0)
        if not re.search(r"(?:typeof\s+[Jj][Qq]uery|window\s*\.\s*[Jj][Qq]uery)", block):
            legacy |= _legacy_hits(block)
        pos = m.end()
    legacy |= _legacy_hits(t[pos:])
    legacy = sorted(legacy)
    if legacy:
        errors.append(f"{name}：发现过时技术「{'、'.join(legacy)}」（现代技术栈基线禁用：用原生 DOM API、fetch、模板字符串等当前主流写法替代，见 tech-recipes.md「现代技术栈基线」）")
    # 体感与交互工艺（tech-recipes）：系统弹窗与内联事件机器拦截（教学注释不拦——先剥 HTML 注释）
    tc = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    dialogs = sorted({m.group(1).lower() for m in re.finditer(r"\b(confirm|alert|prompt)\s*\(", tc)})
    if dialogs:
        errors.append(f"{name}：发现系统弹窗「{'、'.join(dialogs)}(」（体感禁令：阻塞且与页面脱节——改用页面内 toast/撤销条/<dialog>，见 tech-recipes.md「体感与交互工艺」）")
    inline_ev = re.findall(r"""<\w+[^>]*?\son(?:click|submit|change|input|keyup|keydown|load|error|mouseover|dblclick)\s*=""", tc, flags=re.I)
    if inline_ev:
        errors.append(f"{name}：{len(inline_ev)} 处内联事件（onclick= 等）——事件绑定写在 JS（addEventListener/事件委托），innerHTML 拼 onclick 是逻辑混乱之源，见 tech-recipes.md「体感与交互工艺」")
    # file:// 兼容：ES module 外部文件双击打开会被浏览器拦截（本地组件须用 UMD/IIFE 发行版；服务端形态不受限）
    if not esm_ok:
        esm_ext = re.findall(r"""<script[^>]*\btype=["']module["'][^>]*\bsrc=["'][^"']+["']""", t, flags=re.I)
        esm_inline = [m for m in re.finditer(r"""<script[^>]*\btype=["']module["'][^>]*>(.*?)</script>""", t, flags=re.I | re.S)
                      if re.search(r"\bimport\b", m.group(1))]
        if esm_ext or esm_inline:
            errors.append(f"{name}：{len(esm_ext) + len(esm_inline)} 处 ES module 引用（file:// 双击打开会被浏览器拦截——"
                          f"本地组件须选 UMD/IIFE 发行版用普通 script 引用或内联；本地服务形态不受此限）")
    if app_dir is not None:
        check_local_refs(name, t, app_dir, errors)
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
        check_html_text(name, t, errors, warns, check_viewport=(vtype != "front"), app_dir=app_dir)
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
        check_html_text(p.name, p.read_text(encoding="utf-8", errors="replace"), errors, warns, app_dir=app_dir)
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
        check_html_text(p.name, p.read_text(encoding="utf-8", errors="replace"), errors, warns, external="src", app_dir=app_dir, esm_ok=True)
    return errors, warns


def run_verify(app_dir, state):
    """按项目类型分派交付物静态检查，返回 (hard_errors, warnings) 列表。"""
    vtype = state.get("type", "tool")
    kind = type_profile(vtype)["verify"]
    if kind == "data":
        return verify_data(app_dir, state)
    if kind == "admin":
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


def gate_checks_g1(app_dir, state):
    """G1 需求门：PRD 在案、按类型画像的章节齐全、有可勾选 AC、不做清单非空。"""
    checks = []
    vtype = state.get("type", "tool")

    t = read_doc(app_dir, "01")
    checks.append((t is not None, "01-需求文档-PRD.md 存在"))
    if t is not None:
        body = strip_comments(t)
        for h in type_profile(vtype)["g1"]:
            checks.append((bool(re.search(rf"^#+\s*{re.escape(h)}", body, flags=re.M)), f"章节「{h}」存在"))
        acs = ac_ids(body)
        checks.append((len(acs) >= 1, f"有可勾选的验收标准（当前 {len(acs)} 条 AC）"))
        checks.append((nonempty(section_text(body, "不做清单")), "不做清单非空"))
        checks.append((nonempty(section_text(body, "待确认")) or True, "待确认清单（可为空）"))
    return checks


def gate_checks_g2(app_dir, state):
    """G2 设计门：02 章节与 AC 追溯 + 规划书积木块覆盖性（不私加、不漏掉）。"""
    checks = []
    vtype = state.get("type", "tool")

    t01, t02 = read_doc(app_dir, "01"), read_doc(app_dir, "02")
    checks.append((t01 is not None and ac_ids(strip_comments(t01)), "01-PRD 存在且含 AC"))
    checks.append((t02 is not None, "02-设计方案.md 存在"))
    if t02 is not None:
        body = strip_comments(t02)
        for h in type_profile(vtype)["g2"]:
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
        for h in PLAN_DOC_SECTIONS:
            checks.append((bool(re.search(rf"^#+\s*{re.escape(h)}", pbody, flags=re.M)) and blocks,
                           f"章节「{h}」存在且至少 1 块（当前 {len(blocks)} 块）"))
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
    # 产品先审留痕（phases 阶段2）：中型以上必经，机器校验存在，防跳过先审直达用户确认
    if state.get("scale", "small") != "small":
        checks.append(((app_dir / "团队文档" / "派工" / "pm-审核-设计.md").exists(),
                       "产品先审留痕存在（团队文档/派工/pm-审核-设计.md，中型以上必经，见 phases 阶段2）"))
    return checks


def gate_checks_g3(app_dir, state):
    """G3 提测门：verify 静态检查 + 03 契约节非空 + 06 AC 追溯 + 二开组件许可证留痕 + 变更提案要件。"""
    checks = []

    state2, _ = load_state(app_dir)
    errors, _ = run_verify(app_dir, state2)
    checks.append((not errors, "交付物静态检查（verify）" + ("" if not errors else "：" + "；".join(errors))))
    t03 = read_doc(app_dir, "03")
    if t03 is None:
        checks.append((True, "03-技术方案.md 不存在（小型编制兼容；方案用大白话讲清并征得用户同意后开工）"))
    else:
        for h, hint in G3_DOC_SECTIONS:
            checks.append((nonempty(section_text(t03, h)), f"03「{h}」非空（{hint}）"))
    t01, t06 = read_doc(app_dir, "01"), read_doc(app_dir, "06")
    checks.append((t06 is not None, "06-开发自查清单.md 存在"))
    if t01 and t06 is not None:
        need = ac_ids(strip_comments(t01))
        body = strip_comments(t06)
        unchecked = [a for a in need if not re.search(rf"- \[[xX]\]\s*{a}\b", body)]
        checks.append((need and not unchecked,
                       f"自查清单：{len(need) - len(unchecked)}/{len(need)} 条 AC 已实现"
                       + (f"，未勾选 {unchecked}" if unchecked else "")))
    # 开源优先配套审计：交付物本地引用了二开组件（.min 压缩件 / lib/ vendor/ 目录）时，03 须记组件许可证
    vendored = set()
    for p in app_dir.glob("*.html"):
        for r in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+\.(?:js|css))["']""", p.read_text(encoding="utf-8", errors="replace")):
            r = r.strip()
            if not re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|#)", r) and (".min." in r or r.startswith(("lib/", "vendor/"))):
                vendored.add(r)
    if vendored:
        t03v = read_doc(app_dir, "03")
        if t03v is not None:
            checks.append((bool(re.search(r"许可证", strip_comments(t03v))),
                           f"03 记录了二开组件的许可证/来源（检测到本地组件：{sorted(vendored)[:3]}）"))
    # 变更提案（迭代期）：挂着 open 提案时逐份校验要件齐全；一次只做一份，其余排队等下一轮
    open_changes = [c for c in state.get("changes", []) if c.get("state") == "open"]
    if len(open_changes) > 1:
        checks.append((False, "进行中的变更提案应 ≤1（一次只做一份；其余诉求先记\"以后再说\"，做完发版再立下一份）："
                       + "、".join(c["name"] for c in open_changes)))
    for c in open_changes:
        p = app_dir / "团队文档" / "变更" / c["name"] / "提案.md"
        checks.append((p.exists(), f"变更「{c['name']}」：提案文件存在"))
        if not p.exists():
            continue
        body = strip_comments(p.read_text(encoding="utf-8"))
        for h, hint in PROPOSAL_DOC_SECTIONS:
            checks.append((nonempty(section_text(body, h)), f"变更「{c['name']}」：「{h}」非空（{hint}）"))
        added, modified, removed = parse_delta(body)
        checks.append((bool(added or modified or removed),
                       f"变更「{c['name']}」：功能增量至少一条（当前 新增{len(added)}/修改{len(modified)}/移除{len(removed)}）"))
        base = baseline_items(app_dir)
        if base:
            nums = {fid_num(fid) for fid, _, _ in base}
            bad = sorted(f for f in ({fid for fid, _, _ in modified} | set(removed)) if fid_num(f) not in nums)
            checks.append((not bad, f"变更「{c['name']}」：修改/移除的编号都在功能清单里" + (f"（未知 {bad}）" if bad else "")))
    # 产品先审留痕（phases 阶段3）：中型以上必经，机器校验存在，防跳过先审直达用户意见关
    if state.get("scale", "small") != "small":
        checks.append(((app_dir / "团队文档" / "派工" / "pm-审核-技术.md").exists(),
                       "产品先审留痕存在（团队文档/派工/pm-审核-技术.md，中型以上必经，见 phases 阶段3）"))
    return checks


def gate_checks_g4(app_dir, state):
    """G4 发布门：测试报告与严重 bug、积木块全部查验、安全清单、功能清单在案、本轮已过 G3。"""
    checks = []
    vtype = state.get("type", "tool")

    t01, t04 = read_doc(app_dir, "01"), read_doc(app_dir, "04")
    checks.append((t04 is not None, "04-测试报告.md 存在"))
    if t04 is not None:
        body = strip_comments(t04)
        bugs = re.findall(r"- BUG-\d+\s*\|\s*(严重|一般|建议)\s*\|[^|]*\|\s*(open|fixed)", body)
        sev_open = [b for b in bugs if b[0] == "严重" and b[1] == "open"]
        checks.append((not sev_open, f"无 open 状态的严重 bug（当前 bug {len(bugs)} 条，严重 open {len(sev_open)} 条）"))
        for h in type_profile(vtype)["g4_extra"]:
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
            for h in G4_DOC_SECTIONS_07:
                checks.append((bool(re.search(rf"^#+\s*{re.escape(h)}", sbody, flags=re.M)),
                               f"安全清单章节「{h}」存在"))
            for h in G4_07_NONEMPTY:
                checks.append((nonempty(section_text(sbody, h)), f"安全清单「{h}」非空"))
    # 当前功能清单（"现在真相"基线）：发版前必须建好；此后只经 release 合并变更增量
    base = baseline_items(app_dir)
    if base is None:
        checks.append((False, "00-当前功能清单.md 存在（从技能 assets/templates/00-当前功能清单.md 复制；首版发版前把已查验的功能填进「功能条目」）"))
    else:
        checks.append((len(base) >= 1, f"00-当前功能清单.md 在案（当前 {len(base)} 项功能）"))
    g3 = state["gates"].get("G3", {})
    checks.append((g3.get("iteration") == state["iteration"], "本轮迭代已过 G3 提测门（项目经理浏览器/真机走查完成）"))
    return checks


GATE_CHECKS = {"G1": gate_checks_g1, "G2": gate_checks_g2, "G3": gate_checks_g3, "G4": gate_checks_g4}


def cmd_gate(args):
    app_dir = find_project(args.dir)
    state, f = load_state(app_dir)
    g = args.gate
    fn = GATE_CHECKS.get(g)
    if fn is None:
        fail("未知评审门，可选 G1 G2 G3 G4")
    checks = fn(app_dir, state)
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
        entry_nums = {fid_num(fid) for fid, _, _ in entries}
        add_ids = [fid for fid, _, _ in added]
        add_nums = [fid_num(f) for f in add_ids]
        if len(set(add_nums)) != len(add_nums):
            fail(f"变更「{c['name']}」新增编号重复（F-1 与 F-001 视为同一编号）")
        dup = sorted({f for f in add_ids if fid_num(f) in entry_nums})
        if dup:
            fail(f"变更「{c['name']}」新增的 {dup} 已在功能清单里（新增用现有最大号顺延的新编号）")
        mod_map = {fid_num(fid): (title, txt) for fid, title, txt in modified}
        if len(mod_map) != len(modified):
            fail(f"变更「{c['name']}」修改编号重复（F-1 与 F-001 视为同一编号）")
        rm_nums = {fid_num(f) for f in removed}
        rm_orig = {fid_num(f): f for f in removed}
        refs = {fid for fid, _, _ in modified} | set(removed)
        unknown = sorted(f for f in refs if fid_num(f) not in entry_nums)
        if unknown:
            fail(f"变更「{c['name']}」修改/移除的 {unknown} 不在功能清单里（改/删只能动清单里已有的编号）")
        clash_nums = rm_nums & (set(add_nums) | set(mod_map))
        if clash_nums:
            fail(f"变更「{c['name']}」对 {sorted(rm_orig[n] for n in clash_nums)} 既移除又新增/修改，先理顺提案")
        merged = []
        for fid, title, txt in entries:
            n = fid_num(fid)
            if n in rm_nums:
                continue
            if n in mod_map:
                t2, x2 = mod_map[n]
                t2 = re.sub(r"F-\d+", fid, t2, count=1)  # 条目保留基线的规范编号拼写
                merged.append((fid, t2, x2))
            else:
                merged.append((fid, title, txt))
        merged.extend(added)
        rewrite_baseline(bp, merged)
        parts = []
        if added:
            parts.append("新增 " + "、".join(fid for fid, _, _ in added))
        if modified:
            mod_orig = {fid_num(fid): fid for fid, _, _ in modified}
            parts.append("修改 " + "、".join(mod_orig[n] for n in sorted(mod_map)))
        if removed:
            parts.append("移除 " + "、".join(rm_orig[n] for n in sorted(rm_nums)))
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
    g4 = state["gates"].get("G4", {})
    if state.get("scale") != "small" and g4.get("iteration") != state["iteration"]:
        fail("中型以上编制发版前必须通过本轮 G4 发布门（积木块全部经用户查验 + 安全清单 + 功能清单在案）；小项目豁免。")
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

# ---------- 自测（selftest）----------
# 两个职责：① 契约核对——门禁要求的章节，每类模板里必须真的有（防"改了模板忘改门禁"的静默漂移）；
# ② 全流程回放——用最小夹具把 init→G1→G2→checkpoint→verify→G3→G4→release→propose→合并 全走一遍
# （含负例：门禁该拦的必须拦住）。改模板、改门禁、改合并逻辑后必跑。

def _st_shell(cmd_list):
    """子进程跑一条 pm.py 命令，返回 (returncode, 合并输出)。"""
    import subprocess
    _PM_ENTRY = Path(__file__).resolve().parent / "pm.py"
    r = subprocess.run(
        [sys.executable, str(_PM_ENTRY), *cmd_list],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


ST_DOC01 = """# 01 需求文档-PRD（selftest 夹具）
## 产品定义
记一笔账的小工具。
## 用户画像
中老年，手机与电脑混用。
## 用户故事
用户打开就能记一笔。
## 用户旅程
打开 → 点大按钮 → 完成。
## 同类调研
参考两款记账工具。
## 产品特色
差异化：点大按钮即记完。招牌记忆点：一键记一笔。最不像：不做成表格软件。
## 必须有
- [ ] AC-01 记一笔 ≤2 次点击
- [ ] AC-02 列表 1 屏显示最近 10 条
## 以后再说
- 月度统计
## 不做清单
- 多用户
## 待确认
（无）
"""

ST_DOC02 = """# 02 设计方案（selftest 夹具）
## 风格定位
气质：克制、家常、清楚；族：瑞士极简。
## 页面清单
单页：记账页（覆盖 AC-01、AC-02）。
## 交互
点大按钮即记一笔；列表默认显示 10 条。
## 视觉
具体值全在令牌节。
## 设计令牌
:root { --c-primary: #92400E; }
## 趋势侦察
查了当前主流工具类界面。
## 体验自查
即时反馈：过。
## 基线自查
克制：无渐变无发光。
"""

ST_DOC00 = """# 00 项目规划书（selftest 夹具）
## 项目总览
单文件网页小工具。
## 积木块分解
### M1 骨架
- 包含 AC：AC-01, AC-02
- 前置：无
- 完成标准：能记账能看列表
## 查验安排
拼好演示给用户。
## 发布与部署预排
暂无。
## 变更记录
（无）
"""

ST_DOC03 = """# 03 技术方案（selftest 夹具）
## 选型说明
结论：方案 A 单文件网页，引入阶梯 L0 纯手写。需求匹配：双击即用。主流依据：原生 HTML/CSS/JS。否决项：引 React 需构建链。
大白话版本：一个双击就能用的网页，不用装任何东西。
## 逻辑架构
状态清单：items 数组单存 localStorage；数据流：事件→改 items→render()；边界：空输入必填拦截、恢复文件校验；分层：数据/渲染/事件三段。
## 用户意见
用户：可以，就这么做。
"""

ST_DOC04 = """# 04 测试报告（selftest 夹具）
## 测试用例
| 编号 | 步骤 | 预期 | 实际 | 通过 |
|---|---|---|---|---|
| TC-01 | 覆盖 AC-01 | 2 击内记一笔 | 通过 | ✅ |
| TC-02 | 覆盖 AC-02 | 1 屏 10 条 | 通过 | ✅ |
## bug 清单
- BUG-001 | 一般 | 按钮偏小 | fixed
## 待项目经理走查清单
- 主流程一遍
"""

ST_DOC06 = """# 06 开发自查清单（selftest 夹具）
## AC 自查
- [x] AC-01 已实现：大按钮记一笔
- [x] AC-02 已实现：列表显示 10 条
## 自审记录
三人格各 1 条，已修。
"""

ST_DOC07 = """# 07 安全与隐私清单（selftest 夹具）
## 数据分级
记账记录存 localStorage：内部级。
## 存储与传输
纯本地，不上传。
## 输入与攻击面
无外联、无文件操作。
## 隐私底线
最小化收集，可导出。
## 风险与缓解
- [一般] 明文 localStorage | 可接受 | fixed
"""

ST_BASELINE = """# 00 当前功能清单（selftest 夹具）

## 功能条目

### F-001 记一笔账
- 说明：点大按钮记一笔
- 来源：AC-01

### F-002 看账单
- 说明：列表显示最近 10 条
- 来源：AC-02

## 变更史

- [2026-01-01] 初始发布：首次基线，共 2 项功能
"""

ST_PROPOSAL = """# 变更提案：加导出（selftest 夹具）
## 为什么改
用户："想把账拿去打印。"
## 改什么
加导出按钮，点击下载 csv 文件。
## 用户确认
"可以，就这样改。"
## 功能增量
### 新增
#### F-003 导出账单
- 说明：点导出下载 csv
- 来源：本轮提案
### 修改
#### F-001 记一笔账
- 说明：按钮加大一号，其余不变
- 来源：本轮提案（调整）
### 移除
- F-002：用户说用不上
## 任务安排
- 新增块 M2「能导出了」
"""

ST_HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>小账本</title>
</head>
<body>
<button id="add">记一笔</button>
<button id="backup">备份</button>
<script>
const b = document.querySelector('#add');
b.addEventListener('click', () => { b.textContent = '已记 1 笔'; });
</script>
</body>
</html>
"""

ST_PROPOSAL_FID = """# 变更提案：改输入（selftest 夹具·F-编号归一）
## 为什么改
用户："数字太难按。"
## 改什么
数字键盘放大，加夜间模式。
## 用户确认
"好。"
## 功能增量
### 修改
#### F-1 记一笔账
- 说明：数字键盘放大到 48px
- 来源：本轮提案（调整）
### 新增
#### F-9 夜间模式
- 说明：一键切换深色
- 来源：本轮提案
## 任务安排
- 并入现有块
"""

ST_ADMIN_PY = '''# selftest 夹具：最小合规后台（verify_admin 正路径）
import hashlib
import sqlite3
import webbrowser

hashlib.pbkdf2_hmac("sha256", b"x", b"s", 1)  # 密码 pbkdf2 加密存储
conn = sqlite3.connect("data.db")  # SQLite 数据层
print("登录 / 备份数据")
webbrowser.open("http://127.0.0.1:8765")
'''

ST_ADMIN_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
python 服务.py
pause
"""


def cmd_selftest(args):
    import tempfile
    results = []  # (名称, 是否通过, 失败时的输出摘录)

    def check(name, ok, out=""):
        results.append((name, bool(ok), (out or "")[:400]))

    # —— A. 契约核对：门禁要求的章节，每类模板里必须真的有 ——
    for vtype, prof in TYPE_PROFILES.items():
        check(f"契约[画像] {vtype} 必备键齐全", set(prof) == {"label", "g1", "g2", "g4_extra", "verify"} and bool(prof["label"]))
        check(f"契约[画像] {vtype} verify 分派合法", prof["verify"] in ("html", "data", "admin"))
        pairs = [
            ("01", prof["g1"]),
            ("02", prof["g2"]),
            ("04", prof["g4_extra"]),
            ("03", [h for h, _ in G3_DOC_SECTIONS]),
            ("07", list(G4_DOC_SECTIONS_07)),
            ("00", list(PLAN_DOC_SECTIONS)),
        ]
        for doc_id, headers in pairs:
            t = template_for(vtype, DOC_FILES[doc_id]).read_text(encoding="utf-8")
            for h in headers:
                check(f"契约[{vtype}] {DOC_FILES[doc_id]} 含「{h}」",
                      re.search(rf"^#+\s*{re.escape(h)}", t, flags=re.M))
    tb = (TEMPLATES / "00-当前功能清单.md").read_text(encoding="utf-8")
    for h in BASELINE_DOC_SECTIONS:
        check(f"契约[功能清单] 含「{h}」", re.search(rf"^##\s*{re.escape(h)}\s*$", tb, flags=re.M))
    tp = (TEMPLATES / "变更提案.md").read_text(encoding="utf-8")
    for h, _ in PROPOSAL_DOC_SECTIONS:
        check(f"契约[提案] 含「{h}」", re.search(rf"^##\s*{re.escape(h)}\s*$", tp, flags=re.M))
    check("契约[提案] 含「功能增量」节", re.search(r"^##\s*功能增量\s*$", tp, flags=re.M))
    for sub in ("新增", "修改", "移除"):
        check(f"契约[提案] 功能增量含「{sub}」小节", re.search(rf"^###\s*{sub}\s*$", tp, flags=re.M))
    for role, info in DISPATCH.items():
        check(f"契约[派工] {role} 上游文档编号合法", set(info["docs"]) <= set(DOC_FILES))
        check(f"契约[派工] {role} 类型增量键合法", set(info.get("type_must", {})) <= set(TYPE_PROFILES))
        check(f"契约[派工] {role} 手册清单非空", bool(info.get("manuals")))
        for m in info.get("manuals", []):
            check(f"契约[派工] {role} 手册存在 {m}", (SKILL_ROOT / "references" / m).exists())

    # —— B. 全流程回放（tool · medium）——
    with tempfile.TemporaryDirectory(prefix="pm-selftest-") as td:
        tmp = Path(td)
        app = tmp / "selftest-app"
        D = app / "团队文档"

        def run(*a):
            return _st_shell([*a, "--dir", str(app)])

        def wdoc(doc_id, text):
            doc_path(app, doc_id).write_text(text, encoding="utf-8")

        rc, out = _st_shell(["init", "selftest-app", "--type", "tool", "--scale", "medium", "--dir", str(tmp)])
        check("流程 init", rc == 0, out)
        rc, out = run("gate", "G1")
        check("G1 未填 PRD 时拦截", rc != 0, out)
        wdoc("01", ST_DOC01)
        rc, out = run("gate", "G1")
        check("G1 填写后通过", rc == 0, out)
        wdoc("02", ST_DOC02)
        wdoc("00", ST_DOC00)
        rc, out = run("gate", "G2")
        check("G2 拦截缺先审留痕（中型以上）", rc != 0 and "先审" in out, out)
        (D / "派工").mkdir(parents=True, exist_ok=True)
        (D / "派工" / "pm-审核-设计.md").write_text("审核三查通过（selftest 夹具）", encoding="utf-8")
        rc, out = run("gate", "G2")
        check("G2 通过", rc == 0, out)
        wdoc("00", ST_DOC00 + "\n### M2 私货\n- 包含 AC：AC-99\n")
        rc, out = run("gate", "G2")
        check("G2 拦截规划私加 AC", rc != 0 and "AC-99" in out, out)
        wdoc("00", ST_DOC00)
        rc, out = run("dispatch", "pm")
        check("dispatch 生成派工单并留痕", rc == 0 and (D / "派工" / "pm-brief.md").exists(), out)
        rc, out = run("checkpoint", "M1")
        check("checkpoint 未打勾时拦截", rc != 0, out)
        wdoc("06", ST_DOC06)
        rc, out = run("checkpoint", "M1", "--note", "用户已确认")
        check("checkpoint 通过", rc == 0, out)
        html = app / "小账本.html"
        html.write_text(ST_HTML, encoding="utf-8")
        rc, out = run("verify")
        check("verify 通过", rc == 0, out)
        html.write_text(ST_HTML.replace("</body>", '<script src="lib/jquery.min.js"></script></body>'), encoding="utf-8")
        rc, out = run("verify")
        check("verify 拦截过时技术/缺失本地引用", rc != 0, out)
        html.write_text(ST_HTML.replace('id="add">记一笔', 'id="add" onclick="go()">记一笔')
                        .replace("b.textContent = '已记 1 笔'; });", "alert('已记 1 笔'); });"), encoding="utf-8")
        rc, out = run("verify")
        check("verify 拦截系统弹窗/内联事件（体感禁令）", rc != 0 and "体感" in out, out)
        html.write_text(ST_HTML, encoding="utf-8")
        wdoc("03", ST_DOC03.replace("## 逻辑架构\n状态清单：items 数组单存 localStorage；数据流：事件→改 items→render()；边界：空输入必填拦截、恢复文件校验；分层：数据/渲染/事件三段。\n", ""))
        rc, out = run("gate", "G3")
        check("G3 拦截缺「逻辑架构」的 03", rc != 0 and "逻辑架构" in out, out)
        (D / "派工" / "pm-审核-技术.md").unlink(missing_ok=True)
        wdoc("03", ST_DOC03)
        rc, out = run("gate", "G3")
        check("G3 拦截缺先审留痕（中型以上）", rc != 0 and "先审" in out, out)
        (D / "派工" / "pm-审核-技术.md").write_text("审核三查通过（selftest 夹具）", encoding="utf-8")
        rc, out = run("gate", "G3")
        check("G3 通过", rc == 0, out)
        rc, out = run("gate", "G4")
        check("G4 缺安全清单/功能清单时拦截", rc != 0, out)
        wdoc("04", ST_DOC04)
        wdoc("07", ST_DOC07)
        (D / "00-当前功能清单.md").write_text(ST_BASELINE, encoding="utf-8")
        rc, out = run("gate", "G4")
        check("G4 通过", rc == 0, out)
        rc, out = run("release", "--note", "首版")
        check("release 首版", rc == 0, out)
        rc, out = run("propose", "加导出")
        check("propose 立提案", rc == 0, out)
        rc, out = run("propose", "加导出")
        check("propose 重名拦截", rc != 0, out)
        rc, out = run("gate", "G3")
        check("G3 拦截要件不齐的提案", rc != 0, out)
        (D / "变更" / "加导出" / "提案.md").write_text(ST_PROPOSAL, encoding="utf-8")
        rc, out = run("gate", "G3")
        check("G3 提案要件齐全通过", rc == 0, out)
        rc, out = run("gate", "G4")
        check("G4 第二轮通过", rc == 0, out)
        rc, out = run("release", "--note", "加导出")
        check("release 合并变更", rc == 0, out)
        state = json.loads((D / "00-项目状态.json").read_text(encoding="utf-8"))
        check("release 后迭代 +1（第 3 轮）", state["iteration"] == 3)
        entries = baseline_items(app)
        check("合并后条目 = F-001, F-003", [f for f, _, _ in entries] == ["F-001", "F-003"])
        check("F-001 已被提案修改覆盖", any("加大一号" in txt for f, _, txt in entries if f == "F-001"))
        hist = (D / "00-当前功能清单.md").read_text(encoding="utf-8")
        check("变更史留痕（含移除 F-002）", "加导出" in hist and "移除 F-002" in hist)
        check("提案已归档", any((D / "变更" / "归档").glob("*加导出*")))
        rc, out = run("release", "--note", "不应发出去")
        check("release 无本轮 G3 时拦截", rc != 0, out)

        # —— B2. 行为专项（verify 三防线 / 提案 ≤1 / release 强制 G4 / F-编号归一 / 孤儿收编 / 许可证留痕）——
        html.write_text(ST_HTML.replace("</head>", '<script type="module" src="lib/mod.js"></script></head>'), encoding="utf-8")
        rc, out = run("verify")
        check("verify 拦截 ESM 外部引用（file:// 兼容）", rc != 0 and "ES module" in out, out)
        (app / "lib").mkdir(exist_ok=True)
        (app / "lib" / "ok.js").write_text("/* ok */", encoding="utf-8")
        html.write_text(ST_HTML.replace("</body>", '<script src="lib/ok.js"></script><script>if (typeof jQuery !== "undefined") { jQuery.fn.plugin = function(){}; }</script></body>'), encoding="utf-8")
        rc, out = run("verify")
        check("verify 放行 jQuery 特性检测块（二开库兼容分支）", rc == 0, out)
        html.write_text(ST_HTML.replace("</body>", '<script src="lib/ok.js"></script><script>jQuery.ajax({url:"/x"});</script></body>'), encoding="utf-8")
        rc, out = run("verify")
        check("verify 拦截真实 jQuery 调用", rc != 0 and "过时技术" in out, out)
        html.write_text(ST_HTML, encoding="utf-8")

        rc, out = run("propose", "改输入")
        check("propose 立第二份提案", rc == 0, out)
        rc, out = run("propose", "排队等")
        check("propose 立第三份提案", rc == 0, out)
        rc, out = run("gate", "G3")
        check("G3 拦截多份 open 提案（一次只做一份）", rc != 0 and "应 ≤1" in out, out)
        rc, out = run("propose", "排队等", "--drop")
        check("--drop 放弃排队提案", rc == 0, out)
        (D / "变更" / "改输入" / "提案.md").write_text(ST_PROPOSAL_FID, encoding="utf-8")
        rc, out = run("gate", "G3")
        check("G3 通过（F-1 按数字归一识别）", rc == 0, out)
        rc, out = run("release", "--note", "没过G4")
        check("中型 release 强制本轮 G4", rc != 0 and "G4" in out, out)
        rc, out = run("gate", "G4")
        check("G4 第三轮通过", rc == 0, out)
        rc, out = run("release", "--note", "改输入")
        check("release 合并 F-归一提案", rc == 0, out)
        fids = [f for f, _, _ in baseline_items(app)]
        check("F-1 命中 F-001（保留规范拼写）且 F-9 追加", fids == ["F-001", "F-003", "F-9"], str(fids))

        orphan = D / "变更" / "手滑建的"
        orphan.mkdir(parents=True, exist_ok=True)
        (orphan / "提案.md").write_text("# 空", encoding="utf-8")
        rc, out = run("propose", "手滑建的")
        check("孤儿文件夹挡住同名 propose", rc != 0 and "已存在" in out, out)
        rc, out = run("propose", "手滑建的", "--drop")
        check("--drop 收编孤儿文件夹", rc == 0 and "收编归档" in out and any((D / "变更" / "归档").glob("*手滑建的*清理*")), out)
        rc, out = run("propose", "手滑建的")
        check("收编后同名可再立", rc == 0, out)
        rc, out = run("propose", "手滑建的", "--drop")
        check("--drop 正常放弃", rc == 0, out)

        (app / "lib" / "chart.min.js").write_text("/* Chart.js v4 (MIT) */", encoding="utf-8")
        html.write_text(ST_HTML.replace("</head>", '<script src="lib/chart.min.js"></script></head>'), encoding="utf-8")
        rc, out = run("gate", "G3")
        check("G3 拦截未记许可证的二开组件", rc != 0 and "许可证" in out, out)
        wdoc("03", ST_DOC03 + "\n## 组件来源\n- Chart.js 4.x（MIT 许可证）本地引用 lib/chart.min.js，未改动\n")
        rc, out = run("gate", "G3")
        check("G3 许可证在案后通过", rc == 0, out)
        html.write_text(ST_HTML, encoding="utf-8")

        # —— B3. admin 类型 verify 分支（静态路径，不起服务）——
        adm = tmp / "selftest-admin"
        rc, out = _st_shell(["init", "selftest-admin", "--type", "admin", "--scale", "small", "--dir", str(tmp)])
        check("admin init", rc == 0, out)
        (adm / "服务.py").write_text(ST_ADMIN_PY, encoding="utf-8")
        (adm / "启动.bat").write_text(ST_ADMIN_BAT, encoding="utf-8")
        rc, out = _st_shell(["verify", "--dir", str(adm)])
        check("admin verify 正路径（哈希/登录/备份/双击件）", rc == 0, out)
        (adm / "服务.py").write_text(ST_ADMIN_PY.replace('hashlib.pbkdf2_hmac("sha256", b"x", b"s", 1)', "# 密码处理省略"), encoding="utf-8")
        rc, out = _st_shell(["verify", "--dir", str(adm)])
        check("admin verify 拦截明文密码", rc != 0 and "pbkdf2" in out, out)

    # —— C. 解析器回归（v2.4 修过 parse_entries 末位吞节，此处防复发）——
    sample = "## 功能条目\n\n### F-001 甲\n- x\n\n### F-002 乙\n- y\n\n## 变更史\n\n- [2026-01-01] 初始发布\n"
    es = parse_entries(sample)
    check("parse_entries 末位条目不吞「变更史」",
          [f for f, _, _ in es] == ["F-001", "F-002"] and "变更史" not in es[-1][2])
    added, modified, removed = parse_delta(
        "## 功能增量\n### 新增\n#### F-009 t\n- s\n### 修改\n#### F-001 t\n- s\n### 移除\n- F-002：r\n")
    check("parse_delta 三节解析",
          [f for f, _, _ in added] == ["F-009"] and [f for f, _, _ in modified] == ["F-001"] and removed == ["F-002"])
    check("F-编号数字归一", fid_num("F-1") == fid_num("F-001") == 1)
    check("block_acs 解析", block_acs("### M1 x\n- 包含 AC：AC-01, AC-02\n") == ["AC-01", "AC-02"])

    fails = [(n, d) for n, ok, d in results if not ok]
    for name, ok, detail in results:
        print(("✅ " if ok else "❌ ") + name)
        if not ok and detail:
            print("    └ " + detail.replace("\n", "\n    "))
    print(f"\nselftest：{len(results)} 项，通过 {len(results) - len(fails)}，失败 {len(fails)}")
    if fails:
        sys.exit(1)
    print("✅ 全部通过：门禁↔模板契约一致，全流程回放无回归")
