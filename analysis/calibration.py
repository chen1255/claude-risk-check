#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibration.py — 验证计划（docs/validation-plan.md §5）的校准分析

回答的问题是：claude-risk-check 的分数**是否被校准**——即「给了多少分，
实际就有多少比例被封」，还是系统性高估 / 低估。

  1. 分箱可靠性：分数段 0–17 / 18–39 / 40–64 / 65–100 的
     「平均预测风险（分数/100）」vs「实际封号率」→ reliability diagram 数据
  2. Brier score，并与「常数基线（总封号率）」比较，给出 Brier Skill Score
  3. Brier 分解：可靠性 / 分辨率 / 不确定性（Murphy 分解）
  4. 单调性：分数 vs 标签的 Spearman ρ（与 auc.py 共用实现）

说明：本工具并不输出「封号概率」，这里把 0–100 分线性映射为 0–1 的名义概率
（p = 分数/100）来做校准评估——这是对分数的**解释性**校准，不等于工具声称预测概率。

铁律：分数一律来自 claude_risk_check.compute（经 score_from_dataset.load_dataset）。

用法:
    python analysis/calibration.py data/pilot.csv
    python analysis/calibration.py data/pilot.csv --json --out calib.json
"""

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import claude_risk_check as model            # noqa: E402
import score_from_dataset as sfd             # noqa: E402
import auc as aucmod                         # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _safe_div(a, b):
    return None if not b else a / float(b)


def reliability_bins(scores, labels):
    """按分数段（与等级阈值同源）汇总「平均预测风险 vs 实际封号率」。"""
    out = []
    for lo, hi, lv in aucmod.SEGMENTS:
        idx = [i for i, s in enumerate(scores) if lo <= s < hi]
        n = len(idx)
        pred = _safe_div(sum(scores[i] for i in idx), n * 100.0)
        obs = _safe_div(sum(labels[i] for i in idx), n)
        out.append({
            "levelId": lv["id"], "level": lv["name"], "lo": lo, "hi": hi - 1,
            "n": n, "mean_predicted": pred, "observed": obs,
            "gap": (None if pred is None or obs is None else pred - obs),
        })
    return out


def brier_score(scores, labels):
    """Brier score：mean((p - y)^2)，p = 分数/100。"""
    n = len(scores)
    if n == 0:
        return None
    return sum((s / 100.0 - l) ** 2 for s, l in zip(scores, labels)) / n


def baseline_brier(labels):
    """常数基线：一律预测总封号率时的 Brier score。"""
    n = len(labels)
    if n == 0:
        return None
    p = sum(labels) / n
    return sum((p - l) ** 2 for l in labels) / n


def brier_skill_score(bs, bs_base):
    """Brier Skill Score = 1 − BS/BS_base；>0 表示优于常数基线。"""
    if bs is None or bs_base in (None, 0):
        return None
    return 1.0 - bs / bs_base


def decompose(bins, labels):
    """Murphy 分解：BS = 可靠性 − 分辨率 + 不确定性。"""
    n = len(labels)
    if n == 0:
        return None
    base = sum(labels) / n
    reliability = 0.0
    resolution = 0.0
    for b in bins:
        if not b["n"]:
            continue
        frac = b["n"] / n
        reliability += frac * (b["mean_predicted"] - b["observed"]) ** 2
        resolution += frac * (b["observed"] - base) ** 2
    return {
        "reliability": reliability, "resolution": resolution,
        "uncertainty": base * (1.0 - base),
    }


def analyze(records, meta):
    labelled = [r for r in records if r["label"] is not None]
    scores = [r["score"] for r in labelled]
    labels = [r["label"] for r in labelled]

    result = {
        "meta": meta,
        "nLabelled": len(labelled),
        "nBanned": sum(1 for l in labels if l == 1),
        "nSurvived": sum(1 for l in labels if l == 0),
    }
    if not scores or result["nBanned"] == 0 or result["nSurvived"] == 0:
        result["error"] = "缺少标签或单类缺失，无法做校准分析"
        return result

    bins = reliability_bins(scores, labels)
    bs = brier_score(scores, labels)
    bs_base = baseline_brier(labels)
    result["baseRate"] = sum(labels) / len(labels)
    result["bins"] = bins
    result["brier"] = bs
    result["brierBaseline"] = bs_base
    result["brierSkillScore"] = brier_skill_score(bs, bs_base)
    result["decomposition"] = decompose(bins, labels)
    result["monotonicity"] = aucmod.spearman_test(scores, labels)
    return result


def _round_floats(obj, nd=4):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: _round_floats(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, nd) for v in obj]
    return obj


def _fmt(x, nd=4):
    return "—" if x is None else ("%%.%df" % nd) % x


def print_report(res):
    print("数据集：%s" % res["meta"]["csv"])
    if "error" in res:
        print("!! %s" % res["error"])
        return
    print("样本：已封 %d / 未封 %d（合计 %d），总封号率 %.1f%%"
          % (res["nBanned"], res["nSurvived"], res["nLabelled"], res["baseRate"] * 100))
    print()
    print("【Reliability diagram 数据】（预测 = 分数/100）")
    print("  %-8s %-10s %-6s %-12s %-12s %-10s"
          % ("等级", "分数段", "n", "平均预测", "实际封号率", "偏差"))
    for b in res["bins"]:
        seg = "%d–%d" % (b["lo"], b["hi"])
        print("  %-8s %-10s %-6d %-12s %-12s %-10s"
              % (b["level"], seg, b["n"],
                 _fmt(b["mean_predicted"], 3),
                 "—" if b["observed"] is None else "%.3f" % b["observed"],
                 _fmt(b["gap"], 3)))
    print()
    print("【Brier 校准】")
    print("  Brier score        = %s" % _fmt(res["brier"]))
    print("  常数基线 Brier     = %s" % _fmt(res["brierBaseline"]))
    print("  Brier Skill Score  = %s（>0 优于基线）" % _fmt(res["brierSkillScore"]))
    dec = res["decomposition"]
    if dec:
        print("  Murphy 分解：可靠性 %s − 分辨率 %s + 不确定性 %s"
              % (_fmt(dec["reliability"]), _fmt(dec["resolution"]), _fmt(dec["uncertainty"])))
    print()
    mono = res["monotonicity"]
    print("【单调性】Spearman ρ = %s（p = %s, n = %d）"
          % (_fmt(mono["rho"], 3), _fmt(mono["p"], 4), mono["n"]))
    print()
    print("提醒：若「偏差」列基本为负，说明分数系统性高估实际封号率；为正则低估。")
    print("      校准评估须与 docs/validation-plan.md 的主分析一并解读。")


def main():
    ap = argparse.ArgumentParser(
        description="claude-risk-check 校准分析（reliability / Brier / 单调性）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python analysis/calibration.py data/pilot.csv --json",
    )
    ap.add_argument("csv_path", help="输入数据集 CSV 路径")
    ap.add_argument("--allow-partial", action="store_true", help="允许答案不全（默认跳过不完整样本）")
    ap.add_argument("--out", help="把完整结果 JSON 写入文件")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出到 stdout")
    args = ap.parse_args()

    records, meta = sfd.load_dataset(args.csv_path, allow_partial=args.allow_partial)
    result = _round_floats(analyze(records, meta))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print_report(result)
    if args.out:
        print("完整结果已写入：%s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
