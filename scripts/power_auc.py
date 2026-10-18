#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
power_auc.py — 验证计划（docs/validation-plan.md §4）的样本量核算

回答的问题是：在给定「预期 AUC / 显著性水平 / 检验功效」下，「已封 / 未封」
两组各需要多少例，才能稳定地拒绝零假设（AUC = 0.5，即工具无区分力）。

方法：Hanley–McNeil AUC 方差 + 正态近似
    SE(A) = sqrt( [A(1-A) + (n1-1)(Q1-A²) + (n2-1)(Q2-A²)] / (n1·n2) )
    Q1 = A/(2-A)，Q2 = 2A²/(1+A)
    功效条件：(A1 - 0.5) / SE(A1) - z_{α/2} >= z_β

注意：SE 本身依赖 n，故用二分搜索求最小满足功效的 n，而非套一个闭合公式。
纯标准库实现（statistics.NormalDist 提供正态分位点）。

用法:
    python scripts/power_auc.py                              # AUC=0.65, α=.05, power=.80
    python scripts/power_auc.py --auc 0.70 --power 0.90 --ratio 1.5
    python scripts/power_auc.py --table                       # 打印常用参数对照表
"""

import argparse
import math
import sys
from statistics import NormalDist

_NORM = NormalDist()


def auc_se(auc, n_pos, n_neg):
    """Hanley–McNeil 的 AUC 标准误（正态近似）。"""
    a = float(auc)
    q1 = a / (2.0 - a)
    q2 = 2.0 * a * a / (1.0 + a)
    var = (a * (1.0 - a)
           + (n_pos - 1) * (q1 - a * a)
           + (n_neg - 1) * (q2 - a * a)) / (n_pos * n_neg)
    return math.sqrt(max(var, 1e-12))


def achieved_power(auc, n_pos, n_neg, alpha=0.05):
    """在给定样本量下，拒绝 H0（AUC=0.5）的检验功效。"""
    z = (auc - 0.5) / auc_se(auc, n_pos, n_neg) - _NORM.inv_cdf(1 - alpha / 2.0)
    return _NORM.cdf(z)


def required_n(auc, alpha=0.05, power=0.80, ratio=1.0, max_n=10_000_000):
    """求每组（阳性组）所需最小样本量。ratio = n_neg / n_pos。

    返回 (n_pos, n_neg, 实际功效)。
    """
    if not (0.5 < auc < 1.0):
        raise ValueError("预期 AUC 必须落在 (0.5, 1.0) 区间，当前: %s" % auc)
    if not (0 < ratio):
        raise ValueError("ratio 必须为正数")
    z_beta = _NORM.inv_cdf(power)

    def ok(n_pos):
        n_neg = max(1, int(round(n_pos * ratio)))
        z = (auc - 0.5) / auc_se(auc, n_pos, n_neg) - _NORM.inv_cdf(1 - alpha / 2.0)
        return z >= z_beta

    hi = 16
    while not ok(hi):
        hi *= 2
        if hi > max_n:
            raise ValueError("在 max_n=%d 内找不到满足功效的样本量" % max_n)
    lo = 1
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid + 1
    n_pos = lo
    n_neg = max(1, int(round(n_pos * ratio)))
    return n_pos, n_neg, achieved_power(auc, n_pos, n_neg, alpha)


def ci_half_width(auc, n_pos, n_neg, alpha=0.05):
    """该样本量下 AUC 的正态近似 95% 置信区间半宽。"""
    return _NORM.inv_cdf(1 - alpha / 2.0) * auc_se(auc, n_pos, n_neg)


def report(auc, alpha, power, ratio):
    n_pos, n_neg, pw = required_n(auc, alpha, power, ratio)
    hw = ci_half_width(auc, n_pos, n_neg, alpha)
    print("预期 AUC          : %.2f" % auc)
    print("显著性水平 α      : %.3f（双侧）" % alpha)
    print("目标功效 1-β      : %.2f" % power)
    print("阴性/阳性 比例    : %.2f" % ratio)
    print("-" * 44)
    print("所需阳性（已封）样本 : %d" % n_pos)
    print("所需阴性（未封）样本 : %d" % n_neg)
    print("合计                 : %d" % (n_pos + n_neg))
    print("该样本量实际功效     : %.3f" % pw)
    print("AUC 的 %.0f%% CI 半宽  : ±%.3f"
          % ((1 - alpha) * 100, hw))
    print()
    print("说明：正态近似估算，落地前请结合真实正负比例复核；"
          "若结果对样本量高度敏感，建议按更保守（更大）的规模采集。")


def table(alpha, power):
    print("α=%.3f, 1-β=%.2f, ratio=1.0 时的每组样本量：" % (alpha, power))
    print("%-10s %-12s %-12s" % ("预期AUC", "每组n", "合计"))
    print("-" * 36)
    for auc in (0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        n_pos, _, _ = required_n(auc, alpha, power, 1.0)
        print("%-10.2f %-12d %-12d" % (auc, n_pos, n_pos * 2))


def main():
    ap = argparse.ArgumentParser(
        description="AUC 检验的样本量核算（Hanley–McNeil）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python scripts/power_auc.py --auc 0.65 --power 0.8",
    )
    ap.add_argument("--auc", type=float, default=0.65, help="预期（备择）AUC，须 >0.5（默认 0.65）")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平，默认 0.05（双侧）")
    ap.add_argument("--power", type=float, default=0.80, help="目标检验功效，默认 0.80")
    ap.add_argument("--ratio", type=float, default=1.0, help="阴性/阳性 样本比例，默认 1.0")
    ap.add_argument("--table", action="store_true", help="打印常用参数对照表")
    args = ap.parse_args()

    if args.table:
        table(args.alpha, args.power)
    else:
        report(args.auc, args.alpha, args.power, args.ratio)


if __name__ == "__main__":
    sys.exit(main())
