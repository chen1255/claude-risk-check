#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude 账号风控自检（CLI 版）

与网页版使用同一套维度、权重与评分模型，数据同源（根目录 questions.json）：
    每个维度 = 该维度问题风险值(0~1)的平均
    总分     = Σ 维度权重(百分比) × 维度平均风险   → 0~100

用法:
    python claude_risk_check.py                # 交互式作答
    python claude_risk_check.py --auto         # 先尝试自动探测出口 IP / 语言时区，再作答
    python claude_risk_check.py --json         # 作答后额外输出 JSON 结果
    python claude_risk_check.py --no-color     # 关闭 ANSI 颜色
    python claude_risk_check.py --help

说明: Anthropic 未公开“满足某几条即封号”的官方规则。本工具基于社区大量封号案例
与 Anthropic 公开 Safeguards 文档归纳，仅供自查参考，不代表对封号结果的预测，
也不构成规避平台规则的保证。
"""

import argparse
import json
import math
import os
import sys

from probe import detect_answers  # 纯逻辑 + 可选 I/O；无网络时自动降级

# 数据源路径：与脚本同目录的 questions.json（install.ps1 会一并复制到安装目录）
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json")

# ---------- 中文 Windows 终端 UTF-8 兼容 ----------
# 注意：不再调用 `chcp 65001`——它会永久改变调用方终端的代码页（副作用）。
# 仅重配置本进程的 stdout/stdin 编码，退出后不影响外部环境。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------- 数据模型（唯一来源：questions.json） ----------
def load_pack(path=DATA_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


PACK = load_pack()
LEVELS = PACK["levels"]
DIMENSIONS = PACK["dimensions"]
# 统一成 (label, risk, advice) 三元组，便于既有逻辑使用
QUESTIONS = [
    {
        "id": q["id"],
        "dim": q["dim"],
        "text": q["text"],
        "detect": q["detect"],
        "options": [(o["label"], o["risk"], o["advice"]) for o in q["options"]],
    }
    for q in PACK["questions"]
]

# 等级 id → 终端颜色名
ANSI_BY_LEVEL = {"low": "green", "mid": "yellow", "elevated": "orange", "high": "red"}


# ---------- 颜色 ----------
class C:
    def __init__(self, enabled):
        self.enabled = enabled

    def _w(self, code, s):
        return f"\033[{code}m{s}\033[0m" if self.enabled else s

    def bold(self, s):    return self._w("1", s)
    def dim(self, s):     return self._w("2", s)
    def red(self, s):     return self._w("31", s)
    def green(self, s):   return self._w("32", s)
    def yellow(self, s):  return self._w("33", s)
    def orange(self, s):  return self._w("38;5;208", s)
    def accent(self, s):  return self._w("38;5;209", s)


# ---------- 评分模型 ----------
def _round_half_up(x):
    """与 JS Math.round 一致的“四舍五入”，避免 Python round() 的银行家舍入导致双端不一致。"""
    return int(math.floor(x + 0.5))


def compute_raw(answers):
    """返回未取整的总分与各维度明细。answers: {qid: option_index}"""
    dim_scores = {d["id"]: {"sum": 0.0, "n": 0} for d in DIMENSIONS}
    for q in QUESTIONS:
        oi = answers.get(q["id"])
        if oi is None:
            continue
        risk = q["options"][oi][1]
        dim_scores[q["dim"]]["sum"] += risk
        dim_scores[q["dim"]]["n"] += 1

    total = 0.0
    rows = []
    for d in DIMENSIONS:
        s = dim_scores[d["id"]]
        avg = (s["sum"] / s["n"]) if s["n"] else 0.0
        contrib = avg * d["weight"]
        total += contrib
        rows.append({"id": d["id"], "name": d["name"], "weight": d["weight"],
                     "risk": avg, "contrib": contrib})
    return total, rows


def compute(answers):
    """answers: {qid: option_index} → (总分 0~100, 维度明细)"""
    total, rows = compute_raw(answers)
    return _round_half_up(total), rows


def level_of(score):
    """按 questions.json 的 levels 阈值取等级。返回 dict。"""
    for lv in LEVELS:
        if score < lv["max"]:
            return lv
    return LEVELS[-1]


def advice_list(answers):
    items = []
    for q in QUESTIONS:
        oi = answers.get(q["id"])
        if oi is None:
            continue
        label, risk, adv = q["options"][oi]
        if risk <= 0 or not adv:
            continue
        dim = next(d for d in DIMENSIONS if d["id"] == q["dim"])
        items.append({
            "dim": dim["name"], "label": label, "text": adv,
            "risk": risk, "score": dim["weight"] * risk,
        })
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def sev_of(risk):
    if risk >= 0.7:
        return "重点", "red"
    if risk >= 0.4:
        return "建议", "orange"
    return "提示", "yellow"


def bar(risk, width=18):
    filled = _round_half_up(risk * width)
    return "#" * filled + "-" * (width - filled)


# ---------- 交互 ----------
def ask_quiz(presets=None):
    """presets: {qid: option_index} 由自动探测预填，可被用户覆盖。"""
    answers = dict(presets or {})
    i = 0
    total = len(QUESTIONS)
    while i < total:
        q = QUESTIONS[i]
        dim = next(d for d in DIMENSIONS if d["id"] == q["dim"])
        print()
        print(f"[{i + 1}/{total}] {dim['name']} · {q['text']}")
        for oi, (label, risk, _adv) in enumerate(q["options"], start=1):
            mark = "  ← 自动探测建议" if answers.get(q["id"]) == oi - 1 else ""
            print(f"    {oi}) {label}{mark}")
        default = answers.get(q["id"])
        hint = f"（回车采用探测建议 {default + 1}）" if default is not None else ""
        prompt = f"    选择 (数字 ; b=上一题 ; q=退出) {hint}> "
        while True:
            try:
                raw = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n已退出。")
                sys.exit(0)
            if raw == "" and default is not None:
                i += 1
                break
            if raw.lower() in ("q", "quit", "exit"):
                print("已退出。")
                sys.exit(0)
            if raw.lower() == "b":
                if i > 0:
                    i -= 1
                    answers.pop(QUESTIONS[i]["id"], None)
                break
            if raw.isdigit() and 1 <= int(raw) <= len(q["options"]):
                answers[q["id"]] = int(raw) - 1
                i += 1
                break
            print("    输入无效，请输入选项数字，或 b / q。")
    return answers


def print_report(answers, color=True):
    c = C(color)
    score, rows = compute(answers)
    lv = level_of(score)
    ansi = {"green": c.green, "yellow": c.yellow, "orange": c.orange, "red": c.red}[
        ANSI_BY_LEVEL.get(lv["id"], "red")]

    line = "=" * 58
    print()
    print(c.accent(line))
    print(c.bold("  Claude 账号风控自检报告"))
    print(c.accent(line))
    print()
    print(f"  综合风险分：{c.bold(ansi(str(score)))} / 100    评估等级：{ansi(lv['name'])}")
    print(f"  {c.bold(lv['lead'])}")
    print(f"  {c.dim(lv['note'])}")
    print()

    print(c.bold("  各维度风险分布"))
    for r in rows:
        pct = _round_half_up(r["risk"] * 100)
        col = c.green if pct < 20 else c.yellow if pct < 45 else c.orange if pct < 70 else c.red
        print(f"    {r['name']:<10} [{col(bar(r['risk']))}] {pct:>3}%  (权重 {r['weight']})")
    print()

    items = advice_list(answers)
    print(c.bold("  需要调整的方面（按影响优先级排序）"))
    if not items:
        print("    没有发现需要调整的高风险项，当前各项均处于较安全区间。")
    else:
        for it in items:
            sev, cname = sev_of(it["risk"])
            tag = {"red": c.red, "orange": c.orange, "yellow": c.yellow}[cname](f"[{sev}]")
            print(f"    {tag} {c.bold(it['dim'] + '：' + it['label'])}")
            print(f"          {it['text']}")
    print()
    print(c.dim("  说明：本结果基于社区封号案例与 Anthropic 公开文档归纳，仅供自查参考，"))
    print(c.dim("  不代表对封号结果的预测，也不构成规避平台规则的保证。"))
    print()
    return {"score": score, "level": lv["name"], "levelId": lv["id"],
            "dimensions": rows, "advice": items}


def main():
    ap = argparse.ArgumentParser(
        description="Claude 账号风控自检（CLI）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python claude_risk_check.py --auto --json",
    )
    ap.add_argument("--json", action="store_true", help="作答后额外输出 JSON 结果")
    ap.add_argument("--no-color", action="store_true", help="关闭 ANSI 颜色")
    ap.add_argument("--auto", action="store_true",
                    help="先尝试自动探测出口 IP / 系统语言时区，作为作答建议（无网络则跳过）")
    args = ap.parse_args()

    c = C(not args.no_color)
    print()
    print(c.bold("Claude 账号风控自检"))
    print(c.dim("共 %d 题，涵盖 %d 个维度。输入选项数字作答；b 回上一题；q 退出。"
                % (len(QUESTIONS), len(DIMENSIONS))))
    print(c.dim("提示：以下基于社区案例与公开文档归纳，仅供参考。"))

    presets = {}
    if args.auto:
        print(c.dim("正在尝试自动探测（超时 4 秒，失败则跳过）..."))
        presets, notes = detect_answers(timeout=4.0)
        if presets:
            for qid, oi in presets.items():
                q = next(q for q in QUESTIONS if q["id"] == qid)
                print(c.accent(f"  · {qid} 建议：{q['options'][oi][0]}"))
        for n in notes:
            print(c.dim("  · " + n))

    answers = ask_quiz(presets=presets)
    result = print_report(answers, color=not args.no_color)

    if args.json:
        payload = dict(result)
        payload["answers"] = {q["id"]: q["options"][answers[q["id"]]][0]
                               for q in QUESTIONS if q["id"] in answers}
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
