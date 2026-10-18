#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude 账号风控自检（CLI 版）

与 index.html 使用同一套维度、权重与评分模型：
    每个维度 = 该维度问题风险值(0~1)的平均
    总分     = Σ 维度权重(百分比) × 维度平均风险   → 0~100

用法:
    python claude_risk_check.py            # 交互式作答
    python claude_risk_check.py --json     # 作答后额外输出 JSON 结果
    python claude_risk_check.py --no-color # 关闭 ANSI 颜色
    python claude_risk_check.py --help

说明: Anthropic 未公开“满足某几条即封号”的官方规则。本工具基于社区大量封号案例
与 Anthropic 公开 Safeguards 文档归纳，仅供自查参考，不代表对封号结果的预测，
也不构成规避平台规则的保证。
"""

import argparse
import json
import os
import sys

# ---------- 中文 Windows 终端 UTF-8 兼容 ----------
if os.name == "nt":
    os.system("chcp 65001 >nul 2>&1")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------- 数据模型 ----------
DIMENSIONS = [
    {"id": "network",     "name": "网络环境",       "weight": 25},
    {"id": "behavior",    "name": "使用行为模式",   "weight": 20},
    {"id": "accountAge",  "name": "账号年龄与养号", "weight": 15},
    {"id": "sharing",     "name": "账号共享",       "weight": 15},
    {"id": "fingerprint", "name": "环境指纹",       "weight": 10},
    {"id": "channel",     "name": "接入通道",       "weight": 5},
    {"id": "payment",     "name": "支付与订阅",     "weight": 5},
    {"id": "identity",    "name": "邮箱与验证",     "weight": 5},
]

# options: (选项文案, 风险值 0~1, 建议文案)
QUESTIONS = [
    # 网络环境
    {"id": "q1", "dim": "network", "text": "你使用 Claude 时的出口 IP 属于哪一类？", "options": [
        ("家庭 / 住宅 IP（宽带原生 IP）", 0, ""),
        ("不确定，没查过", 0.4, "用 ping0.cc/ip/ 等工具自查：显示“家庭 IP”较安全，显示“IDC 机房”需尽快更换。"),
        ("IDC 机房 / VPS / 云服务器 IP", 0.9, "机房 IP 是封号的头号原因之一，请更换为家庭/住宅 IP 出口。"),
        ("公共共享代理 / 机场“万人骑”节点", 1.0, "共享出口背后常挂着自动化与批量注册流量，务必换成独立、干净的住宅 IP。"),
    ]},
    {"id": "q2", "dim": "network", "text": "最近一个月，你的出口地区是否稳定？", "options": [
        ("长期固定同一地区（国家/城市基本不变）", 0, ""),
        ("偶尔切换，但基本在同一国家内", 0.35, "尽量固定单一地区，减少跨区跳变。"),
        ("频繁跨地区甚至跨国家切换（一天内多个国家）", 1.0, "登录 IP 频繁跨区/跨国是高风险信号，请把出口固定到一个受支持地区。"),
    ]},
    {"id": "q3", "dim": "network", "text": "你的常驻出口地区是否在 Anthropic 官方支持区域内？", "options": [
        ("是（如美国、英国、日本等支持区）", 0, ""),
        ("不确定", 0.5, "对照 Anthropic Supported Countries 列表，确认常驻出口在支持区域内。"),
        ("否 / 在不支持区域", 1.0, "服务条款不覆盖不支持区域，长期使用存在合规风险；建议改用支持区域的稳定出口。"),
    ]},
    # 使用行为模式
    {"id": "q4", "dim": "behavior", "text": "你的使用时段是否有正常作息？", "options": [
        ("每天有正常活跃与休息间隔", 0, ""),
        ("偶尔通宵 / 连续长时间使用", 0.4, "避免长时间不间断高负载，模拟真实用户作息。"),
        ("24 小时持续高负载，基本无作息", 1.0, "人不会 24 小时不断使用，bot 才会；请给账号留出明显的休息间隔。"),
    ]},
    {"id": "q5", "dim": "behavior", "text": "是否会跑自动化脚本 / 批量调用？", "options": [
        ("从不", 0, ""),
        ("极少量、定向的脚本", 0.4, "把自动化频率压到最低，尽量以交互式使用为主。"),
        ("频繁自动化 / 批量调用", 1.0, "批量自动化是典型的商业级滥用特征，建议改为低频、交互式使用。"),
    ]},
    {"id": "q6", "dim": "behavior", "text": "单账号的用量强度大致如何？", "options": [
        ("轻度日常对话 / 写作", 0, ""),
        ("中等，日常开发辅助", 0.3, "保持强度平稳，避免长时间占满配额。"),
        ("重度，长时间连续跑开发任务", 0.7, "控制单次连续任务时长与并发，避免长时间挂机跑 agent。"),
        ("长时间挂机跑 agent / 无人值守连续任务", 1.0, "无人值守长跑 agent 风险高，建议缩短单次任务并保留人工介入。"),
    ]},
    # 账号年龄与养号
    {"id": "q7", "dim": "accountAge", "text": "账号注册至今多久了？", "options": [
        ("3 个月以上", 0, ""),
        ("1–3 个月", 0.25, "账号已较稳定，但仍避免突然拉高负载。"),
        ("2 周 – 1 个月", 0.6, "仍在养号期，避免高频高负载，逐步建立正常使用记录。"),
        ("不满 2 周", 1.0, "新号风险最高：前两周建议只走网页版、低强度使用，别碰 CLI 与自动化。"),
    ]},
    {"id": "q8", "dim": "accountAge", "text": "注册后多久就充值升级了？", "options": [
        ("先免费用了 1 周以上才升级", 0, ""),
        ("用了几天就升级", 0.3, "稍微延后升级节奏，让账号先积累正常的免费使用记录。"),
        ("注册当天或次日就充值", 0.8, "新号立刻充值易被标记为“测试号”，建议先免费使用一段时间再升级。"),
        ("新号直接上最高档（Max 等）", 1.0, "一上来就最高档，画像不像真实用户；建议从低档起步、自然升级。"),
    ]},
    {"id": "q9", "dim": "accountAge", "text": "升级后短期内触发用量上限的次数？", "options": [
        ("0–1 次", 0, ""),
        ("2 次", 0.4, "控制触发限额的频率，给账号留出“克制使用”的画像。"),
        ("3 次以上", 0.8, "频繁打满限额易被判为滥用，建议错峰使用、控制强度。"),
        ("经常持续打满", 1.0, "长期持续打满限额风险很高，建议降低强度或选择合适的方案档位。"),
    ]},
    # 账号共享
    {"id": "q10", "dim": "sharing", "text": "账号的使用者与设备情况？", "options": [
        ("仅自己，主要在固定一台设备", 0, ""),
        ("自己多设备（手机 + 电脑）", 0.3, "多设备本身问题不大，但请保持同一个稳定出口。"),
        ("偶尔借给他人使用", 0.7, "尽量停止共享：任何异地登录都可能触发风控。"),
        ("多人多地同时使用（拼车/共享号）", 1.0, "共享账号是高频封号触发器（异地/多人登录），务必一人一号。"),
    ]},
    # 环境指纹
    {"id": "q11", "dim": "fingerprint", "text": "系统语言 / 时区与出口地区是否一致？", "options": [
        ("英文语言 + 时区与出口地区一致", 0, ""),
        ("部分一致（改了一部分）", 0.4, "尽量让系统语言、时区与出口地区自洽，减少画像矛盾。"),
        ("简体中文 + UTC+8，但 IP 在海外", 0.8, "语言/时区与 IP 矛盾会强化地区画像，建议调整为英文 + 匹配时区。"),
        ("完全没调整过", 1.0, "统一环境：出口地区、系统语言、时区、浏览器语言尽量彼此自洽。"),
    ]},
    {"id": "q12", "dim": "fingerprint", "text": "若曾被封号，换号前是否清理了环境残留？", "options": [
        ("没有封号经历", 0, ""),
        ("清理过（卸载 / 清缓存 / 换隔离环境）", 0.2, ""),
        ("未清理就直接换号", 1.0, "换号前务必彻底清理 Claude 相关文件与浏览器指纹，否则新号可能被快速关联。"),
    ]},
    # 接入通道
    {"id": "q13", "dim": "channel", "text": "新号阶段主要通过什么方式接入 Claude？", "options": [
        ("老号，随意使用（已过养号期）", 0, ""),
        ("新号，只用网页版 claude.ai", 0.2, "新号前两周保持网页版为主，暂缓 CLI 与第三方客户端。"),
        ("新号直接用 CLI（Claude Code 等）", 0.7, "CLI 走开发者通道、调用频次偏高，新号上来就高频容易亮红灯。"),
        ("新号频繁使用第三方 / 逆向客户端", 1.0, "新号经不起非常规调用的折腾，先远离第三方客户端。"),
    ]},
    # 支付与订阅
    {"id": "q14", "dim": "payment", "text": "你的订阅 / 支付方式是？", "options": [
        ("海外信用卡或合规虚拟卡", 0, ""),
        ("Apple / Google 平台级订阅", 0.2, "平台级订阅相对友好，保留好可申诉退款的凭证。"),
        ("第三方代充 / 共享车", 0.4, "选择“封号可退款”的渠道，并提前确认退款比例与流程。"),
        ("直接绑定中国大陆发行的银行卡", 1.0, "国内卡大概率被支付通道风控拦截，建议改用海外卡或平台订阅。"),
    ]},
    # 邮箱与验证
    {"id": "q15", "dim": "identity", "text": "注册用的邮箱类型？", "options": [
        ("老 Google 邮箱（注册 1–2 年以上）", 0, ""),
        ("较新的 Google / ProtonMail", 0.3, "邮箱尚可，注意让注册与常用环境保持稳定一致。"),
        ("免费邮箱 / 企业邮箱", 0.6, "部分免费/企业邮箱更易被标记，建议换更干净的私人邮箱。"),
        ("一次性 / 来源可疑的邮箱", 1.0, "可疑邮箱会拉高账号初始风险，建议更换。"),
    ]},
    {"id": "q16", "dim": "identity", "text": "注册验证手机号的地区？", "options": [
        ("美区 / 英区号码", 0, ""),
        ("其他欧美地区", 0.3, "尽量使用美区/英区号码，通过率更高。"),
        ("印度 / 东南亚号码", 0.7, "这类号码验证失败率与风控标记概率更高，建议换美区/英区。"),
        ("国内 +86 号码", 1.0, "避免使用 +86 号码，容易被关联到风险池。"),
    ]},
]


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
def compute(answers):
    """answers: {qid: option_index}"""
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
    return round(total), rows


def level_of(score):
    if score < 18:
        return "低风险", "green", "当前环境较为干净", "整体画像接近正常用户，继续保持“干净、稳定、一致”即可。"
    if score < 40:
        return "中等风险", "yellow", "存在若干可优化的风险点", "有几项已靠近风控敏感线，建议按清单逐项调整，尤其是高权重维度。"
    if score < 65:
        return "较高风险", "orange", "多项指标触碰风控敏感线", "当前环境同时出现多个高风险信号，被判定异常的概率明显升高，请尽快重点整改。"
    return "高风险", "red", "多项高危信号叠加", "网络、行为、账号年龄等关键维度同时存在高风险特征，建议先停用并重构环境再继续使用。"


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
    filled = int(round(risk * width))
    return "#" * filled + "-" * (width - filled)


# ---------- 交互 ----------
def ask_quiz():
    answers = {}
    i = 0
    total = len(QUESTIONS)
    while i < total:
        q = QUESTIONS[i]
        dim = next(d for d in DIMENSIONS if d["id"] == q["dim"])
        print()
        print(f"[{i + 1}/{total}] {dim['name']} · {q['text']}")
        for oi, (label, risk, _adv) in enumerate(q["options"], start=1):
            print(f"    {oi}) {label}")
        prompt = "    选择 (数字 ; b=上一题 ; q=退出) > "
        while True:
            try:
                raw = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n已退出。")
                sys.exit(0)
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
    name, color_name, lead, note = level_of(score)
    badge = {"green": c.green, "yellow": c.yellow, "orange": c.orange, "red": c.red}[color_name]

    line = "=" * 58
    print()
    print(c.accent(line))
    print(c.bold("  Claude 账号风控自检报告"))
    print(c.accent(line))
    print()
    print(f"  综合风险分：{c.bold(badge(str(score)))} / 100    评估等级：{badge(name)}")
    print(f"  {c.bold(lead)}")
    print(f"  {c.dim(note)}")
    print()

    print(c.bold("  各维度风险分布"))
    for r in rows:
        pct = int(round(r["risk"] * 100))
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
    return {"score": score, "level": name, "dimensions": rows, "advice": items}


def main():
    ap = argparse.ArgumentParser(
        description="Claude 账号风控自检（CLI）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python claude_risk_check.py --json",
    )
    ap.add_argument("--json", action="store_true", help="作答后额外输出 JSON 结果")
    ap.add_argument("--no-color", action="store_true", help="关闭 ANSI 颜色")
    args = ap.parse_args()

    c = C(not args.no_color)
    print()
    print(c.bold("Claude 账号风控自检"))
    print(c.dim("共 16 题，涵盖 8 个维度。输入选项数字作答；b 回上一题；q 退出。"))
    print(c.dim("提示：以下基于社区案例与公开文档归纳，仅供参考。"))

    answers = ask_quiz()
    result = print_report(answers, color=not args.no_color)

    if args.json:
        payload = dict(result)
        payload["answers"] = {q["id"]: q["options"][answers[q["id"]]][0] for q in QUESTIONS}
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
