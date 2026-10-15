#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
idea-to-app 项目工具箱（项目经理的工程化执行器）——CLI 入口。

三层结构：pm.py（本文件，命令装配）/ pm_engine.py（引擎：状态机·门禁·verify·提案合并·自测）/
pm_data.py（数据：岗位卡·类型画像·契约常量）。调用方式不变：
  python "<本技能目录>/scripts/pm.py" <子命令> ...
用 --dir 指定应用文件夹；缺省时从当前目录向上查找 团队文档/00-项目状态.json。

子命令：init / status / scaffold / dispatch / probe / verify / gate / checkpoint /
        propose / release / selftest（各命令作用见 SKILL.md 工具箱表与引擎层实现）
"""
import argparse

from pm_engine import *  # noqa: F401,F403 —— 命令实现与数据（DISPATCH 等）由引擎层提供

def main():
    ap = argparse.ArgumentParser(description="idea-to-app 项目工具箱")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", help="应用文件夹路径（缺省自动向上查找）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化项目", parents=[common])
    p.add_argument("name")
    p.add_argument("--scale", choices=["small", "medium", "large", "xl"], default="small",
                   help="编制：small 单人（默认，证据不足时用） / medium 标准班组 / large 加独立技术负责人 / xl 前后端分岗")
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

    p = sub.add_parser("selftest", help="自测：门禁↔模板契约核对 + 全流程回放（改模板/门禁后必跑）", parents=[common])
    p.set_defaults(fn=cmd_selftest)

    args = ap.parse_args()
    args.dir = getattr(args, "dir", None)
    args.fn(args)


if __name__ == "__main__":
    main()
