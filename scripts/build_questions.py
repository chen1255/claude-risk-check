#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_questions.py — 由 questions.json 生成 questions.js（唯一数据源构建脚本）

背景：网页版需要浏览器可直接 <script src> 加载的脚本（file:// 下 fetch 会被 CORS 拦），
而 CLI（Python）直接读 questions.json。为避免两端各自维护一份数据导致漂移，
本仓库以根目录 questions.json 为唯一数据源：
    · CLI   → 直接读 questions.json
    · 网页  → 读本脚本生成的 questions.js（window.RISK_PACK = {...};）

用法:
    python scripts/build_questions.py            # 重新生成 questions.js
    python scripts/build_questions.py --check    # 仅校验产物是否与源一致（CI 用，不写盘）
"""

import argparse
import json
import os
import sys

# Windows 的 stdout/stderr 默认跟随本地 ANSI 代码页（CI 的 windows-latest 为 cp1252），
# 直接输出中文会抛 UnicodeEncodeError（曾导致 Windows 上该步骤失败）。显式切到 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "questions.json")
OUT = os.path.join(ROOT, "questions.js")

REQUIRED_DETECT = {None, "ip_type", "ip_region", "env_consistency"}


def load_pack(path=SRC):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate(pack):
    """对数据源做结构性校验，任何不符合抛出 ValueError。"""
    errs = []
    for key in ("version", "title", "disclaimer", "levels", "sources", "dimensions", "questions"):
        if key not in pack:
            errs.append("缺少顶层字段: %s" % key)
    if errs:
        raise ValueError("; ".join(errs))

    dim_ids = []
    total_weight = 0
    for d in pack["dimensions"]:
        for k in ("id", "name", "weight", "basis"):
            if k not in d:
                errs.append("维度 %s 缺少字段 %s" % (d.get("id"), k))
        dim_ids.append(d["id"])
        total_weight += d["weight"]
    if total_weight != 100:
        errs.append("维度权重之和应为 100，实际 %s" % total_weight)
    if len(set(dim_ids)) != len(dim_ids):
        errs.append("维度 id 重复")

    for lv in pack["levels"]:
        for k in ("id", "max", "name", "color", "bg", "lead", "note"):
            if k not in lv:
                errs.append("等级 %s 缺少字段 %s" % (lv.get("id"), k))
    # 等级阈值必须严格递增，最后一档需覆盖 100
    maxes = [lv["max"] for lv in pack["levels"]]
    if maxes != sorted(maxes) or len(set(maxes)) != len(maxes):
        errs.append("等级 max 必须严格递增")
    if maxes[-1] < 101:
        errs.append("最高等级 max 需 ≥ 101 以覆盖 100 分")

    q_ids = []
    for q in pack["questions"]:
        for k in ("id", "dim", "text", "detect", "options"):
            if k not in q:
                errs.append("题目 %s 缺少字段 %s" % (q.get("id"), k))
        if q["dim"] not in dim_ids:
            errs.append("题目 %s 的维度 %s 不存在" % (q["id"], q["dim"]))
        if q["detect"] not in REQUIRED_DETECT:
            errs.append("题目 %s 的 detect 非法: %r" % (q["id"], q["detect"]))
        if len(q["options"]) < 2:
            errs.append("题目 %s 选项不足" % q["id"])
        q_ids.append(q["id"])
        for op in q["options"]:
            for k in ("label", "risk", "advice", "source", "confidence"):
                if k not in op:
                    errs.append("题目 %s 选项缺少字段 %s" % (q["id"], k))
            if not (isinstance(op["risk"], (int, float)) and 0 <= op["risk"] <= 1):
                errs.append("题目 %s 选项 risk 需在 0~1" % q["id"])
            if op.get("source") not in pack["sources"]:
                errs.append("题目 %s 选项 source=%r 未在 sources 中定义" % (q["id"], op.get("source")))
            if op.get("confidence") not in ("high", "medium", "low"):
                errs.append("题目 %s 选项 confidence 非法" % q["id"])
    if len(set(q_ids)) != len(q_ids):
        errs.append("题目 id 重复")

    if errs:
        raise ValueError("questions.json 校验失败:\n  - " + "\n  - ".join(errs))


def render(pack):
    """生成 questions.js 文本（LF、UTF-8、无 BOM、确定性）。"""
    body = json.dumps(pack, ensure_ascii=False, indent=2)
    header = "/* 由 scripts/build_questions.py 从 questions.json 生成，请勿手改。*/\n"
    return header + "window.RISK_PACK = " + body + ";\n"


def build(check=False):
    pack = load_pack()
    validate(pack)
    text = render(pack)
    if check:
        if not os.path.exists(OUT):
            print("questions.js 不存在，请先运行 build", file=sys.stderr)
            return 1
        with open(OUT, "r", encoding="utf-8") as f:
            if f.read() != text:
                print("questions.js 与 questions.json 不一致，请重新运行 build", file=sys.stderr)
                return 1
        print("OK：questions.js 与 questions.json 一致（%d 题 / %d 维度）"
              % (len(pack["questions"]), len(pack["dimensions"])))
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("已生成 %s（%d 题 / %d 维度）"
          % (OUT, len(pack["questions"]), len(pack["dimensions"])))
    return 0


def main():
    ap = argparse.ArgumentParser(description="由 questions.json 生成 questions.js")
    ap.add_argument("--check", action="store_true", help="仅校验产物与源一致，不写盘")
    args = ap.parse_args()
    sys.exit(build(check=args.check))


if __name__ == "__main__":
    main()
